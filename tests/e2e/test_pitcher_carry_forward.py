"""A planned pitching takeover carries forward in the live game.

Every inning was first filled with Luke Ames at P; then Mateo Cruz was
planned to take over in the 3rd (Luke to first base). The 4th and 5th plans
still name Luke at P. Ending the 3rd starts the 4th with Mateo still pitching
and Luke at first -- the other positions as planned -- and End Inning says so
beforehand. No removed-pitcher warning, and the same after a reload.
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
    advance_inning as _advance,
    api_url as _api,
    game_state as _state,
    live,
)


LUKE, MATEO = INNING_1['P'], INNING_1['1B']


def _rotated(inning):
    """The outfield rotates every inning, as planned."""
    alignment = dict(INNING_1)
    if inning % 2 == 0:
        alignment['LF'], alignment['RF'] = INNING_1['RF'], INNING_1['LF']
    return alignment


PLAN = {str(i): _rotated(i) for i in range(1, 6)}
PLAN['3'] = dict(_rotated(3), P=MATEO, **{'1B': LUKE})            # Mateo takes over
NOTE = '#liveEndInningBtn .coach-action-note'


def _carried(inning):
    return dict(PLAN[inning], P=MATEO, **{'1B': LUKE})


def _filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def _open(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)


def _wait_inning(page, coachboard_url, inning):
    for _ in range(60):
        if str(_state(page, coachboard_url)['current_inning']) == inning:
            return
        page.wait_for_timeout(250)
    assert str(_state(page, coachboard_url)['current_inning']) == inning


def test_the_new_pitcher_keeps_pitching_after_the_planned_takeover(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _advance(page, coachboard_url)
    _advance(page, coachboard_url)                                 # the 3rd, as planned
    assert _filled(_state(page, coachboard_url)['current_alignment']) == PLAN['3']

    _open(page, coachboard_url)
    expect(page.locator(NOTE)).to_have_text(f'Plan for the 4th · {MATEO} keeps pitching')
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator('#live-board-prep-v3')
    expect(board.locator('[data-next-position="P"]')).to_have_attribute('data-next-player', MATEO)
    expect(board.locator('[data-next-position="1B"]')).to_have_attribute('data-next-player', LUKE)
    expect(board.locator('[data-next-hint]')).to_have_text(
        f'Pregame plan for the 4th · {MATEO} keeps pitching; {LUKE} moves to 1B.')
    # Readable on a phone: the line wraps rather than cutting off the reason.
    assert board.locator('[data-next-hint]').evaluate(
        'el => el.scrollWidth <= el.clientWidth + 1 && getComputedStyle(el).whiteSpace === "normal"')

    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '4')
    assert _filled(_state(page, coachboard_url)['current_alignment']) == _carried('4')
    # No pitcher question or warning on the way (Luke's own status on the
    # pitching card still says he can't return -- that is correct).
    expect(page.locator('.modal.show')).to_have_count(0)
    expect(page.get_by_text(re.compile('already pitched and was removed')).locator('visible=true')).to_have_count(0)

    # A reload: the 5th is prepared the same way.
    _open(page, coachboard_url)
    expect(page.locator(NOTE)).to_have_text(f'Plan for the 5th · {MATEO} keeps pitching')
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '5')
    assert _filled(_state(page, coachboard_url)['current_alignment']) == _carried('5')
    # The saved plan is the reference, unchanged.
    prep = page.cb_api.request.get(_api(page, coachboard_url, 'next-inning-prep')).json()
    assert prep['pregame_rotation']['4']['P'] == LUKE
    assert page.cb_errors == []


# The Bench Report's projected sits -------------------------------------------------------

OWEN, COLE = INNING_1['2B'], 'Catcher Cole'        # a third pitcher; a tenth player
SIT_PLAN = {str(i): dict(INNING_1) for i in range(1, 7)}
SIT_PLAN['3'] = dict(INNING_1, P=MATEO, **{'1B': LUKE})            # Mateo takes over
SIT_PLAN['5'] = dict(INNING_1, **{'1B': COLE})                     # Mateo planned to sit
SIT_PLAN['6'] = dict(INNING_1, P=OWEN, **{'2B': LUKE})             # Owen takes over


def _projected(report, name):
    plan = report.locator(f'[data-cb-br-player="{name}"] .cb-br-plan')
    return plan.inner_text() if plan.count() else ''


def test_the_bench_report_projects_the_carried_pitcher(live, coachboard_url):
    page = live(PHONE, plan=SIT_PLAN)
    _advance(page, coachboard_url)
    _advance(page, coachboard_url)                                 # in the 3rd
    _open(page, coachboard_url)
    page.locator('[data-cb-bench-report]').click()
    report = page.locator('#cbBenchReportModal')
    expect(report.locator('[data-cb-br-sitting]')).to_be_visible(timeout=10_000)

    # The 5th: Mateo keeps pitching, so Luke -- not Mateo -- takes the sit
    # the plan gave Mateo. The 6th: Owen pitches, everyone else as planned.
    expect(report.locator(f'[data-cb-br-player="{LUKE}"] .cb-br-plan')).to_have_text('Projected to sit: 5')
    expect(report.locator(f'[data-cb-br-player="{LUKE}"] .cb-br-count')).to_have_text('1 projected')
    assert _projected(report, MATEO) == ''
    expect(report.locator(f'[data-cb-br-player="{COLE}"] .cb-br-plan')).to_have_text('Projected to sit: 4, 6')

    # The games the app prepares agree.
    _advance(page, coachboard_url)                                 # the 4th
    _advance(page, coachboard_url)                                 # the 5th
    field = _filled(_state(page, coachboard_url)['current_alignment'])
    assert field['P'] == MATEO and field['1B'] == COLE and LUKE not in field.values()
    assert page.cb_errors == []


# A saved fielding edit, then a live pitching change -------------------------------------

def test_a_saved_fielding_edit_follows_a_live_pitching_change(live, coachboard_url):
    from live_fixtures import last_sequence as _sequence, set_next_inning as _set_next

    page = live(PHONE, plan={str(i): INNING_1 for i in range(1, 7)})
    _advance(page, coachboard_url)
    _advance(page, coachboard_url)                                 # in the 3rd
    # The coach's 4th: left and right field swap (Luke still at P -- not chosen).
    edit = dict(INNING_1, LF=INNING_1['RF'], RF=INNING_1['LF'])
    _set_next(page, coachboard_url, edit)
    # Change Pitcher: Mateo comes in from 1B, Luke takes 1B.
    api = page.cb_api.request
    state = _state(page, coachboard_url)
    mateo_id = next(p['id'] for p in state['roster'] if p['name'] == MATEO)
    response = api.post(_api(page, coachboard_url, 'change-pitcher'), data={
        'base_sequence': _sequence(state), 'new_pitcher_id': mateo_id, 'outgoing_destination': '1B'})
    assert response.ok, response.text()[:200]
    expected = dict(edit, P=MATEO, **{'1B': LUKE})

    # A live refresh on this same page must not invent another coach.
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator('#live-board-prep-v3')
    expect(board.locator('[data-next-position="P"]')).to_have_attribute('data-next-player', MATEO)
    expect(board.locator('[data-next-notice]')).to_have_text('Next inning defense updated.')

    for _ in range(2):                                             # and after a reload
        _open(page, coachboard_url)
        expect(page.locator(NOTE)).to_have_text(f'Changes for the 4th · {MATEO} keeps pitching')
        page.locator('#cb-now-next-switch [data-now-next="next"]').click()
        board = page.locator('#live-board-prep-v3')
        expect(board.locator('[data-next-position="P"]')).to_have_attribute('data-next-player', MATEO)
        expect(board.locator('[data-next-position="1B"]')).to_have_attribute('data-next-player', LUKE)
        expect(board.locator('[data-next-position="LF"]')).to_have_attribute('data-next-player', edit['LF'])
        expect(board.locator('[data-next-hint]')).to_have_text(
            f'Changes saved for the 4th · {MATEO} keeps pitching; {LUKE} moves to 1B.')

    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '4')
    expect(page.locator('.modal.show')).to_have_count(0)           # no question about Luke
    assert _filled(_state(page, coachboard_url)['current_alignment']) == expected

    # Live Undo restores the saved next defense without attributing it to someone else.
    page.locator('#liveUndoBtn').click()
    _wait_inning(page, coachboard_url, '3')
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator('#live-board-prep-v3')
    expect(board.locator('[data-next-position="P"]')).to_have_attribute('data-next-player', MATEO)
    expect(board.locator('[data-next-notice]')).to_have_text('Next inning defense updated.')
    assert page.cb_errors == []
