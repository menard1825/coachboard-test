"""Home answers "what's my next game, and what do I need to do for it?" once.

The Next Game card owns the game (opponent, date, place, status), its prep
checklist and its one action. Needs Attention used to repeat the lineup,
defense and competition-rules items -- each linking to the same Manage Game
page -- the card also had a Schedule button duplicating the Game Day quick
action, the header repeated the competition rules, and a live game showed a
Resume banner above a card already offering Resume Live Game.
"""

import os
import re
from datetime import datetime, timedelta

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
GAME_PREP_ROWS = ('Batting lineup', 'Defensive plan', 'Competition rules')


def game(game_id, opponent, days, *, live=False, location='Test Field'):
    when = (datetime.now() + timedelta(days=days)).replace(hour=18, minute=0, second=0, microsecond=0)
    return {'id': game_id, 'date': when.isoformat(sep=' '), 'start_time': '18:00',
            'opponent': opponent, 'location': location, 'is_live': live, 'game_notes': ''}


def readiness(*, lineup=False, defense=False, blockers=None, status=None):
    blockers = blockers if blockers is not None else [
        b for ok, b in ((lineup, 'Batting lineup is not set.'),
                        (defense, 'Choose the starting pitcher for Inning 1.')) if not ok]
    return {'status': status or ('READY' if not blockers else 'PREP'), 'has_end_game': False,
            'lineup_ready': lineup, 'lineup_count': 9 if lineup else 0,
            'defense_ready': defense, 'defense_completed_innings': 6 if defense else 0,
            'present_count': 9, 'absent_count': 0, 'blockers': blockers, 'pitching_alerts': []}


@pytest.fixture
def open_home(browser, coachboard_url):
    contexts = []

    def _open(device, games=(), ready=None, rules=None):
        """Home with the schedule, readiness and rules replaced by `games`."""
        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        page.cb_errors = []
        page.on('pageerror', lambda error: page.cb_errors.append(str(error)))
        games = list(games)
        page.route('**/api/overview_data', lambda route: route.fulfill(json={
            'next_game': games[0] if games else None, 'pitchers_on_rest': {}, 'recent_notes': []}))
        page.route('**/api/games', lambda route: route.fulfill(json=games))
        def reply(payload):
            return lambda route: route.fulfill(json=payload)

        for g in games:
            state = (ready or {}).get(g['id'], readiness())
            page.route(f'**/api/game-day/{g["id"]}/readiness', reply({'status': 'success', 'readiness': state}))
            chosen = (rules or {}).get(g['id'], {'effective': 'USSSA', 'source': 'game'})
            page.route(f'**/api/game-day/{g["id"]}/pitching-rules', reply({'status': 'success', **chosen}))
        page.goto(f'{coachboard_url}/login')
        page.get_by_label('Username or email').fill(TEST_USERNAME)
        page.locator('#password').fill(TEST_PASSWORD)
        page.get_by_role('button', name='Sign In').click()
        page.wait_for_load_state('load')
        dashboard = page.locator('.cb-home-dashboard')
        expect(dashboard).to_be_visible(timeout=20_000)
        return page, dashboard

    yield _open
    for context in contexts:
        context.close()


def visible_links(dashboard, href):
    return dashboard.locator(f'a[href="{href}"]').evaluate_all(
        'els => els.filter(e => e.getClientRects().length).map(e => e.innerText.trim().replace(/\\s+/g, " "))')


def attention_titles(dashboard):
    return dashboard.locator('.cb-home-attention-row strong').all_inner_texts()


def assert_single_owner(page, dashboard, g):
    expect(dashboard.locator('.cb-home-next-game')).to_have_count(1)
    card = dashboard.locator('.cb-home-next-game')
    expect(card).to_contain_text(f'vs {g["opponent"]}')
    # The game and its workflow appear once on Home.
    assert dashboard.inner_text().count(g['opponent']) == 1, dashboard.inner_text()
    assert len(visible_links(dashboard, f'/game/{g["id"]}')) == 1, visible_links(dashboard, f'/game/{g["id"]}')
    expect(card.locator('[aria-label="Game prep checklist"] .cb-home-status')).to_have_count(4)
    assert not set(attention_titles(dashboard)) & set(GAME_PREP_ROWS), attention_titles(dashboard)
    # Game Day is one shortcut, not also a card button.
    game_day = dashboard.locator('a[href="/game-day"]:visible')
    expect(game_day).to_have_count(1)
    expect(game_day).to_have_class(re.compile(r'\bcb-home-quick\b'))
    expect(dashboard.locator('.cb-home-context')).not_to_contain_text('rules')
    duplicate_ids = page.evaluate("""() => { const seen = new Map();
      document.querySelectorAll('[id]').forEach(el => seen.set(el.id, (seen.get(el.id) || 0) + 1));
      return [...seen].filter(([, n]) => n > 1).map(([id]) => id); }""")
    assert duplicate_ids == [], duplicate_ids
    assert page.cb_errors == []


@DEVICES
def test_nothing_prepared_is_one_card_with_one_checklist(open_home, device):
    g = game(501, 'Unprepared Owls', 3)
    page, dashboard = open_home(device, [g], rules={501: {'effective': '', 'source': 'unselected'}})
    assert_single_owner(page, dashboard, g)
    card = dashboard.locator('.cb-home-next-game')
    expect(card.locator('.cb-home-status.is-warning')).to_have_count(3)
    expect(card.locator('.cb-home-prep-note')).to_contain_text('2 preparation items remaining')
    expect(card.locator('.cb-home-prep-note')).to_contain_text('Batting lineup is not set.')
    expect(card.get_by_role('link', name='Manage Game')).to_be_visible()


def test_partly_prepared_game_shows_what_is_done_and_what_is_left(open_home):
    g = game(502, 'Halfway Hawks', 2)
    page, dashboard = open_home(DESKTOP, [g], ready={502: readiness(lineup=True)})
    assert_single_owner(page, dashboard, g)
    card = dashboard.locator('.cb-home-next-game')
    expect(card.locator('.cb-home-status.is-ready', has_text='Batting lineup')).to_contain_text('9 hitters ready')
    expect(card.locator('.cb-home-status.is-warning', has_text='Defense')).to_contain_text('Rotation is not complete')
    expect(card.locator('.cb-home-prep-note')).to_contain_text('1 preparation item remaining')
    expect(card.locator('.cb-home-prep-note')).to_contain_text('Choose the starting pitcher for Inning 1.')


@DEVICES
def test_fully_prepared_game_reads_as_complete(open_home, device):
    g = game(503, 'Ready Rays', 1)
    page, dashboard = open_home(device, [g], ready={503: readiness(lineup=True, defense=True)})
    assert_single_owner(page, dashboard, g)
    card = dashboard.locator('.cb-home-next-game')
    expect(card.locator('.badge')).to_have_text('READY')
    expect(card.locator('.cb-home-status.is-warning')).to_have_count(0)
    expect(card.locator('.cb-home-ready-note')).to_contain_text('Pregame setup complete.')
    expect(card.locator('.cb-home-prep-note')).to_have_count(0)


def test_game_today_and_several_future_games_pick_the_next_one(open_home):
    today = game(504, 'Tonight Tigers', 0)
    later = [game(505, 'Next Week Wolves', 7), game(506, 'Far Off Falcons', 20)]
    page, dashboard = open_home(DESKTOP, [later[1], today, later[0]])
    assert_single_owner(page, dashboard, today)
    for other in later:
        expect(dashboard).not_to_contain_text(other['opponent'])
    expect(dashboard.locator('.cb-home-metrics')).to_contain_text('3')


def test_live_game_offers_resume_once(open_home):
    g = game(507, 'Live Lions', 0, live=True)
    page, dashboard = open_home(DESKTOP, [g], ready={507: readiness(status='LIVE')})
    assert_single_owner(page, dashboard, g)
    expect(dashboard.locator('.cb-home-live')).to_have_count(0)
    expect(dashboard.locator('.cb-home-next-game .badge')).to_have_text('LIVE')
    assert visible_links(dashboard, '/game/507') == ['Resume Live Game']


@DEVICES
def test_no_upcoming_game_is_clean(open_home, device):
    page, dashboard = open_home(device, [])
    card = dashboard.locator('.cb-home-next-game')
    expect(card).to_have_count(1)
    expect(card).to_contain_text('No upcoming game')
    expect(card.locator('.cb-home-readiness')).to_have_count(0)
    assert not set(attention_titles(dashboard)) & set(GAME_PREP_ROWS)
    # Without a game the header still says how competition rules work.
    expect(dashboard.locator('.cb-home-context')).to_contain_text(re.compile('rules', re.I))
    expect(card.get_by_role('link', name='Open Game Day & Schedule')).to_be_visible()
    assert page.cb_errors == []


def test_manage_game_still_opens_the_real_game(browser, coachboard_url):
    cdn_assets.require_vendored_assets()
    context = browser.new_context(viewport=DESKTOP[1])
    cdn_assets.install(context)
    try:
        page = context.new_page()
        page.goto(f'{coachboard_url}/login')
        page.get_by_label('Username or email').fill(TEST_USERNAME)
        page.locator('#password').fill(TEST_PASSWORD)
        page.get_by_role('button', name='Sign In').click()
        card = page.locator('.cb-home-next-game')
        expect(card).to_contain_text('Browser Bears', timeout=20_000)
        card.get_by_role('link', name='Manage Game').click()
        expect(page).to_have_url(re.compile(r'/game/\d+$'))
        page.go_back()
        page.locator('.cb-home-quick', has_text='Game Day').click()
        expect(page).to_have_url(re.compile(r'/game-day/?$'))
    finally:
        context.close()
