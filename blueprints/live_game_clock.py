from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request
from sqlalchemy import UniqueConstraint

from db import db
from extensions import socketio
from models import Game, GameRotationEvent
from blueprints.live_game_api import _authorized_context, _broadcast_state


live_game_clock_bp = Blueprint('live_game_clock', __name__, url_prefix='/api/live-game')


class GameClockState(db.Model):
    __tablename__ = 'game_clock_states'

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    time_limit_minutes = db.Column(db.Integer, nullable=True)
    end_reason = db.Column(db.String(32), nullable=True)
    last_played_inning = db.Column(db.String, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)

    __table_args__ = (
        UniqueConstraint('game_id', 'team_id', name='uq_game_clock_state_game_team'),
    )


def _clock_row(game_id, team_id, create=False):
    row = db.session.query(GameClockState).filter_by(game_id=game_id, team_id=team_id).first()
    if row is None and create:
        row = GameClockState(game_id=game_id, team_id=team_id)
        db.session.add(row)
    return row


def _iso_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace('+00:00', 'Z')


def _inning_number(value):
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _clock_payload(game, row):
    now = datetime.utcnow()
    started = row.started_at if row else None
    ended = row.ended_at if row else None
    elapsed = None
    if started:
        stop = ended or now
        elapsed = max(0, int((stop - started).total_seconds()))

    limit_minutes = row.time_limit_minutes if row else None
    remaining = None
    if elapsed is not None and limit_minutes:
        remaining = (int(limit_minutes) * 60) - elapsed

    return {
        'game_id': game.id,
        'is_live': bool(game.is_live),
        'current_inning': str(game.live_current_inning or '1'),
        'started_at_utc': _iso_utc(started),
        'ended_at_utc': _iso_utc(ended),
        'elapsed_seconds': elapsed,
        'time_limit_minutes': limit_minutes,
        'remaining_seconds': remaining,
        'end_reason': row.end_reason if row else None,
        'last_played_inning': row.last_played_inning if row else None,
    }


def _emit_clock(game, team_id, row=None):
    row = row or _clock_row(game.id, team_id)
    payload = _clock_payload(game, row)
    socketio.emit(
        'game_clock_update',
        payload,
        room=f'team_{team_id}_game_{game.id}',
    )
    return payload


def _response_succeeded(response):
    return 200 <= int(getattr(response, 'status_code', 500)) < 300


def _current_inning_has_recorded_activity(game, team_id):
    """Return True when current-inning live changes prove that inning was used."""
    current = str(game.live_current_inning or '1')
    transition = db.session.query(GameRotationEvent).filter_by(
        game_id=game.id,
        team_id=team_id,
        inning=current,
        event_type='End Inning',
        reverted=False,
    ).order_by(GameRotationEvent.sequence.desc(), GameRotationEvent.id.desc()).first()
    transition_sequence = int(transition.sequence or 0) if transition else 0

    events = db.session.query(GameRotationEvent).filter_by(
        game_id=game.id,
        team_id=team_id,
        inning=current,
        reverted=False,
    ).order_by(GameRotationEvent.sequence.asc(), GameRotationEvent.id.asc()).all()

    return any(
        event.event_type not in {'End Inning', 'End Game'}
        and int(event.sequence or 0) > transition_sequence
        for event in events
    )


def _adjust_unplayed_current_inning(game, team_id):
    """Exclude a next inning that was loaded but never actually started.

    End Inning stores the transition using the *next* inning number. If time is
    called after that transition but before play starts, revert that transition
    and move the durable End Game marker back to the last inning actually played.
    """
    current = _inning_number(game.live_current_inning)
    if current is None or current <= 1:
        return str(game.live_current_inning or '1')

    previous = str(current - 1)
    current_key = str(current)

    transition = db.session.query(GameRotationEvent).filter_by(
        game_id=game.id,
        team_id=team_id,
        inning=current_key,
        event_type='End Inning',
        reverted=False,
    ).order_by(GameRotationEvent.sequence.desc(), GameRotationEvent.id.desc()).first()

    prior_alignment = None
    if transition:
        prior_alignment = dict(transition.before_alignment or {})
        transition.reverted = True

    end_event = db.session.query(GameRotationEvent).filter_by(
        game_id=game.id,
        team_id=team_id,
        event_type='End Game',
        reverted=False,
    ).order_by(GameRotationEvent.sequence.desc(), GameRotationEvent.id.desc()).first()

    if end_event:
        end_event.inning = previous
        if prior_alignment:
            end_event.before_alignment = prior_alignment
            end_event.after_alignment = prior_alignment

    game.live_current_inning = previous
    return previous


def _recover_running_clock(game, team_id, row):
    """Give games already live before this feature a sensible persisted start."""
    if not game.is_live or (row and row.started_at):
        return row

    row = row or _clock_row(game.id, team_id, create=True)
    first_event = db.session.query(GameRotationEvent).filter_by(
        game_id=game.id,
        team_id=team_id,
        reverted=False,
    ).order_by(GameRotationEvent.sequence.asc(), GameRotationEvent.id.asc()).first()
    row.started_at = first_event.timestamp if first_event and first_event.timestamp else datetime.utcnow()
    row.ended_at = None
    row.end_reason = None
    row.last_played_inning = str(game.live_current_inning or '1')
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return row


@live_game_clock_bp.route('/<int:game_id>/clock', methods=['GET', 'POST'])
def game_clock(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403

    row = _clock_row(game.id, team.id, create=request.method == 'POST')
    if request.method == 'GET':
        row = _recover_running_clock(game, team.id, row)
        return jsonify({'status': 'success', 'clock': _clock_payload(game, row)})

    data = request.get_json(silent=True) or {}
    action = str(data.get('action') or '').strip().lower()

    if 'time_limit_minutes' in data:
        raw_limit = data.get('time_limit_minutes')
        if raw_limit in (None, '', 0, '0'):
            row.time_limit_minutes = None
        else:
            try:
                minutes = int(raw_limit)
            except (TypeError, ValueError):
                return jsonify({'status': 'error', 'message': 'Enter a valid game time limit in minutes.'}), 400
            if minutes < 15 or minutes > 300:
                return jsonify({'status': 'error', 'message': 'Game time limit must be between 15 and 300 minutes.'}), 400
            row.time_limit_minutes = minutes

    if action == 'restart':
        if not game.is_live:
            return jsonify({'status': 'error', 'message': 'The game clock can only be restarted while Live Game is active.'}), 409
        row.started_at = datetime.utcnow()
        row.ended_at = None
        row.end_reason = None
        row.last_played_inning = str(game.live_current_inning or '1')

    row.updated_at = datetime.utcnow()
    db.session.commit()
    payload = _emit_clock(game, team.id, row)
    return jsonify({'status': 'success', 'clock': payload})


@live_game_clock_bp.before_app_request
def capture_live_game_clock_lifecycle():
    if request.method != 'POST':
        return None

    endpoint = request.endpoint or ''
    if endpoint not in {'live_game_api.start', 'live_game_pitching.end_with_pitching'}:
        return None

    try:
        game_id = int((request.view_args or {}).get('game_id'))
    except (TypeError, ValueError):
        return None

    user, team, game = _authorized_context(game_id)
    if not game:
        return None

    g.coachboard_clock_game_id = game.id
    g.coachboard_clock_team_id = team.id
    g.coachboard_clock_was_live = bool(game.is_live)
    if endpoint == 'live_game_pitching.end_with_pitching':
        data = request.get_json(silent=True) or {}
        g.coachboard_clock_end_payload = data
        reason = str(data.get('end_reason') or '').strip().lower()
        current_played = data.get('current_inning_played', True)
        if isinstance(current_played, str):
            current_played = current_played.strip().lower() not in {'0', 'false', 'no', 'off'}
        else:
            current_played = bool(current_played)

        if reason == 'time_limit' and not current_played and _current_inning_has_recorded_activity(game, team.id):
            return jsonify({
                'status': 'error',
                'message': (
                    f'Inning {game.live_current_inning} already has a recorded live change, so CoachBoard will not erase it as unplayed. '
                    'Choose that the inning was played, or undo the recorded change first.'
                ),
            }), 409
    return None


@live_game_clock_bp.after_app_request
def persist_live_game_clock_lifecycle(response):
    if not _response_succeeded(response):
        return response

    endpoint = request.endpoint or ''
    game_id = getattr(g, 'coachboard_clock_game_id', None)
    team_id = getattr(g, 'coachboard_clock_team_id', None)
    if not game_id or not team_id:
        return response

    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if not game:
        return response

    if endpoint == 'live_game_api.start':
        row = _clock_row(game.id, team_id, create=True)
        if row.started_at is None or row.ended_at is not None:
            row.started_at = datetime.utcnow()
        row.ended_at = None
        row.end_reason = None
        row.last_played_inning = '1'
        row.updated_at = datetime.utcnow()
        db.session.commit()
        _emit_clock(game, team_id, row)
        return response

    if endpoint == 'live_game_pitching.end_with_pitching' and getattr(g, 'coachboard_clock_was_live', False):
        data = getattr(g, 'coachboard_clock_end_payload', {}) or {}
        reason = str(data.get('end_reason') or 'manual').strip().lower()
        if reason not in {'time_limit', 'regulation', 'run_rule', 'weather', 'manual', 'other'}:
            reason = 'other'

        current_played = data.get('current_inning_played', True)
        if isinstance(current_played, str):
            current_played = current_played.strip().lower() not in {'0', 'false', 'no', 'off'}
        else:
            current_played = bool(current_played)

        last_played = str(game.live_current_inning or '1')
        if reason == 'time_limit' and not current_played:
            last_played = _adjust_unplayed_current_inning(game, team_id)

        row = _clock_row(game.id, team_id, create=True)
        row.started_at = row.started_at or datetime.utcnow()
        row.ended_at = row.ended_at or datetime.utcnow()
        row.end_reason = reason
        row.last_played_inning = last_played
        row.updated_at = datetime.utcnow()
        db.session.commit()

        # The normal end workflow broadcasts before this hook runs. Broadcast one
        # corrected authoritative state if we rolled back an unplayed next inning.
        _broadcast_state(game.id, team_id)
        _emit_clock(game, team_id, row)

    return response
