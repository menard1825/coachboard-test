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


def test_pitching_dashboard_is_fast_to_scan_on_mobile(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/pitching', wait_until='domcontentloaded')

    expect(page.locator('h3').filter(has_text='Pitching')).to_be_visible()
    cards = page.locator('.cb-pitcher-card')
    expect(cards).not_to_have_count(0, timeout=15_000)
    expect(page.locator('.cb-pitch-counts')).to_be_visible()
    expect(cards.first).to_contain_text('Competition eligibility')
    expect(cards.first).to_contain_text('Arm care')
    expect(cards.first.locator('.pitch-arm-care-slot')).not_to_contain_text('Loading', timeout=15_000)

    status_card = page.locator('.card').filter(has=page.locator('h5', has_text='Pitcher Availability')).first
    expect(status_card.locator('table')).to_be_hidden()

    history = page.locator('.card').filter(has=page.locator('h5', has_text='Recent Throwing History')).first
    if history.locator('.list-group-item [data-outing-id]').count():
        expect(history.locator('#cbPitchHistoryPlayer')).to_be_visible()
        expect(history.locator('#cbPitchHistoryRange')).to_be_visible()
        expect(history.locator('#cbPitchHistoryCount')).to_be_visible()

    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2')


def test_pitch_target_save_updates_without_full_page_reload(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/pitching', wait_until='domcontentloaded')
    expect(page.locator('.cb-pitcher-card')).not_to_have_count(0, timeout=15_000)

    marker = 'pitching-target-no-reload-marker'
    page.evaluate('(value) => { window.__pitchingTargetMarker = value; }', marker)
    page.get_by_role('button', name='Set Pitch Target').click()
    expect(page.locator('#coachTargetModal')).to_be_visible()
    page.locator('#targetPlayerInput').select_option(label='Pitcher Pat')
    page.locator('#targetScopeInput').select_option('day')
    page.locator('#targetPitchesInput').fill('25')
    page.locator('#targetReasonInput').fill('Browser no-reload check')
    page.locator('#saveTargetBtn').click()
    expect(page.locator('#coachTargetModal')).to_be_hidden(timeout=10_000)
    assert page.evaluate('window.__pitchingTargetMarker') == marker

    pitcher_card = page.locator('.cb-pitcher-card').filter(has_text='Pitcher Pat').first
    expect(pitcher_card).to_contain_text('25', timeout=10_000)

    pitcher_card.locator('.open-target-modal').click()
    expect(page.locator('#coachTargetModal')).to_be_visible()
    page.locator('#targetPitchesInput').fill('')
    page.locator('#targetReasonInput').fill('')
    page.locator('#saveTargetBtn').click()
    expect(page.locator('#coachTargetModal')).to_be_hidden(timeout=10_000)
    assert page.evaluate('window.__pitchingTargetMarker') == marker


def test_game_planning_uses_same_pitcher_decision_cards(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/game/1', wait_until='domcontentloaded')

    availability = page.locator('#pitcher-availability-card')
    expect(availability).to_be_visible(timeout=15_000)
    expect(availability).to_have_attribute('data-cb-pitching-owner', 'game-setup', timeout=15_000)
    cards = availability.locator('.gpa-card')
    expect(cards).not_to_have_count(0, timeout=15_000)
    expect(cards.first).to_contain_text('Competition eligibility')
    expect(cards.first).to_contain_text('Arm care')
    expect(cards.first).to_contain_text('Game plan')
    expect(availability).to_contain_text('Competition rules needed')
    expect(availability).not_to_contain_text('Eligible')
    expect(availability.locator('table')).to_be_hidden()
    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2')
