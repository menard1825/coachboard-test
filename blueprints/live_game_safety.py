from copy import deepcopy

from flask import Blueprint, jsonify, request

from db import db
from models import Player, PlayerGameAbsence, Rotation
from blueprints.live_game_api import _authorized_context, get_authoritative_live_state


live_game_safety_bp = Blueprint('live_game_safety', __name__)


def _required_positions(team):
    positions = ['P', 'C', '1B', '2B', '3B', 'SS']
    if int(team.outfielder_count or 3) == 4:
        positions += ['LF', 'LCF', 'RCF', 'RF']
    else:
        positions += ['LF', 'CF', 'RF']
    return positions


def _present_names(game, team_id):
    absent_ids = {
        row.player_id
        for row in db.session.query(PlayerGameAbsence).filter_by(
            game_id=game.id,
            team_id=team_id,
        ).all()
    }
    return {
        player.name
        for player in db.session.query(Player).filter_by(team_id=team_id).all()
        if player.id not in absent_ids
    }


def _alignment_problem(alignment, game, team):
    alignment = alignment or {}
    required = _required_positions(team)
    missing = [pos for pos in required if not alignment.get(pos)]
    if missing:
        return f"Defense would leave {', '.join(missing)} open. Use Set New Defense to finish the whole alignment."

    names = [alignment.get(pos) for pos in required if alignment.get(pos)]
    if len(names) != len(set(names)):
        return 'A player cannot occupy more than one defensive position.'

    present_names = _present_names(game, team.id)
    unavailable = [name for name in names if name not in present_names]
    if unavailable:
        return f"{unavailable[0]} is not available for this game."

    return None


def _game_id_from_request():
    try:
        return int((request.view_args or {}).get('game_id'))
    except (TypeError, ValueError):
        return None


def _guard_start(game, team):
    rotation = db.session.query(Rotation).filter_by(
        associated_game_id=game.id,
        team_id=team.id,
    ).first()
    inning_one = deepcopy((rotation.innings or {}).get('1', {}) if rotation else {})
    problem = _alignment_problem(inning_one, game, team)
    if problem:
        return jsonify({
            'status': 'error',
            'message': f'Complete the Inning 1 defense before starting Live Game. {problem}'
        }), 409
    return None


def _guard_quick_change(game, team, data):
    state = get_authoritative_live_state(game.id, team.id) or {}
    before = deepcopy(state.get('current_alignment') or {})
    if not before:
        return jsonify({
            'status': 'error',
            'message': 'No complete current defense exists. Use Set New Defense before making a Quick Change.'
        }), 409

    try:
        player_id = int(data.get('player_id'))
    except (TypeError, ValueError):
        return None

    player = db.session.query(Player).filter_by(id=player_id, team_id=team.id).first()
    if not player:
        return None

    destination = str(data.get('destination_position') or 'BENCH').upper()
    source = next((pos for pos, name in before.items() if name == player.name), None)

    if source == 'P' or destination == 'P':
        return jsonify({
            'status': 'error',
            'message': 'Use Change Pitcher for any move involving P.'
        }), 409

    after = deepcopy(before)
    if destination == 'BENCH':
        if source:
            after.pop(source, None)
    else:
        occupant = after.get(destination)
        if source:
            after.pop(source, None)
        after[destination] = player.name
        if occupant and occupant != player.name and source:
            after[source] = occupant

    problem = _alignment_problem(after, game, team)
    if problem:
        return jsonify({
            'status': 'error',
            'message': problem
        }), 409
    return None


def _guard_legacy_pitcher_change(game, team, data):
    state = get_authoritative_live_state(game.id, team.id) or {}
    before = deepcopy(state.get('current_alignment') or {})
    if not before:
        return jsonify({
            'status': 'error',
            'message': 'No complete current defense exists. Use Set New Defense first.'
        }), 409

    try:
        new_pitcher_id = int(data.get('new_pitcher_id'))
    except (TypeError, ValueError):
        return None

    new_pitcher = db.session.query(Player).filter_by(id=new_pitcher_id, team_id=team.id).first()
    if not new_pitcher:
        return None

    after = deepcopy(before)
    old_pitcher = before.get('P')
    incoming_source = next((pos for pos, name in before.items() if name == new_pitcher.name), None)
    if incoming_source:
        after.pop(incoming_source, None)
    after['P'] = new_pitcher.name

    destination = str(data.get('outgoing_destination') or 'BENCH').upper()
    if old_pitcher and destination != 'BENCH':
        after[destination] = old_pitcher

    problem = _alignment_problem(after, game, team)
    if problem:
        return jsonify({
            'status': 'error',
            'message': f'{problem} Finish the pitching change by explicitly filling every position.'
        }), 409
    return None


@live_game_safety_bp.before_app_request
def protect_complete_live_defense():
    if request.method != 'POST':
        return None

    endpoint = request.endpoint
    if endpoint not in {
        'live_game_api.start',
        'live_game_api.defensive_change',
        'live_game_api.change_pitcher',
    }:
        return None

    game_id = _game_id_from_request()
    if not game_id:
        return None

    user, team, game = _authorized_context(game_id)
    if not game:
        return None

    if endpoint == 'live_game_api.start':
        return _guard_start(game, team)

    if not game.is_live:
        return None

    data = request.get_json(silent=True) or {}
    if endpoint == 'live_game_api.defensive_change':
        return _guard_quick_change(game, team, data)
    if endpoint == 'live_game_api.change_pitcher':
        return _guard_legacy_pitcher_change(game, team, data)

    return None
