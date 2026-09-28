"""Next Inning planning never invents a baseball decision.

"Shawn is moving to 2B next inning" says nothing about Sam, who is planned
at 2B. The plan asks where Sam goes -- no automatic swap or bench -- and
follows the chain for every displaced player. Planning stays fast: moves to
an open spot or the bench are immediate, a one-question answer is saved at
once, and only a longer chain gets a quick check. A resolved chain enters
the save queue as one alignment; an unresolved one never does.
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
    IMMEDIATE_MS,
    bench,
    board_alignment,
    filled,
    next_board,
    other_coach_sets,
    record_prep_posts,
    spot,
    wait_for_server,
)
from test_next_inning_save_race import starting_alignment


SHEET = '#cbNextPitchingChange'


def question(page: Page):
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=5_000)
    return sheet


def choices(sheet):
    return [t.strip() for t in sheet.locator('[data-pitch-choices] button').all_inner_texts()]


def pick(sheet, label):
    sheet.get_by_role('button', name=label, exact=True).click()


def expect_question(sheet, title, text):
    expect(sheet.locator('[data-pitch-title]')).to_have_text(title)
    expect(sheet.locator('[data-pitch-question]')).to_have_text(text)


def move(board, source, target):
    spot(board, source).click()
    spot(board, target).click()


START = filled(starting_alignment())


def test_open_and_bench_moves_stay_immediate(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    posts = record_prep_posts(page)

    # Field -> bench, then field -> open: no question, on the board at once.
    bench(board, 'CF')
    move(board, 'LF', 'CF')
    expect(spot(board, 'CF')).to_have_attribute('data-next-player', 'Left Lee', timeout=IMMEDIATE_MS)
    expect(page.locator(SHEET)).to_be_hidden()

    # Bench -> open.
    board.locator('[data-next-bench-player="Center Casey"]').click()
    spot(board, 'LF').click()
    expect(spot(board, 'LF')).to_have_attribute('data-next-player', 'Center Casey', timeout=IMMEDIATE_MS)
    expect(page.locator(SHEET)).to_be_hidden()

    expected = dict(START, CF='Left Lee', LF='Center Casey')
    wait_for_server(page, coachboard_url, game_id, expected)
    assert posts


def test_occupied_move_asks_and_an_explicit_swap_saves_once(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    posts = record_prep_posts(page)

    move(board, 'SS', '2B')
    sheet = question(page)
    expect_question(sheet, 'Shortstop Shawn is moving to 2B next inning', 'Where should Second Sam go?')
    assert choices(sheet) == [
        'Put Second Sam at SS', 'Move Second Sam to another position…',
        'Bench Second Sam', 'Cancel',
    ]
    # Nothing moves or saves while the coach decides.
    page.wait_for_timeout(500)
    assert posts == []
    assert board_alignment(page) == START

    pick(sheet, 'Put Second Sam at SS')
    # One answer: no extra confirmation for a plan.
    expect(sheet).to_be_hidden(timeout=5_000)
    swapped = dict(START, SS='Second Sam', **{'2B': 'Shortstop Shawn'})
    assert board_alignment(page) == swapped
    wait_for_server(page, coachboard_url, game_id, swapped)
    assert len(posts) == 1
    assert filled(posts[0]['body']['alignment']) == swapped


def test_displaced_player_to_bench(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    move(board, 'SS', '2B')
    pick(question(page), 'Bench Second Sam')
    expected = {pos: name for pos, name in START.items() if pos != 'SS'}
    expected['2B'] = 'Shortstop Shawn'
    wait_for_server(page, coachboard_url, game_id, expected)


def test_bench_player_onto_occupied_spot_asks_about_the_occupant(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    bench(board, 'CF')

    board.locator('[data-next-bench-player="Center Casey"]').click()
    spot(board, 'SS').click()
    sheet = question(page)
    expect_question(sheet, 'Center Casey is moving to SS next inning', 'Where should Shortstop Shawn go?')
    assert choices(sheet) == [
        'Put Shortstop Shawn at CF', 'Move Shortstop Shawn to another position…',
        'Bench Shortstop Shawn', 'Cancel',
    ]
    pick(sheet, 'Put Shortstop Shawn at CF')
    wait_for_server(
        page, coachboard_url, game_id,
        dict(START, SS='Center Casey', CF='Shortstop Shawn'),
    )


def test_three_player_rotation_is_checked_then_saved_as_one_alignment(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    posts = record_prep_posts(page)

    move(board, 'SS', '2B')
    sheet = question(page)
    pick(sheet, 'Move Second Sam to another position…')
    offered = choices(sheet)
    # Shawn, already placed at 2B, is never offered; P is not an ordinary spot.
    assert '2B · Shortstop Shawn' not in offered
    assert not any(label.startswith('P ·') for label in offered)
    pick(sheet, '1B · First Frank')
    expect_question(sheet, 'Second Sam is moving to 1B next inning', 'Where should First Frank go?')
    pick(sheet, 'Put First Frank at SS')

    # A longer chain gets one quick check before it joins the plan.
    expect(sheet.locator('[data-pitch-readiness]')).to_have_text(
        'Shortstop Shawn: SS → 2B\nSecond Sam: 2B → 1B\nFirst Frank: 1B → SS'
    )
    page.wait_for_timeout(400)
    assert posts == []
    assert board_alignment(page) == START

    pick(sheet, 'Save plan')
    rotated = dict(START, **{'2B': 'Shortstop Shawn', '1B': 'Second Sam', 'SS': 'First Frank'})
    wait_for_server(page, coachboard_url, game_id, rotated)
    assert len(posts) == 1
    assert filled(posts[0]['body']['alignment']) == rotated
    assert len(set(rotated.values())) == len(rotated)


def test_cancel_changes_nothing(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    posts = record_prep_posts(page)

    move(board, 'SS', '2B')
    pick(question(page), 'Cancel')
    expect(page.locator(SHEET)).to_be_hidden(timeout=5_000)

    move(board, 'SS', '2B')
    sheet = question(page)
    pick(sheet, 'Move Second Sam to another position…')
    pick(sheet, '1B · First Frank')
    pick(sheet, 'Cancel')
    expect(sheet).to_be_hidden(timeout=5_000)

    page.wait_for_timeout(600)
    assert posts == []
    assert board_alignment(page) == START


def test_another_coachs_update_discards_the_unfinished_question(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    posts = record_prep_posts(page)

    move(board, 'SS', '2B')
    sheet = question(page)
    other = dict(START, LF='Right Riley', RF='Left Lee')
    other_coach_sets(page, coachboard_url, game_id, other)

    expect(sheet).to_be_hidden(timeout=10_000)
    expect(board.locator('[data-next-notice]')).to_have_text(
        'Defense updated by another coach.', timeout=10_000
    )
    assert board_alignment(page) == other
    page.wait_for_timeout(500)
    assert posts == []


def test_pitcher_moves_still_ask_the_pitching_question(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    posts = record_prep_posts(page)

    move(board, 'SS', 'P')
    sheet = question(page)
    expect_question(sheet, 'Shortstop Shawn is going in to pitch', 'Where should Pitcher Pat go?')
    assert choices(sheet) == [
        'Put Pitcher Pat at SS', 'Bench Pitcher Pat · SS open', 'Cancel',
    ]
    pick(sheet, 'Cancel')

    move(board, 'P', 'SS')
    sheet = question(page)
    expect_question(sheet, 'Pitcher Pat is moving to SS', "Who's pitching next inning?")
    pick(sheet, 'Cancel')
    page.wait_for_timeout(400)
    assert posts == []
    assert board_alignment(page) == START
