"""Focus around the live game's dialogs (live_game_modal_focus.js).

Bootstrap 5.3 hides a dialog by setting aria-hidden="true" without moving
focus out first, and returns focus only for data-bs-toggle triggers. Every
live dialog is opened from script, so before this:

* the dialog went aria-hidden with the tapped button (or, after Escape, the
  dialog itself) still focused -- the browser's "Blocked aria-hidden" case;
* focus then fell back to the page, not the control that opened it.

Each test watches for aria-hidden being set on an element that contains the
focused element, and checks where focus lands and that the next tap works.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from live_fixtures import PHONE, live  # noqa: E402,F401


WATCH = """
  window.__cbHiddenOverFocus = [];
  new MutationObserver(records => records.forEach(record => {
    const element = record.target, active = document.activeElement;
    if (element.getAttribute('aria-hidden') === 'true' && active && active !== document.body && element.contains(active)) {
      window.__cbHiddenOverFocus.push(element.id || element.className);
    }
  })).observe(document, {attributes: true, subtree: true, attributeFilter: ['aria-hidden']});
"""

FOCUSED = """() => {
  const a = document.activeElement;
  if (!a || a === document.body) return 'BODY';
  return a.id || a.dataset.cbPosition || a.dataset.nextPosition || a.tagName;
}"""


def _open_game(page, coachboard_url):
    page.add_init_script(WATCH)
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.evaluate("""() => {
      window.__cbShown = [];
      document.addEventListener('shown.bs.modal', e => window.__cbShown.push(e.target.id));
      window.__cbHidden = [];
      document.addEventListener('hidden.bs.modal', e => window.__cbHidden.push(e.target.id));
    }""")


def _opened(page, modal_id):
    """Wait for Bootstrap to finish opening (Escape is ignored mid-opening)."""
    page.wait_for_function('id => window.__cbShown.includes(id)', arg=modal_id, timeout=10_000)
    page.evaluate('id => { window.__cbShown = window.__cbShown.filter(x => x !== id); }', modal_id)


def _closed(page, modal_id):
    page.wait_for_function('id => window.__cbHidden.includes(id)', arg=modal_id, timeout=10_000)
    page.evaluate('id => { window.__cbHidden = window.__cbHidden.filter(x => x !== id); }', modal_id)


def _focused(page):
    return page.evaluate(FOCUSED)


def _clean(page):
    assert page.evaluate('window.__cbHiddenOverFocus') == []


def test_field_picker_cancel_escape_and_reopening(live, coachboard_url):
    page = live(PHONE)
    _open_game(page, coachboard_url)
    left = page.locator('#cbQuickDefense [data-cb-position="LF"]')
    modal = page.locator('#cbQuickMoveModal')

    for close in ('cancel', 'escape', 'cancel'):                 # opened again and again
        left.click()
        _opened(page, 'cbQuickMoveModal')
        if close == 'cancel':
            modal.locator('[data-bs-dismiss="modal"]').first.click()
        else:
            page.keyboard.press('Escape')
        _closed(page, 'cbQuickMoveModal')
        _clean(page)
        assert _focused(page) == 'LF', close

    # The next interaction works: the keyboard opens it again from LF.
    page.keyboard.press('Enter')
    _opened(page, 'cbQuickMoveModal')
    expect(modal).to_be_visible()
    page.keyboard.press('Escape')
    _closed(page, 'cbQuickMoveModal')
    _clean(page)
    assert page.cb_errors == []


def test_change_pitcher_escape_and_one_dialog_leading_to_the_next(live, coachboard_url):
    page = live(PHONE)
    _open_game(page, coachboard_url)
    button = page.locator('#liveChangePitcherBtn')

    button.click()
    _opened(page, 'live-pitcher-picker-v2')
    page.keyboard.press('Escape')
    _closed(page, 'live-pitcher-picker-v2')
    _clean(page)
    assert _focused(page) == 'liveChangePitcherBtn'

    # Choosing a pitcher leads to the next dialog (where the pitcher goes);
    # cancelling that one returns to Change Pitcher.
    button.click()
    _opened(page, 'live-pitcher-picker-v2')
    page.locator('#live-pitcher-picker-v2 .modal-body button').first.click()
    _opened(page, 'live-pitcher-destination-v7')
    _clean(page)
    page.locator('#live-pitcher-destination-v7').get_by_role('button', name='Cancel').click()
    _closed(page, 'live-pitcher-destination-v7')
    _clean(page)
    assert _focused(page) == 'liveChangePitcherBtn'

    # And it opens again.
    page.keyboard.press('Enter')
    _opened(page, 'live-pitcher-picker-v2')
    page.keyboard.press('Escape')
    _closed(page, 'live-pitcher-picker-v2')
    _clean(page)
    assert page.cb_errors == []


def test_open_position_selection_returns_to_the_redrawn_spot(live, coachboard_url):
    page = live(PHONE)
    _open_game(page, coachboard_url)
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator('#live-board-prep-v3')
    right = board.locator('[data-next-position="RF"]')
    right.click()
    board.locator('[data-next-bench-selected]').click()
    expect(right).to_have_attribute('data-next-player', '', timeout=3_000)
    page.wait_for_timeout(600)

    right.click()
    _opened(page, 'cbNextOpenPositionPicker')
    before = right.element_handle()
    page.locator('#cbNextOpenPositionPicker [data-open-position-choices] button').first.click()
    _closed(page, 'cbNextOpenPositionPicker')
    _clean(page)
    expect(right).not_to_have_attribute('data-next-player', '')
    # The board redrew RF after the choice; focus is on the spot now there.
    assert not before.evaluate('el => el.isConnected')
    assert _focused(page) == 'RF'

    # The next interaction works: the keyboard picks RF up for a move.
    page.keyboard.press('Enter')
    expect(right).to_have_class(re.compile(r'\bcb-next-selected\b'), timeout=3_000)
    assert page.cb_errors == []
