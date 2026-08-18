"""Game Day, planning, Live Game, clock, postgame, and safety coverage."""

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
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#games)?$'))


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


def delete_json(page: Page, coachboard_url: str, path: str, expected_status=200):
    response = page.request.fetch(f'{coachboard_url}{path}', method='DELETE')
    assert response.status == expected_status, f'DELETE {path} returned {response.status}: {response.text()}'
    return response.json()


def post_form(page: Page, coachboard_url: str, path: str, form):
    response = page.request.post(f'{coachboard_url}{path}', form=form, max_redirects=0)
    assert response.status in {302, 303}, f'POST {path} returned {response.status}: {response.text()}'
    return response


def alignment(pitcher='Pitcher Pat'):
    return {
        'P': pitcher,
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
    game_date = (date.today() + timedelta(days=5)).isoformat()
    response = post_form(page, coachboard_url, '/game-day/add', {
        'game_date': game_date,
        'game_start_time': '10:30',
        'game_opponent': 'Automation Live Opponent',
        'game_location': 'Automation Field',
        'game_notes': 'Created for the app-wide Playwright suite',
        'pitching_rule_set': 'USSSA',
    })
    location = response.headers.get('location') or ''
    match = re.search(r'/game/(\d+)', location)
    assert match, f'New game redirect did not include a game id: {location}'
    game_id = int(match.group(1))

    lineup = post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Automation Game Lineup',
        'lineup_data': [
            'Pitcher Pat', 'Catcher Cole', 'First Frank', 'Second Sam',
            'Third Theo', 'Shortstop Shawn', 'Left Lee', 'Center Casey', 'Right Riley',
        ],
        'associated_game_id': game_id,
    })
    rotation = post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Automation Game Rotation',
        'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })
    return game_id, lineup['new_id'], rotation['new_id']


def test_game_day_planning_live_game_and_postgame_lifecycle(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id, _, _ = create_game_with_plan(page, coachboard_url)

    rules = get_json(page, coachboard_url, f'/api/game-day/{game_id}/pitching-rules')
    assert rules['override'] == 'USSSA' and rules['source'] == 'game'
    rules = post_json(page, coachboard_url, f'/api/game-day/{game_id}/pitching-rules', {
        'rule_set': 'MLB Pitch Smart',
    })
    assert rules['override'] == 'MLB Pitch Smart'

    post_form(page, coachboard_url, f'/game-day/{game_id}/notes', {
        'game_notes': 'Automation notes updated and persisted',
    })
    game_data = get_json(page, coachboard_url, f'/api/game_data/{game_id}')
    assert game_data['game']['game_notes'] == 'Automation notes updated and persisted'
    assert game_data['lineup']['title'] == 'Automation Game Lineup'
    assert game_data['rotation']['title'] == 'Automation Game Rotation'

    post_form(page, coachboard_url, f'/game/{game_id}/update_absences', {
        'absent_players': '9',
    })
    assert get_json(page, coachboard_url, f'/api/game_data/{game_id}')['absent_player_ids'] == [9]
    post_form(page, coachboard_url, f'/game/{game_id}/update_absences', {})

    post_json(page, coachboard_url, f'/api/live-game/{game_id}/pitching-plan', {
        'player_id': 2,
        'role': 'First Relief',
        'expected_innings': '2',
        'coach_note': 'Attack the zone',
        'situational_note': 'Use after starter',
    })
    post_json(page, coachboard_url, f'/api/live-game/{game_id}/pitching-profile/2', {
        'traits': ['Command / Strike Thrower'],
    })

    pregame_state = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
    assert pregame_state['game']['is_live'] is False
    post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})

    state = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
    assert state['game']['is_live'] is True
    assert state['current_alignment']['P'] == 'Pitcher Pat'

    clock = get_json(page, coachboard_url, f'/api/live-game/{game_id}/clock')
    assert clock['clock']['is_live'] is True
    assert clock['clock']['started_at_utc']
    restarted = post_json(page, coachboard_url, f'/api/live-game/{game_id}/clock', {
        'action': 'restart',
        'time_limit_minutes': 90,
    })
    assert restarted['clock']['time_limit_minutes'] == 90

    changed = post_json(page, coachboard_url, f'/api/live-game/{game_id}/defensive-change', {
        'player_id': 4,
        'destination_position': 'SS',
    })
    assert changed['state']['current_alignment']['SS'] == 'Second Sam'
    restored = post_json(page, coachboard_url, f'/api/live-game/{game_id}/set-defense', {
        'alignment': alignment(),
    })
    assert restored['state']['current_alignment']['SS'] == 'Shortstop Shawn'

    pitching_change = alignment('Second Sam')
    pitching_change['2B'] = 'Pitcher Pat'
    completed = post_json(page, coachboard_url, f'/api/live-game/{game_id}/complete-pitcher-change', {
        'new_pitcher_id': 4,
        'alignment': pitching_change,
    })
    assert completed['state']['current_alignment']['P'] == 'Second Sam'

    prep = post_json(page, coachboard_url, f'/api/live-game/{game_id}/next-inning-prep', {
        'mode': 'current',
    })
    assert prep['confirmed']['alignment']['P'] == 'Second Sam'
    saved_prep = get_json(page, coachboard_url, f'/api/live-game/{game_id}/next-inning-prep')
    assert saved_prep['confirmed']['source'] == 'current'
    cleared_prep = delete_json(page, coachboard_url, f'/api/live-game/{game_id}/next-inning-prep')
    assert cleared_prep['confirmed'] is None
    post_json(page, coachboard_url, f'/api/live-game/{game_id}/next-inning-prep', {
        'mode': 'current',
    })

    inning = post_json(page, coachboard_url, f'/api/live-game/{game_id}/end-inning', {})
    assert inning['state']['current_inning'] == '2'
    undone = post_json(page, coachboard_url, f'/api/live-game/{game_id}/undo', {})
    assert undone['state']['current_inning'] == '1'

    finalized = post_json(page, coachboard_url, f'/api/live-game/{game_id}/end-with-pitching', {
        'defer_pitching': True,
        'end_reason': 'manual',
        'current_inning_played': True,
    })
    assert finalized['state']['game']['is_live'] is False

    delete_json(page, coachboard_url, f'/api/live-game/{game_id}/pitching-plan/2')

    page.goto(f'{coachboard_url}/game-day/{game_id}/report')
    expect(page.get_by_text('Automation Live Opponent')).to_be_visible()
    expect(page.locator('body')).to_contain_text('Automation notes updated and persisted')

    deleted = post_json(page, coachboard_url, f'/game-day/{game_id}/delete', {})
    assert 'Automation Live Opponent' in deleted['message']
    assert get_json(page, coachboard_url, f'/api/game_data/{game_id}', expected_status=404)['error']


def test_live_game_validation_legacy_client_and_cross_site_safety(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id, _, _ = create_game_with_plan(page, coachboard_url)

    inactive = page.request.post(f'{coachboard_url}/api/live-game/{game_id}/set-defense', data={
        'alignment': alignment(),
    })
    assert inactive.status == 409
    assert inactive.json()['message'] == 'Game is not live.'

    invalid_pitcher = page.request.post(f'{coachboard_url}/api/live-game/{game_id}/change-pitcher', data={
        'new_pitcher_id': 99999,
    })
    assert invalid_pitcher.status == 409

    legacy_routes = (
        '/toggle_live_game',
        '/save_rotation_event',
        '/undo_rotation_event',
        '/save_pitching_plan',
        '/delete_pitching_plan',
        '/save_final_pitch_counts',
    )
    for path in legacy_routes:
        response = page.request.post(f'{coachboard_url}{path}', data={'game_id': game_id})
        assert response.status == 410, f'{path} should require a refreshed client'

    cross_site = page.request.post(
        f'{coachboard_url}/api/live-game/{game_id}/start',
        data={},
        headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'},
    )
    assert cross_site.status == 403
    assert cross_site.json()['message'] == 'Cross-site request blocked.'

    destructive_get = page.request.get(
        f'{coachboard_url}/delete_game/{game_id}',
        headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'},
    )
    assert destructive_get.status == 403

    post_json(page, coachboard_url, f'/game-day/{game_id}/delete', {})
