"""Pregame: the pitcher picker shows who can pitch on the game's date.

Choosing the starting pitcher used to accept a resting pitcher with no word
(the rest rule was only enforced once the game went live). The P picker now
shows each player's status for the scheduled game date, from the same check
the live game uses. Planning never stops to ask: a pitcher who isn't ready is
set, and the status stays under the field. Start Game asks for the coach's
decision (Use anyway, I verified, Continue) before first pitch.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from test_set_defense_simplified import (  # noqa: F401 (make_page is a fixture)
    PANEL,
    _filled,
    _innings,
    _open_game,
    _saved,
    make_page,
)
from test_saved_defense_pitcher import setup  # noqa: F401 (fixture)

from playwright.sync_api import expect  # noqa: E402


pytestmark = pytest.mark.e2e

FIELDERS = {'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam', '3B': 'Third Theo',
            'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley'}
NOT_READY = re.compile(r"^(Rule conflict|Can't confirm)")


def _add_game(page, url, day, opponent):
    response = page.request.post(f'{url}/game-day/add', form={
        'game_date': day.isoformat(), 'game_start_time': '15:00', 'game_opponent': opponent,
        'game_location': 'Eligibility Field', 'pitching_rule_set': 'MLB Pitch Smart'}, max_redirects=0)
    return int(re.search(r'/game/(\d+)', response.headers['location']).group(1))


def _delete_game(page, url, game_id):
    page.request.post(f'{url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})


@pytest.fixture
def resting_rex(setup, coachboard_url):
    """Relief Rex threw 70 game pitches yesterday; the game is tomorrow."""
    page = setup[0]
    today = datetime.now(ZoneInfo('America/Indiana/Indianapolis')).date()
    games = []
    try:
        yesterday = _add_game(page, coachboard_url, today - timedelta(days=1), 'Yesterday Opponent')
        games.append(yesterday)
        rex = next(p['id'] for p in page.request.get(f'{coachboard_url}/api/roster').json()
                   if p['name'] == 'Relief Rex')
        saved = page.request.post(f'{coachboard_url}/add_pitching', form={
            'game_id': str(yesterday), 'player_id': str(rex), 'pitches': '70',
            'innings_whole': '3', 'innings_outs': '0', 'pitcher_type': 'Starter'}, max_redirects=0)
        assert saved.status in {302, 303}, saved.text()[:200]
        game_id = _add_game(page, coachboard_url, today + timedelta(days=1), 'Tomorrow Opponent')
        games.append(game_id)
        page.request.post(f'{coachboard_url}/save_rotation', data={
            'title': 'Rotation', 'innings': {'1': dict(FIELDERS)}, 'associated_game_id': game_id})
        _open_game(page, coachboard_url, game_id)
        yield page, game_id
    finally:
        for game in games:
            _delete_game(page, coachboard_url, game)


def _open_p(page):
    page.locator(f'{PANEL} [data-pde-pos="P"]').click()
    expect(page.locator('#pde-player-modal')).to_be_visible(timeout=10_000)


def _choice(page, name):
    return page.locator(f'#pde-list .pde-choice[data-player="{name}"]')


def test_the_p_picker_shows_each_players_status_for_the_game_date(resting_rex):
    page, _ = resting_rex
    _open_p(page)
    expect(_choice(page, 'Relief Rex').locator('.pde-eligibility')).to_have_text(NOT_READY, timeout=10_000)
    expect(_choice(page, 'Relief Rae').locator('.pde-eligibility')).to_have_text('Ready')


def test_a_resting_pitcher_is_flagged_inline_and_start_game_still_asks(resting_rex, coachboard_url):
    """Planning never stops to ask: the status is on the row and stays under
    the field. Start Game is where the decision is required."""
    page, game_id = resting_rex
    _open_p(page)
    expect(_choice(page, 'Relief Rex').locator('.pde-eligibility')).to_have_text(NOT_READY, timeout=10_000)
    _choice(page, 'Relief Rex').click()

    # No question sheet: Rex is set and saved.
    expect(page.locator('#pde-player-modal')).to_be_hidden(timeout=10_000)
    expect(page.locator('.pde-question-choice')).to_have_count(0)
    _saved(page)
    assert _filled(_innings(page, coachboard_url, game_id)['1']) == dict(FIELDERS, P='Relief Rex')

    # The status stays visible under the field, once.
    note = page.locator(f'{PANEL} .pde-pitcher-note')
    expect(note).to_have_count(1, timeout=10_000)
    expect(note).to_have_text(re.compile(
        r"^Relief Rex: (Rule conflict|Can't confirm) · .*70 game pitches on.*Start Game will ask before first pitch\.$"))

    # Start Game still requires the coach's decision about Rex.
    page.locator('#startLiveGameBtnAction').click()
    sheet = page.locator('#cbStartGameModal')
    expect(sheet).to_be_visible(timeout=15_000)
    expect(sheet.locator('.modal-title')).to_have_text('Relief Rex appears ineligible to pitch')
    expect(sheet.get_by_role('button', name='Use Relief Anyway')).to_be_visible()
    sheet.get_by_role('button', name='Close').click()
    expect(sheet).to_be_hidden(timeout=10_000)
    state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
    assert state['game']['is_live'] is False


def test_a_ready_pitcher_is_set_without_a_question(resting_rex, coachboard_url):
    page, game_id = resting_rex
    _open_p(page)
    expect(_choice(page, 'Relief Rae').locator('.pde-eligibility')).to_have_text('Ready', timeout=10_000)
    _choice(page, 'Relief Rae').click()
    expect(page.locator('#pde-player-modal')).to_be_hidden(timeout=10_000)
    _saved(page)
    assert _filled(_innings(page, coachboard_url, game_id)['1']) == dict(FIELDERS, P='Relief Rae')
