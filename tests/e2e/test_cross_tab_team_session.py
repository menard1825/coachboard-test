"""Regression coverage for shared team-session state across browser tabs."""

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
    page.goto(f'{coachboard_url}/logout')
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def test_team_switch_remains_authoritative_across_two_tabs(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    second_tab = page.context.new_page()
    second_tab.goto(coachboard_url)

    # The seeded login starts on team 1. Switch from the second tab to team 2.
    second_tab.goto(f'{coachboard_url}/switch_team/2')
    expect(second_tab.locator('body')).to_contain_text('Other Team')

    # The first tab was opened before the switch. A request from that older tab
    # must use the newly selected shared session rather than restoring team 1.
    page.goto(coachboard_url)
    expect(page.locator('body')).to_contain_text('Other Team')

    # Make another ordinary request from the first tab, then verify the second tab
    # still sees team 2. This protects against stale-request cookie refreshes.
    page.reload()
    second_tab.reload()
    expect(second_tab.locator('body')).to_contain_text('Other Team')

    # Switching back in either tab must immediately become authoritative for both.
    page.goto(f'{coachboard_url}/switch_team/1')
    expect(page.locator('body')).to_contain_text('Playwright Prospects')
    second_tab.reload()
    expect(second_tab.locator('body')).to_contain_text('Playwright Prospects')
