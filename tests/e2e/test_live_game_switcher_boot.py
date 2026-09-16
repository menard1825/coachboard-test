"""The Live Game tabs must not wait for the 3.5s refresh interval.

live_game_board_prep_v2 builds its switcher in ensureSurface(), which needs
both .coach-live-shell and #cbQuickDefense. Those are mounted by other
modules -- live_game_dugout_mode is fetched dynamically, so Quick Field
routinely appears after this module's first next-inning request at 140ms.
ensureSurface() just returns null when they are missing, and the only thing
that retried was the 3500ms interval, so the coach could sit for seconds with
no way to reach Next Inning or the pregame plan.

The race is reproduced deterministically by delaying the dugout module's
script, which pushes #cbQuickDefense well past the first API response.
"""

import os
import re
import time
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

SWITCHER = '#cb-now-next-switch'
QUICK_FIELD = '#cbQuickDefense'

# live_game_board_prep_v2 refreshes at 140ms and then every 3500ms. Before
# the boot fix, a Quick Field that mounted after the first refresh left the
# switcher waiting for the next interval tick. Anything comfortably under
# that interval proves the tabs came from the event-driven boot path.
REFRESH_INTERVAL_MS = 3500
PROMPT_MS = 1500

# Long enough to land after the 140ms first request, short enough to keep
# the test quick.
DUGOUT_DELAY_SECONDS = 1.2


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(
        re.compile(
            rf'^{re.escape(coachboard_url)}/?'
            rf'(?:#(?:games|overview))?$'
        )
    )


def post_json(page: Page, coachboard_url: str, path: str, data, expected_status=200):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == expected_status, (
        f'POST {path} returned {response.status}: {response.text()}'
    )
    payload = response.json()
    if expected_status < 400:
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
            'game_date': (date.today() + timedelta(days=14)).isoformat(),
            'game_start_time': '16:00',
            'game_opponent': 'Switcher Boot Opponent',
            'game_location': 'Switcher Boot Field',
            'game_notes': 'Disposable switcher boot browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )

    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(
        page,
        coachboard_url,
        '/save_rotation',
        {
            'title': 'Switcher Boot Rotation',
            'innings': {'1': alignment(), '2': alignment()},
            'associated_game_id': game_id,
        },
    )

    return game_id


def cleanup_game(page: Page, coachboard_url: str, game_id: int):
    """A live game left behind locks the roster for later tests."""
    state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')

    if state.ok and state.json().get('game', {}).get('is_live'):
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


def test_switcher_appears_without_waiting_for_the_refresh_interval(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    def delay_dugout_module(route):
        # Held rather than blocked: Quick Field must still arrive, just late
        # enough to miss the first next-inning response.
        time.sleep(DUGOUT_DELAY_SECONDS)
        route.continue_()

    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})

        page.route('**/live_game_dugout_mode.js*', delay_dugout_module)

        try:
            page.goto(
                f'{coachboard_url}/game/{game_id}',
                wait_until='domcontentloaded',
            )

            expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)

            # Quick Field is the gating dependency; it lands late by design.
            expect(page.locator(QUICK_FIELD)).to_be_visible(timeout=20_000)
            quick_field_at = time.monotonic()

            # The tabs must follow it essentially immediately rather than
            # waiting for the next 3500ms refresh.
            expect(page.locator(SWITCHER)).to_be_visible(timeout=PROMPT_MS + 1_000)
            switcher_at = time.monotonic()

            gap_ms = (switcher_at - quick_field_at) * 1000
            assert gap_ms < PROMPT_MS, (
                f'switcher took {gap_ms:.0f}ms after Quick Field mounted; '
                f'anything approaching {REFRESH_INTERVAL_MS}ms means it is '
                f'waiting for the refresh interval again'
            )

            # And it is the real, complete switcher.
            expect(
                page.locator(SWITCHER).locator('[data-now-next]')
            ).to_have_count(3)
        finally:
            page.unroute('**/live_game_dugout_mode.js*')
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_boot_leaves_on_the_field_active(page: Page, coachboard_url: str):
    """Building the tabs before the API responds must not change which view
    a coach lands on."""
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        switcher = page.locator(SWITCHER)
        expect(switcher).to_be_visible(timeout=15_000)

        expect(
            switcher.locator('[data-now-next="now"]')
        ).to_have_attribute('aria-pressed', 'true', timeout=10_000)
        expect(page.locator(QUICK_FIELD)).to_be_visible()
        expect(page.locator('#live-board-prep-v3')).to_be_hidden()
        expect(page.locator('#live-board-pregame-plan')).to_be_hidden()
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_observer_stays_armed_and_catches_a_same_page_game_start(page: Page, coachboard_url: str):
    """The boot observer is deliberately left attached with no timeout.

    A game the coach has not started yet keeps the observer armed
    indefinitely, so starting the game on the same page -- no reload -- still
    produces the tabs immediately. The long idle wait below is the point: a
    hypothetical short-lived boot timeout would have expired by then, and the
    switcher would be left to the 3500ms refresh interval.
    """
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        start_button = page.locator('#startLiveGameBtnAction')
        expect(start_button).to_be_visible(timeout=15_000)

        # Not live yet: nothing to switch between.
        expect(page.locator(SWITCHER)).to_have_count(0)

        # Outlast any plausible boot timeout, and the refresh interval too.
        page.wait_for_timeout(5_000)
        expect(page.locator(SWITCHER)).to_have_count(0)

        # The real same-page start path -- no navigation, no injected DOM.
        start_button.click()

        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
        expect(page.locator(QUICK_FIELD)).to_be_visible(timeout=20_000)
        quick_field_at = time.monotonic()

        expect(page.locator(SWITCHER)).to_be_visible(timeout=PROMPT_MS + 1_000)
        gap_ms = (time.monotonic() - quick_field_at) * 1000

        assert gap_ms < PROMPT_MS, (
            f'switcher took {gap_ms:.0f}ms after Quick Field mounted on a '
            f'same-page start; approaching {REFRESH_INTERVAL_MS}ms means the '
            f'observer had been torn down and the interval did the work'
        )

        # Exactly one switcher, with the expected default view.
        expect(page.locator(SWITCHER)).to_have_count(1)
        expect(page.locator(SWITCHER).locator('[data-now-next]')).to_have_count(3)
        expect(
            page.locator(SWITCHER).locator('[data-now-next="now"]')
        ).to_have_attribute('aria-pressed', 'true', timeout=10_000)
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_game_that_is_not_live_never_shows_the_switcher(page: Page, coachboard_url: str):
    """Booting from the DOM instead of the API must not flash a Live Game
    switcher onto a game that has not started."""
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        # Deliberately never started.
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        page.wait_for_timeout(1_500)

        expect(page.locator(SWITCHER)).to_have_count(0)
        expect(page.locator('#live-board-prep-v3')).to_have_count(0)
        expect(page.locator('#live-board-pregame-plan')).to_have_count(0)
    finally:
        cleanup_game(page, coachboard_url, game_id)
