"""The live game page uses one live connection and handles each update once.

The board, the game page and the clock each called io(), and each call
opened its own Socket.IO connection, all joined to the same game room: every
broadcast arrived three times, and after a pitching change each copy forced
its own full /state download. They now share one connection. Each script
still gets its own handlers -- the clock's updates arrive, and after a lost
connection the page recovers what it missed and keeps receiving changes.
The page's own changes (End Inning, Change Pitcher) show from their own
response, so they no longer depend on the broadcast coming back.
"""

import os
import time

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from live_fixtures import (  # noqa: E402,F401 (live is a fixture)
    INNING_1,
    PHONE,
    api_url as _api,
    last_sequence as _sequence,
    game_state as _state,
    live,
)


LUKE, MATEO, OWEN = INNING_1['P'], INNING_1['1B'], INNING_1['2B']
PITCHER = '#cbQuickDefense [data-cb-position="P"]'


def _watch(page):
    """Every live connection, every message it receives, every /state GET."""
    seen = {'sockets': [], 'frames': [], 'state_gets': []}

    def on_socket(ws):
        seen['sockets'].append(ws)
        ws.on('framereceived', lambda payload: seen['frames'].append((time.monotonic(), str(payload))))

    page.on('websocket', on_socket)
    page.on('request', lambda request: seen['state_gets'].append(time.monotonic())
            if request.method == 'GET' and request.url.split('?')[0].endswith('/state') else None)
    return seen


def _open(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_function('() => window.__cbLiveGameSocket?.connected === true', timeout=10_000)
    page.wait_for_timeout(2_500)            # the clock script loads later and asks for a connection too


def _messages(seen, event):
    return [(at, frame) for at, frame in seen['frames'] if frame.startswith(f'42["{event}"')]


def _change_pitcher(page, coachboard_url, name, destination):
    """Another coach's Change Pitcher (the route the board uses): name
    pitches, the pitcher takes destination (name's old spot)."""
    state = _state(page, coachboard_url)
    player = next(p['id'] for p in state['roster'] if p['name'] == name)
    alignment = {pos: who for pos, who in state['current_alignment'].items() if who}
    alignment[destination], alignment['P'] = alignment['P'], name
    response = page.cb_api.request.post(_api(page, coachboard_url, 'complete-pitcher-change'), data={
        'base_sequence': _sequence(state), 'new_pitcher_id': player, 'alignment': alignment, 'fast': True})
    assert response.ok, response.text()[:300]


def test_one_connection_each_update_once(live, coachboard_url):
    page = live(PHONE)
    seen = _watch(page)
    _open(page, coachboard_url)
    assert len(seen['sockets']) == 1, [ws.url for ws in seen['sockets']]

    # Another coach changes pitchers: Mateo in from 1B, Luke to 1B.
    _change_pitcher(page, coachboard_url, MATEO, '1B')
    expect(page.locator(PITCHER)).to_contain_text(MATEO, timeout=10_000)
    page.wait_for_timeout(1_500)

    deltas = _messages(seen, 'live_game_delta')
    assert len(deltas) == 1, [frame[:80] for _, frame in deltas]
    # The page reads the full state once for it (who may no longer pitch).
    arrived = deltas[0][0]
    assert sum(1 for at in seen['state_gets'] if arrived - 0.05 <= at <= arrived + 0.4) == 1

    # The clock, which asked for a connection after it was open, still
    # gets its updates live (its own poll is every 15 s).
    response = page.cb_api.request.post(_api(page, coachboard_url, 'clock'), data={'time_limit_minutes': 75})
    assert response.ok, response.text()[:300]
    page.wait_for_timeout(1_500)
    assert len(_messages(seen, 'game_clock_update')) == 1
    # The clock card can sit in a collapsed section on a phone: its text, not what is on screen.
    page.wait_for_function(
        "() => (document.getElementById('cbLiveGameClock')?.textContent || '').includes('1:15 time limit')",
        timeout=2_000)
    assert page.cb_errors == []


def test_a_lost_connection_recovers_and_keeps_listening(live, coachboard_url):
    page = live(PHONE)
    seen = _watch(page)
    _open(page, coachboard_url)

    page.evaluate('() => window.__cbLiveGameSocket.disconnect()')
    # Missed while disconnected: Mateo in from 1B.
    _change_pitcher(page, coachboard_url, MATEO, '1B')
    page.wait_for_timeout(1_000)
    expect(page.locator(PITCHER)).to_contain_text(LUKE)

    page.evaluate('() => window.__cbLiveGameSocket.connect()')
    expect(page.locator(PITCHER)).to_contain_text(MATEO, timeout=10_000)   # recovered on reconnect
    page.wait_for_timeout(1_000)

    # Back in the room: the next change arrives live, once.
    before = len(_messages(seen, 'live_game_delta'))
    _change_pitcher(page, coachboard_url, OWEN, '2B')
    expect(page.locator(PITCHER)).to_contain_text(OWEN, timeout=10_000)
    page.wait_for_timeout(800)
    assert len(_messages(seen, 'live_game_delta')) == before + 1
    # A reconnect opens a new transport for the same connection: one open at a time.
    assert sum(1 for ws in seen['sockets'] if not ws.is_closed()) == 1
    assert page.cb_errors == []


def test_the_coachs_own_change_shows_while_disconnected(live, coachboard_url):
    # The page's own write answers with the change; it no longer waits for
    # the broadcast to come back over the live connection.
    page = live(PHONE)
    _open(page, coachboard_url)
    page.evaluate('() => window.__cbLiveGameSocket.disconnect()')
    page.locator('#liveEndInningBtn').click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=10_000)
    assert str(_state(page, coachboard_url)['current_inning']) == '2'
    assert page.cb_errors == []
