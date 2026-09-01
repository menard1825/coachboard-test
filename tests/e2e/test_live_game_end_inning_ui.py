"""Critical browser coverage for the CoachBoard End Inning huddle workflow."""

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

    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'End Inning UI Rotation',
        'innings': {'1': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def test_end_inning_uses_huddle_then_starts_next_inning(page: Page, coachboard_url: str):
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

        huddle = page.locator('#cb-test2-huddle-modal')
        expect(huddle).to_be_visible(timeout=10_000)
        expect(huddle.locator('.modal-title')).to_have_text('End Inning')
        expect(huddle.locator('.cb-t2-huddle-sub')).to_contain_text('Inning 1 is over')
        expect(page.locator('#cb-live-field-editor')).to_have_count(0)
        assert native_dialogs == [], f'Legacy End Inning dialog still fired: {native_dialogs}'

        start_next = huddle.locator('[data-cb-t2-start-inning]')
        expect(start_next).to_be_disabled()
        huddle.locator('[data-cb-t2-choice="current"]').click()
        expect(start_next).to_be_enabled(timeout=10_000)
        expect(start_next).to_have_text('Start Inning 2')

        # The inning does not advance until the coach explicitly starts it.
        before = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert before['current_inning'] == '1'

        start_next.click()
        expect(huddle).not_to_be_visible(timeout=10_000)
        expect(page.locator('#live-inning-display')).to_have_text('2', timeout=10_000)

        state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert state['game']['is_live'] is True
        assert state['current_inning'] == '2'
        assert state['current_alignment'] == alignment()
        assert any(
            event.get('event_type') == 'End Inning' and str(event.get('inning')) == '2'
            for event in state.get('rotation_events', [])
        )
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