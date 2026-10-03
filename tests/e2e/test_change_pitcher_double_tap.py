"""A double tap in Change Pitcher never answers a step the coach has not seen.

When the pitcher coming out takes a fielder's position, the fielder's
question has "Bench First Frank" where the next step -- the review of the
whole change -- draws "Make this change". A double tap on "Bench First
Frank" used to land its second tap on "Make this change" about 14 ms later:
one save, never reviewed. A step that replaces the one just answered now
ignores taps for a moment, and any tap whose press began before it
appeared; a deliberate tap still answers it, and still saves once.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect  # noqa: E402

from test_live_change_pitcher_decision import (  # noqa: E402,F401 (live_field is a fixture)
    BASE, QUESTION, live_field, live_state, ready, wait_for_field,
)


def _to_the_fielders_question(page):
    page.locator('#liveChangePitcherBtn').click()
    picker = page.locator('#live-pitcher-picker-v2')
    expect(picker).to_be_visible(timeout=10_000)
    picker.locator('.pitcher-choice-v2', has=page.get_by_text('Shortstop Shawn', exact=True)).click()
    question = page.locator(QUESTION)
    page.wait_for_function(f"() => document.querySelector('{QUESTION}')?.classList.contains('show')", timeout=10_000)
    question.get_by_role('button', name='Move Pitcher Pat to another position…', exact=True).click()
    ready(question)
    question.get_by_role('button', name='1B · First Frank', exact=True).click()
    ready(question)
    return question


def test_a_double_tap_does_not_confirm_the_change(page: Page, coachboard_url, live_field):
    game_id = live_field()
    saves = []
    page.on('request', lambda r: saves.append(r) if r.method == 'POST' and 'complete-pitcher-change' in r.url else None)
    question = _to_the_fielders_question(page)

    bench = question.locator('[data-pc-choices] button', has_text='Bench First Frank')
    box = bench.bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    page.mouse.click(x, y)
    page.wait_for_timeout(14)
    # The review is drawn under the finger ...
    assert page.evaluate('([x, y]) => document.elementFromPoint(x, y)?.textContent?.trim()', [x, y]) == 'Make this change'
    page.mouse.click(x, y)
    page.wait_for_timeout(1_000)

    # ... and the second tap did not answer it: nothing saved, the review is up.
    assert saves == []
    expect(question).to_be_visible()
    expect(question.locator('[data-pc-title]')).to_have_text('Check the pitching change')
    assert {p: n for p, n in live_state(page, coachboard_url, game_id)['current_alignment'].items() if n} == BASE
    # Focus stays inside the question.
    assert page.evaluate(f"() => document.querySelector('{QUESTION}').contains(document.activeElement)")

    # A deliberate tap makes the change, once.
    ready(question)
    question.get_by_role('button', name='Make this change', exact=True).click()
    expected = dict(BASE, P='Shortstop Shawn', **{'1B': 'Pitcher Pat'})
    del expected['SS']
    wait_for_field(page, coachboard_url, game_id, expected)
    page.wait_for_timeout(500)
    assert len(saves) == 1
    expect(question).not_to_be_visible()
    expect(page.locator('#liveChangePitcherBtn')).to_be_focused()


def test_a_keyboard_answer_still_works(page: Page, coachboard_url, live_field):
    game_id = live_field()
    question = _to_the_fielders_question(page)
    question.locator('[data-pc-choices] button', has_text='Bench First Frank').focus()
    page.keyboard.press('Enter')
    expect(question.locator('[data-pc-title]')).to_have_text('Check the pitching change')
    ready(question)
    question.get_by_role('button', name='Make this change', exact=True).focus()
    page.keyboard.press('Enter')
    expected = dict(BASE, P='Shortstop Shawn', **{'1B': 'Pitcher Pat'})
    del expected['SS']
    wait_for_field(page, coachboard_url, game_id, expected)
