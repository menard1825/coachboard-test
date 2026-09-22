"""Browser coverage for the readiness publisher/subscriber handoff.

game_prep_readiness.js polls /api/game-day/<id>/readiness every 5s for its own
pregame panel and now publishes each successful response as
``coachboard:readiness``. game_setup_ux.js consumes that event to drive the
Start Game button and blocker list, and no longer runs an 8s readiness poller.

These tests assert the behaviour the structural guardrails in
tests/test_readiness_event_contract.py cannot see: that the event actually
carries a usable payload, that the Start Game UI updates from it without a
second network request, that a mismatched game is rejected, and that the two
direct-fetch fallbacks still work.

OWNERSHIP: after this slice the owner's 5s poll is the Start Game UI's only
periodic readiness source. Do not gate that poll -- including the "free"
is_live gate the polling audit identified -- without first giving
game_setup_ux.js another periodic source.
"""

import os
import re
import time
from datetime import date, timedelta
from urllib.parse import urlencode

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

OWNER = 'game_prep_readiness.js'
SUBSCRIBER = 'game_setup_ux.js'
QUICK_START = 'pregame_quick_start.js'

# Two application modules override window.fetch (live_game_feedback_pass.js:33
# and live_game_inning_clarity.js:105). Their frames sit between the real
# caller and this probe, so an unfiltered stack blames 100% of readiness
# traffic on whichever wrapper loaded last.
WRAPPERS = ('live_game_feedback_pass.js', 'live_game_inning_clarity.js')

READINESS_PATH = re.compile(r'^/api/game-day/\d+/readiness$')

PROBE = """
(() => {
  window.__cbProbe = {events: [], requests: [], uiUpdates: 0};
  const wrappers = %WRAPPERS%;
  const nativeFetch = window.fetch.bind(window);

  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : input?.url;
    try {
      const path = new URL(url, window.location.href).pathname;
      const frames = ((new Error()).stack || '')
        .split('\\n')
        .map(line => (line.match(/([\\w.-]+\\.js)/) || [])[1])
        .filter(Boolean)
        .filter(name => !wrappers.includes(name));
      window.__cbProbe.requests.push({path, caller: frames[0] || 'unknown'});
    } catch (_) {}
    return nativeFetch(input, init);
  };

  document.addEventListener('coachboard:readiness', event => {
    const detail = event?.detail;
    window.__cbProbe.events.push({
      game_id: detail?.game_id,
      keys: Object.keys(detail?.response || {}).sort(),
      ready: detail?.response?.ready,
      missing: detail?.response?.missing,
      is_live: detail?.response?.readiness?.is_live,
    });
  });

  // One applyStartReadiness() call rewrites #start-live-blockers' class and
  // innerHTML, so it lands as exactly one MutationObserver callback. Counting
  // callbacks therefore counts application updates, which is how we detect a
  // single owner fetch producing two updates.
  new MutationObserver(records => {
    const touched = records.some(record => {
      const node = record.target.nodeType === 1
        ? record.target
        : record.target.parentElement;
      return Boolean(node?.closest?.('#start-live-blockers'));
    });
    if (touched) window.__cbProbe.uiUpdates += 1;
  // Observe `document`, not document.documentElement: this runs as an init
  // script before <html> is parsed, where documentElement is still null and
  // observe() throws -- silently, leaving the counter permanently at zero.
  }).observe(document, {
    attributes: true, childList: true, subtree: true, characterData: true,
  });
})();
""".replace('%WRAPPERS%', repr(list(WRAPPERS)).replace("'", '"'))


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    identity = page.get_by_label('Username or email')
    if identity.count() == 0:
        page.goto(f'{coachboard_url}/logout')
        expect(page).to_have_url(re.compile(r'/login$'))
        identity = page.get_by_label('Username or email')
    identity.fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(
        re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:games|overview))?$')
    )


def post_json(page: Page, coachboard_url: str, path: str, data):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == 200, f'POST {path} -> {response.status}: {response.text()}'
    payload = response.json()
    assert payload.get('status') == 'success', payload
    return payload


def alignment():
    return {
        'P': 'Pitcher Pat',
        'C': 'Catcher Cole',
        '1B': 'First Frank',
        '2B': 'Second Sam',
        '3B': 'Third Theo',
        'SS': 'Shortstop Shawn',
        'LF': 'Left Lee',
        'CF': 'Center Casey',
        'RF': 'Right Riley',
    }


def create_ready_pregame_game(page: Page, coachboard_url: str, opponent: str):
    """A pregame game that can_start_game() reports as ready."""
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=11)).isoformat(),
            'game_start_time': '11:00',
            'game_opponent': opponent,
            'game_location': 'Readiness Handoff Field',
            'game_notes': 'Disposable readiness-handoff browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}, response.status
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match, response.headers
    game_id = int(match.group(1))

    roster = page.request.get(f'{coachboard_url}/api/roster').json()
    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Readiness Handoff Lineup',
        'lineup_player_ids': [int(player['id']) for player in roster],
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Readiness Handoff Rotation',
        'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })

    readiness = page.request.get(
        f'{coachboard_url}/api/game-day/{game_id}/readiness'
    ).json()
    assert readiness['ready'] is True, readiness
    return game_id, roster


def delete_game(page: Page, coachboard_url: str, game_id: int):
    state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
    if state.ok and state.json().get('game', {}).get('is_live'):
        page.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/end-with-pitching',
            data={
                'defer_pitching': True,
                'end_reason': 'manual',
                'current_inning_played': True,
            },
        )
    page.request.post(
        f'{coachboard_url}/game-day/{game_id}/delete',
        headers={'Accept': 'application/json'},
    )


def set_absences(page: Page, coachboard_url: str, game_id: int, player_ids):
    # absent_players repeats, and Playwright's form= takes a dict, so the body
    # is built by hand rather than losing every key but the last.
    body = urlencode([('absent_players', str(pid)) for pid in player_ids] or [('absent_players', '')])
    response = page.request.post(
        f'{coachboard_url}/game/{game_id}/update_absences',
        data=body,
        headers={'content-type': 'application/x-www-form-urlencoded'},
        max_redirects=0,
    )
    assert response.status in {200, 302, 303}, f'{response.status}: {response.text()}'


def open_game_page(page: Page, coachboard_url: str, game_id: int):
    page.add_init_script(PROBE)
    page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
    expect(page.locator('#startLiveGameBtnAction')).to_have_count(1, timeout=20_000)


def readiness_requests(page: Page):
    return [
        request for request in page.evaluate('window.__cbProbe.requests')
        if READINESS_PATH.match(request['path'])
    ]


def attribution(requests):
    counts = {}
    for request in requests:
        counts[request['caller']] = counts.get(request['caller'], 0) + 1
    return counts


def test_one_owner_fetch_publishes_exactly_one_readiness_event(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id, _ = create_ready_pregame_game(page, coachboard_url, 'Handoff Publish')
    try:
        open_game_page(page, coachboard_url, game_id)

        page.wait_for_function(
            'window.__cbProbe.events.length >= 1', timeout=20_000
        )
        page.evaluate('window.__cbProbe.events = []; window.__cbProbe.requests = [];')

        # Two owner ticks at 5s.
        page.wait_for_function(
            'window.__cbProbe.events.length >= 2', timeout=20_000
        )
        events = page.evaluate('window.__cbProbe.events')
        owner_fetches = [
            request for request in readiness_requests(page)
            if request['caller'] == OWNER
        ]

        assert len(events) == len(owner_fetches), (
            f'{len(owner_fetches)} owner fetches produced {len(events)} events; '
            'one successful fetch must publish exactly one event.'
        )

        for event in events:
            assert event['game_id'] == game_id
            # The full endpoint response, not just data.readiness: the
            # subscriber needs top-level ready/missing as well as
            # readiness.is_live.
            assert set(event['keys']) >= {'missing', 'readiness', 'ready', 'status'}, event
            assert isinstance(event['ready'], bool), event
            assert isinstance(event['missing'], list), event
            assert event['is_live'] is False, event
    finally:
        delete_game(page, coachboard_url, game_id)


def test_the_start_game_ui_consumes_the_event_without_its_own_request(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id, _ = create_ready_pregame_game(page, coachboard_url, 'Handoff Consume')
    try:
        open_game_page(page, coachboard_url, game_id)
        expect(page.locator('#startLiveGameBtnAction')).to_be_enabled(timeout=20_000)

        # Dispatch and read back synchronously: the listener runs inline, so
        # there is no window for the owner's real poll to interleave.
        result = page.evaluate(
            """(gameId) => {
              window.__cbProbe.requests = [];
              document.dispatchEvent(new CustomEvent('coachboard:readiness', {
                detail: {
                  game_id: gameId,
                  response: {
                    status: 'success',
                    ready: false,
                    missing: ['SYNTHETIC BLOCKER ONE', 'SYNTHETIC BLOCKER TWO'],
                    readiness: {is_live: false},
                  },
                },
              }));
              const button = document.getElementById('startLiveGameBtnAction');
              const box = document.getElementById('start-live-blockers');
              return {
                disabled: button.disabled,
                text: box ? box.textContent : null,
                hidden: box ? box.classList.contains('d-none') : null,
                requests: window.__cbProbe.requests.map(item => item.path),
              };
            }""",
            game_id,
        )

        assert result['disabled'] is True, result
        assert result['hidden'] is False, result
        assert 'SYNTHETIC BLOCKER ONE' in result['text'], result
        assert 'SYNTHETIC BLOCKER TWO' in result['text'], result
        assert [path for path in result['requests'] if READINESS_PATH.match(path)] == [], (
            f'Consuming the event issued a readiness request: {result["requests"]}'
        )
    finally:
        delete_game(page, coachboard_url, game_id)


def test_a_readiness_event_for_another_game_is_ignored(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id, _ = create_ready_pregame_game(page, coachboard_url, 'Handoff Mismatch')
    try:
        open_game_page(page, coachboard_url, game_id)
        expect(page.locator('#startLiveGameBtnAction')).to_be_enabled(timeout=20_000)

        result = page.evaluate(
            """(gameId) => {
              document.dispatchEvent(new CustomEvent('coachboard:readiness', {
                detail: {
                  game_id: gameId + 1000,
                  response: {
                    status: 'success',
                    ready: false,
                    missing: ['BLOCKER FROM ANOTHER GAME'],
                    readiness: {is_live: false},
                  },
                },
              }));
              const button = document.getElementById('startLiveGameBtnAction');
              const box = document.getElementById('start-live-blockers');
              return {
                disabled: button.disabled,
                text: box ? box.textContent : '',
              };
            }""",
            game_id,
        )

        assert result['disabled'] is False, result
        assert 'BLOCKER FROM ANOTHER GAME' not in result['text'], result
    finally:
        delete_game(page, coachboard_url, game_id)


def test_start_button_converges_and_tracks_state_changes_from_the_owner_poll(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id, roster = create_ready_pregame_game(page, coachboard_url, 'Handoff Transition')
    try:
        open_game_page(page, coachboard_url, game_id)

        start_button = page.locator('#startLiveGameBtnAction')
        blockers = page.locator('#start-live-blockers')

        # Initial load converges via the subscriber's own direct fetch.
        expect(start_button).to_be_enabled(timeout=20_000)
        expect(blockers).to_contain_text('Ready for first pitch', timeout=20_000)

        # A readiness-relevant mutation the page never learns about by socket.
        page.evaluate('window.__cbProbe.requests = [];')
        set_absences(page, coachboard_url, game_id, [int(p['id']) for p in roster])

        # No reload, no interaction: the owner's next <=5s poll must carry it.
        expect(start_button).to_be_disabled(timeout=12_000)
        expect(blockers).to_contain_text(
            'Mark at least one player available', timeout=12_000
        )

        callers = attribution(readiness_requests(page))
        assert callers.get(SUBSCRIBER, 0) == 0, (
            f'The subscriber fetched readiness during a steady-state window: {callers}'
        )
        assert callers.get(OWNER, 0) >= 1, callers

        # And back.
        set_absences(page, coachboard_url, game_id, [])
        expect(start_button).to_be_enabled(timeout=12_000)
        expect(blockers).to_contain_text('Ready for first pitch', timeout=12_000)
    finally:
        delete_game(page, coachboard_url, game_id)


def test_hide_then_show_still_performs_the_direct_fallback_refresh(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id, _ = create_ready_pregame_game(page, coachboard_url, 'Handoff Fallback')
    try:
        open_game_page(page, coachboard_url, game_id)
        expect(page.locator('#startLiveGameBtnAction')).to_be_enabled(timeout=20_000)

        page.evaluate('window.__cbProbe.requests = [];')
        page.evaluate("""() => {
          Object.defineProperty(document, 'hidden', {value: true, configurable: true});
          Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true});
          document.dispatchEvent(new Event('visibilitychange'));
        }""")
        page.evaluate("""() => {
          Object.defineProperty(document, 'hidden', {value: false, configurable: true});
          Object.defineProperty(document, 'visibilityState', {value: 'visible', configurable: true});
          document.dispatchEvent(new Event('visibilitychange'));
        }""")

        page.wait_for_function(
            """(subscriber) => window.__cbProbe.requests.some(
                 item => /^\\/api\\/game-day\\/\\d+\\/readiness$/.test(item.path)
                   && item.caller === subscriber
               )""",
            arg=SUBSCRIBER,
            timeout=10_000,
        )
        callers = attribution(readiness_requests(page))
        assert callers.get(SUBSCRIBER, 0) >= 1, (
            f'Resume must still perform a direct fallback fetch: {callers}'
        )
    finally:
        delete_game(page, coachboard_url, game_id)


def test_one_owner_fetch_produces_one_application_update(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id, _ = create_ready_pregame_game(page, coachboard_url, 'Handoff Single Update')
    try:
        open_game_page(page, coachboard_url, game_id)
        expect(page.locator('#start-live-blockers')).to_be_visible(timeout=20_000)

        page.wait_for_function('window.__cbProbe.events.length >= 1', timeout=20_000)
        page.evaluate(
            'window.__cbProbe.events = []; window.__cbProbe.uiUpdates = 0;'
        )
        page.wait_for_function('window.__cbProbe.events.length >= 3', timeout=25_000)

        probe = page.evaluate(
            '({events: window.__cbProbe.events.length, ui: window.__cbProbe.uiUpdates})'
        )
        assert probe['ui'] == probe['events'], (
            f'{probe["events"]} owner events produced {probe["ui"]} Start Game UI '
            'updates; one fetch must drive exactly one update.'
        )
    finally:
        delete_game(page, coachboard_url, game_id)


@pytest.mark.parametrize('go_live', [False, True], ids=['pregame', 'live'])
def test_readiness_request_rate_characterization(page: Page, coachboard_url: str, go_live: bool):
    """A full 60s steady-state window, with per-module attribution."""
    login(page, coachboard_url)
    label = 'Rate Live' if go_live else 'Rate Pregame'
    game_id, _ = create_ready_pregame_game(page, coachboard_url, f'Handoff {label}')
    try:
        if go_live:
            post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
            state = page.request.get(
                f'{coachboard_url}/api/live-game/{game_id}/state'
            ).json()
            assert state['game']['is_live'] is True, state

        open_game_page(page, coachboard_url, game_id)
        page.wait_for_timeout(5_000)
        page.evaluate('window.__cbProbe.requests = [];')

        started = time.monotonic()
        page.wait_for_timeout(60_000)
        elapsed = time.monotonic() - started

        requests = readiness_requests(page)
        callers = attribution(requests)
        rate = len(requests) * 60.0 / elapsed

        print(f'\n===== {"LIVE" if go_live else "PREGAME"} /game/{game_id} '
              f'({elapsed:.1f}s) =====')
        print(f'  readiness total: {len(requests)} -> {rate:.1f}/min')
        for caller, count in sorted(callers.items(), key=lambda item: -item[1]):
            print(f'    {count:4d}  {count * 60.0 / elapsed:5.1f}/min  <- {caller}')

        assert callers.get(SUBSCRIBER, 0) == 0, (
            f'{SUBSCRIBER} must contribute no periodic readiness traffic: {callers}'
        )
        # The owner's 5s tick, allowing one tick of timer phase either way.
        assert 10 <= callers.get(OWNER, 0) <= 13, callers

        if go_live:
            assert callers.get(QUICK_START, 0) == 0, callers
            assert 10 <= len(requests) <= 14, f'{len(requests)} readiness requests'
        else:
            assert 5 <= callers.get(QUICK_START, 0) <= 7, callers
            assert 16 <= len(requests) <= 20, f'{len(requests)} readiness requests'
    finally:
        delete_game(page, coachboard_url, game_id)
