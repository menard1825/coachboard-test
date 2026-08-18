from collections import defaultdict

from eventlet.semaphore import Semaphore
from flask import Blueprint, g, request


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


@live_game_write_lock_bp.teardown_app_request
def release_live_game_write_lock(error=None):
    lock = getattr(g, 'coachboard_live_game_lock', None)
    if lock is not None:
        lock.release()
