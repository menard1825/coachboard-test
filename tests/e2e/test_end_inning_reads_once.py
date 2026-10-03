"""End Inning reads the game once, after this page's own writes have landed.

It used to read /state until two reads agreed, 120 ms apart, then read the
next inning and /state again. The page shares a /state read already in the
air, so those repeats returned the same response: a fixed delay and an extra
round trip before the inning could start. End Inning now waits for this
page's live writes and Next Inning saves to finish, then reads the game and
the next inning once, together, with requests that start then. The server's
checks (base_sequence, the Next Inning revision) still catch another
device's change.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_next_inning_save_queue import normal_network, slow_network  # noqa: E402
from test_pregame_plan_reference import (  # noqa: E402,F401 (live is a fixture)
    INNING_1, PHONE, _api, _sequence, _state, live,
)


# End Inning's reads (tagged by caller), its advance, and other live writes.
TIMELINE = r"""() => {
  const log = window.__cbTimeline = [];
  const nativeFetch = window.fetch;
  window.fetch = function(input, init) {
    const url = String((input && input.url) || input).split('?')[0];
    const method = String((init && init.method) || 'GET').toUpperCase();
    const name = url.split('/').pop();
    if (!/^(state|next-inning-prep|advance-inning|defense-edit)$/.test(name)) return nativeFetch.apply(this, arguments);
    const tag = /live_game_contract/.test(new Error().stack || '') ? ' (end inning)' : '';
    const label = `${method} ${name}${tag}`;
    log.push('start ' + label);
    const result = nativeFetch.apply(this, arguments);
    const done = () => log.push('end ' + label);
    result.then(done, done);
    return result;
  };
}"""


def _open(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(1_500)
    page.evaluate(TIMELINE)


def _wait_inning(page, coachboard_url, inning):
    for _ in range(80):
        if str(_state(page, coachboard_url)['current_inning']) == inning:
            return
        page.wait_for_timeout(250)
    assert str(_state(page, coachboard_url)['current_inning']) == inning


def test_end_inning_reads_the_game_once(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    page.locator('#liveEndInningBtn').click()
    _wait_inning(page, coachboard_url, '2')

    log = page.evaluate('() => [...window.__cbTimeline]')
    advance = next(i for i, entry in enumerate(log) if entry.startswith('start POST advance-inning'))
    before = log[:advance]
    reads = [entry for entry in before if entry.endswith('(end inning)')]
    # One read of each, sent together.
    assert sorted(e for e in reads if e.startswith('start')) == [
        'start GET next-inning-prep (end inning)', 'start GET state (end inning)'], log
    assert max(reads.index('start GET state (end inning)'), reads.index('start GET next-inning-prep (end inning)')) < \
        min(i for i, e in enumerate(reads) if e.startswith('end')), log
    assert page.cb_errors == []


def test_end_inning_waits_for_a_change_still_saving(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    state = _state(page, coachboard_url)
    swapped = dict(INNING_1, LF=INNING_1['RF'], RF=INNING_1['LF'])

    cdp = slow_network(page, 800)
    try:
        # A live change from this phone, still in the air when End Inning is tapped.
        page.evaluate("""([url, body]) => { window.fetch(url, {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}); }""",
                      [f'/api/live-game/{page.cb_game}/defense-edit',
                       {'base_sequence': _sequence(state), 'alignment': swapped}])
        page.wait_for_timeout(100)
        page.locator('#liveEndInningBtn').click()
        # The live change carried this inning's field forward: End Inning
        # asks (as always) whether to use the 2nd-inning plan instead.
        question = page.locator('#cbSkippedPlanModal')
        expect(question).to_be_visible(timeout=15_000)
        question.get_by_role('button', name='Keep this defense', exact=True).click()
        _wait_inning(page, coachboard_url, '2')
    finally:
        normal_network(cdp)

    log = page.evaluate('() => [...window.__cbTimeline]')
    # End Inning read the game only after the change was answered ...
    assert log.index('end POST defense-edit') < log.index('start GET state (end inning)'), log
    # ... so the inning started on top of it (the field kept), with no stale-field error.
    after = _state(page, coachboard_url)
    first = [e for e in after['rotation_events'] if e['event_type'] == 'Bulk Defensive Change' and not e['reverted']]
    assert first and {p: n for p, n in first[-1]['after_alignment'].items() if n} == swapped
    assert {p: n for p, n in after['current_alignment'].items() if n} == swapped
    expect(page.locator('#live-inning-display')).to_have_text('2')
    assert page.cb_errors == []
