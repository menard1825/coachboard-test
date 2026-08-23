"""Live Game navigation must not end or reset the active game."""

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
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:games|overview))?$'))


def post_json(page: Page, coachboard_url: str, path: str, data, expected_status=200):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == expected_status, f'POST {path} returned {response.status}: {response.text()}'
    payload = response.json()
    if expected_status < 400:
        assert payload.get('status') == 'success', f'POST {path} failed: {payload}'
    return payload


def get_json(page: Page, coachboard_url: str, path: str, expected_status=200):
    response = page.request.get(f'{coachboard_url}{path}')
    assert response.status == expected_status, f'GET {path} returned {response.status}: {response.text()}'
    return response.json()


def alignment():
    return {
        'P': 'Pitcher Pat',
        'C': 'Catcher Cole',
        '1B': 'First Frank',
        '2B': 'Second Sam',
        '3B': 'Third Theo',
        'SS': 'Shortstop Shawn',
        'LF': 'Left Lee',
        'CF': 'Center Casey',
        'RF': 'Right Riley',
    }


def create_game_with_plan(page: Page, coachboard_url: str):
    game_date = (date.today() + timedelta(days=6)).isoformat()
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': game_date,
            'game_start_time': '13:00',
            'game_opponent': 'Navigation Persistence Opponent',
            'game_location': 'Navigation Test Field',
            'game_notes': 'Disposable live navigation test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    location = response.headers.get('location') or ''
    match = re.search(r'/game/(\d+)', location)
    assert match, f'New game redirect did not include a game id: {location}'
    game_id = int(match.group(1))

    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Navigation Test Lineup',
        'lineup_data': [
            'Pitcher Pat', 'Catcher Cole', 'First Frank', 'Second Sam',
            'Third Theo', 'Shortstop Shawn', 'Left Lee', 'Center Casey', 'Right Riley',
        ],
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Navigation Test Rotation',
        'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def test_paused_live_game_survives_navigation_away_and_back(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    game_id = create_game_with_plan(page, coachboard_url)

    try:
        started = post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        assert started['state']['game']['is_live'] is True

        paused = post_json(page, coachboard_url, f'/api/live-game/{game_id}/clock', {'action': 'pause'})
        assert paused['clock']['is_live'] is True
        assert paused['clock']['is_paused'] is True
        paused_elapsed = paused['clock']['elapsed_seconds']

        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
        expect(page.locator('#cbDugoutHeader')).to_be_visible(timeout=15_000)
        expect(page.locator('#cbDugoutHeader [data-cb-menu]')).to_be_visible()
        expect(page.locator('#cbDugoutHeader .cb-dh-clock small')).to_contain_text('Paused')

        # Leaving Live Game is navigation only. It must not call any end-game API.
        page.locator('#cbDugoutHeader [data-cb-menu]').click()
        menu = page.locator('#cbCoachBoardNavModal')
        expect(menu).to_be_visible()
        expect(menu).to_contain_text('The game stays live.')
        game_day_link = menu.get_by_role('link', name='Game Day')
        expect(game_day_link).to_be_visible()
        game_day_link.click()
        expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/game-day/?$'))

        state_away = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
        clock_away = get_json(page, coachboard_url, f'/api/live-game/{game_id}/clock')['clock']
        assert state_away['game']['is_live'] is True
        assert state_away['current_inning'] == '1'
        assert clock_away['is_live'] is True
        assert clock_away['is_paused'] is True
        assert abs(int(clock_away['elapsed_seconds']) - int(paused_elapsed)) <= 1

        # A coach can return later and CoachBoard reconstructs the same live state.
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
        expect(page.locator('#cbDugoutHeader')).to_be_visible(timeout=15_000)
        expect(page.locator('body')).to_have_class(re.compile(r'\bcb-clock-paused\b'), timeout=15_000)
        expect(page.locator('#live-inning-display')).to_have_text('1')

        clock_returned = get_json(page, coachboard_url, f'/api/live-game/{game_id}/clock')['clock']
        assert clock_returned['is_paused'] is True
        assert abs(int(clock_returned['elapsed_seconds']) - int(paused_elapsed)) <= 1

        resumed = post_json(page, coachboard_url, f'/api/live-game/{game_id}/clock', {'action': 'resume'})
        assert resumed['clock']['is_paused'] is False
    finally:
        state_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
        if state_response.ok and state_response.json().get('game', {}).get('is_live'):
            page.request.post(
                f'{coachboard_url}/api/live-game/{game_id}/end-with-pitching',
                data={
                    'defer_pitching': True,
                    'end_reason': 'manual',
                    'current_inning_played': True,
                },
            )
        page.request.post(
            f'{coachboard_url}/game-day/{game_id}/delete',
            headers={'Accept': 'application/json'},
        )
