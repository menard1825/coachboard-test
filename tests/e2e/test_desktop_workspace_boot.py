"""Desktop cross-page workspace first-paint coverage."""

import os
import re
import time

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    identity = page.get_by_label('Username or email')
    if identity.count() == 0:
        page.goto(f'{coachboard_url}/logout')
        identity = page.get_by_label('Username or email')
    identity.fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def test_game_day_to_roster_hides_unfinished_roster_first_paint(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1440, 'height': 900})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/game-day', wait_until='domcontentloaded')
    expect(page.locator('.coach-primary-nav')).to_be_visible()

    def delay_roster(route):
        time.sleep(0.7)
        route.continue_()

    page.route('**/api/roster', delay_roster)

    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('.coach-primary-nav [data-cb-section="roster"]').click()

    expect(page).to_have_url(re.compile(r'/#roster$'))
    expect(page.locator('html')).to_have_class(re.compile(r'\bcb-desktop-workspace-boot\b'))
    expect(page.locator('main.container-fluid')).to_have_attribute('data-cb-workspace-loading', 'Loading Roster…')

    visibility = page.locator('#mainTabContent').evaluate('el => getComputedStyle(el).visibility')
    assert visibility == 'hidden'

    expect(page.locator('.cb-roster-player')).not_to_have_count(0, timeout=15_000)
    expect(page.locator('html')).not_to_have_class(re.compile(r'\bcb-desktop-workspace-boot\b'), timeout=15_000)
    expect(page.locator('#roster')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('.coach-primary-nav [data-cb-section="roster"]')).to_have_class(re.compile(r'\bactive\b'))

    final_visibility = page.locator('#mainTabContent').evaluate('el => getComputedStyle(el).visibility')
    assert final_visibility == 'visible'
