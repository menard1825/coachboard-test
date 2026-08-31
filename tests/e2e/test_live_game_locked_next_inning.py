"""Browser coverage for advancing a coach-confirmed next-inning defense once."""

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


def post_json(page: Page, coachboard_url: str, path: str, data):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == 200, f'POST {path} returned {response.status}: {response.text()}'
    payload = response.json()
    assert payload.get('status') == 'success', payload
    return payload


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


def create_game(page: Page, coachboard_url: str):
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=11)).isoformat(),
            'game_start_time': '16:00',
            'game_opponent': 'Locked Next Inning Opponent',
            'game_location': 'Locked Prep Test Field',
            'game_notes': 'Disposable locked next inning browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Locked Next Inning Lineup',
        'lineup_data': list(alignment().values()),
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Locked Next Inning Rotation',
        'innings': {'1': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def test_locked_next_inning_starts_without_duplicate_defense_modal(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 430, 'height': 932})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        started = post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        assert started['state']['game']['is_live'] is True
        assert started['state']['current_inning'] == '1'

        locked = post_json(page, coachboard_url, f'/api/live-game/{game_id}/next-inning-prep', {
            'mode': 'current',
        })
        assert locked['next_inning'] == '2'
        assert locked['confirmed']['inning'] == '2'
        assert locked['confirmed']['alignment'] == alignment()

        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
        expect(page.locator('#live-inning-display')).to_have_text('1')

        end_inning = page.locator('#liveEndInningBtn')
        expect(end_inning).to_be_visible(timeout=15_000)
        end_inning.click()

        # A locked-in defense is already the coach's confirmation. The full
        # next-inning editor must not ask for the same defense a second time.
        expect(page.locator('#cb-live-field-editor')).not_to_be_visible(timeout=2_000)
        expect(page.locator('#live-inning-display')).to_have_text('2', timeout=10_000)

        state_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
        assert state_response.ok, state_response.text()
        state = state_response.json()
        assert state['current_inning'] == '2'
        assert state['current_alignment'] == alignment()

        prep_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep')
        assert prep_response.ok, prep_response.text()
        prep = prep_response.json()
        assert prep['current_inning'] == '2'
        assert prep['next_inning'] == '3'
        assert prep['confirmed'] is None
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
