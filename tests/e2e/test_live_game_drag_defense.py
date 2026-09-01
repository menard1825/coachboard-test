"""Mobile browser coverage for Quick Field staged drag-and-drop."""

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
BENCH_NAME = 'Drag Bench Blake'


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
        'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
        '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
        'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
    }


def add_bench_player(page: Page, coachboard_url: str):
    response = page.request.post(
        f'{coachboard_url}/add_player',
        form={
            'name': BENCH_NAME, 'number': '44', 'position1': 'SS',
            'throws': 'Right', 'bats': 'Right', 'pitcher_role': 'Not a Pitcher',
        },
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert response.status == 200, response.text()
    payload = response.json()
    assert payload['status'] == 'success'
    return int(payload['player']['id']) if payload.get('player', {}).get('id') else None


def create_game(page: Page, coachboard_url: str):
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=8)).isoformat(),
            'game_start_time': '13:00', 'game_opponent': 'Drag Defense Opponent',
            'game_location': 'Drag Test Field', 'game_notes': 'Disposable Quick Field drag test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))
    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Drag Defense Lineup', 'lineup_data': list(alignment().values()),
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Drag Defense Rotation', 'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def drag(page: Page, source, target):
    source_box = source.bounding_box()
    target_box = target.bounding_box()
    assert source_box and target_box
    page.mouse.move(source_box['x'] + source_box['width'] / 2, source_box['y'] + source_box['height'] / 2)
    page.mouse.down()
    page.mouse.move(target_box['x'] + target_box['width'] / 2, target_box['y'] + target_box['height'] / 2, steps=12)
    page.mouse.up()


def cleanup(page: Page, coachboard_url: str, game_id: int, player_id):
    state_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
    if state_response.ok and state_response.json().get('game', {}).get('is_live'):
        page.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/end-with-pitching',
            data={'defer_pitching': True, 'end_reason': 'manual', 'current_inning_played': True},
        )
    page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
    if player_id:
        page.request.get(f'{coachboard_url}/delete_player/{player_id}')


def test_phone_quick_field_stages_bench_move_then_saves_complete_defense(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    player_id = add_bench_player(page, coachboard_url)
    game_id = create_game(page, coachboard_url)
    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        quick = page.locator('#cbQuickDefense')
        expect(quick).to_be_visible(timeout=15_000)
        expect(quick.locator('.cb-qd-help')).to_contain_text('field and bench')
        expect(page.locator('#liveDefensiveChangeBtn')).to_have_count(0)
        expect(page.locator('#cb-live-field-editor')).to_have_count(0)

        ss = quick.locator('[data-cb-position="SS"]')
        bench = quick.locator('.cb-qd-bench-wrap')
        drag(page, ss, bench)
        expect(ss).to_contain_text('Open — choose player', timeout=10_000)
        expect(quick.locator('.cb-main-draft-banner')).to_contain_text('SS open')

        server_before = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert server_before['current_alignment']['SS'] == 'Shortstop Shawn'

        bench_player = quick.locator(f'[data-cb-move-player="{BENCH_NAME}"]')
        expect(bench_player).to_be_visible()
        drag(page, bench_player, ss)
        expect(quick.locator('.cb-main-draft-banner')).not_to_be_visible(timeout=10_000)
        expect(quick.locator('.cb-save-state')).to_contain_text('Saved', timeout=10_000)

        state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert state['current_alignment']['SS'] == BENCH_NAME
        events = [e for e in state.get('rotation_events', []) if not e.get('reverted') and e.get('event_type') == 'Bulk Defensive Change']
        assert len(events) == 1
        assert events[0]['before_alignment']['SS'] == 'Shortstop Shawn'
        assert events[0]['after_alignment']['SS'] == BENCH_NAME
    finally:
        cleanup(page, coachboard_url, game_id, player_id)


def test_phone_quick_field_swaps_two_fielders_without_second_editor(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)
    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        quick = page.locator('#cbQuickDefense')
        expect(quick).to_be_visible(timeout=15_000)
        ss = quick.locator('[data-cb-position="SS"]')
        second = quick.locator('[data-cb-position="2B"]')
        expect(ss).to_contain_text('Shortstop Shawn')
        expect(second).to_contain_text('Second Sam')

        drag(page, ss, second)
        expect(quick.locator('.cb-save-state')).to_contain_text('Saved', timeout=10_000)
        expect(page.locator('#cb-live-field-editor')).to_have_count(0)

        state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert state['current_alignment']['2B'] == 'Shortstop Shawn'
        assert state['current_alignment']['SS'] == 'Second Sam'
    finally:
        cleanup(page, coachboard_url, game_id, None)
