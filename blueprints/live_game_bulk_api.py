from copy import deepcopy

from flask import Blueprint, jsonify, request

from db import db
from models import Player, PlayerGameAbsence
from blueprints.live_game_api import (
    _actual_rotation,
    _authorized_context,
    _broadcast_state,
    _current_alignment,
    _event,
    _player_id_by_name,
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
    return any(term in status for term in ('rest', 'unavailable', 'ineligible', 'incomplete'))


@live_game_bulk_bp.route('/<int:game_id>/complete-pitcher-change', methods=['POST'])
def complete_pitcher_change(game_id):
    """Apply a pitcher change and the resulting defensive alignment as one live event.

    The incoming pitcher may be coming from the bench or another defensive position.
    The submitted alignment must keep every position that was occupied before the
    pitching change occupied afterward, so moving a fielder to the mound cannot
    silently create a defensive hole.
    """
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not game.is_live:
        return jsonify({'status': 'error', 'message': 'Game is not live.'}), 409

    data = request.get_json(silent=True) or {}
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
        detail = pitcher_summary.get('next_available')
        message = f'{new_pitcher.name} cannot pitch right now: {status}.'
        if detail:
            message += f' Next available: {detail}.'
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

    valid, message = _validate_alignment(after, present_names)
    if not valid:
        return jsonify({'status': 'error', 'message': message}), 409

    # Preserve the shape of the defense that was on the field before the change.
    # If 1B was occupied before, for example, moving that 1B to P cannot leave 1B empty.
    required_positions = [pos for pos in allowed if before.get(pos)]
    missing_positions = [pos for pos in required_positions if not after.get(pos)]
    if missing_positions:
        label = ', '.join(missing_positions)
        return jsonify({
            'status': 'error',
            'message': f'Finish the defense before saving. {label} still needs a player.'
        }), 409

    old_pitcher_id = _player_id_by_name(old_pitcher_name, team.id)
    _event(
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
        if pos == 'P':
            value = current_pitcher
        else:
            value = proposed.get(pos)
        if value:
            if value not in present_names:
                return jsonify({
                    'status': 'error',
                    'message': f'{value} is not available for this game.'
                }), 409
            after[pos] = value

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
