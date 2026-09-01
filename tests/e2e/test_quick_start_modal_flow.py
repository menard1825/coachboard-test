"""Browser coverage for the Test 2 First Pitch / Full Plan pregame modes."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
OPPONENT = 'Pregame Modes Opponent'


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


def test_first_pitch_and_full_plan_are_distinct_pregame_modes(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)

    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': '2030-05-10',
            'game_start_time': '09:00',
            'game_opponent': OPPONENT,
            'game_location': 'Pregame Modes Field',
            'game_notes': 'Disposable Test 2 pregame mode test',
        },
    )
    assert created.ok
    games = page.request.get(f'{coachboard_url}/api/games').json()
    game_id = int(next(item for item in games if item.get('opponent') == OPPONENT)['id'])

    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        modes = page.locator('#cb-test2-pregame-modes')
        expect(modes).to_be_visible(timeout=15_000)
        first_pitch = modes.get_by_role('button', name='First Pitch')
        full_plan = modes.get_by_role('button', name='Full Plan')
        expect(first_pitch).to_have_class(re.compile(r'\bactive\b'))
        expect(page.locator('#cb-quick-start-launch')).to_have_count(0)
        expect(page.locator('#cb-quick-start-modal')).to_have_count(0)

        expect(page.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)
        expect(page.locator('#lineup-card-container')).to_be_hidden()
        expect(page.locator('#pitching-log-container')).to_be_hidden()

        full_plan.click()
        expect(full_plan).to_have_class(re.compile(r'\bactive\b'))
        expect(page.locator('#lineup-card-container')).to_be_visible(timeout=10_000)
        expect(page.locator('#pitching-log-container')).to_be_visible(timeout=10_000)

        first_pitch.click()
        expect(first_pitch).to_have_class(re.compile(r'\bactive\b'))
        expect(page.locator('#lineup-card-container')).to_be_hidden()
        expect(page.locator('#pitching-log-container')).to_be_hidden()
    finally:
        page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
