"""On the Field → Bench: tap and drag make the same baseball decision.

Sending a fielder to the bench leaves their spot open unless the coach
says who plays it. Tap asks "What should happen at SS?" -- Leave SS open
(one tap, saved at once, the same as dragging to the bench), a bench
player, or a field player whose own spot is then left open. Nothing is
filled automatically. The pitcher is never benched this way.
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
    RELIEVER,
    defense_writes,
    drag,
    filled,
    live_events as events,
    live_field,
    live_state,
    wait_for_field,
)
from test_live_defense_coach_chain import (
    expect_question,
    expect_review,
    pick,
)


SS_OPEN = {pos: name for pos, name in BASE.items() if pos != 'SS'}


def bench_from(page: Page, position: str):
    page.locator(f'#cbQuickDefense [data-cb-position="{position}"]').click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=10_000)
    sheet.locator('[data-cb-bench-current]').click()
    return sheet


def choice(sheet, text):
    return sheet.locator('[data-cb-chain-choices] button', has_text=text)


def test_tap_bench_leave_open_is_one_tap_and_one_undo(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = defense_writes(page)
    before_events = len(events(live_state(page, coachboard_url, game_id)))

    sheet = bench_from(page, 'SS')
    expect_question(sheet, 'Shortstop Shawn is going to the bench', 'What should happen at SS?')
    # Nothing is filled for the coach: open is offered first, then choices.
    expect(sheet.locator('[data-cb-chain-choices] button').first).to_have_text('Leave SS open')
    expect(choice(sheet, RELIEVER)).to_contain_text('Bench → SS')
    expect(choice(sheet, 'Second Sam')).to_contain_text('2B → SS · 2B left open')
    expect(choice(sheet, 'Pitcher Pat')).to_have_count(0)
    assert writes == []

    pick(sheet, 'Leave SS open')
    expect(sheet).not_to_be_visible(timeout=10_000)
    wait_for_field(page, coachboard_url, game_id, SS_OPEN)
    assert len(writes) == 1
    assert len(events(live_state(page, coachboard_url, game_id))) == before_events + 1

    page.locator('#liveUndoBtn').click()
    wait_for_field(page, coachboard_url, game_id, BASE)


def test_drag_to_bench_makes_the_same_field(page: Page, coachboard_url, live_field):
    game_id = live_field()
    quick = page.locator('#cbQuickDefense')
    drag(page, quick.locator('[data-cb-position="SS"]'), quick.locator('.cb-qd-bench-wrap'))
    wait_for_field(page, coachboard_url, game_id, SS_OPEN)


def test_bench_player_fills_the_vacated_spot(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = defense_writes(page)
    sheet = bench_from(page, 'SS')
    assert writes == []
    # Two players, both placed by the coach: saved on that choice.
    choice(sheet, RELIEVER).click()
    wait_for_field(page, coachboard_url, game_id, dict(BASE, SS=RELIEVER))
    expect(sheet).not_to_be_visible(timeout=10_000)
    assert len(writes) == 1

    page.locator('#liveUndoBtn').click()
    wait_for_field(page, coachboard_url, game_id, BASE)


def test_fielder_fills_the_vacated_spot_and_their_spot_is_left_open(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    sheet = bench_from(page, 'SS')
    choice(sheet, 'Second Sam').click()
    expected = {pos: name for pos, name in BASE.items() if pos not in ('SS', '2B')}
    expected['SS'] = 'Second Sam'
    wait_for_field(page, coachboard_url, game_id, expected)
    expect(page.locator('#cbQuickDefense [data-cb-position="2B"]')).to_contain_text(
        'Open', timeout=10_000
    )

    # A follow-on move onto an occupied spot is still the coach's chain.
    page.wait_for_timeout(300)
    page.locator('#cbQuickDefense [data-cb-position="1B"]').click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=10_000)
    sheet.locator('[data-cb-destination="SS"]').click()
    expect_question(sheet, 'First Frank is moving to SS', 'Where should Second Sam go?')
    pick(sheet, 'Cancel')
    expect(sheet).not_to_be_visible(timeout=10_000)
    wait_for_field(page, coachboard_url, game_id, expected)


def test_cancel_changes_nothing(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = defense_writes(page)

    sheet = bench_from(page, 'SS')
    pick(sheet, 'Cancel')
    expect(sheet).not_to_be_visible(timeout=10_000)

    page.wait_for_timeout(500)
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE


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
