"""Teardown helpers for browser tests that create games and players.

The browser suite shares one disposable database for the whole session, and
the team's roster is locked while any of its games is live: add_player and
delete_player refuse (with a redirect, or 409 for AJAX) until that game ends.
So a test that starts a live game and fails before ending it breaks every
later test that adds or removes players. Tests that start live games or add
players therefore release them in ``finally`` / fixture teardown with these
helpers, which are safe to call more than once and after a partial setup.
"""

END_LIVE_GAME = {'defer_pitching': True, 'end_reason': 'manual', 'current_inning_played': True}


def end_live_game(request, base_url, game_id):
    """End ``game_id`` if it is still live; return True when it is not live afterwards."""
    state = request.get(f'{base_url}/api/live-game/{game_id}/state')
    if not state.ok or not (state.json().get('game') or {}).get('is_live'):
        return True
    request.post(f'{base_url}/api/live-game/{game_id}/end-with-pitching', data=END_LIVE_GAME)
    state = request.get(f'{base_url}/api/live-game/{game_id}/state')
    return state.ok and not (state.json().get('game') or {}).get('is_live')


def release_game(request, base_url, game_id):
    """End (if live) and delete a game this test created."""
    if not game_id:
        return
    ended = end_live_game(request, base_url, game_id)
    request.post(f'{base_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
    assert ended, f'game {game_id} is still live after cleanup; the roster would stay locked'


def delete_players_named(request, base_url, names):
    """Delete this test's players by name; return the names still on the roster."""
    names = set(names)
    for player in request.get(f'{base_url}/api/roster').json():
        if player['name'] in names:
            request.get(f'{base_url}/delete_player/{player["id"]}')
    return sorted(p['name'] for p in request.get(f'{base_url}/api/roster').json() if p['name'] in names)
