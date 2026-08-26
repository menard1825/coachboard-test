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

        lineup = post_json(page, coachboard_url, '/add_lineup', {
            'title': 'Command Center Game Lineup',
            'lineup_player_ids': roster_ids,
            'associated_game_id': game_id,
        })
        assert lineup['lineup']['associated_game_id'] == game_id

        rotation = post_json(page, coachboard_url, '/save_rotation', {
            'title': 'Command Center Inning 1',
            'innings': {'1': complete_alignment()},
            'associated_game_id': game_id,
        })
        assert rotation['new_id']

        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        quick_note = page.locator('#cb-quick-start-note')
        expect(quick_note).to_be_visible(timeout=15_000)
        expect(quick_note).to_contain_text('Inning 1 is ready')
        expect(quick_note).to_contain_text('set later innings between innings')

        start = page.locator('#startLiveGameBtnAction')
        expect(start).to_be_enabled()
        expect(start).to_contain_text('START WITH INNING 1')
        assert start.get_attribute('data-cb-start-mode') == 'quick'

        start.click()
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

        end_game = page.locator('#liveEndGameBtn')
        expect(end_game).to_have_text(re.compile(r'^\s*End Game\s*$'))
    finally:
        # A live game cannot be deleted. End it without guessing pitching stats,
        # then remove the disposable game.
        page.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/end-with-pitching',
            data={'defer_pitching': True},
        )
        page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
