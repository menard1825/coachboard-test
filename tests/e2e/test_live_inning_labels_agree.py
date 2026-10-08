"""The header, "Plan next inning" and End Inning show the same inning.

They used to come from different reads: the header from the live state, the
"Plan 2nd inning" button and End Inning ("End 1st → Start 2nd") from the Next Inning board's
own poll. After Undo End Inning the tab and button stayed on the old inning
for about 3 s; with the live connection down a remote End Inning put
"INNING 1" beside "End 2nd → Start 3rd" for up to 10 s.

Every /state the page reads (Undo, the polls, End Inning, a reconnect) now
updates one shared live state if it is newer, and the labels follow it.
End Inning refuses to end an inning other than the one its button showed.
"""

import os
import time

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from live_fixtures import (  # noqa: E402,F401 (live is a fixture)
    PHONE,
    api_url as _api,
    last_sequence as _sequence,
    game_state as _state,
    live,
)


LABELS = """() => ({
  header: document.querySelector('#cbDugoutHeader [data-cb-inning]')?.textContent?.trim(),
  display: document.querySelector('#live-inning-display')?.textContent?.trim(),
  tab: document.querySelector('#cb-now-next-switch [data-now-next="next"]')?.textContent?.trim(),
  end: document.querySelector('#liveEndInningBtn .coach-action-title')?.textContent?.trim(),
})"""

ORDINAL = {'1': '1st', '2': '2nd', '3': '3rd', '4': '4th'}


def _consistent(labels):
    inning = labels['header']
    nxt = str(int(inning) + 1)
    return (labels['display'] == inning and labels['tab'] == f'Plan {ORDINAL[nxt]} inning'
            and labels['end'] == f'End {ORDINAL[inning]} → Start {ORDINAL[nxt]}')


def _watch(page, seconds, until):
    """Labels every 50 ms: the time they first all show `until`, and any mix."""
    start, mixed = time.monotonic(), []
    while time.monotonic() - start < seconds:
        labels = page.evaluate(LABELS)
        if not _consistent(labels):
            mixed.append(labels)
        elif labels['header'] == until:
            return time.monotonic() - start, mixed
        page.wait_for_timeout(50)
    raise AssertionError(f'labels never reached inning {until}: {page.evaluate(LABELS)}')


def _open(page, url):
    page.goto(f'{url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_function('() => window.CBLiveState?.current?.()', timeout=10_000)
    page.wait_for_timeout(1_500)
    assert _consistent(page.evaluate(LABELS)), page.evaluate(LABELS)


def _remote_end_inning(page, url):
    prep = page.cb_api.request.get(_api(page, url, 'next-inning-prep')).json()
    response = page.cb_api.request.post(_api(page, url, 'advance-inning'), data={
        'alignment': prep['confirmed']['alignment'], 'next_prep_id': prep['confirmed']['id'],
        'base_sequence': _sequence(_state(page, url))})
    assert response.ok, response.text()[:300]


def test_labels_change_together_after_end_inning_and_undo(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    page.locator('#liveEndInningBtn').click()
    took, mixed = _watch(page, 5, '2')
    assert took < 1.5 and len(mixed) <= 2, (took, mixed)          # at most a frame or two apart

    page.locator('#liveUndoBtn').click()
    took, mixed = _watch(page, 5, '1')
    # Was about 3 s for the tab and End Inning.
    assert took < 1.0 and len(mixed) <= 2, (took, mixed)
    assert page.cb_errors == []


def test_labels_move_together_with_the_connection_down(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    page.evaluate('() => window.__cbLiveGameSocket.disconnect()')
    _remote_end_inning(page, coachboard_url)
    # Found by a poll (unchanged: the Next Inning read every 3.5 s, the game
    # every 5 s), then shown everywhere at once -- never "INNING 1" beside
    # "End 2nd".
    took, mixed = _watch(page, 8, '2')
    assert took < 6.5 and mixed == [], (took, mixed)
    assert page.cb_errors == []


def test_a_newer_inning_never_reaches_the_buttons_before_the_header(live, coachboard_url):
    """The same race the 50 ms watch above can only catch by luck: the page
    takes a newer live state (here the remote End Inning, read while the
    connection is down) and its labels are read in that very turn, and again
    once the next frame has drawn. Every reading agrees."""
    page = live(PHONE)
    _open(page, coachboard_url)
    page.evaluate('() => window.__cbLiveGameSocket.disconnect()')
    _remote_end_inning(page, coachboard_url)
    readings = page.evaluate("""async (labels) => {
      const read = eval(labels);
      const state = await (await fetch(location.pathname.replace(/^\\/game\\//, '/api/live-game/') + '/state')).json();
      const before = read();
      window.CBLiveState.adopt(state, 'test');
      const sameTurn = read();
      await new Promise(done => requestAnimationFrame(() => setTimeout(done, 0)));
      return {before, sameTurn, drawn: read()};
    }""", LABELS)
    assert _consistent(readings['before']) and readings['before']['header'] == '1', readings
    assert _consistent(readings['sameTurn']), readings
    assert _consistent(readings['drawn']) and readings['drawn']['header'] == '2', readings
    assert page.cb_errors == []


def test_the_header_catching_up_to_this_boards_read_moves_the_labels_with_it(live, coachboard_url):
    """The other order: this board's own read finds the 2nd first (its
    buttons wait on the header, "Checking the 2nd defense..."), then the
    live state catches up. The buttons used to be relabelled in that same
    turn, before the header drew -- "INNING 1" beside "End 2nd" for a
    frame, caught in CI by the 50 ms watch above."""
    page = live(PHONE)
    _open(page, coachboard_url)
    page.evaluate('() => window.__cbLiveGameSocket.disconnect()')
    held = '**/api/live-game/*/state'
    page.route(held, lambda route: route.abort())
    _remote_end_inning(page, coachboard_url)
    expect(page.locator('#liveEndInningBtn .coach-action-note')).to_contain_text(
        'Checking the 2nd defense', timeout=10_000)
    assert _consistent(page.evaluate(LABELS)) and page.evaluate(LABELS)['header'] == '1'
    page.unroute(held)
    readings = page.evaluate("""async (labels) => {
      const read = eval(labels);
      const state = await (await fetch(location.pathname.replace(/^\\/game\\//, '/api/live-game/') + '/state')).json();
      const before = read();
      window.CBLiveState.adopt(state, 'test');
      const sameTurn = read();
      await new Promise(done => requestAnimationFrame(() => setTimeout(done, 0)));
      return {before, sameTurn, drawn: read()};
    }""", LABELS)
    assert _consistent(readings['before']) and readings['before']['header'] == '1', readings
    assert _consistent(readings['sameTurn']), readings
    assert _consistent(readings['drawn']) and readings['drawn']['header'] == '2', readings
    assert page.cb_errors == []


def test_end_inning_will_not_end_an_inning_the_coach_did_not_see(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    page.evaluate('() => window.__cbLiveGameSocket.disconnect()')
    # Hold this page's polls so it still shows the 1st when the coach taps.
    held = '**/api/live-game/*/{state,next-inning-prep}'
    page.route(held, lambda route: route.abort())
    _remote_end_inning(page, coachboard_url)
    assert page.evaluate(LABELS)['end'] == 'End 1st → Start 2nd'
    page.unroute(held)
    page.locator('#liveEndInningBtn').click()

    notice = page.locator('#cb-test2-inning-recovery')
    expect(notice).to_contain_text('The game is in Inning 2 now', timeout=10_000)
    page.wait_for_timeout(1_000)
    # Nothing ended: the game is still in the 2nd, now shown everywhere.
    assert str(_state(page, coachboard_url)['current_inning']) == '2'
    took, mixed = _watch(page, 3, '2')
    assert page.cb_errors == []
