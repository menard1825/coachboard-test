"""Regression coverage for a stale-response bug in
static/js/game_logic.js's `fetchLatestGameData()`, found in an independent
review of the CBPregameRotation architecture (see
tests/e2e/test_pregame_rotation_cross_module_race.py and
tests/e2e/test_pregame_rotation_inning_selection_integrity.py for that
architecture's other coverage).

static/js/live_game_board_prep.js's own `refresh()` captures a local
rotation revision at request start and gates applying the response on
`CBPregameRotation.canApplyRefresh(revisionAtStart)`. game_logic.js's
`fetchLatestGameData()` — triggered unconditionally by several socket
events (data_updated, lineup_add/update, roster_update, game_updated,
pitching_update) — did not: it called `setFromServer()` unconditionally
after the fetch resolved, relying only on `setFromServer()`'s own
`hasUnsyncedLocalState()` check at RESPONSE time. That check cannot
distinguish "nothing happened" from "an edit happened and fully saved
while this fetch was outstanding" — in the second case, by response time
everything looks synced again, so the stale (pre-edit) snapshot was
silently accepted and could overwrite the edit, discardable by any later
save built from that reverted state.

Two structurally distinct races are covered:
  1. The edit (and its successful save) happens entirely AFTER the fetch
     starts and completes BEFORE the (still in-flight) fetch's response
     arrives.
  2. The fetch itself starts WHILE a save is already in flight (from one
     of the unguarded socket events above), and that save succeeds before
     the fetch's response arrives — the response-time-only checks look
     safe in this case too unless "safe at request start" is also
     remembered.
"""

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

_VENDOR_DIR = Path(os.environ['COACHBOARD_E2E_CDN_VENDOR_DIR']) if os.environ.get('COACHBOARD_E2E_CDN_VENDOR_DIR') else None


def _install_cdn_vendor_routes(page: Page):
    if not _VENDOR_DIR or not _VENDOR_DIR.is_dir():
        return

    def handler(route):
        name = route.request.url.rsplit('/', 1)[-1].split('?')[0]
        local = _VENDOR_DIR / name
        if local.is_file():
            content_type = 'application/javascript' if name.endswith('.js') else 'text/css'
            route.fulfill(status=200, content_type=content_type, body=local.read_bytes())
        else:
            route.continue_()

    page.route(re.compile(r'^https://cdn\.jsdelivr\.net/'), handler)
    page.route(re.compile(r'^https://cdn\.socket\.io/'), handler)


@pytest.fixture(autouse=True)
def _vendor_cdns(page: Page):
    _install_cdn_vendor_routes(page)
    yield


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def create_planning_game(page: Page, coachboard_url: str, opponent: str, days_offset: int = 10) -> int:
    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=days_offset)).isoformat(),
            'game_start_time': '15:00',
            'game_opponent': opponent,
            'game_location': 'Legacy Refresh Staleness Field',
            'game_notes': 'Disposable legacy-refresh-staleness test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert created.status in {302, 303}, created.text()
    match = re.search(r'/game/(\d+)', created.headers.get('location') or '')
    assert match
    return int(match.group(1))


def cleanup(page: Page, coachboard_url: str, game_id: int):
    page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})


def panel(page: Page):
    return page.locator('#pregame-defense-editor-v3')


def choose_player(page: Page, position: str, player_name: str):
    panel(page).locator(f'[data-pde-pos="{position}"]').click()
    modal = page.locator('#pde-player-modal')
    expect(modal).to_be_visible(timeout=10_000)
    modal.locator(f'.pde-choice[data-player="{player_name}"]').click()
    expect(modal).not_to_be_visible(timeout=10_000)


def save_status(page: Page):
    return panel(page).locator('#pde-save-status')


def get_game_data(page: Page, coachboard_url: str, game_id: int):
    response = page.request.get(f'{coachboard_url}/api/game_data/{game_id}')
    assert response.ok, response.text()
    return response.json()


def canonical_innings(page: Page):
    """Read CBPregameRotation's own in-memory rotation directly, to prove
    the canonical shared object itself was never overwritten by a stale
    response — not merely that some other module's copy looks right."""
    return page.evaluate("window.CBPregameRotation.getRotation('x').innings")


def click_hidden(page: Page, element_id: str):
    page.evaluate(f"document.getElementById('{element_id}')?.click()")


def trigger_data_updated_socket_event(page: Page, coachboard_url: str, title: str) -> int:
    """Fire the real, unguarded `data_updated` socket event
    game_logic.js's setupEventListeners() calls fetchLatestGameData() for
    with no in-flight/unsynced guard (unlike its own 'rotation_save'
    handler). Saving a throwaway rotation template does this: the
    /api/rotation-template/save route broadcasts data_updated globally
    (unscoped to any game room), exactly like the existing
    'rotation_save'-broadcast trick used elsewhere in this suite. Returns
    the created template's id so the caller can delete it afterward."""
    created = page.request.post(
        f'{coachboard_url}/api/rotation-template/save',
        data=json.dumps({'title': title, 'innings': {'1': {}}}),
        headers={'Content-Type': 'application/json'},
    )
    assert created.ok, created.text()
    return created.json()['id']


def test_legacy_refresh_stale_response_does_not_overwrite_successful_edit(page: Page, coachboard_url: str):
    """Race 1: fetchLatestGameData() starts while the rotation is clean and
    captures an old snapshot; a real field edit is made and fully saves
    before that fetch's response arrives. The canonical rotation must
    still contain the edit, and it must still be in the DB after a later,
    unrelated save."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Legacy Refresh Stale Response Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        baseline = get_game_data(page, coachboard_url, game_id)
        assert not baseline['rotation']['innings']['1'].get('SS')

        held_routes = []

        def hold_game_data(route):
            # Leave unresolved until released below; blocking here would
            # stall Playwright's single callback-dispatch thread.
            held_routes.append(route)

        page.route(f'**/api/game_data/{game_id}', hold_game_data)

        template_id = trigger_data_updated_socket_event(
            page, coachboard_url, f'Stale Refresh Trigger {game_id}'
        )
        try:
            page.wait_for_timeout(600)
            assert held_routes, (
                'expected the real data_updated socket event to have started a held /api/game_data request'
            )

            # A real field edit, made and fully saved while that fetch is
            # still outstanding.
            choose_player(page, 'SS', 'Shortstop Shawn')
            expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

            # Release the held response(s) now, with the OLD (pre-edit)
            # snapshot captured above — exactly what a request that
            # started before the edit would have actually received.
            page.unroute(f'**/api/game_data/{game_id}')
            for route in held_routes:
                route.fulfill(status=200, content_type='application/json', body=json.dumps(baseline))
            page.wait_for_timeout(800)

            assert canonical_innings(page)['1'].get('SS') == 'Shortstop Shawn', (
                'a stale fetchLatestGameData() response silently reverted an already-successful edit'
            )

            # A later, unrelated structural action + save must not persist
            # the stale (reverted) rotation either.
            click_hidden(page, 'addInningBtn')
            expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

            data = get_game_data(page, coachboard_url, game_id)
            assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn', (
                'the DB lost the successful edit after a later save built on the stale-reverted state'
            )
        finally:
            page.request.get(f'{coachboard_url}/delete_rotation/{template_id}')
    finally:
        page.unroute(f'**/api/game_data/{game_id}')
        cleanup(page, coachboard_url, game_id)


def test_legacy_refresh_started_during_inflight_save_does_not_overwrite_it(page: Page, coachboard_url: str):
    """Race 2: fetchLatestGameData() starts WHILE a rotation save is
    already in flight (from one of the unguarded socket events), and that
    save succeeds before the fetch's response arrives. Every check
    available only at response time (not in flight, revision unchanged,
    nothing unsynced) would look safe in this case — the fix must also
    remember the fetch was not safe to trust for rotation purposes at the
    moment it started."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Legacy Refresh Inflight Save Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        baseline = get_game_data(page, coachboard_url, game_id)
        assert not baseline['rotation']['innings']['1'].get('SS')

        held_save = {'route': None}

        def hold_save(route):
            if held_save['route'] is None:
                held_save['route'] = route
                return
            route.continue_()

        page.route('**/save_rotation', hold_save)

        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saving', timeout=10_000)
        assert held_save['route'] is not None, 'expected the field edit to have started a held /save_rotation request'

        held_game_data = []

        def hold_game_data(route):
            held_game_data.append(route)

        page.route(f'**/api/game_data/{game_id}', hold_game_data)

        # Trigger fetchLatestGameData() via the real, unguarded
        # data_updated socket event WHILE the save above is still held
        # in flight.
        template_id = trigger_data_updated_socket_event(
            page, coachboard_url, f'Inflight Save Trigger {game_id}'
        )
        try:
            page.wait_for_timeout(600)
            assert held_game_data, (
                'expected data_updated to have started a held /api/game_data request while the save was in flight'
            )

            # Now let the in-flight save complete successfully — by the
            # time the held game-data response is released below, every
            # response-time-only check (not in flight, revision unchanged,
            # nothing unsynced) would look safe again.
            page.unroute('**/save_rotation')
            held_save['route'].continue_()
            expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

            page.unroute(f'**/api/game_data/{game_id}')
            for route in held_game_data:
                route.fulfill(status=200, content_type='application/json', body=json.dumps(baseline))
            page.wait_for_timeout(800)

            assert canonical_innings(page)['1'].get('SS') == 'Shortstop Shawn', (
                'a game-data fetch started while a save was already in flight reverted that save once it landed'
            )

            data = get_game_data(page, coachboard_url, game_id)
            assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn'
        finally:
            page.request.get(f'{coachboard_url}/delete_rotation/{template_id}')
    finally:
        page.unroute('**/save_rotation')
        page.unroute(f'**/api/game_data/{game_id}')
        cleanup(page, coachboard_url, game_id)
