"""After Undo of a pitching change, End Inning's line and the next inning
follow the restored game at once -- and End Inning starts what is shown.

Undo of a pitching change arrives as a full live state with the same
inning; the Next Inning board only re-read on a new inning or a live delta,
so until its next poll (up to 3.5 s) End Inning still said "Owen Park keeps
pitching" and the board still held the undone pitcher. It now re-reads on
any newer live state, and End Inning waits for such a read before starting
the inning.
"""

import os
import time

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_reference import (  # noqa: E402,F401 (live is a fixture)
    INNING_1, PHONE, _api, _sequence, _state, live,
)


NOTE = '#liveEndInningBtn .coach-action-note'
PITCHER = '#cbQuickDefense [data-cb-position="P"]'
LUKE, OWEN = INNING_1['P'], INNING_1['2B']

# What the Next Inning board shows when End Inning sends the advance.
RECORD_ADVANCE = """() => {
  const nativeFetch = window.fetch;
  window.fetch = function(input, init) {
    const url = String((input && input.url) || input);
    if (/advance-inning/.test(url) && String(init?.method).toUpperCase() === 'POST') {
      window.__advance = {shown: window.CBNextDefense.getAlignment(), sent: JSON.parse(init.body).alignment};
    }
    return nativeFetch.apply(this, arguments);
  };
}"""


def _filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def _owen_pitches(page, url):
    """Another coach's pitching change: Owen in from 2B, Luke to 2B."""
    state = _state(page, url)
    owen = next(p['id'] for p in state['roster'] if p['name'] == OWEN)
    alignment = dict(_filled(state['current_alignment']), P=OWEN, **{'2B': LUKE})
    response = page.cb_api.request.post(_api(page, url, 'complete-pitcher-change'), data={
        'base_sequence': _sequence(state), 'new_pitcher_id': owen, 'alignment': alignment, 'fast': True})
    assert response.ok, response.text()[:300]


def _open_with_owen_pitching(page, url):
    page.goto(f'{url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(1_000)
    _owen_pitches(page, url)
    expect(page.locator(NOTE)).to_contain_text(f'{OWEN} keeps pitching', timeout=8_000)


def test_the_line_drops_the_undone_pitcher_promptly(live, coachboard_url):
    page = live(PHONE)
    _open_with_owen_pitching(page, coachboard_url)
    page.locator('#liveUndoBtn').click()
    expect(page.locator(PITCHER)).to_contain_text(LUKE, timeout=5_000)
    restored = time.monotonic()
    # Was up to 3.5 s (the next poll).
    expect(page.locator(NOTE)).not_to_contain_text('keeps pitching', timeout=1_000)
    assert time.monotonic() - restored < 1.0
    expect(page.locator('#live-board-prep-v3 [data-next-position="P"]')).not_to_have_attribute(
        'data-next-player', OWEN)
    assert page.cb_errors == []


def test_end_inning_right_after_undo_starts_the_defense_shown(live, coachboard_url):
    page = live(PHONE)
    _open_with_owen_pitching(page, coachboard_url)
    page.evaluate(RECORD_ADVANCE)
    page.locator('#liveUndoBtn').click()
    expect(page.locator(PITCHER)).to_contain_text(LUKE, timeout=5_000)
    page.locator('#liveEndInningBtn').click()                    # without waiting for the line
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=10_000)

    advance = page.evaluate('() => window.__advance')
    started = _filled(_state(page, coachboard_url)['current_alignment'])
    assert _filled(advance['shown']) == _filled(advance['sent']) == started
    assert started.get('P') != OWEN                               # the undone change is not carried
    assert page.cb_errors == []
