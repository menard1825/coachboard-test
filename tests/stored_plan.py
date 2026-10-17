"""A game's pregame plan saved from a test, the way a coach's page saves it.

/save_rotation refuses a game's plan without ``base_innings`` (the stored plan
the change was made from; see rotation_merge.py). A test that saves a plan is
one coach making one change, so its base is the plan the server holds right
now -- read from the server, never assumed.
"""

import json


def stored_plan(client, game_id):
    response = client.get(f'/api/game_data/{game_id}')
    assert response.status_code == 200, response.get_data(as_text=True)[:200]
    rotation = (response.get_json() or {}).get('rotation') or {}
    innings = rotation.get('innings') or {}
    return json.loads(innings) if isinstance(innings, str) else innings


def with_stored_base(client, payload):
    return {**payload, 'base_innings': stored_plan(client, payload['associated_game_id'])}
