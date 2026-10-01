"""Pregame: the pitcher picker shows who can pitch on the game's date.

Choosing the starting pitcher used to accept a resting pitcher with no word
(the rest rule was only enforced once the game went live). The P picker now
shows each player's status for the scheduled game date, from the same check
the live game uses, and a pitcher who isn't ready is asked about with the
live game's choices -- Use anyway (rule conflict), I verified (can't
confirm), Continue (advisory) -- or Cancel, which changes nothing.
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


def test_a_resting_pitcher_is_asked_about_and_cancel_changes_nothing(resting_rex, coachboard_url):
    page, game_id = resting_rex
    _open_p(page)
    expect(_choice(page, 'Relief Rex').locator('.pde-eligibility')).to_have_text(NOT_READY, timeout=10_000)
    _choice(page, 'Relief Rex').click()

    title = page.locator('#pde-player-modal .modal-title')
    expect(title).to_have_text(re.compile(r"^Relief Rex — (Rule conflict|Can't confirm)$"), timeout=10_000)
    expect(page.locator('#pde-help')).to_contain_text('70 game pitches on')
    go = page.locator('#pde-list .pde-question-choice').filter(
        has_text=re.compile(r'Use Relief Rex anyway|I verified Relief Rex can pitch'))
    expect(go).to_be_visible()

    page.locator('#pde-list .pde-question-choice[data-answer="cancel"]').click()
    expect(page.locator('#pde-player-modal')).to_be_hidden(timeout=10_000)
    page.wait_for_timeout(600)
    assert 'P' not in _filled(_innings(page, coachboard_url, game_id)['1'])

    # Asked again, the coach decides to use him: P is set and saved.
    _open_p(page)
    _choice(page, 'Relief Rex').click()
    expect(go).to_be_visible(timeout=10_000)
    go.click()
    expect(page.locator('#pde-player-modal')).to_be_hidden(timeout=10_000)
    _saved(page)
    assert _filled(_innings(page, coachboard_url, game_id)['1']) == dict(FIELDERS, P='Relief Rex')


def test_a_ready_pitcher_is_set_without_a_question(resting_rex, coachboard_url):
    page, game_id = resting_rex
    _open_p(page)
    expect(_choice(page, 'Relief Rae').locator('.pde-eligibility')).to_have_text('Ready', timeout=10_000)
    _choice(page, 'Relief Rae').click()
    expect(page.locator('#pde-player-modal')).to_be_hidden(timeout=10_000)
    _saved(page)
    assert _filled(_innings(page, coachboard_url, game_id)['1']) == dict(FIELDERS, P='Relief Rae')
