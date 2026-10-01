from copy import deepcopy
from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, request, session
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from db import db
from extensions import socketio
from game_availability import INNING_STARTED, game_availability, inning_has_started
from game_day_helpers import required_positions
from live_history import gameplay_events
from game_start_readiness import can_start_game, normalized_inning_one
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
import pitching_eligibility
from utils import calculate_pitch_count_summary, get_pitching_rules_for_team, model_to_dict
from unrecorded_pitching import with_unrecorded
from team_game_settings import regulation_innings_for_team

live_game_api_bp = Blueprint('live_game_api', __name__, url_prefix='/api/live-game')


def _authorized_context(game_id):
    """Return (user, team, game) for an authorized session, otherwise (None, None, None)."""
    if 'logged_in' not in session:
        return None, None, None

    username = session.get('username')
    team_id = session.get('team_id')
    if not username or not team_id:
        return None, None, None

    cached_user = getattr(g, 'coachboard_user', None)
    cached_membership = getattr(
        g,
        'coachboard_membership',
        None,
    )

    cache_matches = (
        cached_user is not None
        and cached_membership is not None
        and str(cached_user.username).lower()
        == str(username).lower()
        and cached_membership.user_id == cached_user.id
        and cached_membership.team_id == team_id
    )

    if cache_matches:
        user = cached_user
        membership = cached_membership
    else:
        # Keep this fallback: _authorized_context() can be called from a
        # request path where the security guard cache was not populated.
        user = db.session.query(User).filter(
            db.func.lower(User.username)
            == username.lower()
        ).first()
        if not user:
            return None, None, None

        membership = db.session.query(
            TeamMembership
        ).filter_by(
            user_id=user.id,
            team_id=team_id,
        ).first()
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


def _current_sequence(game_id, team_id):
    last_event = db.session.query(GameRotationEvent).filter_by(
        game_id=game_id,
        team_id=team_id,
        reverted=False,
    ).order_by(
        GameRotationEvent.sequence.desc(),
        GameRotationEvent.id.desc(),
    ).first()

    return int(last_event.sequence or 0) if last_event else 0


def _stale_write_response(data, game, team):
    raw_sequence = data.get('base_sequence')

    if raw_sequence in (None, ''):
        return jsonify({
            'status': 'error',
            'code': 'missing_live_state_version',
            'message': (
                'This Live Game screen is out of date. '
                'Refresh the live field before saving this change.'
            ),
            'current_sequence': _current_sequence(
                game.id,
                team.id,
            ),
        }), 409

    try:
        expected = int(raw_sequence)
    except (TypeError, ValueError):
        return jsonify({
            'status': 'error',
            'code': 'invalid_live_state_version',
            'message': (
                'The Live Game version is invalid. '
                'Refresh and try again.'
            ),
        }), 400

    current = _current_sequence(game.id, team.id)

    if expected == current:
        return None

    _, actual_rotation, _ = _actual_rotation(
        game,
        team.id,
    )
    alignment = _current_alignment(
        game,
        team.id,
        actual_rotation,
    )

    return jsonify({
        'status': 'error',
        'code': 'stale_live_state',
        'message': (
            'Another coach changed the live game first. '
            'Review the updated field before saving.'
        ),
        'current_sequence': current,
        'current_inning': str(
            game.live_current_inning or '1'
        ),
        'current_alignment': alignment,
    }), 409


def _record_inning_start(game, team_id, inning, alignment):
    """The inning begins with this defense (game_availability).

    Start Game and End Inning -> Start Next Inning are the inning boundary:
    each records the inning it starts, with the exact defense it sends out.
    Nothing else asks or decides whether an inning has begun.
    """
    return _event(
        game,
        team_id,
        INNING_STARTED,
        str(inning),
        deepcopy(alignment or {}),
        deepcopy(alignment or {}),
    )


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


def get_authoritative_live_state(game_id, team_id, game=None):
    team = db.session.get(Team, team_id)

    if game is None:
        game = db.session.query(Game).filter_by(
            id=game_id,
            team_id=team_id,
        ).first()
    elif game.id != game_id or game.team_id != team_id:
        # A supplied Game is only reusable when it is exactly the row the
        # caller requested. Fall closed rather than trusting mismatched state.
        return None

    if not team or not game:
        return None

    roster = db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
    roster_names = {p.name for p in roster}
    absences = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team_id).all()

    rotation, actual_rotation, events = _actual_rotation(game, team_id)
    # Here now: Out at first pitch, then any late arrival or departure.
    availability = game_availability(
        game, team_id, roster=roster, absences=absences, events=events,
    )
    present_roster = [p for p in roster if availability.is_present(p.id)]
    current_inning = str(game.live_current_inning or '1')
    current_alignment = deepcopy(
        actual_rotation.get(current_inning, {}) or {}
    )

    roster_valid, roster_warning = _validate_alignment(
        current_alignment,
        roster_names,
    )

    alignment_names = {
        name
        for name in current_alignment.values()
        if name
    }

    present_names = {
        player.name
        for player in present_roster
    }

    alignment_offending_names = sorted(
        name
        for name in alignment_names
        if name not in roster_names
    )

    alignment_availability_conflicts = sorted(
        name
        for name in alignment_names
        if name in roster_names
        and name not in present_names
    )

    alignment_valid = (
        roster_valid
        and not alignment_availability_conflicts
    )

    if not roster_valid:
        alignment_warning = roster_warning
    elif alignment_availability_conflicts:
        conflict = alignment_availability_conflicts[0]
        left_names = {p.name for p in roster if p.id in availability.left_game}
        alignment_warning = (
            f'{conflict} left the game.'
            if conflict in left_names
            else f'{conflict} is marked Out for this game.'
        )
    else:
        alignment_warning = None

    # Never erase the saved diamond merely because the roster or
    # availability changed underneath it. Showing the last saved
    # defense is safer than turning the whole field blank.
    assigned = {
        name
        for name in current_alignment.values()
        if name
    }
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
        # Another started game's pitching with no count yet. This game's
        # own pitching is shown from its history (pitching_now below).
        with_unrecorded(team_id, all_outings, game.date.date(), exclude_game_id=game.id, roster=roster),
        rules,
        target_date=game.date,
        all_targets=targets,
        team_timezone=team.timezone,
        current_game_id=game.id,
    )
    # Re-entry depends on this game's pitching history, which the
    # pitch-count calculator does not see -- history, not setup edits made
    # before an inning began (live_history).
    history = gameplay_events(events)
    pitching_eligibility.apply_reentry_rule(
        pitch_summary,
        rules,
        history,
        current_alignment.get('P'),
        current_alignment,
    )
    # Every screen shows the same classification, rule set and reason.
    pitching_eligibility.annotate(pitch_summary, rules)
    # This game's pitches are entered when it ends, so its pitchers have no
    # count yet: say "pitching now" / "pitched this game", never "0 today".
    if game.is_live:
        recorded = {o.player_id for o in all_outings if o.game_id == game.id}
        on_mound = current_alignment.get('P') or ''
        pitched = {on_mound} if on_mound else set()
        for event in history:
            for alignment in (event.before_alignment, event.after_alignment):
                if (alignment or {}).get('P'):
                    pitched.add(alignment['P'])
        for name in pitched:
            item = pitch_summary.get(name)
            if item and item.get('id') not in recorded:
                item['pitched_this_game'] = True
                item['pitching_now'] = name == on_mound

    profiles = db.session.query(PlayerPitchingProfile).filter_by(team_id=team_id).all()
    plans = db.session.query(GamePitchingPlan).filter_by(game_id=game.id, team_id=team_id).all()

    return {
        'game': model_to_dict(game),
        'rotation': model_to_dict(rotation) if rotation else None,
        'actual_rotation': actual_rotation,
        'current_inning': current_inning,
        'current_alignment': current_alignment,
        'alignment_valid': alignment_valid,
        'alignment_warning': alignment_warning,
        'alignment_offending_names': alignment_offending_names,
        'alignment_availability_conflicts': alignment_availability_conflicts,
        'current_pitcher': current_alignment.get('P'),
        'bench': bench,
        'planned_next_inning': next_inning,
        'planned_next_alignment': planned_next,
        'roster': [model_to_dict(p) for p in present_roster],
        'absent_player_ids': sorted(availability.not_here_now()),
        'rotation_events': [model_to_dict(e) for e in events],
        # The same timeline as baseball history (live_history): no setup
        # edits, and each inning taking the field with the defense that
        # actually began it. For who pitched and what changed during play.
        'gameplay_events': [_gameplay_event_dict(e) for e in history],
        'pitch_count_summary': pitch_summary,
        'pitching_profiles': [model_to_dict(p) for p in profiles],
        'pitching_plans': [model_to_dict(p) for p in plans],
        'outfielder_count': team.outfielder_count,
        # How many innings the game is scheduled for (Bench Report names
        # the unplanned ones rather than leaving them out).
        'regulation_innings': regulation_innings_for_team(team),
        'game_pitching_log': [
            {
                **model_to_dict(o),
                'player_name': o.player.name if o.player else None,
            }
            for o in _pitching_log_for_game(game, team_id)
        ],
    }


def _gameplay_event_dict(event):
    source = getattr(event, 'source', None)
    if source is None:
        return model_to_dict(event)
    shown = model_to_dict(source)
    shown.update({
        'after_alignment': deepcopy(event.after_alignment),
        'old_pitcher_id': event.old_pitcher_id,
        'new_pitcher_id': event.new_pitcher_id,
    })
    return shown


def _broadcast_state(game_id, team_id):
    state = get_authoritative_live_state(game_id, team_id)
    if state:
        socketio.emit('game_state_update', state, room=_room_name(team_id, game_id))
    return state


def _event(game, team_id, event_type, inning, before_alignment, after_alignment,
           old_pitcher_id=None, new_pitcher_id=None, pre_start=None):
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
        pre_start=pre_start,
    )
    db.session.add(event)
    return event


@live_game_api_bp.route('/<int:game_id>/state', methods=['GET'])
def state(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403
    return jsonify(
        get_authoritative_live_state(
            game.id,
            team.id,
            game=game,
        )
    )


@live_game_api_bp.route('/<int:game_id>/start', methods=['POST'])
def start(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403

    # This request holds the game's write lock from before this view until
    # teardown (live_game_write_lock.py), and /save_rotation takes the same
    # lock, so the plan read here is the plan the game starts with.
    data = request.get_json(silent=True) or {}

    # Start turns the plan into the official game, so it must say which 1st
    # inning the coach reviewed. A request without one (a tab from before
    # this contract, a script) never starts: it is asked to refresh, not
    # allowed to skip the check.
    reviewed = data.get('inning_one')
    if not isinstance(reviewed, dict):
        return jsonify({
            'status': 'error',
            'code': 'start_refresh_required',
            'title': 'Refresh Prepare Game before starting.',
            'message': "CoachBoard needs to verify the 1st inning defense you're starting with.",
        }), 409

    start_readiness = can_start_game(game, team)

    # The 1st-inning defense the coach reviewed must be the stored one.
    if normalized_inning_one(reviewed, required_positions(team)) != start_readiness['inning_one']:
        return jsonify({
            'status': 'error',
            'code': 'start_defense_changed',
            'message': 'The 1st inning defense changed. Review it before starting.',
            **start_readiness,
        }), 409

    if not start_readiness['ready']:
        return jsonify({
            'status': 'error',
            'code': 'start_hard_stops',
            'message': 'Game is not ready to start.',
            **start_readiness,
        }), 409

    # Open fielding positions are the coach's call, acknowledged for exactly
    # the positions open now: an acknowledgement of CF no longer counts once
    # CF is filled or LF opens.
    open_positions = start_readiness['open_positions']
    if open_positions:
        acknowledged = data.get('open_positions')
        if not isinstance(acknowledged, list) or sorted({str(item) for item in acknowledged}) != sorted(open_positions):
            question = start_readiness['open_question']
            return jsonify({
                'status': 'error',
                'code': 'start_open_positions',
                'message': question['message'],
                'acknowledgement_outdated': acknowledged is not None,
                **start_readiness,
            }), 409

    # Last, the starting pitcher: the same eligibility classification and
    # decisions as every live pitching change, evaluated fresh here. A
    # decision never gets past any check above.
    from blueprints.live_game_bulk_api import (
        start_pitching_decision_row,
        starting_pitcher_check,
    )
    starter = start_readiness['inning_one']['P']
    pitching_question, pitching_decision = starting_pitcher_check(game, team, starter, data)
    if pitching_question is not None:
        response, status_code = pitching_question
        body = response.get_json()
        return jsonify({**start_readiness, **body}), status_code

    # The game going live and the record of an accepted pitching decision
    # commit together: if the record can't be written, the game doesn't start.
    try:
        # Start Game starts the 1st inning with the defense just verified,
        # in the same commit as the game going live.
        first = str(game.live_current_inning or '1')
        if not inning_has_started(game, team.id, first):
            _, planned = _planned_rotation(game, team.id)
            _record_inning_start(game, team.id, first, planned.get(first) or start_readiness['inning_one'])
        game.is_live = True
        if not game.live_current_inning:
            game.live_current_inning = '1'
        if pitching_decision:
            db.session.add(start_pitching_decision_row(user, team, game, starter, pitching_decision))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Start Game for game %s could not be saved', game_id)
        return jsonify({
            'status': 'error',
            'code': 'start_not_saved',
            'message': "The game didn't start because CoachBoard couldn't save it. Try again.",
        }), 500
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

    stale = _stale_write_response(
        data,
        game,
        team,
    )
    if stale:
        return stale

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
        pre_start=False,
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

    stale = _stale_write_response(
        data,
        game,
        team,
    )
    if stale:
        return stale

    try:
        player_id = int(data.get('player_id'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Select a valid player.'}), 400
    destination = (data.get('destination_position') or 'BENCH').upper()

    player = db.session.query(Player).filter_by(id=player_id, team_id=team.id).first()
    if not player:
        return jsonify({'status': 'error', 'message': 'Player is not on this team.'}), 400

    availability = game_availability(game, team.id)
    if not availability.is_present(player.id):
        return jsonify({
            'status': 'error',
            'message': f'{player.name} is not available for this game.',
        }), 409

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

    present_names = {
        p.name
        for p in db.session.query(Player).filter_by(team_id=team.id).all()
        if availability.is_present(p.id)
    }
    valid, message = _validate_alignment(after, present_names)
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
        pre_start=False,
    )
    db.session.commit()
    state = _broadcast_state(game.id, team.id)
    return jsonify({'status': 'success', 'state': state})


@live_game_api_bp.route('/<int:game_id>/end-inning', methods=['POST'])
def end_inning(game_id):
    user, team, game = _authorized_context(game_id)

    if not game:
        return jsonify({
            'status': 'error',
            'message': 'Unauthorized or game not found.',
        }), 403

    return jsonify({
        'status': 'error',
        'code': 'legacy_live_write_disabled',
        'message': (
            'This End Inning action is no longer available from here. '
            'Use End Inning on the live game screen — it applies the '
            'prepared NEXT defense and advances the inning immediately.'
        ),
    }), 409

@live_game_api_bp.route('/<int:game_id>/undo', methods=['POST'])
def undo(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403

    data = request.get_json(silent=True) or {}

    stale = _stale_write_response(
        data,
        game,
        team,
    )
    if stale:
        return stale

    # Undo is for the coach's own changes. An 'Inning Started' marker is
    # bookkeeping (game_availability): Undo passes over it, so undoing the
    # change that followed "Yes, inning started" leaves the inning started.
    last_event = db.session.query(GameRotationEvent).filter(
        GameRotationEvent.game_id == game.id,
        GameRotationEvent.team_id == team.id,
        GameRotationEvent.reverted.is_(False),
        GameRotationEvent.event_type != INNING_STARTED,
    ).order_by(GameRotationEvent.sequence.desc(), GameRotationEvent.id.desc()).first()
    if not last_event:
        return jsonify({'status': 'error', 'message': 'There is nothing to undo.'}), 409

    last_event.reverted = True
    if last_event.event_type == 'End Inning':
        # The inning it loaded is no longer being played, so neither is its
        # start: a later End Inning into it begins unstarted again.
        db.session.query(GameRotationEvent).filter_by(
            game_id=game.id,
            team_id=team.id,
            inning=str(last_event.inning),
            event_type=INNING_STARTED,
            reverted=False,
        ).update({'reverted': True}, synchronize_session='fetch')

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
