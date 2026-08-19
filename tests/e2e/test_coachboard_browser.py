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
    expect(page).to_have_url(
        re.compile(rf'^{re.escape(coachboard_url)}/?(?:#games)?$')
    )
    expect(page.locator('.navbar-brand-text')).to_contain_text('Playwright Prospects')


def test_coach_can_sign_in_and_open_game_day(page: Page, coachboard_url: str):
    page.goto(coachboard_url)
    expect(page).to_have_url(re.compile(r'/login$'))

    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/game-day')

    expect(page.get_by_role('heading', name='Game Day')).to_be_visible()
    game_card = page.locator('[data-game-id="1"]')
    expect(game_card).to_be_visible()
    expect(game_card).to_contain_text('vs Browser Bears')
    expect(game_card).to_contain_text('9 present')

    game_card.locator('.gd-actions a').first.click()
    expect(page).to_have_url(re.compile(r'/game/1$'))
    expect(page.get_by_role('heading', name=re.compile('Playwright Prospects vs Browser Bears'))).to_be_visible()


def test_starting_defense_applies_and_survives_reload(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/game/1')

    preset = page.locator('#pde-preset')
    expect(preset).to_be_visible(timeout=15_000)
    preset.select_option(label='Everyday Defense')

    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#pde-apply').click()
    expect(page.locator('.toast-body')).to_contain_text('Everyday Defense applied', timeout=15_000)

    expected_positions = {
        'P': 'OPEN',
        'C': 'Catcher Cole',
        '1B': 'First Frank',
        '2B': 'Second Sam',
        '3B': 'Third Theo',
        'SS': 'Shortstop Shawn',
        'LF': 'Left Lee',
        'CF': 'Center Casey',
        'RF': 'Right Riley',
    }
    for position, player_name in expected_positions.items():
        expect(
            page.locator(f'[data-pde-pos="{position}"] .pde-name')
        ).to_have_text(player_name)

    page.reload()
    expect(page.locator('#pde-preset')).to_be_visible(timeout=15_000)
    for position, player_name in expected_positions.items():
        expect(
            page.locator(f'[data-pde-pos="{position}"] .pde-name')
        ).to_have_text(player_name)


def test_other_team_game_is_not_exposed(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/game/2')

    expect(page).to_have_url(f'{coachboard_url}/game-day')
    expect(page.get_by_role('heading', name='Game Day')).to_be_visible()
    expect(page.get_by_text('Game not found.')).to_be_visible()
    expect(page.get_by_text('Private Opponent')).to_have_count(0)


def test_game_day_core_flow_works_on_phone_size(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/game-day')

    expect(page.get_by_role('heading', name='Game Day')).to_be_visible()
    game_card = page.locator('[data-game-id="1"]')
    expect(game_card).to_be_visible()
    expect(game_card.locator('.gd-actions a').first).to_be_visible()

    page.get_by_role('button', name='Add Game').first.click()
    add_modal = page.locator('#game-day-add-modal')
    expect(add_modal).to_be_visible()
    expect(add_modal.locator('#gd-add-pitching-rules')).to_be_visible(timeout=15_000)
    add_action = add_modal.get_by_role('button', name='Add & Prepare Game')
    expect(add_action).to_be_visible()
    footer_geometry = add_modal.locator('.modal-footer').evaluate(
        "footer => ({bottom: footer.getBoundingClientRect().bottom, viewport: window.innerHeight})"
    )
    assert footer_geometry['bottom'] <= footer_geometry['viewport'] + 1
    expect(add_modal.locator('.modal-body')).to_have_css('overflow-y', 'auto')
    add_modal.get_by_role('button', name='Cancel').click()
    expect(add_modal).to_be_hidden()

    page.get_by_role('button', name='Add Game').first.click()
    expect(add_modal).to_be_visible()
    add_modal.locator('#gd-add-opponent').fill('Browser Added Opponent')
    add_modal.locator('#gd-add-location').fill('Browser Test Field')
    add_modal.get_by_role('button', name='Add & Prepare Game').click()
    expect(page).to_have_url(re.compile(r'/game/\d+$'))
    added_match = re.search(r'/game/(\d+)$', page.url)
    assert added_match
    added_game_id = int(added_match.group(1))
    expect(page.get_by_role('heading', name=re.compile('Browser Added Opponent'))).to_be_visible()
    deleted = page.request.post(f'{coachboard_url}/game-day/{added_game_id}/delete', data={})
    assert deleted.status == 200 and deleted.json()['status'] == 'success'

    page.goto(f'{coachboard_url}/game-day')
    game_card = page.locator('[data-game-id="1"]')

    game_card.locator('.gd-actions a').first.click()

    expect(page).to_have_url(re.compile(r'/game/1$'))
    expect(page.locator('#pregame-checklist-container')).to_be_visible()
    expect(page.locator('#pde-preset')).to_be_visible(timeout=15_000)


def test_pregame_controls_and_availability_work_on_phone_size(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/game/1')

    availability_toggle = page.locator('#availabilityToggleBtn')
    availability_panel = page.locator('#availabilityCollapse')
    expect(availability_toggle).to_have_text("Set Who's Out", timeout=15_000)
    expect(availability_toggle).to_have_attribute('aria-expanded', 'false')

    availability_toggle.click()
    expect(availability_panel).to_have_class(re.compile(r'\bshow\b'))
    expect(availability_toggle).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('#availability-out-count-v2-value')).to_have_text('0')

    absent_player = page.locator('#absent_9')
    absent_player.check()
    expect(page.locator('#availability-out-count-v2-value')).to_have_text('1')
    expect(absent_player.locator('xpath=ancestor::div[contains(@class,"availability-player-v2")]')).to_contain_text('OUT for this game')
    page.locator('#saveGameAvailabilityBtn').click()

    expect(page).to_have_url(re.compile(r'/game/1#availabilityCollapse$'))
    expect(availability_panel).to_have_class(re.compile(r'\bshow\b'), timeout=15_000)
    expect(absent_player).to_be_checked()
    availability_card = page.locator('#availabilityToggleBtn').locator('xpath=ancestor::div[contains(@class,"card")]')
    expect(availability_card).to_contain_text('8 Available')
    expect(availability_card).to_contain_text('1 out')

    page.goto(f'{coachboard_url}/game-day')
    expect(page.locator('[data-game-id="1"]')).to_contain_text('8 present · 1 out')

    # Restore the shared seeded game so later browser checks start with the full roster.
    page.goto(f'{coachboard_url}/game/1#availabilityCollapse')
    expect(page.locator('#availabilityCollapse')).to_have_class(re.compile(r'\bshow\b'), timeout=15_000)
    page.locator('#absent_9').uncheck()
    page.locator('#saveGameAvailabilityBtn').click()
    expect(page.locator('#absent_9')).not_to_be_checked()

    edit_game = page.locator('[data-bs-target="#editGameModal"]')
    edit_game.click()
    expect(page.locator('#editGameModal')).to_be_visible()
    page.locator('#editGameModal .btn-close').click()
    expect(page.locator('#editGameModal')).to_be_hidden()

    page.get_by_role('button', name='Edit Lineup').click()
    expect(page.locator('#lineupEditorModal')).to_be_visible()
    page.locator('#lineupEditorModal').get_by_role('button', name='Cancel').click()
    expect(page.locator('#lineupEditorModal')).to_be_hidden()

    page.locator('#editDefenseBtn').click()
    expect(page.locator('#pde-preset')).to_be_visible(timeout=15_000)
    page.locator('#viewPitchingBtn').click()
    expect(page.locator('#pitching-log-container')).to_be_visible()
