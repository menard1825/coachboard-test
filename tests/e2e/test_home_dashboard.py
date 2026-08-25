import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#overview)?$'))


def test_coach_lands_on_operational_home(page: Page, coachboard_url: str):
    login(page, coachboard_url)

    dashboard = page.locator('.cb-home-dashboard')
    expect(dashboard).to_be_visible(timeout=15_000)
    expect(dashboard).to_contain_text('CoachBoard Home')
    expect(dashboard).to_contain_text('Next game')
    expect(dashboard).to_contain_text(re.compile(r'(?:Browser Bears|No upcoming game)'))
    expect(dashboard).to_contain_text('Needs Attention')
    expect(dashboard).to_contain_text('Next practice')
    expect(dashboard).to_contain_text('Communication')
    expect(dashboard).to_contain_text('Quick Actions')

    home_nav = page.locator('.coach-primary-nav [data-cb-section="overview"]')
    expect(home_nav).to_be_visible()
    expect(home_nav).to_have_text(re.compile(r'Home'))
    expect(home_nav).to_have_class(re.compile(r'\bactive\b'))


def test_home_is_first_mobile_destination(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)

    expect(page.locator('.cb-home-dashboard')).to_be_visible(timeout=15_000)
    bottom_nav = page.locator('#cb-global-mobile-nav ul')
    expect(bottom_nav).to_be_visible()
    items = bottom_nav.locator('a.nav-link')
    expect(items).to_have_count(5)
    expect(items.nth(0)).to_contain_text('Home')
    expect(items.nth(0)).to_have_attribute('href', '#overview')
    expect(items.nth(1)).to_contain_text('Game Day')
    expect(items.nth(1)).to_have_attribute('href', '/game-day')
    expect(items.nth(2)).to_contain_text('Roster')
    expect(items.nth(3)).to_contain_text('Practice')
    expect(items.nth(4)).to_contain_text('More')

    items.nth(4).click()
    expect(page).to_have_url(re.compile(r'#more$'))
    expect(page.locator('#more .cb-mobile-more-card')).to_contain_text('Development')


def test_mobile_workspace_navigation_stays_stable_under_repeated_taps(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    expect(page.locator('.cb-home-dashboard')).to_be_visible(timeout=15_000)

    # Home, Roster, Practice and More are same-document workspaces. Game Day is
    # intentionally a dedicated route so it can own its game-focused shell.
    page.wait_for_timeout(400)
    bottom_nav = page.locator('#cb-global-mobile-nav ul')
    same_page_items = bottom_nav.locator('a[href^="#"]')
    expect(same_page_items).to_have_count(4)
    for index in range(4):
        expect(same_page_items.nth(index)).not_to_have_attribute('data-bs-toggle', 'tab')

    expected = {
        'Home': '#overview',
        'Roster': '#roster',
        'Practice': '#practice_plan',
        'More': '#more',
    }
    for label in ('Roster', 'Practice', 'More', 'Home', 'Roster', 'More'):
        bottom_nav.get_by_text(label, exact=True).click()
        target = expected[label]
        expect(page.locator(target)).to_have_class(re.compile(r'\bactive\b'))
        expect(page.locator('#mainTabContent > .tab-pane.active')).to_have_count(1)
        expect(bottom_nav.locator('a.nav-link.active span')).to_have_text(label)
        if label == 'Home':
            expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?$'))
        else:
            expect(page).to_have_url(re.compile(re.escape(target) + r'$'))

    page.locator('#more').get_by_text('Development', exact=True).click()
    expect(page.locator('#player_development')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('#mainTabContent > .tab-pane.active')).to_have_count(1)
    expect(bottom_nav.locator('a.nav-link.active span')).to_have_text('More')

    bottom_nav.get_by_text('Home', exact=True).click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?$'))
    expect(page.locator('#overview')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('#mainTabContent > .tab-pane.active')).to_have_count(1)

    # Game Day intentionally performs a real route transition rather than
    # activating the retired #games dashboard pane.
    bottom_nav.get_by_text('Game Day', exact=True).click()
    expect(page).to_have_url(re.compile(r'/game-day$'))
    expect(page.get_by_role('heading', name='Game Day')).to_be_visible()

    page.go_back()
    expect(page.locator('.cb-home-dashboard')).to_be_visible(timeout=15_000)
    expect(page.locator('#overview')).to_have_class(re.compile(r'\bactive\b'))


def test_game_day_mobile_navigation_keeps_home(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/game-day')

    bottom_nav = page.locator('#cb-global-mobile-nav ul')
    expect(bottom_nav).to_be_visible()
    items = bottom_nav.locator('a.nav-link')
    expect(items).to_have_count(5)
    expect(items.nth(0)).to_contain_text('Home')
    expect(items.nth(0)).to_have_attribute('href', '/')
    expect(items.nth(1)).to_contain_text('Game Day')
    expect(items.nth(1)).to_have_class(re.compile(r'\bactive\b'))
    expect(items.nth(2)).to_contain_text('Roster')
    expect(items.nth(3)).to_contain_text('Practice')
    expect(items.nth(4)).to_contain_text('More')

    items.nth(0).click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#overview)?$'))
    expect(page.locator('.cb-home-dashboard')).to_be_visible(timeout=15_000)
