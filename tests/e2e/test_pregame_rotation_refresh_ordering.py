"""Regression coverage for out-of-order server-refresh responses, found in
an independent review of the CBPregameRotation architecture.

Local-edit revision tracking (localRevision/lastSyncedRevision,
canApplyRefresh()) protects an accepted SERVER snapshot from being
clobbered by a LOCAL edit that crossed it — but localRevision never
changes when an accepted server snapshot itself is applied, so it cannot
order two competing server refreshes against each other:

  1. Refresh A starts (local revision N, server state R0).
  2. Another coach's device changes the authoritative server rotation to R1.
  3. Refresh B starts (also at local revision N) and returns first,
     correctly applying R1.
  4. Refresh A returns afterward, still carrying the OLD R0 snapshot it
     captured before step 2. Every check available at that point (not in
     flight, revision still N, nothing unsynced) looks perfectly safe, so
     R0 could silently overwrite R1 in the canonical shared store — and a
     later local edit would persist that regression right back to the
     server.

The fix adds a shared, monotonically increasing refresh-generation token
(CBPregameRotation.beginServerRefresh()/canApplyRefresh(revision, token))
so whichever refresh's response is applied LAST *in start order* wins,
never whichever response merely *arrives* last. This test exercises A and
B through the two different consumers — live_game_board_prep.js's own
refresh() and game_logic.js's fetchLatestGameData() — to prove the token
is genuinely coordinated across both modules through CBPregameRotation,
not two unrelated module-local counters.
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
            'game_location': 'Refresh Ordering Field',
            'game_notes': 'Disposable refresh-ordering test',
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
    return page.evaluate("window.CBPregameRotation.getRotation('x').innings")


def test_later_started_server_refresh_wins_over_earlier_one_arriving_after(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Refresh Ordering Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        baseline = get_game_data(page, coachboard_url, game_id)
        rotation_id = baseline['rotation']['id']
        assert rotation_id, 'expected the auto-provisioned rotation to already have an id'
        assert not baseline['rotation']['innings']['1'].get('SS')

        held_routes = []

        def hold_game_data(route):
            # Leave unresolved until released below; blocking here would
            # stall Playwright's single callback-dispatch thread.
            held_routes.append(route)

        page.route(f'**/api/game_data/{game_id}', hold_game_data)

        # Refresh A: live_game_board_prep.js's own refresh(), via the same
        # debounced trigger used elsewhere in this suite. Captured while
        # the server still holds R0 (the baseline).
        page.locator('#rotationTemplateSelect').dispatch_event('change')
        page.wait_for_timeout(900)
        assert len(held_routes) == 1, 'expected refresh A (live_game_board_prep.js) to have started a held request'

        # Another coach's device changes the authoritative server rotation
        # to R1 — a real, direct write to the same /save_rotation route
        # every client uses, targeting the SAME rotation row.
        r1_innings = dict(baseline['rotation']['innings'])
        r1_innings['1'] = {**r1_innings.get('1', {}), 'SS': 'SecondCoachAssigned'}
        second_coach_write = page.request.post(
            f'{coachboard_url}/save_rotation',
            data=json.dumps({
                'id': rotation_id,
                'title': baseline['rotation']['title'],
                'innings': r1_innings,
                'associated_game_id': game_id,
            }),
            headers={'Content-Type': 'application/json'},
        )
        assert second_coach_write.ok, second_coach_write.text()

        # That write broadcasts a global 'rotation_save' socket event;
        # game_logic.js's own (guarded, but nothing local is in flight
        # here) handler for it calls fetchLatestGameData() — Refresh B,
        # through the OTHER consumer module. It starts strictly after A
        # and, being unheld until now, its /api/game_data fetch reads the
        # server's CURRENT (R1) state.
        page.wait_for_timeout(900)
        assert len(held_routes) == 2, 'expected refresh B (game_logic.js) to have started a second held request'

        # Let B (the later-started refresh) resolve and apply first, by
        # passing its held request straight through to the real server —
        # which now holds R1.
        response_b = held_routes[1].fetch()
        held_routes[1].fulfill(response=response_b)
        page.wait_for_timeout(800)

        assert canonical_innings(page)['1'].get('SS') == 'SecondCoachAssigned', (
            'refresh B (the later-started refresh) should have applied R1'
        )

        # Now release A — the EARLIER-started refresh — with the STALE R0
        # snapshot it actually captured before the second coach's write.
        held_routes[0].fulfill(status=200, content_type='application/json', body=json.dumps(baseline))
        page.wait_for_timeout(800)

        assert canonical_innings(page)['1'].get('SS') == 'SecondCoachAssigned', (
            'an earlier-started refresh (A) that arrives after a later one (B) must not roll the '
            'canonical rotation back to its own stale snapshot'
        )

        # A subsequent normal local edit/save must persist R1 together
        # with the new edit — not silently regress to R0.
        choose_player(page, '2B', 'Second Sam')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings']['1']['SS'] == 'SecondCoachAssigned', (
            'the DB lost the second coach\'s server-side change after a later local save'
        )
        assert data['rotation']['innings']['1']['2B'] == 'Second Sam'
    finally:
        page.unroute(f'**/api/game_data/{game_id}')
        cleanup(page, coachboard_url, game_id)
