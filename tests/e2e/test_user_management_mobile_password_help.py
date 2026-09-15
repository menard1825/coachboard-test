"""Mobile regression coverage for the User Management password-help modal."""

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
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def test_password_help_modal_is_tappable_after_manage_handoff_on_phone(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/admin/users')

    row = page.locator('.user-row[data-username="playwright-assistant"]').first
    expect(row).to_be_visible()
    row.get_by_role('button', name='Manage').click()

    manage_modal = page.locator('#editUserModal-playwright-assistant')
    expect(manage_modal).to_be_visible()
    manage_modal.get_by_role('button', name='Password Help').click()

    reset_modal = page.locator('#resetPasswordModal-playwright-assistant')
    expect(manage_modal).to_be_hidden(timeout=5_000)
    expect(reset_modal).to_be_visible(timeout=5_000)

    # The reset modal is deliberately moved to body so a Bootstrap backdrop
    # cannot cover it through an ancestor stacking context on iOS/WebKit.
    assert reset_modal.evaluate('el => el.parentElement === document.body') is True

    create_link = reset_modal.get_by_role('button', name='Create Reset Link')
    expect(create_link).to_be_visible()
    expect(create_link).to_be_enabled()

    # trial=True runs Playwright's real actionability checks without submitting
    # the form. It fails if a leftover/invisible backdrop intercepts the tap.
    create_link.click(trial=True)

    reset_modal.get_by_role('button', name='Cancel').click()
    expect(reset_modal).to_be_hidden(timeout=5_000)
