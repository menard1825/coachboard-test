"""Change Pitcher does not wait on its dialogs' fade-outs.

Picking the reliever used to wait for the pitcher list to fade out before
reading the state the question needs, and answering the question waited for
it to fade out before saving: about 0.6 s of animation in front of the
coach's network work. Now the read runs while the list closes and the save
leaves at the tap. Unchanged: the question still opens only after the list
has gone (one dialog at a time), a second tap sends nothing, the result is
one pitching change, and focus goes back to Change Pitcher.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect  # noqa: E402

from live_fixtures import (  # noqa: E402,F401 (live_field is a fixture)
    BASE,
    live_field,
    live_state,
    wait_for_field,
)
from test_live_change_pitcher_decision import QUESTION  # noqa: E402


PICKER = '#live-pitcher-picker-v2'

# What happened when: state reads, the pitching-change save, dialogs opening
# and closing -- in the page's own clock.
TIMELINE = r"""() => {
  const log = window.__cbTimeline = [];
  const nativeFetch = window.fetch;
  window.fetch = function(input, init) {
    const url = String((input && input.url) || input);
    const method = String((init && init.method) || 'GET').toUpperCase();
    if (/\/state(\?|$)/.test(url)) {
      const mine = /live_game_pitcher_change_complete/.test(new Error().stack || '');
      log.push(method + ' state' + (mine ? ' (pitching change)' : ''));
    }
    if (/complete-pitcher-change/.test(url)) log.push(method + ' complete-pitcher-change');
    return nativeFetch.apply(this, arguments);
  };
  document.addEventListener('show.bs.modal', e => log.push('show ' + e.target.id));
  document.addEventListener('hidden.bs.modal', e => log.push('hidden ' + e.target.id));
}"""


def _timeline(page):
    return page.evaluate('() => [...window.__cbTimeline]')


def test_change_pitcher_reads_and_saves_without_waiting_on_fades(page: Page, coachboard_url, live_field):
    game_id = live_field()
    page.evaluate(TIMELINE)

    page.locator('#liveChangePitcherBtn').click()
    picker = page.locator(PICKER)
    expect(picker).to_be_visible(timeout=10_000)
    page.evaluate('() => { window.__cbTimeline.length = 0; }')

    picker.locator('.pitcher-choice-v2', has=page.get_by_text('Shortstop Shawn', exact=True)).click()
    question = page.locator(QUESTION)
    expect(question).to_be_visible(timeout=10_000)
    log = _timeline(page)
    # The question's state is read while the list is still closing ...
    assert log.index('GET state (pitching change)') < log.index('hidden live-pitcher-picker-v2'), log
    # ... and the question opens only once the list has gone.
    assert log.index('hidden live-pitcher-picker-v2') < log.index('show live-pitcher-destination-v7'), log
    expect(question).to_contain_text('Where should Pitcher Pat go?')

    page.wait_for_function(
        f"() => document.querySelector('{QUESTION}').classList.contains('show')", timeout=5_000)
    page.evaluate('() => { window.__cbTimeline.length = 0; }')
    # The answer, tapped twice in a row.
    page.evaluate(f"""() => {{
        const button = [...document.querySelectorAll('{QUESTION} [data-pc-choices] button')]
            .find(b => b.textContent.trim() === 'Put Pitcher Pat at SS');
        button.click();
        button.click();
    }}""")
    swapped = dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat')
    wait_for_field(page, coachboard_url, game_id, swapped)
    expect(question).not_to_be_visible(timeout=10_000)
    page.wait_for_timeout(300)

    log = _timeline(page)
    # Saved at the tap, before the question finished closing; once.
    assert log.count('POST complete-pitcher-change') == 1, log
    assert log.index('POST complete-pitcher-change') < log.index('hidden live-pitcher-destination-v7'), log
    changes = [e for e in live_state(page, coachboard_url, game_id)['rotation_events']
               if e['event_type'] == 'Pitcher Change' and not e['reverted']]
    assert len(changes) == 1
    expect(page.locator('#cbQuickDefense [data-cb-position="P"]')).to_contain_text('Shortstop Shawn')
    # Focus goes back to Change Pitcher, as before.
    expect(page.locator('#liveChangePitcherBtn')).to_be_focused()


def test_cancel_still_changes_nothing(page: Page, coachboard_url, live_field):
    game_id = live_field()
    page.locator('#liveChangePitcherBtn').click()
    picker = page.locator(PICKER)
    expect(picker).to_be_visible(timeout=10_000)
    picker.locator('.pitcher-choice-v2', has=page.get_by_text('Shortstop Shawn', exact=True)).click()
    question = page.locator(QUESTION)
    expect(question).to_be_visible(timeout=10_000)
    question.get_by_role('button', name='Cancel', exact=True).click()
    expect(question).not_to_be_visible(timeout=10_000)
    page.wait_for_timeout(500)
    state = live_state(page, coachboard_url, game_id)
    assert {p: n for p, n in state['current_alignment'].items() if n} == BASE
    # Change Pitcher opens again normally.
    page.locator('#liveChangePitcherBtn').click()
    expect(picker).to_be_visible(timeout=10_000)
