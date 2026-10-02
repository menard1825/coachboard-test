"""A planned pitching takeover carries forward in the live game.

Every inning was first filled with Luke Ames at P; then Mateo Cruz was
planned to take over in the 3rd (Luke to first base). The 4th and 5th plans
still name Luke at P. Ending the 3rd starts the 4th with Mateo still pitching
and Luke at first -- the other positions as planned -- and End Inning says so
beforehand. No removed-pitcher warning, and the same after a reload.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_reference import (  # noqa: E402,F401 (live is a fixture)
    INNING_1, PHONE, _advance, _api, _state, live,
)


LUKE, MATEO = INNING_1['P'], INNING_1['1B']


def _rotated(inning):
    """The outfield rotates every inning, as planned."""
    alignment = dict(INNING_1)
    if inning % 2 == 0:
        alignment['LF'], alignment['RF'] = INNING_1['RF'], INNING_1['LF']
    return alignment


PLAN = {str(i): _rotated(i) for i in range(1, 6)}
PLAN['3'] = dict(_rotated(3), P=MATEO, **{'1B': LUKE})            # Mateo takes over
NOTE = '#liveEndInningBtn .coach-action-note'


def _carried(inning):
    return dict(PLAN[inning], P=MATEO, **{'1B': LUKE})


def _filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def _open(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)


def _wait_inning(page, coachboard_url, inning):
    for _ in range(60):
        if str(_state(page, coachboard_url)['current_inning']) == inning:
            return
        page.wait_for_timeout(250)
    assert str(_state(page, coachboard_url)['current_inning']) == inning


def test_the_new_pitcher_keeps_pitching_after_the_planned_takeover(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _advance(page, coachboard_url)
    _advance(page, coachboard_url)                                 # the 3rd, as planned
    assert _filled(_state(page, coachboard_url)['current_alignment']) == PLAN['3']

    _open(page, coachboard_url)
    expect(page.locator(NOTE)).to_have_text(f'Plan for the 4th · {MATEO} keeps pitching')
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator('#live-board-prep-v3')
    expect(board.locator('[data-next-position="P"]')).to_have_attribute('data-next-player', MATEO)
    expect(board.locator('[data-next-position="1B"]')).to_have_attribute('data-next-player', LUKE)
    expect(board.locator('[data-next-hint]')).to_have_text(
        f'Pregame plan for the 4th · {MATEO} keeps pitching (the plan had {LUKE}, who already came out)')

    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '4')
    assert _filled(_state(page, coachboard_url)['current_alignment']) == _carried('4')
    # No pitcher question or warning on the way (Luke's own status on the
    # pitching card still says he can't return -- that is correct).
    expect(page.locator('.modal.show')).to_have_count(0)
    expect(page.get_by_text(re.compile('already pitched and was removed')).locator('visible=true')).to_have_count(0)

    # A reload: the 5th is prepared the same way.
    _open(page, coachboard_url)
    expect(page.locator(NOTE)).to_have_text(f'Plan for the 5th · {MATEO} keeps pitching')
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '5')
    assert _filled(_state(page, coachboard_url)['current_alignment']) == _carried('5')
    # The saved plan is the reference, unchanged.
    prep = page.cb_api.request.get(_api(page, coachboard_url, 'next-inning-prep')).json()
    assert prep['pregame_rotation']['4']['P'] == LUKE
    assert page.cb_errors == []
