from copy import deepcopy
from datetime import datetime

from flask import Blueprint, jsonify, request, session
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from db import db
from extensions import socketio
from game_start_readiness import can_start_game
from models import (
    Game,
    GamePitchingPlan,
    GameRotationEvent,
    Lineup,
    PitchingOuting,
    Player,
    PlayerGameAbsence,
    PlayerPitchTarget,
    PlayerPitchingProfile,
    Rotation,
    Team,
    TeamMembership,
    User,
)
from utils import calculate_pitch_count_summary, get_pitching_rules_for_team, model_to_dict

live_game_api_bp = Blueprint('live_game_api', __name__, url_prefix='/api/live-game')


def _authorized_context(game_id):
    """Return (user, team, game) for an authorized session, otherwise (None, None, None)."""
    if 'logged_in' not in session:
        return None, None, None

    username = session.get('username')
    team_id = session.get('team_id')
    if not username or not team_id:
        return None, None, None

    user = db.session.query(User).filter(db.func.lower(User.username) == username.lower()).first()
    if not user:
        return None, None, None

    membership = db.session.query(TeamMembership).filter_by(user_id=user.id, team_id=team_id).first()
    if not membership:
        return None, None, None

    team = db.session.get(Team, team_id)
    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if not team or not game:
        return None, None, None

    return user, team, game


def _room_name(team_id, game_id):
    return f'team_{team_id}_game_{game_id}'


def _planned_rotation(game, team_id):
    rotation = db.session.query(Rotation).filter_by(
        associated_game_id=game.id,
        team_id=team_id,
    ).first()
    innings = deepcopy(rotation.innings or {}) if rotation else {}
    return rotation, innings


def _events(game_id, team_id):
    return db.session.query(GameRotationEvent).filter_by(
        game_id=game_id,
        team_id=team_id,
    ).order_by(GameRotationEvent.sequence.asc(), GameRotationEvent.id.asc()).all()


def _actual_rotation(game, team_id):
    rotation, actual = _planned_rotation(game, team_id)
    events = _events(game.id, team_id)
    for event in events:
        if not event.reverted:
            actual[str(event.inning)] = deepcopy(event.after_alignment or {})
    return rotation, actual, events


def _next_sequence(game_id, team_id):
    last_event = db.session.query(GameRotationEvent).filter_by(
        game_id=game_id,
        team_id=team_id,
    ).order_by(GameRotationEvent.sequence.desc(), GameRotationEvent.id.desc()).first()
    return (last_event.sequence + 1) if last_event else 1


def _player_name(player_id, team_id):
    if player_id is None:
        return None
    player = db.session.query(Player).filter_by(id=player_id, team_id=team_id).first()
    return player.name if player else None


def _player_id_by_name(name, team_id):
    if not name:
        return None
    player = db.session.query(Player).filter_by(name=name, team_id=team_id).first()
    return player.id if player else None


def _validate_alignment(alignment, roster_names):
    values = [name for name in alignment.values() if name]
    if len(values) != len(set(values)):
        return False, 'A player cannot occupy more than one defensive position.'
    invalid = [name for name in values if name not in roster_names]
    if invalid:
        return False, 'Alignment contains a player who is not on this team.'
    return True, None


def _current_alignment(game, team_id, actual_rotation=None):
    if actual_rotation is None:
        _, actual_rotation, _ = _actual_rotation(game, team_id)
    return deepcopy(actual_rotation.get(str(game.live_current_inning or '1'), {}) or {})


def _pitching_log_for_game(game, team_id):
    return db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter(
        PitchingOuting.team_id == team_id,
        or_(
            PitchingOuting.game_id == game.id,
            and_(
                PitchingOuting.game_id.is_(None),
                PitchingOuting.opponent == game.opponent,
                db.func.date(PitchingOuting.date) == game.date.date(),
            ),
        ),
    ).all()


def get_authoritative_live_state(game_id, team_id):
    team = db.session.get(Team, team_id)
    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if not team or not game:
        return None

    roster = db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
    roster_names = {p.name for p in roster}
    absences = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team_id).all()
    absent_ids = {a.player_id for a in absences}
    present_roster = [p for p in roster if p.id not in absent_ids]

    rotation, actual_rotation, events = _actual_rotation(game, team_id)
    current_inning = str(game.live_current_inning or '1')
    current_alignment = deepcopy(actual_rotation.get(current_inning, {}) or {})
    valid, _ = _validate_alignment(current_alignment, roster_names)
    if not valid:
        current_alignment = {}

    assigned = {name for name in current_alignment.values() if name}
    bench = [model_to_dict(p) for p in present_roster if p.name not in assigned]

    try:
        next_inning = str(int(float(current_inning)) + 1)
    except (TypeError, ValueError):
        next_inning = '1'
    planned_next = deepcopy((rotation.innings or {}).get(next_inning, {}) if rotation else {})

    all_outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()
    targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team_id).all()
    rules = get_pitching_rules_for_team(team)
    pitch_summary = calculate_pitch_count_summary(
        roster,
        all_outings,
        rules,
        target_date=game.date,
        all_targets=targets,
        team_timezone=team.timezone,
        current_game_id=game.id,
    )

    profiles = db.session.query(PlayerPitchingProfile).filter_by(team_id=team_id).all()
    plans = db.session.query(GamePitchingPlan).filter_by(game_id=game.id, team_id=team_id).all()

    return {
        'game': model_to_dict(game),
        'rotation': model_to_dict(rotation) if rotation else None,
        'actual_rotation': actual_rotation,
        'current_inning': current_inning,
        'current_alignment': current_alignment,
        'current_pitcher': current_alignment.get('P'),
        'bench': bench,
        'planned_next_inning': next_inning,
        'planned_next_alignment': planned_next,
        'roster': [model_to_dict(p) for p in present_roster],
        'absent_player_ids': list(absent_ids),
        'rotation_events': [model_to_dict(e) for e in events],
        'pitch_count_summary': pitch_summary,
        'pitching_profiles': [model_to_dict(p) for p in profiles],
        'pitching_plans': [model_to_dict(p) for p in plans],
        'outfielder_count': team.outfielder_count,
        'game_pitching_log': [
            {
                **model_to_dict(o),
                'player_name': o.player.name if o.player else None,
            }
            for o in _pitching_log_for_game(game, team_id)
        ],
    }


def _broadcast_state(game_id, team_id):
    state = get_authoritative_live_state(game_id, team_id)
    if state:
        socketio.emit('game_state_update', state, room=_room_name(team_id, game_id))
    return state


def _event(game, team_id, event_type, inning, before_alignment, after_alignment,
           old_pitcher_id=None, new_pitcher_id=None):
    event = GameRotationEvent(
        team_id=team_id,
        game_id=game.id,
        inning=str(inning),
        sequence=_next_sequence(game.id, team_id),
        event_type=event_type,
        changed_by_user=session.get('username'),
        before_alignment=deepcopy(before_alignment),
        after_alignment=deepcopy(after_alignment),
        old_pitcher_id=old_pitcher_id,
        new_pitcher_id=new_pitcher_id,
    )
    db.session.add(event)
    return event


@live_game_api_bp.route('/<int:game_id>/state', methods=['GET'])
def state(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    return jsonify(get_authoritative_live_state(game.id, team.id))


@live_game_api_bp.route('/<int:game_id>/start', methods=['POST'])
def start(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403

    start_readiness = can_start_game(game, team)
    if not start_readiness['ready']:
        return jsonify({
            'status': 'error',
            'message': 'Game is not ready to start.',
            **start_readiness,
        }), 409

    game.is_live = True
    if not game.live_current_inning:
        game.live_current_inning = '1'
    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({
        'status': 'success',
        **start_readiness,
        'state': state,
    })


@live_game_api_bp.route('/<int:game_id>/change-pitcher', methods=['POST'])
def change_pitcher(game_id):
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
    destination = (data.get('outgoing_destination') or 'BENCH').upper()

    new_pitcher = db.session.query(Player).filter_by(id=new_pitcher_id, team_id=team.id).first()
    if not new_pitcher:
        return jsonify({'status': 'error', 'message': 'Incoming pitcher is not on this team.'}), 400

    _, actual_rotation, _ = _actual_rotation(game, team.id)
    before = _current_alignment(game, team.id, actual_rotation)
    if not before:
        return jsonify({'status': 'error', 'message': 'No current defensive alignment exists.'}), 409

    old_pitcher_name = before.get('P')
    old_pitcher_id = _player_id_by_name(old_pitcher_name, team.id)
    if old_pitcher_name == new_pitcher.name:
        return jsonify({'status': 'error', 'message': 'That player is already pitching.'}), 409

    after = deepcopy(before)
    incoming_old_position = next((pos for pos, name in before.items() if name == new_pitcher.name), None)
    if incoming_old_position:
        after.pop(incoming_old_position, None)

    after['P'] = new_pitcher.name

    if old_pitcher_name:
        if destination != 'BENCH':
            allowed = {'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'LCF', 'RCF'}
            if destination not in allowed:
                return jsonify({'status': 'error', 'message': 'Invalid destination position.'}), 400
            occupant = after.get(destination)
            if occupant and occupant != new_pitcher.name:
                return jsonify({
                    'status': 'error',
                    'message': f'{destination} is occupied by {occupant}. Choose Bench, an empty position, or the incoming pitcher\'s prior position.'
                }), 409
            after[destination] = old_pitcher_name

    roster_names = {p.name for p in db.session.query(Player).filter_by(team_id=team.id).all()}
    valid, message = _validate_alignment(after, roster_names)
    if not valid:
        return jsonify({'status': 'error', 'message': message}), 409

    _event(
        game,
        team.id,
        'Pitcher Change',
        game.live_current_inning,
        before,
        after,
        old_pitcher_id=old_pitcher_id,
        new_pitcher_id=new_pitcher.id,
    )
    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_api_bp.route('/<int:game_id>/defensive-change', methods=['POST'])
def defensive_change(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not game.is_live:
        return jsonify({'status': 'error', 'message': 'Game is not live.'}), 409

    data = request.get_json(silent=True) or {}
    try:
        player_id = int(data.get('player_id'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Select a valid player.'}), 400
    destination = (data.get('destination_position') or 'BENCH').upper()

    player = db.session.query(Player).filter_by(id=player_id, team_id=team.id).first()
    if not player:
        return jsonify({'status': 'error', 'message': 'Player is not on this team.'}), 400

    _, actual_rotation, _ = _actual_rotation(game, team.id)
    before = _current_alignment(game, team.id, actual_rotation)
    after = deepcopy(before)

    source = next((pos for pos, name in before.items() if name == player.name), None)
    if destination == 'BENCH':
        if source:
            after.pop(source, None)
    else:
        allowed = {'P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'LCF', 'RCF'}
        if destination not in allowed:
            return jsonify({'status': 'error', 'message': 'Invalid destination position.'}), 400
        occupant = after.get(destination)
        if source:
            after.pop(source, None)
        after[destination] = player.name
        if occupant and occupant != player.name and source:
            after[source] = occupant
        # Bench -> occupied field means the occupant goes to the bench automatically.

    roster_names = {p.name for p in db.session.query(Player).filter_by(team_id=team.id).all()}
    valid, message = _validate_alignment(after, roster_names)
    if not valid:
        return jsonify({'status': 'error', 'message': message}), 409

    old_pitcher_id = _player_id_by_name(before.get('P'), team.id)
    new_pitcher_id = _player_id_by_name(after.get('P'), team.id)
    _event(
        game,
        team.id,
        'Defensive Change',
        game.live_current_inning,
        before,
        after,
        old_pitcher_id=old_pitcher_id if old_pitcher_id != new_pitcher_id else None,
        new_pitcher_id=new_pitcher_id if old_pitcher_id != new_pitcher_id else None,
    )
    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_api_bp.route('/<int:game_id>/end-inning', methods=['POST'])
def end_inning(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    if not game.is_live:
        return jsonify({'status': 'error', 'message': 'Game is not live.'}), 409

    rotation, actual_rotation, _ = _actual_rotation(game, team.id)
    current = str(game.live_current_inning or '1')
    before = deepcopy(actual_rotation.get(current, {}) or {})
    try:
        next_inning = str(int(float(current)) + 1)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Current inning is invalid.'}), 409

    planned_next = deepcopy((rotation.innings or {}).get(next_inning, {}) if rotation else {})
    after = planned_next if planned_next else deepcopy(before)

    _event(game, team.id, 'End Inning', next_inning, before, after)
    game.live_current_inning = next_inning
    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_api_bp.route('/<int:game_id>/undo', methods=['POST'])
def undo(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403

    last_event = db.session.query(GameRotationEvent).filter_by(
        game_id=game.id,
        team_id=team.id,
        reverted=False,
    ).order_by(GameRotationEvent.sequence.desc(), GameRotationEvent.id.desc()).first()
    if not last_event:
        return jsonify({'status': 'error', 'message': 'There is nothing to undo.'}), 409

    last_event.reverted = True

    current_inning = '1'
    remaining = db.session.query(GameRotationEvent).filter_by(
        game_id=game.id,
        team_id=team.id,
        reverted=False,
        event_type='End Inning',
    ).order_by(GameRotationEvent.sequence.asc(), GameRotationEvent.id.asc()).all()
    for event in remaining:
        current_inning = str(event.inning)
    game.live_current_inning = current_inning

    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_api_bp.route('/<int:game_id>/end', methods=['POST'])
def end_game(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403

    data = request.get_json(silent=True) or {}
    counts = data.get('counts') or []

    for item in counts:
        try:
            player_id = int(item.get('player_id'))
        except (TypeError, ValueError):
            continue
        pitches = item.get('pitches')
        if pitches in (None, ''):
            continue
        try:
            pitches = int(pitches)
        except (TypeError, ValueError):
            continue

        player = db.session.query(Player).filter_by(id=player_id, team_id=team.id).first()
        if not player:
            continue

        outing = db.session.query(PitchingOuting).filter_by(
            game_id=game.id,
            player_id=player.id,
            team_id=team.id,
        ).first()
        if outing:
            outing.pitches = pitches
        else:
            db.session.add(PitchingOuting(
                date=game.date,
                opponent=game.opponent,
                pitches=pitches,
                innings=None,
                pitcher_type='Reliever',
                outing_type='Game',
                team_id=team.id,
                player_id=player.id,
                game_id=game.id,
            ))

    game.is_live = False
    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_api_bp.route('/<int:game_id>/pitching-plan', methods=['POST'])
def save_pitching_plan(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    data = request.get_json(silent=True) or {}
    try:
        player_id = int(data.get('player_id'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Select a valid player.'}), 400

    player = db.session.query(Player).filter_by(id=player_id, team_id=team.id).first()
    if not player:
        return jsonify({'status': 'error', 'message': 'Player is not on this team.'}), 400

    plan = db.session.query(GamePitchingPlan).filter_by(
        game_id=game.id,
        player_id=player.id,
        team_id=team.id,
    ).first()
    if not plan:
        plan = GamePitchingPlan(game_id=game.id, player_id=player.id, team_id=team.id)
        db.session.add(plan)

    plan.role = data.get('role') or None
    plan.expected_innings = data.get('expected_innings') or None
    plan.coach_note = data.get('coach_note') or None
    plan.situational_note = data.get('situational_note') or None
    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_api_bp.route('/<int:game_id>/pitching-plan/<int:player_id>', methods=['DELETE'])
def delete_pitching_plan(game_id, player_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403

    plan = db.session.query(GamePitchingPlan).filter_by(
        game_id=game.id,
        player_id=player_id,
        team_id=team.id,
    ).first()
    if plan:
        db.session.delete(plan)
        db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_api_bp.route('/<int:game_id>/pitching-profile/<int:player_id>', methods=['POST'])
def save_pitching_profile(game_id, player_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403

    player = db.session.query(Player).filter_by(id=player_id, team_id=team.id).first()
    if not player:
        return jsonify({'status': 'error', 'message': 'Player is not on this team.'}), 400

    data = request.get_json(silent=True) or {}
    traits = data.get('traits') or []
    if not isinstance(traits, list):
        return jsonify({'status': 'error', 'message': 'Traits must be a list.'}), 400

    profile = db.session.query(PlayerPitchingProfile).filter_by(player_id=player.id, team_id=team.id).first()
    if not profile:
        profile = PlayerPitchingProfile(player_id=player.id, team_id=team.id)
        db.session.add(profile)
    profile.traits = traits
    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})
