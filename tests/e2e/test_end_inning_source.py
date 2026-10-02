"""End Inning says which defense goes out, asks before a plan is skipped, and
never starts an inning on a change that did not save.

* Beside End Inning (every tab): "Plan for the 2nd", "Same as the 1st",
  "Your changes for the 2nd" (this board's own save; "Changes for the 2nd"
  for another device's) -- or the save state while that matters.
* A live change this inning carries the field forward and skips the next
  inning's own pregame plan by default. Nobody chose that, so End Inning
  asks once: "Use the 2nd-inning plan" or "Keep this defense". The answer is
  saved as the coach's choice: not asked again, kept through later changes.
* A save still in flight holds End Inning until it lands.
* A change refused because another device changed the defense says "Not
  saved" (never "Saved"), shows that device's defense, and holds End Inning
  until the coach accepts it ("Use this defense") or changes it. If that
  defense can't be read, the board says so and offers Try again instead;
  nothing can be accepted, and End Inning stays held, until it loads.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_reference import (  # noqa: E402,F401 (live is a fixture)
    INNING_1, PHONE, _api, _field_edit, _set_next, live,
)


# The 2nd's own plan: shortstop and second base swap. A live change in the
# 1st swaps left and right field instead.
INNING_2 = {**INNING_1, 'SS': INNING_1['2B'], '2B': INNING_1['SS']}
PLAN = {'1': INNING_1, '2': INNING_2}
FIELD_SWAP = {'LF': INNING_1['RF'], 'RF': INNING_1['LF']}
CARRIED = {**INNING_1, **FIELD_SWAP}
NOTE = '#liveEndInningBtn .coach-action-note'
QUESTION = '#cbSkippedPlanModal'


def _open(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)


def _live(page, coachboard_url):
    return page.cb_api.request.get(_api(page, coachboard_url, 'state')).json()


def _filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def _inning(page, coachboard_url):
    return str(_live(page, coachboard_url)['current_inning'])


def _wait_inning(page, coachboard_url, inning):
    for _ in range(60):
        if _inning(page, coachboard_url) == inning:
            return
        page.wait_for_timeout(250)
    assert _inning(page, coachboard_url) == inning


def _prep(page, coachboard_url):
    return page.cb_api.request.get(_api(page, coachboard_url, 'next-inning-prep')).json()


# The source beside End Inning -------------------------------------------------------------

def test_end_inning_names_the_defense_that_goes_out(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _open(page, coachboard_url)
    expect(page.locator(NOTE)).to_have_text('Plan for the 2nd')
    # A live change carries the field forward; the plan is not being used.
    _field_edit(page, coachboard_url, **FIELD_SWAP)
    expect(page.locator(NOTE)).to_have_text('Same as the 1st · plan not used', timeout=10_000)
    assert page.cb_errors == []


# The skipped plan --------------------------------------------------------------------------

def test_a_live_change_then_end_inning_asks_and_can_use_the_plan(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _open(page, coachboard_url)
    _field_edit(page, coachboard_url, **FIELD_SWAP)
    expect(page.locator(NOTE)).to_have_text('Same as the 1st · plan not used', timeout=10_000)

    page.locator('#liveEndInningBtn').click()                 # never visited Next
    question = page.locator(QUESTION)
    expect(question.locator('.modal-title')).to_have_text('Use the 2nd-inning plan?', timeout=10_000)
    question.get_by_role('button', name='Use the 2nd-inning plan').click()

    _wait_inning(page, coachboard_url, '2')
    assert _filled(_live(page, coachboard_url)['current_alignment']) == INNING_2
    assert page.cb_errors == []


def test_keep_this_defense_starts_the_carried_field(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _open(page, coachboard_url)
    _field_edit(page, coachboard_url, **FIELD_SWAP)
    expect(page.locator(NOTE)).to_have_text('Same as the 1st · plan not used', timeout=10_000)

    page.locator('#liveEndInningBtn').click()
    question = page.locator(QUESTION)
    expect(question).to_be_visible(timeout=10_000)
    question.get_by_role('button', name='Keep this defense').click()

    _wait_inning(page, coachboard_url, '2')
    assert _filled(_live(page, coachboard_url)['current_alignment']) == CARRIED
    assert page.cb_errors == []


def test_a_saved_choice_is_not_asked_again_and_survives_later_changes(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _field_edit(page, coachboard_url, **FIELD_SWAP)
    # The coach kept the carried field (on the Next tab, earlier).
    response = page.cb_api.request.post(_api(page, coachboard_url, 'next-inning-prep'), data={'mode': 'current'})
    assert response.ok, response.text()[:200]
    # A later live change: the kept defense follows the field, still the coach's.
    _field_edit(page, coachboard_url, SS=INNING_1['2B'], **{'2B': INNING_1['SS']})
    prep = _prep(page, coachboard_url)
    assert prep['confirmed']['updated_by'] != 'Auto'
    assert _filled(prep['confirmed']['alignment']) == {**CARRIED, 'SS': INNING_1['2B'], '2B': INNING_1['SS']}

    _open(page, coachboard_url)
    expect(page.locator(NOTE)).to_have_text('Same as the 1st')
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '2')
    expect(page.locator(QUESTION)).to_have_count(0)
    assert page.cb_errors == []


def test_a_chosen_plan_is_kept_through_a_later_live_change(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _field_edit(page, coachboard_url, **FIELD_SWAP)
    response = page.cb_api.request.post(_api(page, coachboard_url, 'next-inning-prep'), data={'mode': 'planned'})
    assert response.ok, response.text()[:200]
    _field_edit(page, coachboard_url, **{'1B': INNING_1['3B'], '3B': INNING_1['1B']})
    assert _filled(_prep(page, coachboard_url)['confirmed']['alignment']) == INNING_2

    _open(page, coachboard_url)
    expect(page.locator(NOTE)).to_have_text('Plan for the 2nd')
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '2')
    expect(page.locator(QUESTION)).to_have_count(0)
    assert _filled(_live(page, coachboard_url)['current_alignment']) == INNING_2
    assert page.cb_errors == []


def test_no_question_without_a_separate_plan(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1})          # nothing planned for the 2nd
    _open(page, coachboard_url)
    _field_edit(page, coachboard_url, **FIELD_SWAP)
    expect(page.locator(NOTE)).to_have_text('Same as the 1st', timeout=10_000)
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '2')
    expect(page.locator(QUESTION)).to_have_count(0)
    assert page.cb_errors == []


def test_this_boards_own_save_is_your_changes(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1, '2': INNING_1})
    _open(page, coachboard_url)
    _bench_right_field(page)
    expect(page.locator(NOTE)).to_have_text('Your changes for the 2nd', timeout=10_000)
    # Another device saves over it: no longer this board's changes.
    _set_next(page, coachboard_url, {**INNING_1, **FIELD_SWAP})
    expect(page.locator(NOTE)).to_have_text('Changes for the 2nd', timeout=10_000)
    assert page.cb_errors == []


# Saves that have not landed ---------------------------------------------------------------

def _hold_saves(page):
    held = []
    page.route('**/next-inning-prep', lambda route: held.append(route)
               if route.request.method == 'POST' else route.continue_())
    return held


def _bench_right_field(page):
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator('#live-board-prep-v3')
    board.locator('[data-next-position="RF"]').click()
    board.locator('[data-next-bench-selected]').click()
    expect(board.locator('[data-next-position="RF"]')).to_have_attribute('data-next-player', '', timeout=3_000)
    return board


def test_a_save_still_in_flight_holds_end_inning(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1, '2': INNING_1})
    _open(page, coachboard_url)
    held = _hold_saves(page)
    _bench_right_field(page)
    expect(page.locator(NOTE)).to_have_text('Saving the 2nd defense…')

    page.locator('#liveEndInningBtn').click()
    page.wait_for_timeout(1_500)
    assert _inning(page, coachboard_url) == '1'                 # waits for the save
    assert held
    for route in held:
        route.continue_()
    page.unroute('**/next-inning-prep')
    # RF is open in the edit: End Inning asks about that, as before.
    incomplete = page.locator('#cbIncompleteNextModal')
    expect(incomplete).to_be_visible(timeout=10_000)
    incomplete.get_by_role('button', name=re.compile(r'^Start 2nd with RF Open$')).click()
    _wait_inning(page, coachboard_url, '2')
    assert 'RF' not in _filled(_live(page, coachboard_url)['current_alignment'])
    assert page.cb_errors == []


def test_a_competing_edit_is_not_shown_as_saved_and_holds_end_inning(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1, '2': INNING_1})
    _open(page, coachboard_url)
    held = _hold_saves(page)
    board = _bench_right_field(page)

    # Meanwhile another device saves a different 2nd inning.
    other = {**INNING_1, **FIELD_SWAP}
    _set_next(page, coachboard_url, other)
    assert held
    for route in held:
        route.continue_()
    page.unroute('**/next-inning-prep')

    badge = board.locator('[data-next-save-state]')
    expect(badge).to_have_text('Not saved', timeout=10_000)
    expect(board.locator('[data-next-notice]')).to_contain_text("Your change wasn't saved")
    expect(board.locator('[data-next-notice]')).to_contain_text('changed on another device')
    expect(board.locator('[data-next-position="RF"]')).to_have_attribute('data-next-player', other['RF'])
    expect(page.locator(NOTE)).to_have_text('Not saved — check the 2nd')
    expect(board.locator('[data-next-hint]')).to_have_text('Saved on another device for the 2nd')

    # End Inning waits for the coach.
    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    page.locator('#liveEndInningBtn').click()
    expect(board).to_be_visible(timeout=10_000)                 # sent back to look
    page.wait_for_timeout(800)
    assert _inning(page, coachboard_url) == '1'
    expect(badge).to_have_text('Not saved')

    # Accepting that defense lets the inning start with it.
    board.locator('[data-next-conflict-ack]').click()
    expect(badge).to_have_text('Saved ✓')
    expect(page.locator(NOTE)).to_have_text('Changes for the 2nd')     # not "Your changes"
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '2')
    assert _filled(_live(page, coachboard_url)['current_alignment']) == other
    assert page.cb_errors == []


def test_a_conflict_whose_new_defense_cannot_load_waits_for_it(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1, '2': INNING_1})
    _open(page, coachboard_url)
    held, reads_fail = [], [False]

    def route(route):
        if route.request.method == 'POST':
            held.append(route)
        elif reads_fail[0]:
            route.abort()
        else:
            route.continue_()

    page.route('**/next-inning-prep', route)
    board = _bench_right_field(page)
    rf_before = board.locator('[data-next-position="RF"]')

    # Another device saves a different 2nd; then this phone's save is
    # refused while it can't read anything.
    other = {**INNING_1, **FIELD_SWAP}
    _set_next(page, coachboard_url, other)
    reads_fail[0] = True
    for held_route in held:
        held_route.continue_()

    badge = board.locator('[data-next-save-state]')
    notice = board.locator('[data-next-notice]')
    expect(badge).to_have_text('Not saved', timeout=10_000)
    expect(notice).to_have_text("Couldn't load the latest defense. Try again.")
    expect(board.locator('[data-next-hint]')).to_have_text(
        'Last loaded defense for the 2nd · may be out of date')
    expect(board.locator('[data-next-conflict-ack]')).to_have_count(0)    # nothing to accept yet
    expect(board.locator('[data-next-conflict-retry]')).to_be_visible()
    expect(rf_before).not_to_have_attribute('data-next-player', other['RF'])
    expect(page.locator(NOTE)).to_have_text('Not saved — check the 2nd')

    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    page.locator('#liveEndInningBtn').click()
    expect(board).to_be_visible(timeout=10_000)                 # sent back to look
    page.wait_for_timeout(800)
    assert _inning(page, coachboard_url) == '1'
    expect(notice).to_have_text("Couldn't load the latest defense. Try again.")

    # The connection is back: Try again (or the poll) loads the other defense.
    reads_fail[0] = False
    page.evaluate("document.querySelector('[data-next-conflict-retry]')?.click()")
    ack = board.locator('[data-next-conflict-ack]')
    expect(ack).to_be_visible(timeout=10_000)
    expect(notice).to_contain_text("Your change wasn't saved")
    expect(notice).to_contain_text('changed on another device')
    expect(board.locator('[data-next-hint]')).to_have_text('Saved on another device for the 2nd')
    expect(board.locator('[data-next-position="RF"]')).to_have_attribute('data-next-player', other['RF'])
    expect(badge).to_have_text('Not saved')

    # Loaded is not accepted: End Inning still waits for the coach.
    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    page.locator('#liveEndInningBtn').click()
    expect(board).to_be_visible(timeout=10_000)
    page.wait_for_timeout(800)
    assert _inning(page, coachboard_url) == '1'

    ack.click()
    expect(badge).to_have_text('Saved ✓')
    expect(page.locator(NOTE)).to_have_text('Changes for the 2nd')
    page.unroute('**/next-inning-prep')
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '2')
    assert _filled(_live(page, coachboard_url)['current_alignment']) == other
    assert page.cb_errors == []
