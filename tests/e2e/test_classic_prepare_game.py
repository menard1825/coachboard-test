"""Classic Prepare Game: the original CoachBoard game page on today's data.

Runs against the server that offers the Classic view to every coach
(classic_view_url), on a desktop, iPad Pro portrait and landscape, and a
phone. Checks that Classic shows the original screens -- Availability and
Batting Lineup cards, inning tabs and tools, the bench-and-diamond drag,
the phone diamond with Assign Player, the Rotation Matrix, the playing time
summary and the Pitching Log -- and that every edit goes through the same
save queue, server rules and Start Game checks as Updated.
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
from start_helpers import start_body  # noqa: E402
from plan_helpers import with_stored_base  # noqa: E402
from e2e_cleanup import release_game  # noqa: E402


COACH = ('playwright-coach', 'playwright-password')
ASSISTANT = ('playwright-assistant', 'playwright-assistant-password')

DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
IPAD_PORTRAIT = ('ipad-pro-portrait', {'width': 1032, 'height': 1376}, {'is_mobile': True, 'has_touch': True})
IPAD_LANDSCAPE = ('ipad-pro-landscape', {'width': 1376, 'height': 1032}, {'is_mobile': True, 'has_touch': True})
PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
ALL_DEVICES = [DESKTOP, IPAD_PORTRAIT, IPAD_LANDSCAPE, PHONE]

FULL = {'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam',
        '3B': 'Third Theo', 'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey',
        'RF': 'Right Riley'}
NO_CF = {pos: name for pos, name in FULL.items() if pos != 'CF'}

UPDATED_ONLY = ('live_game_v2.js', 'live_game_contract.js', 'game_setup_ux.js', 'live_game_board_prep.js',
                'live_game_board_prep_v2.js', 'game_management_coach_simplify.js',
                'game_management_visual_polish.js', 'live_game_feedback_pass.js')

START = '#startLiveGameBtnAction'
SHEET = '#cbStartGameModal'


def ids(spec):
    return spec[0]


@pytest.fixture
def device(browser, classic_view_url):
    """`device(spec, who=COACH, view='classic')`: a signed-in page in its own
    context, on the chosen view; each page carries `cb_errors`. Every coach
    is put back on Updated afterwards."""
    contexts = []

    def make(spec, who=COACH, view='classic'):
        cdn_assets.require_vendored_assets()
        _, viewport, extra = spec
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        page.cb_errors = []
        page.on('pageerror', lambda error: page.cb_errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(f'{classic_view_url}/login')
        page.get_by_label('Username or email').fill(who[0])
        page.locator('#password').fill(who[1])
        page.get_by_role('button', name='Sign In').click()
        expect(page).to_have_url(re.compile(rf'^{re.escape(classic_view_url)}/?(?:#\w+)?$'))
        _set_view(page, classic_view_url, view)
        return page

    yield make
    for context in contexts:
        try:
            _set_view(context.pages[0], classic_view_url, 'updated')
        except Exception:  # noqa: BLE001 -- best effort; the page may be gone
            pass
        context.close()


def _set_view(page, url, view):
    response = page.request.post(f'{url}/api/account/view', data=json.dumps({'view': view}),
                                 headers={'Content-Type': 'application/json'})
    assert response.ok, response.text()


def _game(page, url, opponent, innings=None, lineup=None):
    response = page.request.post(f'{url}/game-day/add', form={
        'game_date': (date.today() + timedelta(days=9)).isoformat(), 'game_start_time': '15:00',
        'game_opponent': opponent, 'game_location': 'Classic Field', 'pitching_rule_set': 'USSSA'},
        max_redirects=0)
    game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
    # Opening the game provisions its regulation innings.
    page.request.get(f'{url}/game/{game_id}')
    data = _data(page, url, game_id)
    if innings:
        rotation = data['rotation']
        saved = page.request.post(f'{url}/save_rotation', data=json.dumps(with_stored_base(page.request, url, {
            'id': rotation['id'], 'title': rotation['title'], 'associated_game_id': game_id,
            'innings': {**rotation['innings'], **innings}})), headers={'Content-Type': 'application/json'})
        assert saved.ok, saved.text()
    if lineup:
        by_name = {player['name']: player['id'] for player in data['roster']}
        saved = page.request.post(f'{url}/add_lineup', data=json.dumps({
            'title': f'Lineup vs {opponent}', 'lineup_data': lineup,
            'lineup_player_ids': [by_name[name] for name in lineup], 'associated_game_id': game_id}),
            headers={'Content-Type': 'application/json'})
        assert saved.ok, saved.text()
    return game_id


def _data(page, url, game_id):
    response = page.request.get(f'{url}/api/game_data/{game_id}')
    assert response.ok, response.text()
    return response.json()


def _innings(page, url, game_id):
    innings = _data(page, url, game_id)['rotation']['innings']
    return json.loads(innings) if isinstance(innings, str) else innings


def _delete(page, url, game_id):
    # Ends the game first if a test started it: a live game locks the
    # team's roster for every later test on the shared server.
    release_game(page.request, url, game_id)


def _open(page, url, game_id):
    page.goto(f'{url}/game/{game_id}')
    expect(page.locator('#classicPrepareGame')).to_be_visible(timeout=15_000)
    expect(page.locator('#inning-btn-group input[name="inning-radio"]').first).to_be_attached(timeout=15_000)


def _spot(page, position):
    """The position on whichever diamond this screen shows (desktop/iPad, or phone)."""
    return page.locator(f'#pos-desktop-{position}:visible, #pos-mobile-{position}:visible')


def _inning(page, number):
    page.locator(f'#inning-btn-group label[for="inning-{number}"]').click()
    expect(page.locator(f'#inning-btn-group input[value="{number}"]')).to_be_checked()


def _assign(page, position, name):
    _spot(page, position).click()
    modal = page.locator('#assignPlayerModal')
    expect(modal).to_be_visible(timeout=10_000)
    modal.locator(f'#assignPlayerModalBenchList a[data-player-name="{name}"]').click()
    expect(modal).to_be_hidden(timeout=10_000)


def _saved(page):
    """The Classic save status shows the queue settled and saved."""
    page.wait_for_function(
        '() => !window.CBPregameRotation.isSaveInFlightOrQueued() && !window.CBPregameRotation.hasUnsyncedLocalState()',
        timeout=15_000)
    expect(page.locator('#classic-save-status')).to_have_attribute('data-state', re.compile(r'^(saved|idle)$'))


def _choose(page, view):
    """Pick a view from the account menu, as the coach would on this device."""
    if page.viewport_size['width'] >= 992:
        page.locator('#userMenuDesktop').click()
        item = page.locator(f'.dropdown-menu [data-cb-view-set="{view}"]')
    else:
        page.locator('a[href="#userOffcanvas"]').click()
        item = page.locator(f'#userOffcanvas [data-cb-view-set="{view}"]')
    expect(item).to_be_visible()
    item.click()


MEASURE = """(vw) => ({
  scrollWidth: document.documentElement.scrollWidth,
  wide: [...document.querySelectorAll('#classicPrepareGame .card, #classicGameBar, #rotation-board .row')]
    .filter(el => el.getClientRects().length && el.getBoundingClientRect().right > vw + 0.5)
    .map(el => el.id || el.className.slice(0, 40)),
  scripts: performance.getEntriesByType('resource').map(e => e.name.split('?')[0].split('/').pop()),
})"""


# --- The original screens ----------------------------------------------------------

@pytest.mark.parametrize('spec', ALL_DEVICES, ids=ids)
def test_the_original_prepare_game_screens(device, classic_view_url, spec):
    coach = device(spec)
    game_id = _game(coach, classic_view_url, f'Classic Layout {spec[0]}', {'1': FULL},
                    lineup=list(FULL.values()))
    try:
        _open(coach, classic_view_url, game_id)
        expect(coach.locator('body')).to_have_attribute('data-cb-view', 'classic')
        expect(coach.locator('#classicGameBar')).to_contain_text('Back to All Games')
        expect(coach.locator('#classicAvailabilityCard')).to_contain_text('9 players present, 0 absent.')
        expect(coach.locator('#classicLineupCard li')).to_have_count(9)
        expect(coach.locator('#inning-btn-group input[name="inning-radio"]')).to_have_count(6)
        for tool in ('#addInningBtn', '#removeInningBtn', '#copyPreviousInningBtn'):
            expect(coach.locator(tool)).to_be_visible()
        expect(coach.locator(START)).to_be_enabled(timeout=15_000)
        expect(coach.locator('#classic-save-status')).to_be_visible()
        expect(coach.locator('#pitcher-availability-card table')).to_be_visible()
        expect(coach.locator('#game-pitching-rules-v2')).not_to_be_empty(timeout=15_000)
        if spec is PHONE:
            expect(coach.locator('#diamond-parent-mobile')).to_be_visible()
            expect(_spot(coach, 'P').locator('.player-tag')).to_have_text('Pitcher Pat')
        else:
            expect(coach.locator('#diamond-parent-desktop')).to_be_visible()
            expect(coach.locator('#bench-list-desktop')).to_be_visible()
            expect(coach.locator('#rotationMatrixCollapse table')).to_be_visible()
            expect(coach.locator('#summary-desktop table')).to_be_visible()
            expect(_spot(coach, 'P').locator('.player-tag')).to_have_text('Pitcher Pat')
        # None of the Updated Prepare Game, and nothing wider than the screen.
        expect(coach.locator('#pregame-defense-editor-v3')).to_have_count(0)
        expect(coach.locator('#pregame-checklist-container')).to_have_count(0)
        measured = coach.evaluate(MEASURE, spec[1]['width'])
        assert measured['scrollWidth'] <= spec[1]['width'], measured
        assert measured['wide'] == [], measured
        assert not set(UPDATED_ONLY) & set(measured['scripts']), measured['scripts']
        assert coach.cb_errors == []
    finally:
        _delete(coach, classic_view_url, game_id)


# --- Editing the defense: one save queue, same data as Updated ---------------------

@pytest.mark.parametrize('spec', ALL_DEVICES, ids=ids)
def test_assigning_a_bench_player_saves_and_tapping_them_benches_them(device, classic_view_url, spec):
    coach = device(spec)
    game_id = _game(coach, classic_view_url, f'Classic Assign {spec[0]}', {'1': NO_CF})
    try:
        _open(coach, classic_view_url, game_id)
        _assign(coach, 'CF', 'Center Casey')
        expect(_spot(coach, 'CF').locator('.player-tag')).to_have_text('Center Casey')
        _saved(coach)
        assert _innings(coach, classic_view_url, game_id)['1'] == FULL

        # Tapping a player on the field sends them back to the bench.
        _spot(coach, 'CF').click()
        expect(_spot(coach, 'CF').locator('.player-tag')).to_have_count(0)
        _saved(coach)
        assert _innings(coach, classic_view_url, game_id)['1'] == NO_CF
        assert coach.cb_errors == []
    finally:
        _delete(coach, classic_view_url, game_id)


def test_dragging_from_the_bench_onto_the_diamond(device, classic_view_url):
    coach = device(DESKTOP)
    game_id = _game(coach, classic_view_url, 'Classic Drag', {'1': NO_CF})
    try:
        _open(coach, classic_view_url, game_id)
        tag = coach.locator('#bench-list-desktop .player-tag[data-player-name="Center Casey"]')
        expect(tag).to_be_visible()
        tag.drag_to(coach.locator('#pos-desktop-CF'))
        expect(coach.locator('#pos-desktop-CF .player-tag')).to_have_text('Center Casey', timeout=10_000)
        expect(coach.locator('#bench-list-desktop .player-tag[data-player-name="Center Casey"]')).to_have_count(0)
        _saved(coach)
        assert _innings(coach, classic_view_url, game_id)['1'] == FULL
        # The matrix and the playing time summary follow.
        expect(coach.locator('#rotationMatrixCollapse tr', has_text='Center Casey')).to_contain_text('CF')
        expect(coach.locator('#summary-desktop tr', has_text='Center Casey')).to_contain_text('CF')
        assert coach.cb_errors == []
    finally:
        _delete(coach, classic_view_url, game_id)


@pytest.mark.parametrize('spec', [DESKTOP, IPAD_PORTRAIT, PHONE], ids=ids)
def test_copying_an_inning(device, classic_view_url, spec):
    coach = device(spec)
    game_id = _game(coach, classic_view_url, f'Classic Copy {spec[0]}', {'1': FULL})
    try:
        _open(coach, classic_view_url, game_id)
        # Copy Previous: the 2nd becomes the 1st (the confirm is accepted).
        _inning(coach, 2)
        coach.locator('#copyPreviousInningBtn').click()
        expect(_spot(coach, 'P').locator('.player-tag')).to_have_text('Pitcher Pat')
        _saved(coach)
        assert _innings(coach, classic_view_url, game_id)['2'] == FULL

        # Copy to Multiple: the 1st into the 4th and 5th.
        _inning(coach, 1)
        coach.locator('#rotation-board .dropdown-toggle', has_text='More Tools').click()
        coach.locator('#copyInningBtn').click()
        for inning in ('4', '5'):
            coach.locator(f'#paste-check-{inning}').check()
        coach.locator('#pasteToSelectedBtn').click()
        _saved(coach)
        innings = _innings(coach, classic_view_url, game_id)
        assert innings['4'] == FULL and innings['5'] == FULL
        assert innings['3'] == {} and innings['6'] == {}
        assert coach.cb_errors == []
    finally:
        _delete(coach, classic_view_url, game_id)


@pytest.mark.parametrize('spec', [DESKTOP, PHONE], ids=ids)
def test_adding_and_removing_an_inning(device, classic_view_url, spec):
    coach = device(spec)
    game_id = _game(coach, classic_view_url, f'Classic Innings {spec[0]}', {'1': FULL})
    try:
        _open(coach, classic_view_url, game_id)
        coach.locator('#addInningBtn').click()
        expect(coach.locator('#inning-btn-group input[name="inning-radio"]')).to_have_count(7)
        _saved(coach)
        assert '7' in _innings(coach, classic_view_url, game_id)
        coach.locator('#removeInningBtn').click()
        expect(coach.locator('#inning-btn-group input[name="inning-radio"]')).to_have_count(6)
        _saved(coach)
        assert '7' not in _innings(coach, classic_view_url, game_id)
        assert coach.cb_errors == []
    finally:
        _delete(coach, classic_view_url, game_id)


# --- Batting lineup and availability ---------------------------------------------------

@pytest.mark.parametrize('spec', [DESKTOP, IPAD_LANDSCAPE, PHONE], ids=ids)
def test_changing_the_batting_lineup(device, classic_view_url, spec):
    coach = device(spec)
    game_id = _game(coach, classic_view_url, f'Classic Lineup {spec[0]}')
    try:
        _open(coach, classic_view_url, game_id)
        expect(coach.locator('#classicLineupCard')).to_contain_text('No lineup has been set.')
        coach.locator('#classicLineupCard').get_by_role('button', name='Edit Lineup').click()
        modal = coach.locator('#lineupEditorModal')
        expect(modal).to_be_visible(timeout=10_000)
        for name in ('Left Lee', 'Catcher Cole'):
            modal.locator(f'#lineup-bench [data-player-name="{name}"] .add-player-btn').click()
        # Catcher Cole up to lead off.
        modal.locator('#lineup-order [data-player-name="Catcher Cole"] .move-up-btn').click()
        modal.locator('#saveLineupBtn').click()
        # The original page reloads after a lineup save.
        expect(coach.locator('#classicLineupCard li')).to_have_text(['Catcher Cole', 'Left Lee'], timeout=15_000)
        assert _data(coach, classic_view_url, game_id)['lineup']['lineup_positions'] == ['Catcher Cole', 'Left Lee']
        assert coach.cb_errors == []
    finally:
        _delete(coach, classic_view_url, game_id)


@pytest.mark.parametrize('spec', [DESKTOP, IPAD_PORTRAIT, PHONE], ids=ids)
def test_a_player_marked_out_is_shown_and_blocks_start(device, classic_view_url, spec):
    coach = device(spec)
    game_id = _game(coach, classic_view_url, f'Classic Out {spec[0]}', {'1': FULL},
                    lineup=list(FULL.values()))
    try:
        _open(coach, classic_view_url, game_id)
        expect(coach.locator(START)).to_be_enabled(timeout=15_000)
        coach.locator('#availabilityToggleBtn').click()
        out = coach.locator('#gameAvailabilityForm label', has_text='Pitcher Pat')
        expect(out).to_be_visible()
        out.click()
        coach.locator('#saveGameAvailabilityBtn').click()
        expect(coach.locator('#classicPrepareGame')).to_be_visible(timeout=15_000)

        # Shown everywhere it still is, never hidden.
        expect(coach.locator('#classicAvailabilityCard')).to_contain_text('8 players present, 1 absent.')
        expect(coach.locator('#classicAbsentNames')).to_have_text('Out: Pitcher Pat')
        expect(coach.locator('#classicLineupCard li', has_text='Pitcher Pat')).to_contain_text('Out')
        expect(_spot(coach, 'P').locator('.player-tag')).to_have_text('Pitcher Pat (Out)')
        # Start is blocked with the server's reason, and the notice offers the fixes.
        expect(coach.locator(START)).to_be_disabled(timeout=15_000)
        expect(coach.locator('#start-live-blockers')).to_contain_text('Pitcher Pat is marked Out')
        notice = coach.locator('#gm-out-conflicts')
        expect(notice).to_be_visible(timeout=15_000)
        # Nothing moved on its own: the saved plan still has him.
        assert _innings(coach, classic_view_url, game_id)['1']['P'] == 'Pitcher Pat'

        notice.get_by_role('button', name='Mark Pitcher Pat Playing').click()
        expect(notice).to_have_count(0, timeout=15_000)
        expect(coach.locator(START)).to_be_enabled(timeout=15_000)
        assert coach.cb_errors == []
    finally:
        _delete(coach, classic_view_url, game_id)


# --- Switching views never loses work --------------------------------------------------

@pytest.mark.parametrize('spec', [DESKTOP, PHONE], ids=ids)
def test_switching_to_updated_with_unsaved_work(device, classic_view_url, spec):
    coach = device(spec)
    game_id = _game(coach, classic_view_url, f'Classic Unsaved {spec[0]}', {'1': NO_CF})
    try:
        _open(coach, classic_view_url, game_id)
        coach.evaluate('() => { window.__sameDocument = true; }')
        status = coach.locator('#cbViewSwitchStatus')

        # An availability change not yet saved stops the switch.
        coach.locator('#availabilityToggleBtn').click()
        box = coach.locator('#gameAvailabilityForm input[name="absent_players"]').first
        expect(box).to_be_visible()
        box.click()
        _choose(coach, 'updated')
        expect(status).to_contain_text("aren’t saved yet", timeout=10_000)
        assert coach.evaluate('() => window.__sameDocument === true')
        expect(box).to_be_checked()
        status.click()
        box.click()

        # A defense save that failed stops it too, and stays retryable.
        coach.route('**/save_rotation', lambda route: route.fulfill(
            status=500, json={'status': 'error', 'message': 'Simulated outage'}))
        _assign(coach, 'CF', 'Center Casey')
        pill = coach.locator('#classic-save-status')
        expect(pill).to_have_attribute('data-state', 'failed', timeout=15_000)
        _choose(coach, 'updated')
        expect(status).to_contain_text("defense plan didn’t save", timeout=20_000)
        assert coach.evaluate('() => window.__sameDocument === true')
        expect(_spot(coach, 'CF').locator('.player-tag')).to_have_text('Center Casey')
        status.click()

        # Retry from the save status: saved, then the switch goes ahead.
        coach.unroute('**/save_rotation')
        pill.click()
        _saved(coach)
        _choose(coach, 'updated')
        expect(coach.locator('body')).to_have_attribute('data-cb-view', 'updated', timeout=20_000)
        expect(coach.locator('#pregame-defense-editor-v3 [data-pde-pos="CF"] .pde-name')).to_have_text(
            'Center Casey', timeout=15_000)
        assert _innings(coach, classic_view_url, game_id)['1'] == FULL
    finally:
        _delete(coach, classic_view_url, game_id)


# --- Two coaches, two views, one game ----------------------------------------------------

def _pick_updated(page, position, name):
    page.locator(f'#pregame-defense-editor-v3 [data-pde-pos="{position}"]').click()
    modal = page.locator('#pde-player-modal')
    expect(modal).to_be_visible(timeout=10_000)
    modal.locator(f'.pde-choice[data-player="{name}"]').click()
    expect(modal).to_be_hidden(timeout=10_000)


def test_a_classic_and_an_updated_coach_edit_the_same_game(device, classic_view_url):
    classic = device(DESKTOP)
    updated = device(IPAD_PORTRAIT, who=ASSISTANT, view='updated')
    game_id = _game(classic, classic_view_url, 'Two Views One Game', {'1': NO_CF})
    try:
        _open(classic, classic_view_url, game_id)
        updated.goto(f'{classic_view_url}/game/{game_id}')
        expect(updated.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)

        # Classic's edit reaches the Updated coach.
        _assign(classic, 'CF', 'Center Casey')
        _saved(classic)
        expect(updated.locator('#pregame-defense-editor-v3 [data-pde-pos="CF"] .pde-name')).to_have_text(
            'Center Casey', timeout=20_000)

        # The Updated coach's edit reaches Classic.
        _pick_updated(updated, 'CF', 'Left Lee')
        updated.wait_for_function('() => !window.CBPregameRotation.hasUnsyncedLocalState()', timeout=15_000)
        expect(classic.locator('#pos-desktop-CF .player-tag')).to_have_text('Left Lee', timeout=20_000)
        # (Updated's tap field swaps two fielders.) Classic shows exactly what was saved.
        stored = _innings(classic, classic_view_url, game_id)['1']
        for position, name in stored.items():
            expect(classic.locator(f'#pos-desktop-{position} .player-tag')).to_have_text(name)

        # A refresh never overwrites an edit still saving here: hold Classic's
        # save while the Updated coach saves, then let it land.
        held = []
        classic.route('**/save_rotation', lambda route: held.append(route))
        classic.locator('#pos-desktop-CF').click()   # Left Lee to the bench
        expect(classic.locator('#pos-desktop-CF .player-tag')).to_have_count(0)
        classic.wait_for_function('() => window.CBPregameRotation.isSaveInFlightOrQueued()')
        _pick_updated(updated, 'RF', 'Second Sam')
        updated.wait_for_function('() => !window.CBPregameRotation.hasUnsyncedLocalState()', timeout=15_000)
        classic.wait_for_timeout(1500)
        expect(classic.locator('#pos-desktop-CF .player-tag')).to_have_count(0)
        assert held
        for route in held:
            route.continue_()
        classic.unroute('**/save_rotation')
        _saved(classic)
        stored = _innings(classic, classic_view_url, game_id)['1']
        assert 'CF' not in stored
        # Both screens end on what was saved. (Between two coaches the newest
        # whole-plan save wins, in either view: /save_rotation replaces the plan.)
        for position, name in stored.items():
            expect(classic.locator(f'#pos-desktop-{position} .player-tag')).to_have_text(name)
            expect(updated.locator(f'#pregame-defense-editor-v3 [data-pde-pos="{position}"] .pde-name')).to_have_text(
                name, timeout=20_000)
        # One writer on the Classic page: the shared queue; Updated's tap field
        # (the other client of that queue) is not loaded there.
        assert classic.evaluate('() => Boolean(window.CBPregameRotation) && !window.CBPregameDefense')
        assert classic.cb_errors == [] and updated.cb_errors == []
    finally:
        _delete(classic, classic_view_url, game_id)


# --- Start Live Game ---------------------------------------------------------------------

def _wait_live(page, url, game_id):
    page.wait_for_function(
        f"async () => (await (await fetch('/api/live-game/{game_id}/state')).json()).game.is_live",
        timeout=15_000)


@pytest.mark.parametrize('spec', [DESKTOP, IPAD_PORTRAIT, PHONE], ids=ids)
def test_start_live_game_opens_the_updated_live_screens(device, classic_view_url, spec):
    coach = device(spec)
    game_id = _game(coach, classic_view_url, f'Classic Start {spec[0]}', {'1': FULL},
                    lineup=list(FULL.values()))
    try:
        _open(coach, classic_view_url, game_id)
        sent = []
        coach.on('request', lambda request: sent.append(request.post_data_json)
                 if request.url.endswith(f'/api/live-game/{game_id}/start') else None)
        expect(coach.locator(START)).to_be_enabled(timeout=15_000)
        coach.locator(START).click()
        # A starting-pitcher question, if the rules ask one, is answered as shown.
        sheet = coach.locator(SHEET)
        try:
            expect(sheet).to_be_visible(timeout=3_000)
            sheet.locator('.modal-footer .btn-primary').click()
        except AssertionError:
            pass
        _wait_live(coach, classic_view_url, game_id)
        # The same Start as Updated: the reviewed 1st inning went with it.
        assert sent and sent[-1]['inning_one'] == FULL
        expect(coach.locator('body')).to_have_attribute('data-cb-view', 'updated', timeout=20_000)
        expect(coach.locator('body')).to_have_attribute('data-cb-view-choice', 'classic')
        expect(coach.locator('#classicPrepareGame')).to_have_count(0)
    finally:
        _delete(coach, classic_view_url, game_id)


def test_start_asks_the_same_questions_as_updated(device, classic_view_url):
    coach = device(DESKTOP)
    game_id = _game(coach, classic_view_url, 'Classic Start Questions', {'1': NO_CF})
    try:
        _open(coach, classic_view_url, game_id)
        # An open position is the coach's call: Start asks, and Fix shows the 1st inning.
        _inning(coach, 3)
        expect(coach.locator(START)).to_be_enabled(timeout=15_000)
        coach.locator(START).click()
        sheet = coach.locator(SHEET)
        expect(sheet).to_be_visible(timeout=10_000)
        expect(sheet).to_contain_text('CF')
        sheet.get_by_role('button', name='Fix 1st Inning Defense').click()
        expect(coach.locator('#inning-btn-group input[value="1"]')).to_be_checked(timeout=10_000)
        assert not _data(coach, classic_view_url, game_id)['game']['is_live']

        # A starter who appears ineligible: Choose Another Pitcher points out
        # the P spot (on Classic's diamond a tap would remove him, so it is
        # never tapped for the coach).
        _assign(coach, 'CF', 'Center Casey')
        _saved(coach)
        coach.route('**/api/live-game/*/start', lambda route: route.fulfill(status=409, json={
            'status': 'error', 'code': 'pitcher_rule_conflict', 'eligibility': 'rule_conflict',
            'required_decision': 'rule_override', 'pitcher': 'Pitcher Pat', 'ready': True,
            'eligibility_heading': 'Pitcher Pat appears ineligible to pitch',
            'eligibility_message': 'USSSA: Resting. Needs 1 day of rest.', 'message': 'USSSA: Resting.',
            'override_confirm': 'CoachBoard believes this may violate the selected USSSA rules.',
            'hard_stops': [], 'missing': [], 'open_positions': [], 'open_question': None}))
        coach.locator(START).click()
        expect(sheet).to_contain_text('appears ineligible', timeout=10_000)
        sheet.get_by_role('button', name='Choose Another Pitcher').click()
        expect(coach.locator('#pos-desktop-P')).to_have_class(re.compile('cb-start-attention'), timeout=10_000)
        expect(coach.locator('#pos-desktop-P .player-tag')).to_have_text('Pitcher Pat')
        assert not _data(coach, classic_view_url, game_id)['game']['is_live']
        assert coach.cb_errors == []
    finally:
        _delete(coach, classic_view_url, game_id)


def test_a_game_started_by_another_coach_hands_over_to_the_live_screens(device, classic_view_url):
    coach = device(IPAD_LANDSCAPE)
    game_id = _game(coach, classic_view_url, 'Started Elsewhere', {'1': FULL}, lineup=list(FULL.values()))
    try:
        _open(coach, classic_view_url, game_id)
        other = device(DESKTOP, who=ASSISTANT, view='updated')
        response = other.request.post(f'{classic_view_url}/api/live-game/{game_id}/start',
                                      data=json.dumps(start_body(other.request, classic_view_url, game_id)),
                                      headers={'Content-Type': 'application/json'})
        if response.status == 409:
            body = response.json()
            response = other.request.post(f'{classic_view_url}/api/live-game/{game_id}/start', data=json.dumps(
                start_body(other.request, classic_view_url, game_id,
                           pitching_decision=body.get('required_decision'),
                           pitching_decision_status=body.get('pitching_status', ''),
                           pitching_decision_rule_set=body.get('decision_rule_set', ''),
                           pitching_decision_reason=body.get('decision_reason', ''))),
                headers={'Content-Type': 'application/json'})
        assert response.ok, response.text()
        expect(coach.locator('body')).to_have_attribute('data-cb-view', 'updated', timeout=20_000)
        expect(coach.locator('#classicPrepareGame')).to_have_count(0)
    finally:
        _delete(coach, classic_view_url, game_id)
