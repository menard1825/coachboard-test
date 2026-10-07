"""On the Field: moving a fielder onto P is a pitching change, not a move.

P is not a destination on the Move sheet, and dropping a fielder on P opens
Change Pitcher and changes nothing on the field. (The old displaced-player
chain questions were retired: field → occupied is now an immediate swap and
bench → occupied sends the fielder to the bench; see
test_live_move_single_writer.)
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect

from live_fixtures import (  # noqa: F401 (fixture)
    BASE,
    MOVE_SHEET as SHEET,
    defense_writes,
    drag,
    field_player,
    filled,
    live_field,
    live_state,
)


def test_moving_onto_p_goes_to_change_pitcher(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = defense_writes(page)
    quick = page.locator('#cbQuickDefense')

    # P is not an ordinary destination on the Move sheet...
    quick.locator(field_player('2B')).click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=10_000)
    expect(sheet.locator('[data-cb-destination="P"]')).to_have_count(0)
    sheet.locator('.btn-close').click()
    expect(sheet).not_to_be_visible(timeout=10_000)

    # ...and dropping a fielder on P opens Change Pitcher, changing nothing.
    page.wait_for_timeout(750)
    drag(page, quick.locator(field_player('2B')), quick.locator(field_player('P')))
    expect(page.locator('#live-pitcher-picker-v2')).to_be_visible(timeout=10_000)
    page.wait_for_timeout(400)
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE
