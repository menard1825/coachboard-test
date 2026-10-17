"""Classic Games list: the original Home "Games" tab for a Classic coach.

Runs against the server that offers the Classic view to every coach
(classic_view_url), on a desktop, iPad Pro portrait and landscape, and a
phone. A Classic coach's Games link opens the original list (Add New Game,
Game Schedule with Lineup / Rotation and Manage), showing every game of the
team -- the same records Game Day shows. Manage opens Classic Prepare Game
and Back to All Games returns; a live game opens the Updated live screens.
An Updated coach's navigation is unchanged: #games still goes to Game Day.
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
from e2e_cleanup import release_game  # noqa: E402
from plan_helpers import with_stored_base  # noqa: E402
from start_helpers import start_body  # noqa: E402


COACH = ('playwright-coach', 'playwright-password')

DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
IPAD_PORTRAIT = ('ipad-pro-portrait', {'width': 1032, 'height': 1376}, {'is_mobile': True, 'has_touch': True})
IPAD_LANDSCAPE = ('ipad-pro-landscape', {'width': 1376, 'height': 1032}, {'is_mobile': True, 'has_touch': True})
PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
ALL_DEVICES = [DESKTOP, IPAD_PORTRAIT, IPAD_LANDSCAPE, PHONE]

FULL = {'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam',
        '3B': 'Third Theo', 'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey',
        'RF': 'Right Riley'}

LIST = '#games-list-container'


def ids(spec):
    return spec[0]


@pytest.fixture
def coach(browser, classic_view_url):
    """`coach(spec, view='classic')`: the head coach, signed in on that view;
    put back on Updated afterwards. Games made with `page.cb_game(...)` are
    ended (if live) and deleted afterwards."""
    contexts = []
    games = []

    def make(spec, view='classic'):
        cdn_assets.require_vendored_assets()
        _, viewport, extra = spec
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        page.cb_errors = []
        page.on('pageerror', lambda error: page.cb_errors.append(str(error)))
        page.goto(f'{classic_view_url}/login')
        page.get_by_label('Username or email').fill(COACH[0])
        page.locator('#password').fill(COACH[1])
        page.get_by_role('button', name='Sign In').click()
        expect(page).to_have_url(re.compile(rf'^{re.escape(classic_view_url)}/?(?:#\w+)?$'))
        _set_view(page, classic_view_url, view)
        page.reload()   # signed in on `/`; show it in the chosen view

        def game(opponent, days=9, plan=None, live=False, start='15:00'):
            game_id = _add_game(page, classic_view_url, opponent, days, start)
            games.append((page, game_id))
            if plan or live:
                _save_plan(page, classic_view_url, game_id, plan or {'1': FULL})
            if live:
                _start(page, classic_view_url, game_id)
            return game_id

        page.cb_game = game
        return page

    yield make
    for page, game_id in games:
        release_game(page.request, classic_view_url, game_id)
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


def _add_game(page, url, opponent, days, start):
    response = page.request.post(f'{url}/game-day/add', form={
        'game_date': (date.today() + timedelta(days=days)).isoformat(), 'game_start_time': start,
        'game_opponent': opponent, 'game_location': 'Classic Field', 'pitching_rule_set': 'USSSA'},
        max_redirects=0)
    return int(re.search(r'/game/(\d+)', response.headers['location']).group(1))


def _save_plan(page, url, game_id, innings):
    saved = page.request.post(f'{url}/save_rotation', data=json.dumps(with_stored_base(page.request, url, {
        'title': 'Rotation', 'innings': innings, 'associated_game_id': game_id})),
        headers={'Content-Type': 'application/json'})
    assert saved.ok, saved.text()


def _start(page, url, game_id):
    body = start_body(page.request, url, game_id)
    for _ in range(3):
        response = page.request.post(f'{url}/api/live-game/{game_id}/start', data=json.dumps(body),
                                     headers={'Content-Type': 'application/json'})
        if response.ok:
            return
        question = response.json()
        body.update(pitching_decision=question.get('required_decision'),
                    pitching_decision_status=question.get('pitching_status', ''),
                    pitching_decision_rule_set=question.get('decision_rule_set', ''),
                    pitching_decision_reason=question.get('decision_reason', ''))
    raise AssertionError(response.text())


def _games_link(page):
    """The primary navigation's Games link on this screen size."""
    if page.viewport_size['width'] >= 992:
        return page.locator('.coach-primary-nav [data-cb-section="games"]')
    return page.locator('#cb-global-mobile-nav a', has_text='Games')


def _open_games(page, url):
    page.goto(f'{url}/#overview')
    link = _games_link(page)
    expect(link).to_be_visible(timeout=15_000)
    link.click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(url)}/#games$'))
    expect(page.locator('#games')).to_be_visible(timeout=15_000)
    expect(page.locator(f'{LIST} li').first).to_be_visible(timeout=15_000)


def _row(page, game_id):
    return page.locator(f'{LIST} [data-cb-game="{game_id}"]')


@pytest.mark.parametrize('spec', ALL_DEVICES, ids=ids)
def test_the_classic_games_list(coach, classic_view_url, spec):
    page = coach(spec)
    planned = page.cb_game(f'Classic List {spec[0]}', plan={'1': FULL})
    opened = page.cb_game(f'Opened Only {spec[0]}')
    page.request.get(f'{classic_view_url}/game/{opened}')        # an opened game has empty innings
    live = page.cb_game(f'Classic Live {spec[0]}', days=0, live=True, start='18:00')

    _open_games(page, classic_view_url)
    expect(page.locator('#games .card-header', has_text='Add New Game')).to_be_visible()
    expect(page.locator('#games .card-header', has_text='Game Schedule')).to_be_visible()

    # Every game of the team, and nothing else.
    team_games = {game['id'] for game in page.request.get(f'{classic_view_url}/api/games').json()}
    listed = {int(value) for value in page.locator(f'{LIST} [data-cb-game]').evaluate_all(
        'rows => rows.map(row => row.dataset.cbGame)')}
    assert listed == team_games

    row = _row(page, planned)
    expect(row).to_contain_text(f'vs Classic List {spec[0]}')
    expect(row).to_contain_text('3:00 PM')
    expect(row).to_contain_text('Rotation: Set')
    expect(row.locator('[data-cb-game-open]')).to_have_text(re.compile('Manage'))
    expect(row.locator('[data-cb-delete-game]')).to_have_count(1)
    # Opened but never planned: its empty innings are not a plan.
    expect(_row(page, opened)).to_contain_text('Rotation: Not Set')
    live_row = _row(page, live)
    expect(live_row.locator('[data-cb-game-live]')).to_have_text('LIVE')
    expect(live_row).to_contain_text('6:00 PM')
    expect(live_row.locator('[data-cb-game-open]')).to_have_text(re.compile('Open Live Game'))
    expect(live_row.locator('[data-cb-delete-game]')).to_have_count(0)

    width = spec[1]['width']
    measured = page.evaluate("""(vw) => ({
      scrollWidth: document.documentElement.scrollWidth,
      wide: [...document.querySelectorAll('#games .card, #games-list-container > li')]
        .filter(el => el.getClientRects().length && el.getBoundingClientRect().right > vw + 0.5).length,
    })""", width)
    assert measured['wide'] == 0 and measured['scrollWidth'] <= width, measured
    assert page.cb_errors == []


def test_the_same_games_as_game_day(coach, classic_view_url):
    page = coach(DESKTOP)
    page.cb_game('Same Records Today', days=0)
    page.cb_game('Same Records Later', days=20)
    game_day = page.request.get(f'{classic_view_url}/game-day').text()
    on_game_day = {int(game_id) for game_id in re.findall(r'/game/(\d+)', game_day)}
    assert on_game_day, 'Game Day should list games'

    _open_games(page, classic_view_url)
    listed = {int(value) for value in page.locator(f'{LIST} [data-cb-game]').evaluate_all(
        'rows => rows.map(row => row.dataset.cbGame)')}
    # Game Day shows a window of upcoming games; every game it shows is in
    # the Classic list, which lists them all.
    assert on_game_day <= listed, on_game_day - listed


@pytest.mark.parametrize('spec', [DESKTOP, IPAD_PORTRAIT, PHONE], ids=ids)
def test_manage_opens_classic_prepare_game_and_back_returns(coach, classic_view_url, spec):
    page = coach(spec)
    game_id = page.cb_game(f'Manage Me {spec[0]}', plan={'1': FULL})
    _open_games(page, classic_view_url)
    _row(page, game_id).locator('[data-cb-game-open]').click()
    expect(page).to_have_url(f'{classic_view_url}/game/{game_id}')
    expect(page.locator('#classicPrepareGame')).to_be_visible(timeout=15_000)
    page.locator('#classicBackToGames').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(classic_view_url)}/#games$'))
    expect(_row(page, game_id)).to_be_visible(timeout=15_000)
    assert page.cb_errors == []


@pytest.mark.parametrize('spec', [DESKTOP, IPAD_LANDSCAPE, PHONE], ids=ids)
def test_a_live_game_opens_the_updated_live_screens(coach, classic_view_url, spec):
    page = coach(spec)
    game_id = page.cb_game(f'Live From List {spec[0]}', days=0, live=True)
    _open_games(page, classic_view_url)
    _row(page, game_id).locator('[data-cb-game-open]').click()
    expect(page).to_have_url(f'{classic_view_url}/game/{game_id}')
    expect(page.locator('body')).to_have_attribute('data-cb-view', 'updated', timeout=15_000)
    expect(page.locator('body')).to_have_attribute('data-cb-view-choice', 'classic')
    expect(page.locator('#classicPrepareGame')).to_have_count(0)


@pytest.mark.parametrize('spec', [DESKTOP, PHONE], ids=ids)
def test_adding_a_game_from_the_list(coach, classic_view_url, spec):
    page = coach(spec)
    _open_games(page, classic_view_url)
    form = page.locator('#games form')
    form.locator('[name="game_date"]').fill((date.today() + timedelta(days=12)).isoformat())
    form.locator('[name="game_start_time"]').fill('16:30')
    opponent = f'Added In Classic {spec[0]}'
    form.locator('[name="game_opponent"]').fill(opponent)
    form.get_by_role('button', name='Add & Manage').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(classic_view_url)}/game/\d+'))
    game_id = int(re.search(r'/game/(\d+)', page.url).group(1))
    page.cb_errors.clear()
    try:
        expect(page.locator('#classicPrepareGame')).to_be_visible(timeout=15_000)
        expect(page.locator('#classicGameBar')).to_contain_text(opponent)
        page.locator('#classicBackToGames').click()
        expect(_row(page, game_id)).to_contain_text('4:30 PM', timeout=15_000)
    finally:
        release_game(page.request, classic_view_url, game_id)


@pytest.mark.parametrize('spec', [DESKTOP, PHONE], ids=ids)
def test_deleting_a_game_from_the_list(coach, classic_view_url, spec):
    page = coach(spec)
    game_id = page.cb_game(f'Delete Me {spec[0]}')
    _open_games(page, classic_view_url)
    _row(page, game_id).locator('[data-cb-delete-game]').click()
    modal = page.locator('#confirmDeleteModal')
    expect(modal).to_be_visible(timeout=10_000)
    expect(modal).to_contain_text(f'the game against Delete Me {spec[0]}')
    modal.locator('#confirmDeleteButton').click()
    expect(modal).to_be_hidden(timeout=10_000)
    expect(_row(page, game_id)).to_have_count(0)
    assert game_id not in {game['id'] for game in page.request.get(f'{classic_view_url}/api/games').json()}
    assert page.cb_errors == []


@pytest.mark.parametrize('spec', [DESKTOP, PHONE], ids=ids)
def test_updated_navigation_is_unchanged(coach, classic_view_url, spec):
    page = coach(spec, view='updated')
    page.goto(f'{classic_view_url}/#games')
    expect(page).to_have_url(f'{classic_view_url}/game-day', timeout=15_000)
    if spec is DESKTOP:
        link = page.locator('.coach-primary-nav [data-cb-section="game-day"]')
        expect(link).to_have_text(re.compile('Game Day'))
        expect(page.locator('.coach-primary-nav [data-cb-section="games"]')).to_have_count(0)
    else:
        link = page.locator('#cb-global-mobile-nav [data-cb-mobile-section="game-day"]')
        expect(link).to_have_text(re.compile('Game Day'))
    assert link.get_attribute('href').endswith('/game-day')

