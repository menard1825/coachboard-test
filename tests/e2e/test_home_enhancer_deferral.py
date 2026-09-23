"""Hidden-feature enhancer scripts make no request until their feature opens.

After main.js stopped loading hidden tabs, three enhancer scripts still made a
request of their own on every Home load, for panes the coach had not opened:

* roster_pitching_traits.js -> /api/roster-pitching-profiles (Roster)
* season_management_v2.js  -> /api/rotations               (Rotations)
* mobile_game_day_fields.js -> /api/games                  (legacy #games, phones)

Each now initialises its network work the first time its pane becomes active,
by any path -- desktop tabs and menus, the phone navigator, a direct /#hash
load -- and keeps its existing refresh behaviour after that. Home is left
with its own work: home_dashboard.js (9), getting_started_home.js (1) and the
usage heartbeat (1).

Two refreshes predate this and are kept: opening Roster or Rotations through
Bootstrap's tab lifecycle (desktop) refreshes an already-initialised feature.
The first desktop open is both an initialisation and such a showing; it must
still make one request, whatever the latency.

The legacy #games pane has no supported way in: navigation_v2.js sends /#games
to /game-day and rewrites every #games link. mobile_game_day_fields.js stays
loaded but dormant, and would initialise if the pane were ever shown.

Requests are attributed to the script whose code called fetch().
"""

import os
import uuid
from collections import Counter

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
LATENCIES = [0, 150]

TRAITS_JS = 'roster_pitching_traits.js'
SEASON_JS = 'season_management_v2.js'
MOBILE_GAMES_JS = 'mobile_game_day_fields.js'
PROFILES = '/api/roster-pitching-profiles'
ROTATIONS = '/api/rotations'
GAMES = '/api/games'
PRESET_PREFIX = 'DEFENSE PRESET — '

#: What Home itself needs, by initiator. Nothing else may make a request.
HOME_OWNERS = Counter({
    'home_dashboard.js': 9,
    'getting_started_home.js': 1,
    'client_timezone.js': 1,          # the usage heartbeat
})

RECORDER = r"""
(() => {
  const native = window.fetch.bind(window);
  window.__cbApi = [];
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.includes('/api/')) {
      const frame = (new Error().stack || '').split('\n')
        .map(line => line.match(/\/static\/js\/([\w.-]+\.js)/)).find(Boolean);
      window.__cbApi.push({path: new URL(url, location.href).pathname,
                           by: frame ? frame[1] : '(unknown)'});
    }
    return native(input, init);
  };
  window.__cbSockets = [];
  let io;
  Object.defineProperty(window, 'io', {
    configurable: true,
    get() { return io; },
    set(value) {
      if (typeof value !== 'function') { io = value; return; }
      const wrapped = function (...args) {
        const socket = value.apply(this, args);
        window.__cbSockets.push(socket);
        return socket;
      };
      Object.assign(wrapped, value);
      io = wrapped;
    },
  });
})();
"""


@pytest.fixture
def make_page(browser):
    contexts = []

    def _make(viewport=DESKTOP, *, api_delay_ms=0):
        cdn_assets.require_vendored_assets()
        mobile = viewport is PHONE
        context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        cdn_assets.install(context, api_delay_ms=api_delay_ms)
        context.add_init_script(RECORDER)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        page.cb_settle = 3000 if api_delay_ms else 2000
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


def _open_home(page, base_url):
    """Home by the team logo from another page, as a coach gets there."""
    _login(page, base_url)
    page.goto(f'{base_url}/pitching')
    page.wait_for_load_state('networkidle')
    page.evaluate('() => { window.__cbApi.length = 0; }')
    page.click('.navbar-brand')
    page.wait_for_load_state('load')
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_have_count(1, timeout=20_000)
    page.wait_for_timeout(page.cb_settle + 1000)


def _direct(page, base_url, hash_):
    """A real document load of /#hash (from another page, not a fragment change)."""
    _login(page, base_url)
    page.goto(f'{base_url}/pitching')
    page.wait_for_load_state('networkidle')
    page.evaluate('() => { window.__cbSameDocument = true; }')
    page.goto(f'{base_url}/#{hash_}')
    page.wait_for_load_state('load')
    assert page.evaluate('window.__cbSameDocument') is None, 'not a fresh document load'


def _calls(page, path=None, by=None):
    return [c for c in page.evaluate('window.__cbApi')
            if (path is None or c['path'] == path) and (by is None or c['by'] == by)]


def _count(page, path, by):
    return len(_calls(page, path, by))


def _by_initiator(page):
    return Counter(c['by'] for c in _calls(page))


def _go(page, pane):
    page.evaluate('id => { location.hash = "#" + id; }', pane)
    expect(page.locator(f'#{pane}')).to_be_visible(timeout=15_000)


def _wait_roster_traits(page):
    page.wait_for_function(
        """() => {
          const cards = document.querySelectorAll('#roster-cards-container .save-player-btn').length;
          const traits = document.querySelectorAll('#roster-cards-container .roster-pitch-profile').length;
          return cards > 0 && traits === cards;
        }""", timeout=20_000)
    expect(page.locator('#roster .cb-roster-metrics-v2 .cb-roster-metric-copy')).to_have_count(3)


def _wait_rotations_decorated(page):
    page.wait_for_function(
        """() => {
          const panel = document.getElementById('defense-preset-home-v2');
          const items = [...document.querySelectorAll('#rotationsAccordion [data-rotation-id]')];
          const header = document.querySelector('#rotations .card-header h5');
          return panel && panel.querySelector('.dph-chip') && items.length > 0
            && items.every(item => item.querySelector('.rotation-template-edit-btn'))
            && header && header.textContent.trim() === 'Full-Game Rotation Templates';
        }""", timeout=20_000)


def _fire(page, event, payload, *, listener_owner):
    """Deliver a socket event to the socket that has `listener_owner` bound."""
    return page.evaluate(
        """async ([event, payload, owner]) => {
          const socket = window.__cbSockets.find(s => s.listeners(owner).length);
          if (!socket) return ['socket not found'];
          const errors = [];
          for (const handler of socket.listeners(event)) {
            try { await handler(payload); } catch (error) { errors.push(String(error)); }
          }
          return errors;
        }""", [event, payload, listener_owner])


# --- 1. Home ---------------------------------------------------------------

@pytest.mark.parametrize('delay', LATENCIES, ids=['0ms', '150ms'])
@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_home_makes_only_its_own_requests(make_page, coachboard_url, viewport, delay):
    page = make_page(viewport, api_delay_ms=delay)
    _open_home(page, coachboard_url)
    initiators = _by_initiator(page)
    for script in (TRAITS_JS, SEASON_JS, MOBILE_GAMES_JS, 'main.js'):
        assert initiators[script] == 0, f'{script} made Home requests: {sorted((c["by"], c["path"]) for c in _calls(page))}'
    assert initiators == HOME_OWNERS, dict(initiators)
    assert sum(initiators.values()) == 11
    assert page.cb_errors == []


def test_mobile_game_fields_is_loaded_but_dormant_on_phone_home(make_page, coachboard_url):
    page = make_page(PHONE)
    _open_home(page, coachboard_url)
    assert page.locator('script[data-cb-mobile-game-day-fields]').count() == 1
    assert _calls(page, by=MOBILE_GAMES_JS) == []
    # Refresh triggers before initialisation do nothing either.
    page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
    page.wait_for_timeout(800)
    assert _calls(page, by=MOBILE_GAMES_JS) == []


# --- 2. Roster profiles --------------------------------------------------------

@pytest.mark.parametrize('delay', LATENCIES, ids=['0ms', '150ms'])
@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_first_roster_open_loads_profiles_once(make_page, coachboard_url, viewport, delay):
    page = make_page(viewport, api_delay_ms=delay)
    _open_home(page, coachboard_url)
    assert _count(page, PROFILES, TRAITS_JS) == 0
    _go(page, 'roster')
    _wait_roster_traits(page)
    page.wait_for_timeout(page.cb_settle)
    assert _count(page, PROFILES, TRAITS_JS) == 1, _calls(page, PROFILES)
    assert page.cb_errors == []


@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_reopening_roster_keeps_the_existing_refresh_only(make_page, coachboard_url, viewport):
    """Desktop opens tabs through Bootstrap, whose shown.bs.tab has always
    refreshed profiles on an initialised Roster; phones never did."""
    page = make_page(viewport)
    _open_home(page, coachboard_url)
    _go(page, 'roster')
    _wait_roster_traits(page)
    page.wait_for_timeout(1000)
    _go(page, 'overview')
    _go(page, 'roster')
    page.wait_for_timeout(1500)
    expected = 1 if viewport is PHONE else 2
    assert _count(page, PROFILES, TRAITS_JS) == expected, _calls(page, PROFILES)
    _wait_roster_traits(page)


@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_direct_roster_load_initialises_profiles(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    _direct(page, coachboard_url, 'roster')
    _wait_roster_traits(page)
    page.wait_for_function("!document.documentElement.classList.contains('cb-desktop-workspace-boot')",
                           timeout=5_000)
    page.wait_for_timeout(1500)
    assert _count(page, PROFILES, TRAITS_JS) == 1, _calls(page, PROFILES)
    assert page.cb_errors == []


def test_profile_refresh_triggers_wait_for_roster(make_page, coachboard_url):
    """focus, visibility, a bfcache restore and a profile socket event are
    refreshes of an initialised Roster, not reasons to initialise it."""
    page = make_page()
    _open_home(page, coachboard_url)
    page.evaluate("""() => {
      window.dispatchEvent(new Event('focus'));
      document.dispatchEvent(new Event('visibilitychange'));
      window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}));
    }""")
    assert _fire(page, 'pitching_profile_update', {'player_id': 1, 'team_id': 1, 'traits': []},
                 listener_owner='pitching_profile_update') == []
    page.wait_for_timeout(1000)
    assert _count(page, PROFILES, TRAITS_JS) == 0

    _go(page, 'roster')
    _wait_roster_traits(page)
    page.wait_for_timeout(1000)
    before = _count(page, PROFILES, TRAITS_JS)
    page.evaluate("() => window.dispatchEvent(new Event('focus'))")
    page.wait_for_timeout(1000)
    assert _count(page, PROFILES, TRAITS_JS) == before + 1
    assert page.cb_errors == []


# --- 3. Rotations ----------------------------------------------------------------

@pytest.mark.parametrize('delay', LATENCIES, ids=['0ms', '150ms'])
@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_first_rotations_open_fetches_once_and_decorates(make_page, coachboard_url, viewport, delay):
    """On desktop the first open is both the initialisation and a shown.bs.tab:
    one request between them."""
    page = make_page(viewport, api_delay_ms=delay)
    _open_home(page, coachboard_url)
    assert _count(page, ROTATIONS, SEASON_JS) == 0
    _go(page, 'rotations')
    _wait_rotations_decorated(page)
    page.wait_for_timeout(page.cb_settle)
    assert _count(page, ROTATIONS, SEASON_JS) == 1, _calls(page, ROTATIONS)
    assert _count(page, ROTATIONS, 'main.js') == 1
    assert page.cb_errors == []


def test_first_desktop_rotations_open_through_the_more_menu(make_page, coachboard_url):
    page = make_page(api_delay_ms=150)
    _open_home(page, coachboard_url)
    page.locator('.navbar .dropdown-toggle', has_text='More').first.click()
    page.locator('a.dropdown-item[href$="#rotations"]').first.click()
    expect(page.locator('#rotations')).to_be_visible(timeout=15_000)
    _wait_rotations_decorated(page)
    page.wait_for_timeout(3000)
    assert _count(page, ROTATIONS, SEASON_JS) == 1, _calls(page, ROTATIONS)


@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_reopening_rotations_keeps_the_existing_refresh_only(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    _open_home(page, coachboard_url)
    _go(page, 'rotations')
    _wait_rotations_decorated(page)
    page.wait_for_timeout(1500)
    _go(page, 'overview')
    _go(page, 'rotations')
    page.wait_for_timeout(1500)
    expected = 1 if viewport is PHONE else 2
    assert _count(page, ROTATIONS, SEASON_JS) == expected, _calls(page, ROTATIONS)
    _wait_rotations_decorated(page)


@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_direct_rotations_load_initialises(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    _direct(page, coachboard_url, 'rotations')
    _wait_rotations_decorated(page)
    page.wait_for_timeout(1500)
    assert _count(page, ROTATIONS, SEASON_JS) == 1, _calls(page, ROTATIONS)
    assert page.cb_errors == []


@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_practice_and_development_do_not_fetch_rotations(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    _open_home(page, coachboard_url)
    _go(page, 'practice_plan')
    expect(page.locator('#practicePlanAccordion .cb-practice-plan-button').first).to_be_attached(timeout=15_000)
    _go(page, 'player_development')
    expect(page.locator('#dev-player-list .cb-dev-player').first).to_be_attached(timeout=15_000)
    page.wait_for_timeout(1500)
    assert _calls(page, ROTATIONS) == []
    assert _calls(page, by=SEASON_JS) == []

    # Reusing a plan still works.
    _go(page, 'practice_plan')
    page.locator('.cb-practice-plan-button').first.click()
    page.get_by_role('button', name='Reuse on another date').first.click()
    expect(page.locator('#reusePracticeModal')).to_be_visible(timeout=5_000)
    assert page.locator('#reusePracticeDate').input_value() != ''
    assert _calls(page, ROTATIONS) == []
    assert page.cb_errors == []


def test_rotation_change_before_first_open_is_current_at_first_open(make_page, coachboard_url):
    """Saving a template emits rotation_save and data_updated, saving a preset
    data_updated; none of them may fetch on Home, and the first open shows
    both -- the template in main.js's list, the preset in this script's panel."""
    page = make_page()
    _open_home(page, coachboard_url)
    title = f'Early Template {uuid.uuid4().hex[:4]}'
    response = page.request.post(f'{coachboard_url}/api/rotation-template/save',
                                 data={'title': title, 'innings': {'1': {}}})
    assert response.ok, response.status
    name = f'Early Preset {uuid.uuid4().hex[:4]}'
    response = page.request.post(f'{coachboard_url}/save_rotation_as_template',
                                 data={'title': PRESET_PREFIX + name, 'innings': {'1': {'P': 'Pitcher Pat'}}})
    assert response.ok, response.status
    page.wait_for_timeout(1500)
    assert _calls(page, ROTATIONS) == []

    _go(page, 'rotations')
    page.wait_for_function(
        """name => [...document.querySelectorAll('#defense-preset-home-v2 .dph-chip')]
                    .some(c => c.textContent.trim() === name)""", arg=name, timeout=15_000)
    _wait_rotations_decorated(page)
    assert title in page.locator('#rotationsAccordion .accordion-button strong').all_inner_texts()
    page.wait_for_timeout(1500)
    assert _count(page, ROTATIONS, SEASON_JS) == 1
    assert page.cb_errors == []


# --- 4. legacy #games (phones) ----------------------------------------------

def test_legacy_games_pane_initialises_if_it_is_ever_shown(make_page, coachboard_url):
    """No supported path shows #games today (see the module docstring). If one
    ever did, the script initialises then, once."""
    page = make_page(PHONE)
    _open_home(page, coachboard_url)
    assert _calls(page, by=MOBILE_GAMES_JS) == []
    page.evaluate("""() => {
      const pane = document.getElementById('games');
      document.querySelectorAll('#mainTabContent > .tab-pane').forEach(p => p.classList.remove('active', 'show'));
      pane.classList.add('active', 'show');
    }""")
    page.wait_for_timeout(1500)
    assert _count(page, GAMES, MOBILE_GAMES_JS) == 1
    page.evaluate("""() => {
      const pane = document.getElementById('games');
      pane.classList.remove('active', 'show');
      pane.classList.add('active', 'show');
    }""")
    page.wait_for_timeout(1000)
    assert _count(page, GAMES, MOBILE_GAMES_JS) == 1
    assert page.cb_errors == []


@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_legacy_games_hash_still_goes_to_game_day(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    _direct_target = '/game-day'
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/pitching')
    page.wait_for_load_state('networkidle')
    page.goto(f'{coachboard_url}/#games')
    page.wait_for_url(f'**{_direct_target}', timeout=15_000)
    page.wait_for_load_state('load')
    assert page.cb_errors == []


@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_game_day_is_untouched(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/game-day')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1000)
    assert page.locator('script[src*="mobile_game_day_fields.js"]').count() == 0
    assert _calls(page, by=MOBILE_GAMES_JS) == []
    assert _calls(page, by=TRAITS_JS) == [] and _calls(page, by=SEASON_JS) == []
    expect(page.locator('main')).to_contain_text('Browser Bears')
    assert page.cb_errors == []
