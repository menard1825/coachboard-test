"""The live header clock and field card hold still when nothing changed.

- Before the first /clock answer the header clock shows "—", never a
  made-up 0:00.
- The 12 s recovery read of the live state (live_game_dugout_mode.js
  getState) used to rebuild the whole field card every time -- markers,
  bench and Bench Report button -- so a long press on a player in that
  moment never armed. The card is now redrawn only when what it shows
  changed: the field, the bench, the save status, or the roster's names and
  numbers.
"""

import json
import math
import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from cdp_touch import GHOST_SELECTOR, TouchDriver, centres, ghost_creations, watch_ghosts  # noqa: E402
from live_fixtures import (  # noqa: E402,F401
    INNING_1,
    PHONE,
    api_url as _api,
    last_sequence as _sequence,
    game_state as _state,
    live,
)


CARD = '#cbQuickDefense'
CLOCK = '#cbDugoutHeader [data-cb-clock-time]'
SS_PLAYER = INNING_1['SS']
RECOVERY_MS = 12_000

# Installed before the page's scripts: the header clock as shown, every
# rewrite of the field card, and the dugout's own recovery reads of /state.
WATCH = r"""
(() => {
  // The page wraps fetch several times over; keep enough frames to see who called.
  Error.stackTraceLimit = 60;
  const t0 = performance.now();
  const now = () => performance.now() - t0;
  window.__now = now;
  // Every value the header clock shows, as it changes.
  window.__clock = [];
  const sample = () => {
    const text = document.querySelector('#cbDugoutHeader [data-cb-clock-time]')?.textContent?.trim();
    if (text && window.__clock[window.__clock.length - 1] !== text) window.__clock.push(text);
  };
  new MutationObserver(sample).observe(document, {childList: true, characterData: true, subtree: true});

  window.__rebuilds = [];
  const html = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  Object.defineProperty(Element.prototype, 'innerHTML', {
    configurable: true,
    get() { return html.get.call(this); },
    set(value) {
      if (this.id === 'cbQuickDefense') window.__rebuilds.push(now());
      return html.set.call(this, value);
    },
  });
})();
"""

# Installed once the page has loaded, outside every other fetch wrapper:
# the dugout's own /state reads (live_game_feedback_pass.js shares one
# request between callers, so the request itself may carry another stack).
READS = r"""
(() => {
  window.__recoveryReads = [];
  const outer = window.fetch;
  window.fetch = function(input, init) {
    const url = String((input && input.url) || input);
    let path = '';
    try { path = new URL(url, location.href).pathname; } catch (_) {}
    const result = outer.apply(this, arguments);
    if (/\/state$/.test(path) && /live_game_dugout_mode/.test(new Error().stack || '')) {
      const read = {sent: window.__now(), landed: null};
      window.__recoveryReads.push(read);
      Promise.resolve(result).then(() => { read.landed = window.__now(); }, () => {});
    }
    return result;
  };
})();
"""


def _open(page, url, before=None):
    page.add_init_script(WATCH)
    if before:
        before(page)
    page.goto(f'{url}/game/{page.cb_game}')
    page.locator(CARD).wait_for(state='visible', timeout=20_000)
    expect(page.locator(f'{CARD} [data-cb-position="SS"]')).to_contain_text(SS_PLAYER, timeout=10_000)
    page.evaluate(READS)
    # The dugout's next recovery read sets the phase of its 12 s timer.
    page.wait_for_function('() => window.__recoveryReads.some(r => r.landed !== null)', timeout=15_000)
    page.wait_for_timeout(300)


def _now(page):
    return page.evaluate('() => window.__now()')


def _reads(page):
    return page.evaluate('() => window.__recoveryReads')


def _rebuilds_since(page, since):
    return [t for t in page.evaluate('() => window.__rebuilds') if t >= since]


def _wait_until_before_next_read(page, lead_ms):
    """Sleep until `lead_ms` before the dugout's next 12 s recovery read."""
    first = _reads(page)[0]['sent']
    now = _now(page)
    k = math.ceil((now + 1_000 - first) / RECOVERY_MS)
    target = first + RECOVERY_MS * k
    page.wait_for_timeout(max(0, target - lead_ms - now))
    return target


def _read_landed_between(page, start, end):
    return [r for r in _reads(page) if r['landed'] is not None and start <= r['landed'] <= end]


def _bench_drop(page):
    return page.locator(f'{CARD} .cb-qd-bench-wrap')


def _ss_on_bench(page, url):
    return not _state(page, url)['current_alignment'].get('SS')


# ------------------------------------------------------------- clock


def test_the_clock_shows_a_dash_not_zero_until_the_server_time_is_known(live, coachboard_url):
    page = live(PHONE)
    assert page.cb_api.request.post(_api(page, coachboard_url, 'clock'), data={'time_limit_minutes': 90}).ok
    held = []
    page.route(re.compile(r'.*/api/live-game/\d+/clock$'),
               lambda route: held.append(route) if route.request.method == 'GET' else route.continue_())
    page.add_init_script(WATCH)
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator(CARD).wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(1_500)
    expect(page.locator(CLOCK)).to_have_text('—')               # every /clock read is held
    assert held
    for route in held:
        route.continue_()
    page.unroute(re.compile(r'.*/api/live-game/\d+/clock$'))
    expect(page.locator(CLOCK)).to_have_text(re.compile(r'^1:29:\d\d$'), timeout=5_000)
    shown = page.evaluate('() => window.__clock')
    assert '0:00' not in shown, shown
    assert shown[0] == '—' and shown[1].startswith('1:29:'), shown   # 90 minutes, counting down
    assert page.cb_errors == []


# ------------------------------------------------- the recovery read


def test_an_unchanged_recovery_read_leaves_the_field_card_alone(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    page.evaluate("""() => {
        window.__kept = [...document.querySelectorAll('#cbQuickDefense button')];
    }""")
    start = _now(page)
    target = _wait_until_before_next_read(page, -600)            # just after it lands
    assert _read_landed_between(page, start, _now(page)), _reads(page)
    assert _rebuilds_since(page, start) == []
    assert page.evaluate('() => window.__kept.length > 0 && window.__kept.every(b => b.isConnected)')
    expect(page.locator(f'{CARD} [data-cb-bench-report]')).to_have_count(1)
    assert target > start
    assert page.cb_errors == []


def test_a_touch_long_press_across_the_recovery_read_still_drags(live, coachboard_url, browser_name):
    if browser_name != 'chromium':
        pytest.skip('CDP touch injection is Chromium-only.')
    page = live(PHONE)
    _open(page, coachboard_url)
    page.route('**/api/live-game/*/clock', lambda route: route.abort())   # only the read under test
    watch_ghosts(page)
    (sx, sy), (tx, ty) = centres(page.locator(f'{CARD} [data-cb-position="SS"]'), _bench_drop(page))

    _wait_until_before_next_read(page, 150)
    touch = TouchDriver(page)
    down = _now(page)
    touch.down(sx, sy).hold(500)                                  # the read lands ~150 ms in
    held_until = _now(page)
    touch.move_to(tx, ty, steps=12, pause_ms=8)
    expect(page.locator(GHOST_SELECTOR)).to_have_count(1, timeout=3_000)
    touch.up()

    assert _read_landed_between(page, down, held_until), (down, held_until, _reads(page))
    assert _rebuilds_since(page, down - 1) == [] or min(_rebuilds_since(page, down - 1)) > held_until
    expect(page.locator(f'{CARD} [data-cb-position="SS"]')).to_contain_text('Open', timeout=10_000)
    assert _ss_on_bench(page, coachboard_url)
    assert ghost_creations(page) == 1
    assert page.cb_errors == []


def test_a_mouse_press_across_the_recovery_read_still_drags(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    page.route('**/api/live-game/*/clock', lambda route: route.abort())
    box = page.locator(f'{CARD} [data-cb-position="SS"]').bounding_box()
    drop = _bench_drop(page).bounding_box()

    _wait_until_before_next_read(page, 150)
    down = _now(page)
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    page.mouse.down()
    page.wait_for_timeout(500)                                    # the read lands while pressed
    held_until = _now(page)
    page.mouse.move(drop['x'] + drop['width'] / 2, drop['y'] + drop['height'] / 2, steps=12)
    page.mouse.up()

    assert _read_landed_between(page, down, held_until), (down, held_until, _reads(page))
    assert not [t for t in _rebuilds_since(page, down) if t <= held_until]
    expect(page.locator(f'{CARD} [data-cb-position="SS"]')).to_contain_text('Open', timeout=10_000)
    assert _ss_on_bench(page, coachboard_url)
    assert page.cb_errors == []


# ---------------------------------------------- real changes redraw


def test_another_devices_defense_change_redraws_the_card(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    start = _now(page)
    state = _state(page, coachboard_url)
    alignment = {pos: name for pos, name in state['current_alignment'].items() if name}
    alignment['SS'], alignment['2B'] = alignment['2B'], alignment['SS']
    response = page.cb_api.request.post(_api(page, coachboard_url, 'defense-edit'), data={
        'alignment': alignment, 'base_sequence': _sequence(state)})
    assert response.ok, response.text()[:300]

    expect(page.locator(f'{CARD} [data-cb-position="SS"]')).to_contain_text(alignment['SS'], timeout=10_000)
    expect(page.locator(f'{CARD} [data-cb-position="2B"]')).to_contain_text(alignment['2B'])
    assert _rebuilds_since(page, start)
    assert page.cb_errors == []


def test_a_roster_number_change_in_the_recovery_read_redraws_the_card(live, coachboard_url):
    """The roster is locked during a live game, so the recovery read is
    made to answer with a new jersey number for the shortstop: nothing else
    changed, and the field marker must show it."""
    page = live(PHONE)
    _open(page, coachboard_url)
    expect(page.locator(f'{CARD} [data-cb-position="SS"] .cb-qd-num')).not_to_have_text('#77')

    def renumbered(route):
        response = route.fetch()
        data = response.json()
        for player in data.get('roster', []):
            if player.get('name') == SS_PLAYER:
                player['number'] = '77'
        route.fulfill(response=response, body=json.dumps(data))

    start = _now(page)
    page.route(re.compile(r'.*/api/live-game/\d+/state$'), renumbered)
    _wait_until_before_next_read(page, -800)                     # one recovery read later
    assert _read_landed_between(page, start, _now(page)), _reads(page)
    expect(page.locator(f'{CARD} [data-cb-position="SS"] .cb-qd-num')).to_have_text('#77', timeout=3_000)
    assert _rebuilds_since(page, start)
    assert page.cb_errors == []
    page.unroute_all(behavior='ignoreErrors')
