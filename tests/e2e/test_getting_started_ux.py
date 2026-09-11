"""Browser coverage for backward-safe guided setup."""

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
        expect(page).to_have_url(re.compile(r'/login$'))
        identity = page.get_by_label('Username or email')
    identity.fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#overview)?$'))


def test_existing_team_is_not_prompted_but_can_open_getting_started(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/#overview', wait_until='domcontentloaded')

    expect(page.locator('.cb-home-dashboard')).to_be_visible()
    # The seeded Playwright team intentionally has no TeamSetupState row. It is
    # treated as ready and must never receive an automatic onboarding card.
    expect(page.locator('.cb-home-setup-card')).to_have_count(0)

    page.goto(f'{coachboard_url}/#more', wait_until='domcontentloaded')
    getting_started = page.locator('#more [data-cb-getting-started-link]')
    expect(getting_started).to_be_visible()
    expect(getting_started).to_contain_text('Getting Started')
    getting_started.click()

    expect(page).to_have_url(re.compile(r'/getting-started$'))
    expect(page.get_by_role('heading', name='Your Team Is Ready')).to_be_visible()
    expect(page.get_by_text('Review or update your team setup at any time.')).to_be_visible()
    expect(page.get_by_text('Use the shortcuts below anytime to review or update your team settings and coaching setup.')).to_be_visible()
    expect(page.get_by_text(re.compile(r'guided setup was added', re.I))).to_have_count(0)
    expect(page.get_by_text(re.compile(r'already in CoachBoard', re.I))).to_have_count(0)

    overflow = page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 1
