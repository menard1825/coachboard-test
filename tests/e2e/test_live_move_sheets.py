"""On the Field: every move is saved without asking whether the inning started,
and every move sheet is closed before its change is saved.

* Start Game and End Inning -> Start Next Inning are the inning boundary
  (game_availability.py); no On the Field change asks "Has the 4th inning
  started?".
* A successful save leaves every move sheet closed.

(Refused and failed saves, Retry and the move rules themselves are covered
with both gestures in test_live_move_single_writer.)
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

from live_fixtures import (  # noqa: F401 (fixture)
    BASE,
    RELIEVER,
    bench_player,
    field_player,
    filled,
    last_sequence as sequence,
    live_field,
    live_state,
    tap_move,
    wait_for_field,
)
from change_pitcher_flow import choose_incoming_pitcher, choose_outgoing_destination


NO_LF = {pos: name for pos, name in BASE.items() if pos != 'LF'}


def _changes(page, url, game_id):
    return [
        e['event_type']
        for e in sorted(live_state(page, url, game_id)['rotation_events'], key=lambda e: e['sequence'])
        if not e.get('reverted') and e['event_type'] != 'Inning Started'
    ]


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
    question = choose_incoming_pitcher(page, 'Shortstop Shawn')
    choose_outgoing_destination(question, 'Pitcher Pat → SS')
    wait_for_field(page, coachboard_url, game_id, dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat'))
    assert _changes(page, coachboard_url, game_id) == ['Pitcher Change']
    _all_sheets_closed(page)

