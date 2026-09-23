"""pageshow must refresh only after a back/forward-cache restore.

Two Home modules refetched on every `pageshow`:

* roster_pitching_traits.js -> /api/roster-pitching-profiles (every viewport)
* mobile_game_day_fields.js -> /api/games (phones and tablets only)

Both already fetch once in their own start-up code. `pageshow` also fires on
every ordinary page load, so each normal Home visit fetched twice. The only
pageshow worth refreshing on is a bfcache restore (`event.persisted`), where
the page comes back from memory with whatever data it had when the coach
left.

Requests are attributed to the script that made them, from the fetch call's
stack, because /api/games also has legitimate callers in main.js and
home_dashboard.js. Counting the endpoint alone would test the wrong thing.

The normal-pageshow and restore tests dispatch a synthetic PageTransitionEvent
after the page has settled. That exercises exactly the handler under test with
no timing dependence -- the load-count tests alone could pass by luck if the
first fetch were still in flight when pageshow fired.
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

PROFILES = '/api/roster-pitching-profiles'
GAMES = '/api/games'
TRAITS_JS = 'roster_pitching_traits.js'
MOBILE_GAMES_JS = 'mobile_game_day_fields.js'

#: Records every /api/ fetch with the first application script on its stack.
FETCH_RECORDER = r"""
(() => {
  const native = window.fetch.bind(window);
  window.__cbApi = [];
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.includes('/api/')) {
      const frame = (new Error().stack || '').split('\n')
        .map(line => line.match(/\/static\/js\/([\w.-]+\.js)/))
        .find(Boolean);
      window.__cbApi.push({
        path: new URL(url, location.href).pathname,
        by: frame ? frame[1] : '(unknown)',
      });
    }
    return native(input, init);
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
        context.add_init_script(FETCH_RECORDER)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        return page

    yield _make
    for context in contexts:
        context.close()


def _open_home(page, base_url):
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')
    page.goto(f'{base_url}/')
    page.wait_for_load_state('load')
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_have_count(1, timeout=15_000)
    # Traits panels exist only after the profile fetch has resolved.
    page.wait_for_function(
        """() => {
          const cards = document.querySelectorAll('#roster-cards-container .save-player-btn').length;
          const traits = document.querySelectorAll('#roster-cards-container .roster-pitch-profile').length;
          return cards > 0 && traits === cards;
        }""",
        timeout=15_000,
    )
    page.wait_for_timeout(1500)


def _calls(page, path, by=None):
    return [call for call in page.evaluate('window.__cbApi')
            if call['path'] == path and (by is None or call['by'] == by)]


def _dispatch_pageshow(page, persisted):
    page.evaluate(
        "persisted => window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted}))",
        persisted)
    page.wait_for_timeout(800)


def _describe(page, path):
    return sorted((call['by'] for call in _calls(page, path)))


# --- roster_pitching_traits.js ---------------------------------------------

def test_home_load_fetches_roster_profiles_once(make_page, coachboard_url):
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    calls = _calls(page, PROFILES)
    assert len(calls) == 1, f'{PROFILES} fetched {len(calls)} times on one Home load: {calls}'
    assert calls[0]['by'] == TRAITS_JS
    assert page.cb_errors == []


def test_normal_pageshow_does_not_refetch_roster_profiles(make_page, coachboard_url):
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    before = len(_calls(page, PROFILES, TRAITS_JS))
    _dispatch_pageshow(page, persisted=False)
    after = len(_calls(page, PROFILES, TRAITS_JS))
    assert after == before, f'a normal pageshow refetched {PROFILES} ({before} -> {after})'


def test_bfcache_restore_refreshes_roster_profiles(make_page, coachboard_url):
    """A restored page may hold stale traits from before the coach left."""
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    before = len(_calls(page, PROFILES, TRAITS_JS))
    _dispatch_pageshow(page, persisted=True)
    after = len(_calls(page, PROFILES, TRAITS_JS))
    assert after == before + 1, f'a bfcache restore did not refresh {PROFILES} ({before} -> {after})'
    # The refresh must still land in the roster, not just fire a request.
    expect(page.locator('#roster-cards-container .roster-pitch-profile')).not_to_have_count(0)
    assert page.cb_errors == []


# --- mobile_game_day_fields.js (phones and tablets only) -------------------

def test_phone_home_load_fetches_mobile_games_once(make_page, coachboard_url):
    page = make_page(PHONE)
    _open_home(page, coachboard_url)
    mine = _calls(page, GAMES, MOBILE_GAMES_JS)
    assert len(mine) == 1, (
        f'{MOBILE_GAMES_JS} fetched {GAMES} {len(mine)} times on one Home load; '
        f'all {GAMES} callers: {_describe(page, GAMES)}')
    # The other callers are legitimate and out of scope; they must be seen and
    # attributed separately, or this test would not be measuring the module.
    others = {call['by'] for call in _calls(page, GAMES)} - {MOBILE_GAMES_JS}
    assert {'main.js', 'home_dashboard.js'} <= others, _describe(page, GAMES)
    assert page.cb_errors == []


def test_normal_pageshow_does_not_refetch_mobile_games(make_page, coachboard_url):
    page = make_page(PHONE)
    _open_home(page, coachboard_url)
    before = len(_calls(page, GAMES, MOBILE_GAMES_JS))
    _dispatch_pageshow(page, persisted=False)
    after = len(_calls(page, GAMES, MOBILE_GAMES_JS))
    assert after == before, f'a normal pageshow refetched {GAMES} ({before} -> {after})'


def test_bfcache_restore_refreshes_mobile_games(make_page, coachboard_url):
    page = make_page(PHONE)
    _open_home(page, coachboard_url)
    before = len(_calls(page, GAMES, MOBILE_GAMES_JS))
    _dispatch_pageshow(page, persisted=True)
    after = len(_calls(page, GAMES, MOBILE_GAMES_JS))
    assert after == before + 1, f'a bfcache restore did not refresh {GAMES} ({before} -> {after})'
    assert page.cb_errors == []


def test_desktop_does_not_load_the_mobile_games_module(make_page, coachboard_url):
    """Guard for the attribution above: this module is phone/tablet only."""
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    assert _calls(page, GAMES, MOBILE_GAMES_JS) == []
