"""Regression coverage for the parts of static/js/game_logic.js's legacy
rotation-save code that remain user-reachable.

An architectural investigation for this reconciliation confirmed:
  - The legacy SortableJS diamond (#diamond-parent-desktop /
    #diamond-parent-mobile) is unconditionally hidden during pregame
    planning (static/js/live_game_board_prep.js) and during live play
    (the whole #rotation-board gets the `coach-live-board-hidden` class).
    Its touch-vs-drag logic is dead code and is NOT covered here.
  - The rotation card's header (both Save Rotation buttons) and toolbar are
    ALSO visually hidden by static/js/game_management_coach_simplify.js,
    but that module's own modern buttons programmatically forward real
    clicks to them: `document.getElementById('saveRotationBtn')?.click()`
    (its `enhanceHeader`-style wiring) and an explicit action-delegation
    list that includes `#saveRotationBtn` and `#clearInningBtn`. So the
    save queue, `keepalive`, persistent Saving/Saved/Failed UI, the fixed
    manual-click `isAutosave` bug, and the `rotation_save` socket guard are
    all still exercised for real coaches through that forwarding — this
    file drives the same underlying elements directly (via a real DOM
    `.click()`, exactly like the forwarding code does) rather than through
    coach-simplify's own UI, to keep the test surface precise and stable.

Sandbox note: see test_pregame_defense_save_reliability.py's module
docstring for why `_install_cdn_vendor_routes` exists (it is a no-op,
falling through to the real network, everywhere except this restricted
sandbox).
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


@pytest.fixture(autouse=True)
def _dialogs(page: Page):
    """clearInningBtn's handler shows a confirm() before clearing; every
    test that triggers it needs that accepted or the clear (and the
    autosave it would otherwise fire) silently never happens. Accept every
    dialog by default and record each as (type, message) so a test that
    cares about a specific dialog (e.g. the manual-save failure alert) can
    still inspect what fired."""
    seen = []

    def on_dialog(dialog):
        seen.append((dialog.type, dialog.message))
        dialog.accept()

    page.on('dialog', on_dialog)
    yield seen


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def create_planning_game(page: Page, coachboard_url: str, opponent: str, days_offset: int = 10) -> int:
    """Note: a pre-existing before_request hook
    (prepare_regulation_innings_for_game_management, blueprints/rotation_templates.py)
    auto-provisions a blank Rotation row with all regulation-inning slots
    the moment /game/<id> is GET-loaded for any upcoming, non-live game, so
    rotation.id is already non-null by the time game_logic.js's own state
    is built from the initial page render. Pass a negative days_offset (a
    past-dated game) to get a genuinely un-provisioned rotation.id — that
    hook explicitly skips past games."""
    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=days_offset)).isoformat(),
            'game_start_time': '15:00',
            'game_opponent': opponent,
            'game_location': 'Legacy Save Queue Field',
            'game_notes': 'Disposable game_logic.js save-queue reachability test',
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


def click_hidden(page: Page, element_id: str):
    """Fire a real click on a legacy element that game_management_coach_simplify.js
    hides visually but forwards real clicks to — the same
    `document.getElementById(id).click()` mechanism that module itself uses."""
    page.evaluate(f"document.getElementById('{element_id}')?.click()")


def get_game_data(page: Page, coachboard_url: str, game_id: int):
    response = page.request.get(f'{coachboard_url}/api/game_data/{game_id}')
    assert response.ok, response.text()
    return response.json()


def test_manual_save_button_alerts_on_failure_autosave_does_not(page: Page, coachboard_url: str, _dialogs):
    """Direct regression test for the fixed bug where the DOM click Event
    object was passed as `isAutosave`, so a manual Save Rotation click
    silently ran as an autosave (no alert on failure)."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Manual Save Alert Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)

        def fail_save(route):
            route.fulfill(status=500, content_type='application/json', body='{"message": "simulated failure"}')

        page.route('**/save_rotation', fail_save)

        # Autosave path (triggered by Clear Inning) must NOT alert on failure.
        # _dialogs accepts every dialog (including Clear Inning's own
        # confirm()); only 'alert' entries are the thing under test here.
        click_hidden(page, 'clearInningBtn')
        page.wait_for_timeout(1500)
        alerts = [message for kind, message in _dialogs if kind == 'alert']
        assert alerts == [], f'Autosave failure must not alert, but got: {alerts}'

        # Manual click path MUST alert on failure (isAutosave explicitly false,
        # not the truthy click Event the old wiring passed through).
        click_hidden(page, 'saveRotationBtn')
        page.wait_for_timeout(500)
        alerts = [message for kind, message in _dialogs if kind == 'alert']
        assert alerts, 'Manual Save Rotation click must alert on failure.'
        assert 'simulated failure' in alerts[0] or 'Error saving rotation' in alerts[0]
    finally:
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)


def test_manual_save_button_persists_and_reaches_saved_ui(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Manual Save Persists Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)

        click_hidden(page, 'saveRotationBtn')
        expect(page.locator('#saveRotationBtn')).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['id'] is not None

        # Mobile Save Rotation button reaches the same code path.
        click_hidden(page, 'saveRotationBtnMobile')
        page.wait_for_timeout(1000)
    finally:
        cleanup(page, coachboard_url, game_id)


def test_failed_save_remains_visible_and_retryable(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Legacy Failed Retry Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)

        def fail_save(route):
            route.fulfill(status=500, content_type='application/json', body='{"message": "simulated failure"}')

        page.route('**/save_rotation', fail_save)
        click_hidden(page, 'clearInningBtn')

        expect(page.locator('#saveRotationBtn')).to_contain_text('Retry', timeout=10_000)
        page.wait_for_timeout(2500)
        expect(page.locator('#saveRotationBtn')).to_contain_text('Retry')

        page.unroute('**/save_rotation')
        click_hidden(page, 'saveRotationBtn')
        expect(page.locator('#saveRotationBtn')).to_contain_text('Saved', timeout=10_000)
    finally:
        cleanup(page, coachboard_url, game_id)


def test_rapid_clear_inning_clicks_coalesce_and_reuse_new_id(page: Page, coachboard_url: str):
    """Uses a past-dated game so prepare_regulation_innings_for_game_management
    does not auto-provision a rotation on page load, so this starts from a
    genuine id-less rotation."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Legacy Rapid Coalesce Opponent', days_offset=-3)
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)

        requests_seen = []
        responses_seen = []
        held = {'route': None}

        def handle_save(route):
            requests_seen.append(json.loads(route.request.post_data or '{}'))
            if len(requests_seen) == 1:
                # Leave unresolved until the main thread resolves it below;
                # blocking here would stall Playwright's callback-dispatch
                # thread and prevent the clicks below from being processed.
                held['route'] = route
                return
            response = route.fetch()
            responses_seen.append(response.json())
            route.fulfill(response=response)

        page.route('**/save_rotation', handle_save)

        click_hidden(page, 'clearInningBtn')
        expect(page.locator('#saveRotationBtn')).to_contain_text('Saving', timeout=10_000)

        click_hidden(page, 'clearInningBtn')
        page.wait_for_timeout(100)
        click_hidden(page, 'clearInningBtn')
        page.wait_for_timeout(200)

        assert len(requests_seen) == 1, 'A second request must not fire while the first is still in flight.'

        response = held['route'].fetch()
        responses_seen.append(response.json())
        held['route'].fulfill(response=response)
        expect(page.locator('#saveRotationBtn')).to_contain_text('Saved', timeout=15_000)

        assert len(requests_seen) == 2, f'Expected exactly 2 coalesced requests, got {len(requests_seen)}'
        assert requests_seen[0]['id'] is None
        new_id = responses_seen[0]['new_id']
        assert new_id, 'First save must create a new rotation id.'
        assert requests_seen[1]['id'] == new_id, (
            'The coalesced second request must reuse the id the first save created, not create a duplicate.'
        )

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['id'] == new_id
    finally:
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)


def test_save_request_uses_keepalive(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Legacy Keepalive Opponent')
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
        expect(page.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)

        click_hidden(page, 'clearInningBtn')
        expect(page.locator('#saveRotationBtn')).to_contain_text('Saved', timeout=10_000)

        captured = page.evaluate('window.__capturedSaveFetchInit')
        assert captured, 'No fetch() call to /save_rotation was captured.'
        assert captured[-1].get('keepalive') is True, f'Expected keepalive: true, got {captured[-1]}'
    finally:
        cleanup(page, coachboard_url, game_id)


def test_rotation_save_socket_refresh_ignored_during_inflight_then_resumes(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Legacy Socket Guard Opponent')
    other_game_id = create_planning_game(page, coachboard_url, 'Legacy Socket Guard Broadcaster Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)

        held = {'route': None}

        def handle_save(route):
            # Only the first (our own game's) save is held; requests for
            # the broadcaster game below must pass straight through, and
            # nothing here may block Playwright's dispatch thread.
            if held['route'] is None and json.loads(route.request.post_data or '{}').get('associated_game_id') == game_id:
                held['route'] = route
                return
            route.continue_()

        page.route('**/save_rotation', handle_save)
        click_hidden(page, 'clearInningBtn')
        expect(page.locator('#saveRotationBtn')).to_contain_text('Saving', timeout=10_000)

        # A save on a different game broadcasts a global 'rotation_save'
        # socket event (the backend does not scope this broadcast to a
        # room). While our own save is in flight, this must not trigger an
        # immediate fetchLatestGameData refresh.
        page.request.post(
            f'{coachboard_url}/save_rotation',
            data=json.dumps({
                'title': 'Broadcaster Rotation', 'innings': {'1': {}},
                'associated_game_id': other_game_id,
            }),
            headers={'Content-Type': 'application/json'},
        )
        page.wait_for_timeout(500)
        # Still saving (not reset by a socket-triggered refresh mid-flight).
        expect(page.locator('#saveRotationBtn')).to_contain_text('Saving')

        page.unroute('**/save_rotation')
        held['route'].continue_()
        expect(page.locator('#saveRotationBtn')).to_contain_text('Saved', timeout=15_000)
    finally:
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)
        cleanup(page, coachboard_url, other_game_id)
