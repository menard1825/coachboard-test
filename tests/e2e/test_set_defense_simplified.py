"""Set Defense and Plan Options use two ideas, not five overlapping buttons.

* Game Plan  -- the full multi-inning defensive plan for a game.
* Saved Defense -- a reusable defense for one inning.

Copying the inning shown is one action placed after the field, "Copy this
defense...", offered only once the inning has a defense. A Saved Defense is
chosen and then used for "This inning" or the "Whole game". Plan Options holds
only inning structure and Game Plan actions.
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
COPY = '#gmCopyDefenseBtn'


# --- setup ------------------------------------------------------------------------------

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
    """A future game planned with Inning 1 = A and Inning 3 = B; 2, 4-6 empty."""
    setup = make_page(DESKTOP)
    response = setup.request.post(f'{coachboard_url}/game-day/add', form={
        'game_date': (date.today() + timedelta(days=14)).isoformat(), 'game_start_time': '15:00',
        'game_opponent': f'Set Defense {uuid.uuid4().hex[:5]}', 'game_location': 'Plan Field',
        'pitching_rule_set': 'USSSA'}, max_redirects=0)
    game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
    innings = {str(i): {} for i in range(1, 7)}
    innings['1'], innings['3'] = dict(DEFENSE_A), dict(DEFENSE_B)
    saved = setup.request.post(f'{coachboard_url}/save_rotation', data={
        'title': 'Rotation', 'innings': innings, 'associated_game_id': game_id})
    assert saved.ok and saved.json().get('status') == 'success', saved.text()
    yield game_id
    setup.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})


def _innings(page, base_url, game_id):
    rotation = page.request.get(f'{base_url}/api/game_data/{game_id}').json()['rotation']
    innings = rotation['innings']
    return json.loads(innings) if isinstance(innings, str) else innings


def _filled(defense):
    return {pos: name for pos, name in (defense or {}).items() if name}


def _open_game(page, base_url, game_id):
    page.goto(f'{base_url}/game/{game_id}')
    expect(page.locator(PANEL)).to_be_visible(timeout=20_000)
    page.wait_for_timeout(600)


def _choose_inning(page, inning):
    page.locator('#inning-btn-group label').filter(has_text=re.compile(rf'^\s*{inning}\s*$')).first.click()
    expect(page.locator(f'{PANEL} .pde-title')).to_contain_text(f'Inning {inning}')
    page.wait_for_timeout(300)


def _saved(page):
    expect(page.locator(f'{PANEL} #pde-save-status')).to_contain_text('Saved', timeout=10_000)


def _copy(page, choice):
    page.locator(COPY).click()
    page.get_by_role('button', name=choice, exact=True).click()


# --- Copy this defense ------------------------------------------------------------------

@DEVICES
def test_copy_is_offered_only_after_the_field_for_an_inning_with_a_defense(make_page, coachboard_url, game, device):
    page = make_page(device)
    _open_game(page, coachboard_url, game)

    # The three old buttons are no longer on the card.
    for name in ('Apply to All Innings', 'Apply to Later Innings', 'Pick Innings'):
        expect(page.get_by_role('button', name=name, exact=True)).to_have_count(0)

    expect(page.locator(COPY)).to_be_visible()
    expect(page.locator(COPY)).to_have_text(re.compile(r'Copy this defense…'))
    field = page.locator(f'{PANEL} .pde-field').bounding_box()
    assert page.locator(COPY).bounding_box()['y'] > field['y'] + field['height'], 'Copy sits after the field'

    _choose_inning(page, 2)                                   # empty inning
    expect(page.locator(COPY)).to_be_hidden()
    _choose_inning(page, 1)
    expect(page.locator(COPY)).to_be_visible()
    assert page.cb_errors == []


@DEVICES
def test_copy_to_all_other_innings(make_page, coachboard_url, game, device):
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    _copy(page, 'All other innings')
    _saved(page)
    innings = _innings(page, coachboard_url, game)
    assert all(_filled(innings[str(i)]) == DEFENSE_A for i in range(1, 7)), innings


@DEVICES
def test_copy_to_later_innings_leaves_earlier_innings(make_page, coachboard_url, game, device):
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    _choose_inning(page, 3)
    _copy(page, 'Later innings')
    _saved(page)
    innings = _innings(page, coachboard_url, game)
    assert _filled(innings['1']) == DEFENSE_A and _filled(innings['2']) == {}
    assert all(_filled(innings[str(i)]) == DEFENSE_B for i in (3, 4, 5, 6)), innings


@DEVICES
def test_copy_to_chosen_innings(make_page, coachboard_url, game, device):
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    _copy(page, 'Choose innings…')
    sheet = page.locator('#gmPickInningsModal')
    expect(sheet).to_be_visible()
    expect(sheet.locator('.modal-title')).to_have_text(re.compile('Copy Inning 1'))
    sheet.locator('.gm-pick-inning-choice').filter(has_text=re.compile(r'\b5\b')).first.click()
    sheet.get_by_role('button', name=re.compile(r'^Copy')).click()
    _saved(page)
    innings = _innings(page, coachboard_url, game)
    assert _filled(innings['5']) == DEFENSE_A
    assert _filled(innings['2']) == {} and _filled(innings['3']) == DEFENSE_B


@DEVICES
def test_copy_can_be_undone(make_page, coachboard_url, game, device):
    """Copying overwrites at once and offers Undo, as before."""
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    _copy(page, 'All other innings')
    _saved(page)
    page.get_by_role('button', name='Undo').click()
    _saved(page)
    page.wait_for_timeout(500)
    innings = _innings(page, coachboard_url, game)
    assert _filled(innings['3']) == DEFENSE_B and _filled(innings['2']) == {}


# --- Saved Defense ------------------------------------------------------------------------

@pytest.fixture
def saved_defense(make_page, coachboard_url):
    page = make_page(DESKTOP)
    name = f'Everyday {uuid.uuid4().hex[:4]}'
    defense = {**DEFENSE_A, 'SS': 'Left Lee', 'LF': 'Shortstop Shawn'}
    response = page.request.post(f'{coachboard_url}/api/starting-defense-template/save',
                                 data={'title': name, 'innings': {'1': defense}})
    assert response.ok, response.text()
    yield name, defense


def _use(page, scope):
    """Use -> This inning / Whole game."""
    page.locator('#pde-use').click()
    item = page.locator('#pde-use-inning' if scope == 'This inning' else '#pde-use-game')
    expect(item).to_be_visible()
    expect(item).to_have_text(scope)
    item.click()


def _saved_defense_tools(page):
    toggle = page.locator(f'{PANEL} .gm-mobile-preset-toggle')
    if toggle.is_visible():
        expect(toggle).to_have_text(re.compile('Use a saved defense'))
        toggle.click()
    tools = page.locator(f'{PANEL} .pde-tools')
    expect(tools).to_be_visible()
    return tools


@DEVICES
def test_saved_defense_for_this_inning(make_page, coachboard_url, game, saved_defense, device):
    name, defense = saved_defense
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    _choose_inning(page, 2)
    tools = _saved_defense_tools(page)
    expect(tools).to_contain_text('Use a saved defense')
    # One obvious action: the scope choices wait behind Use.
    expect(page.locator('#pde-use')).to_be_disabled()
    for scope in ('This inning', 'Whole game'):
        expect(tools.get_by_role('button', name=scope, exact=True)).to_be_hidden()
    expect(tools.get_by_role('button', name='Save this defense', exact=True)).to_be_visible()
    tools.locator('#pde-preset').select_option(label=name)
    expect(page.locator('#pde-use')).to_be_enabled()
    page.once('dialog', lambda dialog: dialog.accept())
    _use(page, 'This inning')
    _saved(page)
    innings = _innings(page, coachboard_url, game)
    assert _filled(innings['2'])['SS'] == defense['SS']
    assert _filled(innings['1']) == DEFENSE_A and _filled(innings['4']) == {}


@DEVICES
def test_saved_defense_for_the_whole_game_asks_first(make_page, coachboard_url, game, saved_defense, device):
    name, defense = saved_defense
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    tools = _saved_defense_tools(page)
    tools.locator('#pde-preset').select_option(label=name)

    # Declining the overwrite leaves the plan exactly as it was.
    page.once('dialog', lambda dialog: dialog.dismiss())
    _use(page, 'Whole game')
    page.wait_for_timeout(600)
    assert _filled(_innings(page, coachboard_url, game)['3']) == DEFENSE_B

    page.once('dialog', lambda dialog: dialog.accept())
    _use(page, 'Whole game')
    _saved(page)
    innings = _innings(page, coachboard_url, game)
    for i in range(1, 7):
        assert _filled(innings[str(i)]).get('SS') == defense['SS'], (i, innings[str(i)])


@DEVICES
def test_save_this_defense_is_on_the_card_and_reloads(make_page, coachboard_url, game, device):
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    tools = _saved_defense_tools(page)
    tools.get_by_role('button', name='Save this defense', exact=True).click()
    modal = page.locator('#pde-preset-modal')
    expect(modal).to_be_visible()
    name = f'Saved {uuid.uuid4().hex[:4]}'
    modal.locator('#pde-name').fill(name)
    modal.locator('#pde-confirm').click()
    expect(modal).to_be_hidden(timeout=10_000)

    _open_game(page, coachboard_url, game)
    tools = _saved_defense_tools(page)
    expect(tools.locator('#pde-preset option').filter(has_text=name)).to_have_count(1)


# --- Plan Options -------------------------------------------------------------------------

def _plan_options(page):
    page.get_by_role('button', name='Plan Options').click()
    menu = page.locator('.gm-plan-options-menu.show')
    expect(menu).to_be_visible()
    return menu


def _menu_entries(menu):
    return menu.evaluate("""m => [...m.children].filter(li => li.getClientRects().length && getComputedStyle(li).display !== 'none')
      .map(li => { const s = li.querySelector('select'); if (s) return s.options[0].textContent.trim();
        const b = li.querySelector('.dropdown-item:not(.d-none), .dropdown-header'); return b ? b.textContent.trim().replace(/\\s+/g, ' ') : null; })
      .filter(Boolean)""")


@DEVICES
def test_plan_options_holds_innings_and_game_plan_only(make_page, coachboard_url, game, device):
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    entries = _menu_entries(_plan_options(page))
    expected = ['Innings', 'Add inning', 'Remove last inning', 'Plan mid-inning change…',
                'Game Plan', 'Load saved game plan…', 'Save game plan', 'Print', 'Delete game plan']
    assert entries == expected, entries
    # This game's plan autosaves; the manual Save Rotation is gone.
    expect(page.locator('#saveRotationBtn')).to_have_count(0)
    delete = page.locator('#deleteRotationBtn')
    assert 'text-danger' in delete.get_attribute('class')


@DEVICES
def test_plan_options_actions_still_work(make_page, coachboard_url, game, device):
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    chips = page.locator('#inning-btn-group input[name="inning-radio"]')
    count = chips.count()

    _plan_options(page).locator('#gmPlanAddInning').click()
    expect(chips).to_have_count(count + 1, timeout=10_000)
    _saved(page)
    _plan_options(page).locator('#gmPlanRemoveLastInning').click()
    expect(chips).to_have_count(count, timeout=10_000)
    _saved(page)

    _plan_options(page).get_by_role('link', name='Save game plan').click()
    modal = page.locator('#saveRotationTemplateModal')
    expect(modal).to_be_visible()
    expect(modal.locator('.modal-title')).to_have_text('Save game plan')
    modal.get_by_role('button', name='Cancel').click()
    expect(modal).to_be_hidden()

    menu = _plan_options(page)
    menu.locator('#gmPlanMidInningChange').click()
    expect(page.locator('.gm-coach-sheet.show, .modal.show').first).to_be_visible()
    assert page.cb_errors == []


@DEVICES
def test_game_plan_edits_still_autosave(make_page, coachboard_url, game, device):
    page = make_page(device)
    _open_game(page, coachboard_url, game)
    _choose_inning(page, 2)
    page.locator(f'{PANEL} [data-pde-pos="SS"]').click()
    chooser = page.locator('#pde-player-modal')
    expect(chooser).to_be_visible()
    chooser.locator('.pde-choice[data-player="Shortstop Shawn"]').click()
    expect(chooser).to_be_hidden()
    _saved(page)
    assert _filled(_innings(page, coachboard_url, game)['2']) == {'SS': 'Shortstop Shawn'}


def test_save_game_plan_creates_a_reusable_named_plan(make_page, coachboard_url, game):
    page = make_page(DESKTOP)
    _open_game(page, coachboard_url, game)
    name = f'Plan {uuid.uuid4().hex[:4]}'
    _plan_options(page).get_by_role('link', name='Save game plan').click()
    page.locator('#rotationTemplateName').fill(name)
    page.once('dialog', lambda dialog: dialog.accept())
    with page.expect_request(lambda r: r.url.endswith('/save_rotation_as_template')) as plan_save:
        page.locator('#confirmSaveTemplateBtn').click()
    assert plan_save.value.post_data_json['title'] == name
    assert 'associated_game_id' not in plan_save.value.post_data_json

    # It is a reusable Game Plan: another visit offers it under Load.
    _open_game(page, coachboard_url, game)
    options = page.locator('#rotationTemplateSelect option').filter(has_text=name)
    expect(options).to_have_count(1)
