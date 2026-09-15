"""Regression coverage for a second (and third) direct /save_rotation
writer found in an independent review of the CBPregameRotation
architecture: static/js/game_management_coach_simplify.js's
"Remove This Planned Change" action (removeCurrentMidInningChange())
built its own full-rotation payload from an independently re-fetched
/api/game_data snapshot and POSTed straight to /save_rotation, entirely
bypassing the shared CBPregameRotation store and its one save queue.

That meant a normal shared-queue save (a field edit, an inning-toolbar
action, anything routed through commitLocalChange()) that was already in
flight when a coach removed a mid-inning planned change (e.g. "1.1")
raced against this action's own independent POST: whichever request the
server finished processing LAST won, so the earlier shared save's stale
full-rotation snapshot (still containing "1.1") could land after the
direct delete and silently resurrect the removed planned change.

The fix makes removeCurrentMidInningChange() mutate the canonical
window.CBPregameRotation rotation object in place and save through the
one shared queue, exactly like every other pregame writer — eliminating
the second writer rather than merely serializing around it. This test
proves the race is actually gone: a genuinely in-flight shared save can no
longer produce two independent, unordered /save_rotation requests, so the
coalesced follow-up is always built from the current (already-deleted)
canonical state.
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
    """"Remove This Planned Change" shows a confirm() before deleting.
    Accept every dialog so the flow under test can proceed unattended."""
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
    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=days_offset)).isoformat(),
            'game_start_time': '15:00',
            'game_opponent': opponent,
            'game_location': 'Writer Consolidation Field',
            'game_notes': 'Disposable writer-consolidation test',
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


def canonical_innings(page: Page):
    return page.evaluate("window.CBPregameRotation.getRotation('x').innings")


def click_hidden(page: Page, element_id: str):
    """Fire a real click on an element game_management_coach_simplify.js
    keeps inside a collapsed dropdown menu (the same
    document.getElementById(id).click() mechanism a real coach opening
    that menu and clicking the item would trigger)."""
    page.evaluate(f"document.getElementById('{element_id}')?.click()")


def select_inning(page: Page, inning_key: str):
    page.locator(f'label[for="inning-{inning_key}"]').click()


@pytest.mark.parametrize(
    'release_order',
    ['field_edit_response_first', 'remove_response_first'],
)
def test_remove_planned_change_during_inflight_save_keeps_it_deleted(page: Page, coachboard_url: str, release_order):
    """Create a real mid-inning planned change (sub-inning "1.1"), start a
    normal shared rotation save and hold it in flight, then invoke the
    real user-facing "Remove This Planned Change" action while that save
    is still outstanding. Both possible response-arrival orders are
    covered: before the fix, this action's own independent POST could
    race the shared save and have "1.1" resurrected by whichever request
    the server finished last."""
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, f'Remove Planned Change Race {release_order} Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        # Create the mid-inning planned change under test.
        click_hidden(page, 'addSubInningBtn')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert '1.1' in data['rotation']['innings'], 'expected Add Sub-Inning to have created inning 1.1'

        # Switch to base inning 1 (Add Sub-Inning's own render leaves 1.1
        # checked) and make the field edit that starts/holds the shared
        # save there — deliberately a DIFFERENT inning than the one being
        # removed, so the final assertions can tell the two effects apart:
        # the edit surviving and 1.1 actually being gone, not just one
        # overwriting the other.
        select_inning(page, '1')
        expect(panel(page).locator('.pde-inning strong')).to_have_text('1', timeout=10_000)
        page.wait_for_timeout(300)

        held_routes = []
        auto_continue = {'flag': False}

        def handle_save(route):
            if auto_continue['flag']:
                route.continue_()
                return
            held_routes.append(route)

        page.route('**/save_rotation', handle_save)

        # Start/hold a normal shared rotation save on inning 1.
        choose_player(page, 'SS', 'Shortstop Shawn')
        expect(save_status(page)).to_contain_text('Saving', timeout=10_000)
        page.wait_for_timeout(400)
        assert held_routes, 'expected the field-edit save to have started a held /save_rotation request'

        # Switch to 1.1 (a genuine transition, since inning 1 is currently
        # selected) so the remove action targets the actual planned
        # change, and let coach-simplify's own patch cycle inject "Remove
        # This Planned Change" for it — all while the save above is still
        # held in flight.
        select_inning(page, '1.1')
        expect(panel(page).locator('.pde-inning strong')).to_have_text('1.1', timeout=10_000)
        page.wait_for_timeout(300)

        # Invoke the real user-facing "Remove This Planned Change" action
        # while that save is still in flight.
        click_hidden(page, 'gmRemoveCurrentSubInning')
        page.wait_for_timeout(700)

        batch = list(held_routes)
        order = list(reversed(batch)) if release_order == 'remove_response_first' else batch

        auto_continue['flag'] = True
        for route in order:
            response = route.fetch()
            route.fulfill(response=response)
            page.wait_for_timeout(250)

        page.wait_for_timeout(1500)
        expect(save_status(page)).to_contain_text('Saved', timeout=15_000)

        assert '1.1' not in canonical_innings(page), (
            f'[{release_order}] 1.1 was resurrected in the canonical CBPregameRotation rotation'
        )
        assert page.locator('label[for="1.1"]').count() == 0
        assert page.locator('#inning-btn-group input[name="inning-radio"][value="1.1"]').count() == 0, (
            f'[{release_order}] the removed planned change\'s radio is still in the DOM'
        )

        data = get_game_data(page, coachboard_url, game_id)
        assert '1.1' not in data['rotation']['innings'], (
            f'[{release_order}] 1.1 reappeared in the DB'
        )
        assert data['rotation']['innings']['1']['SS'] == 'Shortstop Shawn'

        # A later rotation edit/save must not resurrect it either.
        click_hidden(page, 'addInningBtn')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert '1.1' not in data['rotation']['innings'], (
            f'[{release_order}] 1.1 reappeared in the DB after a later save'
        )
    finally:
        page.unroute('**/save_rotation')
        cleanup(page, coachboard_url, game_id)
