"""main.js loads a legacy workspace section's data when the section is opened.

Home belongs to home_dashboard.js. main.js used to fetch all thirteen of its
datasets at start-up anyway -- session, roster, lineups, pitching, scouting,
rotations, games, notes, practice plans, development, signs, stats and the
legacy overview -- and render every hidden tab, so half of Home's API requests
served panes the coach had not opened.

The contract pinned here:

* Home: main.js makes no API request of its own (desktop and phone).
* First open of a section fetches exactly the datasets that section renders,
  once each, renders it, and lets its enhancer scripts decorate it.
* Every way in works: the desktop top navigation, the desktop More menu, the
  hidden legacy tab strip (Bootstrap's tab lifecycle, which the Roster and
  Development cross-links still use), the phone bottom bar, the phone More
  pane, and a direct /#hash load -- including the desktop Roster pre-paint.
* Reopening a loaded section fetches nothing; two sections opened at once
  share the requests for the datasets they have in common.
* Socket events that arrive before a section has loaded neither throw nor
  invent data: the later first open shows the server's current data.
  After a section has loaded, events refresh it.
* A failed first load is reported in that section only, stays retryable, and
  is never treated as loaded.
* When home_dashboard.js is unavailable, main.js still draws its legacy
  overview with real data.

The Schedule pane (#games) is not reachable: navigation_v2.js redirects
/#games to /game-day and rewrites every #games link. Its handlers are still
exercised below through socket events.
"""

import os
import re
import uuid
from collections import Counter

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from e2e_cleanup import delete_players_named  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
DESKTOP = {'width': 1440, 'height': 900}
PHONE = {'width': 390, 'height': 844}
MAIN_JS = 'main.js'

#: section -> (main.js endpoints for a first open from Home,
#:             selector that proves main.js rendered it,
#:             selector that proves its enhancer scripts decorated it, or None)
SECTIONS = {
    'roster': (
        {'/api/session_data', '/api/roster'},
        '#roster-cards-container .save-player-btn',
        '#roster-cards-container .roster-pitch-profile',          # roster_pitching_traits.js
    ),
    'player_development': (
        {'/api/session_data', '/api/roster', '/api/player_development'},
        '#dev-player-list .cb-dev-player',
        None,
    ),
    'lineups': (
        {'/api/lineups', '/api/roster'},                           # roster: the lineup editor
        '#lineupsAccordion [data-lineup-id]',
        None,
    ),
    'rotations': (
        {'/api/rotations'},
        '#rotationsAccordion [data-rotation-id]',
        '#rotationsAccordion .rotation-template-edit-btn',         # season_management_v2.js
    ),
    'scouting_list': (
        {'/api/scouting_list'},
        '#scouting-list-targets .fw-bold',
        None,
    ),
    'practice_plan': (
        {'/api/practice_plans', '/api/roster'},                    # roster: attendance
        '#practicePlanAccordion .accordion-item',
        None,
    ),
    'signs': (
        {'/api/signs'},
        '#signs-list-container strong',
        None,
    ),
    'stats': (
        {'/api/stats', '/api/roster'},
        '#stats-content-container > *',
        '#stats-content-container [data-stats-dashboard-v2]',      # stats_dashboard_v2.js
    ),
    'collaboration': (
        {'/api/session_data', '/api/roster', '/api/collaboration_notes'},
        '#team-notes-container .card',
        None,
    ),
    'pitching': (
        {'/api/session_data', '/api/roster', '/api/pitching_data'},
        '#recorded-outings-list li strong',
        None,
    ),
}

FETCH_RECORDER = r"""
(() => {
  const native = window.fetch.bind(window);
  window.__cbApi = [];
  const hold = window.__cbHold = {path: null, ms: 0};
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.includes('/api/')) {
      const frame = (new Error().stack || '').split('\n')
        .map(line => line.match(/\/static\/js\/([\w.-]+\.js)/))
        .find(Boolean);
      window.__cbApi.push({path: new URL(url, location.href).pathname,
                           by: frame ? frame[1] : '(unknown)'});
    }
    // A test can hold one endpoint's responses: the server answers at once,
    // but the page only sees the answer later -- a request that was already
    // out when the server changed.
    const path = url.includes('/api/') ? new URL(url, location.href).pathname : null;
    if (path && path === hold.path) {
      return native(input, init).then(response =>
        new Promise(resolve => setTimeout(() => resolve(response), hold.ms)));
    }
    return native(input, init);
  };

  // Keep every socket.io client so a test can deliver an event to main.js's
  // handlers exactly as an incoming packet would.
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

  // Anything main.js ever wrote into the Roster list before real cards.
  window.__cbRosterStates = [];
  document.addEventListener('DOMContentLoaded', () => {
    const list = document.getElementById('roster-cards-container');
    if (!list) return;
    new MutationObserver(() => {
      const text = list.textContent.replace(/\s+/g, ' ').trim();
      if (!list.querySelector('.save-player-btn')) window.__cbRosterStates.push(text.slice(0, 80));
    }).observe(list, {childList: true});
  });
})();
"""


@pytest.fixture
def make_page(browser, coachboard_url):
    contexts = []
    pages = []

    def _make(viewport=DESKTOP, *, api_delay_ms=0, blocked=()):
        cdn_assets.require_vendored_assets()
        mobile = viewport is PHONE
        context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        cdn_assets.install(context, api_delay_ms=api_delay_ms, blocked=blocked)
        context.add_init_script(FETCH_RECORDER)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text)
                if message.type == 'error' and 'Could not load' not in message.text
                and 'Failed to load resource' not in message.text else None)
        page.cb_errors = errors
        page.cb_failing = set()
        page.cb_players = []
        pages.append(page)
        return page

    yield _make
    # Remove the players these tests added so the shared roster is unchanged.
    for page in pages:
        if page.cb_players:
            left = delete_players_named(page.request, coachboard_url, page.cb_players)
            assert left == [], f'test players were not removed: {left}'
    for context in contexts:
        context.close()


def _login(page, base_url):
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')


def _open_home(page, base_url, *, settle_ms=2500):
    _login(page, base_url)
    page.goto(f'{base_url}/')
    page.wait_for_load_state('load')
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_have_count(1, timeout=30_000)
    page.wait_for_timeout(settle_ms)


def _calls(page, by=MAIN_JS):
    return [call['path'] for call in page.evaluate('window.__cbApi') if call['by'] == by]


def _fail(page, path):
    page.cb_failing.add(path)
    page.route(f'**{path}', lambda route: route.fulfill(
        status=500, content_type='application/json', body='{"status": "error"}'))


def _recover(page, path):
    page.cb_failing.discard(path)
    page.unroute(f'**{path}')


def _go(page, section):
    page.evaluate('id => { location.hash = "#" + id; }', section)
    expect(page.locator(f'#{section}')).to_be_visible(timeout=15_000)


def _assert_rendered(page, section, *, enhancer=True):
    _, ready, decorated = SECTIONS[section]
    expect(page.locator(ready).first).to_be_attached(timeout=15_000)
    if enhancer and decorated:
        expect(page.locator(decorated).first).to_be_attached(timeout=15_000)


def _fire(page, event, payload=None):
    """Deliver one socket event to main.js's handlers; return what they threw."""
    return page.evaluate(
        """async ([event, payload]) => {
          const socket = window.__cbSockets.find(s => s.listeners('roster_add').length);
          if (!socket) return ['main.js socket not found'];
          const errors = [];
          for (const handler of socket.listeners(event)) {
            try { await handler(payload); } catch (error) { errors.push(String(error)); }
          }
          return errors;
        }""",
        [event, payload],
    )


def _roster_names(page):
    return page.locator('#roster-cards-container .cb-roster-name').all_inner_texts()


def _add_player(page, base_url, name):
    response = page.request.post(f'{base_url}/add_player', form={
        'name': name, 'number': '77', 'position1': 'SS', 'position2': '', 'position3': '',
        'throws': 'Right', 'bats': 'Right', 'notes': '', 'pitcher_role': 'Not a Pitcher',
        'roster_status': 'regular'})
    assert response.status in (200, 302), response.status
    page.cb_players.append(name)


def _add_template(page, base_url, title):
    response = page.request.post(f'{base_url}/api/rotation-template/save',
                                 data={'title': title, 'innings': {'1': {}}})
    assert response.ok, (response.status, response.text())


def _rotation_titles(page):
    return [t.strip() for t in
            page.locator('#rotationsAccordion .accordion-button strong').all_inner_texts()]


# --- 1. Home ----------------------------------------------------------------

@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_home_load_makes_no_main_js_requests(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    _open_home(page, coachboard_url)
    assert _calls(page) == [], Counter(_calls(page))
    expect(page.locator('#overview')).to_be_visible()
    assert page.cb_errors == []


# --- 2. first open of each section --------------------------------------------

@pytest.mark.parametrize('section', sorted(SECTIONS))
def test_first_open_fetches_exactly_its_own_datasets(make_page, coachboard_url, section):
    page = make_page()
    _open_home(page, coachboard_url)
    assert _calls(page) == []

    _go(page, section)
    _assert_rendered(page, section)
    page.wait_for_timeout(800)

    endpoints = SECTIONS[section][0]
    calls = Counter(_calls(page))
    assert set(calls) == endpoints, f'{section}: main.js fetched {dict(calls)}, expected {endpoints}'
    assert all(n == 1 for n in calls.values()), f'{section}: repeated requests {dict(calls)}'
    assert page.locator(f'#{section} [data-cb-load-error]').count() == 0
    assert page.cb_errors == []


# --- 3. every way in -------------------------------------------------------------

def test_desktop_top_navigation_opens_roster(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    page.locator('.coach-primary-nav [data-cb-section="roster"]').click()
    expect(page.locator('#roster')).to_be_visible(timeout=15_000)
    _assert_rendered(page, 'roster')
    assert set(_calls(page)) == SECTIONS['roster'][0]
    assert page.cb_errors == []


def test_desktop_more_menu_opens_rotations(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    page.locator('.navbar .dropdown-toggle', has_text='More').first.click()
    page.locator('a.dropdown-item[href$="#rotations"]').first.click()
    expect(page.locator('#rotations')).to_be_visible(timeout=15_000)
    _assert_rendered(page, 'rotations')
    assert set(_calls(page)) == SECTIONS['rotations'][0]
    assert page.cb_errors == []


def test_desktop_legacy_tab_strip_opens_signs(make_page, coachboard_url):
    """Bootstrap's own tab lifecycle -- what the Roster <-> Development
    cross-links use."""
    page = make_page()
    _open_home(page, coachboard_url)
    page.evaluate("""() => document.querySelector('#mainTabsDesktop a[href="#signs"]').click()""")
    expect(page.locator('#signs')).to_be_visible(timeout=15_000)
    _assert_rendered(page, 'signs')
    assert set(_calls(page)) == SECTIONS['signs'][0]
    assert page.cb_errors == []


def test_roster_cross_link_opens_development_for_that_player(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    _go(page, 'roster')
    _assert_rendered(page, 'roster', enhancer=False)
    card = page.locator('#roster-cards-container .player-card').nth(1)
    name = card.locator('.cb-roster-name').inner_text().strip()
    card.locator('.cb-roster-player-summary').click()
    card.locator('.open-player-development').click()
    expect(page.locator('#player_development')).to_be_visible(timeout=15_000)
    expect(page.locator('#dev-player-list .cb-dev-player.active')).to_contain_text(name, timeout=15_000)
    assert Counter(_calls(page)) == Counter({'/api/session_data': 1, '/api/roster': 1,
                                            '/api/player_development': 1})
    assert page.cb_errors == []


def test_phone_bottom_bar_opens_roster_and_practice(make_page, coachboard_url):
    page = make_page(PHONE)
    _open_home(page, coachboard_url)
    page.locator('#cb-global-mobile-nav [data-cb-mobile-section="roster"]').click()
    expect(page.locator('#roster')).to_be_visible(timeout=15_000)
    _assert_rendered(page, 'roster')
    page.locator('#cb-global-mobile-nav [data-cb-mobile-section="practice_plan"]').click()
    expect(page.locator('#practice_plan')).to_be_visible(timeout=15_000)
    _assert_rendered(page, 'practice_plan')
    assert Counter(_calls(page)) == Counter({'/api/session_data': 1, '/api/roster': 1,
                                            '/api/practice_plans': 1})
    assert page.cb_errors == []


@pytest.mark.parametrize('section', ['rotations'])
def test_phone_first_open_is_decorated_by_its_enhancer(make_page, coachboard_url, section):
    """Phones switch panes without Bootstrap events, so season_management_v2.js
    sees the new list only through its observers on the containers main.js
    renders into."""
    page = make_page(PHONE)
    _open_home(page, coachboard_url)
    _go(page, section)
    _assert_rendered(page, section)
    assert set(_calls(page)) == SECTIONS[section][0]
    assert page.cb_errors == []


def test_phone_more_pane_opens_lineups(make_page, coachboard_url):
    page = make_page(PHONE)
    _open_home(page, coachboard_url)
    page.locator('#cb-global-mobile-nav [data-cb-mobile-section="more"]').click()
    link = page.locator('#more a[href$="#lineups"]').first
    expect(link).to_be_visible(timeout=15_000)
    assert _calls(page) == []                      # More itself loads nothing
    link.click()
    expect(page.locator('#lineups')).to_be_visible(timeout=15_000)
    _assert_rendered(page, 'lineups')
    assert set(_calls(page)) == SECTIONS['lineups'][0]
    assert page.cb_errors == []


# --- 4. direct /#hash loads -------------------------------------------------------

@pytest.mark.parametrize('section,viewport', [
    ('roster', DESKTOP), ('rotations', DESKTOP), ('signs', DESKTOP), ('roster', PHONE),
], ids=['roster-desktop', 'rotations-desktop', 'signs-desktop', 'roster-phone'])
def test_direct_hash_load(make_page, coachboard_url, section, viewport):
    page = make_page(viewport)
    _login(page, coachboard_url)
    # From another page, as a bookmark would: going from /#overview straight to
    # /#roster would only be a same-document fragment change.
    page.goto(f'{coachboard_url}/pitching')
    page.wait_for_load_state('networkidle')      # leave nothing of its own in flight
    page.evaluate('() => { window.__cbSameDocument = true; }')
    page.goto(f'{coachboard_url}/#{section}')
    page.wait_for_load_state('load')
    assert page.evaluate('window.__cbSameDocument') is None, 'not a fresh document load'
    expect(page.locator(f'#{section}')).to_be_visible(timeout=15_000)
    _assert_rendered(page, section)
    # The desktop Roster pre-paint hides the workspace until real cards exist.
    page.wait_for_function("!document.documentElement.classList.contains('cb-desktop-workspace-boot')",
                           timeout=5_000)
    page.wait_for_timeout(800)

    assert set(_calls(page)) == SECTIONS[section][0], Counter(_calls(page))
    if section == 'roster':
        assert page.evaluate('window.__cbRosterStates') == [], (
            'the Roster list showed something other than real cards')
    assert page.cb_errors == []


# --- 5. load once, share in-flight work ------------------------------------------

def test_reopening_a_loaded_section_fetches_nothing(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    _go(page, 'roster')
    _assert_rendered(page, 'roster')
    _go(page, 'overview')
    _go(page, 'roster')
    _go(page, 'rotations')
    _assert_rendered(page, 'rotations')
    _go(page, 'roster')
    page.wait_for_timeout(1000)
    assert Counter(_calls(page)) == Counter({'/api/session_data': 1, '/api/roster': 1,
                                            '/api/rotations': 1})
    assert page.cb_errors == []


def test_sections_opened_together_share_their_common_requests(make_page, coachboard_url):
    page = make_page(api_delay_ms=400)
    _open_home(page, coachboard_url, settle_ms=4000)
    # Roster, Development and Coach Notes all need session_data and roster.
    page.evaluate("""() => {
      location.hash = '#roster';
      setTimeout(() => { location.hash = '#player_development'; }, 20);
      setTimeout(() => { location.hash = '#collaboration'; }, 40);
      setTimeout(() => { location.hash = '#roster'; }, 60);
    }""")
    _assert_rendered(page, 'roster')
    _go(page, 'player_development')
    _assert_rendered(page, 'player_development')
    _go(page, 'collaboration')
    _assert_rendered(page, 'collaboration')
    page.wait_for_timeout(1500)
    assert Counter(_calls(page)) == Counter({'/api/session_data': 1, '/api/roster': 1,
                                            '/api/player_development': 1,
                                            '/api/collaboration_notes': 1})
    assert page.cb_errors == []


# --- 6. socket events before a section has loaded -------------------------------

def test_roster_change_before_roster_loads(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    name = f'Early Ellis {uuid.uuid4().hex[:4]}'
    _add_player(page, coachboard_url, name)          # data_updated
    page.wait_for_timeout(1500)
    assert _calls(page) == []
    assert page.cb_errors == []

    _go(page, 'roster')
    _assert_rendered(page, 'roster')
    expect(page.locator('#roster-cards-container .cb-roster-name', has_text=name)).to_have_count(1)


def test_rotation_change_before_rotations_load(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    title = f'Early Template {uuid.uuid4().hex[:4]}'
    _add_template(page, coachboard_url, title)       # rotation_save + data_updated
    page.wait_for_timeout(1500)
    assert _calls(page) == []
    assert page.cb_errors == []

    _go(page, 'rotations')
    _assert_rendered(page, 'rotations')
    assert title in _rotation_titles(page)


def test_game_change_before_anything_loads(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    response = page.request.post(f'{coachboard_url}/add_game', form={
        'game_date': '2031-08-01', 'game_opponent': f'Early {uuid.uuid4().hex[:4]}',
        'game_start_time': '10:00', 'game_location': 'Field', 'game_notes': ''})
    assert response.status in (200, 302)
    page.wait_for_timeout(1500)
    assert _calls(page) == []
    assert page.cb_errors == []


def test_rotation_save_alone_before_rotations_load(make_page, coachboard_url):
    """Saving a game's rotation emits rotation_save with no data_updated after
    it (gameday.py); on its own it must not stand in for a load."""
    page = make_page()
    _open_home(page, coachboard_url)
    assert _fire(page, 'rotation_save', {'rotation': {'id': 1, 'title': 'Six Inning Rotation'}}) == []
    page.wait_for_timeout(500)
    assert _calls(page) == []

    _go(page, 'rotations')
    _assert_rendered(page, 'rotations')
    assert _calls(page) == ['/api/rotations']
    assert 'Six Inning Rotation' in _rotation_titles(page)
    assert page.cb_errors == []


#: One of every event main.js listens for. Several are never emitted by the
#: server today (roster_*, game_*, rotation_delete, dev_focus_*, notes/plans/
#: signs/stats_update); they must be safe anyway.
GHOST_ID = 987654
SOCKET_EVENTS = [
    ('roster_add', {'player': {'id': GHOST_ID, 'name': 'Ghost Player', 'number': '0'}}),
    ('roster_update', {'player': {'id': GHOST_ID, 'name': 'Ghost Player'}}),
    ('player_order_update', {'order': ['Ghost Player']}),
    ('roster_delete', {'player_id': GHOST_ID}),
    ('game_add', {'game': {'id': GHOST_ID, 'date': '2031-01-01', 'opponent': 'Ghosts'}}),
    ('game_update', {'game': {'id': GHOST_ID, 'date': '2031-01-01', 'opponent': 'Ghosts'}}),
    ('game_delete', {'game_id': GHOST_ID}),
    ('lineup_add', {'lineup': {'id': GHOST_ID, 'title': 'Ghost Lineup', 'lineup_positions': []}}),
    ('lineup_update', {'lineup': {'id': GHOST_ID, 'title': 'Ghost Lineup', 'lineup_positions': []}}),
    ('lineup_delete', {'lineup_id': GHOST_ID}),
    ('rotation_save', {'rotation': {'id': GHOST_ID, 'title': 'Ghost Rotation'}}),
    ('rotation_delete', {'rotation_id': GHOST_ID}),
    ('dev_focus_add', {'player_name': 'Ghost Player', 'focus': {'id': GHOST_ID}}),
    ('dev_focus_update', {'player_name': 'Ghost Player', 'focus': {'id': GHOST_ID}}),
    ('dev_focus_delete', {'player_name': 'Ghost Player', 'focus_id': GHOST_ID}),
    ('pitching_update', None),
    ('scouting_update', None),
    ('notes_update', None),
    ('plans_update', None),
    ('signs_update', None),
    ('stats_update', None),
    ('data_updated', None),
]


def test_every_socket_event_before_load_is_safe_and_invents_nothing(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    thrown = {event: errors for event, payload in SOCKET_EVENTS
              if (errors := _fire(page, event, payload))}
    page.wait_for_timeout(1000)
    assert thrown == {}
    assert _calls(page) == [], Counter(_calls(page))

    for section in ('roster', 'lineups', 'rotations'):
        _go(page, section)
        _assert_rendered(page, section, enhancer=False)
    assert 'Ghost Player' not in _roster_names(page)
    assert page.locator('#lineupsAccordion', has_text='Ghost Lineup').count() == 0
    assert 'Ghost Rotation' not in _rotation_titles(page)
    assert page.cb_errors == []


# --- 7. socket events after a section has loaded --------------------------------

def test_roster_change_after_roster_loaded_refreshes_it(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    _go(page, 'roster')
    _assert_rendered(page, 'roster')
    name = f'Late Logan {uuid.uuid4().hex[:4]}'
    _add_player(page, coachboard_url, name)
    expect(page.locator('#roster-cards-container .cb-roster-name', has_text=name)).to_have_count(1, timeout=15_000)
    assert page.cb_errors == []


def test_rotation_change_after_rotations_loaded_refreshes_them(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    _go(page, 'rotations')
    _assert_rendered(page, 'rotations')
    title = f'Late Template {uuid.uuid4().hex[:4]}'
    _add_template(page, coachboard_url, title)
    page.wait_for_function(
        """title => [...document.querySelectorAll('#rotationsAccordion .accordion-button strong')]
                     .some(s => s.textContent.trim() === title)""", arg=title, timeout=15_000)
    assert page.cb_errors == []


def test_change_to_a_loaded_hidden_section_shows_on_next_open(make_page, coachboard_url):
    page = make_page()
    _open_home(page, coachboard_url)
    _go(page, 'roster')
    _assert_rendered(page, 'roster')
    _go(page, 'overview')
    before = Counter(_calls(page))

    name = f'Hidden Harper {uuid.uuid4().hex[:4]}'
    _add_player(page, coachboard_url, name)
    page.wait_for_timeout(1500)
    assert Counter(_calls(page)) == before, 'a hidden section was refetched while Home was showing'

    _go(page, 'roster')
    expect(page.locator('#roster-cards-container .cb-roster-name', has_text=name)).to_have_count(1, timeout=15_000)
    assert page.cb_errors == []


def test_change_while_the_first_load_is_in_flight_is_not_lost(make_page, coachboard_url):
    """The roster request leaves before the server changes and is answered
    after the change's socket event: that answer is out of date."""
    page = make_page()
    _open_home(page, coachboard_url)
    page.evaluate("() => Object.assign(window.__cbHold, {path: '/api/roster', ms: 2500})")
    page.evaluate("() => { location.hash = '#roster'; }")
    page.wait_for_function(
        "window.__cbApi.some(c => c.path === '/api/roster' && c.by === 'main.js')", timeout=5_000)
    page.wait_for_timeout(300)

    name = f'Midflight Morgan {uuid.uuid4().hex[:4]}'
    _add_player(page, coachboard_url, name)
    page.wait_for_timeout(300)
    page.evaluate("() => { window.__cbHold.path = null; }")

    expect(page.locator('#roster-cards-container .cb-roster-name', has_text=name)).to_have_count(1, timeout=15_000)
    assert _calls(page).count('/api/roster') == 2
    assert page.cb_errors == []


def test_lineup_delta_after_lineups_loaded(make_page, coachboard_url):
    """lineup_add is the one delta event the server really emits for Home."""
    page = make_page()
    _open_home(page, coachboard_url)
    _go(page, 'lineups')
    _assert_rendered(page, 'lineups')
    errors = _fire(page, 'lineup_add', {'lineup': {'id': GHOST_ID + 1, 'title': 'Delta Lineup',
                                                   'lineup_positions': ['A'], 'associated_game_id': None}})
    assert errors == []
    expect(page.locator('#lineupsAccordion', has_text='Delta Lineup')).to_have_count(1)
    assert page.cb_errors == []


# --- 8. a failed first load ------------------------------------------------------

def test_failed_first_open_is_contained_and_retryable(make_page, coachboard_url):
    page = make_page()
    _fail(page, '/api/signs')
    _open_home(page, coachboard_url)

    _go(page, 'signs')
    notice = page.locator('#signs > [data-cb-load-error="signs"]')
    expect(notice).to_be_visible(timeout=15_000)
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_have_count(1)
    assert page.locator('[data-cb-load-error]').count() == 1

    _go(page, 'scouting_list')
    _assert_rendered(page, 'scouting_list')
    _go(page, 'overview')
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_be_visible()

    # Reopening while the endpoint still fails tries again; it is not "loaded".
    _go(page, 'signs')
    page.wait_for_function("window.__cbApi.filter(c => c.path === '/api/signs').length >= 2", timeout=15_000)
    expect(notice).to_be_visible()

    _recover(page, '/api/signs')
    notice.get_by_role('button', name='Try again').click()
    _assert_rendered(page, 'signs')
    expect(notice).to_have_count(0)
    assert _calls(page).count('/api/signs') == 3
    assert page.locator('[data-cb-load-error]').count() == 0
    assert page.cb_errors == []


# --- 9. the legacy overview is still a fallback ----------------------------------

def test_legacy_overview_loads_its_data_when_home_dashboard_is_missing(make_page, coachboard_url):
    page = make_page(blocked=('/static/js/home_dashboard.js',))
    _login(page, coachboard_url)
    page.goto(f'{coachboard_url}/')
    page.wait_for_load_state('load')
    container = page.locator('#overview-content-container')
    expect(container).to_contain_text('Next Game', timeout=15_000)
    expect(container).to_contain_text('Pitcher Availability')
    assert '/api/overview_data' in _calls(page)
    assert page.cb_errors == []
