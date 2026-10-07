"""On the Field → Bench by drag, and the pitcher is never benched this way.

Dragging a fielder to the bench leaves their spot open. Tapping P opens
Change Pitcher, and P is not a drag source. (Tap → Bench and Retry are
covered with both gestures in test_live_move_single_writer.)
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
    filled,
    live_field,
    live_state,
    wait_for_field,
)


SS_OPEN = {pos: name for pos, name in BASE.items() if pos != 'SS'}


def test_drag_to_bench_makes_the_same_field(page: Page, coachboard_url, live_field):
    game_id = live_field()
    quick = page.locator('#cbQuickDefense')
    drag(page, quick.locator('[data-cb-position="SS"]'), quick.locator('.cb-qd-bench-wrap'))
    wait_for_field(page, coachboard_url, game_id, SS_OPEN)


def test_pitcher_is_never_benched_through_the_defense_path(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = defense_writes(page)
    quick = page.locator('#cbQuickDefense')
    picker = page.locator('#live-pitcher-picker-v2')

    # Tapping P opens Change Pitcher, not the Move/Bench sheet.
    quick.locator('[data-cb-position="P"]').click()
    expect(picker).to_be_visible(timeout=10_000)
    expect(page.locator(SHEET)).not_to_be_visible()
    picker.locator('.btn-close').click()
    expect(picker).not_to_be_visible(timeout=10_000)

    # P is not a drag source On the Field: dragging it to the bench does
    # nothing at all.
    page.wait_for_timeout(750)
    drag(page, quick.locator('[data-cb-position="P"]'), quick.locator('.cb-qd-bench-wrap'))
    page.wait_for_timeout(600)
    expect(quick.locator('[data-cb-position="P"]')).to_contain_text('Pitcher Pat')
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE
