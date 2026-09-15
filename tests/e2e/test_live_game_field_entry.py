"""Browser coverage that current-fielder changes stay inside Quick Field."""

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
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


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
            'game_date': (date.today() + timedelta(days=9)).isoformat(),
            'game_start_time': '13:30',
            'game_opponent': 'Field Entry Opponent',
            'game_location': 'Field Entry Test Field',
            'game_notes': 'Disposable current-fielder Quick Field browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Field Entry Lineup',
        'lineup_data': list(alignment().values()),
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Field Entry Rotation',
        'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def test_phone_current_fielder_uses_quick_field_move_sheet(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        quick = page.locator('#cbQuickDefense')
        expect(quick).to_be_visible(timeout=15_000)
        expect(quick.locator('.cb-qd-title')).to_have_text('Quick Field')
        shortstop = quick.locator('[data-cb-position="SS"]')
        expect(shortstop).to_contain_text('Shortstop Shawn')
        shortstop.click()

        move_sheet = page.locator('#cbQuickMoveModal')
        expect(move_sheet).to_be_visible(timeout=10_000)
        expect(move_sheet).to_contain_text('Shortstop Shawn is currently playing SS')
        expect(page.locator('#cb-live-field-editor')).to_have_count(0)
        expect(page.locator('#liveDefensiveChangeBtn')).to_have_count(0)

        # Swap SS and 2B from the one live defense surface.
        move_sheet.locator('[data-cb-destination="2B"]').click()
        expect(move_sheet).not_to_be_visible(timeout=10_000)
        expect(quick.locator('[data-cb-position="2B"]')).to_contain_text('Shortstop Shawn', timeout=10_000)
        expect(quick.locator('[data-cb-position="SS"]')).to_contain_text('Second Sam', timeout=10_000)
        expect(quick.locator('.cb-save-state')).to_contain_text('Saved')

        state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert state['current_alignment']['2B'] == 'Shortstop Shawn'
        assert state['current_alignment']['SS'] == 'Second Sam'
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