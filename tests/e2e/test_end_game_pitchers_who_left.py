"""End Game stats include every pitcher, even one who has left the game.

Luke starts on the mound, Mateo relieves him, Luke goes to the bench and is
marked unavailable (Menu -> Player availability). After End Game ("Not
Ready Yet"), Enter GameChanger Stats must still show Luke, saved counts come
back when the screen is opened again, and saving it again keeps them.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_reference import (  # noqa: E402,F401 (live is a fixture)
    INNING_1, PHONE, _api, _field_edit, _sequence, _state, live,
)


LUKE, MATEO = INNING_1['P'], INNING_1['1B']


def _pid(state, name):
    return next(p['id'] for p in state['roster'] + state.get('not_here', []) if p['name'] == name)


def _log(page, coachboard_url):
    return {o['player_name']: (o['pitches'], o['innings'])
            for o in _state(page, coachboard_url)['game_pitching_log']}


def _open_stats(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}?pitching=1')
    cards = page.locator('.final-pitcher-card')
    expect(cards.first).to_be_visible(timeout=20_000)
    return cards


def _card(page, name):
    return page.locator(f'.final-pitcher-card[data-player-name="{name}"]')


def _enter(page, name, pitches, innings):
    card = _card(page, name)
    card.locator('.final-complete-pitches').fill(str(pitches))
    card.locator('.final-complete-innings').fill(str(innings))


def _save(page):
    button = page.locator('#confirmFinalCountsBtn')
    expect(button).to_be_enabled()
    with page.expect_navigation(url=f'**/game-day/{page.cb_game}/report', timeout=20_000):
        button.click()


def test_a_pitcher_who_left_still_gets_stats_and_keeps_them(live, coachboard_url):
    page = live(PHONE, plan={'1': INNING_1, '2': INNING_1})
    api = page.cb_api.request
    state = _state(page, coachboard_url)
    response = api.post(_api(page, coachboard_url, 'change-pitcher'), data={
        'base_sequence': _sequence(state), 'new_pitcher_id': _pid(state, MATEO), 'outgoing_destination': '1B'})
    assert response.ok, response.text()[:200]
    state = _state(page, coachboard_url)
    bench = next(p['name'] for p in state['roster'] if p['name'] not in state['current_alignment'].values())
    _field_edit(page, coachboard_url, **{'1B': bench})                    # Luke to the bench
    state = _state(page, coachboard_url)
    response = api.post(_api(page, coachboard_url, 'availability'), data={
        'action': 'left', 'player_id': _pid(state, LUKE), 'base_sequence': _sequence(state)})
    assert response.ok, response.text()[:200]
    assert LUKE in {p['name'] for p in _state(page, coachboard_url)['not_here']}
    response = api.post(_api(page, coachboard_url, 'end-with-pitching'), data={'defer_pitching': True})
    assert response.ok                                                    # Not Ready Yet
    assert _log(page, coachboard_url) == {}

    # Both pitchers are on the stats screen, the one who left included.
    cards = _open_stats(page, coachboard_url)
    expect(cards).to_have_count(2)
    assert [c.get_attribute('data-player-name') for c in cards.all()] == [LUKE, MATEO]
    expect(_card(page, LUKE).locator('.final-complete-pitches')).to_have_value('')
    _enter(page, LUKE, 0, 1)                                              # a confirmed zero
    _enter(page, MATEO, 41, 1)
    _save(page)
    assert _log(page, coachboard_url) == {LUKE: (0, 1.0), MATEO: (41, 1.0)}

    # Opened again: the saved lines are filled in.
    _open_stats(page, coachboard_url)
    expect(_card(page, LUKE).locator('.final-complete-pitches')).to_have_value('0')
    expect(_card(page, MATEO).locator('.final-complete-pitches')).to_have_value('41')

    # Correct Mateo only; Luke's line stays.
    _card(page, MATEO).locator('.final-complete-pitches').fill('43')
    _save(page)
    assert _log(page, coachboard_url) == {LUKE: (0, 1.0), MATEO: (43, 1.0)}
    assert page.cb_errors == []
