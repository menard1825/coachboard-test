"""Next Inning reads the server one request at a time, and never lets an
older answer replace a newer one.

At start-up, building the tabs used to send its own next-inning request
while the 140 ms start-up request was still in the air (or just before it),
so the same state was read twice ~40 ms apart. Callers that only need the
data now share the read in the air; a live change arriving while a read is
in the air marks that read stale, so its answer is dropped and read again.

The page's fetch is wrapped to count next-inning reads, to note how many are
in the air at once, and -- to make a response slow -- to hold an answer the
server has already produced, so a held answer is an old one.
"""

import json
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
NEXT_LF = '#live-board-prep-v3 [data-next-position="LF"] .cb-qd-name'

WATCH = r"""
((hold) => {
  const reads = window.__cbReads = {starts: [], inFlight: 0, maxInFlight: 0, firstDrawn: null};
  // {ms, count}: hold the next `count` answers for `ms` (count -1: all).
  window.__cbHold = hold;
  const originalFetch = window.fetch;
  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : input?.url || '';
    const method = (init?.method || input?.method || 'GET').toUpperCase();
    if (!url.includes('/next-inning-prep') || method !== 'GET') return originalFetch.apply(this, arguments);
    reads.starts.push(Math.round(performance.now()));
    reads.inFlight += 1;
    reads.maxInFlight = Math.max(reads.maxInFlight, reads.inFlight);
    try {
      const response = await originalFetch.apply(this, arguments);
      const h = window.__cbHold;
      if (h && h.ms && h.count !== 0) {
        if (h.count > 0) h.count -= 1;
        await new Promise(resolve => setTimeout(resolve, h.ms));
      }
      return response;
    } finally {
      reads.inFlight -= 1;
    }
  };
  // Every left-field name the Next Inning board shows, in order.
  window.__cbLeftField = [];
  const watch = () => {
    if (reads.firstDrawn === null && document.querySelector('#live-board-prep-v3 .cb-next-head')) {
      reads.firstDrawn = reads.starts.length;
    }
    const name = document.querySelector('#live-board-prep-v3 [data-next-position="LF"] .cb-qd-name')?.textContent.trim();
    const seen = window.__cbLeftField;
    if (name && seen[seen.length - 1] !== name) seen.push(name);
  };
  document.addEventListener('DOMContentLoaded', () => {
    new MutationObserver(watch).observe(document.body, {childList: true, subtree: true, characterData: true});
    watch();
  });
})(%s);
"""


@pytest.fixture
def live(browser, coachboard_url):
    made = []

    def _open(device, hold=None):
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
        page.add_init_script(WATCH % json.dumps(hold or {'ms': 0, 'count': 0}))
        page.goto(f'{coachboard_url}/game/{game_id}')
        return page

    yield _open
    for setup, api, game_id, player_ids, *contexts in made:
        for context in contexts:
            context.close()
        remove_named_live_game(api, coachboard_url, game_id, player_ids)
        setup.close()


def _lineup(**moves):
    alignment = {pos: name for pos, (name, _) in LINEUP.items()}
    alignment.update(moves)
    return alignment


def _other_coach_sets(page, coachboard_url, alignment):
    response = page.cb_api.request.post(
        f'{coachboard_url}/api/live-game/{page.cb_game}/next-inning-prep',
        data={'mode': 'custom', 'alignment': alignment})
    assert response.ok, response.text()[:200]


def _announce_change(page):
    """What the live page hears when anything changes (live_game_v2 and the
    socket send the same)."""
    page.evaluate("document.dispatchEvent(new CustomEvent('coachboard:live-delta', {detail: {}}))")


def _reads(page):
    return page.evaluate('window.__cbReads')


def _settle(page):
    page.wait_for_function('window.__cbReads.inFlight === 0', timeout=10_000)


LF, RF, CF = LINEUP['LF'][0], LINEUP['RF'][0], LINEUP['CF'][0]


@DEVICES
def test_a_slow_start_up_read_is_shared_not_repeated(live, device):
    page = live(device, hold={'ms': 1200, 'count': -1})
    page.locator('#cb-now-next-switch [data-now-next="next"]').wait_for(state='visible', timeout=20_000)
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    expect(page.locator(HEAD)).to_be_visible(timeout=6_000)
    expect(page.locator(HEAD)).to_contain_text('2nd Inning Defense')

    reads = _reads(page)
    assert reads['firstDrawn'] == 1, reads             # drawn from the one start-up read
    assert reads['maxInFlight'] == 1, reads
    expect(page.locator(NEXT_LF)).to_have_text(LF)
    assert page.cb_errors == []


@DEVICES
def test_a_change_during_the_start_up_read_shows_and_the_old_answer_never_lands(live, device, coachboard_url):
    page = live(device, hold={'ms': 1500, 'count': 1})
    page.wait_for_function('window.__cbReads.starts.length >= 1', timeout=20_000)

    # While the start-up answer (the old defense) is held, another coach
    # changes the next inning and the page hears about it.
    _other_coach_sets(page, coachboard_url, _lineup(LF=RF, RF=LF))
    _announce_change(page)

    page.locator('#cb-now-next-switch [data-now-next="next"]').wait_for(state='visible', timeout=20_000)
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    expect(page.locator(NEXT_LF)).to_have_text(RF, timeout=6_000)
    _settle(page)
    page.wait_for_timeout(300)

    expect(page.locator(NEXT_LF)).to_have_text(RF)
    assert page.evaluate('window.__cbLeftField') == [RF]   # the held, older answer was never drawn
    assert _reads(page)['maxInFlight'] == 1
    assert page.cb_errors == []


@DEVICES
def test_later_changes_show_promptly_and_in_order(live, device, coachboard_url):
    page = live(device)
    page.locator('#cb-now-next-switch [data-now-next="next"]').wait_for(state='visible', timeout=20_000)
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    expect(page.locator(NEXT_LF)).to_have_text(LF, timeout=6_000)
    _settle(page)

    # A change is read right away, not at the 3.5 s poll.
    _other_coach_sets(page, coachboard_url, _lineup(LF=RF, RF=LF))
    _announce_change(page)
    expect(page.locator(NEXT_LF)).to_have_text(RF, timeout=2_500)

    # Slow answers: a second change while the first one's read is in the
    # air. That read is about the older state; only the newest is drawn.
    _settle(page)
    page.evaluate("window.__cbHold = {ms: 1200, count: 1}; window.__cbLeftField = []")
    before = len(_reads(page)['starts'])
    _other_coach_sets(page, coachboard_url, _lineup(LF=CF, CF=LF))
    _announce_change(page)
    page.wait_for_function(f'window.__cbReads.starts.length > {before}', timeout=5_000)
    _other_coach_sets(page, coachboard_url, _lineup())
    _announce_change(page)

    expect(page.locator(NEXT_LF)).to_have_text(LF, timeout=6_000)
    _settle(page)
    page.wait_for_timeout(300)
    expect(page.locator(NEXT_LF)).to_have_text(LF)
    assert CF not in page.evaluate('window.__cbLeftField')     # the superseded answer was dropped
    assert _reads(page)['maxInFlight'] == 1
    assert page.cb_errors == []
