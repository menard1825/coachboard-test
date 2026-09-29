"""Start a live game the way the Start button does.

Start requires the 1st-inning defense the coach reviewed (`inning_one`) and
refuses a request without it. Test setup that starts a game over the API
sends the stored 1st inning -- what a coach looking at Prepare Game sees.
"""

import json


def stored_inning_one(request, base_url, game_id):
    rotation = request.get(f'{base_url}/api/game_data/{game_id}').json().get('rotation') or {}
    innings = rotation.get('innings') or {}
    if isinstance(innings, str):
        innings = json.loads(innings)
    return dict(innings.get('1') or {})


def start_body(request, base_url, game_id, **extra):
    return {'inning_one': stored_inning_one(request, base_url, game_id), **extra}
