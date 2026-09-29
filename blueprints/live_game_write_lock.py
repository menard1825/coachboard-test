from collections import defaultdict
from contextlib import contextmanager

from eventlet.semaphore import Semaphore
from flask import Blueprint, g, has_app_context, request


live_game_write_lock_bp = Blueprint('live_game_write_lock', __name__)

# This module owns write serialization only. The optimistic-write version that
# those serialized writes compare against is _current_sequence, which
# blueprints.live_game_api owns and blueprints.live_game_bulk_api imports
# normally. A copy of that calculation used to live here and was assigned over
# live_game_bulk_api's own definition at import time, so the function a reader
# found in that file was never the one that ran.

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


@contextmanager
def game_write_lock(game_id):
    """Hold the same per-game lock for a write outside the live-game routes.

    The pregame plan (/save_rotation) and the regulation-innings top-up read,
    check and write the game's rotation; holding this lock across all three
    means no live write for the game -- Start Game included -- can run in the
    middle, and vice versa. The semaphore is not reentrant, so a request that
    already holds it through serialize_live_game_write() is not blocked.
    """
    lock = _game_locks[int(game_id)]
    held = getattr(g, 'coachboard_live_game_lock', None) if has_app_context() else None
    if held is lock:
        yield
        return
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


@live_game_write_lock_bp.teardown_app_request
def release_live_game_write_lock(error=None):
    lock = getattr(g, 'coachboard_live_game_lock', None)
    if lock is not None:
        lock.release()
