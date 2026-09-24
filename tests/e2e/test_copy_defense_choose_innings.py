"""Copy this defense... > Choose innings copies to several innings at once.

(And every Copy this defense... choice protects innings that already have a
defense -- see the All other innings / Later innings tests at the end.)

From Inning 1 a coach can tick 2, 4, 5 and 7 and copy the defense to all four
in one action. Every other inning is offered, never the one being copied;
each choice stays visibly ticked while the others are chosen; Copy Defense
waits for at least one. Innings that already have a different defense are
named in a confirmation first, and cancelling it changes nothing.
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

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
DEVICES = pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])

DEFENSE_A = {'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam',
             '3B': 'Third Theo', 'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey',
             'RF': 'Right Riley'}
DEFENSE_B = {**DEFENSE_A, 'SS': 'Second Sam', '2B': 'Shortstop Shawn', 'LF': 'Right Riley', 'RF': 'Left Lee'}
PANEL = '#pregame-defense-editor-v3'
SHEET = '#gmPickInningsModal'
CONFIRM = '#gmCoachConfirmModal'
INNINGS = 7


def _login(page, base_url):
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')


@pytest.fixture
def make_page(browser, coachboard_url):
    contexts = []

    def _make(device):
        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        _login(page, coachboard_url)
        return page

    yield _make
    for context in contexts:
        context.close()


@pytest.fixture
def game(make_page, coachboard_url):
    """A future game with 7 innings: Inning 1 = A, Inning 3 = B, the rest empty."""
    setup = make_page(DESKTOP)
    response = setup.request.post(f'{coachboard_url}/game-day/add', form={
        'game_date': (date.today() + timedelta(days=15)).isoformat(), 'game_start_time': '15:00',
        'game_opponent': f'Choose Innings {uuid.uuid4().hex[:5]}', 'game_location': 'Plan Field',
        'pitching_rule_set': 'USSSA'}, max_redirects=0)
    game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
    innings = {str(i): {} for i in range(1, INNINGS + 1)}
    innings['1'], innings['3'] = dict(DEFENSE_A), dict(DEFENSE_B)
    saved = setup.request.post(f'{coachboard_url}/save_rotation', data={
        'title': 'Rotation', 'innings': innings, 'associated_game_id': game_id})
    assert saved.ok and saved.json().get('status') == 'success', saved.text()
    yield game_id
    setup.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})


def _innings(page, base_url, game_id):
    innings = page.request.get(f'{base_url}/api/game_data/{game_id}').json()['rotation']['innings']
    innings = json.loads(innings) if isinstance(innings, str) else innings
    return {key: {pos: name for pos, name in (value or {}).items() if name} for key, value in innings.items()}


def _open_sheet(page, base_url, game_id):
    page.goto(f'{base_url}/game/{game_id}')
    expect(page.locator(PANEL)).to_be_visible(timeout=20_000)
    page.wait_for_timeout(600)
    page.locator('#gmCopyDefenseBtn').click()
    page.locator('#gmChooseDefenseInningsBtn').click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible()
    return sheet


def _choice(sheet, inning):
    return sheet.locator(f'[data-gm-pick-inning="{inning}"]')


def _selected(sheet):
    return sheet.locator('[data-gm-pick-inning]').evaluate_all(
        "els => els.filter(el => el.getAttribute('aria-checked') === 'true').map(el => el.dataset.gmPickInning)")


def _copy(sheet):
    sheet.locator('[data-gm-pick-apply]').click()


def _saved(page):
    expect(page.locator(f'{PANEL} #pde-save-status')).to_contain_text('Saved', timeout=10_000)


def _expect_innings(page, base_url, game_id, expected):
    # Autosave is asynchronous; poll the server until it has the copy.
    for _ in range(40):
        innings = _innings(page, base_url, game_id)
        if all(innings[key] == value for key, value in expected.items()):
            return innings
        page.wait_for_timeout(250)
    assert {key: innings[key] for key in expected} == expected


# --- tests ---------------------------------------------------------------------------------

@DEVICES
def test_offers_every_other_inning_and_waits_for_a_choice(make_page, coachboard_url, game, device):
    page = make_page(device)
    sheet = _open_sheet(page, coachboard_url, game)

    offered = sheet.locator('[data-gm-pick-inning]').evaluate_all('els => els.map(el => el.dataset.gmPickInning)')
    assert offered == [str(i) for i in range(2, INNINGS + 1)]       # never Inning 1 itself
    # The choices are checkboxes, one per inning, and the only action is Copy Defense.
    assert sheet.locator('[role="checkbox"][data-gm-pick-inning]').count() == INNINGS - 1
    apply = sheet.locator('[data-gm-pick-apply]')
    expect(apply).to_have_text('Copy Defense')
    expect(apply).to_be_disabled()

    _choice(sheet, 2).click()
    expect(apply).to_be_enabled()
    _choice(sheet, 2).click()
    expect(apply).to_be_disabled()
    assert page.cb_errors == []


@DEVICES
def test_copies_to_one_chosen_inning(make_page, coachboard_url, game, device):
    page = make_page(device)
    sheet = _open_sheet(page, coachboard_url, game)
    _choice(sheet, 2).click()
    _copy(sheet)
    expect(sheet).to_be_hidden()
    _saved(page)
    innings = _expect_innings(page, coachboard_url, game, {'2': DEFENSE_A})
    assert innings['3'] == DEFENSE_B and all(innings[str(i)] == {} for i in (4, 5, 6, 7))
    assert page.cb_errors == []


@DEVICES
def test_copies_to_several_nonconsecutive_innings_in_one_action(make_page, coachboard_url, game, device):
    page = make_page(device)
    sheet = _open_sheet(page, coachboard_url, game)
    for inning in (2, 4, 5, 7):
        _choice(sheet, inning).click()
    # Every choice stays ticked, visibly, while the others are chosen.
    assert _selected(sheet) == ['2', '4', '5', '7']
    ticked = _choice(sheet, 4).evaluate('el => getComputedStyle(el).backgroundColor')
    unticked = _choice(sheet, 6).evaluate('el => getComputedStyle(el).backgroundColor')
    assert ticked != unticked
    expect(_choice(sheet, 4).locator('.gm-pick-check')).to_be_visible()
    expect(_choice(sheet, 6).locator('.gm-pick-check')).to_be_hidden()

    _copy(sheet)
    expect(sheet).to_be_hidden()
    _saved(page)
    innings = _expect_innings(page, coachboard_url, game,
                              {'2': DEFENSE_A, '4': DEFENSE_A, '5': DEFENSE_A, '7': DEFENSE_A})
    # Innings nobody chose are untouched.
    assert innings['1'] == DEFENSE_A and innings['3'] == DEFENSE_B and innings['6'] == {}
    assert page.cb_errors == []


@DEVICES
def test_choices_toggle_off_before_copying(make_page, coachboard_url, game, device):
    page = make_page(device)
    sheet = _open_sheet(page, coachboard_url, game)
    for inning in (2, 4, 5):
        _choice(sheet, inning).click()
    _choice(sheet, 4).click()                                   # changed my mind
    assert _selected(sheet) == ['2', '5']
    # Tapped off, it looks like any unchosen inning -- even while it has focus.
    look = 'el => [getComputedStyle(el).backgroundColor, getComputedStyle(el).color]'
    assert _choice(sheet, 4).evaluate(look) == _choice(sheet, 6).evaluate(look)
    assert _choice(sheet, 5).evaluate(look) != _choice(sheet, 6).evaluate(look)
    expect(_choice(sheet, 4).locator('.gm-pick-check')).to_be_hidden()
    _copy(sheet)
    _saved(page)
    innings = _expect_innings(page, coachboard_url, game, {'2': DEFENSE_A, '5': DEFENSE_A})
    assert innings['4'] == {}
    assert page.cb_errors == []


@DEVICES
def test_innings_with_a_defense_are_confirmed_before_replacing(make_page, coachboard_url, game, device):
    page = make_page(device)
    sheet = _open_sheet(page, coachboard_url, game)
    _choice(sheet, 3).click()                                   # already has Defense B
    _choice(sheet, 4).click()
    _copy(sheet)

    confirm = page.locator(CONFIRM)
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text('Inning 3')
    # Cancelling copies nothing at all -- not even to the empty Inning 4.
    confirm.get_by_role('button', name='Cancel').click()
    expect(confirm).to_be_hidden()
    page.wait_for_timeout(800)
    innings = _innings(page, coachboard_url, game)
    assert innings['3'] == DEFENSE_B and innings['4'] == {}

    sheet = _open_sheet(page, coachboard_url, game)
    _choice(sheet, 3).click()
    _choice(sheet, 4).click()
    _copy(sheet)
    confirm.locator('[data-gm-confirm-action]').click()
    _saved(page)
    _expect_innings(page, coachboard_url, game, {'3': DEFENSE_A, '4': DEFENSE_A})
    assert page.cb_errors == []


# --- every copy choice protects existing defenses -----------------------------------------

def _open_game(page, base_url, game_id):
    page.goto(f'{base_url}/game/{game_id}')
    expect(page.locator(PANEL)).to_be_visible(timeout=20_000)
    page.wait_for_timeout(600)


def _copy_menu(page, choice):
    page.locator('#gmCopyDefenseBtn').click()
    page.get_by_role('button', name=choice, exact=True).click()


EMPTY_EXCEPT_3 = {str(i): {} for i in range(2, INNINGS + 1) if i != 3}


@DEVICES
@pytest.mark.parametrize('choice', ['All other innings', 'Later innings'])
def test_copy_menu_confirms_before_replacing_and_cancel_changes_nothing(
        make_page, coachboard_url, game, device, choice):
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    _copy_menu(page, choice)                                    # from Inning 1: 2-7, and 3 has Defense B

    confirm = page.locator(CONFIRM)
    expect(confirm).to_be_visible()
    expect(confirm.locator('.modal-title')).to_have_text('Replace the defense in Inning 3?')
    confirm.get_by_role('button', name='Cancel').click()
    expect(confirm).to_be_hidden()
    page.wait_for_timeout(800)
    innings = _innings(page, coachboard_url, game)
    assert innings['3'] == DEFENSE_B and all(innings[key] == {} for key in EMPTY_EXCEPT_3), innings

    # Replace copies to the whole scope, the empty innings included, and Undo still works.
    _copy_menu(page, choice)
    expect(confirm).to_be_visible()
    confirm.locator('[data-gm-confirm-action]').click()
    _saved(page)
    _expect_innings(page, coachboard_url, game, {str(i): DEFENSE_A for i in range(1, INNINGS + 1)})

    page.get_by_role('button', name='Undo').click()
    _saved(page)
    _expect_innings(page, coachboard_url, game, {'3': DEFENSE_B, **EMPTY_EXCEPT_3})
    assert page.cb_errors == []


@DEVICES
def test_later_innings_that_are_empty_copy_at_once(make_page, coachboard_url, game, device):
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    page.locator('#inning-btn-group label').filter(has_text=re.compile(r'^\s*3\s*$')).first.click()
    expect(page.locator(f'{PANEL} .pde-title')).to_contain_text('Inning 3')
    page.wait_for_timeout(300)

    _copy_menu(page, 'Later innings')                           # 4-7 are all empty
    _saved(page)
    expect(page.locator(CONFIRM)).to_be_hidden()
    innings = _expect_innings(page, coachboard_url, game, {str(i): DEFENSE_B for i in range(4, INNINGS + 1)})
    assert innings['1'] == DEFENSE_A and innings['2'] == {}
    assert page.cb_errors == []
