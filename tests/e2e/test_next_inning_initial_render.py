"""Next Inning shows as soon as its data is loaded after a fresh page load.

The first next-inning request goes out 140 ms after start-up, usually before
the live shell exists, so the card could not be drawn yet; the tabs were built
a moment later from the DOM alone, and nothing drew the card until the next
3.5 s poll. The card is now drawn as soon as the shell is ready, from the
data already loaded -- no extra request.

The deterministic check: when the Next Inning heading first appears, exactly
one next-inning request has been made (the start-up one). Waiting for the
poll would mean a second.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from live_field_markers import LINEUP, create_named_live_game, login, remove_named_live_game  # noqa: E402


PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
DEVICES = pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])
HEAD = '#live-board-prep-v3 .cb-next-head'

#: Counts next-inning requests, and notes how many had been made (and when)
#: the moment the Next Inning heading first exists.
WATCH = r"""
(() => {
  window.__cbPrepFetches = [];
  const originalFetch = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : input?.url || '';
    const method = (init?.method || input?.method || 'GET').toUpperCase();
    if (url.includes('/next-inning-prep') && method === 'GET') window.__cbPrepFetches.push(Math.round(performance.now()));
    return originalFetch.apply(this, arguments);
  };
  const watch = () => {
    if (window.__cbFirstNextRender || !document.querySelector('#live-board-prep-v3 .cb-next-head')) return;
    window.__cbFirstNextRender = {at: Math.round(performance.now()), fetches: window.__cbPrepFetches.length};
  };
  document.addEventListener('DOMContentLoaded', () => {
    new MutationObserver(watch).observe(document.body, {childList: true, subtree: true});
    watch();
  });
})();
"""


@pytest.fixture
def live(browser, coachboard_url):
    made = []

    def _open(device):
        setup = browser.new_context()
        cdn_assets.install(setup)
        api = setup.new_page()
        login(api, coachboard_url)
        game_id, player_ids = create_named_live_game(api, coachboard_url)
        made.append((setup, api, game_id, player_ids))

        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        made[-1] += (context,)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors, page.cb_api, page.cb_game = errors, api, game_id
        login(page, coachboard_url)
        page.add_init_script(WATCH)
        page.goto(f'{coachboard_url}/game/{game_id}')
        return page

    yield _open
    for setup, api, game_id, player_ids, *contexts in made:
        for context in contexts:
            context.close()
        remove_named_live_game(api, coachboard_url, game_id, player_ids)
        setup.close()


def _names(page):
    return {pos: page.locator(f'#live-board-prep-v3 [data-next-position="{pos}"] .cb-qd-name').inner_text().strip()
            for pos in LINEUP}


@DEVICES
def test_next_inning_is_drawn_from_the_first_load_not_the_first_poll(live, device):
    page = live(device)
    tab = page.locator('#cb-now-next-switch [data-now-next="next"]')
    tab.wait_for(state='visible', timeout=20_000)
    tab.click()                                          # as soon as the tabs exist

    expect(page.locator(HEAD)).to_be_visible(timeout=3_000)
    first = page.evaluate('window.__cbFirstNextRender')
    assert first and first['fetches'] == 1, (first, page.evaluate('window.__cbPrepFetches'))

    # The right inning, field and bench.
    expect(page.locator(HEAD)).to_contain_text('2nd Inning Defense')
    assert _names(page) == {pos: name for pos, (name, _) in LINEUP.items()}
    expect(page.locator('#live-board-prep-v3 .cb-next-bench-head')).to_contain_text('Bench ·')
    assert page.cb_errors == []


@DEVICES
def test_no_extra_start_up_request_and_the_poll_carries_on(live, coachboard_url, device):
    page = live(device)
    page.locator('#cb-now-next-switch [data-now-next="next"]').wait_for(state='visible', timeout=20_000)
    page.locator(HEAD).wait_for(state='attached', timeout=3_000)
    # One start-up request, then only the 3.5 s poll.
    fetches = page.evaluate('window.__cbPrepFetches')
    assert len(fetches) == 1 or fetches[1] - fetches[0] > 3_000, fetches

    # The background refresh still brings in a change made elsewhere.
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    expect(page.locator(HEAD)).to_be_visible()
    lf, rf = LINEUP['LF'][0], LINEUP['RF'][0]
    edited = {pos: name for pos, (name, _) in LINEUP.items()}
    edited['LF'], edited['RF'] = rf, lf
    response = page.cb_api.request.post(f'{coachboard_url}/api/live-game/{page.cb_game}/next-inning-prep',
                                        data={'mode': 'custom', 'alignment': edited})
    assert response.ok, response.text()[:200]
    expect(page.locator('#live-board-prep-v3 [data-next-position="LF"] .cb-qd-name')).to_have_text(rf, timeout=8_000)
    expect(page.locator('#live-board-prep-v3 [data-next-position="RF"] .cb-qd-name')).to_have_text(lf)
    fetches = page.evaluate('window.__cbPrepFetches')
    gaps = [b - a for a, b in zip(fetches, fetches[1:])]
    assert all(gap > 1_000 for gap in gaps[1:]), fetches        # no burst of start-up requests
    assert page.cb_errors == []
