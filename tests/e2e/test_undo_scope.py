"""Which Undo is which, and Undo next-inning edit after a reload.

The header's Undo is one button with two jobs. On the 2nd Inning tab it
undoes the coach's last change to the next inning's defense (the board takes
the tap); everywhere else it is the live game's Undo. It now says which:
"Undo live change" / "Undo next-inning edit".

The next-inning Undo restores the server's one previous saved defense --
with its source and whether a coach chose it -- so it survives a reload,
and it is refused when another device saved a newer defense first.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_reference import (  # noqa: E402,F401 (live is a fixture)
    INNING_1, PHONE, _api, _set_next, live,
)


UNDO = '#liveUndoBtn'
NOTE = '#liveEndInningBtn .coach-action-note'
BOARD = '#live-board-prep-v3'
PLAN = {'1': INNING_1, '2': INNING_1}
SWAP = {**INNING_1, 'LF': INNING_1['RF'], 'RF': INNING_1['LF']}


def _open(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)


def _next_tab(page):
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator(BOARD)
    expect(board).to_be_visible()
    return board


def _prep(page, coachboard_url):
    return page.cb_api.request.get(_api(page, coachboard_url, 'next-inning-prep')).json()['confirmed']


def _filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def _bench_right_field(page, coachboard_url, board):
    board.locator('[data-next-position="RF"]').click()
    board.locator('[data-next-bench-selected]').click()
    expect(board.locator('[data-next-position="RF"]')).to_have_attribute('data-next-player', '', timeout=3_000)
    for _ in range(40):                                 # saved on the server
        if 'RF' not in _filled(_prep(page, coachboard_url)['alignment']):
            break
        page.wait_for_timeout(250)
    expect(board.locator('[data-next-save-state]')).to_have_class(re.compile(r'\bsaved\b'), timeout=10_000)


def test_the_header_names_which_undo_it_is(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _open(page, coachboard_url)
    undo = page.locator(UNDO)
    expect(undo).to_have_attribute('aria-label', 'Undo live change')
    expect(undo).to_have_attribute('title', 'Undo the last live-game change')
    expect(undo).to_contain_text('live change')
    expect(undo).to_be_enabled()

    _next_tab(page)
    expect(undo).to_have_attribute('aria-label', 'Undo next-inning edit')
    expect(undo).to_contain_text('next inning')
    expect(undo).to_be_disabled()                       # nothing changed yet

    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    expect(undo).to_have_attribute('aria-label', 'Undo live change')
    assert page.cb_errors == []


@pytest.mark.parametrize('width', [320, 360, 390])
def test_both_labels_fit_the_header(live, coachboard_url, width):
    page = live(('phone', {'width': width, 'height': 700}, {'is_mobile': True, 'has_touch': True}), plan=PLAN)
    _open(page, coachboard_url)
    fits = """() => {
      const header = document.getElementById('cbDugoutHeader');
      // LIVE · SYNCED as drawn (its box spans the whole grid column).
      const live = document.createRange();
      live.selectNodeContents(header.querySelector('.cb-dh-live'));
      const rects = [live.getBoundingClientRect(), ...['#liveUndoBtn', '[data-cb-clock]', '[data-cb-menu]']
        .map(sel => header.querySelector(sel).getBoundingClientRect())];
      let overlaps = 0;
      for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i], b = rects[j];
        if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps++;
      }
      const undo = document.getElementById('liveUndoBtn');
      return {overlaps, clipped: undo.scrollWidth > undo.clientWidth + 1,
              overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth};
    }"""
    assert page.evaluate(fits) == {'overlaps': 0, 'clipped': False, 'overflow': 0}
    _next_tab(page)
    expect(page.locator(UNDO)).to_have_attribute('aria-label', 'Undo next-inning edit')
    assert page.evaluate(fits) == {'overlaps': 0, 'clipped': False, 'overflow': 0}


def test_a_next_inning_edit_can_be_undone_after_a_reload(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _open(page, coachboard_url)
    board = _next_tab(page)
    _bench_right_field(page, coachboard_url, board)
    assert _prep(page, coachboard_url)['updated_by'] != 'Auto'

    _open(page, coachboard_url)                         # reload
    board = _next_tab(page)
    undo = page.locator(UNDO)
    expect(undo).to_be_enabled(timeout=10_000)
    undo.click()

    expect(board.locator('[data-next-undo-note]')).to_have_text(
        f"Undid your last change to the 2nd: {INNING_1['RF']} back at RF.", timeout=10_000)
    expect(board.locator('[data-next-save-state]')).to_have_text('Restored ✓', timeout=10_000)
    prep = _prep(page, coachboard_url)
    assert _filled(prep['alignment']) == INNING_1
    # Back to the plan nobody had chosen, as before the edit.
    assert prep['updated_by'] == 'Auto' and prep['source'] == 'planned'
    assert prep['previous'] is None
    expect(page.locator(NOTE)).to_have_text('Plan for the 2nd')
    expect(undo).to_be_disabled()                       # one step
    # The live game itself was not touched.
    state = page.cb_api.request.get(_api(page, coachboard_url, 'state')).json()
    assert state['current_inning'] == '1'
    assert _filled(state['current_alignment']) == INNING_1
    assert page.cb_errors == []


def test_undo_never_overwrites_a_newer_edit_from_another_device(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _open(page, coachboard_url)
    board = _next_tab(page)
    _bench_right_field(page, coachboard_url, board)

    # This phone hears nothing more; another device saves a newer defense.
    held = []
    page.route('**/next-inning-prep', lambda route: held.append(route)
               if route.request.method == 'GET' else route.continue_())
    _set_next(page, coachboard_url, SWAP)

    with page.expect_response(lambda r: '/next-inning-prep' in r.url and r.request.method == 'POST') as answer:
        page.locator(UNDO).click()
    assert answer.value.status == 409
    for route in held:
        route.continue_()
    page.unroute('**/next-inning-prep')

    expect(board.locator('[data-next-save-state]')).to_have_text('Not saved', timeout=10_000)
    expect(board.locator('[data-next-notice]')).to_contain_text('changed on another device')
    expect(board.locator('[data-next-position="RF"]')).to_have_attribute('data-next-player', SWAP['RF'])
    assert _filled(_prep(page, coachboard_url)['alignment']) == SWAP      # theirs stands
    expect(page.locator(UNDO)).to_be_disabled()
    assert page.cb_errors == []


def test_undo_on_the_field_is_still_the_live_undo(live, coachboard_url):
    page = live(PHONE, plan=PLAN)
    _open(page, coachboard_url)
    board = _next_tab(page)
    _bench_right_field(page, coachboard_url, board)
    page.locator('#cb-now-next-switch [data-now-next="now"]').click()

    # End the 1st, then undo it from On the Field: the live Undo.
    page.locator('#liveEndInningBtn').click()
    incomplete = page.locator('#cbIncompleteNextModal')
    expect(incomplete).to_be_visible(timeout=10_000)
    incomplete.get_by_role('button', name=re.compile(r'^Start 2nd with RF Open$')).click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    page.wait_for_timeout(800)
    page.locator(UNDO).click()
    expect(page.locator('#live-inning-display')).to_have_text('1', timeout=10_000)
    assert page.cb_errors == []
