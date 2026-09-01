"""Browser coverage for the Test 2 live defensive command center."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
OPPONENT = 'Command Center Pivot Opponent'


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


def post_json(page: Page, coachboard_url: str, path: str, data):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == 200, f'POST {path} returned {response.status}: {response.text()}'
    payload = response.json()
    assert payload.get('status') == 'success', payload
    return payload


def complete_alignment():
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


def test_first_pitch_launches_quick_field_command_center(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)

    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': '2030-02-15',
            'game_start_time': '12:00',
            'game_opponent': OPPONENT,
            'game_location': 'Tournament Field',
            'game_notes': 'Disposable command-center test',
            'pitching_rule_set': 'MLB Pitch Smart',
        },
    )
    assert created.ok
    games = page.request.get(f'{coachboard_url}/api/games').json()
    game = next(item for item in games if item.get('opponent') == OPPONENT)
    game_id = int(game['id'])

    try:
        roster = page.request.get(f'{coachboard_url}/api/roster').json()
        roster_ids = [int(player['id']) for player in roster]
        assert set(complete_alignment().values()).issubset({player['name'] for player in roster})

        game_data = page.request.get(f'{coachboard_url}/api/game_data/{game_id}').json()
        lineup_payload = {
            'title': 'Command Center Game Lineup',
            'lineup_player_ids': roster_ids,
            'associated_game_id': game_id,
        }
        existing_lineup = game_data.get('lineup') or {}
        if existing_lineup.get('id'):
            post_json(page, coachboard_url, f'/edit_lineup/{int(existing_lineup["id"])}', lineup_payload)
        else:
            post_json(page, coachboard_url, '/add_lineup', lineup_payload)

        rotation_payload = {
            'title': 'Command Center Inning 1',
            'innings': {'1': complete_alignment()},
            'associated_game_id': game_id,
        }
        existing_rotation = game_data.get('rotation') or {}
        if existing_rotation.get('id'):
            rotation_payload['id'] = int(existing_rotation['id'])
        post_json(page, coachboard_url, '/save_rotation', rotation_payload)

        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        modes = page.locator('#cb-test2-pregame-modes')
        expect(modes).to_be_visible(timeout=15_000)
        expect(modes.get_by_role('button', name='First Pitch')).to_have_class(re.compile(r'\bactive\b'))
        expect(page.locator('#cb-quick-start-launch')).to_have_count(0)

        start = page.locator('#startLiveGameBtnAction')
        expect(start).to_be_enabled()
        start.click()

        quick = page.locator('#cbQuickDefense')
        expect(quick).to_be_visible(timeout=15_000)
        expect(quick.locator('.cb-qd-title')).to_have_text('Quick Field', timeout=15_000)
        expect(page.locator('#liveDefensiveChangeBtn')).to_have_count(0)
        expect(page.locator('#cb-live-field-editor')).to_have_count(0)
        expect(page.locator('#liveChangePitcherBtn')).to_be_visible()
        expect(page.locator('#liveEndInningBtn')).to_be_visible()
        expect(page.locator('#liveUndoBtn')).to_be_visible()

        sync_status = page.locator('#live-sync-status-v2')
        expect(sync_status).to_be_visible(timeout=10_000)
        expect(sync_status).to_contain_text('SYNCED')

        page.context.set_offline(True)
        expect(sync_status).to_contain_text(re.compile(r'RECONNECTING|NOT SYNCED'), timeout=10_000)
        page.context.set_offline(False)
        expect(sync_status).to_contain_text('SYNCED', timeout=15_000)
    finally:
        page.context.set_offline(False)
        state_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
        if state_response.ok and state_response.json().get('game', {}).get('is_live'):
            page.request.post(
                f'{coachboard_url}/api/live-game/{game_id}/end-with-pitching',
                data={'defer_pitching': True, 'end_reason': 'manual', 'current_inning_played': True},
            )
        page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
