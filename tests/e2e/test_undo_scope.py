"""Undo on the live screen is the live game's Undo.

After a Next Inning edit, ending the inning and tapping the header Undo
takes back the inning change. (Plan Undo lives in the planner; see
test_next_plan_undo_ownership.)
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
    api_url as _api,
    end_inning_from_live,
    live,
    open_next_inning_planner,
    return_to_live_field,
)


UNDO = '#liveUndoBtn'
BOARD = '#live-board-prep-v3'
PLAN = {'1': INNING_1, '2': INNING_1}


def _open(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)


def _planner(page):
    open_next_inning_planner(page)
    board = page.locator(BOARD)
    expect(board).to_be_visible()
    return board


def _prep(page, coachboard_url):
    return page.cb_api.request.get(_api(page, coachboard_url, 'next-inning-prep')).json()['confirmed']


def _filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def _bench_right_field(page, coachboard_url, board):
    board.locator('[data-next-position="RF"]').click()
    board.locator('[data-next-bench-selected]').click()
    expect(board.locator('[data-next-position="RF"]')).to_have_attribute('data-next-player', '', timeout=3_000)
    for _ in range(40):                                 # saved on the server
        if 'RF' not in _filled(_prep(page, coachboard_url)['alignment']):
            break
        page.wait_for_timeout(250)
    expect(board.locator('[data-next-save-state]')).to_have_class(re.compile(r'\bsaved\b'), timeout=10_000)


def test_undo_on_the_field_is_still_the_live_undo(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _open(page, coachboard_url)
    board = _planner(page)
    _bench_right_field(page, coachboard_url, board)
    return_to_live_field(page)

    # End the 1st, then undo it from the live field: the live Undo.
    end_inning_from_live(page)
    incomplete = page.locator('#cbIncompleteNextModal')
    expect(incomplete).to_be_visible(timeout=10_000)
    incomplete.get_by_role('button', name=re.compile(r'^Start 2nd with RF Open$')).click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    page.wait_for_timeout(800)
    page.locator(UNDO).click()
    expect(page.locator('#live-inning-display')).to_have_text('1', timeout=10_000)
    assert page.cb_errors == []
