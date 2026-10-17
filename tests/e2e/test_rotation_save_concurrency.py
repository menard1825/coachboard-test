"""Two coaches, two views, one game's defense, at the same time.

The head coach plans in Classic (the original bench-and-diamond editor), the
assistant in Updated (the tap field). Both save through the same queue to
/save_rotation, which now merges changes to different positions and refuses
a save that would replace the other coach's change to the same position
(rotation_merge.py). Saves are held in the air to force each ordering:

* unrelated positions, both saving at once: both changes kept, no question;
* the same position: the later save is refused, its coach's change stays on
  their screen, unsaved, and they choose -- Use Their Change or Keep Mine;
* a save delayed while the other coach's save and socket refresh land: the
  refresh never overwrites the unsaved edit, and the merge brings both in;
* an edit made while one's own save is still on its way, to a position the
  other coach changed: asked about too, never overwritten;
* Retry while a conflict is open asks again instead of re-sending.
"""

import json
import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from plan_helpers import with_stored_base  # noqa: E402


COACH = ('playwright-coach', 'playwright-password')
ASSISTANT = ('playwright-assistant', 'playwright-assistant-password')
DESKTOP = {'width': 1440, 'height': 900}
IPAD = {'width': 1032, 'height': 1376}

FULL = {'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam',
        '3B': 'Third Theo', 'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey',
        'RF': 'Right Riley'}
# CF and RF open; Center Casey and Right Riley on the bench.
TWO_OPEN = {pos: name for pos, name in FULL.items() if pos not in ('CF', 'RF')}

DIALOG = '#cbRotationConflictModal'


@pytest.fixture
def coaches(browser, classic_view_url):
    """`coaches(game_id)` -> (classic, updated): the head coach on Classic at
    a desktop, the assistant on Updated at an iPad, both on the game."""
    contexts = []

    def sign_in(who, view, viewport, mobile):
        cdn_assets.require_vendored_assets()
        context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        page.cb_errors = []
        page.on('pageerror', lambda error: page.cb_errors.append(str(error)))
        page.goto(f'{classic_view_url}/login')
        page.get_by_label('Username or email').fill(who[0])
        page.locator('#password').fill(who[1])
        page.get_by_role('button', name='Sign In').click()
        expect(page).to_have_url(re.compile(rf'^{re.escape(classic_view_url)}/?(?:#\w+)?$'))
        response = page.request.post(f'{classic_view_url}/api/account/view', data=json.dumps({'view': view}),
                                     headers={'Content-Type': 'application/json'})
        assert response.ok, response.text()
        return page

    def make(game_id):
        classic = sign_in(COACH, 'classic', DESKTOP, False)
        updated = sign_in(ASSISTANT, 'updated', IPAD, True)
        classic.goto(f'{classic_view_url}/game/{game_id}')
        expect(classic.locator('#pos-desktop-P .player-tag')).to_have_count(1, timeout=15_000)
        updated.goto(f'{classic_view_url}/game/{game_id}')
        expect(updated.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)
        return classic, updated

    yield make
    for context in contexts:
        try:
            context.pages[0].request.post(f'{classic_view_url}/api/account/view',
                                          data=json.dumps({'view': 'updated'}),
                                          headers={'Content-Type': 'application/json'})
        except Exception:  # noqa: BLE001 -- best effort
            pass
        context.close()


@pytest.fixture
def game(browser, classic_view_url):
    """A game whose 1st inning is TWO_OPEN; deleted afterwards."""
    context = browser.new_context()
    page = context.new_page()
    page.goto(f'{classic_view_url}/login')
    page.get_by_label('Username or email').fill(COACH[0])
    page.locator('#password').fill(COACH[1])
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state()
    created = []

    def make(opponent):
        response = page.request.post(f'{classic_view_url}/game-day/add', form={
            'game_date': (date.today() + timedelta(days=11)).isoformat(), 'game_start_time': '15:00',
            'game_opponent': opponent, 'game_location': 'Two Coaches Field', 'pitching_rule_set': 'USSSA'},
            max_redirects=0)
        game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
        created.append(game_id)
        page.request.get(f'{classic_view_url}/game/{game_id}')
        rotation = page.request.get(f'{classic_view_url}/api/game_data/{game_id}').json()['rotation']
        saved = page.request.post(f'{classic_view_url}/save_rotation', data=json.dumps(with_stored_base(
            page.request, classic_view_url, {
                'id': rotation['id'], 'title': rotation['title'], 'associated_game_id': game_id,
                'innings': {**rotation['innings'], '1': TWO_OPEN}})), headers={'Content-Type': 'application/json'})
        assert saved.ok, saved.text()
        return game_id

    yield make
    for game_id in created:
        page.request.post(f'{classic_view_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
    context.close()


def _stored(page, url, game_id):
    innings = page.request.get(f'{url}/api/game_data/{game_id}').json()['rotation']['innings']
    return (json.loads(innings) if isinstance(innings, str) else innings)['1']


def _classic_assign(page, position, name):
    page.locator(f'#pos-desktop-{position}').click()
    modal = page.locator('#assignPlayerModal')
    expect(modal).to_be_visible(timeout=10_000)
    modal.locator(f'#assignPlayerModalBenchList a[data-player-name="{name}"]').click()
    expect(modal).to_be_hidden(timeout=10_000)


def _updated_assign(page, position, name):
    page.locator(f'#pregame-defense-editor-v3 [data-pde-pos="{position}"]').click()
    modal = page.locator('#pde-player-modal')
    expect(modal).to_be_visible(timeout=10_000)
    modal.locator(f'.pde-choice[data-player="{name}"]').click()
    expect(modal).to_be_hidden(timeout=10_000)


def _classic_at(page, position):
    return page.locator(f'#pos-desktop-{position} .player-tag')


def _updated_at(page, position):
    return page.locator(f'#pregame-defense-editor-v3 [data-pde-pos="{position}"] .pde-name')


def _hold_saves(page):
    held = []
    page.route('**/save_rotation', lambda route: held.append(route))
    return held


def _release(page, held):
    for route in held:
        route.continue_()
    page.unroute('**/save_rotation')


def _settled(page):
    page.wait_for_function(
        '() => !window.CBPregameRotation.isSaveInFlightOrQueued()'
        ' && !window.CBPregameRotation.hasUnsyncedLocalState()', timeout=15_000)


def _in_flight(page):
    page.wait_for_function('() => window.CBPregameRotation.isSaveInFlightOrQueued()', timeout=10_000)


def test_changes_to_different_positions_are_both_kept(coaches, game, classic_view_url):
    game_id = game('Two Coaches Unrelated')
    classic, updated = coaches(game_id)

    # Both save at once: the Updated coach's save is held while Classic's lands.
    held = _hold_saves(updated)
    _updated_assign(updated, 'RF', 'Right Riley')
    _in_flight(updated)
    _classic_assign(classic, 'CF', 'Center Casey')
    _settled(classic)
    _release(updated, held)
    _settled(updated)

    assert _stored(classic, classic_view_url, game_id) == FULL
    # No question for either coach, and both screens show both changes.
    expect(updated.locator(DIALOG)).to_be_hidden()
    expect(classic.locator(DIALOG)).to_have_count(0)
    expect(_updated_at(updated, 'CF')).to_have_text('Center Casey', timeout=20_000)
    expect(_updated_at(updated, 'RF')).to_have_text('Right Riley')
    expect(_classic_at(classic, 'RF')).to_have_text('Right Riley', timeout=20_000)
    expect(_classic_at(classic, 'CF')).to_have_text('Center Casey')
    assert classic.cb_errors == [] and updated.cb_errors == []


@pytest.mark.parametrize('choice', ['theirs', 'mine'])
def test_the_same_position_is_asked_never_overwritten(coaches, game, classic_view_url, choice):
    game_id = game(f'Two Coaches Same Spot {choice}')
    classic, updated = coaches(game_id)

    held = _hold_saves(updated)
    _updated_assign(updated, 'CF', 'Right Riley')
    _in_flight(updated)
    _classic_assign(classic, 'CF', 'Center Casey')
    _settled(classic)
    _release(updated, held)

    # Refused: the Classic coach's saved choice stands, and the Updated
    # coach's own choice is still on their screen, unsaved.
    dialog = updated.locator(DIALOG)
    expect(dialog).to_be_visible(timeout=15_000)
    expect(dialog).to_contain_text('1st inning, CF: you chose Right Riley; the other coach saved Center Casey.')
    assert _stored(classic, classic_view_url, game_id)['CF'] == 'Center Casey'
    expect(_updated_at(updated, 'CF')).to_have_text('Right Riley')
    assert updated.evaluate('() => window.CBPregameRotation.hasUnsyncedLocalState()')
    expect(updated.locator('#pde-save-status')).to_have_attribute('data-status', 'failed')

    if choice == 'theirs':
        dialog.get_by_role('button', name='Use Their Change').click()
        _settled(updated)
        expect(_updated_at(updated, 'CF')).to_have_text('Center Casey', timeout=10_000)
        assert _stored(classic, classic_view_url, game_id)['CF'] == 'Center Casey'
    else:
        dialog.get_by_role('button', name='Keep My Change').click()
        _settled(updated)
        assert _stored(classic, classic_view_url, game_id)['CF'] == 'Right Riley'
        # The Classic coach's screen follows the deliberate choice.
        expect(_classic_at(classic, 'CF')).to_have_text('Right Riley', timeout=20_000)
    expect(dialog).to_be_hidden()
    assert classic.cb_errors == [] and updated.cb_errors == []


def test_a_delayed_save_survives_the_other_coachs_refresh_and_both_are_kept(coaches, game, classic_view_url):
    game_id = game('Two Coaches Delayed')
    classic, updated = coaches(game_id)

    # Classic's save is delayed; the Updated coach saves and its socket
    # refresh reaches the Classic page meanwhile.
    held = _hold_saves(classic)
    _classic_assign(classic, 'CF', 'Center Casey')
    _in_flight(classic)
    _updated_assign(updated, 'RF', 'Right Riley')
    _settled(updated)
    classic.wait_for_timeout(1500)
    # The refresh did not overwrite the unsaved edit.
    expect(_classic_at(classic, 'CF')).to_have_text('Center Casey')

    _release(classic, held)
    _settled(classic)
    assert _stored(classic, classic_view_url, game_id) == FULL
    # The merge brought the other coach's change onto the Classic screen.
    expect(_classic_at(classic, 'RF')).to_have_text('Right Riley', timeout=10_000)
    expect(_updated_at(updated, 'CF')).to_have_text('Center Casey', timeout=20_000)
    assert classic.cb_errors == [] and updated.cb_errors == []


def test_an_edit_made_while_saving_is_asked_about_and_retry_asks_again(coaches, game, classic_view_url):
    game_id = game('Two Coaches In Flight')
    classic, updated = coaches(game_id)

    # Classic: CF saves (held); then RF is edited while that save is away.
    held = _hold_saves(classic)
    _classic_assign(classic, 'CF', 'Center Casey')
    _in_flight(classic)
    _classic_assign(classic, 'RF', 'Right Riley')
    # Meanwhile the Updated coach puts First Frank into RF (from 1B).
    _updated_assign(updated, 'RF', 'First Frank')
    _settled(updated)

    _release(classic, held)
    # CF merged in; RF clashed with the other coach's saved choice: asked.
    dialog = classic.locator(DIALOG)
    expect(dialog).to_be_visible(timeout=15_000)
    expect(dialog).to_contain_text('RF: you chose Right Riley; the other coach saved First Frank.')
    stored = _stored(classic, classic_view_url, game_id)
    assert stored['CF'] == 'Center Casey' and stored['RF'] == 'First Frank'
    expect(_classic_at(classic, 'RF')).to_have_text('Right Riley')
    pill = classic.locator('#classic-save-status')
    expect(pill).to_have_attribute('data-state', 'failed')
    expect(pill).to_contain_text('another coach changed this')

    # Decide Later keeps everything unsaved on screen; Retry (the save
    # status) asks again rather than re-sending.
    dialog.get_by_role('button', name='Decide Later').click()
    expect(dialog).to_be_hidden()
    expect(_classic_at(classic, 'RF')).to_have_text('Right Riley')
    assert classic.evaluate('() => window.CBPregameRotation.hasUnsyncedLocalState()')
    requests = []
    classic.on('request', lambda request: requests.append(request) if request.url.endswith('/save_rotation') else None)
    pill.click()
    expect(dialog).to_be_visible(timeout=10_000)
    assert requests == []

    dialog.get_by_role('button', name='Keep My Change').click()
    _settled(classic)
    stored = _stored(classic, classic_view_url, game_id)
    assert stored['RF'] == 'Right Riley' and stored['CF'] == 'Center Casey'
    assert classic.cb_errors == [] and updated.cb_errors == []


def _as_an_old_page(page):
    """Send this page's saves the way a tab opened before this protection
    would: the whole plan, without the stored plan it was made from."""
    def strip_base(route):
        body = json.loads(route.request.post_data or '{}')
        body.pop('base_innings', None)
        route.continue_(post_data=json.dumps(body))
    page.route('**/save_rotation', strip_base)


def test_an_out_of_date_page_cannot_overwrite_the_saved_plan(coaches, game, classic_view_url):
    game_id = game('Two Coaches Old Tab')
    classic, updated = coaches(game_id)

    # The Updated coach saves CF; then a Classic page running old code
    # saves its own (older) plan with RF filled.
    _updated_assign(updated, 'CF', 'Center Casey')
    _settled(updated)
    _as_an_old_page(classic)
    _classic_assign(classic, 'RF', 'Right Riley')

    pill = classic.locator('#classic-save-status')
    expect(pill).to_have_attribute('data-state', 'failed', timeout=15_000)
    expect(pill).to_have_text('Not saved — refresh this page to keep editing')
    assert classic.evaluate("() => window.CBPregameRotation.getLastError().code") == 'rotation_refresh_required'
    # The saved plan is the Updated coach's, untouched; the old page's edit
    # is still on its own screen, unsaved.
    stored = _stored(classic, classic_view_url, game_id)
    assert stored['CF'] == 'Center Casey' and 'RF' not in stored
    expect(_classic_at(classic, 'RF')).to_have_text('Right Riley')
    expect(classic.locator(DIALOG)).to_have_count(0)

    # The same in Updated: told to refresh, nothing overwritten.
    _as_an_old_page(updated)
    _updated_assign(updated, 'RF', 'Right Riley')
    status = updated.locator('#pde-save-status')
    expect(status).to_have_attribute('data-status', 'failed', timeout=15_000)
    expect(status).to_contain_text('This page is out of date')
    expect(status).to_contain_text('Refresh the page')
    assert 'RF' not in _stored(classic, classic_view_url, game_id)

    # After a refresh (current code), the edit saves normally.
    classic.unroute('**/save_rotation')
    classic.reload()
    expect(classic.locator('#pos-desktop-P .player-tag')).to_have_count(1, timeout=15_000)
    _classic_assign(classic, 'RF', 'Right Riley')
    _settled(classic)
    assert _stored(classic, classic_view_url, game_id) == FULL
    assert classic.cb_errors == [] and updated.cb_errors == []
