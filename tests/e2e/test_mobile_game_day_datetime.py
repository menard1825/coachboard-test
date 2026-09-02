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


def test_mobile_game_day_uses_saved_start_time(page: Page, coachboard_url: str):
    """The dedicated Game Day workspace must display saved times in coach-friendly 12-hour form."""
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/game-day', wait_until='domcontentloaded')

    expect(page).to_have_url(re.compile(r'/game-day$'))
    expect(page.get_by_role('heading', name='Game Day')).to_be_visible()

    # The seeded Browser Bears game is saved with start_time='09:00'. The old
    # renderer ignored that field whenever game.date included a midnight time
    # component and incorrectly displayed 12:00 AM.
    browser_bears = page.locator('[data-game-id="1"]')
    expect(browser_bears).to_be_visible()
    expect(browser_bears).to_contain_text('9:00 AM')
    expect(browser_bears).not_to_contain_text('12:00 AM')


def test_mobile_game_day_moves_past_games_out_of_upcoming_schedule(page: Page, coachboard_url: str):
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
                f'{coachboard_url}/game-day/add',
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

        page.goto(f'{coachboard_url}/game-day', wait_until='domcontentloaded')
        expect(page.get_by_role('heading', name='Game Day')).to_be_visible()
        expect(page.locator('body')).to_contain_text(future_opponent)

        past_title = page.locator('.gd-section-title', has_text='Past Games')
        expect(past_title).to_be_visible()
        past_list = past_title.locator('xpath=following-sibling::*[1]')
        expect(past_list).to_contain_text(past_opponent)
        expect(past_list).not_to_contain_text(future_opponent)

        # Saved times are formatted consistently in both upcoming and history.
        expect(page.locator('body')).to_contain_text('6:00 PM')
        expect(past_list).to_contain_text('4:30 PM')
    finally:
        for game_id in created_ids:
            page.request.post(
                f'{coachboard_url}/game-day/{game_id}/delete',
                headers={'Accept': 'application/json'},
            )
