"""Next Inning planning stays fast and asks only real baseball questions.

Moves to an open spot or the bench are immediate. Tapping an open spot asks
who plays there. Moves involving P still ask the pitching question.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect

from live_fixtures import (  # noqa: F401 (fixture)
    IMMEDIATE_MS,
    bench,
    board_alignment,
    filled,
    next_board,
    record_prep_posts,
    spot,
    wait_for_server,
    starting_alignment,
)


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


def test_tapping_open_position_asks_who_plays_there(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board

    # Make 2B open, then start from the coaching question: "Who plays 2B?"
    bench(board, '2B')
    wait_for_server(
        page, coachboard_url, game_id,
        {pos: name for pos, name in START.items() if pos != '2B'},
    )

    spot(board, '2B').click()
    picker = page.locator('#cbNextOpenPositionPicker')
    expect(picker).to_be_visible(timeout=5_000)
    expect(picker.locator('[data-open-position-title]')).to_have_text(
        'Who plays 2B in the 2nd?'
    )
    expect(picker).to_contain_text('Bench')
    expect(picker).to_contain_text('On the field')

    # The old full-board "STEP 2 · CHOOSE PLAYER" mode is gone.
    expect(board.locator('[data-next-cancel]')).to_have_count(0)

    # Choosing a fielder moves them into the open spot and leaves their
    # previous position open.
    picker.get_by_role(
        'button',
        name=re.compile(r'Shortstop Shawn .* SS'),
    ).click()
    expect(picker).to_be_hidden(timeout=5_000)

    expected = {
        pos: name for pos, name in START.items()
        if pos not in {'2B', 'SS'}
    }
    expected['2B'] = 'Shortstop Shawn'
    wait_for_server(page, coachboard_url, game_id, expected)

    # Fill the newly open SS directly from the bench.
    spot(board, 'SS').click()
    expect(picker).to_be_visible(timeout=5_000)
    expect(picker.locator('[data-open-position-title]')).to_have_text(
        'Who plays SS in the 2nd?'
    )
    picker.get_by_role(
        'button',
        name=re.compile(r'Second Sam'),
    ).click()

    swapped = dict(START, SS='Second Sam', **{'2B': 'Shortstop Shawn'})
    wait_for_server(page, coachboard_url, game_id, swapped)


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
