from collections import defaultdict

from eventlet.semaphore import Semaphore
from flask import Blueprint, g, request

from db import db
from models import GameRotationEvent


live_game_write_lock_bp = Blueprint('live_game_write_lock', __name__)

# The current CoachBoard deployment is one Socket.IO process. These per-game
# semaphores prevent two coach requests from calculating event state/sequence
# from the same snapshot at the same time. If CoachBoard is later deployed with
# multiple worker processes, move this coordination to a database/Redis lock or
# optimistic version column shared by all workers.
_game_locks = defaultdict(lambda: Semaphore(1))


def _live_game_write():
    endpoint = request.endpoint or ''
    return request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and (
        endpoint.startswith('live_game_api.')
        or endpoint.startswith('live_game_bulk.')
        or endpoint.startswith('live_game_pitching.')
        or endpoint.startswith('live_game_clock.')
        or endpoint == 'live_game_ui.next_inning_prep'
    )


def _effective_live_sequence(game_id, team_id):
    """Return the sequence for the currently active live state.

    An Undo reverts the latest event instead of inserting another rotation
    event. Using the latest *unreverted* event as the optimistic-write version
    therefore makes an Undo invalidate editor screens that were opened before
    the undo. Fresh clients calculate the same value from rotation_events.
    """
    last_event = db.session.query(GameRotationEvent).filter_by(
        game_id=game_id,
        team_id=team_id,
        reverted=False,
    ).order_by(GameRotationEvent.sequence.desc(), GameRotationEvent.id.desc()).first()
    return int(last_event.sequence or 0) if last_event else 0


# live_game_bulk_api owns the staged-defense endpoints, while this module owns
# write serialization. Keep their optimistic version definition identical so an
# Undo cannot be silently overwritten by a coach who had an older editor open.
from blueprints import live_game_bulk_api as _live_game_bulk_module
_live_game_bulk_module._current_sequence = _effective_live_sequence


@live_game_write_lock_bp.before_app_request
def serialize_live_game_write():
    if not _live_game_write():
        return None

    try:
        game_id = int((request.view_args or {}).get('game_id'))
    except (TypeError, ValueError):
        return None

    lock = _game_locks[game_id]
    lock.acquire()
    g.coachboard_live_game_lock = lock
    return None


@live_game_write_lock_bp.teardown_app_request
def release_live_game_write_lock(error=None):
    lock = getattr(g, 'coachboard_live_game_lock', None)
    if lock is not None:
        lock.release()
