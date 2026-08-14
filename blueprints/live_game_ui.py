import re
from copy import deepcopy
from datetime import datetime

from flask import Blueprint, jsonify, request, session
from sqlalchemy import JSON, UniqueConstraint

from db import db
from extensions import socketio
from models import Game, Player, PlayerGameAbsence, Rotation
from blueprints.live_game_api import (
    _actual_rotation,
    _authorized_context,
    _broadcast_state,
    _event,
    _player_id_by_name,
    _validate_alignment,
    get_authoritative_live_state,
)


# Compatibility blueprint: the existing gameday route still owns /game/<id>,
# while this layer protects planned rotations and owns coach-confirmed next-inning prep.
live_game_ui_bp = Blueprint('live_game_ui', __name__)


class GameNextInningPrep(db.Model):
    __tablename__ = 'game_next_inning_preps'

    id = db.Column(db.Integer, primary_key=True)
    inning = db.Column(db.String, nullable=False)
    alignment = db.Column(JSON, nullable=False)
    source = db.Column(db.String, nullable=True)
    updated_by = db.Column(db.String, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)

    __table_args__ = (
        UniqueConstraint('game_id', 'team_id', name='uq_game_next_inning_prep'),
    )


def _next_inning_key(current):
    try:
        return str(int(float(str(current or '1'))) + 1)
    except (TypeError, ValueError):
        return None


def _allowed_positions(team):
    base = ['P', 'C', '1B', '2B', '3B', 'SS']
    outfield = ['LF', 'LCF', 'RCF', 'RF'] if int(team.outfielder_count or 3) == 4 else ['LF', 'CF', 'RF']
    return base + outfield


def _present_players(game, team_id):
    absent_ids = {
        row.player_id
        for row in db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team_id).all()
    }
    return [
        player
        for player in db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
        if player.id not in absent_ids
    ]


def _clean_complete_alignment(candidate, game, team):
    if not isinstance(candidate, dict):
        return None, 'A defensive alignment is required.'

    allowed = _allowed_positions(team)
    present = _present_players(game, team.id)
    present_names = {player.name for player in present}
    cleaned = {pos: candidate.get(pos) or '' for pos in allowed}

    missing = [pos for pos in allowed if not cleaned.get(pos)]
    if missing:
        return None, f"Choose a player for {', '.join(missing)} before confirming the next inning."

    valid, message = _validate_alignment(cleaned, present_names)
    if not valid:
        return None, message

    return cleaned, None


def _prep_dict(prep):
    if not prep:
        return None
    return {
        'id': prep.id,
        'inning': prep.inning,
        'alignment': deepcopy(prep.alignment or {}),
        'source': prep.source,
        'updated_by': prep.updated_by,
        'updated_at': prep.updated_at.isoformat() if prep.updated_at else None,
    }


def _prep_for_game(game_id, team_id):
    return db.session.query(GameNextInningPrep).filter_by(game_id=game_id, team_id=team_id).first()


def _clear_prep(game_id, team_id):
    prep = _prep_for_game(game_id, team_id)
    if prep:
        db.session.delete(prep)
        return True
    return False


def _next_inning_context(game, team):
    rotation, actual_rotation, _ = _actual_rotation(game, team.id)
    current_inning = str(game.live_current_inning or '1')
    next_inning = _next_inning_key(current_inning)
    current_alignment = deepcopy(actual_rotation.get(current_inning, {}) or {})
    planned_alignment = deepcopy((rotation.innings or {}).get(next_inning, {}) if rotation and next_inning else {})
    prep = _prep_for_game(game.id, team.id)

    if prep and prep.inning != next_inning:
        db.session.delete(prep)
        db.session.commit()
        prep = None

    return current_inning, next_inning, current_alignment, planned_alignment, prep


def _end_inning_with_confirmed_prep():
    try:
        game_id = int((request.view_args or {}).get('game_id'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Invalid game.'}), 400

    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not game.is_live:
        return jsonify({'status': 'error', 'message': 'Game is not live.'}), 409

    _, next_inning, before, _, prep = _next_inning_context(game, team)
    if not next_inning:
        return jsonify({'status': 'error', 'message': 'Current inning is invalid.'}), 409
    if not prep or prep.inning != next_inning:
        return jsonify({
            'status': 'error',
            'message': f'Confirm the Inning {next_inning} setup in Physical Board Prep before ending the inning.'
        }), 409

    after, message = _clean_complete_alignment(prep.alignment, game, team)
    if not after:
        return jsonify({'status': 'error', 'message': message}), 409

    old_pitcher = before.get('P')
    new_pitcher = after.get('P')
    if new_pitcher and new_pitcher != old_pitcher:
        state = get_authoritative_live_state(game.id, team.id) or {}
        summary = (state.get('pitch_count_summary') or {}).get(new_pitcher, {})
        status = str(summary.get('status') or '').lower()
        if any(term in status for term in ('rest', 'unavailable', 'ineligible', 'incomplete', 'restriction', 'verify')):
            return jsonify({
                'status': 'error',
                'message': f'{new_pitcher} cannot start the next inning right now: {summary.get("status") or "not available"}.'
            }), 409

    old_pitcher_id = _player_id_by_name(old_pitcher, team.id)
    new_pitcher_id = _player_id_by_name(new_pitcher, team.id)
    _event(
        game,
        team.id,
        'End Inning',
        next_inning,
        before,
        after,
        old_pitcher_id=old_pitcher_id if old_pitcher_id != new_pitcher_id else None,
        new_pitcher_id=new_pitcher_id if old_pitcher_id != new_pitcher_id else None,
    )
    game.live_current_inning = next_inning
    db.session.delete(prep)
    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_ui_bp.route('/api/live-game/<int:game_id>/next-inning-prep', methods=['GET', 'POST', 'DELETE'])
def next_inning_prep(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not game.is_live:
        return jsonify({'status': 'error', 'message': 'Game is not live.'}), 409

    current_inning, next_inning, current_alignment, planned_alignment, prep = _next_inning_context(game, team)
    if not next_inning:
        return jsonify({'status': 'error', 'message': 'Current inning is invalid.'}), 409

    if request.method == 'DELETE':
        if prep:
            db.session.delete(prep)
            db.session.commit()
            socketio.emit('next_inning_prep_update', {'game_id': game.id, 'inning': next_inning}, room=f'team_{team.id}_game_{game.id}')
        return jsonify({'status': 'success', 'confirmed': None})

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        mode = (data.get('mode') or '').lower()

        if mode == 'current':
            candidate = current_alignment
            source = 'current'
        elif mode == 'planned':
            if not planned_alignment:
                return jsonify({'status': 'error', 'message': f'No complete pregame plan is saved for Inning {next_inning}.'}), 409
            candidate = planned_alignment
            source = 'planned'
        elif mode == 'custom':
            candidate = data.get('alignment')
            source = 'custom'
        else:
            return jsonify({'status': 'error', 'message': 'Choose Current Defense, Pregame Plan, or a custom setup.'}), 400

        cleaned, message = _clean_complete_alignment(candidate, game, team)
        if not cleaned:
            return jsonify({'status': 'error', 'message': message}), 409

        prep = prep or GameNextInningPrep(game_id=game.id, team_id=team.id)
        prep.inning = next_inning
        prep.alignment = cleaned
        prep.source = source
        prep.updated_by = session.get('username')
        prep.updated_at = datetime.utcnow()
        db.session.add(prep)
        db.session.commit()
        socketio.emit('next_inning_prep_update', {'game_id': game.id, 'inning': next_inning}, room=f'team_{team.id}_game_{game.id}')

    return jsonify({
        'status': 'success',
        'game_id': game.id,
        'current_inning': current_inning,
        'next_inning': next_inning,
        'current_alignment': current_alignment,
        'planned_alignment': planned_alignment,
        'confirmed': _prep_dict(prep),
        'roster': [{'id': player.id, 'name': player.name} for player in _present_players(game, team.id)],
        'outfielder_count': team.outfielder_count,
    })


@live_game_ui_bp.before_app_request
def protect_live_game_workflows():
    """Protect the pregame plan and require an explicit next-inning decision."""
    if request.method == 'POST' and request.endpoint == 'live_game_api.end_inning':
        return _end_inning_with_confirmed_prep()

    if request.method == 'POST' and request.endpoint in {
        'live_game_api.start',
        'live_game_api.end_game',
        'live_game_pitching.end_with_pitching',
    }:
        try:
            game_id = int((request.view_args or {}).get('game_id'))
        except (TypeError, ValueError):
            game_id = None
        if game_id:
            user, team, game = _authorized_context(game_id)
            if game and _clear_prep(game.id, team.id):
                db.session.commit()

    if request.method != 'POST' or request.endpoint != 'gameday.save_rotation':
        return None

    team_id = session.get('team_id')
    if not team_id:
        return None

    payload = request.get_json(silent=True) or {}
    game_id = payload.get('associated_game_id')

    if not game_id and payload.get('id'):
        try:
            rotation_id = int(payload.get('id'))
        except (TypeError, ValueError):
            rotation_id = None
        if rotation_id:
            rotation = db.session.query(Rotation).filter_by(id=rotation_id, team_id=team_id).first()
            if rotation:
                game_id = rotation.associated_game_id

    try:
        game_id = int(game_id) if game_id not in (None, '') else None
    except (TypeError, ValueError):
        game_id = None

    if not game_id:
        return None

    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if game and game.is_live:
        return jsonify({
            'status': 'error',
            'message': 'The planned defensive rotation is locked while this game is live. Use Live Game changes instead.'
        }), 409

    return None


@live_game_ui_bp.after_app_request
def inject_live_game_assets(response):
    """Load the final live-game helpers and avoid a legacy first-paint flash."""
    if response.mimetype != 'text/html' or not re.fullmatch(r'/game/\d+/?', request.path):
        return response

    html = response.get_data(as_text=True)

    if 'coach-live-first-paint' not in html:
        first_paint = '''
<style id="coach-live-first-paint">
  #live-game-overlay:not(.coach-live-polished):not(.coach-live-boot-fallback) {
    visibility: hidden !important;
  }
  #pregame-checklist-container > .d-flex:first-child .bi {
    display: none !important;
  }
</style>
'''
        if '</head>' in html:
            html = html.replace('</head>', first_paint + '</head>', 1)
        else:
            html = first_paint + html

    # This controller must register before live_game_v2.js so it owns the End
    # Game click and prevents the old pitch-count-only finalization workflow.
    if 'live_game_pitching_finalize.js' not in html:
        finalize_asset = '<script src="/static/js/live_game_pitching_finalize.js"></script>\n'
        v2_marker = '<script src="/static/js/live_game_v2.js"></script>'
        if v2_marker in html:
            html = html.replace(v2_marker, finalize_asset + v2_marker, 1)
        elif '</head>' in html:
            html = html.replace('</head>', finalize_asset + '</head>', 1)
        else:
            html = finalize_asset + html

    if 'live_game_board_prep_v2.js' not in html:
        assets = '''
<script>
  window.setTimeout(function () {
    var overlay = document.getElementById('live-game-overlay');
    if (overlay && !overlay.classList.contains('coach-live-polished')) {
      overlay.classList.add('coach-live-boot-fallback');
    }
  }, 2500);
</script>
<script src="/static/js/live_game_pitcher_change_complete.js"></script>
<script src="/static/js/live_game_board_prep_v2.js"></script>
<script src="/static/js/live_game_postgame_cleanup.js"></script>
'''
        if '</body>' in html:
            html = html.replace('</body>', assets + '</body>', 1)
        else:
            html += assets

    response.set_data(html)
    return response
