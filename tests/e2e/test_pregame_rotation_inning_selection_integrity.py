"""Regression coverage for a render-side-effect bug in
static/js/live_game_board_prep.js found in an independent review of the
cross-module CBPregameRotation architecture (see
tests/e2e/test_pregame_rotation_cross_module_race.py for that
architecture's own coverage).

`ensureRotation()` used to silently recreate the currently-selected inning
(`rotation.innings[inning] = {}`) whenever it was missing — including when
it was missing because it had just been legitimately removed by
game_logic.js's Remove Last Inning, or because a fresh server snapshot no
longer contained it. `CBPregameRotation.commitLocalChange()` (and
`setFromServer()`) call `notifyChange()` before this module's own explicit
reconciliation of its local `inning` selection has a chance to run, and
this module's `onChange` listener calls `render()` immediately — which
reads `alignment()` -> `ensureRotation()`. That resurrected the removed
inning into the CANONICAL shared rotation object, so a later save (the one
that just ran, or any later unrelated one) could persist the removed
inning right back into the DB.

The fix makes `ensureRotation()` (via `reconcileInningSelection()`)
side-effect free with respect to the canonical rotation structure: it only
ever moves the local `inning` selection to an existing key, never creates
one. These tests attack the two structurally distinct triggers named in
the review — a structural toolbar action (Remove Last Inning) and a
server-refresh snapshot that no longer contains the viewed inning — plus a
third real-world path (applying a full-game defense plan) that replaces
the whole inning set the same way.
"""

import copy
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
    """Remove Last Inning has no confirm(); applying a full-game plan does.
    Accept every dialog by default so these flows can proceed unattended."""
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
    prepare_regulation_innings_for_game_management before_request hook
    (blueprints/rotation_templates.py) auto-provisions a Rotation row with
    the team's full set of regulation-inning slots the moment such a
    game's /game/<id> is loaded — giving these tests a known,
    multi-inning starting rotation with no extra setup."""
    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=days_offset)).isoformat(),
            'game_start_time': '15:00',
            'game_opponent': opponent,
            'game_location': 'Inning Selection Integrity Field',
            'game_notes': 'Disposable inning-selection-integrity test',
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


def displayed_inning(page: Page) -> str:
    return page.locator('#pregame-defense-editor-v3 .pde-inning strong').inner_text()


def get_game_data(page: Page, coachboard_url: str, game_id: int):
    response = page.request.get(f'{coachboard_url}/api/game_data/{game_id}')
    assert response.ok, response.text()
    return response.json()


def canonical_inning_keys(page: Page):
    """Read the CBPregameRotation store's own in-memory rotation directly,
    bypassing this module's `state.rotation` reference, to prove the
    canonical object itself was never resurrected — not merely that the
    UI's own copy looks right."""
    return page.evaluate("Object.keys(window.CBPregameRotation.getRotation('x').innings || {})")


def click_hidden(page: Page, element_id: str):
    """Fire a real click on a legacy element that
    game_management_coach_simplify.js hides visually but forwards real
    clicks to (document.getElementById(id).click(), the same mechanism
    its own 'Add Another Inning' / 'Remove Last Inning' actions use)."""
    page.evaluate(f"document.getElementById('{element_id}')?.click()")


def select_inning(page: Page, inning_key: str):
    page.locator(f'label[for="inning-{inning_key}"]').click()


def test_remove_current_last_inning_does_not_resurrect_it(page: Page, coachboard_url: str):
    """Select the actual last inning in the modern pregame editor, then use
    the real user-facing Remove Last Inning action (game_management_coach_simplify.js
    forwards it to #removeInningBtn). The removed inning must not
    reappear — not immediately, and not after further normal
    refresh/socket activity settles."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Remove Last Inning Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        baseline = get_game_data(page, coachboard_url, game_id)
        inning_keys = sorted(baseline['rotation']['innings'].keys(), key=float)
        assert len(inning_keys) >= 2, 'expected the auto-provisioned rotation to have at least two regulation innings'
        removed_inning = inning_keys[-1]
        expected_new_last = inning_keys[-2]

        select_inning(page, removed_inning)
        expect(panel(page).locator('.pde-inning strong')).to_have_text(removed_inning, timeout=10_000)

        click_hidden(page, 'removeInningBtn')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert removed_inning not in data['rotation']['innings'], (
            'the removed inning must be gone from the DB immediately after the save'
        )
        assert set(data['rotation']['innings'].keys()) == set(inning_keys[:-1])

        # The modern editor must have moved off the removed inning to a
        # valid remaining one, not silently kept showing/recreating it.
        assert displayed_inning(page) == expected_new_last
        assert removed_inning not in canonical_inning_keys(page), (
            "the removed inning must not exist in CBPregameRotation's own canonical rotation"
        )

        # Wait through normal refresh/socket activity (the same debounced
        # refresh the inning toolbar triggers elsewhere on the page), which
        # is exactly the onChange -> render() -> ensureRotation() path the
        # bug lived in.
        page.locator('#rotationTemplateSelect').dispatch_event('change')
        page.wait_for_timeout(1200)
        assert removed_inning not in canonical_inning_keys(page), (
            'a background refresh must not have resurrected the removed inning into the canonical rotation'
        )

        # A further, unrelated edit + save must not silently resurrect and
        # persist the removed inning either.
        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert removed_inning not in data['rotation']['innings'], (
            'the removed inning reappeared in the DB after further normal activity'
        )
        assert data['rotation']['innings'][expected_new_last]['SS'] == 'Shortstop Shawn'
    finally:
        cleanup(page, coachboard_url, game_id)


def test_server_refresh_removing_current_inning_does_not_resurrect_it(page: Page, coachboard_url: str):
    """Have the modern editor viewing an inning, then let a legitimate
    server snapshot (as if another coach's device already removed that
    inning) arrive via the real refresh path. The UI must move to an
    existing inning, CBPregameRotation must not recreate the removed one,
    and a later normal edit/save must not persist it either."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Server Refresh Removes Inning Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        baseline = get_game_data(page, coachboard_url, game_id)
        inning_keys = sorted(baseline['rotation']['innings'].keys(), key=float)
        assert len(inning_keys) >= 2, 'expected the auto-provisioned rotation to have at least two regulation innings'
        viewed_inning = inning_keys[-1]

        select_inning(page, viewed_inning)
        expect(panel(page).locator('.pde-inning strong')).to_have_text(viewed_inning, timeout=10_000)

        # Simulate the authoritative server snapshot no longer containing
        # the inning this panel is currently viewing.
        modified_snapshot = copy.deepcopy(baseline)
        del modified_snapshot['rotation']['innings'][viewed_inning]

        def serve_modified(route):
            route.fulfill(status=200, content_type='application/json', body=json.dumps(modified_snapshot))

        page.route(f'**/api/game_data/{game_id}', serve_modified)

        # The real refresh path: the same debounced scheduleRefresh() the
        # inning toolbar triggers elsewhere on the page.
        page.locator('#rotationTemplateSelect').dispatch_event('change')
        page.wait_for_timeout(1200)

        page.unroute(f'**/api/game_data/{game_id}')

        remaining_keys = set(modified_snapshot['rotation']['innings'].keys())
        assert displayed_inning(page) != viewed_inning
        assert displayed_inning(page) in remaining_keys

        assert viewed_inning not in canonical_inning_keys(page), (
            'the removed inning must not have been recreated in CBPregameRotation by the refresh'
        )

        # A later, real edit/save (against the real, unmocked endpoint from
        # here on) must not resurrect and persist the removed inning.
        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert viewed_inning not in data['rotation']['innings'], (
            'the server-removed inning reappeared in the DB after a later normal edit'
        )
    finally:
        page.unroute(f'**/api/game_data/{game_id}')
        cleanup(page, coachboard_url, game_id)


def test_applying_full_game_plan_missing_current_inning_does_not_resurrect_it(page: Page, coachboard_url: str):
    """Same structural class of issue via a third real path: applying a
    full-game defense plan (game_logic.js's #rotationTemplateSelect
    'change' handler) replaces the whole inning set outright. If the
    modern editor is currently viewing an inning absent from the applied
    plan, that inning must not be resurrected."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Full Game Plan Missing Inning Opponent')
    try:
        # A first visit is required before the rotation exists at all: the
        # regulation-inning auto-provisioning hook only fires on loading
        # /game/<id> itself, not on the JSON API.
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        baseline = get_game_data(page, coachboard_url, game_id)
        regulation_keys = sorted(baseline['rotation']['innings'].keys(), key=float)
        assert len(regulation_keys) >= 2

        # A full-game plan built from exactly the regulation innings —
        # created before the extra inning below exists, so it genuinely
        # lacks it (the save endpoint pads UP to the regulation count but
        # never removes/adds beyond what's submitted).
        created = page.request.post(
            f'{coachboard_url}/api/rotation-template/save',
            data=json.dumps({
                'title': 'Bonus Inning Integrity Full Game Plan',
                'innings': {key: {} for key in regulation_keys},
            }),
            headers={'Content-Type': 'application/json'},
        )
        assert created.ok, created.text()
        template = created.json()
        template_id = template['id']

        try:
            # Load the page fresh now so the template is present in the
            # initial gameData.rotation_templates the #rotationTemplateSelect
            # dropdown is built from.
            page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
            expect(panel(page)).to_be_visible(timeout=15_000)

            extra_inning = str(int(regulation_keys[-1]) + 1)
            click_hidden(page, 'addInningBtn')
            expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

            # Add Inning's own render already leaves the new inning's radio
            # checked (game_logic.js's own doing), but only a genuine click
            # transition fires the 'change' event this module listens for
            # to move its own local `inning` selection — clicking an
            # already-checked radio is a browser no-op. Select a different
            # inning first so the click onto extra_inning is a real
            # transition.
            select_inning(page, regulation_keys[0])
            expect(panel(page).locator('.pde-inning strong')).to_have_text(regulation_keys[0], timeout=10_000)
            select_inning(page, extra_inning)
            expect(panel(page).locator('.pde-inning strong')).to_have_text(extra_inning, timeout=10_000)

            defense_options = page.get_by_role('button', name=re.compile('Plan Options'))
            expect(defense_options).to_be_visible(timeout=10_000)
            defense_options.click()
            select = page.locator('#rotationTemplateSelect')
            expect(select).to_be_visible(timeout=10_000)
            select.select_option(value=str(template_id))

            expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

            data = get_game_data(page, coachboard_url, game_id)
            assert set(data['rotation']['innings'].keys()) == set(regulation_keys), (
                'applying the full-game plan must replace the inning set with exactly the plan\'s innings'
            )
            assert extra_inning not in data['rotation']['innings']

            assert displayed_inning(page) != extra_inning
            assert displayed_inning(page) in set(regulation_keys)
            assert extra_inning not in canonical_inning_keys(page), (
                'the inning absent from the applied plan must not be recreated in CBPregameRotation'
            )

            page.locator('#rotationTemplateSelect').dispatch_event('change')
            page.wait_for_timeout(1200)
            choose_player(page, 'SS', 'Shortstop Shawn')
            expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

            data = get_game_data(page, coachboard_url, game_id)
            assert extra_inning not in data['rotation']['innings'], (
                'the inning absent from the applied plan reappeared in the DB after further normal activity'
            )
        finally:
            page.request.get(f'{coachboard_url}/delete_rotation/{template_id}')
    finally:
        cleanup(page, coachboard_url, game_id)



def test_apply_all_preserves_planned_mid_inning_changes(
    page: Page,
    coachboard_url: str,
):
    """Normal Apply-to-All works on base innings only. A deliberately
    different planned mid-inning alignment must survive unchanged."""
    login(page, coachboard_url)

    game_id = create_planning_game(
        page,
        coachboard_url,
        'Apply All Preserves Planned Change Opponent',
    )

    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        expect(
            panel(page)
        ).to_be_visible(timeout=15_000)

        baseline = get_game_data(
            page,
            coachboard_url,
            game_id,
        )

        base_keys = sorted(
            (
                key
                for key in baseline['rotation']['innings']
                if float(key).is_integer()
            ),
            key=float,
        )

        base = base_keys[0]

        select_inning(page, base)

        choose_player(
            page,
            'SS',
            'Shortstop Shawn',
        )

        choose_player(
            page,
            '2B',
            'Second Sam',
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        click_hidden(
            page,
            'addSubInningBtn',
        )

        sub = f'{int(float(base))}.1'

        expect(
            page.locator(
                f'label[for="inning-{sub}"]'
            )
        ).to_have_count(
            1,
            timeout=10_000,
        )

        select_inning(
            page,
            sub,
        )

        # The selector uses the coach-facing 1A SUB label while the
        # compact inning badge intentionally keeps the base inning number.
        # Verify that the planned-change state itself is selected and that
        # the editor clearly identifies what the coach is editing.
        expect(
            page.locator(
                f'input[name="inning-radio"][value="{sub}"]'
            )
        ).to_be_checked()

        expect(
            panel(page).locator(
                '.pde-inning strong'
            )
        ).to_have_text(
            str(int(float(base))),
            timeout=10_000,
        )

        expect(
            page.locator(
                f'label[for="inning-{sub}"]'
            )
        ).to_contain_text(
            '1A',
            timeout=10_000,
        )

        # Normal inning-copy controls are intentionally unavailable while
        # editing a planned change.
        expect(
            page.locator(
                '#gmApplyDefenseAllBtn'
            )
        ).to_be_hidden()

        expect(
            page.locator(
                '#gmApplyDefenseRemainingBtn'
            )
        ).to_be_hidden()

        expect(
            page.locator(
                '#gmChooseDefenseInningsBtn'
            )
        ).to_be_hidden()

        # Make 1A intentionally different from normal Inning 1.
        page.evaluate(
            """sub => {
                const rotation =
                    window.CBPregameRotation
                        .getRotation('Rotation');

                const alignment =
                    rotation.innings[sub];

                const ss = alignment.SS;
                alignment.SS = alignment['2B'];
                alignment['2B'] = ss;

                window.CBPregameRotation
                    .commitLocalChange(
                        'Rotation',
                        false
                    );
            }""",
            sub,
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        planned_before = page.evaluate(
            """sub => ({
                ...(
                    window.CBPregameRotation
                        .getRotation('Rotation')
                        .innings[sub] || {}
                )
            })""",
            sub,
        )

        assert (
            planned_before['SS']
            == 'Second Sam'
        )

        assert (
            planned_before['2B']
            == 'Shortstop Shawn'
        )

        select_inning(
            page,
            base,
        )

        expect(
            page.locator(
                '#gmApplyDefenseAllBtn'
            )
        ).to_be_visible(
            timeout=10_000,
        )

        page.locator(
            '#gmApplyDefenseAllBtn'
        ).click()

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        planned_after = page.evaluate(
            """sub => ({
                ...(
                    window.CBPregameRotation
                        .getRotation('Rotation')
                        .innings[sub] || {}
                )
            })""",
            sub,
        )

        assert planned_after == planned_before, (
            'Apply to All must not overwrite a planned '
            'mid-inning change'
        )

        data = get_game_data(
            page,
            coachboard_url,
            game_id,
        )

        assert (
            data['rotation']['innings'][sub]
            == planned_before
        )

    finally:
        cleanup(
            page,
            coachboard_url,
            game_id,
        )


def test_add_and_remove_base_innings_ignore_planned_changes(
    page: Page,
    coachboard_url: str,
):
    """Add Another Inning copies the previous BASE inning, not its
    planned change; Remove Last Inning removes the base inning together
    with any planned changes that belong to it."""
    login(page, coachboard_url)

    game_id = create_planning_game(
        page,
        coachboard_url,
        'Base Inning Structure Opponent',
    )

    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        expect(
            panel(page)
        ).to_be_visible(timeout=15_000)

        baseline = get_game_data(
            page,
            coachboard_url,
            game_id,
        )

        base_keys = sorted(
            (
                key
                for key in baseline['rotation']['innings']
                if float(key).is_integer()
            ),
            key=float,
        )

        last_base = base_keys[-1]

        select_inning(
            page,
            last_base,
        )

        choose_player(
            page,
            'SS',
            'Shortstop Shawn',
        )

        choose_player(
            page,
            '2B',
            'Second Sam',
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        click_hidden(
            page,
            'addSubInningBtn',
        )

        sub = (
            f'{int(float(last_base))}.1'
        )

        select_inning(
            page,
            sub,
        )

        page.evaluate(
            """sub => {
                const rotation =
                    window.CBPregameRotation
                        .getRotation('Rotation');

                const alignment =
                    rotation.innings[sub];

                const ss = alignment.SS;
                alignment.SS = alignment['2B'];
                alignment['2B'] = ss;

                window.CBPregameRotation
                    .commitLocalChange(
                        'Rotation',
                        false
                    );
            }""",
            sub,
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        new_base = str(
            int(float(last_base)) + 1
        )

        # We are intentionally ON the planned change when Add is used.
        # The new inning must still copy normal last_base, not sub.
        click_hidden(
            page,
            'addInningBtn',
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        rotation = page.evaluate(
            """() => (
                window.CBPregameRotation
                    .getRotation('Rotation')
                    .innings
            )"""
        )

        assert new_base in rotation

        assert (
            rotation[new_base]['SS']
            == 'Shortstop Shawn'
        )

        assert (
            rotation[new_base]['2B']
            == 'Second Sam'
        )

        assert (
            rotation[sub]['SS']
            == 'Second Sam'
        )

        # First removal removes the newly-added base inning only.
        click_hidden(
            page,
            'removeInningBtn',
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        keys = set(
            canonical_inning_keys(page)
        )

        assert new_base not in keys
        assert last_base in keys
        assert sub in keys

        # Second removal removes the old last BASE inning and every
        # planned change belonging to it.
        click_hidden(
            page,
            'removeInningBtn',
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        keys = set(
            canonical_inning_keys(page)
        )

        assert last_base not in keys
        assert sub not in keys

        data = get_game_data(
            page,
            coachboard_url,
            game_id,
        )

        assert last_base not in (
            data['rotation']['innings']
        )

        assert sub not in (
            data['rotation']['innings']
        )

    finally:
        cleanup(
            page,
            coachboard_url,
            game_id,
        )


# --- planner-open-tap regression coverage ---


def planner_rotation_snapshot(page: Page):
    """Deep-copy the canonical client-side rotation."""
    return page.evaluate(
        """() => JSON.parse(JSON.stringify(
            window.CBPregameRotation
                .getRotation('Rotation')
                .innings || {}
        ))"""
    )


def planner_base_innings(page: Page):
    return sorted(
        (
            key
            for key in planner_rotation_snapshot(
                page
            )
            if float(key).is_integer()
        ),
        key=float,
    )


def test_apply_all_undo_restores_targets_and_preserves_planned_change(
    page: Page,
    coachboard_url: str,
):
    """Undo must restore every copied base inning exactly while leaving
    a planned mid-inning change completely untouched."""
    login(page, coachboard_url)

    game_id = create_planning_game(
        page,
        coachboard_url,
        'Apply All Undo Restore Opponent',
    )

    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        expect(
            panel(page)
        ).to_be_visible(
            timeout=15_000
        )

        base_keys = planner_base_innings(
            page
        )

        assert len(base_keys) >= 3

        source = base_keys[0]
        targets = base_keys[1:]

        select_inning(
            page,
            source,
        )

        choose_player(
            page,
            'SS',
            'Shortstop Shawn',
        )

        choose_player(
            page,
            '2B',
            'Second Sam',
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        # Add a planned change for the source inning so Undo is also
        # proven not to touch decimal/sub-innings.
        click_hidden(
            page,
            'addSubInningBtn',
        )

        sub = (
            f'{int(float(source))}.1'
        )

        expect(
            page.locator(
                f'input[name="inning-radio"]'
                f'[value="{sub}"]'
            )
        ).to_have_count(
            1,
            timeout=10_000,
        )

        select_inning(
            page,
            sub,
        )

        # Make the planned change intentionally distinct from the
        # normal source inning.
        page.evaluate(
            """sub => {
                const rotation =
                    window.CBPregameRotation
                        .getRotation(
                            'Rotation'
                        );

                const alignment =
                    rotation.innings[sub];

                const ss =
                    alignment.SS;

                alignment.SS =
                    alignment['2B'];

                alignment['2B'] =
                    ss;

                window.CBPregameRotation
                    .commitLocalChange(
                        'Rotation',
                        false
                    );
            }""",
            sub,
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        planned_before = (
            planner_rotation_snapshot(
                page
            )[sub]
        )

        select_inning(
            page,
            source,
        )

        before = (
            planner_rotation_snapshot(
                page
            )
        )

        target_before = {
            inning: before[inning]
            for inning in targets
        }

        apply_all = page.locator(
            '#gmApplyDefenseAllBtn'
        )

        expect(
            apply_all
        ).to_be_visible(
            timeout=10_000
        )

        apply_all.click()

        copy_toast = (
            page.locator(
                '#gm-coach-toast-holder '
                '.toast.show'
            )
            .filter(
                has_text=(
                    f'Copied Inning '
                    f'{source}'
                )
            )
            .last
        )

        expect(
            copy_toast
        ).to_be_visible(
            timeout=5_000
        )

        undo = copy_toast.get_by_role(
            'button',
            name='Undo',
        )

        expect(
            undo
        ).to_be_visible()

        # Prove the copy actually occurred before Undo.
        copied = (
            planner_rotation_snapshot(
                page
            )
        )

        source_alignment = copied[source]

        for inning in targets:
            assert (
                copied[inning]
                == source_alignment
            ), (
                f'Apply All did not copy '
                f'{source} to {inning}'
            )

        assert (
            copied[sub]
            == planned_before
        )

        undo.click()

        undone_toast = (
            page.locator(
                '#gm-coach-toast-holder '
                '.toast.show'
            )
            .filter(
                has_text='Defense copy undone.'
            )
            .last
        )

        expect(
            undone_toast
        ).to_be_visible(
            timeout=5_000
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        after = planner_rotation_snapshot(
            page
        )

        for inning in targets:
            assert (
                after[inning]
                == target_before[inning]
            ), (
                f'Undo did not restore '
                f'Inning {inning}'
            )

        assert (
            after[sub]
            == planned_before
        ), (
            'Undo must not alter the planned '
            'mid-inning change'
        )

    finally:
        cleanup(
            page,
            coachboard_url,
            game_id,
        )


def test_apply_all_undo_refuses_after_newer_target_edit_without_partial_restore(
    page: Page,
    coachboard_url: str,
):
    """If any copied target has changed since Apply All, Undo must
    refuse the whole operation rather than partially restoring targets."""
    login(page, coachboard_url)

    game_id = create_planning_game(
        page,
        coachboard_url,
        'Apply All Undo Stale Opponent',
    )

    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        expect(
            panel(page)
        ).to_be_visible(
            timeout=15_000
        )

        base_keys = planner_base_innings(
            page
        )

        assert len(base_keys) >= 4

        source = base_keys[0]
        targets = base_keys[1:]
        changed_target = targets[2]

        select_inning(
            page,
            source,
        )

        choose_player(
            page,
            'SS',
            'Shortstop Shawn',
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        page.locator(
            '#gmApplyDefenseAllBtn'
        ).click()

        copy_toast = (
            page.locator(
                '#gm-coach-toast-holder '
                '.toast.show'
            )
            .filter(
                has_text=(
                    f'Copied Inning '
                    f'{source}'
                )
            )
            .last
        )

        expect(
            copy_toast
        ).to_be_visible(
            timeout=5_000
        )

        copied = planner_rotation_snapshot(
            page
        )

        source_alignment = copied[source]

        for inning in targets:
            assert (
                copied[inning]
                == source_alignment
            )

        # Simulate a legitimate newer coach edit in exactly one target
        # inning after the copy but before Undo.
        page.evaluate(
            """inning => {
                const rotation =
                    window.CBPregameRotation
                        .getRotation(
                            'Rotation'
                        );

                rotation
                    .innings[inning]
                    .SS = 'Second Sam';

                window.CBPregameRotation
                    .commitLocalChange(
                        'Rotation',
                        false
                    );
            }""",
            changed_target,
        )

        # Do not wait for persistence here. Undo's stale check must use
        # the live canonical store immediately.
        copy_toast.get_by_role(
            'button',
            name='Undo',
        ).click()

        warning = (
            page.locator(
                '#gm-coach-toast-holder '
                '.toast.show'
            )
            .filter(
                has_text=(
                    'Defense changed since then, '
                    'so Undo was not applied.'
                )
            )
            .last
        )

        expect(
            warning
        ).to_be_visible(
            timeout=5_000
        )

        after = planner_rotation_snapshot(
            page
        )

        # The newer edit survives.
        assert (
            after[changed_target]['SS']
            == 'Second Sam'
        )

        # More importantly, Undo must not have restored ANY of the
        # untouched targets either. This proves all-or-nothing behavior.
        for inning in targets:
            if inning == changed_target:
                continue

            assert (
                after[inning]
                == source_alignment
            ), (
                'stale Undo partially restored '
                f'Inning {inning}'
            )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

    finally:
        cleanup(
            page,
            coachboard_url,
            game_id,
        )


def test_plan_options_reorder_settles_after_patch(
    page: Page,
    coachboard_url: str,
):
    """A normal MutationObserver-triggered patch must not keep moving
    the Plan Options children and create a perpetual observer/rAF loop."""
    login(page, coachboard_url)

    game_id = create_planning_game(
        page,
        coachboard_url,
        'Plan Options Mutation Opponent',
    )

    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        expect(
            panel(page)
        ).to_be_visible(
            timeout=15_000
        )

        expect(
            page.get_by_role(
                'button',
                name=re.compile(
                    'Plan Options'
                ),
            )
        ).to_be_visible(
            timeout=10_000
        )

        initial = page.evaluate(
            """() => {
                const title =
                    document.getElementById(
                        'rotation-editor-title'
                    );

                const menu =
                    title
                        ?.closest(
                            '.card-header'
                        )
                        ?.querySelector(
                            '.dropdown-toggle'
                        )
                        ?.nextElementSibling;

                if (!menu) {
                    throw new Error(
                        'Plan Options menu not found'
                    );
                }

                window.__gmMenuMutationCount =
                    0;

                window.__gmMenuMutationObserver
                    ?.disconnect();

                window.__gmMenuMutationObserver =
                    new MutationObserver(
                        records => {
                            window
                                .__gmMenuMutationCount +=
                                records.filter(
                                    record =>
                                        record.type
                                        === 'childList'
                                ).length;
                        }
                    );

                window
                    .__gmMenuMutationObserver
                    .observe(
                        menu,
                        {
                            childList:true,
                        }
                    );

                // Trigger the app's body-wide observer and therefore
                // one normal queuePatch()/patch() cycle.
                document.body
                    .classList.add(
                        'gm-test-patch-pulse'
                    );

                document.body
                    .classList.remove(
                        'gm-test-patch-pulse'
                    );

                return {
                    ordered:
                        menu.dataset.gmOrdered,
                    childCount:
                        menu.children.length,
                };
            }"""
        )

        assert (
            initial['ordered']
            == '1'
        )

        assert (
            initial['childCount']
            >= 11
        )

        page.wait_for_timeout(
            600
        )

        mutations = page.evaluate(
            """() => {
                const count =
                    window
                        .__gmMenuMutationCount
                    || 0;

                window
                    .__gmMenuMutationObserver
                    ?.disconnect();

                return count;
            }"""
        )

        assert mutations == 0, (
            'Plan Options children kept moving '
            f'after patch settled: {mutations} '
            'childList mutation(s)'
        )

    finally:
        cleanup(
            page,
            coachboard_url,
            game_id,
        )


def test_plan_change_confirm_double_tap_creates_only_one_planned_change(
    page: Page,
    coachboard_url: str,
):
    """Two rapid taps on Plan Change during the Bootstrap fade-out must
    execute the pending action only once."""
    login(page, coachboard_url)

    game_id = create_planning_game(
        page,
        coachboard_url,
        'Plan Change Double Tap Opponent',
    )

    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        expect(
            panel(page)
        ).to_be_visible(
            timeout=15_000
        )

        current = page.evaluate(
            """() =>
                document.querySelector(
                    'input[name="inning-radio"]:checked'
                )?.value
            """
        )

        assert current
        assert float(current).is_integer()

        page.get_by_role(
            'button',
            name=re.compile(
                'Plan Options'
            ),
        ).click()

        plan_change = page.get_by_role(
            'button',
            name=re.compile(
                'Plan a Change During This Inning'
            ),
        )

        expect(
            plan_change
        ).to_be_visible(
            timeout=5_000
        )

        plan_change.click()

        modal = page.locator(
            '#gmCoachConfirmModal'
        )

        expect(
            modal
        ).to_be_visible(
            timeout=5_000
        )

        confirm = modal.locator(
            '[data-gm-confirm-action]'
        )

        expect(
            confirm
        ).to_have_text(
            'Plan Change'
        )

        # Dispatch both clicks synchronously so both occur inside the
        # modal fade-out window. Without the action-consumption guard,
        # both hidden.bs.modal handlers execute the pending action.
        # Confirm is enabled only after Bootstrap has fully shown the sheet.
        expect(confirm).to_be_enabled(timeout=5_000)

        page.evaluate(
            """() => {
                const button =
                    document.querySelector(
                        '#gmCoachConfirmModal [data-gm-confirm-action]'
                    );

                if (!button) {
                    throw new Error(
                        'confirm button not found'
                    );
                }

                button.click();
                button.click();
            }"""
        )

        expect(
            modal
        ).not_to_be_visible(
            timeout=10_000
        )

        expect(
            save_status(page)
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        keys = canonical_inning_keys(
            page
        )

        base_number = int(
            float(current)
        )

        planned = [
            key
            for key in keys
            if (
                not float(key).is_integer()
                and int(float(key))
                == base_number
            )
        ]

        assert planned == [
            f'{base_number}.1'
        ], (
            'rapid double tap created more than '
            f'one planned change: {planned}'
        )

    finally:
        cleanup(
            page,
            coachboard_url,
            game_id,
        )
