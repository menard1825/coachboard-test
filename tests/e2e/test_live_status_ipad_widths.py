"""The connection status stays visible in the compact (iPad portrait) header.

Between 576 and 900 px wide the Live Game header drops to a compact layout,
and it used to hide "Live · Synced" entirely -- so on an iPad in portrait a
dropped connection ("Reconnecting…", "Not Synced") was never shown. It now
keeps a narrow status column; the header still fits on one row.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_live_game_status_ownership import set_sync  # noqa: E402
from test_pregame_plan_reference import live  # noqa: E402,F401 (live is a fixture)


LABEL = '#cbDugoutHeader [data-cb-live-label]'

# iPad mini, iPad, iPad Air/Pro 11 portrait, and the edges of the range.
WIDTHS = [(576, 900), (744, 1133), (768, 1024), (820, 1180), (834, 1194), (899, 1100)]


@pytest.mark.parametrize('size', WIDTHS, ids=lambda s: f'{s[0]}px')
def test_connection_status_is_visible_and_the_header_fits(live, coachboard_url, size):
    page = live(('tablet', {'width': size[0], 'height': size[1]}, {'is_mobile': True, 'has_touch': True}))
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(1_000)

    for mode, text in (('synced', 'Live · Synced'), ('reconnecting', 'Reconnecting…'), ('offline', 'Not Synced')):
        set_sync(page, mode)
        expect(page.locator(LABEL)).to_have_text(text)
        expect(page.locator(LABEL)).to_be_visible()
        fit = page.evaluate("""() => {
          const header = document.getElementById('cbDugoutHeader');
          const main = header.querySelector('.cb-dh-main');
          const boxes = [...main.children].filter(el => el.getClientRects().length)
            .map(el => el.getBoundingClientRect());
          const live = header.querySelector('.cb-dh-live').getBoundingClientRect();
          // One row: every item starts above where every other one ends.
          const oneRow = Math.max(...boxes.map(b => b.top)) < Math.min(...boxes.map(b => b.bottom));
          return {rows: oneRow ? 1 : 2,
                  overflow: main.scrollWidth - main.clientWidth,
                  inside: live.right <= header.getBoundingClientRect().right && live.width > 0};
        }""")
        assert fit['rows'] == 1 and fit['overflow'] <= 1 and fit['inside'], (size, mode, fit)
    assert page.cb_errors == []
