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
    _validate_alignment,
)

live_game_bulk_bp = Blueprint('live_game_bulk', __name__, url_prefix='/api/live-game')


def _allowed_positions(team):
    infield = ['P', 'C', '1B', '2B', '3B', 'SS']
    outfield = ['LF', 'LCF', 'RCF', 'RF'] if int(team.outfielder_count or 3) == 4 else ['LF', 'CF', 'RF']
    return infield + outfield


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

    absent_ids = {
        row.player_id
        for row in db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team.id).all()
    }
    present_players = db.session.query(Player).filter_by(team_id=team.id).all()
    present_names = {player.name for player in present_players if player.id not in absent_ids}

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
