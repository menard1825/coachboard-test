"""Mobile browser coverage for staged Live Game field/bench drag-and-drop."""

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


def add_bench_player(page: Page, coachboard_url: str):
    response = page.request.post(
        f'{coachboard_url}/add_player',
        form={
            'name': BENCH_NAME,
            'number': '44',
            'position1': 'SS',
            'throws': 'Right',
            'bats': 'Right',
            'pitcher_role': 'Not a Pitcher',
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
            'game_start_time': '13:00',
            'game_opponent': 'Drag Defense Opponent',
            'game_location': 'Drag Test Field',
            'game_notes': 'Disposable staged drag defense browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Drag Defense Lineup',
        'lineup_data': list(alignment().values()),
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Drag Defense Rotation',
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


def cleanup_game(page: Page, coachboard_url: str, game_id: int, bench_player_id):
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
    if bench_player_id:
        page.request.get(f'{coachboard_url}/delete_player/{bench_player_id}')


def test_phone_main_field_drag_stages_bench_move_then_auto_saves_complete_defense(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    bench_player_id = add_bench_player(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        quick = page.locator('#cbQuickDefense')
        expect(quick).to_be_visible(timeout=15_000)
        expect(quick.locator('.cb-qd-help')).to_contain_text('Drag players right on the field', timeout=10_000)

        ss_spot = quick.locator('[data-cb-position="SS"]')
        bench_wrap = quick.locator('.cb-qd-bench-wrap')
        expect(ss_spot).to_contain_text('Shortstop Shawn')
        expect(bench_wrap).to_be_visible()

        # Dragging a fielder to Bench is staged locally because CoachBoard must
        # never save a defense with an empty position.
        drag(page, ss_spot, bench_wrap)
        expect(ss_spot).to_contain_text('Open — choose player', timeout=10_000)
        expect(quick.locator('.cb-main-draft-banner')).to_be_visible()
        expect(quick.locator('.cb-main-draft-banner')).to_contain_text('SS open')
        expect(quick.locator('[data-cb-move-player="Shortstop Shawn"]')).to_be_visible()

        server_before = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert server_before['current_alignment']['SS'] == 'Shortstop Shawn'
        assert not [
            event for event in server_before.get('rotation_events', [])
            if not event.get('reverted') and event.get('event_type') == 'Bulk Defensive Change'
        ]

        # Filling the open SS spot completes the defense and automatically saves
        # both moves as one authoritative mid-inning defensive event.
        bench_player = quick.locator(f'[data-cb-move-player="{BENCH_NAME}"]')
        expect(bench_player).to_be_visible()
        drag(page, bench_player, ss_spot)

        expect(quick.locator('.cb-main-draft-banner')).not_to_be_visible(timeout=10_000)
        expect(quick.locator('.cb-save-state')).to_contain_text('Saved', timeout=10_000)

        state_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
        assert state_response.ok, state_response.text()
        state = state_response.json()
        assert state['current_alignment']['SS'] == BENCH_NAME
        assert 'Shortstop Shawn' not in state['current_alignment'].values()
        events = [
            event for event in state.get('rotation_events', [])
            if not event.get('reverted') and event.get('event_type') == 'Bulk Defensive Change'
        ]
        assert len(events) == 1
        assert events[0]['inning'] == '1'
        assert events[0]['before_alignment']['SS'] == 'Shortstop Shawn'
        assert events[0]['after_alignment']['SS'] == BENCH_NAME
    finally:
        cleanup_game(page, coachboard_url, game_id, bench_player_id)


def test_phone_drag_field_to_bench_then_bench_to_field_and_save_once(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    bench_player_id = add_bench_player(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
        defense_button = page.locator('#liveDefensiveChangeBtn')
        expect(defense_button).to_be_visible(timeout=15_000)
        defense_button.click()

        editor = page.locator('#cb-live-field-editor')
        expect(editor).to_be_visible(timeout=10_000)
        bench_drop = editor.locator('[data-cb-editor-drop="BENCH"]')
        expect(bench_drop).to_be_visible()

        # First drag a current fielder down to the visible Bench drop zone.
        shortstop = editor.locator('[data-cb-editor-player="Shortstop Shawn"]')
        expect(shortstop).to_be_visible()
        drag(page, shortstop, bench_drop)

        ss_spot = editor.locator('[data-cb-editor-drop="SS"]')
        expect(ss_spot).to_contain_text('Open')
        expect(bench_drop.locator('[data-cb-editor-player="Shortstop Shawn"]')).to_be_visible()

        # Then drag an existing bench player into the newly open shortstop spot.
        bench_player = bench_drop.locator(f'[data-cb-editor-player="{BENCH_NAME}"]')
        expect(bench_player).to_be_visible()
        drag(page, bench_player, ss_spot)

        expect(ss_spot.locator(f'[data-cb-editor-player="{BENCH_NAME}"]')).to_be_visible()
        expect(bench_drop.locator('[data-cb-editor-player="Shortstop Shawn"]')).to_be_visible()
        expect(editor.locator('.cb-lf-change-count')).to_contain_text('2 player moves staged')

        # Both staged moves are committed by one server save.
        editor.locator('[data-cb-editor-save]').click()
        expect(editor).not_to_be_visible(timeout=10_000)

        state_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
        assert state_response.ok, state_response.text()
        state = state_response.json()
        assert state['current_alignment']['SS'] == BENCH_NAME
        assert 'Shortstop Shawn' not in state['current_alignment'].values()
        events = [
            event for event in state.get('rotation_events', [])
            if not event.get('reverted') and event.get('event_type') == 'Bulk Defensive Change'
        ]
        assert len(events) == 1
        assert events[0]['before_alignment']['SS'] == 'Shortstop Shawn'
        assert events[0]['after_alignment']['SS'] == BENCH_NAME
    finally:
        cleanup_game(page, coachboard_url, game_id, bench_player_id)
