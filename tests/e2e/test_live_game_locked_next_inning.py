"""Browser coverage for starting a coach-confirmed next-inning defense from the huddle."""

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
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:games|overview))?$'))


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
            'game_date': (date.today() + timedelta(days=11)).isoformat(),
            'game_start_time': '16:00',
            'game_opponent': 'Locked Next Inning Opponent',
            'game_location': 'Locked Prep Test Field',
            'game_notes': 'Disposable locked next inning browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Locked Next Inning Rotation',
        'innings': {'1': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def test_locked_next_inning_huddle_requires_explicit_start(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 430, 'height': 932})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        started = post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        assert started['state']['game']['is_live'] is True
        assert started['state']['current_inning'] == '1'

        locked = post_json(page, coachboard_url, f'/api/live-game/{game_id}/next-inning-prep', {
            'mode': 'current',
        })
        assert locked['next_inning'] == '2'
        assert locked['confirmed']['inning'] == '2'
        assert locked['confirmed']['alignment'] == alignment()

        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
        expect(page.locator('#live-inning-display')).to_have_text('1')

        page.locator('#liveEndInningBtn').click()
        huddle = page.locator('#cb-test2-huddle-modal')
        expect(huddle).to_be_visible(timeout=10_000)
        expect(page.locator('#cb-live-field-editor')).to_have_count(0)
        start = huddle.locator('[data-cb-t2-start-inning]')
        expect(start).to_be_enabled(timeout=10_000)
        expect(start).to_have_text('Start Inning 2')

        # A locked defense is ready, but End Inning itself no longer advances the game.
        expect(page.locator('#live-inning-display')).to_have_text('1')
        start.click()
        expect(huddle).not_to_be_visible(timeout=10_000)
        expect(page.locator('#live-inning-display')).to_have_text('2', timeout=10_000)

        state_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
        assert state_response.ok, state_response.text()
        state = state_response.json()
        assert state['current_inning'] == '2'
        assert state['current_alignment'] == alignment()

        prep_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep')
        assert prep_response.ok, prep_response.text()
        prep = prep_response.json()
        assert prep['current_inning'] == '2'
        assert prep['next_inning'] == '3'
        assert prep['confirmed'] is None
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


def test_new_defense_is_position_first_and_follows_vacancy(
    page: Page,
    coachboard_url: str,
):
    page.set_viewport_size({'width': 430, 'height': 932})
    login(page, coachboard_url)

    bench_name = 'Next Bench Nate'
    bench_id = None
    game_id = None

    add = page.request.post(
        f'{coachboard_url}/add_player',
        form={
            'name': bench_name,
            'number': '24',
            'position1': 'SS',
            'throws': 'Right',
            'bats': 'Right',
            'pitcher_role': 'Not a Pitcher',
        },
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert add.status == 200, add.text()
    add_payload = add.json()
    assert add_payload['status'] == 'success'

    game_id = create_game(page, coachboard_url)

    try:
        started = post_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/start',
            {},
        )
        assert started['state']['current_inning'] == '1'

        bench_player = next(
            player
            for player in started['state']['roster']
            if player['name'] == bench_name
        )
        bench_id = int(bench_player['id'])

        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        next_board = page.locator('#live-board-prep-v3')
        expect(next_board).to_be_visible(timeout=15_000)

        expect(
            next_board.locator('.nxd-plan-note')
        ).to_contain_text(
            'Next inning only'
        )

        expect(
            next_board.locator('.nxd-plan-note')
        ).to_contain_text(
            'Current pitcher stays'
        )

        next_board.get_by_role(
            'button',
            name='New Defense',
        ).click()

        modal = page.locator('#next-inning-adjust-modal')
        expect(modal).to_be_visible(timeout=10_000)

        expect(
            modal.locator('.modal-header .small.text-muted')
        ).to_contain_text(
            'plans Inning 2 only'
        )

        expect(
            modal.locator('.ni-pitcher-note')
        ).to_contain_text(
            'stays at P'
        )

        expect(
            modal.locator('.ni-selected')
        ).to_contain_text(
            'Tap the position you want to change'
        )

        # Coach thinks "I want to change 2B" first.
        modal.locator('[data-ni-pos="2B"]').click()

        chooser = modal.locator('.ni-player-chooser')
        expect(chooser).to_contain_text('Who plays 2B?')
        expect(chooser).to_contain_text('Second Sam')

        # Pick somebody already on the field.
        # CoachBoard should move that fielder to 2B, bench the old 2B,
        # and immediately follow the newly-open SS position.
        shortstop = chooser.locator(
            '[data-ni-player="Shortstop Shawn"]'
        )
        expect(shortstop).to_contain_text('SS → 2B')
        shortstop.click()

        expect(
            modal.locator('[data-ni-pos="2B"]')
        ).to_contain_text('Shortstop Shawn')

        expect(
            modal.locator('[data-ni-pos="SS"]')
        ).to_contain_text('Open')

        # Second Sam was displaced from 2B and should now be on the bench.
        expect(
            modal.locator('.ni-bench')
        ).to_contain_text('Second Sam')

        # No second position tap is required. CoachBoard should already
        # be asking the coach to fill the vacancy left at SS.
        chooser = modal.locator('.ni-player-chooser')
        expect(chooser).to_contain_text('Who plays SS?')

        bench_choice = chooser.locator(
            f'[data-ni-player="{bench_name}"]'
        )
        expect(bench_choice).to_contain_text('BENCH → SS')
        bench_choice.click()

        expect(
            modal.locator('[data-ni-pos="SS"]')
        ).to_contain_text(bench_name)

        expect(
            modal.locator('.ni-bench')
        ).to_contain_text('Second Sam')

        # Pitcher is fixed in this planner.
        expect(
            modal.locator('[data-ni-pos="P"]')
        ).to_contain_text('Pitcher Pat')

        modal.locator('#save-next-inning-adjust').click()
        expect(modal).not_to_be_visible(timeout=10_000)

        prep_response = page.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep'
        )
        assert prep_response.ok, prep_response.text()
        prep = prep_response.json()

        confirmed = prep['confirmed']['alignment']

        assert confirmed['P'] == 'Pitcher Pat'
        assert confirmed['2B'] == 'Shortstop Shawn'
        assert confirmed['SS'] == bench_name
        assert 'Second Sam' not in confirmed.values()

    finally:
        if game_id is not None:
            state_response = page.request.get(
                f'{coachboard_url}/api/live-game/{game_id}/state'
            )

            if (
                state_response.ok
                and state_response.json()
                .get('game', {})
                .get('is_live')
            ):
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

        if bench_id is not None:
            page.request.get(
                f'{coachboard_url}/delete_player/{bench_id}'
            )
