"""Use Previous Game Setup, as a coach uses it on a phone and an iPad.

* The sheet shows what will be copied before anything changes.
* The pitcher is never copied; today's planned P stays.
* A player who is Out today or is today's pitcher is not placed.
* Today's existing defense is replaced only when the coach turns it on.
* The earlier game is never changed.
"""

import re
import uuid
from datetime import date, timedelta

import pytest

from test_set_defense_simplified import (  # noqa: F401 (make_page is a fixture)
    DEFENSE_A,
    PHONE,
    _filled,
    _innings,
    make_page,
)
from test_pregame_player_time_summary import mark_absent

from playwright.sync_api import expect  # noqa: E402


pytestmark = pytest.mark.e2e

IPAD = ('ipad', {'width': 820, 'height': 1180}, {'has_touch': True})
DEVICES = pytest.mark.parametrize('device', [PHONE, IPAD], ids=lambda d: d[0])
SHEET = '#previousSetupModal'
# Far enough out that no other test's game falls between these two.
SOURCE_DAYS, TODAY_DAYS = 500, 501


@pytest.fixture
def setup(make_page, coachboard_url):
    page = make_page(PHONE)
    games = []

    def add_game(days, innings):
        response = page.request.post(f'{coachboard_url}/game-day/add', form={
            'game_date': (date.today() + timedelta(days=days)).isoformat(), 'game_start_time': '15:00',
            'game_opponent': f'Prev Setup {uuid.uuid4().hex[:5]}', 'game_location': 'Field',
            'pitching_rule_set': 'USSSA'}, max_redirects=0)
        game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
        games.append(game_id)
        plan = {str(i): {} for i in range(1, 7)}
        plan.update(innings)
        saved = page.request.post(f'{coachboard_url}/save_rotation', data={
            'title': 'Rotation', 'innings': plan, 'associated_game_id': game_id})
        assert saved.ok and saved.json().get('status') == 'success', saved.text()
        return game_id

    def add_lineup(game_id, names):
        roster = {p['name']: p['id'] for p in page.request.get(f'{coachboard_url}/api/roster').json()}
        response = page.request.post(f'{coachboard_url}/add_lineup', data={
            'title': 'Last game lineup', 'lineup_player_ids': [roster[name] for name in names],
            'associated_game_id': game_id})
        assert response.ok, response.text()

    try:
        yield page, add_game, add_lineup
    finally:
        for game_id in games:
            page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})


def _open_sheet(page, base_url, game_id):
    page.goto(f'{base_url}/game/{game_id}')
    launch = page.locator('#previousSetupLaunch')
    expect(launch).to_be_visible(timeout=20_000)
    button = launch.get_by_role('button', name='Review & Copy')
    box = button.bounding_box()
    assert box and box['height'] >= 44, box
    button.click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('.cb-ps-choices')).to_be_visible(timeout=10_000)
    return sheet


def _no_sideways_scroll(page):
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')


@DEVICES
def test_copy_last_games_setup_without_its_pitcher(setup, make_page, coachboard_url, device):
    page, add_game, add_lineup = setup
    source_id = add_game(SOURCE_DAYS, {'1': dict(DEFENSE_A)})
    add_lineup(source_id, list(DEFENSE_A.values()))
    # Today Third Theo pitches; Left Lee is Out.
    today_id = add_game(TODAY_DAYS, {'1': {'P': 'Third Theo'}})
    mark_absent(page, coachboard_url, today_id, ['Left Lee'])
    source_before = page.request.get(f'{coachboard_url}/api/game_data/{source_id}').json()

    coach = make_page(device)

    sheet = _open_sheet(coach, coachboard_url, today_id)
    _no_sideways_scroll(coach)
    expect(sheet.locator('#previousSetupUse-lineup')).to_be_checked()
    expect(sheet.locator('#previousSetupUse-defense')).to_be_checked()
    field = sheet.locator('[data-ps-preview="defense"]')
    expect(field).to_contain_text('Third Theo')
    expect(field).to_contain_text('Stays')
    expect(field).to_contain_text('Open · Third Theo — Today\'s pitcher')
    expect(field).to_contain_text('Open · Left Lee — Out today')
    expect(field).to_contain_text("Last game's pitcher (Pitcher Pat) isn't copied.")
    expect(sheet.locator('[data-ps-preview="lineup"]')).to_contain_text('Not copied: Left Lee (Out today)')

    apply = sheet.locator('#previousSetupApplyBtn')
    expect(apply).to_have_text('Copy lineup & defense')
    assert apply.bounding_box()['height'] >= 44
    with coach.expect_navigation(timeout=20_000):
        apply.click()

    # The coach sees what was copied, once, and the card shows it was used.
    launch = coach.locator('#previousSetupLaunch')
    expect(coach.locator('#previousSetupResult')).to_have_text(
        re.compile(r'^Copied \d+ batters and 6 fielders from [A-Z][a-z]{2} \d+(, \d{4})?\.$'), timeout=20_000)
    expect(launch).to_have_attribute('data-state', 'copied')
    expect(launch.locator('.cb-psl-title')).to_contain_text('Copied from vs ')
    expect(launch).to_contain_text('Batting order: copied')
    expect(launch).to_contain_text('Starting defense: copied (6 fielders)')
    expect(launch.get_by_role('button', name='Review', exact=True)).to_be_visible()
    coach.reload()
    expect(launch).to_have_attribute('data-state', 'copied', timeout=20_000)
    expect(coach.locator('#previousSetupResult')).to_be_hidden()

    first = _filled(_innings(page, coachboard_url, today_id)['1'])
    expected = {pos: name for pos, name in DEFENSE_A.items() if pos not in {'P', '3B', 'LF'}}
    assert first == {**expected, 'P': 'Third Theo'}

    today = page.request.get(f'{coachboard_url}/api/game_data/{today_id}').json()
    names = today['lineup']['lineup_positions']
    assert 'Left Lee' not in names
    assert [name for name in names if name in DEFENSE_A.values()] == [
        name for name in DEFENSE_A.values() if name != 'Left Lee']

    source_after = page.request.get(f'{coachboard_url}/api/game_data/{source_id}').json()
    assert source_after['rotation']['innings'] == source_before['rotation']['innings']
    assert source_after['lineup'] == source_before['lineup']
    assert coach.cb_errors == []


def test_todays_defense_is_kept_unless_the_coach_replaces_it(setup, coachboard_url):
    page, add_game, add_lineup = setup
    source_id = add_game(SOURCE_DAYS, {'1': dict(DEFENSE_A)})
    add_lineup(source_id, list(DEFENSE_A.values()))
    today_plan = {'P': 'Pitcher Pat', 'C': 'First Frank', '1B': 'Catcher Cole'}
    today_id = add_game(TODAY_DAYS, {'1': dict(today_plan)})

    sheet = _open_sheet(page, coachboard_url, today_id)
    defense = sheet.locator('#previousSetupUse-defense')
    expect(defense).not_to_be_checked()
    expect(sheet).to_contain_text("Replace today's starting defense")
    expect(sheet).to_contain_text("Today's 1st-inning fielders (2) will be replaced.")
    expect(sheet.locator('[data-ps-preview="defense"]')).to_be_hidden()

    apply = sheet.locator('#previousSetupApplyBtn')
    expect(apply).to_have_text('Copy batting order')
    with page.expect_navigation(timeout=20_000):
        apply.click()

    assert _filled(_innings(page, coachboard_url, today_id)['1']) == today_plan
    lineup = page.request.get(f'{coachboard_url}/api/game_data/{today_id}').json()['lineup']
    assert lineup and 'Catcher Cole' in lineup['lineup_positions']

    # Turning it on is the explicit agreement to replace it.
    sheet = _open_sheet(page, coachboard_url, today_id)
    expect(sheet).to_contain_text("Replace today's batting order")
    sheet.locator('label[for="previousSetupUse-defense"]').click()
    expect(sheet.locator('[data-ps-preview="defense"]')).to_be_visible()
    apply = sheet.locator('#previousSetupApplyBtn')
    expect(apply).to_have_text('Copy starting defense')
    with page.expect_navigation(timeout=20_000):
        apply.click()

    first = _filled(_innings(page, coachboard_url, today_id)['1'])
    assert first['P'] == 'Pitcher Pat'
    assert first['C'] == 'Catcher Cole' and first['1B'] == 'First Frank'
    assert len(set(first.values())) == len(first)


def test_a_change_made_elsewhere_while_reviewing_copies_nothing(setup, coachboard_url):
    page, add_game, add_lineup = setup
    source_id = add_game(SOURCE_DAYS, {'1': dict(DEFENSE_A)})
    add_lineup(source_id, list(DEFENSE_A.values()))
    today_id = add_game(TODAY_DAYS, {'1': {}})

    sheet = _open_sheet(page, coachboard_url, today_id)
    expect(sheet.locator('#previousSetupUse-lineup')).to_be_checked()
    # Another coach saves a batting order for today while this sheet is open.
    add_lineup(today_id, ['Catcher Cole', 'First Frank'])

    apply = sheet.locator('#previousSetupApplyBtn')
    apply.click()
    expect(sheet.locator('#previousSetupFeedback')).to_contain_text("Today's setup changed while you were reviewing")
    expect(apply).to_have_text('Refresh')

    assert _filled(_innings(page, coachboard_url, today_id)['1']) == {}
    lineup = page.request.get(f'{coachboard_url}/api/game_data/{today_id}').json()['lineup']
    assert lineup['lineup_positions'] == ['Catcher Cole', 'First Frank']


# --- Copying both, when only one part saves ---------------------------------------

def _refuse(page, path, message):
    page.route(f'**{path}', lambda route: route.fulfill(
        status=500, content_type='application/json', body='{"status": "error", "message": "%s"}' % message))


def test_defense_saves_but_the_batting_order_fails(setup, coachboard_url):
    page, add_game, add_lineup = setup
    source_id = add_game(SOURCE_DAYS, {'1': dict(DEFENSE_A)})
    add_lineup(source_id, list(DEFENSE_A.values()))
    today_id = add_game(TODAY_DAYS, {'1': {}})

    sheet = _open_sheet(page, coachboard_url, today_id)
    _refuse(page, '/add_lineup', 'Lineup server error')
    sheet.locator('#previousSetupApplyBtn').click()

    result = sheet.locator('#previousSetupFeedback')
    expect(result).to_contain_text('Only part of the setup was copied.', timeout=15_000)
    expect(result.locator('[data-ps-result="saved"]')).to_have_text('Saved: Starting defense')
    expect(result.locator('[data-ps-result="failed"]')).to_have_text('Not saved: Batting order — Lineup server error')
    expect(result).not_to_contain_text('Copied.')
    expect(sheet.locator('#previousSetupApplyBtn')).to_have_text('Refresh')
    page.wait_for_timeout(1500)
    expect(sheet).to_be_visible()  # no automatic reload hides the result

    page.unroute('**/add_lineup')
    assert _filled(_innings(page, coachboard_url, today_id)['1']) == {
        pos: name for pos, name in DEFENSE_A.items() if pos != 'P'}
    assert page.request.get(f'{coachboard_url}/api/game_data/{today_id}').json()['lineup'] is None

    # Refresh: the card shows only what was copied, never "Copied" for both.
    with page.expect_navigation(timeout=20_000):
        sheet.locator('#previousSetupApplyBtn').click()
    launch = page.locator('#previousSetupLaunch')
    expect(launch).to_have_attribute('data-state', 'partial', timeout=20_000)
    expect(launch.locator('.cb-psl-title')).to_contain_text('Partly copied from vs ')
    expect(launch).to_contain_text('Starting defense: copied (8 fielders)')
    expect(launch).to_contain_text('Batting order: not copied')
    expect(page.locator('#previousSetupResult')).to_be_hidden()


def test_batting_order_saves_but_the_defense_fails(setup, coachboard_url):
    page, add_game, add_lineup = setup
    source_id = add_game(SOURCE_DAYS, {'1': dict(DEFENSE_A)})
    add_lineup(source_id, list(DEFENSE_A.values()))
    today_id = add_game(TODAY_DAYS, {'1': {}})

    sheet = _open_sheet(page, coachboard_url, today_id)
    _refuse(page, '/save_rotation', 'Defense server error')
    sheet.locator('#previousSetupApplyBtn').click()

    result = sheet.locator('#previousSetupFeedback')
    expect(result).to_contain_text('Only part of the setup was copied.', timeout=15_000)
    expect(result.locator('[data-ps-result="failed"]')).to_have_text('Not saved: Starting defense — Defense server error')
    expect(result.locator('[data-ps-result="saved"]')).to_have_text('Saved: Batting order')
    expect(sheet.locator('#previousSetupApplyBtn')).to_have_text('Refresh')

    page.unroute('**/save_rotation')
    assert _filled(_innings(page, coachboard_url, today_id)['1']) == {}
    lineup = page.request.get(f'{coachboard_url}/api/game_data/{today_id}').json()['lineup']
    assert lineup and 'Catcher Cole' in lineup['lineup_positions']

    # Refresh shows the truth: the batting order is saved, the defense is not.
    with page.expect_navigation(timeout=20_000):
        sheet.locator('#previousSetupApplyBtn').click()
    sheet = _open_sheet(page, coachboard_url, today_id)
    expect(sheet).to_contain_text("Replace today's batting order")
    expect(sheet.locator('#previousSetupUse-defense')).to_be_checked()


def test_nothing_saved_says_nothing_was_copied(setup, coachboard_url):
    page, add_game, add_lineup = setup
    source_id = add_game(SOURCE_DAYS, {'1': dict(DEFENSE_A)})
    add_lineup(source_id, list(DEFENSE_A.values()))
    today_id = add_game(TODAY_DAYS, {'1': {}})

    sheet = _open_sheet(page, coachboard_url, today_id)
    page.route('**/save_rotation', lambda route: route.abort())
    page.route('**/add_lineup', lambda route: route.abort())
    sheet.locator('#previousSetupApplyBtn').click()

    result = sheet.locator('#previousSetupFeedback')
    expect(result).to_contain_text('Nothing was copied.', timeout=15_000)
    expect(result.locator('[data-ps-result="saved"]')).to_have_count(0)
    expect(result.locator('[data-ps-result="failed"]')).to_have_count(2)
    expect(result).to_contain_text('Not saved: Batting order — No connection to CoachBoard.')
    page.unroute('**/save_rotation')
    page.unroute('**/add_lineup')
    assert _filled(_innings(page, coachboard_url, today_id)['1']) == {}
    assert page.request.get(f'{coachboard_url}/api/game_data/{today_id}').json()['lineup'] is None
