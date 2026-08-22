"""Mobile Game Day date/time and schedule-grouping regression coverage."""

import os
import re
from datetime import date, timedelta

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


def test_mobile_game_day_labels_native_date_time_and_uses_saved_start_time(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/#games', wait_until='domcontentloaded')

    games = page.locator('#games')
    expect(games).to_have_class(re.compile(r'\bactive\b'))

    # Empty native date/time controls do not expose placeholder text on iPhone,
    # so CoachBoard supplies visible labels and empty-state text itself.
    expect(games.locator('label[for="add_game_date"]')).to_have_text('Date')
    expect(games.locator('label[for="add_game_start_time"]')).to_contain_text('Start time')
    expect(games.locator('.cb-game-native-empty', has_text='Select date')).to_be_visible()
    expect(games.locator('.cb-game-native-empty', has_text='Select time')).to_be_visible()

    date_input = games.locator('#add_game_date')
    time_input = games.locator('#add_game_start_time')
    date_input.fill('2026-09-12')
    time_input.fill('16:30')
    expect(games.locator('.cb-game-native-input').nth(0)).to_have_class(re.compile(r'\bhas-value\b'))
    expect(games.locator('.cb-game-native-input').nth(1)).to_have_class(re.compile(r'\bhas-value\b'))

    # The seeded Browser Bears game is saved with start_time='09:00'. The old
    # renderer ignored that field whenever game.date included a midnight time
    # component and incorrectly displayed 12:00 AM.
    browser_bears = games.locator('#games-list-container li.list-group-item').filter(has_text='Browser Bears')
    expect(browser_bears).to_be_visible()
    expect(browser_bears.locator('p.mb-1')).to_contain_text('9:00 AM')
    expect(browser_bears.locator('p.mb-1')).not_to_contain_text('12:00 AM')


def test_mobile_game_day_moves_past_games_out_of_game_schedule(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)

    stamp = date.today().strftime('%Y%m%d')
    past_opponent = f'Past Panthers {stamp}'
    future_opponent = f'Future Falcons {stamp}'
    past_date = (date.today() - timedelta(days=10)).isoformat()
    future_date = (date.today() + timedelta(days=10)).isoformat()

    created_ids = []
    try:
        for game_date, opponent, start_time in (
            (past_date, past_opponent, '16:30'),
            (future_date, future_opponent, '18:00'),
        ):
            response = page.request.post(
                f'{coachboard_url}/add_game',
                form={
                    'game_date': game_date,
                    'game_start_time': start_time,
                    'game_opponent': opponent,
                    'game_location': 'Browser Test Field',
                    'game_notes': '',
                },
            )
            assert response.ok

        all_games = page.request.get(f'{coachboard_url}/api/games').json()
        created_ids = [
            int(game['id'])
            for game in all_games
            if game.get('opponent') in {past_opponent, future_opponent}
        ]
        assert len(created_ids) == 2

        page.goto(f'{coachboard_url}/#games', wait_until='domcontentloaded')
        games = page.locator('#games')
        expect(games).to_have_class(re.compile(r'\bactive\b'))

        schedule = games.locator('#games-list-container')
        past_list = games.locator('#games-past-list-container')
        past_card = games.locator('#cb-mobile-past-games-card')

        expect(past_card).to_be_visible()
        expect(past_card.locator('.card-header h5')).to_have_text('Past Games')
        expect(schedule).to_contain_text(future_opponent)
        expect(schedule).not_to_contain_text(past_opponent)
        expect(past_list).to_contain_text(past_opponent)
        expect(past_list).not_to_contain_text(future_opponent)
    finally:
        for game_id in created_ids:
            page.request.get(f'{coachboard_url}/delete_game/{game_id}')
