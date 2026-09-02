import os
import re
from copy import deepcopy

from flask import Blueprint, current_app, g, jsonify, request, url_for

from db import db
from extensions import socketio
from models import GameRotationEvent, Player, PlayerGameAbsence
from blueprints.live_game_api import (
    _actual_rotation,
    _authorized_context,
    _broadcast_state,
    _current_alignment,
    _event,
    _player_id_by_name,
    _room_name,
    _validate_alignment,
    get_authoritative_live_state,
)

live_game_bulk_bp = Blueprint('live_game_bulk', __name__, url_prefix='/api/live-game')


def _allowed_positions(team):
    infield = ['P', 'C', '1B', '2B', '3B', 'SS']
    outfield = ['LF', 'LCF', 'RCF', 'RF'] if int(team.outfielder_count or 3) == 4 else ['LF', 'CF', 'RF']
    return infield + outfield


def _present_players(game, team_id):
    absent_ids = {
        row.player_id
        for row in db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team_id).all()
    }
    players = db.session.query(Player).filter_by(team_id=team_id).all()
    return [player for player in players if player.id not in absent_ids]


def _pitcher_status_blocks_change(summary):
    status = str((summary or {}).get('status') or '').lower()
    return any(term in status for term in (
        'rest', 'unavailable', 'ineligible', 'incomplete', 'restriction', 'verify'
    ))


def _missing_positions(alignment, allowed):
    return [pos for pos in allowed if not (alignment or {}).get(pos)]


def _current_sequence(game_id, team_id):
    last_event = db.session.query(GameRotationEvent).filter_by(
        game_id=game_id,
        team_id=team_id,
    ).order_by(GameRotationEvent.sequence.desc(), GameRotationEvent.id.desc()).first()
    return int(last_event.sequence or 0) if last_event else 0


def _stale_write_response(data, game, team):
    if data.get('base_sequence') in (None, ''):
        return None
    try:
        expected = int(data.get('base_sequence'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'The live-game version is invalid.'}), 400

    current = _current_sequence(game.id, team.id)
    if expected == current:
        return None

    _, actual_rotation, _ = _actual_rotation(game, team.id)
    alignment = _current_alignment(game, team.id, actual_rotation)
    return jsonify({
        'status': 'error',
        'code': 'stale_live_state',
        'message': 'Another coach changed the live game first. Review the updated field before saving.',
        'current_sequence': current,
        'current_inning': str(game.live_current_inning or '1'),
        'current_alignment': alignment,
    }), 409


def _event_dict(event):
    return {
        'id': event.id,
        'inning': str(event.inning),
        'sequence': int(event.sequence or 0),
        'event_type': event.event_type,
        'changed_by_user': event.changed_by_user,
        'before_alignment': deepcopy(event.before_alignment or {}),
        'after_alignment': deepcopy(event.after_alignment or {}),
        'old_pitcher_id': event.old_pitcher_id,
        'new_pitcher_id': event.new_pitcher_id,
        'reverted': bool(event.reverted),
    }


def _delta_payload(game, team, event, alignment):
    players = _present_players(game, team.id)
    assigned = {name for name in (alignment or {}).values() if name}
    bench = [
        {'id': player.id, 'name': player.name, 'number': getattr(player, 'number', None)}
        for player in players
        if player.name not in assigned
    ]
    return {
        'game_id': game.id,
        'current_inning': str(game.live_current_inning or event.inning or '1'),
        'current_alignment': deepcopy(alignment or {}),
        'current_pitcher': (alignment or {}).get('P'),
        'sequence': int(event.sequence or 0),
        'event': _event_dict(event),
        'bench': bench,
    }


def _release_request_write_lock():
    lock = getattr(g, 'coachboard_live_game_lock', None)
    if lock is None:
        return
    try:
        lock.release()
    finally:
        g.coachboard_live_game_lock = None


def _fast_success(game, team, event, alignment, *, prep_changed=False):
    delta = _delta_payload(game, team, event, alignment)
    _release_request_write_lock()
    room = _room_name(team.id, game.id)
    socketio.emit('live_game_delta', delta, room=room)
    if prep_changed:
        socketio.emit(
            'next_inning_prep_update',
            {'game_id': game.id, 'inning': str(game.live_current_inning or '1')},
            room=room,
        )
    return jsonify({'status': 'success', 'delta': delta})


def _validate_complete_alignment(proposed, game, team):
    if not isinstance(proposed, dict):
        return None, None, 'A complete defensive alignment is required.'

    allowed = _allowed_positions(team)
    unknown_positions = [pos for pos in proposed.keys() if pos not in allowed]
    if unknown_positions:
        return None, None, f'Invalid defensive position: {unknown_positions[0]}.'

    present_players = _present_players(game, team.id)
    present_names = {player.name for player in present_players}
    after = {}
    for pos in allowed:
        value = proposed.get(pos)
        if value:
            if value not in present_names:
                return None, None, f'{value} is not available for this game.'
            after[pos] = value

    missing = _missing_positions(after, allowed)
    if missing:
        return None, None, f"Finish the defense before saving. Missing: {', '.join(missing)}."

    valid, message = _validate_alignment(after, present_names)
    if not valid:
        return None, None, message
    return after, present_players, None


@live_game_bulk_bp.route('/<int:game_id>/complete-pitcher-change', methods=['POST'])
def complete_pitcher_change(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not game.is_live:
        return jsonify({'status': 'error', 'message': 'Game is not live.'}), 409

    data = request.get_json(silent=True) or {}
    stale = _stale_write_response(data, game, team)
    if stale:
        return stale

    try:
        new_pitcher_id = int(data.get('new_pitcher_id'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Select a valid incoming pitcher.'}), 400

    proposed = data.get('alignment')
    if not isinstance(proposed, dict):
        return jsonify({'status': 'error', 'message': 'Finish the defensive alignment before saving the pitching change.'}), 400

    allowed = _allowed_positions(team)
    unknown_positions = [pos for pos in proposed.keys() if pos not in allowed]
    if unknown_positions:
        return jsonify({'status': 'error', 'message': f'Invalid defensive position: {unknown_positions[0]}.'}), 400

    present_players = _present_players(game, team.id)
    present_by_id = {player.id: player for player in present_players}
    present_names = {player.name for player in present_players}
    new_pitcher = present_by_id.get(new_pitcher_id)
    if not new_pitcher:
        return jsonify({'status': 'error', 'message': 'Incoming pitcher is not available for this game.'}), 409

    _, actual_rotation, _ = _actual_rotation(game, team.id)
    before = _current_alignment(game, team.id, actual_rotation)
    if not before:
        return jsonify({'status': 'error', 'message': 'No current defensive alignment exists.'}), 409

    old_pitcher_name = before.get('P')
    if old_pitcher_name == new_pitcher.name:
        return jsonify({'status': 'error', 'message': 'That player is already pitching.'}), 409

    state = get_authoritative_live_state(game.id, team.id) or {}
    pitcher_summary = (state.get('pitch_count_summary') or {}).get(new_pitcher.name, {})
    if _pitcher_status_blocks_change(pitcher_summary):
        status = pitcher_summary.get('status') or 'not available'
        detail = pitcher_summary.get('status_detail') or pitcher_summary.get('next_available')
        message = f'{new_pitcher.name} cannot pitch right now: {status}.'
        if detail:
            message += f' {detail}'
        return jsonify({'status': 'error', 'message': message}), 409

    after = {}
    for pos in allowed:
        value = proposed.get(pos)
        if value:
            if value not in present_names:
                return jsonify({'status': 'error', 'message': f'{value} is not available for this game.'}), 409
            after[pos] = value

    if after.get('P') != new_pitcher.name:
        return jsonify({'status': 'error', 'message': f'{new_pitcher.name} must be assigned to P for this pitching change.'}), 409

    missing_positions = _missing_positions(after, allowed)
    if missing_positions:
        return jsonify({
            'status': 'error',
            'message': f"Finish the defense before saving. {', '.join(missing_positions)} still needs a player.",
        }), 409

    valid, message = _validate_alignment(after, present_names)
    if not valid:
        return jsonify({'status': 'error', 'message': message}), 409

    old_pitcher_id = _player_id_by_name(old_pitcher_name, team.id)
    event = _event(
        game,
        team.id,
        'Pitcher Change',
        game.live_current_inning,
        deepcopy(before),
        deepcopy(after),
        old_pitcher_id=old_pitcher_id,
        new_pitcher_id=new_pitcher.id,
    )
    db.session.commit()

    if data.get('fast'):
        return _fast_success(game, team, event, after)

    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_bulk_bp.route('/<int:game_id>/set-defense', methods=['POST'])
def set_defense(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not game.is_live:
        return jsonify({'status': 'error', 'message': 'Game is not live.'}), 409

    data = request.get_json(silent=True) or {}
    proposed = data.get('alignment')
    if not isinstance(proposed, dict):
        return jsonify({'status': 'error', 'message': 'A complete defensive alignment is required.'}), 400

    allowed = _allowed_positions(team)
    unknown_positions = [pos for pos in proposed.keys() if pos not in allowed]
    if unknown_positions:
        return jsonify({'status': 'error', 'message': f'Invalid defensive position: {unknown_positions[0]}.'}), 400

    _, actual_rotation, _ = _actual_rotation(game, team.id)
    before = _current_alignment(game, team.id, actual_rotation)
    if not before:
        return jsonify({'status': 'error', 'message': 'No current defensive alignment exists.'}), 409

    current_pitcher = before.get('P')
    requested_pitcher = proposed.get('P') or current_pitcher
    if requested_pitcher != current_pitcher:
        return jsonify({
            'status': 'error',
            'message': 'Set New Defense cannot change the pitcher. Use Change Pitcher so eligibility and workload are checked.'
        }), 409

    present_players = _present_players(game, team.id)
    present_names = {player.name for player in present_players}

    after = {}
    for pos in allowed:
        value = current_pitcher if pos == 'P' else proposed.get(pos)
        if value:
            if value not in present_names:
                return jsonify({'status': 'error', 'message': f'{value} is not available for this game.'}), 409
            after[pos] = value

    missing_positions = _missing_positions(after, allowed)
    if missing_positions:
        return jsonify({
            'status': 'error',
            'message': f"Set New Defense must fill every position. Missing: {', '.join(missing_positions)}.",
        }), 409

    valid, message = _validate_alignment(after, present_names)
    if not valid:
        return jsonify({'status': 'error', 'message': message}), 409

    comparable_before = {pos: before.get(pos) for pos in allowed if before.get(pos)}
    if comparable_before == after:
        return jsonify({'status': 'error', 'message': 'No defensive changes were made.'}), 409

    _event(
        game,
        team.id,
        'Bulk Defensive Change',
        game.live_current_inning,
        deepcopy(before),
        deepcopy(after),
    )
    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_bulk_bp.route('/<int:game_id>/defense-edit', methods=['POST'])
def defense_edit(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not game.is_live:
        return jsonify({'status': 'error', 'message': 'Game is not live.'}), 409

    data = request.get_json(silent=True) or {}
    stale = _stale_write_response(data, game, team)
    if stale:
        return stale

    after, _, message = _validate_complete_alignment(data.get('alignment'), game, team)
    if not after:
        return jsonify({'status': 'error', 'message': message}), 409

    _, actual_rotation, _ = _actual_rotation(game, team.id)
    before = _current_alignment(game, team.id, actual_rotation)
    if not before:
        return jsonify({'status': 'error', 'message': 'No current defensive alignment exists.'}), 409

    if after.get('P') != before.get('P'):
        return jsonify({
            'status': 'error',
            'message': 'The pitcher changed. Save this as a pitcher change so eligibility can be checked.',
        }), 409

    allowed = _allowed_positions(team)
    comparable_before = {pos: before.get(pos) for pos in allowed if before.get(pos)}
    if comparable_before == after:
        return jsonify({'status': 'error', 'message': 'No defensive changes were made.'}), 409

    event = _event(
        game,
        team.id,
        'Bulk Defensive Change',
        game.live_current_inning,
        deepcopy(before),
        deepcopy(after),
    )
    db.session.commit()
    return _fast_success(game, team, event, after)


@live_game_bulk_bp.route('/<int:game_id>/advance-inning', methods=['POST'])
def advance_inning(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not game.is_live:
        return jsonify({'status': 'error', 'message': 'Game is not live.'}), 409

    data = request.get_json(silent=True) or {}
    stale = _stale_write_response(data, game, team)
    if stale:
        return stale

    after, present_players, message = _validate_complete_alignment(data.get('alignment'), game, team)
    if not after:
        return jsonify({'status': 'error', 'message': message}), 409

    _, actual_rotation, _ = _actual_rotation(game, team.id)
    current = str(game.live_current_inning or '1')
    before = _current_alignment(game, team.id, actual_rotation)
    if not before:
        return jsonify({'status': 'error', 'message': 'No current defensive alignment exists.'}), 409

    try:
        next_inning = str(int(float(current)) + 1)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Current inning is invalid.'}), 409

    old_pitcher = before.get('P')
    new_pitcher = after.get('P')
    old_pitcher_id = _player_id_by_name(old_pitcher, team.id)
    new_pitcher_id = _player_id_by_name(new_pitcher, team.id)

    if new_pitcher and new_pitcher != old_pitcher:
        present_names = {player.name for player in present_players}
        if new_pitcher not in present_names:
            return jsonify({'status': 'error', 'message': 'The next pitcher is not available for this game.'}), 409
        state = get_authoritative_live_state(game.id, team.id) or {}
        pitcher_summary = (state.get('pitch_count_summary') or {}).get(new_pitcher, {})
        if _pitcher_status_blocks_change(pitcher_summary):
            status = pitcher_summary.get('status') or 'not available'
            detail = pitcher_summary.get('status_detail') or pitcher_summary.get('next_available')
            error = f'{new_pitcher} cannot start Inning {next_inning}: {status}.'
            if detail:
                error += f' {detail}'
            return jsonify({'status': 'error', 'message': error}), 409

    event = _event(
        game,
        team.id,
        'End Inning',
        next_inning,
        deepcopy(before),
        deepcopy(after),
        old_pitcher_id=old_pitcher_id if old_pitcher_id != new_pitcher_id else None,
        new_pitcher_id=new_pitcher_id if old_pitcher_id != new_pitcher_id else None,
    )
    game.live_current_inning = next_inning

    from blueprints.live_game_ui import GameNextInningPrep
    prep = db.session.query(GameNextInningPrep).filter_by(game_id=game.id, team_id=team.id).first()
    if prep:
        db.session.delete(prep)

    db.session.commit()
    return _fast_success(game, team, event, after, prep_changed=True)


def _feedback_asset_url():
    path = os.path.join(current_app.root_path, 'static', 'js', 'live_game_feedback_pass.js')
    try:
        version = str(int(os.path.getmtime(path)))
    except OSError:
        version = None
    return url_for('static', filename='js/live_game_feedback_pass.js', v=version) if version else url_for(
        'static', filename='js/live_game_feedback_pass.js'
    )


@live_game_bulk_bp.after_app_request
def inject_live_game_feedback_pass(response):
    if response.mimetype != 'text/html' or not re.fullmatch(r'/game/\d+/?', request.path):
        return response

    html = response.get_data(as_text=True)
    if 'live_game_feedback_pass.js' in html:
        return response

    tag = f'<script src="{_feedback_asset_url()}"></script>\n'
    if '</head>' in html:
        html = html.replace('</head>', tag + '</head>', 1)
    else:
        html = tag + html

    response.set_data(html)
    return response
