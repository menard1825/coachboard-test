"""Bench Report and Player availability: who sat, and who is here.

* A player sat an inning only when they were here for it and not in the
  defense the game recorded for it. An inning with no record is named as
  unknown; the plan is never read as what happened.
* The Bench Report is for reading: who is sitting now, innings already sat,
  projected sits, and who is not here -- with no attendance buttons.
* Attendance changes live in one place, Menu -> Player availability: "Mark
  unavailable" (after "Mark Jack unavailable for the rest of the game?") and
  "Mark available". They record a live departure or arrival from the inning
  being played; live Undo takes it back; earlier innings and first-pitch
  attendance stay as they were. A player on the field or in the next
  inning's defense has to be moved off it first.
"""

import os

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
    edit_live_defense as _field_edit,
    set_next_inning as _set_next,
    game_state as _state,
    live,
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


SHEET = '#cbPlayerAvailabilityModal'
PHONE_IPAD = [PHONE, ('ipad', {'width': 768, 'height': 1024}, {'is_mobile': True, 'has_touch': True}),
              ('ipad-landscape', {'width': 1024, 'height': 768}, {'is_mobile': True, 'has_touch': True})]


def _open_availability(page):
    page.locator('#cbDugoutHeader [data-cb-menu]').click()
    menu = page.locator('#cbCoachBoardNavModal')
    expect(menu).to_be_visible(timeout=10_000)
    menu.get_by_role('button', name='Player availability').click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('[data-cb-pa-here]')).to_be_visible(timeout=10_000)
    expect(menu).to_be_hidden()
    return sheet


def _not_here(page, coachboard_url):
    return [p['name'] for p in _state(page, coachboard_url)['not_here']]


def _player_id(page, coachboard_url, name):
    return next(p['id'] for p in _state(page, coachboard_url)['roster'] if p['name'] == name)


def _mark_left(page, coachboard_url, name):
    state = _state(page, coachboard_url)
    response = page.cb_api.request.post(_api(page, coachboard_url, 'availability'), data={
        'action': 'left', 'player_id': _player_id(page, coachboard_url, name),
        'base_sequence': max([int(e['sequence']) for e in state['rotation_events'] if not e['reverted']] or [0])})
    assert response.ok, response.text()[:200]


def test_the_bench_report_shows_attendance_without_buttons(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1})
    _field_edit(page, coachboard_url, RF='')                 # RF sits; the spot is open
    _mark_left(page, coachboard_url, RF)
    _open_game(page, coachboard_url)
    report = _open_report(page)

    away = report.locator('[data-cb-br-not-here]')
    expect(away.locator(f'[data-cb-br-player="{RF}"]')).to_be_visible()
    expect(report.locator('[data-cb-br-away-count]')).to_have_text('Not here: 1')
    expect(report.locator('[data-cb-br-sitting]')).to_have_text(f'Sitting now: {_sitting(page, coachboard_url)}')
    expect(away).to_contain_text('Menu → Player availability')
    # Reading only: no attendance (or any other) buttons on the player cards.
    expect(report.locator('.cb-br-row button')).to_have_count(0)
    expect(report.get_by_role('button', name='Left this inning')).to_have_count(0)
    expect(report.get_by_role('button', name='Here now')).to_have_count(0)
    assert page.cb_errors == []


def test_mark_unavailable_asks_first_then_available_and_undo(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1})
    _field_edit(page, coachboard_url, RF='')
    _open_game(page, coachboard_url)
    sheet = _open_availability(page)
    expect(sheet.locator('.cb-pa-intro')).to_contain_text('Changes take effect this inning (the 1st)')

    # On the field: can't be marked unavailable from here.
    left_field = sheet.locator(f'[data-cb-pa-player="{LF}"]')
    expect(left_field.locator('.cb-pa-where')).to_have_text('On the field at LF · move them off first')
    expect(left_field.get_by_role('button', name='Mark unavailable')).to_be_disabled()

    right = sheet.locator(f'[data-cb-pa-player="{RF}"]')
    expect(right.locator('.cb-pa-where')).to_have_text('Sitting now')
    right.get_by_role('button', name='Mark unavailable').click()
    question = sheet.locator('[data-cb-pa-question]')
    expect(question.locator('h6')).to_have_text(f'Mark {RF} unavailable for the rest of the game?')
    expect(question).to_contain_text('This takes effect now, in the 1st inning.')
    question.get_by_role('button', name='Cancel').click()            # nothing recorded
    expect(sheet.locator('[data-cb-pa-here]')).to_be_visible()
    assert _not_here(page, coachboard_url) == []

    right.get_by_role('button', name='Mark unavailable').click()
    sheet.locator('[data-cb-pa-question]').get_by_role('button', name='Mark unavailable').click()
    away = sheet.locator('[data-cb-pa-away]')
    expect(away.locator(f'[data-cb-pa-player="{RF}"]')).to_be_visible(timeout=10_000)
    expect(away.locator('.cb-pa-title')).to_have_text('Unavailable · 1')
    state = _state(page, coachboard_url)
    assert [p['name'] for p in state['not_here']] == [RF]
    event = state['rotation_events'][-1]
    assert (event['event_type'], event['effective_inning']) == ('Player Left', 1)

    # Back again, no question.
    away.get_by_role('button', name='Mark available').click()
    expect(sheet.locator('[data-cb-pa-away]')).to_have_count(0, timeout=10_000)
    assert _not_here(page, coachboard_url) == []

    # Done returns to the Menu button; live Undo takes back the last change.
    sheet.get_by_role('button', name='Done').click()
    expect(sheet).to_be_hidden()
    page.wait_for_function("document.activeElement?.matches('#cbDugoutHeader [data-cb-menu]')", timeout=5_000)
    page.locator('#liveUndoBtn').click()
    for _ in range(40):
        if _not_here(page, coachboard_url) == [RF]:
            break
        page.wait_for_timeout(250)
    assert _not_here(page, coachboard_url) == [RF]
    report = _open_report(page)
    expect(report.locator('[data-cb-br-away-count]')).to_have_text('Not here: 1')
    assert page.cb_errors == []


def test_the_next_defense_and_the_server_still_guard_it(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1})
    _field_edit(page, coachboard_url, RF='')
    _set_next(page, coachboard_url, INNING_1)                 # RF is back at RF in the 2nd
    _open_game(page, coachboard_url)
    sheet = _open_availability(page)
    right = sheet.locator(f'[data-cb-pa-player="{RF}"]')
    expect(right.locator('.cb-pa-where')).to_have_text('At RF in the 2nd inning · take them out of it first')
    expect(right.get_by_role('button', name='Mark unavailable')).to_be_disabled()

    # A stale screen: the server still refuses, and says why.
    page.evaluate(f"""() => {{
      const b = document.querySelector('#cbPlayerAvailabilityModal [data-cb-pa-player="{LF}"] [data-cb-pa-unavailable]');
      b.disabled = false;
    }}""")
    sheet.locator(f'[data-cb-pa-player="{LF}"]').get_by_role('button', name='Mark unavailable').click()
    sheet.locator('[data-cb-pa-question]').get_by_role('button', name='Mark unavailable').click()
    expect(sheet.locator('[data-cb-pa-message]')).to_have_text(
        f'{LF} is at LF. Take them off the field first.', timeout=10_000)
    assert _not_here(page, coachboard_url) == []
    assert page.cb_errors == []


@pytest.mark.parametrize('device', PHONE_IPAD, ids=lambda d: d[0])
def test_availability_sheet_layout(live, coachboard_url, device):
    page = live(device, plan={'1': INNING_1})
    _field_edit(page, coachboard_url, RF='')
    _mark_left(page, coachboard_url, RF)
    _open_game(page, coachboard_url)
    sheet = _open_availability(page)
    layout = page.evaluate("""() => {
      const modal = document.getElementById('cbPlayerAvailabilityModal');
      const rows = [...modal.querySelectorAll('.cb-pa-row')];
      let overlaps = 0, small = 0;
      rows.forEach(row => {
        const button = row.querySelector('button').getBoundingClientRect();
        if (button.height < 40) small++;
        row.querySelectorAll('.cb-pa-name, .cb-pa-where').forEach(text => {
          const t = text.getBoundingClientRect();
          if (t.right > button.left + 1 && t.bottom > button.top + 1 && t.top < button.bottom - 1) overlaps++;
        });
      });
      const dialog = modal.querySelector('.modal-content').getBoundingClientRect();
      return {rows: rows.length, overlaps, small,
              inside: dialog.left >= 0 && dialog.right <= window.innerWidth,
              overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth};
    }""")
    assert layout['rows'] >= 9 and layout['overlaps'] == 0 and layout['small'] == 0, layout
    assert layout['inside'] and layout['overflow'] == 0, layout
    assert page.cb_errors == []


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
