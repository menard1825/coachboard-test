"""Browser coverage for applying a Starting Defense across a game's innings."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
OPPONENT = 'Starting Defense Base Opponent'


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


def starting_defense():
    return {
        'C': 'Catcher Cole',
        '1B': 'First Frank',
        '2B': 'Second Sam',
        '3B': 'Third Theo',
        'SS': 'Shortstop Shawn',
        'LF': 'Left Lee',
        'CF': 'Center Casey',
        'RF': 'Right Riley',
    }


def test_starting_defense_can_seed_game_without_overwriting_pitchers(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)

    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': '2030-03-01',
            'game_start_time': '10:00',
            'game_opponent': OPPONENT,
            'game_location': 'Tournament Field',
            'game_notes': 'Disposable starting-defense test',
            'pitching_rule_set': 'MLB Pitch Smart',
        },
    )
    assert created.ok
    games = page.request.get(f'{coachboard_url}/api/games').json()
    game = next(item for item in games if item.get('opponent') == OPPONENT)
    game_id = int(game['id'])
    template_title = f'E2E Starting Defense {game_id}'

    try:
        # Loading Game Management initializes the regulation-inning rotation slots.
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)

        roster = page.request.get(f'{coachboard_url}/api/roster').json()
        roster_names = {player['name'] for player in roster}
        assert {'Pitcher Pat', *starting_defense().values()}.issubset(roster_names)

        saved_template = post_json(
            page,
            coachboard_url,
            '/api/starting-defense-template/save',
            {'title': template_title, 'innings': {'1': starting_defense()}},
        )
        assert saved_template.get('new_template') or saved_template.get('id')

        game_data_response = page.request.get(f'{coachboard_url}/api/game_data/{game_id}')
        assert game_data_response.ok
        game_data = game_data_response.json()
        rotation = game_data.get('rotation') or {}
        innings = rotation.get('innings') or {}
        assert innings

        # Give every planned inning an explicit pitcher first. Applying a Starting
        # Defense must not silently rewrite the pitching plan.
        for key in list(innings):
            if re.fullmatch(r'\d+', str(key)):
                innings[key] = {'P': 'Pitcher Pat'}
        rotation_payload = {
            'id': rotation.get('id'),
            'title': rotation.get('title') or f'Rotation for vs {OPPONENT}',
            'innings': innings,
            'associated_game_id': game_id,
        }
        post_json(page, coachboard_url, '/save_rotation', rotation_payload)

        page.reload(wait_until='domcontentloaded')
        select = page.locator('#pde-preset')
        expect(select).to_be_visible(timeout=15_000)
        select.select_option(label=template_title)

        use_for_game = page.get_by_role('button', name='Use for Game')
        expect(use_for_game).to_be_enabled()
        expect(page.get_by_role('button', name='This Inning')).to_be_visible()
        expect(page.get_by_text('Pitchers stay as you already assigned them')).to_be_visible()

        page.once('dialog', lambda dialog: dialog.accept())
        use_for_game.click()
        page.wait_for_load_state('domcontentloaded')

        updated_response = page.request.get(f'{coachboard_url}/api/game_data/{game_id}')
        assert updated_response.ok
        updated = updated_response.json().get('rotation') or {}
        updated_innings = updated.get('innings') or {}
        whole_innings = [
            key for key in sorted(updated_innings, key=lambda value: int(value) if str(value).isdigit() else 99)
            if str(key).isdigit()
        ]
        assert len(whole_innings) >= 6

        for key in whole_innings:
            alignment = updated_innings[key]
            assert alignment.get('P') == 'Pitcher Pat'
            for position, player_name in starting_defense().items():
                assert alignment.get(position) == player_name
    finally:
        page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
