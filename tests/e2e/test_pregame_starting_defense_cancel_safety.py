"""Regression coverage for a cancellation side-effect bug in
static/js/pregame_starting_defense_scope.js's applyStartingDefenseToGame(),
found in an independent review of the round-6 writer-consolidation fix.

Before round 6, this "Apply to Game" action built its proposed game-wide
Starting Defense against a working copy parsed from a freshly re-fetched
/api/game_data snapshot (parseInnings(data.rotation?.innings)) — a
detached object. Canceling the confirm() dialog simply discarded it.

Round 6 correctly moved this action onto the canonical CBPregameRotation
rotation object instead of that stale, independently re-fetched snapshot
(to close the cross-module lost-update race also fixed for the other
former writers). But it did so by mutating rotation.innings — the
canonical object itself — DURING the proposal-building step, before the
confirm() dialog was even shown. Canceling that dialog returned early
without ever calling commitLocalChange(), but the canonical rotation had
already been rewritten in memory: a later, completely unrelated save
could persist the "canceled" Starting Defense into the DB.

The fix builds the proposal on a detached deep copy of the canonical
innings and only assigns it back to the canonical rotation object (then
saves through the shared queue) after the coach confirms. This test
proves cancellation now leaves the canonical rotation, the visible
defense, and the DB completely untouched.
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
            'game_location': 'Starting Defense Cancel Safety Field',
            'game_notes': 'Disposable starting-defense cancel-safety test',
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


def test_canceling_apply_to_game_leaves_canonical_rotation_and_db_untouched(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_planning_game(page, coachboard_url, 'Starting Defense Cancel Safety Opponent')
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(panel(page)).to_be_visible(timeout=15_000)

        # Establish a distinctive existing defense: SS is a player the
        # Starting Defense preset below will NOT put at SS, so applying
        # (or failing to properly cancel) the preset is unmistakable.
        choose_player(page, 'SS', 'Second Sam')
        expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

        data = get_game_data(page, coachboard_url, game_id)
        assert data['rotation']['innings']['1']['SS'] == 'Second Sam'

        # A Starting Defense preset that would visibly change SS if applied.
        preset_innings = {
            'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam',
            '3B': 'Third Theo', 'SS': 'Shortstop Shawn', 'LF': 'Left Lee',
            'CF': 'Center Casey', 'RF': 'Right Riley',
        }
        created = page.request.post(
            f'{coachboard_url}/api/starting-defense-template/save',
            data=json.dumps({'title': f'Cancel Safety Preset {game_id}', 'innings': {'1': preset_innings}}),
            headers={'Content-Type': 'application/json'},
        )
        assert created.ok, created.text()
        template_id = created.json().get('id') or created.json().get('new_template', {}).get('id')

        try:
            # Reload so the fresh preset is present in the initial
            # rotation_templates the #pde-preset dropdown is built from.
            page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
            expect(panel(page)).to_be_visible(timeout=15_000)

            select = page.locator('#pde-preset')
            expect(select).to_be_visible(timeout=10_000)
            select.select_option(label=f'Cancel Safety Preset {game_id}')

            # Use -> Whole game runs the same Whole game apply.
            page.locator('#pde-use').click()
            apply_to_game = page.locator('#pde-use-game')
            expect(apply_to_game).to_be_visible(timeout=10_000)

            # Dismiss (Cancel) the confirmation dialog this action shows.
            page.once('dialog', lambda dialog: dialog.dismiss())
            apply_to_game.click()
            page.wait_for_timeout(500)

            # Nothing should have started saving: the canceled action must
            # never have called commitLocalChange().
            expect(save_status(page)).not_to_contain_text('Saving')
            expect(save_status(page)).not_to_contain_text('Saved')

            assert canonical_innings(page)['1']['SS'] == 'Second Sam', (
                'canceling Apply to Game must leave the canonical CBPregameRotation rotation unchanged'
            )
            expect(panel(page).locator('[data-pde-pos="SS"] .pde-name')).to_have_text('Second Sam')

            data = get_game_data(page, coachboard_url, game_id)
            assert data['rotation']['innings']['1']['SS'] == 'Second Sam', (
                'canceling Apply to Game must leave the DB unchanged'
            )

            # A completely unrelated normal defense edit/save must not
            # resurrect and persist the canceled Starting Defense either.
            choose_player(page, '2B', 'Center Casey')
            expect(save_status(page)).to_contain_text('Saved', timeout=10_000)

            data = get_game_data(page, coachboard_url, game_id)
            assert data['rotation']['innings']['1']['SS'] == 'Second Sam', (
                'the canceled Starting Defense reappeared in the DB after a later, unrelated save'
            )
            assert data['rotation']['innings']['1']['2B'] == 'Center Casey'
        finally:
            if template_id:
                page.request.get(f'{coachboard_url}/delete_rotation/{template_id}')
    finally:
        cleanup(page, coachboard_url, game_id)
