"""End Inning with no pitcher for the next inning: one message, focus on P.

End Inning correctly refuses a next inning with P open, but said so twice
("Set a pitcher for the next inning." as the Next Inning board's warning and
again as its error line) and left focus nowhere. Now the board's own line is
the only message, and focus goes to the P spot -- where the pitcher is
chosen -- which is described by that line. Choosing a pitcher there lets
the inning start.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_reference import (  # noqa: E402,F401 (live is a fixture)
    INNING_1, PHONE, _api, _state, live,
)


BOARD = '#live-board-prep-v3'
MESSAGE = 'Set a pitcher for the next inning.'


def _open_p_next(page, url):
    prep = page.cb_api.request.get(_api(page, url, 'next-inning-prep')).json()
    response = page.cb_api.request.post(_api(page, url, 'next-inning-prep'), data={
        'mode': 'custom', 'alignment': dict(prep['confirmed']['alignment'], P=''),
        'base_alignment': prep['confirmed']['alignment'], 'inning': prep['next_inning']})
    assert response.ok, response.text()[:300]


def _visible_messages(page):
    return page.evaluate(f"""() => [...document.querySelectorAll('body *')].filter(el =>
        el.children.length === 0 && el.textContent.includes({MESSAGE!r}) && el.checkVisibility()).length""")


def test_open_p_shows_one_message_and_focuses_the_pitcher_spot(live, coachboard_url):
    page = live(PHONE)
    _open_p_next(page, coachboard_url)
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(1_500)

    page.locator('#liveEndInningBtn').click()
    spot = page.locator(f'{BOARD} [data-next-position="P"]')
    expect(spot).to_be_focused(timeout=5_000)
    assert _visible_messages(page) == 1
    # The focused spot carries the reason.
    described = page.evaluate(f"""() => document.getElementById(
        document.querySelector('{BOARD} [data-next-position="P"]').getAttribute('aria-describedby'))?.textContent""")
    assert described == MESSAGE
    assert str(_state(page, coachboard_url)['current_inning']) == '1'

    # The coach picks the planned reliever for P; End Inning then starts the 2nd.
    board = page.locator(BOARD)
    reliever = INNING_1['1B']
    board.locator(f'[data-next-bench-player="{reliever}"]').click()
    spot.click()
    expect(spot).to_have_attribute('data-next-player', reliever, timeout=3_000)
    expect(board.locator('.cb-next-save')).to_have_class(re.compile(r'\bsaved\b'), timeout=5_000)
    page.locator('#liveEndInningBtn').click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=10_000)
    assert _visible_messages(page) == 0
    assert page.cb_errors == []
