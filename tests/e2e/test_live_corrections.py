"""Correcting the defense during a game, and reading the live screen.

* End Inning's "Fix 1st Defense" opens the picker for the empty spot on the
  field; "Finish 2nd Inning Defense" is the prominent choice and opens the
  picker for the open spot in the next inning. With more than one spot
  open, the picker names the one it fills and lists the others, which stay
  marked Open.
* A spot empty right now is a red line ("Empty now (1st inning): SS"),
  separate from the amber next-inning line; each opens its picker.
* Undo is labelled and 44px tall, and says what it took back.
* The live header keeps the inning, clock and pitcher apart at 320px, with
  44px controls and no sideways scrolling.
"""

import re

import pytest

from playwright.sync_api import Page, expect

from test_next_inning_save_queue import (  # noqa: F401 (next_board is a fixture)
    CARD,
    live_state,
    next_board,
    open_on_the_field,
    other_coach_sets,
    server_next,
    spot,
    wait_for_server,
)
from test_next_inning_save_race import starting_alignment
from e2e_cleanup import wait_until_modal_shown, watch_modal_openings


pytestmark = pytest.mark.e2e

FIELD_PICKER = '#cbQuickMoveModal'
NEXT_PICKER = '#cbNextOpenPositionPicker'


def _filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def _reload_live(page, url, game_id):
    page.goto(f'{url}/game/{game_id}', wait_until='domcontentloaded')
    expect(page.locator('#cb-now-next-switch')).to_be_visible(timeout=15_000)
    page.wait_for_timeout(800)


def _wait_field(page, url, game_id, expected):
    for _ in range(50):
        if _filled(live_state(page, url, game_id)['current_alignment']) == expected:
            return
        page.wait_for_timeout(200)
    assert _filled(live_state(page, url, game_id)['current_alignment']) == expected


def test_fix_opens_the_field_picker_and_names_the_other_empty_spot(page: Page, coachboard_url, next_board):
    _, game_id = next_board
    open_on_the_field(page, coachboard_url, game_id, 'SS', 'LF')
    _reload_live(page, coachboard_url, game_id)

    page.locator('#liveEndInningBtn').click()
    recorded = page.locator('#cbRecordedInningGapModal')
    expect(recorded.locator('.modal-title')).to_have_text(
        'Shortstop and left field are empty at the end of the 1st', timeout=10_000)
    expect(recorded.get_by_role('button', name='Fix 1st Defense')).to_have_class(re.compile(r'\bbtn-primary\b'))
    expect(recorded.get_by_role('button', name='Continue to 2nd')).to_have_class(re.compile(r'\bbtn-outline-primary\b'))
    recorded.get_by_role('button', name='Fix 1st Defense').click()

    picker = page.locator(FIELD_PICKER)
    expect(picker.locator('.modal-title')).to_have_text('Fill SS', timeout=10_000)
    expect(picker.locator('[data-cb-move-hint]')).to_contain_text('Also open: LF.')
    # LF stays visibly open behind the picker.
    expect(page.locator('#cbQuickDefense [data-cb-position="LF"]')).to_contain_text('Open')

    picker.locator('button').filter(has_text='Shortstop Shawn').first.click()
    expected = {p: n for p, n in starting_alignment().items() if p != 'LF'}
    _wait_field(page, coachboard_url, game_id, expected)
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'


def test_finish_is_prominent_and_opens_the_next_inning_picker(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    planned = {p: n for p, n in starting_alignment().items() if p not in ('CF', 'RF')}
    other_coach_sets(page, coachboard_url, game_id, planned)
    expect(spot(board, 'RF')).to_have_attribute('data-next-player', '', timeout=10_000)

    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    page.locator('#liveEndInningBtn').click()
    incomplete = page.locator('#cbIncompleteNextModal')
    expect(incomplete.locator('.modal-title')).to_have_text('2nd inning defense has open positions', timeout=10_000)
    finish = incomplete.get_by_role('button', name='Finish 2nd Inning Defense')
    start = incomplete.get_by_role('button', name='Start 2nd with CF and RF Open')
    expect(finish).to_have_class(re.compile(r'\bbtn-primary\b'))
    expect(start).to_have_class(re.compile(r'\bbtn-outline-primary\b'))
    expect(start).to_be_enabled()
    finish.click()

    picker = page.locator(NEXT_PICKER)
    expect(picker.locator('[data-open-position-title]')).to_have_text('Who plays CF in the 2nd?', timeout=10_000)
    expect(picker.locator('[data-open-position-help]')).to_contain_text('Also open: RF.')
    expect(board).to_be_visible()
    expect(spot(board, 'RF')).to_contain_text('OPEN')
    picker.locator('button').filter(has_text='Center Casey').first.click()
    wait_for_server(page, coachboard_url, game_id, dict(planned, CF='Center Casey'))
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'


def test_empty_now_and_next_inning_are_separate_lines(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    open_on_the_field(page, coachboard_url, game_id, 'SS')
    other_coach_sets(page, coachboard_url, game_id,
                     {p: n for p, n in starting_alignment().items() if p != 'RF'})
    _reload_live(page, coachboard_url, game_id)

    now_line = page.locator('#cbNowOpenWarning')
    next_line = page.locator('#cbNextOpenWarning')
    expect(now_line).to_have_text('⚠ Empty now (1st inning): SS · Tap to fix', timeout=10_000)
    expect(next_line).to_have_text('⚠ Next inning: RF is open')
    assert now_line.bounding_box()['y'] < next_line.bounding_box()['y']

    watch_modal_openings(page)
    now_line.click()
    expect(page.locator(FIELD_PICKER).locator('.modal-title')).to_have_text('Fill SS', timeout=10_000)
    wait_until_modal_shown(page, 'cbQuickMoveModal')    # Escape is ignored mid-opening
    page.keyboard.press('Escape')
    expect(page.locator(FIELD_PICKER)).to_be_hidden(timeout=10_000)

    next_line.click()
    expect(page.locator(NEXT_PICKER).locator('[data-open-position-title]')).to_have_text(
        'Who plays RF in the 2nd?', timeout=10_000)


def _toast(page):
    return page.locator('#live-toast-container-v2 .toast-body').last


def test_undo_is_labelled_and_says_what_it_took_back(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    undo = page.locator('#liveUndoBtn')
    expect(undo).to_have_attribute('aria-label', 'Undo live change')
    expect(undo).to_contain_text('live change')
    box = undo.bounding_box()
    assert box['height'] >= 44 and box['width'] >= 44, box

    open_on_the_field(page, coachboard_url, game_id, 'SS')
    page.wait_for_timeout(1500)
    undo.click()
    expect(_toast(page)).to_have_text('✓ Undid the last change: Shortstop Shawn back at SS. Saved.', timeout=10_000)
    _wait_field(page, coachboard_url, game_id, starting_alignment())
    expect(page.locator('#cbNowOpenWarning')).to_have_count(0, timeout=5_000)

    # Undoing an inning change names it.
    page.locator('#liveEndInningBtn').click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    page.wait_for_timeout(800)
    undo.click()
    expect(_toast(page)).to_have_text('✓ Undid starting the 2nd. Back in the 1st. Saved.', timeout=10_000)
    expect(page.locator('#live-inning-display')).to_have_text('1', timeout=10_000)


def test_next_inning_undo_says_what_came_back(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    spot(board, 'RF').click()
    board.get_by_role('button', name=re.compile(r'^Bench #\d+ Right Riley$')).click()
    expect(spot(board, 'RF')).to_have_attribute('data-next-player', '', timeout=2_000)
    page.wait_for_timeout(800)
    page.locator('#liveUndoBtn').click()
    expect(board.locator('[data-next-undo-note]')).to_have_text(
        'Undid your last change to the 2nd: Right Riley back at RF.', timeout=5_000)
    wait_for_server(page, coachboard_url, game_id, starting_alignment())


@pytest.mark.parametrize('size', [(320, 640), (360, 740), (375, 667), (390, 844), (440, 956),
                                  (768, 1024), (1024, 768)],
                         ids=lambda s: f'{s[0]}x{s[1]}')
def test_the_live_header_is_readable_and_reachable(page: Page, coachboard_url, next_board, size):
    page.set_viewport_size({'width': size[0], 'height': size[1]})
    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    page.wait_for_timeout(500)
    data = page.evaluate("""() => {
      const header = document.getElementById('cbDugoutHeader');
      const box = sel => { const el = header.querySelector(sel); const r = el.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom}; };
      const parts = ['.cb-dh-inning', '.cb-dh-clock', '.cb-dh-pitcher', '#liveUndoBtn', '[data-cb-clock]', '[data-cb-menu]'].map(box);
      let overlaps = 0;
      for (let i = 0; i < parts.length; i++) for (let j = i + 1; j < parts.length; j++) {
        const a = parts[i], b = parts[j];
        if (a.l < b.r - 1 && b.l < a.r - 1 && a.t < b.b - 1 && b.t < a.b - 1) overlaps++;
      }
      const buttons = [...header.querySelectorAll('button')].map(b => b.getBoundingClientRect().height);
      const name = header.querySelector('[data-cb-pitcher]');
      const unlabeled = [...document.querySelectorAll('button')].filter(b =>
        b.offsetParent && !b.innerText.trim() && !b.getAttribute('aria-label') && !b.getAttribute('title')).length;
      return {
        overlaps, minButton: Math.min(...buttons),
        nameFont: parseFloat(getComputedStyle(name).fontSize),
        nameClipped: name.scrollWidth > name.clientWidth + 1,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        unlabeled,
      };
    }""")
    assert data['overlaps'] == 0, data
    assert data['minButton'] >= 44, data
    assert data['nameFont'] >= 12 and not data['nameClipped'], data
    assert data['overflow'] <= 0, data
    assert data['unlabeled'] == 0, data
    # The header stays at the top while the page scrolls.
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(300)
    assert round(page.locator('#cbDugoutHeader').bounding_box()['y']) == 0


def test_the_previous_inning_button_reads_as_an_action(page: Page, coachboard_url, next_board):
    board, _ = next_board
    button = board.get_by_role('button', name='Use 1st Inning Defense')
    expect(button).to_be_visible()
    color = button.evaluate('el => getComputedStyle(el).color')
    assert color == 'rgb(52, 64, 84)', color
    assert button.bounding_box()['height'] >= 44
