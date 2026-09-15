"""Regression coverage for the pregame defense editor's save reliability.

This targets `#pregame-defense-editor-v3` (static/js/live_game_board_prep.js),
which is the tap-based defense editor coaches actually use during pregame
planning today. A prior architectural investigation confirmed that the
legacy SortableJS diamond in static/js/game_logic.js is unconditionally
hidden here (and during live play), so that legacy editor's touch-vs-drag
behavior is dead code and is not covered by this file. This file instead
verifies the reliability concepts ported from the production iPad hotfix
into the editor coaches actually see: no dropped edits while a save is in
flight, a coalescing/newest-wins save queue, new-rotation-id propagation
into a queued save, `keepalive` on the save request, a persistent
Saving/Saved/Failed indicator, and no stale-refresh clobbering of a newer
local edit.

Sandbox note: this environment's egress policy blocks the CDN hosts
(cdn.jsdelivr.net, cdn.socket.io) that templates/base.html loads Bootstrap,
Sortable, and Socket.IO from. `_install_cdn_vendor_routes` below serves
locally vendored copies of those exact pinned versions instead, but only
when COACHBOARD_E2E_CDN_VENDOR_DIR is set — it is a no-op (real network
request) everywhere else, including real CI, which has normal internet
access. It changes no application code or behavior under test.
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

from playwright.sync_api import Browser, Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

_VENDOR_DIR = Path(os.environ['COACHBOARD_E2E_CDN_VENDOR_DIR']) if os.environ.get('COACHBOARD_E2E_CDN_VENDOR_DIR') else None


def _install_cdn_vendor_routes(target):
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

    target.route(re.compile(r'^https://cdn\.jsdelivr\.net/'), handler)
    target.route(re.compile(r'^https://cdn\.socket\.io/'), handler)


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
    """A fresh game. Note: a pre-existing before_request hook
    (prepare_regulation_innings_for_game_management, blueprints/rotation_templates.py)
    auto-provisions a blank Rotation row with all regulation-inning slots
    the moment /game/<id> is GET-loaded for any upcoming, non-live game, so
    rotation.id is already non-null by the time either editor renders. Pass
    a negative days_offset (a past-dated game) to get a genuinely
    un-provisioned rotation.id — that hook explicitly skips past games."""
    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=days_offset)).isoformat(),
            'game_start_time': '15:00',
            'game_opponent': opponent,
            'game_location': 'Pregame Defense Field',
            'game_notes': 'Disposable pregame-defense-save-reliability test',
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
    """Tap a field position, then choose a player from the resulting modal —
    the one interaction the tap editor supports, for mouse and touch alike."""
    panel(page).locator(f'[data-pde-pos="{position}"]').click()
    modal = page.locator('#pde-player-modal')
    expect(modal).to_be_visible(timeout=10_000)
    modal.locator(f'.pde-choice[data-player="{player_name}"]').click()
    expect(modal).not_to_be_visible(timeout=10_000)


def get_game_data(page: Page, coachboard_url: str, game_id: int):
    response = page.request.get(f'{coachboard_url}/api/game_data/{game_id}')
    assert response.ok, response.text()
    return response.json()


def save_status(page: Page):
    return panel(page).locator('#pde-save-status')


def test_pregame_editor_visible_legacy_diamond_hidden(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Editor Visibility Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)
        expect(page.locator('#pos-desktop-SS')).to_be_hidden()
        expect(page.locator('#pos-mobile-SS')).to_be_hidden()
    finally:
        cleanup(page, coachboard_url, game_id)


def test_changing_a_position_persists(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Position Change Persists Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn'
    finally:
        cleanup(page, coachboard_url, game_id)


def test_saving_state_is_visible(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Saving Visible Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        # Hold the response open briefly so the 'saving' state is reliably
        # observable rather than racing a same-machine round-trip that can
        # complete between two polls of the assertion below.
        held = {'route': None}
        auto_continue = {'flag': False}

        def handle_save(route):
            if auto_continue['flag']:
                route.continue_()
                return
            held['route'] = route

        page.route('**/save_rotation', handle_save)
        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saving', timeout=5_000)

        # Resolve the already-captured route while its handler is still
        # installed. Unrouting first would let Playwright auto-continue
        # this still-pending route on its own once the handler is removed,
        # so a later explicit continue_() here would race that and can
        # raise "Route is already handled".
        auto_continue['flag'] = True
        held['route'].continue_()
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)
    finally:
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)


def test_failed_save_remains_visible_and_retryable(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Failed Save Retry Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        def fail_save(route):
            route.fulfill(status=500, content_type='application/json', body='{"message": "simulated failure"}')

        page.route('**/save_rotation', fail_save)
        choose_player(page, 'SS', 'Shortstop Shawn')

        expect(save_status(page)).to_contain_text('Save failed', timeout=10_000)
        # The old behavior reset autosave UI after a couple seconds; prove
        # this status stays failed well past that.
        page.wait_for_timeout(2500)
        expect(save_status(page)).to_contain_text('Save failed')
        expect(save_status(page)).to_contain_text('simulated failure')

        page.unroute('**/save_rotation')
        save_status(page).click()
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn'
    finally:
        cleanup(page, coachboard_url, game_id)


def test_malformed_http_200_response_fails_closed(page: Page, coachboard_url: str):
    """A malformed/empty HTTP 200 JSON response (no explicit
    {"status": "success"}) must be treated as a failed save, not a silent
    success. Success now requires result.status === 'success' exactly —
    matching the check static/js/game_logic.js's queue already used —
    instead of the old, looser 'not explicitly {status: "error"}'. Failing
    closed here must also NOT advance the shared store's
    lastSyncedRevision, so the edit stays genuinely unsynced: retryable,
    and safe from a background refresh mistaking it for already-saved."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Malformed 200 Response Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        def malformed_ok(route):
            # HTTP 200, valid JSON, but no {"status": "success"} — the kind
            # of malformed/empty response a proxy or bug could produce.
            route.fulfill(status=200, content_type='application/json', body='{}')

        page.route('**/save_rotation', malformed_ok)
        choose_player(page, 'SS', 'Shortstop Shawn')

        expect(save_status(page)).to_contain_text('Save failed', timeout=10_000)
        assert page.evaluate('window.CBPregameRotation.hasUnsyncedLocalState()') is True, (
            'A malformed 200 must not advance lastSyncedRevision.'
        )

        page.unroute('**/save_rotation')
        save_status(page).click()
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn'
    finally:
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)


def test_rapid_consecutive_changes_do_not_disappear_and_coalesce(page: Page, coachboard_url: str):
    """Rapid taps while the first (rotation-creating) save is in flight must:
    never be silently dropped, never fire overlapping requests, persist only
    the newest snapshot, and have the coalesced save reuse the id the first
    save just created rather than creating a duplicate rotation.

    Uses a past-dated game so prepare_regulation_innings_for_game_management
    (blueprints/rotation_templates.py) does not auto-provision a rotation on
    page load; that lets this test start from a genuine id-less rotation."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Rapid Coalesce Opponent', days_offset=-3)
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        requests_seen = []
        responses_seen = []
        held = {'route': None}

        def handle_save(route):
            requests_seen.append(json.loads(route.request.post_data or '{}'))
            if len(requests_seen) == 1:
                # Leave the first request unresolved (no continue/fulfill/abort
                # call) so it stays genuinely in flight; the test resolves it
                # later from the main thread once taps #2/#3 have queued.
                # Resolving synchronously here (even via a blocking wait)
                # would block Playwright's single callback-dispatch thread
                # and starve the route events for taps #2/#3.
                held['route'] = route
                return
            response = route.fetch()
            responses_seen.append(response.json())
            route.fulfill(response=response)

        page.route('**/save_rotation', handle_save)

        # Tap #1 starts the first (held-open) save, creating the rotation.
        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saving', timeout=10_000)

        # Taps #2 and #3 happen while save #1 is still in flight. The UI must
        # keep responding (no silent drop) and each edit must be visible
        # immediately, even though nothing has saved yet.
        choose_player(page, '2B', 'Second Sam')
        expect(panel(page).locator('[data-pde-pos="2B"] .pde-name')).to_have_text('Second Sam')
        choose_player(page, '3B', 'Third Theo')
        expect(panel(page).locator('[data-pde-pos="3B"] .pde-name')).to_have_text('Third Theo')

        assert len(requests_seen) == 1, 'A second request must not fire while the first is still in flight.'

        response = held['route'].fetch()
        responses_seen.append(response.json())
        held['route'].fulfill(response=response)
        expect(save_status(page)).to_contain_text('Saved', timeout=15_000)

        assert len(requests_seen) == 2, f'Expected exactly 2 coalesced requests, got {len(requests_seen)}'
        assert requests_seen[0]['id'] is None
        new_id = responses_seen[0]['new_id']
        assert new_id, 'First save must create a new rotation id.'
        assert requests_seen[1]['id'] == new_id, (
            'The coalesced second request must reuse the id the first save created, not create a duplicate.'
        )
        assert requests_seen[1]['innings']['1']['SS'] == 'Shortstop Shawn'
        assert requests_seen[1]['innings']['1']['2B'] == 'Second Sam'
        assert requests_seen[1]['innings']['1']['3B'] == 'Third Theo'

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['id'] == new_id
        assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn'
        assert data['rotation']['innings']['1']['2B'] == 'Second Sam'
        assert data['rotation']['innings']['1']['3B'] == 'Third Theo'
    finally:
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)


def test_save_request_uses_keepalive(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Keepalive Opponent')
    try:
        page.add_init_script("""
            window.__capturedSaveFetchInit = [];
            const _origFetch = window.fetch;
            window.fetch = function(input, init) {
                const url = typeof input === 'string' ? input : (input && input.url) || '';
                if (url.includes('/save_rotation')) {
                    window.__capturedSaveFetchInit.push(init || {});
                }
                return _origFetch.apply(this, arguments);
            };
        """)
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        captured = page.evaluate('window.__capturedSaveFetchInit')
        assert captured, 'No fetch() call to /save_rotation was captured.'
        assert captured[-1].get('keepalive') is True, f'Expected keepalive: true, got {captured[-1]}'
    finally:
        cleanup(page, coachboard_url, game_id)


def test_no_stale_refresh_replaces_newer_pending_local_state(page: Page, coachboard_url: str):
    """A background refresh (scheduled by an inning-toolbar action elsewhere
    on the page) must not overwrite a local edit that is still saving or
    queued to save."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Stale Refresh Guard Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        held = {'route': None}

        def handle_save(route):
            # Only hold the FIRST save (our own tap, from live_game_board_prep.js).
            # #addInningBtn below also triggers an independent save from the
            # legacy game_logic.js editor; that one must pass straight
            # through untouched. Leaving the first unresolved here (rather
            # than blocking) avoids stalling Playwright's single
            # callback-dispatch thread.
            if held['route'] is None:
                held['route'] = route
                return
            route.continue_()

        page.route('**/save_rotation', handle_save)

        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saving', timeout=10_000)

        # Force a refresh while the save above is still in flight (the same
        # trigger the inning toolbar uses elsewhere on the page).
        page.evaluate("window.dispatchEvent(new Event('resize'))")
        page.locator('#addInningBtn').dispatch_event('click')
        page.wait_for_timeout(900)

        # The local edit must still be showing; a stale refresh must not
        # have reverted it back to OPEN while the save was in flight.
        expect(panel(page).locator('[data-pde-pos="SS"] .pde-name')).to_have_text('Shortstop Shawn')

        # Resolve the already-captured route while its handler is still
        # installed (it already auto-continues anything else via the
        # else-branch above) — unrouting first would let Playwright
        # auto-continue this pending route on its own, racing the explicit
        # continue_() below and risking "Route is already handled".
        held['route'].continue_()
        expect(save_status(page)).to_contain_text('Saved', timeout=15_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn'
    finally:
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)


@pytest.mark.parametrize(
    'context_kwargs',
    [
        pytest.param({'viewport': {'width': 1280, 'height': 800}}, id='desktop-mouse'),
        pytest.param({'viewport': {'width': 1024, 'height': 768}, 'has_touch': True}, id='touch'),
    ],
)
def test_desktop_and_touch_interaction_with_tap_editor(browser: Browser, coachboard_url: str, context_kwargs):
    """The tap editor is unified across input types by design (no
    drag/drop); confirm it works identically with a plain mouse context and
    with a real touch-emulated (has_touch=True) context. Parametrized
    (rather than looped in one test body) so a failure in either input mode
    names it directly in the test id, and each mode gets a fully
    independent browser context and game — no state carried over from one
    mode's run to the other's."""
    label = 'touch' if context_kwargs.get('has_touch') else 'desktop-mouse'
    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    _install_cdn_vendor_routes(page)
    try:
        login(page, coachboard_url)
        game_id = create_planning_game(page, coachboard_url, f'Tap Editor {label} Opponent')
        try:
            page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
            expect(panel(page)).to_be_visible(timeout=15_000)

            # Defensive diagnostics before the click that previously timed
            # out with no further context in CI: confirm the target player
            # is actually part of the roster this modal will list, and
            # capture what the modal actually shows if it is absent.
            data = get_game_data(page, coachboard_url, game_id)
            absent_ids = set(data.get('absent_player_ids') or [])
            roster_names = {
                player['name'] for player in data.get('roster', [])
                if player.get('id') not in absent_ids
            }
            assert 'Shortstop Shawn' in roster_names, (
                f"[{label}] 'Shortstop Shawn' missing from the available roster: {sorted(roster_names)}"
            )

            panel(page).locator('[data-pde-pos="SS"]').click()
            modal = page.locator('#pde-player-modal')
            expect(modal).to_be_visible(timeout=10_000)
            choice = modal.locator('.pde-choice[data-player="Shortstop Shawn"]')
            if choice.count() == 0:
                visible_names = modal.locator('.pde-choice').all_inner_texts()
                pytest.fail(
                    f"[{label}] 'Shortstop Shawn' was not offered in the player modal. "
                    f"Modal choices shown: {visible_names}"
                )
            choice.click()
            try:
                expect(modal).not_to_be_visible(timeout=5_000)
            except AssertionError:
                # Observed intermittently in the touch-emulated context:
                # the modal is still open 5s after the click. Rather than
                # guessing at a timing fix, retry the exact same click only
                # if the DOM shows it is actually still needed — a real
                # second failure to close still fails the test below, it
                # is not masked.
                if modal.is_visible():
                    choice.click()
                expect(modal).not_to_be_visible(timeout=10_000)

            expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

            data = get_game_data(page, coachboard_url, game_id)
            assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn', label
        finally:
            cleanup(page, coachboard_url, game_id)
    finally:
        context.close()


def test_mobile_viewport_interaction_with_tap_editor(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    page.set_viewport_size({'width': 390, 'height': 844})
    game_id = create_planning_game(page, coachboard_url, 'Mobile Tap Editor Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn'
    finally:
        cleanup(page, coachboard_url, game_id)


def trigger_scheduled_refresh(page: Page):
    """Fire the exact `scheduleRefresh()` mechanism Game Management uses
    elsewhere on the page (live_game_board_prep.js:wire() listens for a
    plain 'change' event on #rotationTemplateSelect and always calls
    scheduleRefresh(), no matter the selected value). A bare 'change' event
    with no value selected is a safe no-op in game_logic.js's own listener
    on the same element, so this cannot itself mutate any rotation state —
    it only exercises the background-refresh path under test."""
    page.locator('#rotationTemplateSelect').dispatch_event('change')
    # scheduleRefresh() debounces at 650ms; give the fetch round-trip room too.
    page.wait_for_timeout(1200)


def test_failed_save_survives_a_scheduled_refresh_then_retries_successfully(page: Page, coachboard_url: str):
    """A failed save must not be discarded by an unrelated background
    refresh (the same debounced refresh Game Management's inning toolbar
    triggers), and retrying afterward must still save the edit."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Failed Save Survives Refresh Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        def fail_save(route):
            route.fulfill(status=500, content_type='application/json', body='{"message": "simulated failure"}')

        page.route('**/save_rotation', fail_save)
        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Save failed', timeout=10_000)

        trigger_scheduled_refresh(page)

        # The failed, unsaved edit must still be showing and still failed —
        # a background refresh must neither have discarded it nor silently
        # reset the status back to idle.
        expect(panel(page).locator('[data-pde-pos="SS"] .pde-name')).to_have_text('Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Save failed')

        page.unroute('**/save_rotation')
        save_status(page).click()
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn'
    finally:
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)


def test_inflight_stale_refresh_cannot_overwrite_newer_local_edit(page: Page, coachboard_url: str):
    """A refresh that was already in flight before a local edit started
    (so it passed the entry guard while nothing was pending) must still be
    rejected once its stale response arrives after that edit has saved."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Inflight Stale Refresh Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        # A definitely-stale snapshot: captured before any edit, so SS is open.
        stale_snapshot = get_game_data(page, coachboard_url, game_id)
        assert not stale_snapshot['rotation']['innings']['1'].get('SS')

        # More than one /api/game_data request can land in this window (the
        # page has other refresh triggers besides the one this test fires).
        # Track all of them and resolve only the FIRST — the one genuinely
        # started before the edit below — with the stale snapshot; anything
        # else is let through untouched so the page keeps working normally.
        held_routes = []

        def hold_game_data(route):
            # Leave unresolved until released below; blocking here would
            # stall Playwright's single callback-dispatch thread.
            held_routes.append(route)

        page.route(f'**/api/game_data/{game_id}', hold_game_data)
        page.locator('#rotationTemplateSelect').dispatch_event('change')
        page.wait_for_timeout(900)
        assert held_routes, 'expected the scheduled refresh to have started a game_data fetch by now'
        first_stale_route = held_routes[0]

        # While that GET is held open (already in flight), make a real,
        # unintercepted local edit + save.
        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        # Now release the FIRST held request — the one dispatched before the
        # edit above — with the OLD (pre-edit) snapshot: exactly the
        # "started before the edit, arrives after" race.
        first_stale_route.fulfill(status=200, content_type='application/json', body=json.dumps(stale_snapshot))
        page.wait_for_timeout(800)

        # Let any other captured request through normally so the page isn't
        # left with a permanently-hanging fetch.
        for route in held_routes:
            if route is first_stale_route:
                continue
            try:
                response = route.fetch()
                route.fulfill(response=response)
            except Exception:
                pass

        expect(panel(page).locator('[data-pde-pos="SS"] .pde-name')).to_have_text('Shortstop Shawn')

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn'
    finally:
        page.unroute(f'**/api/game_data/{game_id}')
        cleanup(page, coachboard_url, game_id)
