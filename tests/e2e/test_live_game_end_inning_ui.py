"""Critical browser coverage for the coach-facing End Inning workflow."""

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
            'game_date': (date.today() + timedelta(days=7)).isoformat(),
            'game_start_time': '11:00',
            'game_opponent': 'End Inning UI Opponent',
            'game_location': 'Workflow Test Field',
            'game_notes': 'Disposable End Inning browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'End Inning UI Lineup',
        'lineup_data': [
            'Pitcher Pat', 'Catcher Cole', 'First Frank', 'Second Sam',
            'Third Theo', 'Shortstop Shawn', 'Left Lee', 'Center Casey', 'Right Riley',
        ],
        'associated_game_id': game_id,
    })
    # Deliberately save only Inning 1. End Inning must ask Same Defense/New
    # Defense instead of silently advancing to an already-prepared next inning.
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'End Inning UI Rotation',
        'innings': {'1': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def test_end_inning_has_one_coach_facing_workflow(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)
    native_dialogs = []

    def dismiss_unexpected_dialog(dialog):
        native_dialogs.append(dialog.message)
        dialog.dismiss()

    page.on('dialog', dismiss_unexpected_dialog)

    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        page.locator('#startLiveGameBtnAction').click()
        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
        expect(page.locator('#liveEndInningBtn')).to_be_visible(timeout=15_000)

        page.locator('#liveEndInningBtn').click()

        # The retired window.confirm() handler must never run. Coaches should
        # see exactly one baseball decision sheet owned by inning_clarity.
        expect(page.locator('#cbEndInningSheet')).to_be_visible(timeout=10_000)
        expect(page.locator('#cbEndInningSheet')).to_contain_text('Who goes back out?')
        expect(page.locator('#cbEndInningSheet [data-cb-end-same]')).to_contain_text('Same Defense')
        expect(page.locator('#cbEndInningSheet [data-cb-end-new]')).to_contain_text('New Defense')
        assert native_dialogs == [], f'Legacy End Inning confirm still fired: {native_dialogs}'

        # Canceling the sheet must leave the inning and live state untouched.
        page.locator('#cbEndInningSheet .btn-close').click()
        expect(page.locator('#cbEndInningSheet')).to_be_hidden()
        state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert state['game']['is_live'] is True
        assert state['current_inning'] == '1'
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
