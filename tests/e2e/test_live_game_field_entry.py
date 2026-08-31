"""Browser coverage for entering the unified Live Game editor from a current fielder."""

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
            'game_date': (date.today() + timedelta(days=9)).isoformat(),
            'game_start_time': '13:30',
            'game_opponent': 'Field Entry Opponent',
            'game_location': 'Field Entry Test Field',
            'game_notes': 'Disposable current-fielder editor-entry browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Field Entry Lineup',
        'lineup_data': list(alignment().values()),
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Field Entry Rotation',
        'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def drag(page: Page, source, target):
    source_box = source.bounding_box()
    target_box = target.bounding_box()
    assert source_box, 'Drag source has no bounding box.'
    assert target_box, 'Drag target has no bounding box.'

    sx = source_box['x'] + source_box['width'] / 2
    sy = source_box['y'] + source_box['height'] / 2
    tx = target_box['x'] + target_box['width'] / 2
    ty = target_box['y'] + target_box['height'] / 2

    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move(tx, ty, steps=12)
    page.mouse.up()


def test_phone_current_fielder_opens_unified_editor_preselected_and_can_drag_to_bench(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        quick_defense = page.locator('#cbQuickDefense')
        expect(quick_defense).to_be_visible(timeout=15_000)
        current_shortstop = quick_defense.locator('[data-cb-position="SS"]')
        expect(current_shortstop).to_contain_text('Shortstop Shawn')
        current_shortstop.click()

        editor = page.locator('#cb-live-field-editor')
        expect(editor).to_be_visible(timeout=10_000)
        expect(editor.locator('.modal-title')).to_have_text('On Field Now')

        shortstop = editor.locator('[data-cb-editor-player="Shortstop Shawn"]')
        expect(shortstop).to_be_visible()
        expect(shortstop).to_have_class(re.compile(r'\bselected\b'))

        bench = editor.locator('[data-cb-editor-drop="BENCH"]')
        expect(bench).to_be_visible()
        drag(page, shortstop, bench)

        expect(editor.locator('[data-cb-editor-drop="SS"]')).to_contain_text('Open')
        expect(bench.locator('[data-cb-editor-player="Shortstop Shawn"]')).to_be_visible()

        # This test validates the staging interaction only. Do not persist an
        # intentionally incomplete defense with SS open.
        editor.get_by_role('button', name='Cancel').click()
        expect(editor).not_to_be_visible(timeout=10_000)
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
