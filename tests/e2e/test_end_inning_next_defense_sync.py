"""End Inning starts the next inning only from a settled, current plan.

Before it reads the server and sends the next inning's defense, End Inning
waits for:

* a Plan Undo the coach started -- all of it: the plan save it waits for,
  the Undo, and the answer the board adopts (CBNextDefense.flush() waits on
  the whole Undo). Refused, it stops and says why;
* the Next Inning board to catch up with a live change (whenCurrent): after
  a live Undo of a pitching change the board used to show the undone
  defense, and its button "... keeps pitching", until the next poll -- and
  End Inning started a different defense than the one shown.

So the defense that starts is the one the coach was shown, and a Plan Undo
in flight never ends in "NEXT defense changed before the inning could
advance" (409 stale_next_inning_prep).
"""

import os
import re
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
from test_next_plan_undo_ownership import (  # noqa: E402,F401 (assistant is a fixture)
    NOT_YOURS, PLAN_BUTTON, PLANNER, UNDO, _filled, _prep, _save, _swap, _tap_swap, assistant,
)


END = '#liveEndInningBtn'
NOTE = '#liveEndInningBtn .coach-action-note'
PITCHER = '#cbQuickDefense [data-cb-position="P"]'
ERROR = f'{PLANNER} .cb-next-error'
NEXT_PREP = re.compile(r'.*/next-inning-prep$')
LUKE, OWEN = INNING_1['P'], INNING_1['2B']

# Installed before the page's scripts: each advance request with what the
# Next Inning board and End Inning's button showed as it was sent, and the
# order of the Next Inning saves around it.
RECORD = r"""
(() => {
  window.__sync = [];
  const nativeFetch = window.fetch;
  window.fetch = function(input, init) {
    const url = String((input && input.url) || input);
    const method = String(init?.method || 'GET').toUpperCase();
    let path = '';
    try { path = new URL(url, location.href).pathname; } catch (_) {}
    let entry = null;
    if (method === 'POST' && /\/(next-inning-prep|advance-inning)$/.test(path)) {
      let body = {};
      try { body = JSON.parse(init?.body || '{}'); } catch (_) {}
      entry = {
        kind: /advance/.test(path) ? 'advance' : `plan:${body.mode}`,
        sent: body.alignment || null,
        shown: window.CBNextDefense?.getAlignment?.() || null,
        line: document.querySelector('#liveEndInningBtn')?.textContent?.replace(/\s+/g, ' ').trim() || '',
      };
      window.__sync.push(entry);
    }
    const result = nativeFetch.apply(this, arguments);
    if (entry) {
      result.then(response => {
        entry.status = response.status;
        return response.clone().json().then(data => { entry.code = data.code || ''; });
      }).catch(() => { entry.status = entry.status || 0; });
    }
    return result;
  };
})();
"""


def _open(page, url):
    page.add_init_script(RECORD)
    page.goto(f'{url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)


def _log(page):
    return page.evaluate('() => window.__sync')


def _advances(page):
    return [entry for entry in _log(page) if entry['kind'] == 'advance']


def _inning(page, url):
    return str(_state(page, url)['current_inning'])


def _wait_for_inning(page, url, inning, timeout_s=15):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and _inning(page, url) != inning:
        page.wait_for_timeout(200)
    assert _inning(page, url) == inning


def _open_planner(page):
    page.locator(PLAN_BUTTON).click()
    expect(page.locator(PLANNER)).to_be_visible()


def _close_planner(page):
    page.keyboard.press('Escape')
    expect(page.locator(PLANNER)).not_to_be_visible(timeout=5_000)


def _saved(page):
    expect(page.locator(f'{PLANNER} [data-next-save-state]')).to_contain_text('✓', timeout=10_000)


def _started(page, url):
    return _filled(_state(page, url)['current_alignment'])


def _one_clean_advance(page, url, expected):
    """Exactly one advance, accepted, sending the plan the board showed,
    and the inning started with it."""
    _wait_for_inning(page, url, '2')
    page.wait_for_timeout(500)
    for _ in range(50):                                          # the answer reaches the page
        advances = _advances(page)
        if advances and all('status' in entry for entry in advances):
            break
        page.wait_for_timeout(200)
    assert [entry.get('status') for entry in advances] == [200], advances
    advance = advances[0]
    assert _filled(advance['sent']) == _filled(advance['shown'])
    assert _filled(advance['sent']) == _filled(expected) == _started(page, url)
    return advance


# --------------------------------------------- after a live Undo


def _owen_pitches(page, url):
    """Another coach's pitching change: Owen in from 2B, Luke to 2B."""
    state = _state(page, url)
    owen = next(p['id'] for p in state['roster'] if p['name'] == OWEN)
    alignment = dict(_filled(state['current_alignment']), P=OWEN, **{'2B': LUKE})
    response = page.cb_api.request.post(_api(page, url, 'complete-pitcher-change'), data={
        'base_sequence': _sequence(state), 'new_pitcher_id': owen, 'alignment': alignment, 'fast': True})
    assert response.ok, response.text()[:300]
    expect(page.locator(NOTE)).to_contain_text(f'{OWEN} keeps pitching', timeout=8_000)


def test_after_live_undo_the_board_and_button_follow_the_restored_game(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    _owen_pitches(page, coachboard_url)

    page.locator('#liveUndoBtn').click()
    expect(page.locator(PITCHER)).to_contain_text(LUKE, timeout=5_000)
    restored = time.monotonic()
    # Was until the next poll (up to 3.5 s; 2.4 s measured).
    expect(page.locator(NOTE)).not_to_contain_text('keeps pitching', timeout=1_500)
    assert time.monotonic() - restored < 1.5
    expect(page.locator(f'{PLANNER} [data-next-position="P"]')).not_to_have_attribute(
        'data-next-player', OWEN)
    assert page.cb_errors == []


def test_end_inning_right_after_live_undo_starts_the_defense_shown(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    _owen_pitches(page, coachboard_url)

    page.locator('#liveUndoBtn').click()
    expect(page.locator(PITCHER)).to_contain_text(LUKE, timeout=5_000)
    page.locator(END).click()                                    # without waiting for the line

    _wait_for_inning(page, coachboard_url, '2')
    advance = _advances(page)[0]
    assert advance['status'] == 200
    assert _filled(advance['shown']) == _filled(advance['sent']) == _started(page, coachboard_url)
    assert 'keeps pitching' not in advance['line']               # the button said what started
    assert _started(page, coachboard_url).get('P') != OWEN       # the undone change is not carried
    assert page.cb_errors == []


# -------------------------------------------------------- Plan Undo


@pytest.mark.parametrize('attempt', range(8))
def test_plan_undo_behind_a_save_in_flight_then_end_inning(live, coachboard_url, attempt):
    """The edit is still saving, the coach taps Undo (which waits for it),
    closes the planner and ends the inning. End Inning waits for the whole
    Undo and starts the restored plan: one advance, never a 409."""
    page = live(PHONE)
    _open(page, coachboard_url)
    before = _prep(page.cb_api.request, coachboard_url, page)['alignment']
    _open_planner(page)
    held = []

    def hold_the_edit(route):
        body = route.request.post_data_json if route.request.method == 'POST' else None
        if isinstance(body, dict) and body.get('mode') == 'custom' and not held:
            held.append(route)
        else:
            route.continue_()

    page.route(NEXT_PREP, hold_the_edit)
    _tap_swap(page, 'LF', 'RF')
    page.wait_for_timeout(150)
    assert held
    page.locator(UNDO).click()
    _close_planner(page)
    page.locator(END).click()
    page.wait_for_timeout(300 + 100 * attempt)                   # vary where the edit lands
    assert _advances(page) == []
    held[0].continue_()
    page.unroute(NEXT_PREP)

    _one_clean_advance(page, coachboard_url, before)
    kinds = [entry['kind'] for entry in _log(page)]
    assert kinds.index('plan:undo') < kinds.index('advance')
    assert page.cb_errors == []


@pytest.mark.parametrize('latency_ms', [150, 300, 450, 600, 800])
def test_plan_undo_behind_a_slow_save_then_end_inning(live, coachboard_url, latency_ms):
    """The same race on a slow connection, without holding anything."""
    page = live(PHONE)
    _open(page, coachboard_url)
    before = _prep(page.cb_api.request, coachboard_url, page)['alignment']
    _open_planner(page)
    cdp = page.context.new_cdp_session(page)
    cdp.send('Network.enable')
    cdp.send('Network.emulateNetworkConditions', {
        'offline': False, 'latency': latency_ms, 'downloadThroughput': -1, 'uploadThroughput': -1})

    _tap_swap(page, 'LF', 'RF')
    page.locator(UNDO).click()
    _close_planner(page)
    page.locator(END).click()

    _one_clean_advance(page, coachboard_url, before)
    assert page.cb_errors == []


def test_end_inning_waits_for_the_plan_undo_answer(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    before = _prep(page.cb_api.request, coachboard_url, page)['alignment']
    _open_planner(page)
    _tap_swap(page, 'LF', 'RF')
    _saved(page)
    held = []

    def hold_the_undo(route):
        body = route.request.post_data_json if route.request.method == 'POST' else None
        if isinstance(body, dict) and body.get('mode') == 'undo' and not held:
            held.append(route)
        else:
            route.continue_()

    page.route(NEXT_PREP, hold_the_undo)
    page.locator(UNDO).click()
    _close_planner(page)
    page.locator(END).click()
    page.wait_for_timeout(1_000)
    assert held and _advances(page) == []
    held[0].continue_()
    page.unroute(NEXT_PREP)

    _one_clean_advance(page, coachboard_url, before)


def test_a_refused_plan_undo_stops_end_inning(live, assistant, coachboard_url):
    """Another coach saved after this coach's edit; this (stale) screen's
    Undo is refused while End Inning waits for it. End Inning does not
    start with any plan: it stops and says nothing was undone. Ended again,
    it starts the other coach's plan -- the server's."""
    page = live(PHONE)
    _open(page, coachboard_url)
    _open_planner(page)
    _tap_swap(page, 'LF', 'RF')
    _saved(page)
    expect(page.locator(UNDO)).to_be_enabled(timeout=5_000)

    held, holding = [], {'on': True}

    def hold(route):
        body = route.request.post_data_json if route.request.method == 'POST' else None
        is_undo = isinstance(body, dict) and body.get('mode') == 'undo'
        if holding['on'] and (route.request.method == 'GET' or is_undo):
            held.append(route)
        else:
            route.continue_()

    page.route(NEXT_PREP, hold)                                  # this screen hears nothing more
    other = assistant(page)
    confirmed = _prep(other.request, coachboard_url, page)
    theirs = _save(other.request, coachboard_url, page, **_swap(confirmed, '2B', 'SS'))

    page.locator(UNDO).click()                                   # still looks like ours
    _close_planner(page)
    page.locator(END).click()
    page.wait_for_timeout(800)
    assert _advances(page) == []
    holding['on'] = False
    for route in held:
        route.continue_()
    page.unroute(NEXT_PREP)

    expect(page.locator(PLANNER)).to_be_visible(timeout=10_000)  # back to the plan, with why
    expect(page.locator(ERROR)).to_contain_text('Nothing was undone', timeout=10_000)
    page.wait_for_timeout(500)
    assert _advances(page) == []
    assert _inning(page, coachboard_url) == '1'
    undo = [entry for entry in _log(page) if entry['kind'] == 'plan:undo']
    assert [entry.get('code') for entry in undo] == ['next_prep_not_yours']
    expect(page.locator(f'{PLANNER} [data-next-position="2B"]')).to_have_attribute(
        'data-next-player', theirs['alignment']['2B'])

    _close_planner(page)
    page.locator(END).click()
    _one_clean_advance(page, coachboard_url, theirs['alignment'])


def test_another_coachs_plan_change_is_the_one_started(live, assistant, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    other = assistant(page)
    confirmed = _prep(other.request, coachboard_url, page)
    theirs = _save(other.request, coachboard_url, page, **_swap(confirmed, '2B', 'SS'))

    page.locator(END).click()                                    # at once

    _one_clean_advance(page, coachboard_url, theirs['alignment'])
    assert page.cb_errors == []


def test_another_coachs_plan_not_yet_on_this_board_is_shown_before_it_starts(
    live, assistant, coachboard_url
):
    """The race CI hit by chance, made certain: this page's live connection is
    down, so its board cannot have heard of the other coach's plan when End
    Inning is tapped. End Inning reads the server's plan; the board shows it
    before the advance is sent, so what starts is what is on screen."""
    page = live(PHONE)
    _open(page, coachboard_url)
    page.evaluate('() => window.__cbLiveGameSocket.disconnect()')
    other = assistant(page)
    confirmed = _prep(other.request, coachboard_url, page)
    theirs = _save(other.request, coachboard_url, page, **_swap(confirmed, '2B', 'SS'))
    assert _filled(page.evaluate('() => window.CBNextDefense.getAlignment()')) != _filled(theirs['alignment'])

    page.locator(END).click()                                    # at once

    _one_clean_advance(page, coachboard_url, theirs['alignment'])
    assert page.cb_errors == []


def test_end_inning_with_nothing_pending_is_unchanged(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    plan = _prep(page.cb_api.request, coachboard_url, page)['alignment']
    tapped = time.monotonic()

    page.locator(END).click()

    _one_clean_advance(page, coachboard_url, plan)
    assert [entry['kind'] for entry in _log(page)] == ['advance']
    assert time.monotonic() - tapped < 5
    assert page.cb_errors == []


def test_when_current_is_bounded_if_the_read_never_lands(live, coachboard_url):
    """A board read that never answers holds End Inning a bounded time."""
    page = live(PHONE)
    _open(page, coachboard_url)
    page.route(NEXT_PREP, lambda route: None if route.request.method == 'GET' else route.continue_())
    elapsed = page.evaluate("""async () => {
        document.dispatchEvent(new CustomEvent('coachboard:live-delta', {detail: {}}));
        const started = performance.now();
        await window.CBNextDefense.whenCurrent();
        return performance.now() - started;
    }""")
    assert 2_500 <= elapsed <= 4_500
    page.unroute(NEXT_PREP)
