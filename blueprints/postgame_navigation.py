from copy import deepcopy

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from db import db
from game_day_helpers import actual_game_rotation, build_game_readiness, required_positions
from lineup_service import lineup_to_dict, sync_lineup
from models import (
    Game,
    GameRotationEvent,
    Lineup,
    Player,
    PlayerGameAbsence,
    Team,
    TeamMembership,
    User,
)


postgame_navigation_bp = Blueprint('postgame_navigation', __name__)


def _authorized_game(game_id):
    if 'logged_in' not in session:
        return None, None
    team_id = session.get('team_id')
    if not team_id:
        return None, None
    team = db.session.get(Team, team_id)
    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    return team, game


def _has_end_game(game, team_id):
    if not game or game.is_live:
        return False
    return db.session.query(GameRotationEvent.id).filter_by(
        game_id=game.id,
        team_id=team_id,
        event_type='End Game',
        reverted=False,
    ).first() is not None


def _correction_role_allowed(team_id):
    username = str(session.get('username') or '').strip()
    if not username:
        return False
    user = db.session.query(User).filter(db.func.lower(User.username) == username.lower()).first()
    if not user:
        return False
    membership = db.session.query(TeamMembership).filter_by(user_id=user.id, team_id=team_id).first()
    role = str(membership.role if membership else session.get('role') or '').strip()
    return role != 'Game Changer'


def _present_players(game, team_id):
    absent_ids = {
        row.player_id
        for row in db.session.query(PlayerGameAbsence).filter_by(
            game_id=game.id,
            team_id=team_id,
        ).all()
    }
    return [
        player
        for player in db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
        if player.id not in absent_ids
    ]


def _inning_sort(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 9999.0


def _correction_context(game, team):
    present = _present_players(game, team.id)
    lineup = db.session.query(Lineup).filter_by(
        associated_game_id=game.id,
        team_id=team.id,
    ).first()
    lineup_data = lineup_to_dict(lineup) if lineup else None
    lineup_entries = list((lineup_data or {}).get('lineup_entries') or [])

    _, actual, _, reached = actual_game_rotation(game, team.id)
    readiness = build_game_readiness(game, team)
    regulation = int(readiness.get('regulation_innings') or 6)
    inning_keys = {str(number) for number in range(1, regulation + 1)}
    inning_keys.update(str(value) for value in reached)

    player_payload = [
        {
            'id': player.id,
            'name': player.name,
            'number': str(player.number or '').strip(),
        }
        for player in present
    ]
    player_by_name = {player['name']: player for player in player_payload}

    def label(name):
        player = player_by_name.get(str(name or ''))
        if not player:
            return str(name or '')
        return f"#{player['number']} {player['name']}" if player['number'] else player['name']

    innings = []
    for inning in sorted(inning_keys, key=_inning_sort):
        alignment = deepcopy(actual.get(inning) or {})
        innings.append({
            'inning': inning,
            'alignment': alignment,
            'display_alignment': {
                pos: label(name)
                for pos, name in alignment.items()
                if name
            },
            'recorded': inning in reached,
        })

    return {
        'players': player_payload,
        'lineup': [
            {
                'player_id': entry.get('player_id'),
                'name': entry.get('name') or '',
                'display_name': label(entry.get('name')),
            }
            for entry in lineup_entries
            if entry.get('player_id') is not None
        ],
        'innings': innings,
        'positions': required_positions(team),
        'regulation_innings': regulation,
    }


@postgame_navigation_bp.before_app_request
def route_completed_game_to_report():
    """Keep completed games in the actual-game workflow, not the pregame planner.

    `/game/<id>` is the historical Game Management route and still contains
    pregame lineup/rotation/pitching planning tools. Once a durable End Game
    event exists, opening that URL normally should show the Actual Game Report.

    Explicit postgame tools may opt into the old shell:
    - ?pitching=1 opens focused GameChanger stat entry.
    - ?edit=1 intentionally opens the setup/review screen.
    """
    if request.method != 'GET' or request.endpoint != 'gameday.game_management':
        return None

    if request.args.get('pitching') == '1' or request.args.get('edit') == '1':
        return None

    team_id = session.get('team_id')
    if not team_id:
        return None

    try:
        game_id = int((request.view_args or {}).get('game_id'))
    except (TypeError, ValueError):
        return None

    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if not game or game.is_live:
        return None

    if not _has_end_game(game, team_id):
        return None

    return redirect(url_for('game_day.game_report', game_id=game.id))


@postgame_navigation_bp.route('/game-day/<int:game_id>/correct')
def correct_game(game_id):
    team, game = _authorized_game(game_id)
    if not team or not game:
        return redirect(url_for('auth.login')) if 'logged_in' not in session else redirect(url_for('game_day.game_day_home'))
    if not _has_end_game(game, team.id):
        flash('Only ended games can be corrected from the Game Report.', 'warning')
        return redirect(url_for('game_day.game_report', game_id=game.id))
    if not _correction_role_allowed(team.id):
        flash('GameChanger users can update pitching stats, but game-record corrections require a coach.', 'warning')
        return redirect(url_for('game_day.game_report', game_id=game.id))

    return render_template(
        'game_correction.html',
        current_team=team,
        game=game,
        correction=_correction_context(game, team),
    )


@postgame_navigation_bp.route('/api/game-day/<int:game_id>/corrections/defense', methods=['POST'])
def correct_defense(game_id):
    team, game = _authorized_game(game_id)
    if not team or not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not _correction_role_allowed(team.id):
        return jsonify({'status': 'error', 'message': 'A coach is required to correct the game record.'}), 403
    if not _has_end_game(game, team.id):
        return jsonify({'status': 'error', 'message': 'Only ended games can be corrected.'}), 409

    data = request.get_json(silent=True) or {}
    inning = str(data.get('inning') or '').strip()
    try:
        inning_number = float(inning)
        if inning_number <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Choose a valid inning.'}), 400

    proposed = data.get('alignment')
    if not isinstance(proposed, dict):
        return jsonify({'status': 'error', 'message': 'A complete defensive alignment is required.'}), 400

    positions = required_positions(team)
    present = _present_players(game, team.id)
    present_names = {player.name for player in present}
    cleaned = {pos: str(proposed.get(pos) or '').strip() for pos in positions}
    missing = [pos for pos in positions if not cleaned[pos]]
    if missing:
        return jsonify({
            'status': 'error',
            'message': f"Fill every defensive position before saving. Missing: {', '.join(missing)}.",
        }), 409

    names = list(cleaned.values())
    if len(names) != len(set(names)):
        return jsonify({'status': 'error', 'message': 'A player cannot occupy more than one defensive position.'}), 409
    invalid = [name for name in names if name not in present_names]
    if invalid:
        return jsonify({'status': 'error', 'message': f'{invalid[0]} is not available for this game.'}), 409

    _, actual, _, reached = actual_game_rotation(game, team.id)
    regulation = int(build_game_readiness(game, team).get('regulation_innings') or 6)
    allowed_innings = {str(number) for number in range(1, regulation + 1)} | {str(value) for value in reached}
    if inning not in allowed_innings:
        return jsonify({'status': 'error', 'message': 'That inning is outside this game record.'}), 409

    before = deepcopy(actual.get(inning) or {})
    comparable_before = {pos: before.get(pos) or '' for pos in positions}
    if comparable_before == cleaned:
        return jsonify({'status': 'success', 'message': f'Inning {inning} already matches that defense.'})

    last_event = db.session.query(GameRotationEvent).filter_by(
        game_id=game.id,
        team_id=team.id,
    ).order_by(GameRotationEvent.sequence.desc(), GameRotationEvent.id.desc()).first()
    sequence = (last_event.sequence + 1) if last_event else 1
    by_name = {player.name: player for player in present}
    old_pitcher = by_name.get(before.get('P'))
    new_pitcher = by_name.get(cleaned.get('P'))

    db.session.add(GameRotationEvent(
        inning=inning,
        sequence=sequence,
        event_type='Postgame Correction',
        before_alignment=before,
        after_alignment=deepcopy(cleaned),
        old_pitcher_id=old_pitcher.id if old_pitcher and (not new_pitcher or old_pitcher.id != new_pitcher.id) else None,
        new_pitcher_id=new_pitcher.id if new_pitcher and (not old_pitcher or old_pitcher.id != new_pitcher.id) else None,
        changed_by_user=session.get('full_name') or session.get('username'),
        team_id=team.id,
        game_id=game.id,
    ))
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': f'Inning {inning} defense corrected.',
        'alignment': cleaned,
    })


@postgame_navigation_bp.route('/api/game-day/<int:game_id>/corrections/lineup', methods=['POST'])
def correct_lineup(game_id):
    team, game = _authorized_game(game_id)
    if not team or not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not _correction_role_allowed(team.id):
        return jsonify({'status': 'error', 'message': 'A coach is required to correct the game record.'}), 403
    if not _has_end_game(game, team.id):
        return jsonify({'status': 'error', 'message': 'Only ended games can be corrected.'}), 409

    data = request.get_json(silent=True) or {}
    raw_ids = data.get('player_ids')
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({'status': 'error', 'message': 'Add at least one player to the batting order.'}), 400
    try:
        player_ids = [int(player_id) for player_id in raw_ids]
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'One or more batting-order players are invalid.'}), 400
    if len(player_ids) != len(set(player_ids)):
        return jsonify({'status': 'error', 'message': 'A player can only appear once in the batting order.'}), 409

    present = _present_players(game, team.id)
    by_id = {player.id: player for player in present}
    missing = [player_id for player_id in player_ids if player_id not in by_id]
    if missing:
        return jsonify({'status': 'error', 'message': 'The batting order includes a player who was marked out for this game.'}), 409
    ordered_players = [by_id[player_id] for player_id in player_ids]

    lineup = db.session.query(Lineup).filter_by(
        associated_game_id=game.id,
        team_id=team.id,
    ).first()
    if not lineup:
        lineup = Lineup(
            title=f'Game vs {game.opponent}',
            team_id=team.id,
            associated_game_id=game.id,
        )
    sync_lineup(
        lineup,
        ordered_players,
        title=lineup.title or f'Game vs {game.opponent}',
        associated_game_id=game.id,
        is_default=False,
    )
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Batting order corrected.',
        'player_ids': player_ids,
    })
