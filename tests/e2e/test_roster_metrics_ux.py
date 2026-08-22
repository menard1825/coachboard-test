"""Regression coverage for roster summary metrics on mobile."""

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
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def test_mobile_roster_metrics_show_overlapping_counts_clearly(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/#roster', wait_until='domcontentloaded')

    metrics = page.locator('#roster .cb-roster-metrics-v2')
    expect(metrics).to_be_visible()
    expect(page.locator('#roster-cards-container .cb-roster-player').first).to_be_visible()

    total = int(page.locator('#rosterPlayerCount').inner_text())
    pitchers = int(page.locator('#rosterPitcherCount').inner_text())
    profile_status = page.locator('#rosterProfileStatus')
    total_chip = page.locator('#rosterPlayerCount').locator('xpath=..')
    pitcher_chip = page.locator('#rosterPitcherCount').locator('xpath=..')

    expect(total_chip).to_contain_text(f'{total} total player')
    expect(pitcher_chip).to_contain_text(f'{pitchers} of {total}')
    expect(pitcher_chip).to_contain_text('pitcher')

    if profile_status.locator('strong').inner_text().strip().lower() == 'all':
        expect(profile_status).to_contain_text(f'All {total} profiles complete')
    else:
        incomplete = int(profile_status.locator('strong').inner_text())
        expect(profile_status).to_contain_text(f'{incomplete} of {total}')
        expect(profile_status).to_contain_text('profile')
        expect(profile_status).to_contain_text('incomplete')

    # These are overlapping roster attributes, not categories that should sum.
    expect(metrics).not_to_contain_text('profiles to finish')
    assert pitchers <= total

    layout = metrics.evaluate(
        """node => {
            const totalChip = node.querySelector('.cb-roster-total').getBoundingClientRect();
            const pitcherChip = node.querySelector('#rosterPitcherCount').parentElement.getBoundingClientRect();
            const profileChip = node.querySelector('#rosterProfileStatus').getBoundingClientRect();
            return {
                totalWidth: totalChip.width,
                pitcherWidth: pitcherChip.width,
                profileWidth: profileChip.width,
            };
        }"""
    )
    # The total occupies its own primary row while the overlapping attributes sit below it.
    assert layout['totalWidth'] > layout['pitcherWidth'] * 1.5
    assert abs(layout['pitcherWidth'] - layout['profileWidth']) <= 4
