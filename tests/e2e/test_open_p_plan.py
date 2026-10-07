"""A next-inning plan with P open: the pitcher carries on, his planned spot
shows open, and End Inning asks about it the usual way.

The 3rd's plan leaves P open and puts Luke Ames -- pitching -- at first base.
The board used to show Luke at P and at 1B, and End Inning was refused.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from live_fixtures import (  # noqa: E402,F401 (live is a fixture)
    INNING_1,
    PHONE,
    advance_inning as _advance,
    game_state as _state,
    live,
)


LUKE, MATEO = INNING_1['P'], INNING_1['1B']
THIRD = dict(INNING_1, P='', **{'1B': LUKE, 'RF': MATEO})          # Carter Diaz sits
PLAN = {'1': INNING_1, '2': INNING_1, '3': THIRD}


def _open(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)


def _next_board(page):
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator('#live-board-prep-v3')
    expect(board).to_be_visible()
    return board


def test_the_pitcher_carries_on_and_his_planned_spot_shows_open(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _advance(page, coachboard_url)                                 # in the 2nd
    _open(page, coachboard_url)
    board = _next_board(page)
    expect(board.locator('[data-next-position="P"]')).to_have_attribute('data-next-player', LUKE)
    expect(board.locator('[data-next-position="1B"]')).to_have_attribute('data-next-player', '')
    expect(board.locator('[data-next-position="RF"]')).to_have_attribute('data-next-player', MATEO)
    players = board.locator('[data-next-position]').evaluate_all(
        'els => els.map(e => e.dataset.nextPlayer).filter(Boolean)')
    assert len(players) == len(set(players)), players

    # A reload shows the same.
    _open(page, coachboard_url)
    board = _next_board(page)
    expect(board.locator('[data-next-position="1B"]')).to_have_attribute('data-next-player', '')

    # End Inning asks about the open spot, as for any open position.
    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    page.locator('#liveEndInningBtn').click()
    incomplete = page.locator('#cbIncompleteNextModal')
    expect(incomplete).to_be_visible(timeout=10_000)
    incomplete.get_by_role('button', name=re.compile(r'^Start 3rd with 1B Open$')).click()
    for _ in range(60):
        if str(_state(page, coachboard_url)['current_inning']) == '3':
            break
        page.wait_for_timeout(250)
    field = _state(page, coachboard_url)['current_alignment']
    assert field['P'] == LUKE and not field.get('1B') and field['RF'] == MATEO
    assert page.cb_errors == []
