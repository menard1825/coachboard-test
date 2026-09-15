"""iPad coverage for the scan-first Pitching dashboard."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Browser, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


def login(page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    identity = page.get_by_label('Username or email')
    if identity.count() == 0:
        page.goto(f'{coachboard_url}/logout')
        expect(page).to_have_url(re.compile(r'/login$'))
        identity = page.get_by_label('Username or email')
    identity.fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def test_pitching_ipad_uses_compact_decision_board(browser: Browser, coachboard_url: str):
    """Touch iPads should not render the tall desktop pitcher-card wall."""
    context = browser.new_context(
        viewport={'width': 1366, 'height': 1024},
        has_touch=True,
        is_mobile=False,
    )
    page = context.new_page()
    try:
        login(page, coachboard_url)
        page.goto(f'{coachboard_url}/pitching', wait_until='domcontentloaded')

        body = page.locator('body')
        expect(body).to_have_class(re.compile(r'cb-pitch-dugout-tablet'), timeout=15_000)

        cards = page.locator('#pitcherAvailabilityCard .cb-pitcher-card')
        expect(cards).not_to_have_count(0)
        expect(cards.first.locator('.cb-pitcher-details-toggle')).to_be_visible(timeout=15_000)
        expect(cards.first.locator('.cb-pitch-metrics')).to_be_hidden()

        eligible = page.locator(
            '#pitcherAvailabilityCard .cb-pitcher-card[data-availability-group="eligible"]'
        )
        if eligible.count():
            rollup = page.locator('#cb-ready-pitcher-rollup')
            expect(rollup).to_be_visible()
            expect(rollup.locator('.cb-ready-rollup-name')).to_have_count(eligible.count())
            expect(eligible.first).to_be_hidden()

            rollup.locator('.cb-ready-rollup-toggle').click()
            expect(eligible.first).to_be_visible()
            expect(eligible.first.locator('.cb-pitch-metrics')).to_be_hidden()

            eligible.first.locator('.cb-pitcher-details-toggle').click()
            expect(eligible.first.locator('.cb-pitch-metrics')).to_be_visible()

        assert page.evaluate(
            'document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2'
        )
    finally:
        context.close()
