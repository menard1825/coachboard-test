"""End Inning asks two separate, clearly labelled questions.

1. The inning being recorded: an open position On the Field may be a
   recording mistake, so it is asked about -- as that inning's record,
   never as if the next inning's plan were open. "Keep as Recorded" is
   remembered for that exact recorded defense.
2. The next inning's plan (prep.confirmed.alignment, after the save queue
   settles): its open positions are named for that inning, and the same
   alignment is what advance-inning receives.
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

from test_next_inning_save_queue import (  # noqa: F401 (fixture)
    bench,
    board_alignment,
    filled,
    live_state,
    next_board,
    open_on_the_field,
    other_coach_sets,
    server_next,
    slow_network,
    spot,
    wait_for_server,
)
from test_next_inning_save_race import starting_alignment


START = filled(starting_alignment())
INCOMPLETE = '#cbIncompleteNextModal'
RECORDED = '#cbRecordedInningGapModal'


def advance_posts(page: Page):
    posts = []
    page.on(
        'request',
        lambda r: posts.append(r.post_data_json)
        if r.method == 'POST' and r.url.endswith('/advance-inning') else None,
    )
    return posts


def end_inning(page: Page):
    page.locator('#liveEndInningBtn').click()


def expect_started_with(page: Page, url: str, game_id: int, alignment):
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    assert filled(live_state(page, url, game_id)['current_alignment']) == alignment


def test_screenshot_case_cf_open_on_the_field_but_filled_in_the_plan(
    page: Page, coachboard_url, next_board
):
    """On the Field CF is open this inning; the plan has Casey at CF."""
    board, game_id = next_board
    posts = advance_posts(page)
    open_on_the_field(page, coachboard_url, game_id, 'CF')
    page.reload(wait_until='domcontentloaded')
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    # The plan follows the field (CF open); the coach fills CF in the plan.
    expect(spot(board, 'CF')).to_have_attribute('data-next-player', '', timeout=10_000)
    board.locator('[data-next-bench-player="Center Casey"]').click()
    spot(board, 'CF').click()
    expect(spot(board, 'CF')).to_have_attribute('data-next-player', 'Center Casey', timeout=2_000)
    wait_for_server(page, coachboard_url, game_id, START)

    end_inning(page)
    # Asked about the 1st inning's record -- not the 2nd inning's plan.
    recorded = page.locator(RECORDED)
    expect(recorded.locator('.modal-title')).to_have_text(
        '1st inning record has an open position', timeout=10_000
    )
    expect(recorded).to_contain_text(
        'CF was left open on the recorded defense for the 1st inning.'
    )
    expect(recorded).not_to_contain_text('available on the bench')
    recorded.get_by_role('button', name='Keep as Recorded').click()

    # Casey is at CF in the plan: no 2nd-inning CF warning, and the plan
    # with Casey at CF is what advance-inning receives.
    expect_started_with(page, coachboard_url, game_id, START)
    expect(page.locator(INCOMPLETE)).not_to_be_visible()
    assert filled(posts[-1]['alignment']) == START
    assert posts[-1]['alignment']['CF'] == 'Center Casey'


def test_inverse_full_record_but_the_plan_has_cf_open(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    posts = advance_posts(page)
    plan = {pos: n for pos, n in START.items() if pos != 'CF'}
    other_coach_sets(page, coachboard_url, game_id, plan)
    expect(spot(board, 'CF')).to_have_attribute('data-next-player', '', timeout=10_000)

    end_inning(page)
    incomplete = page.locator(INCOMPLETE)
    expect(incomplete.locator('.modal-title')).to_have_text(
        '2nd inning defense has CF open', timeout=10_000
    )
    expect(incomplete).to_contain_text('CF is open, and players are available on the bench.')
    expect(page.locator(RECORDED)).not_to_be_visible()
    incomplete.get_by_role('button', name='Start 2nd with CF Open').click()
    expect_started_with(page, coachboard_url, game_id, plan)
    assert filled(posts[-1]['alignment']) == plan


def test_fix_first_inning_goes_back_without_advancing(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    posts = advance_posts(page)
    open_on_the_field(page, coachboard_url, game_id, 'CF')
    page.reload(wait_until='domcontentloaded')
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()

    end_inning(page)
    recorded = page.locator(RECORDED)
    expect(recorded).to_be_visible(timeout=10_000)
    recorded.get_by_role('button', name='Fix 1st Inning').click()
    expect(recorded).not_to_be_visible(timeout=10_000)
    expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=10_000)
    page.wait_for_timeout(500)
    assert posts == []
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'


def test_move_leaving_old_spot_open_names_the_actual_open_spot(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    posts = advance_posts(page)
    bench(board, 'CF')
    board.locator('[data-next-position="LF"]').click()
    spot(board, 'CF').click()
    plan = {pos: n for pos, n in START.items() if pos != 'LF'}
    plan['CF'] = 'Left Lee'
    wait_for_server(page, coachboard_url, game_id, plan)

    end_inning(page)
    incomplete = page.locator(INCOMPLETE)
    expect(incomplete).to_contain_text('LF is open, and players are available on the bench.', timeout=10_000)
    expect(incomplete).not_to_contain_text('CF')
    incomplete.get_by_role('button', name='Start 2nd with LF Open').click()
    expect_started_with(page, coachboard_url, game_id, plan)
    assert filled(posts[-1]['alignment']) == plan


def test_resolved_chain_is_what_is_validated_and_sent(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    posts = advance_posts(page)
    # SS -> 2B; the coach benches Sam: SS is open in the plan.
    spot(board, 'SS').click()
    spot(board, '2B').click()
    page.locator('#cbNextPitchingChange').get_by_role(
        'button', name='Bench Second Sam', exact=True
    ).click()
    plan = {pos: n for pos, n in START.items() if pos != 'SS'}
    plan['2B'] = 'Shortstop Shawn'
    wait_for_server(page, coachboard_url, game_id, plan)

    end_inning(page)
    incomplete = page.locator(INCOMPLETE)
    expect(incomplete).to_contain_text('SS is open, and players are available on the bench.', timeout=10_000)
    incomplete.get_by_role('button', name='Start 2nd with SS Open').click()
    expect_started_with(page, coachboard_url, game_id, plan)
    assert filled(posts[-1]['alignment']) == plan


def test_bench_to_occupied_chain_is_what_is_validated_and_sent(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    bench(board, 'CF')
    board.locator('[data-next-bench-player="Center Casey"]').click()
    spot(board, 'SS').click()
    page.locator('#cbNextPitchingChange').get_by_role(
        'button', name='Put Shortstop Shawn at CF', exact=True
    ).click()
    plan = dict(START, SS='Center Casey', CF='Shortstop Shawn')
    wait_for_server(page, coachboard_url, game_id, plan)

    end_inning(page)
    expect_started_with(page, coachboard_url, game_id, plan)
    expect(page.locator(INCOMPLETE)).not_to_be_visible()


def test_end_inning_waits_for_the_save_in_flight_then_validates_it(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    bench(board, 'RF')
    wait_for_server(page, coachboard_url, game_id, {p: n for p, n in START.items() if p != 'RF'})

    # Fill RF on a slow connection and End Inning at once: the check must
    # wait for that save and see RF filled.
    slow_network(page)
    board.locator('[data-next-bench-player="Right Riley"]').click()
    spot(board, 'RF').click()
    end_inning(page)
    expect_started_with(page, coachboard_url, game_id, START)
    expect(page.locator(INCOMPLETE)).not_to_be_visible()


def test_another_coachs_plan_is_the_one_validated(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    other = {pos: n for pos, n in START.items() if pos != 'CF'}
    other_coach_sets(page, coachboard_url, game_id, other)
    expect(spot(board, 'CF')).to_have_attribute('data-next-player', '', timeout=10_000)

    end_inning(page)
    expect(page.locator(INCOMPLETE)).to_contain_text('CF is open, and players are available on the bench.', timeout=10_000)
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'


def test_missing_pitcher_is_still_a_hard_stop(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    posts = advance_posts(page)
    other_coach_sets(page, coachboard_url, game_id, {p: n for p, n in START.items() if p != 'P'})
    expect(spot(board, 'P')).to_have_attribute('data-next-player', '', timeout=10_000)

    end_inning(page)
    expect(board.locator('.cb-next-error, .cb-next-warnings').first).to_contain_text(
        'Set a pitcher for the next inning', timeout=10_000
    )
    expect(page.locator(INCOMPLETE)).not_to_be_visible()
    page.wait_for_timeout(500)
    assert posts == []
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'
