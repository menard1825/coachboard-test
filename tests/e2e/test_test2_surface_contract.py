"""Locked Test 2 coach-facing contract for pregame and Live Game surfaces."""

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


def inning_two_alignment():
    value = alignment()
    value['SS'], value['2B'] = value['2B'], value['SS']
    return value


def post_json(page: Page, coachboard_url: str, path: str, data):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == 200, f'POST {path} returned {response.status}: {response.text()}'
    payload = response.json()
    assert payload.get('status') == 'success', payload
    return payload


def create_game_without_lineup(page: Page, coachboard_url: str):
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=12)).isoformat(),
            'game_start_time': '10:00',
            'game_opponent': 'Test 2 Surface Opponent',
            'game_location': 'Test 2 Contract Field',
            'game_notes': 'Disposable Test 2 surface contract game',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Test 2 Surface Rotation',
        'innings': {'1': alignment(), '2': inning_two_alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def test_test2_pregame_modes_quick_field_and_pause_resume(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    game_id = create_game_without_lineup(page, coachboard_url)

    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        modes = page.locator('#cb-test2-pregame-modes')
        expect(modes).to_be_visible(timeout=15_000)
        first_pitch = modes.locator('[data-cb-t2-mode="first-pitch"]')
        full_plan = modes.locator('[data-cb-t2-mode="full-plan"]')
        expect(first_pitch).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('body')).to_have_class(re.compile(r'\bcb-test2-first-pitch\b'))

        # First Pitch is a real reduced workspace, not a label on the full planner.
        expect(page.locator('#lineup-card-container')).not_to_be_visible()
        expect(page.locator('#pitching-log-container')).not_to_be_visible()
        expect(page.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)
        expect(page.locator('#pregame-defense-editor-v3 .pde-title')).to_have_text('First-pitch defense')
        expect(page.locator('#liveGameModeToggle')).to_have_count(0)
        expect(page.locator('#cb-quick-start-launch')).to_have_count(0)
        expect(page.locator('#cb-quick-start-modal')).to_have_count(0)

        full_plan.click()
        expect(full_plan).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('body')).to_have_class(re.compile(r'\bcb-test2-full-plan\b'))
        expect(page.locator('#lineup-card-container')).to_be_visible()
        expect(page.locator('#pitching-log-container')).to_be_visible()
        inning_two = page.locator('#inning-btn-group input[name="inning-radio"][value="2"]')
        expect(inning_two).to_have_count(1)
        inning_two.click(force=True)
        expect(inning_two).to_be_checked()

        first_pitch.click()
        inning_one = page.locator('#inning-btn-group input[name="inning-radio"][value="1"]')
        expect(inning_one).to_be_checked(timeout=5_000)
        expect(page.locator('#lineup-card-container')).not_to_be_visible()

        # Empty batting order is optional. The same server contract must allow the start.
        readiness = page.request.get(f'{coachboard_url}/api/game-day/{game_id}/readiness').json()
        assert readiness['readiness']['lineup_ready'] is False
        assert readiness['ready'] is True, readiness
        started = post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        assert started['state']['game']['is_live'] is True

        page.reload(wait_until='domcontentloaded')
        quick = page.locator('#cbQuickDefense')
        expect(quick).to_be_visible(timeout=15_000)
        expect(quick.locator('.cb-qd-title')).to_have_text('Quick Field')
        expect(page.locator('#cb-test2-pregame-modes')).to_have_count(0)

        for selector in (
            '#liveDefensiveChangeBtn', '#liveSetDefenseBtnCoach', '#live-bulk-defense-coach',
            '[data-cb-full-defense]', '#live-defense-v2', '#live-defense-destination-v2',
            '#liveDefensiveSwapModal', '#cb-live-field-editor', '#liveGameModeToggle',
        ):
            expect(page.locator(selector)).to_have_count(0)

        header = page.locator('#cbDugoutHeader')
        expect(header).to_be_visible(timeout=15_000)
        pause = header.locator('[data-cb-clock]')
        expect(pause).to_have_text('Pause', timeout=10_000)
        pause.click()
        expect(pause).to_have_text('Resume', timeout=10_000)
        clock = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/clock').json()['clock']
        assert clock['is_paused'] is True

        pause.click()
        expect(pause).to_have_text('Pause', timeout=10_000)
        clock = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/clock').json()['clock']
        assert clock['is_paused'] is False
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