"""App-wide page, navigation, API, and responsive-layout coverage."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
ASSISTANT_USERNAME = 'playwright-assistant'
ASSISTANT_PASSWORD = 'playwright-assistant-password'


def login(page: Page, coachboard_url: str, username=TEST_USERNAME, password=TEST_PASSWORD):
    page.goto(f'{coachboard_url}/login')
    identity = page.get_by_label('Username or email')
    if identity.count() == 0:
        page.goto(f'{coachboard_url}/logout')
        expect(page).to_have_url(re.compile(r'/login$'))
        identity = page.get_by_label('Username or email')
    identity.fill(username)
    page.locator('#password').fill(password)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def assert_healthy_document(page: Page, coachboard_url: str, path: str, expected_text: str):
    response = page.goto(f'{coachboard_url}{path}', wait_until='domcontentloaded')
    assert response is not None, f'{path} did not return a document response'
    assert response.status < 500, f'{path} returned HTTP {response.status}'
    body_locator = page.locator('body')
    expect(body_locator).to_contain_text(
        re.compile(re.escape(expected_text), re.IGNORECASE),
        timeout=15_000,
    )
    body = body_locator.inner_text().strip()
    assert body, f'{path} rendered an empty page'
    assert 'Internal Server Error' not in body, f'{path} rendered an internal error'


def test_public_account_pages_and_protected_redirects(page: Page, coachboard_url: str):
    public_pages = [
        ('/login', 'Sign In'),
        ('/register', 'Create Account'),
        ('/forgot_password', 'Forgot'),
        ('/password_help/playwright-assistant', 'Password'),
    ]
    for path, expected_text in public_pages:
        assert_healthy_document(page, coachboard_url, path, expected_text)

    for path in ('/', '/game-day', '/pitching', '/admin/users', '/admin/settings'):
        page.goto(f'{coachboard_url}{path}')
        expect(page).to_have_url(re.compile(r'/login$'))


def test_every_authenticated_screen_renders(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    screens = [
        ('/', 'Playwright Prospects'),
        ('/game-day', 'Game Day'),
        ('/game/1', 'Browser Bears'),
        ('/game-day/1/report', 'Browser Bears'),
        ('/pitching', 'Pitching'),
        ('/rules', 'Pitching Rules'),
        ('/admin/users', 'User Management'),
        ('/admin/teams', 'Team Management'),
        ('/admin/settings', 'Team Settings'),
        ('/rotation-template/new', 'Rotation'),
        ('/rotation-template/2', 'Edit Rotation Template'),
        ('/starting-defense-template/new', 'Starting Defense'),
        ('/starting-defense-template/1', 'Edit Starting Defense'),
        ('/change_password', 'Password'),
    ]
    for path, expected_text in screens:
        assert_healthy_document(page, coachboard_url, path, expected_text)


def test_lineup_editor_is_unique_and_cancel_discards_mobile_draft(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)

    page.goto(coachboard_url)
    page.locator('#mainTabsDesktop [href="#lineups"]').evaluate(
        "el => bootstrap.Tab.getOrCreateInstance(el).show()"
    )
    page.locator('[data-bs-target="#lineup-collapse-1"]').click()
    edit_template = page.locator('[data-bs-target="#lineupEditorModal"][data-lineup-id="1"]').first
    edit_template.click()
    expect(page.locator('#lineupEditorModal')).to_be_visible()
    expect(page.locator('#lineup-order .list-group-item')).to_have_count(9)
    page.locator('#lineup-order .remove-player-btn').first.click()
    expect(page.locator('#lineup-order .list-group-item')).to_have_count(8)
    page.locator('#lineupEditorModal').get_by_role('button', name='Cancel').click()
    expect(page.locator('#lineupEditorModal')).to_be_hidden()

    edit_template.click()
    expect(page.locator('#lineup-order .list-group-item')).to_have_count(9)
    page.locator('#lineupEditorModal').get_by_role('button', name='Cancel').click()
    expect(page.locator('#lineupEditorModal')).to_be_hidden()

    page.goto(f'{coachboard_url}/game/1')
    expect(page.locator('#lineupEditorModal')).to_have_count(1)
    page.get_by_role('button', name='Edit Lineup').click()
    expect(page.locator('#lineupEditorModal')).to_be_visible()
    page.locator('#lineupTemplateSelect').select_option('template:1')
    page.locator('#applyLineupSourceBtn').click()
    expect(page.locator('#lineup-order .list-group-item')).to_have_count(9)
    page.locator('#rotateLineupBtn').click()
    expect(page.locator('#lineup-order .list-group-item').first).to_contain_text('Catcher Cole')
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#saveLineupBtn').click()

    game_data = page.request.get(f'{coachboard_url}/api/game_data/1').json()
    assert game_data['lineup']['lineup_player_ids'][0] == 2
    assert game_data['lineup']['lineup_positions'][0] == 'Catcher Cole'
    page.request.get(f'{coachboard_url}/delete_lineup/{game_data["lineup"]["id"]}')


def test_all_dashboard_data_services_return_team_scoped_data(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    endpoints = (
        '/api/session_data',
        '/api/overview_data',
        '/api/roster',
        '/api/lineups',
        '/api/pitching_data',
        '/api/scouting_list',
        '/api/rotations',
        '/api/games',
        '/api/collaboration_notes',
        '/api/practice_plans',
        '/api/player_development',
        '/api/signs',
        '/api/stats',
        '/api/stats-dashboard',
        '/api/game_data/1',
        '/api/game-day/1/readiness',
        '/api/game-day/1/pitching-rules',
        '/api/game-day/pitching-rule-options',
        '/api/team-game-settings',
        '/api/roster-pitching-profiles',
    )
    for endpoint in endpoints:
        response = page.request.get(f'{coachboard_url}{endpoint}')
        assert response.status == 200, f'{endpoint} returned HTTP {response.status}: {response.text()}'
        assert response.json() is not None, f'{endpoint} did not return JSON'

    roster = page.request.get(f'{coachboard_url}/api/roster').json()
    assert {player['name'] for player in roster} >= {'Pitcher Pat', 'Right Riley'}
    assert 'Private Player' not in {player['name'] for player in roster}


def test_every_home_dashboard_area_loads_seeded_content(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    page.goto(coachboard_url)

    areas = [
        ('overview', '#overview-content-container'),
        ('roster', '#roster-cards-container'),
        ('player_development', '#dev-player-list'),
        ('stats', '#stats-content-container'),
        ('lineups', '#lineupsAccordion'),
        ('rotations', '#rotationsAccordion'),
        ('scouting_list', '#scouting-list-container'),
        ('collaboration', '#team-notes-container'),
        ('practice_plan', '#practicePlanAccordion'),
        ('signs', '#signs-list-container'),
    ]
    for tab_name, container_selector in areas:
        tab = page.locator(f'#mainTabsDesktop [href="#{tab_name}"]')
        expect(tab).to_have_count(1)
        tab.evaluate("el => bootstrap.Tab.getOrCreateInstance(el).show()")
        expect(page.locator(f'#{tab_name}')).to_have_class(re.compile(r'\bactive\b'))
        container = page.locator(container_selector)
        expect(container).to_be_visible()
        expect(container).not_to_be_empty(timeout=15_000)


def test_mobile_navigation_reaches_every_primary_area(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(coachboard_url)

    bottom_nav = page.locator('nav.bottom-nav-fixed')
    expect(bottom_nav).to_be_visible()
    for label in ('Home', 'Game Day', 'Roster', 'Practice', 'More'):
        expect(bottom_nav.get_by_text(label, exact=True)).to_be_visible()

    bottom_nav.get_by_text('Home', exact=True).click()
    expect(page.locator('#overview')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('.cb-home-dashboard')).to_be_visible(timeout=15_000)

    bottom_nav.get_by_text('Roster', exact=True).click()
    expect(page.locator('#roster')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('#roster-cards-container')).to_contain_text('Pitcher Pat', timeout=15_000)

    bottom_nav.get_by_text('Practice', exact=True).click()
    expect(page.locator('#practice_plan')).to_have_class(re.compile(r'\bactive\b'))

    bottom_nav.get_by_text('More', exact=True).click()
    expect(page.locator('#more')).to_have_class(re.compile(r'\bactive\b'))
    for label in ('Development', 'Pitching', 'Schedule', 'Lineup Templates', 'Defensive Templates', 'Stats', 'Scouting', 'Coach Notes'):
        expect(page.locator('#more').get_by_text(label, exact=True)).to_be_visible()

    page.locator('#more').get_by_text('Development', exact=True).click()
    expect(page.locator('#player_development')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('#player_development > .cb-tab-intro')).to_have_count(0)
    expect(page.locator('#season-dev-summary-v2')).to_have_count(0)
    expect(page.locator('.cb-dev-mobile-picker')).to_be_visible()
    expect(page.locator('.cb-dev-player-card')).to_be_hidden()
    expect(page.locator('#player-dev-content')).to_contain_text('Individual development plan', timeout=15_000)


def test_coaching_workspaces_expose_new_primary_actions(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    page.goto(coachboard_url)

    expect(page.locator('#rosterPlayerCount')).not_to_have_text('0', timeout=15_000)
    expect(page.locator('.cb-roster-player')).not_to_have_count(0)
    page.locator('#mainTabsDesktop [href="#roster"]').evaluate(
        "el => bootstrap.Tab.getOrCreateInstance(el).show()"
    )
    expect(page.locator('#roster')).to_have_class(re.compile(r'\bactive\b'))
    first_player = page.locator('.cb-roster-player').first
    first_player.locator('.cb-roster-player-summary').click()
    first_player.get_by_role('button', name='Player Development').click()
    expect(page.locator('#player_development')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('.cb-dev-detail-head')).to_be_visible()
    expect(page.get_by_role('button', name='Add priority')).to_be_visible()

    page.locator('#mainTabsDesktop [href="#practice_plan"]').evaluate(
        "el => bootstrap.Tab.getOrCreateInstance(el).show()"
    )
    expect(page.locator('#practicePlanSummary')).to_be_visible()
    expect(page.locator('.cb-practice-plan')).not_to_have_count(0)
    page.locator('.cb-practice-plan-button').first.click()
    expect(page.get_by_role('button', name='Reuse on another date').first).to_be_visible()

    page.goto(f'{coachboard_url}/pitching')
    expect(page.get_by_text('Game-pitch targets are coaching plans, not rule limits.')).to_be_visible()
    page.get_by_role('button', name='Plan a target').click()
    expect(page.locator('#coachTargetModal')).to_be_visible()
    expect(page.locator('#targetScopeInput')).to_have_value('day')
    page.locator('#targetScopeInput').select_option('game')
    expect(page.locator('#targetGameField')).to_be_visible()



def test_user_management_mobile_cards_do_not_overlap(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/admin/users')

    table = page.locator('.cb-user-admin-table')
    expect(table).to_be_visible()

    role_cell = table.locator('td[data-label="Role"]:visible').first
    expect(role_cell).to_be_visible()
    mobile_layout = role_cell.evaluate(
        """cell => {
            const cellStyle = getComputedStyle(cell);
            const labelStyle = getComputedStyle(cell, '::before');
            return {
                display: cellStyle.display,
                gridColumns: cellStyle.gridTemplateColumns,
                labelDisplay: labelStyle.display,
                labelPosition: labelStyle.position,
            };
        }"""
    )
    assert mobile_layout['display'] == 'grid'
    assert mobile_layout['gridColumns'] != 'none'
    assert mobile_layout['labelDisplay'] == 'block'
    assert mobile_layout['labelPosition'] == 'static'

    coach_cell = table.locator('td[data-label="Username"]:visible').first
    coach_label = coach_cell.evaluate(
        "cell => getComputedStyle(cell, '::before').display"
    )
    assert coach_label == 'none'

    card_bounds = table.locator('tbody .user-row:visible').evaluate_all(
        """rows => rows.map(row => {
            const rect = row.getBoundingClientRect();
            return {left: rect.left, right: rect.right, viewport: innerWidth};
        })"""
    )
    assert card_bounds
    assert all(
        bounds['left'] >= -1 and bounds['right'] <= bounds['viewport'] + 1
        for bounds in card_bounds
    )


def test_role_and_team_boundaries_are_enforced(page: Page, coachboard_url: str):
    login(page, coachboard_url, ASSISTANT_USERNAME, ASSISTANT_PASSWORD)

    page.goto(f'{coachboard_url}/admin/settings')
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?$'))
    expect(page.locator('.cb-home-dashboard')).to_be_visible(timeout=15_000)
    expect(page.get_by_role('heading', name='Team Settings')).to_have_count(0)

    response = page.request.get(f'{coachboard_url}/api/game_data/2')
    assert response.status == 404
    assert 'Private Opponent' not in response.text()

    page.context.clear_cookies()
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/switch_team/2')
    expect(page.locator('.navbar-brand-text')).to_contain_text('Other Team')
    team_two_roster = page.evaluate(
        """async () => {
            const response = await fetch('/api/roster', {
                cache: 'no-store',
                credentials: 'same-origin',
            });
            if (!response.ok) {
                throw new Error(`Roster request failed with HTTP ${response.status}`);
            }
            return response.json();
        }"""
    )
    assert [player['name'] for player in team_two_roster] == ['Private Player']


def test_logout_ends_the_authenticated_session(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/logout')
    expect(page).to_have_url(re.compile(r'/login$'))
    response = page.request.get(f'{coachboard_url}/api/roster')
    assert response.status == 401