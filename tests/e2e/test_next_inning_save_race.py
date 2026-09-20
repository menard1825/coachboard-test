"""Regression coverage for the real-game NEXT-defense save race."""

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


def starting_alignment():
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


def planned_alignment():
    # Deliberately different from inning 1 so "Use Current Defense"
    # gives us an unmistakable final NEXT draft.
    return {
        'P': 'Pitcher Pat',
        'C': 'Catcher Cole',
        '1B': 'First Frank',
        '2B': 'Second Sam',
        '3B': 'Shortstop Shawn',
        'SS': 'Third Theo',
        'LF': 'Left Lee',
        'CF': 'Right Riley',
        'RF': 'Center Casey',
    }


def create_game(page: Page, coachboard_url: str):
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date':
                (date.today() + timedelta(days=7)).isoformat(),
            'game_start_time': '11:00',
            'game_opponent': 'NEXT Save Race Opponent',
            'game_location': 'Regression Test Field',
            'game_notes': 'Disposable NEXT save race test',
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
            'title': 'NEXT Save Race Rotation',
            'innings': {
                '1': starting_alignment(),
                '2': planned_alignment(),
            },
            'associated_game_id': game_id,
        },
    )

    return game_id


def start_live_game(
    page: Page,
    coachboard_url: str,
    game_id: int,
):
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

    next_board = page.locator('#live-board-prep-v3')

    expect(
        next_board
    ).to_be_visible(timeout=10_000)

    return next_board


def cleanup_game(
    page: Page,
    coachboard_url: str,
    game_id: int,
):
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


def test_end_inning_waits_for_inflight_next_save(
    page: Page,
    coachboard_url: str,
):
    """
    Game-78 regression:

    The coach changes NEXT and immediately taps End Inning while the
    /next-inning-prep POST is still in flight.

    End Inning must wait for that exact save before advancing.
    """

    page.set_viewport_size(
        {
            'width': 390,
            'height': 844,
        }
    )

    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        next_board = start_live_game(
            page,
            coachboard_url,
            game_id,
        )

        initial_prep = page.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/next-inning-prep'
        ).json()

        assert (
            initial_prep['confirmed']['alignment']
            == planned_alignment()
        )

        # Hold the NEXT POST inside the browser. This is the real race:
        # the board has begun saving, but the server has not received the
        # coach's final NEXT defense yet.
        page.evaluate(
            """gameId => {
                const originalFetch = window.fetch.bind(window);

                let releaseSave;
                const saveGate = new Promise(resolve => {
                    releaseSave = resolve;
                });

                window.__cbNextSaveStarted = false;
                window.__cbAdvanceCalls = 0;
                window.__cbReleaseNextSave = () => releaseSave();

                window.fetch = (...args) => {
                    const input = args[0];
                    const init = args[1] || {};

                    const url =
                        typeof input === 'string'
                            ? input
                            : (input?.url || '');

                    const method = String(
                        init.method ||
                        (
                            typeof input !== 'string'
                                ? input?.method
                                : ''
                        ) ||
                        'GET'
                    ).toUpperCase();

                    if (
                        url.includes(
                            `/api/live-game/${gameId}/next-inning-prep`
                        ) &&
                        method === 'POST' &&
                        !window.__cbNextSaveStarted
                    ) {
                        window.__cbNextSaveStarted = true;

                        return saveGate.then(
                            () => originalFetch(...args)
                        );
                    }

                    if (
                        url.includes(
                            `/api/live-game/${gameId}/advance-inning`
                        ) &&
                        method === 'POST'
                    ) {
                        window.__cbAdvanceCalls += 1;
                    }

                    return originalFetch(...args);
                };
            }""",
            game_id,
        )

        # Changing from the inning-2 pregame plan to inning-1's current
        # defense starts a real NEXT save through saveAlignment().
        next_board.locator(
            '[data-next-use-current]'
        ).click()

        page.wait_for_function(
            '() => window.__cbNextSaveStarted === true'
        )

        assert page.evaluate(
            '() => window.CBNextDefense'
            '?.isSaveInFlightOrQueued?.() === true'
        )

        # This is the tap that lost Travis's final edits in game 78.
        page.locator(
            '#liveEndInningBtn'
        ).click()

        # Give the old buggy implementation enough time to run its state
        # stabilization check and incorrectly advance using stale NEXT.
        page.wait_for_timeout(500)

        expect(
            page.locator('#live-inning-display')
        ).to_have_text('1')

        assert page.evaluate(
            '() => window.__cbAdvanceCalls'
        ) == 0

        # Let the final NEXT save reach the server.
        page.evaluate(
            '() => window.__cbReleaseNextSave()'
        )

        expect(
            page.locator('#live-inning-display')
        ).to_have_text(
            '2',
            timeout=10_000,
        )

        state = page.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/state'
        ).json()

        assert state['current_inning'] == '2'
        assert (
            state['current_alignment']
            == starting_alignment()
        )

        end_events = [
            event
            for event in state.get('rotation_events', [])
            if (
                not event.get('reverted')
                and event.get('event_type') == 'End Inning'
                and str(event.get('inning')) == '2'
            )
        ]

        assert end_events
        assert (
            end_events[-1]['after_alignment']
            == starting_alignment()
        )

        assert page.evaluate(
            '() => window.__cbAdvanceCalls'
        ) == 1

    finally:
        cleanup_game(
            page,
            coachboard_url,
            game_id,
        )


def test_advance_rejects_next_changed_after_client_read(
    page: Page,
    coachboard_url: str,
):
    """
    A second coach/device changes NEXT after End Inning reads it but
    before /advance-inning commits.

    The server must fail closed with stale_next_inning_prep.
    """

    page.set_viewport_size(
        {
            'width': 390,
            'height': 844,
        }
    )

    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        next_board = start_live_game(
            page,
            coachboard_url,
            game_id,
        )

        initial_prep = page.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/next-inning-prep'
        ).json()

        assert (
            initial_prep['confirmed']['alignment']
            == planned_alignment()
        )

        # Intercept only the browser's actual advance request.
        #
        # By the time this code runs, End Inning has already:
        #   1. flushed NEXT
        #   2. GET /next-inning-prep
        #   3. captured prep id
        #
        # We now simulate another coach replacing NEXT before the original
        # advance request reaches Flask.
        page.evaluate(
            """({gameId, competingAlignment}) => {
                const originalFetch = window.fetch.bind(window);

                window.__cbAdvanceIntercepted = false;
                window.__cbAdvanceStatus = null;
                window.__cbCompetingWriteStatus = null;

                window.fetch = async (...args) => {
                    const input = args[0];
                    const init = args[1] || {};

                    const url =
                        typeof input === 'string'
                            ? input
                            : (input?.url || '');

                    const method = String(
                        init.method ||
                        (
                            typeof input !== 'string'
                                ? input?.method
                                : ''
                        ) ||
                        'GET'
                    ).toUpperCase();

                    if (
                        url.includes(
                            `/api/live-game/${gameId}/advance-inning`
                        ) &&
                        method === 'POST' &&
                        !window.__cbAdvanceIntercepted
                    ) {
                        window.__cbAdvanceIntercepted = true;

                        const competing = await originalFetch(
                            `/api/live-game/${gameId}/next-inning-prep`,
                            {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                },
                                body: JSON.stringify({
                                    mode: 'custom',
                                    alignment: competingAlignment,
                                }),
                            }
                        );

                        window.__cbCompetingWriteStatus =
                            competing.status;

                        const response =
                            await originalFetch(...args);

                        window.__cbAdvanceStatus =
                            response.status;

                        return response;
                    }

                    return originalFetch(...args);
                };
            }""",
            {
                'gameId': game_id,
                'competingAlignment': starting_alignment(),
            },
        )

        page.locator(
            '#liveEndInningBtn'
        ).click()

        page.wait_for_function(
            '() => window.__cbAdvanceStatus !== null'
        )

        assert page.evaluate(
            '() => window.__cbCompetingWriteStatus'
        ) == 200

        assert page.evaluate(
            '() => window.__cbAdvanceStatus'
        ) == 409

        expect(
            page.locator('#live-inning-display')
        ).to_have_text('1')

        state = page.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/state'
        ).json()

        assert state['current_inning'] == '1'
        assert (
            state['current_alignment']
            == starting_alignment()
        )

        prep = page.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/next-inning-prep'
        ).json()

        assert (
            prep['confirmed']['alignment']
            == starting_alignment()
        )

        # The original stale plan must never have generated an End Inning
        # event.
        assert not [
            event
            for event in state.get('rotation_events', [])
            if (
                not event.get('reverted')
                and event.get('event_type') == 'End Inning'
            )
        ]

        expect(
            next_board.locator('.cb-next-error')
        ).to_contain_text(
            'NEXT defense changed',
            timeout=10_000,
        )

    finally:
        cleanup_game(
            page,
            coachboard_url,
            game_id,
        )
