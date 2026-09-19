"""Critical browser coverage for one-tap Live Game End Inning."""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()

    expect(page).to_have_url(
        re.compile(
            rf'^{re.escape(coachboard_url)}/?'
            rf'(?:#(?:overview|games))?$'
        )
    )


def post_json(page: Page, coachboard_url: str, path: str, data):
    response = page.request.post(
        f'{coachboard_url}{path}',
        data=data,
    )

    assert response.status == 200, (
        f'POST {path} returned '
        f'{response.status}: {response.text()}'
    )

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
            'game_date':
                (date.today() + timedelta(days=7)).isoformat(),
            'game_start_time': '11:00',
            'game_opponent': 'Direct End Inning Opponent',
            'game_location': 'Workflow Test Field',
            'game_notes': 'Disposable direct End Inning test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )

    assert response.status in {302, 303}

    match = re.search(
        r'/game/(\d+)',
        response.headers.get('location') or '',
    )

    assert match
    game_id = int(match.group(1))

    post_json(
        page,
        coachboard_url,
        '/save_rotation',
        {
            'title': 'Direct End Inning Rotation',
            'innings': {
                '1': alignment(),
            },
            'associated_game_id': game_id,
        },
    )

    return game_id


def test_end_inning_is_one_tap_and_carries_current_when_no_plan(
    page: Page,
    coachboard_url: str,
):
    page.set_viewport_size(
        {
            'width': 390,
            'height': 844,
        }
    )

    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        start = page.locator(
            '#gm-mobile-start-game'
        )

        expect(
            start
        ).to_be_visible(
            timeout=15_000
        )

        start.click()

        expect(
            page.locator(
                '#live-game-overlay'
            )
        ).to_be_visible(
            timeout=15_000
        )

        expect(
            page.locator(
                '#cb-now-next-switch'
            )
        ).to_be_visible(
            timeout=15_000
        )

        prep = page.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/next-inning-prep'
        ).json()

        assert prep['next_inning'] == '2'
        assert prep['confirmed']['source'] == 'current'
        assert prep['confirmed']['alignment'] == alignment()

        page.locator(
            '#liveEndInningBtn'
        ).click()

        expect(
            page.locator(
                '#cb-test2-huddle-modal'
            )
        ).to_have_count(0)

        expect(
            page.locator(
                '#live-inning-display'
            )
        ).to_have_text(
            '2',
            timeout=10_000,
        )

        state = page.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/state'
        ).json()

        assert state['current_inning'] == '2'
        assert state['current_alignment'] == alignment()

    finally:
        state_response = page.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/state'
        )

        if (
            state_response.ok
            and state_response.json()
            .get('game', {})
            .get('is_live')
        ):
            page.request.post(
                f'{coachboard_url}/api/live-game/'
                f'{game_id}/end-with-pitching',
                data={
                    'defer_pitching': True,
                    'end_reason': 'manual',
                    'current_inning_played': True,
                },
            )

        page.request.post(
            f'{coachboard_url}/game-day/'
            f'{game_id}/delete',
            headers={
                'Accept': 'application/json',
            },
        )

def test_phone_next_inning_uses_bottom_dock_without_covering_content(
    page: Page,
    coachboard_url: str,
):
    page.set_viewport_size(
        {
            'width': 390,
            'height': 844,
        }
    )

    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        start = page.locator('#gm-mobile-start-game')
        expect(start).to_be_visible(timeout=15_000)
        start.click()

        expect(
            page.locator('#live-game-overlay')
        ).to_be_visible(timeout=15_000)

        expect(
            page.locator('#cb-now-next-switch')
        ).to_be_visible(timeout=15_000)

        page.locator(
            '#cb-now-next-switch [data-now-next="next"]'
        ).click()

        expect(
            page.locator('#live-board-prep-v3')
        ).to_be_visible(timeout=10_000)

        expect(
            page.locator('#liveEndInningBtn')
        ).to_be_visible()

        page.wait_for_timeout(100)

        expect(
            page.locator('#coach-action-slot')
        ).to_have_class(
            re.compile(r'\bcb-single-live-action\b')
        )

        page.evaluate(
            'window.scrollTo(0, document.documentElement.scrollHeight)'
        )
        page.wait_for_timeout(100)

        geometry = page.evaluate(
            '''() => {
              const dock = document
                .querySelector('#coach-action-slot')
                .getBoundingClientRect();

              const end = document
                .querySelector('#liveEndInningBtn')
                .getBoundingClientRect();

              const next = document
                .querySelector('#live-board-prep-v3')
                .getBoundingClientRect();

              const shell = document
                .querySelector('.coach-live-shell');

              const shellStyle = getComputedStyle(shell);
              const dockStyle = getComputedStyle(
                document.querySelector('#coach-action-slot')
              );

              return {
                dockTop: dock.top,
                dockBottom: dock.bottom,
                dockPosition: dockStyle.position,
                endWidth: end.width,
                nextBottom: next.bottom,
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
                shellPaddingBottom:
                  parseFloat(shellStyle.paddingBottom) || 0,
                scrollWidth:
                  document.documentElement.scrollWidth,
                clientWidth:
                  document.documentElement.clientWidth,
              };
            }'''
        )

        assert geometry['dockPosition'] == 'fixed', geometry

        assert abs(
            geometry['dockBottom']
            - geometry['viewportHeight']
        ) <= 2, geometry

        # Nearly full phone width with normal page gutters.
        assert geometry['endWidth'] >= (
            geometry['viewportWidth'] - 30
        ), geometry

        # Reserved bottom clearance lets all Next Inning content move
        # completely above the dock instead of being covered by it.
        assert geometry['shellPaddingBottom'] >= 90, geometry

        assert geometry['nextBottom'] <= (
            geometry['dockTop'] + 2
        ), geometry

        assert geometry['scrollWidth'] <= (
            geometry['clientWidth'] + 2
        ), geometry

    finally:
        state_response = page.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/state'
        )

        if (
            state_response.ok
            and state_response.json()
            .get('game', {})
            .get('is_live')
        ):
            page.request.post(
                f'{coachboard_url}/api/live-game/'
                f'{game_id}/end-with-pitching',
                data={
                    'defer_pitching': True,
                    'end_reason': 'manual',
                    'current_inning_played': True,
                },
            )

        page.request.post(
            f'{coachboard_url}/game-day/'
            f'{game_id}/delete',
            headers={
                'Accept': 'application/json',
            },
        )


def test_end_inning_warns_but_can_continue_with_open_position(
    page: Page,
    coachboard_url: str,
):
    page.set_viewport_size(
        {
            'width': 390,
            'height': 844,
        }
    )

    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        start = page.locator('#gm-mobile-start-game')
        expect(start).to_be_visible(timeout=15_000)
        start.click()

        expect(
            page.locator('#live-game-overlay')
        ).to_be_visible(timeout=15_000)

        state = page.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        ).json()

        sequence = max(
            [
                int(event.get('sequence') or 0)
                for event in state.get(
                    'rotation_events',
                    [],
                )
                if not event.get('reverted')
            ]
            or [0]
        )

        incomplete = dict(
            state['current_alignment']
        )
        incomplete.pop('2B')

        edited = page.request.post(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/defense-edit',
            data={
                'alignment': incomplete,
                'base_sequence': sequence,
            },
        )

        assert edited.status == 200, edited.text()

        page.reload(
            wait_until='domcontentloaded'
        )

        expect(
            page.locator('#liveEndInningBtn')
        ).to_be_visible(timeout=15_000)

        page.locator(
            '#liveEndInningBtn'
        ).click()

        warning = page.locator(
            '#cbOpenDefenseEndModal'
        )

        expect(
            warning
        ).to_be_visible(timeout=10_000)

        expect(
            warning
        ).to_contain_text(
            '2B is still Open.'
        )

        expect(
            warning.get_by_role(
                'button',
                name='Go Back',
            )
        ).to_be_visible()

        expect(
            warning.get_by_role(
                'button',
                name='End Inning Anyway',
            )
        ).to_be_visible()

        warning.get_by_role(
            'button',
            name='Go Back',
        ).click()

        expect(
            warning
        ).not_to_be_visible(timeout=10_000)

        state = page.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        ).json()

        assert state['current_inning'] == '1'

        page.locator(
            '#liveEndInningBtn'
        ).click()

        expect(
            warning
        ).to_be_visible(timeout=10_000)

        warning.get_by_role(
            'button',
            name='End Inning Anyway',
        ).click()

        expect(
            page.locator('#live-inning-display')
        ).to_have_text(
            '2',
            timeout=10_000,
        )

    finally:
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
                f'{coachboard_url}/api/live-game/'
                f'{game_id}/end-with-pitching',
                data={
                    'defer_pitching': True,
                    'end_reason': 'manual',
                    'current_inning_played': True,
                },
            )

        page.request.post(
            f'{coachboard_url}/game-day/'
            f'{game_id}/delete',
            headers={
                'Accept': 'application/json',
            },
        )
