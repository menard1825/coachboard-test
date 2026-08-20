"""Safety-net coverage ensuring every remaining route fails cleanly, never with 500."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill('playwright-coach')
    page.locator('#password').fill('playwright-password')
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def test_remaining_get_routes_fail_cleanly_for_missing_records(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    paths = (
        '/switch_team/99999',
        '/reset_password/not-a-valid-reset-token',
        '/rotation-template/99999',
        '/starting-defense-template/99999',
        '/game/99999',
        '/game-day/99999/report',
        '/api/game_data/99999',
        '/api/game-day/99999/readiness',
        '/api/game-day/99999/pitching-rules',
        '/api/live-game/99999/state',
        '/api/live-game/99999/clock',
        '/api/live-game/99999/next-inning-prep',
        '/delete_game/99999',
        '/delete_lineup/99999',
        '/delete_rotation/99999',
        '/delete_pitching/99999',
        '/delete_player/99999',
        '/delete_focus/99999',
        '/complete_focus/99999',
        '/delete_lesson_info/99999',
        '/delete_scouted_player/targets/99999',
        '/delete_note/team_notes/99999',
        '/delete_practice_plan/99999',
        '/delete_task/99999/99999',
        '/delete_sign/99999',
        '/admin/delete_team/99999',
    )
    for path in paths:
        response = page.request.get(f'{coachboard_url}{path}', max_redirects=0)
        assert response.status < 500, f'GET {path} crashed with {response.status}: {response.text()}'


def test_remaining_form_routes_fail_cleanly_for_invalid_input(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    paths = (
        '/add_game',
        '/edit_game/99999',
        '/game/99999/update_absences',
        '/add_pitching',
        '/edit_pitching/99999',
        '/add_player',
        '/update_player_inline/99999',
        '/add_focus/No Such Player',
        '/update_focus/99999',
        '/update_lesson_info/99999',
        '/add_note/team_notes',
        '/edit_note',
        '/add_practice_plan',
        '/edit_practice_plan/99999',
        '/update_practice_attendance/99999',
        '/add_task_to_plan/99999',
        '/add_sign',
        '/update_sign/99999',
        '/move_scouted_player/targets/committed/99999',
        '/move_scouted_player_to_roster/99999',
        '/admin/add_user',
        '/admin/edit_user/no-such-user',
        '/admin/reset_password/no-such-user',
        '/admin/delete_user/no-such-user',
        '/admin/settings/update',
        '/admin/settings/regulation-innings',
        '/admin/upload_logo',
        '/admin/create_team',
        '/admin/rollover_season',
        '/game-day/add',
        '/game-day/99999/notes',
    )
    for path in paths:
        form = {}
        if path == '/edit_note':
            form = {'note_id': '99999', 'note_type': 'team_notes', 'note_text': 'No change'}
        response = page.request.post(
            f'{coachboard_url}{path}',
            form=form,
            max_redirects=0,
        )
        assert response.status < 500, f'POST {path} crashed with {response.status}: {response.text()}'


def test_remaining_json_routes_fail_cleanly_for_invalid_input(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    post_paths = (
        '/add_lineup',
        '/edit_lineup/99999',
        '/save_rotation',
        '/save_rotation_as_template',
        '/add_scouted_player',
        '/save_player_order',
        '/save_player_target',
        '/update_pitching_profile/99999',
        '/clone_practice_plan/99999',
        '/update_task_status/99999/99999',
        '/api/rotation-template/save',
        '/api/starting-defense-template/save',
        '/api/game-day/99999/pitching-rules',
        '/api/live-game/99999/start',
        '/api/live-game/99999/change-pitcher',
        '/api/live-game/99999/defensive-change',
        '/api/live-game/99999/end-inning',
        '/api/live-game/99999/undo',
        '/api/live-game/99999/end',
        '/api/live-game/99999/end-with-pitching',
        '/api/live-game/99999/pitching-plan',
        '/api/live-game/99999/pitching-profile/99999',
        '/api/live-game/99999/complete-pitcher-change',
        '/api/live-game/99999/set-defense',
        '/api/live-game/99999/clock',
        '/api/live-game/99999/next-inning-prep',
        '/game-day/99999/delete',
    )
    for path in post_paths:
        response = page.request.post(f'{coachboard_url}{path}', data={})
        assert response.status < 500, f'POST {path} crashed with {response.status}: {response.text()}'

    delete_paths = (
        '/api/live-game/99999/pitching-plan/99999',
        '/api/live-game/99999/next-inning-prep',
    )
    for path in delete_paths:
        response = page.request.fetch(f'{coachboard_url}{path}', method='DELETE')
        assert response.status < 500, f'DELETE {path} crashed with {response.status}: {response.text()}'
