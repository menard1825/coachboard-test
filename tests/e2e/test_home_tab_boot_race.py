"""A workspace opened while Home is starting up stays open.

main.js reads the URL's tab when the page is ready but activates it a turn
later (setTimeout 0), pushing that tab's hash. A coach -- or a link, or Back
-- who opened another workspace in between was sent back to Home, with the
URL rewritten to #overview. On a slow device that turn is long enough to
hit; in CI it failed test_coach_notes_ux and test_roster_metrics_ux, each
landing on Home with its workspace hidden.

Here the other workspace is opened at exactly that moment, every time.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect  # noqa: E402

from test_roster_metrics_ux import login  # noqa: E402


# Runs before the page's scripts, so this ready-handler is queued ahead of
# main.js's: the coach's tap lands after main.js has read the hash and before
# its deferred activation runs.
TAP_DURING_STARTUP = """(target) => {
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
      if (location.pathname === '/' && location.hash !== target) location.hash = target;
    }, 0);
  });
}"""


@pytest.mark.parametrize('target', ['#collaboration', '#roster', '#rotations'])
def test_a_workspace_opened_during_startup_is_not_replaced_by_home(page: Page, coachboard_url, target):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.add_init_script(f'({TAP_DURING_STARTUP})({target!r})')
    page.goto(f'{coachboard_url}/', wait_until='domcontentloaded')

    pane = page.locator(target)
    expect(pane).to_be_visible(timeout=10_000)
    page.wait_for_timeout(1_500)                     # past main.js's deferred step
    expect(pane).to_be_visible()
    expect(page.locator('#overview')).to_be_hidden()
    assert page.url.endswith(target), page.url
    assert not re.search(r'#overview$', page.url)
