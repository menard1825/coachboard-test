"""Bench time: who has sat, and who sits next, while planning the next inning.

The Next Inning planner shows, beside the field, every player who is here:
innings recorded on the bench (and "now" if sitting this inning), where the
planned defense puts them next inning, and planned sits still ahead. Its
numbers are the Bench Report's own (CBBenchReport.build) with the defense as
planned on the board, so they move with each tap -- before the save lands --
and always agree with the full report, which stays one tap away.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from live_fixtures import (  # noqa: E402,F401 (live is a fixture)
    INNING_2,
    PHONE,
    advance_inning,
    api_url,
    game_state,
    live,
    set_next_inning,
)


PLANNER = '#live-board-prep-v3'
QUICK = f'{PLANNER} [data-next-bench-quick]'
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
IPAD_LANDSCAPE = ('ipad-landscape', {'width': 1024, 'height': 768}, {'is_mobile': True, 'has_touch': True})
IPAD_PORTRAIT = ('ipad-portrait', {'width': 768, 'height': 1024}, {'is_mobile': True, 'has_touch': True})

# After the 1st: the default lineup is on the field and these players (the
# shared test roster's others) sat the 1st and are sitting the 2nd.
SITTERS = ['Catcher Cole', 'Center Casey', 'Left Lee']
# A complete 3rd: the 2nd's defense with Catcher Cole in left field.
THIRD = {**INNING_2, 'LF': 'Catcher Cole'}
BENCHED_FOR_COLE = INNING_2['LF']


def _open_planner(page, url):
    page.goto(f'{url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(600)
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    expect(page.locator(PLANNER)).to_be_visible()
    expect(page.locator(QUICK)).to_be_visible(timeout=10_000)
    return page.locator(QUICK)


def _expand(quick):
    box = quick.locator('[data-next-bench-quick-box]')
    if box.get_attribute('open') is None:
        quick.locator('summary').click()
    expect(box).to_have_attribute('open', '')


def _row(quick, name):
    return quick.locator(f'[data-next-bench-quick-player="{name}"]')


def _cells(quick, name):
    row = _row(quick, name)
    return {
        'sat': int(row.locator('[data-nq-sat]').get_attribute('data-nq-sat')),
        'now': row.locator('[data-nq-sat]').get_attribute('data-nq-now') == '1',
        'next': row.locator('[data-nq-next]').get_attribute('data-nq-next'),
        'proj': int(row.locator('[data-nq-proj]').get_attribute('data-nq-proj')),
        'class': row.get_attribute('class'),
    }


def _report_counts(report, name):
    """Sat / projected counts as the full Bench Report shows them."""
    text = report.locator(f'[data-cb-br-player="{name}"]').inner_text()
    sat = re.search(r'Sat:\s*([^\n·]*)', text).group(1).strip()
    sat_count = 0 if sat == 'None' else len([x for x in sat.split(',') if x.strip()])
    proj = re.search(r'Projected to sit:\s*([^\n]*)', text)
    proj_count = len([x for x in proj.group(1).split(',') if x.strip()]) if proj else 0
    return sat_count, ' now' in text, proj_count


def test_bench_time_agrees_with_the_bench_report_and_moves_with_each_tap(live, coachboard_url):
    page = live(DESKTOP)
    advance_inning(page, coachboard_url)
    set_next_inning(page, coachboard_url, THIRD)
    quick = _open_planner(page, coachboard_url)
    expect(quick.locator('[data-next-bench-quick-box]')).to_have_attribute('open', '')

    # Who has sat, and where the planned 3rd puts them.
    cole, casey = _cells(quick, 'Catcher Cole'), _cells(quick, 'Center Casey')
    assert (cole['sat'], cole['now'], cole['next']) == (1, True, 'LF'), cole
    assert (casey['sat'], casey['now'], casey['next']) == (1, True, 'Bench'), casey
    assert casey['proj'] == 1 and cole['proj'] == 0, (casey, cole)
    # Sat the most and benched again: flagged. Cole plays next: not flagged.
    assert 'again' in casey['class'] and 'most' in casey['class'], casey
    assert 'again' not in cole['class'] and 'most' in cole['class'], cole
    expect(quick.locator('[data-next-bench-quick-glance]')).to_contain_text('Sat most (2)')
    expect(quick.locator('[data-next-bench-quick-glance]')).to_contain_text('again in the 3rd')
    benched = _cells(quick, BENCHED_FOR_COLE)
    assert (benched['sat'], benched['now'], benched['next'], benched['proj']) == (0, False, 'Bench', 1), benched

    # The same numbers as the full Bench Report, which opens from here.
    quick.locator('[data-next-bench-full]').click()
    report = page.locator('#cbBenchReportModal')
    expect(report.locator('[data-cb-br-sitting]')).to_be_visible(timeout=10_000)
    for name in [*SITTERS, BENCHED_FOR_COLE, INNING_2['CF']]:
        cells = _cells(quick, name)
        assert _report_counts(report, name) == (cells['sat'], cells['now'], cells['proj']), name
    report.get_by_role('button', name='Back to Game').click()
    expect(report).to_be_hidden()
    expect(page.locator(PLANNER)).to_be_visible()

    # A tap moves the numbers at once -- the save is held, so this is the
    # board's own plan, not a server round trip.
    held = []
    page.route('**/next-inning-prep', lambda route: held.append(route)
               if route.request.method == 'POST' else route.continue_())
    board = page.locator(PLANNER)
    center = INNING_2['CF']
    board.locator('[data-next-bench-player="Center Casey"]').click()
    board.locator('[data-next-position="CF"]').click()
    expect(_row(quick, 'Center Casey').locator('[data-nq-next]')).to_have_attribute('data-nq-next', 'CF', timeout=2_000)
    assert held, 'the save should still be in the air'
    casey, out = _cells(quick, 'Center Casey'), _cells(quick, center)
    assert (casey['next'], casey['proj']) == ('CF', 0) and 'again' not in casey['class'], casey
    assert (out['next'], out['proj']) == ('Bench', 1), out
    for route in held:
        route.continue_()
    page.unroute('**/next-inning-prep')
    expect(board.locator('[data-next-save-state]')).to_contain_text('✓', timeout=10_000)
    saved = page.cb_api.request.get(api_url(page, coachboard_url, 'next-inning-prep')).json()['confirmed']['alignment']
    assert saved['CF'] == 'Center Casey'
    assert _cells(quick, 'Center Casey')['next'] == 'CF'
    assert page.cb_errors == []


def test_unplanned_inning_unknown_history_and_players_not_here(live, coachboard_url):
    page = live(PHONE)
    advance_inning(page, coachboard_url)
    # Left Lee goes home.
    state = game_state(page, coachboard_url)
    lee = next(p['id'] for p in state['roster'] if p['name'] == 'Left Lee')
    sequence = max([int(e['sequence']) for e in state['rotation_events'] if not e['reverted']] or [0])
    response = page.cb_api.request.post(api_url(page, coachboard_url, 'availability'), data={
        'action': 'left', 'player_id': lee, 'base_sequence': sequence})
    assert response.ok, response.text()[:200]

    # The 1st inning's record is missing from what this board reads.
    def drop_first(route):
        if route.request.method != 'GET':
            return route.continue_()
        response = route.fetch()
        data = response.json()
        (data.get('played_innings') or {}).pop('1', None)
        route.fulfill(response=response, json=data)
    page.route('**/next-inning-prep', drop_first)

    quick = _open_planner(page, coachboard_url)
    # Phones: collapsed, with the one-line answer still showing.
    box = quick.locator('[data-next-bench-quick-box]')
    assert box.get_attribute('open') is None
    glance = quick.locator('[data-next-bench-quick-glance]')
    expect(glance).to_be_visible()
    # The default 3rd is only partly planned: nobody is said to sit "again".
    expect(glance).to_contain_text("the 3rd isn't fully planned")
    _expand(quick)
    expect(quick.locator('.cb-nq-row.again')).to_have_count(0)
    casey = _cells(quick, 'Center Casey')
    assert casey['next'] == '' and casey['proj'] == 0, casey

    # Unknown history: the 1st isn't counted, and says so.
    assert (casey['sat'], casey['now']) == (0, True), casey
    expect(quick.locator('[data-next-bench-quick-note]').first).to_contain_text('No recorded defense for the 1st')
    # Not here: listed apart, with no row of its own.
    expect(quick.locator('[data-next-bench-quick-away]')).to_contain_text('Left Lee')
    expect(_row(quick, 'Left Lee')).to_have_count(0)
    assert page.cb_errors == []


@pytest.mark.parametrize('device', [PHONE, IPAD_PORTRAIT, IPAD_LANDSCAPE, DESKTOP], ids=lambda d: d[0])
def test_bench_time_fits_beside_or_under_the_field(live, coachboard_url, device):
    page = live(device)
    advance_inning(page, coachboard_url)
    set_next_inning(page, coachboard_url, THIRD)
    quick = _open_planner(page, coachboard_url)
    box = quick.locator('[data-next-bench-quick-box]')
    wide = device[1]['width'] >= 700
    assert (box.get_attribute('open') is not None) == wide
    _expand(quick)

    field = page.locator(f'{PLANNER} .cb-next-field').bounding_box()
    panel = quick.bounding_box()
    width = device[1]['width']
    assert panel['x'] >= 0 and panel['x'] + panel['width'] <= width + 1, (panel, width)
    if device[1]['width'] > device[1]['height'] and wide:
        assert panel['x'] >= field['x'] + field['width'] - 1, (field, panel)       # beside the field
    else:
        assert panel['y'] >= field['y'] + field['height'] - 1, (field, panel)      # under it
    # Every row readable: name, Sat, Next, Proj on one line.
    rows = quick.locator('.cb-nq-row:not(.head)')
    assert rows.count() >= len(SITTERS)
    first = rows.first.bounding_box()
    assert first['height'] <= 48, first
    page.evaluate('() => document.activeElement?.blur()')
    assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth + 1')
    assert page.cb_errors == []
