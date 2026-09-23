"""The roster metric enhancer must settle, and Roster must still render.

roster_pitching_traits.js relabels the Roster summary chips ("9 total
players", "7 of 9 are pitchers", ...). Its render() used to delete and
re-create the label nodes on every call, and it watches those same nodes, so
each render queued the next one: about 240 callbacks a second for as long as
Home was open, with a second whole-body observer re-scanning the hidden roster
on every pass. Measured before the fix: roughly 1.5 s of main-thread CPU per
5 s under 4x CPU throttling, indefinitely.

The loop tests are behavioural. After the page has settled they watch, for a
fixed window, how many DOM mutations happen under #roster and how many
animation frames the page requests. They do not know which function looped,
so they would also catch a different enhancer doing the same thing.

The navigation tests pin what the fix must not break: Roster opened from the
desktop nav, from the phone bottom nav, and by loading /#roster directly, with
the chip labels exactly as the enhancer intends.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

DESKTOP = {'width': 1440, 'height': 900}
PHONE = {'width': 390, 'height': 844}

#: How long to watch once the page has settled, and how much activity is
#: acceptable in that window. Measured on the fixed build: 0 roster mutations
#: and 0 animation frames. Measured on the looping build over the same window:
#: thousands of each.
QUIET_WINDOW_MS = 2000
MAX_ROSTER_MUTATIONS = 0
MAX_ANIMATION_FRAMES = 10

#: Counts every requestAnimationFrame call on the page, whoever makes it.
FRAME_COUNTER = r"""
(() => {
  const native = window.requestAnimationFrame.bind(window);
  window.__cbFrames = 0;
  window.requestAnimationFrame = (callback) => {
    window.__cbFrames += 1;
    return native(callback);
  };
})();
"""


@pytest.fixture
def make_page(browser):
    contexts = []

    def _make(viewport):
        cdn_assets.require_vendored_assets()
        mobile = viewport is PHONE
        context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        cdn_assets.install(context)
        context.add_init_script(FRAME_COUNTER)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        return page

    yield _make
    for context in contexts:
        context.close()


def _login(page, base_url):
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')


def _wait_until_roster_is_enhanced(page):
    """Roster rendered, metrics relabelled, and every card has its traits panel."""
    expect(page.locator('#roster .cb-roster-metrics-v2')).to_have_count(1, timeout=15_000)
    expect(page.locator('#roster-cards-container .save-player-btn')).not_to_have_count(0, timeout=15_000)
    page.wait_for_function(
        """() => {
          const cards = document.querySelectorAll('#roster-cards-container .save-player-btn').length;
          const traits = document.querySelectorAll('#roster-cards-container .roster-pitch-profile').length;
          return cards > 0 && traits === cards;
        }""",
        timeout=15_000,
    )
    # Let one-shot debounces and follow-up frames from the initial render finish.
    page.wait_for_timeout(1000)


def _activity_in_quiet_window(page):
    return page.evaluate(
        """async (windowMs) => {
          const roster = document.getElementById('roster');
          let mutations = 0;
          const watcher = new MutationObserver(records => { mutations += records.length; });
          watcher.observe(roster, {subtree: true, childList: true, characterData: true, attributes: true});
          const framesBefore = window.__cbFrames;
          await new Promise(resolve => setTimeout(resolve, windowMs));
          watcher.disconnect();
          return {mutations, frames: window.__cbFrames - framesBefore};
        }""",
        QUIET_WINDOW_MS,
    )


def _assert_settled(page, where):
    # Two consecutive windows: a loop that is merely slow would show up in both.
    for attempt in (1, 2):
        activity = _activity_in_quiet_window(page)
        assert activity['mutations'] <= MAX_ROSTER_MUTATIONS, (
            f'{where}: #roster kept mutating after the page settled '
            f'(window {attempt}): {activity}')
        assert activity['frames'] <= MAX_ANIMATION_FRAMES, (
            f'{where}: the page kept requesting animation frames after it '
            f'settled (window {attempt}): {activity}')


def _expected_metric_text(page, base_url):
    """What the enhancer should say, computed from the same data main.js uses."""
    roster = page.request.get(f'{base_url}/api/roster').json()
    total = len(roster)
    pitchers = sum(1 for p in roster if p.get('pitcher_role') and p['pitcher_role'] != 'Not a Pitcher')
    incomplete = sum(1 for p in roster
                     if not (p.get('number') and p.get('position1') and p.get('throws') and p.get('bats')))
    plural = '' if total == 1 else 's'
    return {
        'total': f'{total} total player{plural}',
        'pitchers': (f'{pitchers} of 1 is a pitcher' if total == 1
                     else f'{pitchers} of {total} are pitchers'),
        'profiles': (f'All {total} profiles complete' if incomplete == 0
                     else f'{incomplete} of {total} profile{plural} incomplete'),
    }


def _assert_metric_labels(page, base_url):
    expected = _expected_metric_text(page, base_url)
    chips = page.evaluate(
        """() => {
          const text = el => (el?.textContent || '').replace(/\\s+/g, ' ').trim();
          const total = document.querySelector('#roster .cb-roster-total');
          const pitchers = document.getElementById('rosterPitcherCount')?.closest('span');
          const profiles = document.getElementById('rosterProfileStatus');
          return {
            total: text(total), pitchers: text(pitchers), profiles: text(profiles),
            copies: [total, pitchers, profiles].map(el =>
              el ? el.querySelectorAll(':scope > .cb-roster-metric-copy').length : -1),
          };
        }""")
    assert chips['total'] == expected['total'], chips
    assert chips['pitchers'] == expected['pitchers'], chips
    assert chips['profiles'] == expected['profiles'], chips
    # Exactly one label per chip: a fix that appended instead of replacing
    # would pass the text checks above only by accident.
    assert chips['copies'] == [1, 1, 1], chips


# --- the loop --------------------------------------------------------------

def test_roster_enhancer_settles_while_home_is_open(make_page, coachboard_url):
    """Roster is hidden behind Home here; it must still stop working."""
    page = make_page(DESKTOP)
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/')
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_have_count(1, timeout=15_000)
    _wait_until_roster_is_enhanced(page)
    _assert_settled(page, 'Home')
    assert page.cb_errors == []


def test_roster_enhancer_settles_while_roster_is_visible(make_page, coachboard_url):
    page = make_page(DESKTOP)
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/#roster')
    _wait_until_roster_is_enhanced(page)
    _assert_settled(page, 'Roster')
    assert page.cb_errors == []


def test_roster_enhancer_settles_on_phone(make_page, coachboard_url):
    page = make_page(PHONE)
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/')
    _wait_until_roster_is_enhanced(page)
    _assert_settled(page, 'Home (phone)')
    assert page.cb_errors == []


def test_roster_enhancer_rerenders_once_when_the_counts_change(make_page, coachboard_url):
    """Settling must not mean ignoring real changes.

    main.js rewrites the three summary elements whenever it re-renders the
    roster. The enhancer has to relabel them again -- once -- and then stop.
    """
    page = make_page(DESKTOP)
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/#roster')
    _wait_until_roster_is_enhanced(page)

    # Simulate main.js renderRoster() writing new counts.
    page.evaluate("""() => {
      document.getElementById('rosterPlayerCount').textContent = '42';
      document.getElementById('rosterPitcherCount').textContent = '17';
      const profile = document.getElementById('rosterProfileStatus');
      profile.innerHTML = '<strong>5</strong> profiles to finish';
      profile.classList.remove('is-complete');
    }""")
    page.wait_for_timeout(500)

    chips = page.evaluate("""() => ['.cb-roster-total', '#rosterPitcherCount', '#rosterProfileStatus']
      .map(sel => document.querySelector(sel))
      .map(el => el.closest('span') || el)
      .map(el => el.textContent.replace(/\\s+/g, ' ').trim())""")
    assert chips == ['42 total players', '17 of 42 are pitchers', '5 of 42 profiles incomplete'], chips
    _assert_settled(page, 'Roster after a count change')


def test_roster_enhancer_settles_when_every_profile_is_complete(make_page, coachboard_url):
    """The complete-profiles branch writes the word 'All' into the chip.

    That branch has its own write, separate from the label spans, so it needs
    its own settle check. The seeded roster has incomplete profiles, so the
    state is produced the way main.js renderRoster() would produce it.
    """
    page = make_page(DESKTOP)
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/#roster')
    _wait_until_roster_is_enhanced(page)

    page.evaluate("""() => {
      const profile = document.getElementById('rosterProfileStatus');
      profile.innerHTML = '<strong>All</strong> profiles complete';
      profile.classList.add('is-complete');
    }""")
    page.wait_for_timeout(500)

    total = page.locator('#rosterPlayerCount').inner_text().strip()
    text = page.locator('#rosterProfileStatus').evaluate(
        "el => el.textContent.replace(/\\s+/g, ' ').trim()")
    assert text == f'All {total} profiles complete', text
    _assert_settled(page, 'Roster with every profile complete')


# --- navigation must still produce a normal Roster -------------------------

def test_roster_opens_from_the_desktop_nav(make_page, coachboard_url):
    page = make_page(DESKTOP)
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/')
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_have_count(1, timeout=15_000)

    page.locator('.coach-primary-nav [data-cb-section="roster"]').click()

    expect(page).to_have_url(re.compile(r'/#roster$'))
    expect(page.locator('#roster')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('#roster')).to_be_visible()
    _wait_until_roster_is_enhanced(page)
    _assert_metric_labels(page, coachboard_url)
    assert page.cb_errors == []


def test_direct_roster_load_clears_the_boot_screen(make_page, coachboard_url):
    """/#roster on desktop hides the workspace until the roster is ready."""
    page = make_page(DESKTOP)
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/#roster')

    expect(page.locator('html')).not_to_have_class(
        re.compile(r'\bcb-desktop-workspace-boot\b'), timeout=15_000)
    expect(page.locator('#roster')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('#roster')).to_be_visible()
    visibility = page.locator('#mainTabContent').evaluate('el => getComputedStyle(el).visibility')
    assert visibility == 'visible'
    _wait_until_roster_is_enhanced(page)
    _assert_metric_labels(page, coachboard_url)
    assert page.cb_errors == []


def test_roster_opens_from_the_phone_bottom_nav(make_page, coachboard_url):
    page = make_page(PHONE)
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/')
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_have_count(1, timeout=15_000)

    links = page.locator('#cb-global-mobile-nav a[href$="#roster"], nav.bottom-nav-fixed a[href$="#roster"]')
    visible = [links.nth(i) for i in range(links.count()) if links.nth(i).is_visible()]
    assert visible, 'no visible Roster link in the phone bottom navigation'
    visible[0].click()

    expect(page.locator('#roster')).to_be_visible(timeout=15_000)
    _wait_until_roster_is_enhanced(page)
    _assert_metric_labels(page, coachboard_url)
    assert page.cb_errors == []
