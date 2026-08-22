"""Browser coverage for deleting historical games from Game Day."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
PAST_OPPONENT = 'Past Delete Test Opponent'


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


def test_head_coach_can_delete_past_game_from_mobile_history(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)

    created = page.context.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': '2025-01-15',
            'game_start_time': '16:30',
            'game_opponent': PAST_OPPONENT,
            'game_location': 'History Field',
            'game_notes': 'Disposable past-game delete regression test',
        },
    )
    assert created.ok

    games_response = page.context.request.get(f'{coachboard_url}/api/games')
    assert games_response.ok
    game = next(item for item in games_response.json() if item.get('opponent') == PAST_OPPONENT)
    game_id = int(game['id'])

    # The full Game Day history should expose the protected options menu too.
    page.goto(f'{coachboard_url}/game-day', wait_until='domcontentloaded')
    past_row = page.locator(f'.gd-up-row[data-game-id="{game_id}"]')
    expect(past_row).to_be_visible()
    past_row.locator('.gd-game-menu > button').click()
    expect(past_row.get_by_role('button', name='Delete Game')).to_be_visible()

    # Mobile's same-document Game Day workspace must also support deletion even
    # when its row was created by the API-authoritative fallback renderer.
    page.goto(f'{coachboard_url}/#games', wait_until='domcontentloaded')
    mobile_row = page.locator(f'#games-past-list-container [data-cb-game-id="{game_id}"]')
    expect(mobile_row).to_be_visible()
    delete_button = mobile_row.locator('.cb-mobile-delete-game')
    expect(delete_button).to_be_visible()

    page.once('dialog', lambda dialog: dialog.accept())
    delete_button.click()
    page.wait_for_function(
        "gameId => !document.querySelector(`[data-cb-game-id=\"${gameId}\"]`)",
        game_id,
        timeout=10000,
    )

    games_after = page.context.request.get(f'{coachboard_url}/api/games')
    assert games_after.ok
    assert all(int(item['id']) != game_id for item in games_after.json())
