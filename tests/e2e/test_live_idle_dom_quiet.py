"""An idle Live Game page does not rewrite itself every animation frame.

Several scripts made writes that changed nothing -- setting an attribute,
hidden flag, title, class or text to the value it already had, or moving
two elements in front of each other -- and each such write woke another
script's MutationObserver, which wrote again: on an idle live page about
3,000 DOM changes a second and a style recalculation every frame, on
hidden pregame elements and the pitcher status. Writes are now made only
when something changes; the page is quiet between the clock's ticks.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from live_fixtures import PHONE, live  # noqa: E402,F401 (live is a fixture)


COUNT = """() => new Promise(resolve => {
  const counts = {};
  const name = el => !el ? '?' : el.nodeType !== 1 ? name(el.parentElement) :
    el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\\s+/)[0] : '');
  const observer = new MutationObserver(records => records.forEach(r => {
    const key = `${r.type} ${r.attributeName || ''} ${name(r.target)}`;
    counts[key] = (counts[key] || 0) + 1;
  }));
  observer.observe(document.documentElement, {subtree: true, childList: true, attributes: true, characterData: true});
  setTimeout(() => { observer.disconnect(); resolve(counts); }, 5000);
})"""


@pytest.mark.parametrize('size', [PHONE[1], {'width': 820, 'height': 1180}], ids=['phone', 'ipad'])
def test_an_idle_live_page_is_quiet(live, coachboard_url, size):
    page = live(('device', size, {'is_mobile': True, 'has_touch': True}))
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(4_000)
    counts = page.evaluate(COUNT)
    total = sum(counts.values())
    # The clock ticks (a few changes a second); nothing rewrites every frame.
    assert total < 150, sorted(counts.items(), key=lambda kv: -kv[1])[:10]
    assert max(counts.values(), default=0) < 30, sorted(counts.items(), key=lambda kv: -kv[1])[:10]
    assert page.cb_errors == []
