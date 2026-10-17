"""Saving a game's pregame plan from test setup, the way a coach's page does.

/save_rotation refuses a game's plan without ``base_innings``: the stored
plan the change was made from, so the server can tell when another coach
saved in between (rotation_merge.py). A coach's page starts from the plan
stored when it loaded. Test setup that writes a plan over the API is one
coach making one change, so its base is the plan stored right now -- read
from the server, never assumed (a game nobody has opened has no plan yet,
so its base really is empty).
"""

import json


def stored_plan(request, base_url, game_id):
    """The game's plan exactly as the server holds it now ({} if none)."""
    response = request.get(f'{base_url}/api/game_data/{game_id}')
    assert response.ok, response.text()[:200]
    rotation = response.json().get('rotation') or {}
    innings = rotation.get('innings') or {}
    return json.loads(innings) if isinstance(innings, str) else innings


def with_stored_base(request, base_url, payload):
    """``payload`` for /save_rotation, with the stored plan as its base."""
    return {**payload, 'base_innings': stored_plan(request, base_url, payload['associated_game_id'])}
