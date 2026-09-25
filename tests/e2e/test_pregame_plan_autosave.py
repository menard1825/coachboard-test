"""The pregame game plan autosaves; there is no manual Save Rotation.

The manual Save Rotation buttons were removed on purpose: every field or plan
change is saved as it happens, and the save status in the Set Defense panel
is the one place a coach sees Saving / Saved / Save failed. This covers that
contract end to end:

* a field change and a plan (inning) change each save on their own;
* a failed autosave stays visible, offers tap-to-retry and never raises a
  browser alert;
* another game's save broadcast cannot refresh this page over a save that is
  still in flight.

Saving the plan as a reusable named Game Plan ("Save game plan") is covered by
test_set_defense_simplified.py::test_save_game_plan_creates_a_reusable_named_plan.
The store's queueing details (coalescing, keepalive, stale refreshes) are
covered by test_pregame_defense_save_reliability.py.
"""

import json
import os
import re
import uuid
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect

import cdn_assets


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
PANEL = '#pregame-defense-editor-v3'
PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})


@pytest.fixture
def open_page(browser, coachboard_url):
    """A logged-in page per device that records every browser dialog."""
    contexts = []

    def _open(device=DESKTOP):
        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        page.dialogs = []

        def on_dialog(dialog):
            page.dialogs.append((dialog.type, dialog.message))
            dialog.accept()

        page.on('dialog', on_dialog)
        page.goto(f'{coachboard_url}/login')
        page.get_by_label('Username or email').fill(TEST_USERNAME)
        page.locator('#password').fill(TEST_PASSWORD)
        page.get_by_role('button', name='Sign In').click()
        page.wait_for_load_state('load')
        return page

    yield _open
    for context in contexts:
        context.close()


@pytest.fixture
def new_game(open_page, coachboard_url):
    """Future games this test owns; every one is deleted afterwards."""
    setup = open_page()
    created = []

    def _new():
        response = setup.request.post(f'{coachboard_url}/game-day/add', form={
            'game_date': (date.today() + timedelta(days=10)).isoformat(), 'game_start_time': '15:00',
            'game_opponent': f'Autosave {uuid.uuid4().hex[:6]}', 'game_location': 'Autosave Field',
            'pitching_rule_set': 'USSSA'}, max_redirects=0)
        assert response.status in {302, 303}, response.text()
        game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
        created.append(game_id)
        return game_id

    yield _new
    for game_id in created:
        setup.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})


def _open_game(page, base_url, game_id):
    page.goto(f'{base_url}/game/{game_id}')
    expect(page.locator(PANEL)).to_be_visible(timeout=20_000)


def _status(page):
    return page.locator(f'{PANEL} #pde-save-status')


def _choose(page, position, player):
    page.locator(f'{PANEL} [data-pde-pos="{position}"]').click()
    chooser = page.locator('#pde-player-modal')
    expect(chooser).to_be_visible(timeout=10_000)
    chooser.locator(f'.pde-choice[data-player="{player}"]').click()
    expect(chooser).to_be_hidden(timeout=10_000)


def _rotation(page, base_url, game_id):
    rotation = page.request.get(f'{base_url}/api/game_data/{game_id}').json()['rotation']
    innings = rotation['innings']
    return rotation, (json.loads(innings) if isinstance(innings, str) else innings)


def _alerts(page):
    return [message for kind, message in page.dialogs if kind == 'alert']


@pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])
def test_field_change_autosaves_with_no_save_button(open_page, new_game, coachboard_url, device):
    page = open_page(device)
    game_id = new_game()
    _open_game(page, coachboard_url, game_id)

    expect(page.locator('#saveRotationBtn')).to_have_count(0)
    expect(page.locator('#saveRotationBtnMobile')).to_be_hidden()

    _choose(page, 'SS', 'Shortstop Shawn')
    expect(_status(page)).to_contain_text('Saved', timeout=10_000)
    _, innings = _rotation(page, coachboard_url, game_id)
    assert innings['1']['SS'] == 'Shortstop Shawn'
    assert _alerts(page) == []


def test_plan_change_autosaves(open_page, new_game, coachboard_url):
    page = open_page()
    game_id = new_game()
    _open_game(page, coachboard_url, game_id)
    _, before = _rotation(page, coachboard_url, game_id)

    page.get_by_role('button', name='Plan Options').click()
    page.locator('.gm-plan-options-menu.show #gmPlanAddInning').click()
    expect(_status(page)).to_contain_text('Saved', timeout=10_000)

    _, after = _rotation(page, coachboard_url, game_id)
    added = sorted(set(after) - set(before), key=int)
    assert added == [str(max(int(key) for key in before) + 1)], (sorted(before), sorted(after))


def test_failed_autosave_stays_visible_and_retries_without_an_alert(open_page, new_game, coachboard_url):
    page = open_page()
    game_id = new_game()
    _open_game(page, coachboard_url, game_id)

    page.route('**/save_rotation', lambda route: route.fulfill(
        status=500, content_type='application/json', body='{"message": "simulated failure"}'))
    _choose(page, 'SS', 'Shortstop Shawn')

    expect(_status(page)).to_have_attribute('data-status', 'failed', timeout=10_000)
    expect(_status(page)).to_have_text(re.compile(r'Save failed: simulated failure — tap to retry'))
    page.wait_for_timeout(2500)
    expect(_status(page)).to_have_attribute('data-status', 'failed')
    assert _alerts(page) == [], 'A failed autosave is reported by the save status, not an alert.'

    page.unroute('**/save_rotation')
    _status(page).click()
    expect(_status(page)).to_contain_text('Saved', timeout=10_000)
    _, innings = _rotation(page, coachboard_url, game_id)
    assert innings['1']['SS'] == 'Shortstop Shawn'
    assert _alerts(page) == []


def test_another_games_save_does_not_refresh_over_an_inflight_autosave(open_page, new_game, coachboard_url):
    page = open_page()
    game_id, other_game_id = new_game(), new_game()
    _open_game(page, coachboard_url, game_id)

    held = {}

    def hold_own_save(route):
        body = json.loads(route.request.post_data or '{}')
        if 'route' not in held and body.get('associated_game_id') == game_id:
            held['route'] = route
            return
        route.continue_()

    page.route('**/save_rotation', hold_own_save)
    try:
        _choose(page, 'SS', 'Shortstop Shawn')
        expect(_status(page)).to_contain_text('Saving', timeout=10_000)

        # Saving any game broadcasts a team-wide rotation_save event. While
        # this page's own save is in flight it must not refetch the game.
        refreshes = []
        page.on('request', lambda request: refreshes.append(request.url)
                if f'/api/game_data/{game_id}' in request.url else None)
        other = page.request.post(f'{coachboard_url}/save_rotation', data={
            'title': 'Other Game', 'innings': {'1': {}}, 'associated_game_id': other_game_id})
        assert other.ok and other.json().get('status') == 'success', other.text()
        page.wait_for_timeout(700)

        expect(_status(page)).to_contain_text('Saving')
        expect(page.locator(f'{PANEL} [data-pde-pos="SS"] .pde-name')).to_have_text('Shortstop Shawn')
        assert refreshes == [], refreshes

        held['route'].continue_()
        expect(_status(page)).to_contain_text('Saved', timeout=15_000)
    finally:
        page.unroute('**/save_rotation')

    _, innings = _rotation(page, coachboard_url, game_id)
    assert innings['1']['SS'] == 'Shortstop Shawn'
