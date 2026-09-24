"""The End Inning button keeps its "End 1st -> Start 2nd" label.

Three scripts used to write this button's label. The Next Inning board sets
"End 1st -> Start 2nd" on its 3.5 s refresh; the live command center reset it
to "End Inning" on its own 15 s refresh and whenever the coach came back to
the app, so the button flashed "End Inning" for a few seconds at a time. The
Next Inning board is now the only owner of the label.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from live_field_markers import create_named_live_game, login, remove_named_live_game  # noqa: E402


PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
BUTTON = '#liveEndInningBtn'

#: Records every label the button shows, from the moment it is installed.
RECORD = """() => {
  const button = document.querySelector('#liveEndInningBtn');
  const seen = window.__cbEndInningLabels = [];
  const note = () => {
    const text = button.innerText.replace(/\\s+/g, ' ').trim();
    if (seen[seen.length - 1] !== text) seen.push(text);
  };
  note();
  new MutationObserver(note).observe(button, {childList: true, subtree: true, characterData: true});
}"""


@pytest.fixture
def live_page(browser, coachboard_url):
    created = []

    def _open(device):
        setup = browser.new_context()
        cdn_assets.install(setup)
        setup_page = setup.new_page()
        login(setup_page, coachboard_url)
        game_id, player_ids = create_named_live_game(setup_page, coachboard_url)
        created.append((setup, setup_page, game_id, player_ids))

        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        login(page, coachboard_url)
        page.goto(f'{coachboard_url}/game/{game_id}')
        page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
        created[-1] += (context,)
        return page, game_id

    yield _open
    for setup, setup_page, game_id, player_ids, *rest in created:
        for context in rest:
            context.close()
        remove_named_live_game(setup_page, coachboard_url, game_id, player_ids)
        setup.close()


def _labels(page):
    return page.evaluate('window.__cbEndInningLabels')


@pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])
def test_end_inning_label_never_flashes_back(live_page, coachboard_url, device):
    page, game_id = live_page(device)
    button = page.locator(BUTTON)
    expect(button).to_contain_text('End 1st → Start 2nd', timeout=15_000)
    page.evaluate(RECORD)

    # Through more than one 15 s command-center refresh and several 3.5 s
    # Next Inning refreshes, with a return to the app in the middle.
    page.wait_for_timeout(10_000)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
    page.wait_for_timeout(11_000)

    labels = _labels(page)
    assert all(label.startswith('End 1st → Start 2nd') for label in labels), labels
    assert not any(re.match(r'^End Inning\b', label) for label in labels), labels
    expect(button).to_have_attribute('aria-label', 'End 1st inning and start 2nd')

    # End Inning still advances, and the label moves on to the next inning.
    button.click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=15_000)
    expect(button).to_contain_text('End 2nd → Start 3rd', timeout=10_000)
    state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
    assert str(state['current_inning']) == '2'

    page.evaluate(RECORD)
    page.wait_for_timeout(4_000)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(2_000)
    labels = _labels(page)
    assert all(label.startswith('End 2nd → Start 3rd') for label in labels), labels
    assert page.cb_errors == []
