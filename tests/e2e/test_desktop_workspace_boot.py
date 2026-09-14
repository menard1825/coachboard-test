"""Desktop cross-page workspace first-paint coverage."""

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

    held_roster_requests = []

    def hold_roster(route):
        held_roster_requests.append(route)
        # Intentionally leave this request unresolved so the browser can stay
        # on the real intermediate frame while the test inspects first paint.

    page.route('**/api/roster', hold_roster)

    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('.coach-primary-nav [data-cb-section="roster"]').click()

    expect(page).to_have_url(re.compile(r'/#roster$'))

    # The pre-paint marker is created in <head>, before dashboard markup can be
    # rendered. This is what prevents a human-visible old/unfinished frame.
    expect(page.locator('html')).to_have_class(re.compile(r'\bcb-desktop-workspace-boot\b'))
    expect(page.locator('html')).to_have_attribute('data-cb-workspace-boot', 'roster')

    for _ in range(20):
        if held_roster_requests:
            break
        page.wait_for_timeout(25)
    assert held_roster_requests, 'Roster API request was not intercepted'

    expect(page.locator('main.container-fluid')).to_have_attribute('data-cb-workspace-loading', 'Loading Roster…')

    visibility = page.locator('#mainTabContent').evaluate('el => getComputedStyle(el).visibility')
    assert visibility == 'hidden'

    # The retired dashboard tab strip must never be the thing a coach sees while
    # Roster is loading. It remains in the DOM only for legacy controller hooks.
    legacy_tabs_display = page.locator('#mainTabsDesktop').evaluate('el => getComputedStyle(el).display')
    assert legacy_tabs_display == 'none'

    held_roster_requests.pop(0).continue_()

    expect(page.locator('.cb-roster-player')).not_to_have_count(0, timeout=15_000)
    expect(page.locator('html')).not_to_have_class(re.compile(r'\bcb-desktop-workspace-boot\b'), timeout=15_000)
    expect(page.locator('#roster')).to_have_class(re.compile(r'\bactive\b'))
    expect(page.locator('.coach-primary-nav [data-cb-section="roster"]')).to_have_class(re.compile(r'\bactive\b'))

    final_visibility = page.locator('#mainTabContent').evaluate('el => getComputedStyle(el).visibility')
    assert final_visibility == 'visible'
    final_legacy_tabs_display = page.locator('#mainTabsDesktop').evaluate('el => getComputedStyle(el).display')
    assert final_legacy_tabs_display == 'none'
