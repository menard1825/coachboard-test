"""Browser coverage for actual vs planned bench innings during Live Game."""

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
BENCH_NAME = 'Bench Plan Blake'


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


def base_alignment():
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
            'position1': 'C',
            'throws': 'Right',
            'bats': 'Right',
            'pitcher_role': 'Not a Pitcher',
        },
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert response.status == 200, response.text()
    assert response.json()['status'] == 'success'


def create_game(page: Page, coachboard_url: str):
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=8)).isoformat(),
            'game_start_time': '13:00',
            'game_opponent': 'Bench Plan Opponent',
            'game_location': 'Bench Plan Field',
            'game_notes': 'Disposable planned-bench browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Bench Plan Lineup',
        'lineup_data': list(base_alignment().values()),
        'associated_game_id': game_id,
    })

    inning_two = base_alignment()
    inning_two['C'] = BENCH_NAME
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Bench Plan Rotation',
        'innings': {
            '1': base_alignment(),
            '2': inning_two,
            '3': base_alignment(),
        },
        'associated_game_id': game_id,
    })
    return game_id


def test_bench_report_shows_actual_and_future_planned_sits(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    add_bench_player(page, coachboard_url)
    game_id = create_game(page, coachboard_url)
    bench_player_id = None

    try:
        started = post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        bench_player = next(player for player in started['state']['roster'] if player['name'] == BENCH_NAME)
        bench_player_id = int(bench_player['id'])

        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        report_button = page.locator('[data-cb-bench-report]')
        expect(report_button).to_be_visible(timeout=15_000)
        report_button.click()

        modal = page.locator('#cbBenchReportModal')
        expect(modal).to_be_visible(timeout=10_000)
        expect(modal).to_contain_text('Actual + planned bench innings')

        bench_row = modal.locator('.cb-br-row').filter(has_text=BENCH_NAME)
        expect(bench_row).to_have_count(1)
        expect(bench_row).to_have_class(re.compile(r'\bcurrent\b'))
        expect(bench_row).to_contain_text('Sat: None')
        expect(bench_row).to_contain_text('Inning 1 now')
        expect(bench_row).to_contain_text('Planned to sit: 3')

        catcher_row = modal.locator('.cb-br-row').filter(has_text='Catcher Cole')
        expect(catcher_row).to_have_count(1)
        expect(catcher_row).to_contain_text('Sat: None')
        expect(catcher_row).to_contain_text('Planned to sit: 2')

        modal.get_by_role('button', name='Back to Game').click()
        expect(modal).to_be_hidden()

        next_board = page.locator('#live-board-prep-v3')
        expect(next_board).to_be_visible(timeout=10_000)
        expect(next_board).to_contain_text('Your planned Inning 2 defense is ready.')
        expect(next_board).to_contain_text('Pregame Defense')
        expect(next_board.get_by_role('button', name='Use Planned Defense')).to_be_enabled()
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
