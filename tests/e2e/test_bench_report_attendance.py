"""Bench Report: sits from the recorded game, and who is here.

* A player sat an inning only when they were here for it and not in the
  defense the game recorded for it. An inning with no record is named as
  unknown; the plan is never read as what happened.
* "Sitting now" (here, off the field) is separate from "Not here".
* "Left this inning" / "Here now" record a live departure or arrival from
  the inning being played. Live Undo takes it back; earlier innings and
  first-pitch attendance stay as they were.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_reference import (  # noqa: E402,F401 (live is a fixture)
    INNING_1, PHONE, _advance, _api, _field_edit, _state, live,
)


RF = INNING_1['RF']
LF = INNING_1['LF']
REPORT = '#cbBenchReportModal'


def _open_game(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)


def _open_report(page):
    page.locator('[data-cb-bench-report]').click()
    report = page.locator(REPORT)
    expect(report.locator('[data-cb-br-sitting]')).to_be_visible(timeout=10_000)
    return report


def _sitting(page, coachboard_url):
    """Here and off the field now (the shared test roster has other players)."""
    state = _state(page, coachboard_url)
    on_field = {name for name in state['current_alignment'].values() if name}
    return len([p for p in state['roster'] if p['name'] not in on_field])


def _row(report, name):
    return report.locator(f'[data-cb-br-player="{name}"]')


def test_sitting_now_leaving_arriving_and_undo(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1})
    _field_edit(page, coachboard_url, RF='')                 # RF sits; the spot is open
    _open_game(page, coachboard_url)
    report = _open_report(page)
    sitting = _sitting(page, coachboard_url)
    assert sitting >= 1

    expect(report.locator('[data-cb-br-sitting]')).to_have_text(f'Sitting now: {sitting}')
    expect(_row(report, RF).locator('.cb-br-history')).to_contain_text('Inning 1 now')
    expect(report.locator('[data-cb-br-not-here]')).to_have_count(0)
    expect(_row(report, LF).locator('[data-cb-br-left]')).to_have_count(0)   # on the field

    # RF goes home in the 1st.
    _row(report, RF).locator('[data-cb-br-left]').click()
    away = report.locator('[data-cb-br-not-here]')
    expect(away.locator(f'[data-cb-br-player="{RF}"]')).to_be_visible(timeout=10_000)
    expect(report.locator('[data-cb-br-sitting]')).to_have_text(f'Sitting now: {sitting - 1}')
    expect(report.locator('[data-cb-br-away-count]')).to_have_text('Not here: 1')
    state = _state(page, coachboard_url)
    assert [p['name'] for p in state['not_here']] == [RF]
    assert state['rotation_events'][-1]['event_type'] == 'Player Left'
    assert state['rotation_events'][-1]['effective_inning'] == 1

    # And comes back.
    away.locator('[data-cb-br-arrived]').click()
    expect(report.locator('[data-cb-br-not-here]')).to_have_count(0, timeout=10_000)
    expect(report.locator('[data-cb-br-sitting]')).to_have_text(f'Sitting now: {sitting}')

    # Undo takes back the arrival: gone again.
    report.locator('.btn-close, [data-bs-dismiss="modal"]').first.click()
    expect(report).to_be_hidden()
    page.locator('#liveUndoBtn').click()
    for _ in range(40):
        if [p['name'] for p in _state(page, coachboard_url)['not_here']] == [RF]:
            break
        page.wait_for_timeout(250)
    assert [p['name'] for p in _state(page, coachboard_url)['not_here']] == [RF]
    report = _open_report(page)
    expect(report.locator('[data-cb-br-away-count]')).to_have_text('Not here: 1')
    assert page.cb_errors == []


def test_a_player_on_the_field_cannot_leave_from_the_report(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1})
    _field_edit(page, coachboard_url, RF='')
    _open_game(page, coachboard_url)
    report = _open_report(page)
    # The server refuses a departure for someone on the field (a stale report).
    page.evaluate(f"""() => document.querySelector('#cbBenchReportModal [data-cb-br-left]').dataset.cbBrLeft =
        String({_player_id(page, coachboard_url, LF)})""")
    report.locator('[data-cb-br-left]').first.click()
    message = report.locator('[data-cb-br-message]')
    expect(message).to_have_text(f'{LF} is at LF. Take them off the field first.', timeout=10_000)
    assert _state(page, coachboard_url)['not_here'] == []
    assert page.cb_errors == []


def _player_id(page, coachboard_url, name):
    return next(p['id'] for p in _state(page, coachboard_url)['roster'] if p['name'] == name)


def test_sits_come_from_the_recorded_defense_and_who_was_here(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1})
    _field_edit(page, coachboard_url, RF='')                 # RF sits the 1st, here
    _advance(page, coachboard_url)                           # the 2nd: RF still open
    _open_game(page, coachboard_url)
    report = _open_report(page)
    expect(_row(report, RF).locator('.cb-br-history')).to_have_text('Sat: 1 · Inning 2 now')
    expect(_row(report, LF).locator('.cb-br-history')).to_have_text('Sat: None')
    expect(report.locator('[data-cb-br-unknown]')).to_have_count(0)
    assert page.cb_errors == []


def test_an_inning_with_no_record_is_unknown_not_read_from_the_plan(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1})
    _field_edit(page, coachboard_url, RF='')
    _advance(page, coachboard_url)

    def without_a_record(route):
        response = route.fetch()
        data = response.json()
        data['played_innings'] = {'1': {'alignment': None, 'recorded_by': None, 'available': []}}
        route.fulfill(response=response, json=data)

    page.route('**/next-inning-prep', lambda route: without_a_record(route)
               if route.request.method == 'GET' else route.continue_())
    _open_game(page, coachboard_url)
    report = _open_report(page)
    expect(report.locator('[data-cb-br-unknown]')).to_contain_text('No recorded defense: 1st')
    expect(_row(report, RF).locator('.cb-br-history')).to_have_text('Sat: None · Inning 2 now')
    assert page.cb_errors == []
