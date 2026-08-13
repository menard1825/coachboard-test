from copy import deepcopy

from flask import session
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from db import db
from extensions import socketio
from models import (
    Game, GamePitchingPlan, GameRotationEvent, PitchingOuting, Player,
    PlayerGameAbsence, PlayerPitchTarget, PlayerPitchingProfile, Rotation,
    Team, TeamMembership, User,
)
from utils import calculate_pitch_count_summary, get_pitching_rules_for_team, model_to_dict


def authorized_context(game_id):
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


def room_name(team_id, game_id):
    return f'team_{team_id}_game_{game_id}'


def valid_positions(team):
    positions = {'P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'RF'}
    if getattr(team, 'outfielder_count', 3) == 4:
        positions.update({'LCF', 'RCF'})
    else:
        positions.add('CF')
    return positions


def planned_rotation(game, team_id):
    rotation = db.session.query(Rotation).filter_by(associated_game_id=game.id, team_id=team_id).first()
    return rotation, deepcopy(rotation.innings or {}) if rotation else {}


def events_for_game(game_id, team_id):
    return db.session.query(GameRotationEvent).filter_by(game_id=game_id, team_id=team_id).order_by(
        GameRotationEvent.sequence.asc(), GameRotationEvent.id.asc()
    ).all()


def actual_rotation(game, team_id):
    rotation, actual = planned_rotation(game, team_id)
    events = events_for_game(game.id, team_id)
    for event in events:
        if not event.reverted:
            actual[str(event.inning)] = deepcopy(event.after_alignment or {})
    return rotation, actual, events


def next_sequence(game_id, team_id):
    last_event = db.session.query(GameRotationEvent).filter_by(game_id=game_id, team_id=team_id).order_by(
        GameRotationEvent.sequence.desc(), GameRotationEvent.id.desc()
    ).first()
    return last_event.sequence + 1 if last_event else 1


def player_id_by_name(name, team_id):
    if not name:
        return None
    player = db.session.query(Player).filter_by(name=name, team_id=team_id).first()
    return player.id if player else None


def present_roster(game, team_id):
    roster = db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
    absent_ids = {a.player_id for a in db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team_id).all()}
    return roster, [p for p in roster if p.id not in absent_ids], absent_ids


def validate_alignment(alignment, allowed_names, positions=None):
    alignment = alignment or {}
    if positions is not None:
        bad = [pos for pos in alignment if pos not in positions]
        if bad:
            return False, f'Invalid defensive position: {bad[0]}.'
    values = [name for name in alignment.values() if name]
    if len(values) != len(set(values)):
        return False, 'A player cannot occupy more than one defensive position.'
    invalid = [name for name in values if name not in allowed_names]
    if invalid:
        return False, f'{invalid[0]} is unavailable for this game.'
    return True, None


def pitch_context(team, game, roster=None):
    roster = roster or db.session.query(Player).filter_by(team_id=team.id).all()
    outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team.id).all()
    targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team.id).all()
    summary = calculate_pitch_count_summary(
        roster, outings, get_pitching_rules_for_team(team), target_date=game.date,
        all_targets=targets, team_timezone=team.timezone, current_game_id=game.id,
    )
    return summary, targets


def official_pitcher_check(team, game, player, roster=None):
    summary, _ = pitch_context(team, game, roster=roster)
    data = summary.get(player.name)
    if not data:
        return False, 'Pitching eligibility could not be verified.'
    if data.get('status') == 'Available':
        return True, None
    if data.get('status') == 'Pitch Count Incomplete':
        return False, 'Pitch history is incomplete. Verify the missing GameChanger pitch count before using this pitcher.'
    return False, f"{player.name} is {data.get('status', 'not available')} under the configured pitching rules."


def whole_inning(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 1


def pitchers_used(actual, current_inning):
    used, seen = [], set()
    for inning in range(1, whole_inning(current_inning) + 1):
        name = (actual.get(str(inning), {}) or {}).get('P')
        if name and name not in seen:
            seen.add(name)
            used.append(name)
    return used


def pitching_log_for_game(game, team_id):
    return db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter(
        PitchingOuting.team_id == team_id,
        or_(
            PitchingOuting.game_id == game.id,
            and_(PitchingOuting.game_id.is_(None), PitchingOuting.opponent == game.opponent,
                 db.func.date(PitchingOuting.date) == game.date.date()),
        ),
    ).all()


def build_state(game_id, team_id):
    team = db.session.get(Team, team_id)
    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if not team or not game:
        return None
    roster, present, absent_ids = present_roster(game, team_id)
    rotation, actual, events = actual_rotation(game, team_id)
    current = str(game.live_current_inning or '1')
    alignment = deepcopy(actual.get(current, {}) or {})
    valid, warning = validate_alignment(alignment, {p.name for p in present}, valid_positions(team))
    assigned = {name for name in alignment.values() if name}
    next_inning = str(whole_inning(current) + 1)
    pitch_summary, targets = pitch_context(team, game, roster=roster)
    profiles = db.session.query(PlayerPitchingProfile).filter_by(team_id=team_id).all()
    plans = db.session.query(GamePitchingPlan).filter_by(game_id=game.id, team_id=team_id).all()
    active_events = [e for e in events if not e.reverted]
    lifecycle = 'live' if game.is_live else ('post_game' if any(e.event_type == 'Start Game' for e in active_events) else 'pre_game')
    planned_next = deepcopy((rotation.innings or {}).get(next_inning, {}) if rotation else {})
    return {
        'game': model_to_dict(game), 'lifecycle': lifecycle,
        'rotation': model_to_dict(rotation) if rotation else None,
        'actual_rotation': actual, 'current_inning': current,
        'current_alignment': alignment, 'alignment_valid': valid, 'alignment_warning': warning,
        'current_pitcher': alignment.get('P'),
        'bench': [model_to_dict(p) for p in present if p.name not in assigned],
        'planned_next_inning': next_inning, 'planned_next_alignment': planned_next,
        'roster': [model_to_dict(p) for p in present], 'absent_player_ids': list(absent_ids),
        'rotation_events': [model_to_dict(e) for e in events],
        'last_change': model_to_dict(active_events[-1]) if active_events else None,
        'pitch_count_summary': pitch_summary,
        'pitching_profiles': [model_to_dict(p) for p in profiles],
        'pitching_plans': [model_to_dict(p) for p in plans],
        'pitch_targets': [model_to_dict(t) for t in targets],
        'pitchers_used': pitchers_used(actual, current), 'outfielder_count': team.outfielder_count,
        'game_pitching_log': [{**model_to_dict(o), 'player_name': o.player.name if o.player else None}
                              for o in pitching_log_for_game(game, team_id)],
    }


def broadcast_state(game_id, team_id):
    state = build_state(game_id, team_id)
    if state:
        socketio.emit('game_state_update', state, room=room_name(team_id, game_id))
    return state
