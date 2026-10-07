"""End Inning's line stops saying "Saving…" when the Next Inning save lands.

The Next Inning board's badge showed the save done, but End Inning's line
("Saving the 2nd defense…") was redrawn while the save still counted as in
the air, and stayed until the next read -- about 0.8 s behind the badge on a
150 ms connection. It now changes with the badge.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from live_fixtures import PHONE, live  # noqa: E402,F401 (live is a fixture)


SAMPLE = """() => {
  window.__lbl = [];
  const tick = () => {
    window.__lbl.push({t: performance.now(),
      badge: document.querySelector('#live-board-prep-v3 .cb-next-save')?.className || '',
      note: document.querySelector('#liveEndInningBtn .coach-action-note')?.textContent?.trim() || ''});
    if (window.__lbl.length < 400) requestAnimationFrame(tick);
  };
  tick();
}"""


def test_end_inning_line_follows_the_save(live, coachboard_url):
    page = live(PHONE)
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(1_500)
    cdp = page.context.new_cdp_session(page)
    cdp.send('Network.enable')
    cdp.send('Network.emulateNetworkConditions', {
        'offline': False, 'latency': 150, 'downloadThroughput': -1, 'uploadThroughput': -1})

    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator('#live-board-prep-v3')
    spot = lambda pos: board.locator(f'[data-next-position="{pos}"]')
    rf = spot('RF').get_attribute('data-next-player')
    spot('LF').click()
    spot('RF').click()
    page.evaluate(SAMPLE)
    page.locator('#cbNextPitchingChange').get_by_role('button', name=f'Put {rf} at LF', exact=True).click()
    page.wait_for_timeout(2_500)

    samples = page.evaluate('() => window.__lbl')
    saving = [s for s in samples if s['note'].startswith('Saving the')]
    assert saving, 'End Inning never said it was saving'
    saved_at = next(s['t'] for s in samples if ' saved' in f" {s['badge']} " and s['t'] > saving[0]['t'])
    note_at = next(s['t'] for s in samples if s['t'] > saving[0]['t'] and not s['note'].startswith('Saving the'))
    assert note_at - saved_at < 100, (note_at - saved_at, samples[-1])
    assert samples[-1]['note'] == 'Your changes for the 2nd'
    assert page.cb_errors == []
