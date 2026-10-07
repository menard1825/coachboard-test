"""A double tap in Change Pitcher saves once, and only what was tapped.

Phones double-tap. In the current one-decision flow:

* on the incoming pitcher: the first tap chooses them and the list starts to
  close; the second lands on the closing list (or, if slower, on the
  question's backdrop as it appears). It must not choose again, answer the
  question or dismiss it: the question for the first pitcher opens and
  nothing is saved until the coach answers.
* on a destination: the choice is saved once, exactly as labelled, and the
  question closes. Nothing is left open or stuck, and Change Pitcher opens
  again normally.

(The old review step and its double-tap guard are gone; see
test_live_change_pitcher_decision for the flow itself.)
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect  # noqa: E402

from change_pitcher_flow import (  # noqa: E402
    DESTINATION_QUESTION,
    choose_incoming_pitcher,
    choose_outgoing_destination,
    expect_destination_question,
    incoming_pitcher_row,
    open_change_pitcher,
    outcome_of,
    pitcher_outcome_choices,
    record_pitching_changes,
    wait_for_pitcher_change,
)
from live_fixtures import (  # noqa: E402,F401 (live_field is a fixture)
    BASE,
    filled,
    live_field,
    live_state,
    pitcher_changes,
)


OUTGOING = 'Pitcher Pat'


@pytest.fixture(scope='session')
def browser_context_args(browser_context_args):
    """A phone: real touch taps (the live_field fixture sets the size)."""
    return {**browser_context_args, 'has_touch': True, 'is_mobile': True}


def centre(locator):
    box = locator.bounding_box()
    return box['x'] + box['width'] / 2, box['y'] + box['height'] / 2


def double_tap(page: Page, locator, gesture: str):
    if gesture == 'dblclick':
        locator.dblclick()
        return
    x, y = centre(locator)
    gap_ms = int(gesture.split('-')[1])
    page.touchscreen.tap(x, y)
    page.wait_for_timeout(gap_ms)
    page.touchscreen.tap(x, y)


def no_dialog_left_open(page: Page):
    expect(page.locator('.modal.show')).to_have_count(0, timeout=10_000)
    expect(page.locator('.modal-backdrop')).to_have_count(0)


@pytest.mark.parametrize('gesture', ['touch-80', 'touch-250', 'dblclick'])
def test_a_double_tap_on_the_incoming_pitcher_asks_once_and_saves_nothing(
    page: Page, coachboard_url, live_field, gesture
):
    game_id = live_field()
    posts = record_pitching_changes(page)

    picker = open_change_pitcher(page)
    page.wait_for_function(
        "() => document.querySelector('#live-pitcher-picker-v2').contains(document.activeElement)")
    double_tap(page, incoming_pitcher_row(picker, 'Shortstop Shawn'), gesture)

    # The question for the pitcher tapped first -- not another row's, not
    # dismissed -- and nothing saved.
    question = page.locator(DESTINATION_QUESTION)
    expect(question).to_be_visible(timeout=10_000)
    page.wait_for_timeout(1_200)
    expect(question).to_be_visible()
    expect(picker).not_to_be_visible()
    expect_destination_question(question, 'Shortstop Shawn', OUTGOING)
    assert pitcher_outcome_choices(question)[:2] == [f'Bench {OUTGOING} · SS open', f'{OUTGOING} → SS']
    assert posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE

    # The coach answers normally: one change, as chosen.
    choose_outgoing_destination(question, f'{OUTGOING} → SS')
    wait_for_pitcher_change(page, coachboard_url, game_id, dict(BASE, P='Shortstop Shawn', SS=OUTGOING))
    assert len(posts) == 1
    no_dialog_left_open(page)


@pytest.mark.parametrize('gesture', ['touch-80', 'touch-250', 'dblclick'])
def test_a_double_tap_on_a_destination_saves_it_once(
    page: Page, coachboard_url, live_field, gesture
):
    game_id = live_field()
    posts = record_pitching_changes(page)

    question = choose_incoming_pitcher(page, 'Shortstop Shawn')
    page.wait_for_function(
        f"() => document.querySelector('{DESTINATION_QUESTION}').contains(document.activeElement)")
    label = f'{OUTGOING} → 1B · First Frank → SS'
    expected = outcome_of(label, BASE, 'Shortstop Shawn', OUTGOING)
    double_tap(page, question.get_by_role('button', name=label, exact=True), gesture)

    # Saved once, exactly as labelled; the question closed.
    wait_for_pitcher_change(page, coachboard_url, game_id, expected)
    expect(question).not_to_be_visible(timeout=10_000)
    page.wait_for_timeout(1_000)
    assert len(posts) == 1
    assert filled(posts[0]['alignment']) == expected
    assert len(pitcher_changes(live_state(page, coachboard_url, game_id))) == 1
    no_dialog_left_open(page)

    # Change Pitcher still works.
    question = choose_incoming_pitcher(page, 'First Frank')
    expect_destination_question(question, 'First Frank', 'Shortstop Shawn')
    choose_outgoing_destination(question, 'Cancel')
