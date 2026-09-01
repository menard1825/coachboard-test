"""Browser coverage for the defensive-command-center Live Game pivot."""

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


def test_inning_one_quick_start_launches_defensive_command_center(page: Page, coachboard_url: str):
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
        assert roster
        roster_ids = [int(player['id']) for player in roster]
        roster_names = {player['name'] for player in roster}
        assert set(complete_alignment().values()).issubset(roster_names)

        existing = page.request.get(f'{coachboard_url}/api/game_data/{game_id}')
        assert existing.ok
        existing_data = existing.json()

        existing_lineup = existing_data.get('lineup') or {}
        lineup_payload = {
            'title': 'Command Center Game Lineup',
            'lineup_player_ids': roster_ids,
            'associated_game_id': game_id,
        }
        if existing_lineup.get('id'):
            lineup = post_json(
                page,
                coachboard_url,
                f'/edit_lineup/{int(existing_lineup["id"])}',
                lineup_payload,
            )
        else:
            lineup = post_json(page, coachboard_url, '/add_lineup', lineup_payload)
        assert lineup['lineup']['associated_game_id'] == game_id

        existing_rotation = existing_data.get('rotation') or {}
        rotation_payload = {
            'title': 'Command Center Inning 1',
            'innings': {'1': complete_alignment()},
            'associated_game_id': game_id,
        }
        if existing_rotation.get('id'):
            rotation_payload['id'] = int(existing_rotation['id'])
        rotation = post_json(page, coachboard_url, '/save_rotation', rotation_payload)
        assert rotation['new_id']

        saved = page.request.get(f'{coachboard_url}/api/game_data/{game_id}')
        assert saved.ok
        saved_rotation = saved.json().get('rotation') or {}
        assert saved_rotation.get('innings', {}).get('1') == complete_alignment()

        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        # Quick Start is now a discoverable setup workflow around the one
        # canonical Start Game action. It does not create a second start mode.
        launch = page.locator('#cb-quick-start-launch')
        expect(launch).to_be_visible(timeout=15_000)
        expect(launch).to_contain_text('Quick Start')
        expect(launch.get_by_role('button', name='Open Quick Start')).to_be_visible()
        expect(page.locator('#cb-quick-start-note')).to_be_hidden()

        start = page.locator('#startLiveGameBtnAction')
        expect(start).to_be_enabled()
        expect(start).to_contain_text('START GAME')

        launch.get_by_role('button', name='Open Quick Start').click()
        quick = page.locator('#cb-quick-start-modal')
        expect(quick).to_be_visible()
        expect(quick).to_contain_text('Get ready for first pitch')
        expect(quick).to_contain_text('Player Availability')
        expect(quick).to_contain_text('Batting Order')
        expect(quick).to_contain_text('Starting Defense')
        expect(quick).to_contain_text('Starting Pitcher')
        expect(quick).to_contain_text('Pitching Tracking')
        expect(quick).to_contain_text('Track Pitches')
        expect(quick).to_contain_text('Game Clock')
        quick_start = quick.get_by_role('button', name='START GAME')
        expect(quick_start).to_be_enabled()
        quick_start.click()

        shell = page.locator('.coach-live-shell')
        expect(shell).to_be_visible(timeout=15_000)

        actions = shell.locator('#coach-action-slot')
        expect(actions.get_by_role('button', name=re.compile('Defense Change'))).to_be_visible()
        expect(actions.get_by_role('button', name=re.compile('Change Pitcher'))).to_be_visible()
        expect(actions.get_by_role('button', name=re.compile('End Inning'))).to_be_visible()

        undo = shell.get_by_role('button', name='Undo last change')
        expect(undo).to_be_visible()
        undo_box = undo.bounding_box()
        assert undo_box and undo_box['width'] >= 44 and undo_box['height'] >= 44

        pitcher_status = page.locator('#live-pitcher-stats')
        expect(pitcher_status).to_contain_text('Eligible to pitch')
        expect(pitcher_status).not_to_contain_text('7-day')
        expect(pitcher_status).not_to_contain_text('Coach target')

        sync_status = page.locator('#live-sync-status-v2')
        expect(sync_status).to_be_visible(timeout=10_000)
        expect(sync_status).to_contain_text('SYNCED')

        page.context.set_offline(True)
        expect(sync_status).to_contain_text(re.compile(r'RECONNECTING|NOT SYNCED'), timeout=10_000)
        page.context.set_offline(False)
        expect(sync_status).to_contain_text('SYNCED', timeout=15_000)

        end_game = page.locator('#liveEndGameBtn')
        expect(end_game).to_have_text(re.compile(r'^\s*End Game\s*$'))
        page.once('dialog', lambda dialog: dialog.accept())
        end_game.click()

        expect(page).to_have_url(re.compile(rf'/game-day/{game_id}/report$'), timeout=15_000)
        expect(page.get_by_text('GameChanger Pitching', exact=True)).to_be_visible()
        expect(page.get_by_role('link', name='Enter GameChanger Stats')).to_be_visible()
    finally:
        page.context.set_offline(False)
        # A live game cannot be deleted. End it without guessing pitching stats
        # only when an earlier assertion stopped the test before End Game.
        state_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
        if state_response.ok:
            state = state_response.json()
            if state.get('game', {}).get('is_live'):
                page.request.post(
                    f'{coachboard_url}/api/live-game/{game_id}/end-with-pitching',
                    data={'defer_pitching': True},
                )
        page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
