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
    game_card.locator('.gd-actions a').first.click()

    expect(page).to_have_url(re.compile(r'/game/1$'))
    expect(page.locator('#pregame-checklist-container')).to_be_visible()
    expect(page.locator('#pde-preset')).to_be_visible(timeout=15_000)
