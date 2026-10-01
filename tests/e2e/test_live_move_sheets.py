"""On the Field: every move is saved without asking whether the inning started,
and every move sheet is closed before its change is saved.

* Start Game and End Inning -> Start Next Inning are the inning boundary
  (game_availability.py); no On the Field change asks "Has the 4th inning
  started?".
* The coach decides where a displaced player goes -- CoachBoard never does.
  A decision involving two players is saved as soon as the second choice is
  made; three or more players get one final "Check the defensive change".
* The sheet closes before the save begins, so nothing stacks on it; a
  successful save leaves every move sheet closed; a refused or failed save
  is reported once, on the Quick Field status; Cancel writes nothing.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect

from test_live_change_pitcher_decision import (  # noqa: F401 (fixture)
    BASE,
    RELIEVER,
    answer,
    choose_new_pitcher,
    filled,
    live_field,
    live_state,
    sequence,
    wait_for_field,
)
from test_live_defense_coach_chain import (
    bench_player,
    choices,
    expect_question,
    expect_review,
    field_player,
    pick,
    tap_move,
)


SHEET = '#cbQuickMoveModal'
NO_LF = {pos: name for pos, name in BASE.items() if pos != 'LF'}


def _changes(page, url, game_id):
    return [
        e['event_type']
        for e in sorted(live_state(page, url, game_id)['rotation_events'], key=lambda e: e['sequence'])
        if not e.get('reverted') and e['event_type'] != 'Inning Started'
    ]


def _record_writes(page):
    writes = []
    page.on('request', lambda request: writes.append(request.url.rsplit('/', 1)[-1])
            if request.method == 'POST' and '/api/live-game/' in request.url else None)
    return writes


def _all_sheets_closed(page):
    expect(page.locator('.modal.show')).to_have_count(0, timeout=10_000)
    expect(page.locator('.modal-backdrop')).to_have_count(0)
    assert not page.locator('#cbInningStartModal').count()


def test_start_game_started_the_1st_with_its_defense(page: Page, coachboard_url, live_field):
    game_id = live_field()
    markers = [e for e in live_state(page, coachboard_url, game_id)['rotation_events']
               if e['event_type'] == 'Inning Started']
    assert [(m['inning'], filled(m['after_alignment'])) for m in markers] == [('1', BASE)]


def test_a_single_move_saves_without_an_inning_question(page: Page, coachboard_url, live_field):
    game_id = live_field()
    state = live_state(page, coachboard_url, game_id)
    response = page.request.post(
        f'{coachboard_url}/api/live-game/{game_id}/defense-edit',
        data={'alignment': NO_LF, 'base_sequence': sequence(state)},
    )
    assert response.ok, response.text()[:300]
    expect(page.locator(f'#cbQuickDefense {field_player("LF")}')).to_contain_text('Open', timeout=10_000)

    tap_move(page, bench_player(RELIEVER), 'LF')
    wait_for_field(page, coachboard_url, game_id, dict(NO_LF, LF=RELIEVER))
    _all_sheets_closed(page)


def test_change_pitcher_saves_without_an_inning_question(page: Page, coachboard_url, live_field):
    game_id = live_field()
    question = choose_new_pitcher(page, 'Shortstop Shawn')
    answer(question, 'Put Pitcher Pat at SS')
    wait_for_field(page, coachboard_url, game_id, dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat'))
    assert _changes(page, coachboard_url, game_id) == ['Pitcher Change']
    _all_sheets_closed(page)


def test_bench_player_in_and_occupant_to_bench_saves_on_that_choice(page: Page, coachboard_url, live_field):
    """Graham: Bench -> 1B; the coach sends Hansen (1B) to the bench. Saved."""
    game_id = live_field()
    writes = _record_writes(page)
    sheet = tap_move(page, bench_player(RELIEVER), '1B')
    expect_question(sheet, f'{RELIEVER} is moving to 1B', 'Where should First Frank go?')
    page.wait_for_timeout(300)
    assert writes == []                        # nothing is decided for the coach
    pick(sheet, 'Bench First Frank')

    wait_for_field(page, coachboard_url, game_id, dict(BASE, **{'1B': RELIEVER}))
    _all_sheets_closed(page)
    expect(page.locator(SHEET).get_by_text('Check the defensive change')).to_have_count(0)
    assert writes == ['defense-edit']
    assert _changes(page, coachboard_url, game_id) == ['Bulk Defensive Change']


def test_a_swap_is_saved_on_the_coachs_second_choice(page: Page, coachboard_url, live_field):
    game_id = live_field()
    sheet = tap_move(page, field_player('2B'), 'SS')
    pick(sheet, 'Put Shortstop Shawn at 2B')
    wait_for_field(page, coachboard_url, game_id, dict(BASE, SS='Second Sam', **{'2B': 'Shortstop Shawn'}))
    _all_sheets_closed(page)


def test_three_players_get_one_final_review(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = _record_writes(page)
    sheet = tap_move(page, field_player('2B'), 'SS')
    pick(sheet, 'Move Shortstop Shawn to another position…')
    pick(sheet, '1B · First Frank')
    pick(sheet, 'Put First Frank at 2B')
    expect_review(sheet, ['Second Sam: 2B → SS', 'Shortstop Shawn: SS → 1B', 'First Frank: 1B → 2B'])
    assert writes == []
    pick(sheet, 'Make this change')
    wait_for_field(page, coachboard_url, game_id,
                   dict(BASE, SS='Second Sam', **{'1B': 'Shortstop Shawn', '2B': 'First Frank'}))
    _all_sheets_closed(page)
    assert writes == ['defense-edit']


def test_cancel_writes_nothing_and_closes(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = _record_writes(page)
    sheet = tap_move(page, bench_player(RELIEVER), '1B')
    pick(sheet, 'Cancel')
    _all_sheets_closed(page)

    sheet = tap_move(page, field_player('2B'), 'SS')
    pick(sheet, 'Move Shortstop Shawn to another position…')
    pick(sheet, '1B · First Frank')
    pick(sheet, 'Put First Frank at 2B')
    pick(sheet, 'Cancel')                      # at the final review
    _all_sheets_closed(page)
    page.wait_for_timeout(500)
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE


def test_a_refused_save_is_reported_once_with_every_sheet_closed(page: Page, coachboard_url, live_field):
    game_id = live_field()
    page.route('**/api/live-game/*/defense-edit', lambda route: route.fulfill(
        status=409, content_type='application/json',
        body='{"status": "error", "message": "First Frank is not available for this game."}',
    ))
    sheet = tap_move(page, bench_player(RELIEVER), '1B')
    pick(sheet, 'Bench First Frank')
    status = page.locator('#cbQuickDefense .cb-save-state')
    expect(status).to_contain_text('Not saved — First Frank is not available for this game.', timeout=10_000)
    _all_sheets_closed(page)
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE


def test_a_lost_connection_offers_retry_of_the_same_decision(page: Page, coachboard_url, live_field):
    game_id = live_field()
    failing = {'on': True}

    def handle(route):
        if failing['on']:
            route.abort()
        else:
            route.continue_()

    page.route('**/api/live-game/*/defense-edit', handle)
    sheet = tap_move(page, bench_player(RELIEVER), '1B')
    pick(sheet, 'Bench First Frank')
    status = page.locator('#cbQuickDefense .cb-save-state')
    expect(status).to_contain_text('Not saved — Retry', timeout=10_000)
    _all_sheets_closed(page)

    failing['on'] = False
    status.click()
    wait_for_field(page, coachboard_url, game_id, dict(BASE, **{'1B': RELIEVER}))
    _all_sheets_closed(page)
