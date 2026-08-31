"""Phone-first Live Game defense/bench workflow coverage."""

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
BENCH_NAME = 'Bench Blake Longname'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:games|overview))?$'))


def post_json(page: Page, coachboard_url: str, path: str, data):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == 200, f'POST {path} returned {response.status}: {response.text()}'
    payload = response.json()
    assert payload.get('status') == 'success', payload
    return payload


def get_json(page: Page, coachboard_url: str, path: str):
    response = page.request.get(f'{coachboard_url}{path}')
    assert response.status == 200, f'GET {path} returned {response.status}: {response.text()}'
    return response.json()


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
            'number': '22',
            'position1': 'OF',
            'throws': 'Right',
            'bats': 'Right',
            'pitcher_role': 'Not a Pitcher',
        },
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert response.status == 200, response.text()
    assert response.json()['status'] == 'success'


def create_game_with_plan(page: Page, coachboard_url: str):
    game_date = (date.today() + timedelta(days=7)).isoformat()
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': game_date,
            'game_start_time': '14:00',
            'game_opponent': 'Quick Defense Opponent',
            'game_location': 'Quick Defense Field',
            'game_notes': 'Disposable quick-defense browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Quick Defense Lineup',
        'lineup_data': list(alignment().values()),
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Quick Defense Rotation',
        'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def test_phone_live_game_keeps_field_and_bench_visible_and_saves_tap_moves(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    add_bench_player(page, coachboard_url)
    game_id = create_game_with_plan(page, coachboard_url)
    bench_player_id = None

    try:
        started = post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        bench_player = next(player for player in started['state']['roster'] if player['name'] == BENCH_NAME)
        bench_player_id = bench_player['id']

        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        quick = page.locator('#cbQuickDefense')
        expect(quick).to_be_visible(timeout=15_000)

        expect(page.locator('#liveSetDefenseBtnCoach')).to_have_count(0)
        expect(page.locator('#live-bulk-defense-coach')).to_have_count(0)

        expect(quick.locator('.cb-qd-field')).to_be_visible()
        bench_button = quick.locator(f'[data-cb-move-player="{BENCH_NAME}"]')
        expect(bench_button).to_be_visible()
        expect(bench_button).to_contain_text(BENCH_NAME)
        expect(bench_button.locator('.cb-bench-note')).not_to_be_visible()
        expect(page.locator('#cbDugoutHeader .cb-dh-pitcher')).to_be_visible()
        expect(page.locator('#coach-pitcher-slot')).not_to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2')

        labels = quick.locator('.cb-qd-name')
        samples = labels.evaluate_all("""items => items.map(el => {
            const s = getComputedStyle(el);
            return {
                text: (el.textContent || '').trim(),
                whiteSpace: s.whiteSpace,
                overflow: s.overflow,
                textOverflow: s.textOverflow,
                scrollWidth: el.scrollWidth,
                clientWidth: el.clientWidth,
                scrollHeight: el.scrollHeight,
                clientHeight: el.clientHeight,
            };
        })""")
        for sample in samples:
            assert sample['whiteSpace'] == 'normal', sample
            assert sample['overflow'] == 'visible', sample
            assert sample['textOverflow'] == 'clip', sample
            assert sample['scrollWidth'] <= sample['clientWidth'] + 1, sample
            assert sample['scrollHeight'] <= sample['clientHeight'] + 1, sample

        # Bench -> CF keeps the quick substitution popup. The outgoing CF becomes bench.
        bench_button.click()
        modal = page.locator('#cbQuickMoveModal')
        expect(modal).to_be_visible()
        expect(modal).to_contain_text(f'{BENCH_NAME} is currently on the bench')
        modal.locator('[data-cb-destination="CF"]').click()
        expect(modal).not_to_be_visible(timeout=10_000)
        expect(quick.locator('[data-cb-position="CF"]')).to_contain_text(BENCH_NAME, timeout=10_000)
        expect(quick.locator('[data-cb-move-player="Center Casey"]')).to_be_visible(timeout=10_000)
        expect(quick.locator('.cb-save-state')).to_contain_text('Saved')

        state = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
        assert state['current_alignment']['CF'] == BENCH_NAME
        assert 'Center Casey' not in state['current_alignment'].values()

        # Tapping a current fielder now enters the unified editor with that
        # fielder preselected. Dedicated drag-defense coverage verifies moves
        # inside this editor, including field -> Bench.
        quick.locator('[data-cb-position="SS"]').click()
        editor = page.locator('#cb-live-field-editor')
        expect(editor).to_be_visible()
        shortstop = editor.locator('[data-cb-editor-player="Shortstop Shawn"]')
        expect(shortstop).to_have_class(re.compile(r'\bselected\b'))
        expect(editor.locator('[data-cb-editor-drop="BENCH"]')).to_be_visible()
        editor.get_by_role('button', name='Cancel').click()
        expect(editor).not_to_be_visible(timeout=10_000)

        state = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
        assert state['current_alignment']['SS'] == 'Shortstop Shawn'
        assert state['current_alignment']['2B'] == 'Second Sam'

        next_board = page.locator('#live-board-prep-v3')
        expect(next_board).to_be_visible()
        preview = next_board.locator('.bp-main > section').last
        if preview.count():
            expect(preview).not_to_be_visible()
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
        if bench_player_id:
            page.request.get(f'{coachboard_url}/delete_player/{bench_player_id}')
