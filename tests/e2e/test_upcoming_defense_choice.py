"""Which defense takes the field next, said plainly, and kept as chosen.

* An upcoming inning with no plan of its own carries the field forward.
* A live change during the 1st still carries the field forward when the 2nd
  has its own plan, but the Next Inning board now says so -- "Using the
  1st-inning field. Your 2nd-inning plan won't be used." -- and offers
  "Use 2nd-inning plan". That choice is saved as the coach's: a reload, a
  tab switch, or another live change does not undo it, and End Inning
  starts exactly that defense. A different pitcher in it goes through End
  Inning's usual pitching check.
* After an edit the header says "Changes saved for the 2nd" at once.
* Bench Report projects the upcoming inning from the defense that will
  actually start, then the plan, and names innings it can't project.
* Pregame Plan keeps the original plan as a reference and labels its two
  comparisons: plan against plan, and the game against this plan.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from playwright.sync_api import Page, expect
from start_helpers import start_body

from e2e_cleanup import delete_players_named
from test_next_inning_save_race import cleanup_game, login, post_json, starting_alignment
from test_pregame_player_time_summary import add_player


pytestmark = pytest.mark.e2e

CARD = '#live-board-prep-v3'
PHONE = {'width': 390, 'height': 844}
BENCH = 'Bench Bo'

D1 = starting_alignment()
# The 2nd's own plan: four positions differ -- Bench Bo plays RF, Right Riley
# LF, and Left Lee sits.
D2 = dict(D1, **{'1B': 'Second Sam', '2B': 'First Frank', 'LF': 'Right Riley', 'RF': BENCH})
SWAP = dict(D1, SS='Third Theo', **{'3B': 'Shortstop Shawn'})      # a live change in the 1st
NOTE = "Using the 1st-inning field. Your 2nd-inning plan won't be used."


def _filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def _today():
    return datetime.now(ZoneInfo('America/Indiana/Indianapolis')).date()


def _create_game(page, url, innings, *, day=None, rule='USSSA', opponent='Upcoming Defense'):
    response = page.request.post(f'{url}/game-day/add', form={
        'game_date': (day or _today()).isoformat(), 'game_start_time': '13:00',
        'game_opponent': opponent, 'game_location': 'Choice Field', 'pitching_rule_set': rule,
    }, max_redirects=0)
    game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
    post_json(page, url, '/save_rotation', {
        'title': 'Upcoming Defense Rotation', 'innings': innings, 'associated_game_id': game_id})
    return game_id


def _state(page, url, game_id):
    return page.request.get(f'{url}/api/live-game/{game_id}/state').json()


def _prep(page, url, game_id):
    return page.request.get(f'{url}/api/live-game/{game_id}/next-inning-prep').json()['confirmed']


def _sequence(state):
    return max([int(e.get('sequence') or 0) for e in state.get('rotation_events', [])
                if not e.get('reverted')] or [0])


def _live_change(page, url, game_id, alignment):
    response = page.request.post(f'{url}/api/live-game/{game_id}/defense-edit', data={
        'alignment': alignment, 'base_sequence': _sequence(_state(page, url, game_id))})
    assert response.ok, response.text()[:300]


def _board(page):
    return page.locator(CARD)


def _spot(page, pos):
    return _board(page).locator(f'[data-next-position="{pos}"]')


def _board_alignment(page):
    return _filled(page.evaluate('() => window.CBNextDefense.getAlignment()'))


def _show(page, view):
    page.locator(f'#cb-now-next-switch [data-now-next="{view}"]').click()


def _expect_board(page, alignment, label):
    board = _board(page)
    expect(board.locator('[data-next-hint]')).to_have_text(label, timeout=15_000)
    for pos, name in alignment.items():
        expect(_spot(page, pos)).to_have_attribute('data-next-player', name)


@pytest.fixture
def game(page: Page, coachboard_url):
    """Live, 1st inning; the 2nd has its own plan (D2), the 3rd has CF open,
    the 4th-6th have no plan."""
    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    add_player(page, coachboard_url, BENCH, '31')
    third = {pos: name for pos, name in D2.items() if pos != 'CF'}
    game_id = _create_game(page, coachboard_url, {'1': D1, '2': D2, '3': third})
    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start',
                  start_body(page.request, coachboard_url, game_id))
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#cb-now-next-switch')).to_be_visible(timeout=15_000)
        _show(page, 'next')
        yield game_id
    finally:
        cleanup_game(page, coachboard_url, game_id)
        delete_players_named(page.request, coachboard_url, [BENCH])


# 1. A separately planned next inning -------------------------------------------------------

def test_the_planned_inning_is_shown_as_planned(page: Page, coachboard_url, game):
    _expect_board(page, D2, 'Pregame plan for the 2nd')
    expect(_board(page).locator('[data-next-plan-note]')).to_have_count(0)
    expect(_board(page).get_by_role('button', name='Use 2nd-inning plan')).to_have_count(0)
    expect(_board(page).get_by_role('button', name='Use 1st Inning Defense')).to_be_visible()


# 2. A live change carries the field forward, and says so -----------------------------------

def test_a_live_change_says_the_plan_wont_be_used(page: Page, coachboard_url, game):
    _live_change(page, coachboard_url, game, SWAP)
    _expect_board(page, SWAP, 'Same defense as the 1st')
    expect(_board(page).locator('[data-next-plan-note]')).to_have_text(NOTE)
    expect(_board(page).get_by_role('button', name='Use 2nd-inning plan')).to_be_visible()
    # The original plan is still there, labelled as the reference.
    _show(page, 'plan')
    expect(page.get_by_text('Reference only').first).to_be_visible(timeout=10_000)
    # Plan against plan, and the game against this plan, each labelled.
    expect(page.locator('.cb-plan-changes')).to_have_text('Plan change from Inning 1: 1B, 2B, LF, RF')
    expect(page.locator('.cb-plan-colhead .cb-plan-planned')).to_have_text('Pregame plan')
    expect(page.locator('.cb-plan-colhead .cb-plan-game')).to_have_text('Next inning')


# 3. Choosing the saved plan, keeping it, and starting with exactly it -----------------------

def test_using_the_plan_is_kept_and_starts_the_inning(page: Page, coachboard_url, game):
    _live_change(page, coachboard_url, game, SWAP)
    _expect_board(page, SWAP, 'Same defense as the 1st')
    _board(page).get_by_role('button', name='Use 2nd-inning plan').click()
    _expect_board(page, D2, 'Pregame plan for the 2nd')
    expect(_board(page).locator('[data-next-plan-note]')).to_have_count(0)
    page.wait_for_timeout(800)
    prep = _prep(page, coachboard_url, game)
    assert prep['source'] == 'planned' and _filled(prep['alignment']) == D2

    # A tab switch, a reload, and another live change keep the choice.
    _show(page, 'now')
    _show(page, 'next')
    _expect_board(page, D2, 'Pregame plan for the 2nd')
    page.reload(wait_until='domcontentloaded')
    expect(page.locator('#cb-now-next-switch')).to_be_visible(timeout=15_000)
    _show(page, 'next')
    _expect_board(page, D2, 'Pregame plan for the 2nd')
    _live_change(page, coachboard_url, game, dict(SWAP, LF='Center Casey', CF='Left Lee'))
    page.wait_for_timeout(4_500)                  # past the board's poll
    _expect_board(page, D2, 'Pregame plan for the 2nd')

    page.locator('#liveEndInningBtn').click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    assert _filled(_state(page, coachboard_url, game)['current_alignment']) == D2


# 4. An unplanned inning keeps carrying forward ---------------------------------------------

def test_an_unplanned_inning_follows_the_field(page: Page, coachboard_url):
    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    game_id = _create_game(page, coachboard_url, {'1': D1}, opponent='Unplanned')
    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start',
                  start_body(page.request, coachboard_url, game_id))
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#cb-now-next-switch')).to_be_visible(timeout=15_000)
        _show(page, 'next')
        _expect_board(page, D1, 'Same defense as the 1st')
        _live_change(page, coachboard_url, game_id, SWAP)
        _expect_board(page, SWAP, 'Same defense as the 1st')
        expect(_board(page).locator('[data-next-plan-note]')).to_have_count(0)
        expect(_board(page).get_by_role('button', name='Use 2nd-inning plan')).to_have_count(0)
        page.locator('#liveEndInningBtn').click()
        expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
        assert _filled(_state(page, coachboard_url, game_id)['current_alignment']) == SWAP
    finally:
        cleanup_game(page, coachboard_url, game_id)


# 5. A direct edit to the upcoming defense ---------------------------------------------------

def test_an_edit_is_named_at_once_and_the_plan_can_come_back(page: Page, coachboard_url, game):
    _expect_board(page, D2, 'Pregame plan for the 2nd')
    _spot(page, 'LF').click()
    _board(page).get_by_role('button', name=re.compile(r'^Bench #\d+ Right Riley$')).click()
    # The label follows the edit immediately, not after the next redraw.
    expect(_board(page).locator('[data-next-hint]')).to_have_text('Changes saved for the 2nd', timeout=400)
    expect(_board(page).locator('[data-next-plan-note]')).to_have_text(
        "Changed for the 2nd. Your 2nd-inning plan won't be used.")
    page.wait_for_timeout(800)
    assert _prep(page, coachboard_url, game)['source'] == 'custom'
    _board(page).get_by_role('button', name='Use 2nd-inning plan').click()
    _expect_board(page, D2, 'Pregame plan for the 2nd')


# 6. Undo ----------------------------------------------------------------------------------

def test_undo_of_the_live_change_brings_the_plan_back(page: Page, coachboard_url, game):
    _live_change(page, coachboard_url, game, SWAP)
    _expect_board(page, SWAP, 'Same defense as the 1st')
    _show(page, 'now')
    page.locator('#liveUndoBtn').click()
    page.wait_for_function(
        f"async () => (await (await fetch('/api/live-game/{game}/state')).json()).current_alignment.SS === 'Shortstop Shawn'",
        timeout=10_000,
    )
    _show(page, 'next')
    _expect_board(page, D2, 'Pregame plan for the 2nd')
    expect(_board(page).locator('[data-next-plan-note]')).to_have_count(0)


def test_undo_on_the_next_inning_board_takes_back_using_the_plan(page: Page, coachboard_url, game):
    _live_change(page, coachboard_url, game, SWAP)
    _expect_board(page, SWAP, 'Same defense as the 1st')
    _board(page).get_by_role('button', name='Use 2nd-inning plan').click()
    _expect_board(page, D2, 'Pregame plan for the 2nd')
    page.wait_for_timeout(800)
    page.locator('#liveUndoBtn').click()
    expect(_spot(page, 'SS')).to_have_attribute('data-next-player', 'Third Theo', timeout=10_000)
    expect(_board(page).locator('[data-next-plan-note]')).to_be_visible()
    expect(_board(page).get_by_role('button', name='Use 2nd-inning plan')).to_be_visible()


# 7. Bench Report ---------------------------------------------------------------------------

def _bench_report(page):
    _show(page, 'now')
    page.locator('[data-cb-bench-report]').click()
    modal = page.locator('#cbBenchReportModal')
    expect(modal.locator('[data-cb-br-basis]')).to_be_visible(timeout=10_000)
    return modal


def _row(modal, name):
    return modal.locator('.cb-br-row').filter(has_text=name)


def test_bench_report_follows_the_defense_that_will_start(page: Page, coachboard_url, game):
    # Carried forward: Bench Bo sits the 2nd; Left Lee plays it.
    _live_change(page, coachboard_url, game, SWAP)
    _expect_board(page, SWAP, 'Same defense as the 1st')
    modal = _bench_report(page)
    expect(modal.locator('[data-cb-br-basis]')).to_have_text(
        'Projections use the 2nd-inning defense as it will start, then the pregame plan.')
    expect(_row(modal, BENCH)).to_contain_text('Projected to sit: 2')
    expect(_row(modal, 'Left Lee')).not_to_contain_text('Projected to sit')
    # The 3rd has CF open and the 4th-6th have no plan: named, not counted.
    expect(modal.locator('[data-cb-br-unprojected]')).to_have_text(
        "Not projected: 3rd (CF open), 4th (not planned), 5th (not planned), 6th (not planned). "
        "Sits for those innings aren't counted.")
    modal.get_by_role('button', name='Back to Game').click()
    expect(modal).to_be_hidden()

    # Using the plan (Riley to LF, Bench Bo in RF): now Left Lee sits the 2nd.
    _show(page, 'next')
    _board(page).get_by_role('button', name='Use 2nd-inning plan').click()
    _expect_board(page, D2, 'Pregame plan for the 2nd')
    page.wait_for_timeout(800)
    modal = _bench_report(page)
    expect(_row(modal, 'Left Lee')).to_contain_text('Projected to sit: 2', timeout=10_000)
    expect(_row(modal, BENCH)).not_to_contain_text('Projected to sit')


# 8. A different pitcher in the plan meets End Inning's pitching check ----------------------

def test_a_resting_pitcher_in_the_plan_is_asked_about_at_end_inning(page: Page, coachboard_url):
    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    today = _today()
    games = []
    try:
        # Center Casey threw 70 game pitches yesterday (Pitch Smart: resting).
        yesterday = _create_game(page, coachboard_url, {'1': D1}, day=today - timedelta(days=1),
                                 rule='MLB Pitch Smart', opponent='Yesterday')
        games.append(yesterday)
        casey = next(p['id'] for p in page.request.get(f'{coachboard_url}/api/roster').json()
                     if p['name'] == 'Center Casey')
        saved = page.request.post(f'{coachboard_url}/add_pitching', form={
            'game_id': str(yesterday), 'player_id': str(casey), 'pitches': '70',
            'innings_whole': '3', 'innings_outs': '0', 'pitcher_type': 'Starter'}, max_redirects=0)
        assert saved.status in {302, 303}

        casey_pitches = dict(D1, P='Center Casey', CF='Pitcher Pat')
        game_id = _create_game(page, coachboard_url, {'1': D1, '2': casey_pitches},
                               rule='MLB Pitch Smart', opponent='Today')
        games.append(game_id)
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start',
                  start_body(page.request, coachboard_url, game_id))
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#cb-now-next-switch')).to_be_visible(timeout=15_000)
        _show(page, 'next')
        _live_change(page, coachboard_url, game_id, SWAP)
        _expect_board(page, SWAP, 'Same defense as the 1st')
        _board(page).get_by_role('button', name='Use 2nd-inning plan').click()
        _expect_board(page, casey_pitches, 'Pregame plan for the 2nd')
        page.wait_for_timeout(800)

        page.locator('#liveEndInningBtn').click()
        decision = page.locator('#cbPitchingDecisionModal')
        expect(decision).to_be_visible(timeout=15_000)
        expect(decision).to_contain_text('70 game pitches')
        decision.locator('[data-cb-decision-cancel]').click()
        expect(decision).to_be_hidden(timeout=10_000)
        page.wait_for_timeout(600)
        assert str(_state(page, coachboard_url, game_id)['current_inning']) == '1'
    finally:
        for game_id in games:
            cleanup_game(page, coachboard_url, game_id)
