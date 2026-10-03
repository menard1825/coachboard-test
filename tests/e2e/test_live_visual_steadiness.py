"""Small visual steadiness fixes on the Live Game page.

- After a reload the header clock showed 0:00 until its first read; it now
  shows "—" until the server's time is known.
- The 12 s recovery read of the live state rebuilt the whole field card
  (Bench Report button and icon included) even when nothing had changed;
  the card is now redrawn only when its own data changes.
- With the next inning's P open, the Next Inning tab said so twice, one
  line above the other wider than a phone ("Set a pitcher for the next
  inning." and End Inning's "⚠ Next inning: P is open"); End Inning's line
  now steps aside there. On a phone the fixed End Inning dock covers the
  card's line, so End Inning's line stays the one in view.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_reference import PHONE, _api, live  # noqa: E402,F401 (live is a fixture)


FIRST_FRAMES = r"""
(() => {
  const seen = window.__clockSeen = [];
  const t0 = performance.now();
  const tick = () => {
    const text = document.querySelector('#cbDugoutHeader [data-cb-clock-time]')?.textContent?.trim();
    if (text && seen[seen.length - 1] !== text) seen.push(text);
    if (performance.now() - t0 < 3000) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})();
"""


def _open(page, url):
    page.goto(f'{url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)


def test_the_clock_never_shows_zero_before_it_is_known(live, coachboard_url):
    page = live(PHONE)
    api = page.cb_api.request
    assert api.post(_api(page, coachboard_url, 'clock'), data={'time_limit_minutes': 90}).ok
    page.add_init_script(FIRST_FRAMES)
    _open(page, coachboard_url)
    page.wait_for_timeout(3_000)
    seen = page.evaluate('() => window.__clockSeen')
    assert '0:00' not in seen, seen
    assert [text for text in seen if text != '—'][0].startswith('1:29:'), seen   # 90-minute limit, counting down


def test_the_field_card_is_not_rebuilt_when_nothing_changed(live, coachboard_url):
    page = live(PHONE)
    _open(page, coachboard_url)
    page.wait_for_timeout(1_500)
    page.evaluate("""() => { window.__card = [...document.querySelectorAll('#cbQuickDefense button')]; }""")
    page.wait_for_timeout(13_000)                                   # past the 12 s recovery read
    kept = page.evaluate("""() => window.__card.length > 0 && window.__card.every(button => button.isConnected)""")
    assert kept, 'the field card was rebuilt by the recovery read'


IPAD = ('device', {'width': 820, 'height': 1180}, {'is_mobile': True, 'has_touch': True})


def _open_p_next(page, url):
    prep = page.cb_api.request.get(_api(page, url, 'next-inning-prep')).json()
    response = page.cb_api.request.post(_api(page, url, 'next-inning-prep'), data={
        'mode': 'custom', 'alignment': dict(prep['confirmed']['alignment'], P=''),
        'base_alignment': prep['confirmed']['alignment'], 'inning': prep['next_inning']})
    assert response.ok, response.text()[:300]


def test_an_open_p_is_said_once_on_the_next_inning_tab(live, coachboard_url):
    page = live(IPAD)
    _open_p_next(page, coachboard_url)
    _open(page, coachboard_url)
    line = page.locator('#cbNextOpenWarning')
    # On the field tab, End Inning's line is the notice (and a shortcut).
    expect(line).to_have_text('⚠ Next inning: P is open', timeout=10_000)
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    # On the next inning's tab the card's own line, just above End Inning, says it.
    note = page.locator('#live-board-prep-v3 #cb-next-needs-pitcher')
    expect(note).to_be_in_viewport()
    expect(line).to_have_count(0)
    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    expect(line).to_have_text('⚠ Next inning: P is open')
    assert page.cb_errors == []


def test_on_a_phone_the_line_stays_where_the_dock_covers_the_card(live, coachboard_url):
    page = live(PHONE)
    _open_p_next(page, coachboard_url)
    _open(page, coachboard_url)
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    expect(page.locator('#live-board-prep-v3 #cb-next-needs-pitcher')).not_to_be_in_viewport()
    expect(page.locator('#cbNextOpenWarning')).to_have_text('⚠ Next inning: P is open')
    expect(page.locator('#cbNextOpenWarning')).to_be_in_viewport()
    assert page.cb_errors == []
