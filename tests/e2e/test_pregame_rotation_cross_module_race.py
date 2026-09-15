"""Regression coverage for the cross-module pregame-rotation lost-update
race between static/js/live_game_board_prep.js (owns the
#pregame-defense-editor-v3 tap field) and static/js/game_logic.js (owns
Add/Remove/Clear Inning, Copy Previous, Paste, and full-game-plan
application via its inning toolbar).

Before the shared static/js/pregame_rotation_sync.js store, each module
kept its own separate in-memory rotation snapshot and its own independent
/save_rotation queue. game_management_coach_simplify.js visually hides
game_logic.js's legacy toolbar but programmatically forwards real
user-facing actions ("Add Another Inning", "Clear This Inning", ...) into
it (document.getElementById(id)?.click()), so both writers were reachable
during ordinary pregame planning — not just through the dead legacy
diamond. A field edit in one module racing with an inning-toolbar action in
the other could silently lose one of the two changes: whichever module's
stale full-rotation snapshot was saved last would overwrite the other's
edit, and even fully-serialized requests were not safe, because the second
module's payload could still be built from a full-rotation snapshot that
never learned about the other module's already-saved edit.

Both tests below drive the exact same real, user-facing entry points
game_management_coach_simplify.js forwards clicks to
(test_game_logic_rotation_save_queue.py's click_hidden() pattern), not the
legacy diamond itself.
"""

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
    """Clear This Inning shows a confirm() before clearing. Accept every
    dialog so the flow under test can proceed unattended."""
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
    """Default (future-dated) games are used here deliberately: the
    pre-existing prepare_regulation_innings_for_game_management before_request
    hook (blueprints/rotation_templates.py) auto-provisions a Rotation row
    with the team's full set of regulation-inning slots (and a non-null id)
    the moment such a game's /game/<id> is loaded — giving both tests a
    known starting rotation with multiple innings already present, and a
    stable id both modules agree on, with no extra setup."""
    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=days_offset)).isoformat(),
            'game_start_time': '15:00',
            'game_opponent': opponent,
            'game_location': 'Cross Module Race Field',
            'game_notes': 'Disposable cross-module rotation race test',
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
    choice = modal.locator(f'.pde-choice[data-player="{player_name}"]')
    choice.click()
    try:
        expect(modal).not_to_be_visible(timeout=5_000)
    except AssertionError:
        # Observed intermittently: the modal is still open 5s after the
        # click. Rather than guessing at a timing fix, retry the exact
        # same click only if the DOM shows it is actually still needed —
        # a real second failure to close still fails the test below, it
        # is not masked.
        if modal.is_visible():
            choice.click()
        expect(modal).not_to_be_visible(timeout=10_000)


def save_status(page: Page):
    return panel(page).locator('#pde-save-status')


def get_game_data(page: Page, coachboard_url: str, game_id: int):
    response = page.request.get(f'{coachboard_url}/api/game_data/{game_id}')
    assert response.ok, response.text()
    return response.json()


def click_hidden(page: Page, element_id: str):
    """Fire a real click on a legacy element that
    game_management_coach_simplify.js hides visually but forwards real
    clicks to — the same document.getElementById(id).click() mechanism
    that module's own 'Add Another Inning' / 'Clear This Inning' actions
    use (game_management_coach_simplify.js:addInningOption and its
    action-delegation list)."""
    page.evaluate(f"document.getElementById('{element_id}')?.click()")


@pytest.mark.parametrize(
    'release_order',
    ['field_edit_response_first', 'add_inning_response_first'],
)
def test_add_inning_during_inflight_field_edit_save_keeps_both_changes(page: Page, coachboard_url: str, release_order):
    """Reproduces the exact race from the independent review: hold the tap
    editor's first /save_rotation request open, make a visible field
    assignment (SS -> player), then, while that request is still in
    flight, invoke the real user-facing "Add Another Inning" path that
    forwards into game_logic.js. Both possible response-arrival orders are
    covered (parametrized): before the fix, whichever module's stale
    full-rotation snapshot reached the server last silently discarded the
    other module's change; the final DB state must contain BOTH the field
    assignment AND the newly added inning, regardless of order."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, f'Add Inning Race {release_order} Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        baseline = get_game_data(page, coachboard_url, game_id)
        starting_inning_count = len(baseline['rotation']['innings'])
        assert starting_inning_count >= 1

        held_routes = []
        auto_continue = {'flag': False}

        def handle_save(route):
            if auto_continue['flag']:
                route.continue_()
                return
            # Leave unresolved until released below; blocking here would
            # stall Playwright's single callback-dispatch thread.
            held_routes.append(route)

        page.route('**/save_rotation', handle_save)

        # Step 1-2: hold the field edit's save open with a visible change.
        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saving', timeout=10_000)
        page.wait_for_timeout(400)
        assert held_routes, 'expected the field-edit save to have started a held /save_rotation request'

        # Step 3-4: while that request is held, invoke the real
        # user-facing Add Another Inning path.
        click_hidden(page, 'addInningBtn')
        # Give a second, independent request time to fire if the two
        # modules do not coordinate (the pre-fix, buggy behavior); the
        # fixed shared queue instead coalesces this into the same pending
        # payload and sends nothing new yet.
        page.wait_for_timeout(700)

        batch = list(held_routes)
        order = list(reversed(batch)) if release_order == 'add_inning_response_first' else batch

        # Step 5: release requests. Any further request (e.g. the fixed
        # architecture's coalesced follow-up save once the first
        # completes) is allowed to pass straight through from here on, so
        # nothing is left hanging.
        auto_continue['flag'] = True
        for route in order:
            response = route.fetch()
            route.fulfill(response=response)
            page.wait_for_timeout(250)

        page.wait_for_timeout(1500)
        expect(save_status(page)).to_contain_text('Saved', timeout=15_000)

        # Step 6: verify the final DB state contains BOTH changes.
        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn', (
            f'[{release_order}] the field assignment was lost by the cross-module race'
        )
        assert len(data['rotation']['innings']) == starting_inning_count + 1, (
            f'[{release_order}] the added inning was lost by the cross-module race; '
            f"innings={sorted(data['rotation']['innings'].keys(), key=float)}"
        )
    finally:
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)


def test_clear_inning_after_sequential_field_edit_does_not_revert_other_inning(page: Page, coachboard_url: str):
    """Coverage for a destructive/overwrite-style legacy action, per the
    review's requirement that serializing requests alone is not enough:
    even with NO concurrency at all (the field edit's save completes
    fully before Clear This Inning is used), the second module's payload
    must still be built from the latest combined state. A field edit is
    made and fully saved on one inning; Clear This Inning (the real
    user-facing action game_management_coach_simplify.js forwards to
    #clearInningBtn) is then used on a DIFFERENT inning. Before the fix,
    game_logic.js's own `state.rotation` was only ever refreshed from the
    server on a periodic/explicit refresh — never in response to the tap
    editor's own edits — so Clear's full-rotation save payload was built
    from a stale snapshot that silently reverted the already-saved field
    edit on the other inning.

    Every successful /save_rotation broadcasts a global 'rotation_save'
    socket event that triggers a background refresh
    (fetchLatestGameData()) in every open Game Management tab, including
    this same page — given enough wall-clock time, that refresh alone
    would happen to resync the stale state and mask the bug. This test
    holds every /api/game_data/<id> request open for the whole critical
    window (regardless of what triggers it) so no such background refresh
    can land before Clear This Inning is used, making the reproduction
    deterministic rather than a timing accident."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Clear Inning Cross Module Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        baseline = get_game_data(page, coachboard_url, game_id)
        inning_keys = sorted(baseline['rotation']['innings'].keys(), key=float)
        assert len(inning_keys) >= 2, 'expected the auto-provisioned rotation to have at least two regulation innings'
        first_inning, second_inning = inning_keys[0], inning_keys[1]

        held_refreshes = []
        auto_continue = {'flag': False}

        def hold_game_data(route):
            if auto_continue['flag']:
                route.continue_()
                return
            # Leave unresolved until released below; blocking here would
            # stall Playwright's single callback-dispatch thread.
            held_refreshes.append(route)

        page.route(f'**/api/game_data/{game_id}', hold_game_data)

        # Field edit on the FIRST inning via the tap editor; let it fully
        # save before touching anything else — no /save_rotation
        # concurrency is involved in this scenario at all.
        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings'][first_inning]['SS'] == 'Shortstop Shawn'

        # Switch to a DIFFERENT inning and clear it via the real
        # user-facing action, still with any background refresh held open.
        page.locator(f'label[for="inning-{second_inning}"]').click()
        click_hidden(page, 'clearInningBtn')
        page.wait_for_timeout(300)
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        # Now let any held background refresh(es) through normally: snapshot
        # what's captured so far, switch the handler to auto-continue
        # anything that arrives afterward, then resolve the snapshot —
        # unrouting first would let Playwright auto-continue these
        # still-pending routes on its own, racing the explicit fulfill()
        # below and risking "Route is already handled" (silently masked
        # before by a broad try/except here, which has been removed: a
        # real failure to resolve one of these must not be swallowed).
        batch = list(held_refreshes)
        auto_continue['flag'] = True
        for route in batch:
            response = route.fetch()
            route.fulfill(response=response)
        page.wait_for_timeout(300)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings'][first_inning].get('SS') == 'Shortstop Shawn', (
            'Clearing an unrelated inning must not silently revert a field edit already saved on another inning.'
        )
        assert data['rotation']['innings'][second_inning] == {}
    finally:
        page.unroute(f'**/api/game_data/{game_id}')
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)
