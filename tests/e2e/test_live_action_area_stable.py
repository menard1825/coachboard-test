"""The live-game screen does not flash its words.

Several live scripts used to write the same visible text. The Quick Field card
was drawn as "Current Defense / Field + bench at a glance" and then relabelled
"Live Defense / Quick Field" on every redraw, and two scripts woke each other
through the page's classes every animation frame. Each visible text now has
one owner. This records the visible text of the action area -- the Quick
Field heading and tip, the End Inning / Change Pitcher buttons, the tabs, the
live header and the Next Inning heading -- through the 3.5 s and 15 s
refreshes and a return to the app, and expects none of it to change.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

import cdn_assets  # noqa: E402
from live_field_markers import create_named_live_game, login, remove_named_live_game  # noqa: E402


PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})

RECORD = r"""() => {
  const areas = {
    'Quick Field heading': '#cbQuickDefense .cb-qd-head',
    'Quick Field tip': '#cbQuickDefense .cb-qd-tip',
    'action buttons': '#coach-action-slot',
    'tabs': '#cb-now-next-switch',
    'live header': '#cbDugoutHeader',
    'Next Inning heading': '#live-board-prep-v3 .cb-next-head',
  };
  // Only what is on screen counts: a hidden tab's card may be built in the
  // background. The clock ticks every second by design; everything else
  // must hold still.
  const read = sel => [...document.querySelectorAll(sel)]
    .filter(el => el.getClientRects().length)
    .map(el => (el.innerText || '').replace(/\d+:\d\d/g, '0:00').replace(/\s+/g, ' ').trim()).join(' | ');
  const seen = window.__cbAreaText = {};
  const sample = () => {
    for (const [area, sel] of Object.entries(areas)) {
      const text = read(sel);
      const list = seen[area] || (seen[area] = []);
      // An area first appearing is not a flash; going blank after showing is.
      if (!list.length && !text) continue;
      if (list[list.length - 1] !== text) list.push(text);
    }
  };
  sample();
  new MutationObserver(sample).observe(document.body, {subtree: true, childList: true, characterData: true});
  window.__cbBodyWrites = 0;
  new MutationObserver(ms => { window.__cbBodyWrites += ms.length; }).observe(document.body, {attributes: true});
}"""


def _come_back(page):
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")


@pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])
def test_live_action_area_text_holds_still(browser, coachboard_url, device):
    setup = browser.new_context()
    cdn_assets.install(setup)
    api = setup.new_page()
    login(api, coachboard_url)
    game_id, player_ids = create_named_live_game(api, coachboard_url)
    context = None
    try:
        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        login(page, coachboard_url)
        page.goto(f'{coachboard_url}/game/{game_id}')
        page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
        page.wait_for_function("() => /End 1st/.test(document.querySelector('#liveEndInningBtn')?.innerText || '')",
                               timeout=15_000)
        page.wait_for_timeout(1_000)

        # On the Field, through a 15 s refresh, several 3.5 s ones and an app return.
        page.evaluate(RECORD)
        page.wait_for_timeout(10_000)
        _come_back(page)
        page.wait_for_timeout(11_000)
        seen = page.evaluate('window.__cbAreaText')
        flashing = {area: texts for area, texts in seen.items() if len(texts) > 1}
        assert flashing == {}, flashing
        assert seen['Quick Field heading'][0].startswith('LIVE DEFENSE Quick Field') or \
            seen['Quick Field heading'][0].startswith('Live Defense Quick Field'), seen['Quick Field heading']
        # No script loop rewriting the page's classes every frame.
        assert page.evaluate('window.__cbBodyWrites') < 20

        # Next Inning, with its own refreshes and an app return.
        page.locator('#cb-now-next-switch [data-now-next="next"]').click()
        page.locator('#live-board-prep-v3 .cb-next-head').wait_for(state='visible')
        page.wait_for_timeout(500)
        page.evaluate(RECORD)
        page.wait_for_timeout(5_000)
        _come_back(page)
        page.wait_for_timeout(4_000)
        seen = page.evaluate('window.__cbAreaText')
        flashing = {area: texts for area, texts in seen.items() if len(texts) > 1}
        assert flashing == {}, flashing
        assert errors == []
    finally:
        if context:
            context.close()
        remove_named_live_game(api, coachboard_url, game_id, player_ids)
        setup.close()
