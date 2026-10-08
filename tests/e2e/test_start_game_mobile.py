"""Start Game on a phone: usable when the game is ready, and says why when not.

A coach's roster name was saved as typed on an iPhone, autocomplete's
trailing space and all ('Rhett Wanninger '). The 1st-inning check trimmed the
plan's names but not the roster's, so Start Game was greyed out with "...is
at 2B in the 1st inning but is not on the roster" -- a message phones never
showed, because the canonical Start and its reason box are hidden there and a
proxy Start Game in the header stands in for them.
"""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect  # noqa: E402

from e2e_cleanup import delete_players_named  # noqa: E402
from test_live_game_switcher_boot import alignment, cleanup_game, login, post_json  # noqa: E402
from test_pregame_player_time_summary import add_player  # noqa: E402


PHONE = {'width': 390, 'height': 844}
PADDED = 'Rhett Probe '                      # as saved from a phone keyboard
START = '#gm-mobile-start-game'
REASON = '#gm-mobile-start-reason'


def create_game(page: Page, url: str, innings):
    response = page.request.post(f'{url}/game-day/add', form={
        'game_date': (date.today() + timedelta(days=2)).isoformat(),
        'game_start_time': '19:00',
        'game_opponent': 'Westfield Probe',
        'game_location': 'Mobile Start Field',
        'pitching_rule_set': 'USSSA',
    }, max_redirects=0)
    game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
    post_json(page, url, '/save_rotation', {
        'title': 'Mobile Start Rotation', 'innings': innings, 'associated_game_id': game_id})
    return game_id


@pytest.fixture
def padded_player(page: Page, coachboard_url):
    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    add_player(page, coachboard_url, PADDED, '44')
    assert PADDED in [p['name'] for p in page.request.get(f'{coachboard_url}/api/roster').json()]
    yield
    delete_players_named(page.request, coachboard_url, [PADDED])


def open_game(page: Page, url: str, game_id: int):
    page.goto(f'{url}/game/{game_id}', wait_until='domcontentloaded')
    expect(page.locator(START)).to_be_visible(timeout=15_000)


def test_a_padded_roster_name_does_not_grey_out_start_game(page: Page, coachboard_url, padded_player):
    # Six innings; Rhett at 2B. The 1st and 2nd hold his name exactly as on
    # the roster, the rest the trimmed spelling some editors save.
    innings = {str(n): dict(alignment(), **{'2B': PADDED}) for n in (1, 2)}
    innings.update({str(n): dict(alignment(), **{'2B': PADDED.strip()}) for n in range(3, 7)})
    game_id = create_game(page, coachboard_url, innings)
    try:
        readiness = page.request.get(f'{coachboard_url}/api/game-day/{game_id}/readiness').json()
        assert readiness['ready'] is True, readiness['missing']
        assert readiness['readiness']['defense_completed_innings'] == 6

        open_game(page, coachboard_url, game_id)
        start = page.locator(START)
        expect(start).to_be_enabled(timeout=10_000)
        expect(page.locator(REASON)).to_be_hidden()

        # The coach's own button starts the game.
        start.click()
        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=20_000)
        state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert state['game']['is_live'] is True
        assert state['current_alignment']['2B'].strip() == PADDED.strip()
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_a_real_blocker_is_explained_right_under_start_game(page: Page, coachboard_url, padded_player):
    innings = {str(n): dict(alignment(), **{'2B': 'Nobody On Roster'}) for n in range(1, 7)}
    game_id = create_game(page, coachboard_url, innings)
    try:
        open_game(page, coachboard_url, game_id)
        start = page.locator(START)
        expect(start).to_be_disabled(timeout=10_000)

        reason = page.locator(REASON)
        expect(reason).to_be_visible()
        expect(reason).to_have_text('Nobody On Roster is at 2B in the 1st inning but is not on the roster.')
        expect(start).to_have_attribute('aria-describedby', 'gm-mobile-start-reason')

        # Directly under the button, on screen without scrolling.
        button, note = start.bounding_box(), reason.bounding_box()
        assert 0 <= note['y'] - (button['y'] + button['height']) <= 24, (button, note)
        assert note['y'] + note['height'] <= PHONE['height']

        # Still a hard stop: tapping does nothing.
        start.click(force=True)
        page.wait_for_timeout(800)
        state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert not state['game']['is_live']

        # Fixed in place: Start becomes usable and the note goes away.
        post_json(page, coachboard_url, '/save_rotation', {
            'title': 'Mobile Start Rotation', 'associated_game_id': game_id,
            'id': page.request.get(f'{coachboard_url}/api/game_data/{game_id}').json()['rotation']['id'],
            'innings': {str(n): dict(alignment(), **{'2B': PADDED}) for n in range(1, 7)},
        })
        expect(start).to_be_enabled(timeout=12_000)
        expect(reason).to_be_hidden()
    finally:
        cleanup_game(page, coachboard_url, game_id)
