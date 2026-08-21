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


def test_pitching_dashboard_is_stable_and_fast_to_scan_on_mobile(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/pitching', wait_until='domcontentloaded')

    expect(page.locator('h3').filter(has_text='Pitching')).to_be_visible()
    rule_strip = page.locator('#pitchingRuleStrip')
    expect(rule_strip).to_be_visible()
    cards = page.locator('.cb-pitcher-card')
    expect(cards).not_to_have_count(0)
    expect(page.locator('.cb-pitch-counts')).to_be_visible()
    expect(cards.first).to_contain_text('Competition Eligibility')
    expect(cards.first).to_contain_text('Arm Care')
    expect(cards.first.locator('.pitch-arm-care-slot')).not_to_contain_text('Loading', timeout=15_000)

    # Rules and arm care share one compact row on phones rather than consuming
    # two full-width cards before the coach reaches pitcher availability.
    rule_items = rule_strip.locator('.cb-pitch-rule-item')
    expect(rule_items).to_have_count(2)
    tops = rule_items.evaluate_all('items => items.map(item => Math.round(item.getBoundingClientRect().top))')
    assert abs(tops[0] - tops[1]) <= 2
    expect(rule_items.first.locator('small')).to_be_hidden()

    # The current dashboard is rendered as cards from first paint. The old
    # table->JavaScript-card replacement and injected duplicate summary are gone.
    status_card = page.locator('#pitcherAvailabilityCard')
    expect(status_card.locator('table')).to_have_count(0)
    expect(page.locator('.cb-pitch-source')).to_have_count(0)
    expect(page.locator('#pitchingDualRuleSummary')).to_have_count(0)

    # The seeded test team intentionally chooses competition rules per game.
    # The generic Pitching dashboard must not present that as official eligibility.
    expect(status_card).to_contain_text('Competition Rules Needed')
    expect(status_card).not_to_contain_text('Eligible Today\n1')

    # Mobile starts scan-first: official decision / next date and arm care stay
    # visible, while usage, workload, and target detail are collapsed.
    first_card = cards.first
    expect(first_card).to_have_attribute('data-mobile-expanded', 'false')
    details_button = first_card.locator('.cb-pitcher-details-toggle')
    expect(details_button).to_be_visible()
    expect(details_button).to_have_attribute('aria-expanded', 'false')
    expect(first_card.locator('.cb-pitch-metrics')).to_be_hidden()
    details_button.click()
    expect(details_button).to_have_attribute('aria-expanded', 'true')
    expect(first_card.locator('.cb-pitch-metrics')).to_be_visible()
    details_button.click()
    expect(first_card.locator('.cb-pitch-metrics')).to_be_hidden()

    # Availability summary cards are controls, not dead statistics. The seeded
    # team has no default competition rule, so every pitcher belongs to Review.
    summary_items = page.locator('.cb-pitch-summary-item[data-cb-pitch-filter]')
    expect(summary_items).to_have_count(3)
    review_filter = summary_items.filter(has_text='Needs Review')
    expect(review_filter).to_have_attribute('role', 'button')
    expect(review_filter).to_have_attribute('aria-disabled', None)
    review_filter.click()
    expect(review_filter).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.cb-pitch-filter-state')).to_be_visible()
    groups = page.locator('.cb-pitcher-card:not([hidden])').evaluate_all('items => items.map(item => item.dataset.availabilityGroup)')
    assert groups and all(group == 'review' for group in groups)
    review_filter.click()
    expect(page.locator('.cb-pitch-filter-state')).to_be_hidden()

    bounds = cards.evaluate_all(
        """items => items.map(item => {
            const r = item.getBoundingClientRect();
            return {left:r.left, right:r.right, viewport:innerWidth};
        })"""
    )
    assert bounds
    assert all(b['left'] >= -1 and b['right'] <= b['viewport'] + 1 for b in bounds)

    # Secondary work stays one tap away instead of adding several phone screens
    # below availability. Desktop remains expanded by CSS / responsive mode.
    targets = page.locator('#pitchTargetsCard')
    record = page.locator('#newPitchingOutingForm').locator('xpath=ancestor::div[contains(@class,"cb-pitch-section-card")][1]')
    history = page.locator('#pitchHistoryCard')
    expect(targets).to_have_attribute('data-mobile-collapsed', 'true')
    expect(record).to_have_attribute('data-mobile-collapsed', 'true')
    expect(history).to_have_attribute('data-mobile-collapsed', 'true')
    expect(page.locator('#newPitchingOutingForm')).to_be_hidden()
    expect(history.locator('#cbPitchHistoryPlayer')).to_be_hidden()

    history.get_by_role('button', name='Expand Recent Throwing History').click()
    expect(history).to_have_attribute('data-mobile-collapsed', 'false')
    expect(history.locator('#cbPitchHistoryPlayer')).to_be_visible()
    expect(history.locator('#cbPitchHistoryRange')).to_be_visible()
    expect(history.locator('#cbPitchHistoryCount')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2')


def test_pitch_target_save_updates_without_full_page_reload(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/pitching', wait_until='domcontentloaded')
    expect(page.locator('.cb-pitcher-card')).not_to_have_count(0)

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

    details_button = pitcher_card.locator('.cb-pitcher-details-toggle')
    if details_button.get_attribute('aria-expanded') == 'false':
        details_button.click()
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