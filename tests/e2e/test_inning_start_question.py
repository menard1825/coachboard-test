"""On the Field: "Has the 1st inning started?"

End Inning (and Start Game) only load an inning's defense. The first On the
Field change to an inning CoachBoard doesn't know has begun asks the coach
(game_availability.py, live_history.py):

* Not yet -- the change is saved as a setup edit; the next change asks again;
* Yes, inning started -- the defense that began the inning is recorded just
  before the change, and nothing asks again that inning;
* Cancel change -- nothing is sent or saved; the field is exactly as it was.

Other browser tests answer "Not yet" by default (tests/e2e/conftest.py).
These opt out, so each production writer -- a single move, a multi-player
change, Change Pitcher -- must handle the real question itself.
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

from conftest import ask_inning_start_question
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
from test_live_defense_coach_chain import bench_player, field_player, pick, tap_move


QUESTION = '#cbInningStartModal'
TITLE = 'Has the 1st inning started?'
SWAPPED = dict(BASE, SS='Second Sam', **{'2B': 'Shortstop Shawn'})
NO_LF = {pos: name for pos, name in BASE.items() if pos != 'LF'}


def _active(page, url, game_id):
    return sorted(
        (e for e in live_state(page, url, game_id)['rotation_events'] if not e.get('reverted')),
        key=lambda e: e['sequence'],
    )


def _kinds(page, url, game_id):
    return [e['event_type'] for e in _active(page, url, game_id)]


def _question(page):
    question = page.locator(QUESTION)
    expect(question.locator('.modal-title')).to_have_text(TITLE, timeout=10_000)
    return question


def _answer(page, label):
    question = _question(page)
    question.get_by_role('button', name=label, exact=True).click()
    expect(question).to_be_hidden(timeout=10_000)


def _swap(page, other_name):
    """A multi-player change: whoever is at 2B and other_name at SS trade places."""
    sheet = tap_move(page, field_player('2B'), 'SS')
    pick(sheet, f'Put {other_name} at 2B')
    pick(sheet, 'Make this change')


def _no_change_saved(page, url, game_id, alignment, kinds):
    page.wait_for_timeout(800)
    assert filled(live_state(page, url, game_id)['current_alignment']) == alignment
    assert _kinds(page, url, game_id) == kinds


@pytest.fixture
def asking(page: Page, coachboard_url, live_field):  # noqa: F811 (fixture)
    game_id = live_field()
    ask_inning_start_question(page)
    page.reload(wait_until='domcontentloaded')
    expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
    return game_id


# --- A multi-player change (Defense Edit) --------------------------------------------------------

def test_not_yet_saves_the_change_and_asks_again(page: Page, coachboard_url, asking):
    game_id = asking
    _swap(page, 'Shortstop Shawn')
    question = _question(page)
    for label in ('Cancel change', 'Not yet', 'Yes, inning started'):
        expect(question.get_by_role('button', name=label, exact=True)).to_be_visible()
    _answer(page, 'Not yet')
    wait_for_field(page, coachboard_url, game_id, SWAPPED)
    events = _active(page, coachboard_url, game_id)
    assert [e['event_type'] for e in events] == ['Bulk Defensive Change']
    assert events[0]['pre_start'] is True

    _swap(page, 'Second Sam')
    _answer(page, 'Not yet')
    wait_for_field(page, coachboard_url, game_id, BASE)


def test_yes_records_the_start_and_is_not_asked_again(page: Page, coachboard_url, asking):
    game_id = asking
    _swap(page, 'Shortstop Shawn')
    _answer(page, 'Yes, inning started')
    wait_for_field(page, coachboard_url, game_id, SWAPPED)
    events = _active(page, coachboard_url, game_id)
    assert [e['event_type'] for e in events] == ['Inning Started', 'Bulk Defensive Change']
    assert filled(events[0]['after_alignment']) == BASE
    assert events[1]['pre_start'] is False

    _swap(page, 'Second Sam')
    wait_for_field(page, coachboard_url, game_id, BASE)
    expect(page.locator(QUESTION)).to_be_hidden()

    # Undo takes back the coach's last change, never the start.
    page.locator('#liveUndoBtn').click()
    wait_for_field(page, coachboard_url, game_id, SWAPPED)
    assert 'Inning Started' in _kinds(page, coachboard_url, game_id)


def test_cancel_saves_nothing_and_leaves_the_field(page: Page, coachboard_url, asking):
    game_id = asking
    _swap(page, 'Shortstop Shawn')
    _answer(page, 'Cancel change')
    _no_change_saved(page, coachboard_url, game_id, BASE, [])
    quick = page.locator('#cbQuickDefense')
    expect(quick.locator(field_player('2B'))).to_contain_text('Second Sam')
    expect(quick.locator(field_player('SS'))).to_contain_text('Shortstop Shawn')


# --- A single move -------------------------------------------------------------------------------

@pytest.fixture
def open_lf(page: Page, coachboard_url, asking):
    """LF open before the 1st (a setup edit), so a bench player can go straight in."""
    game_id = asking
    state = live_state(page, coachboard_url, game_id)
    response = page.request.post(
        f'{coachboard_url}/api/live-game/{game_id}/defense-edit',
        data={'alignment': NO_LF, 'base_sequence': sequence(state), 'inning_started': False},
    )
    assert response.ok, response.text()[:300]
    expect(page.locator(f'#cbQuickDefense {field_player("LF")}')).to_contain_text('Open', timeout=10_000)
    return game_id


def test_a_single_move_asks_and_cancel_keeps_the_spot_open(page: Page, coachboard_url, open_lf):
    game_id = open_lf
    before = _kinds(page, coachboard_url, game_id)
    tap_move(page, bench_player(RELIEVER), 'LF')
    _answer(page, 'Cancel change')
    _no_change_saved(page, coachboard_url, game_id, NO_LF, before)
    expect(page.locator(f'#cbQuickDefense {field_player("LF")}')).to_contain_text('Open')


def test_a_single_move_with_yes_goes_in_after_the_start(page: Page, coachboard_url, open_lf):
    game_id = open_lf
    tap_move(page, bench_player(RELIEVER), 'LF')
    _answer(page, 'Yes, inning started')
    wait_for_field(page, coachboard_url, game_id, dict(NO_LF, LF=RELIEVER))
    assert _kinds(page, coachboard_url, game_id)[-2:] == ['Inning Started', 'Bulk Defensive Change']


# --- Change Pitcher ------------------------------------------------------------------------------

def test_change_pitcher_cancel_keeps_the_pitcher(page: Page, coachboard_url, asking):
    game_id = asking
    question = choose_new_pitcher(page, 'Shortstop Shawn')
    answer(question, 'Put Pitcher Pat at SS')
    _answer(page, 'Cancel change')
    _no_change_saved(page, coachboard_url, game_id, BASE, [])


def test_change_pitcher_not_yet_is_setup_not_a_pitching_change(page: Page, coachboard_url, asking):
    game_id = asking
    question = choose_new_pitcher(page, 'Shortstop Shawn')
    answer(question, 'Put Pitcher Pat at SS')
    _answer(page, 'Not yet')
    swapped = dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat')
    wait_for_field(page, coachboard_url, game_id, swapped)
    state = live_state(page, coachboard_url, game_id)
    change = [e for e in state['rotation_events'] if e['event_type'] == 'Pitcher Change'][0]
    assert change['pre_start'] is True
    # Pitching history: nobody changed pitchers during play.
    assert not [e for e in state['gameplay_events'] if e['event_type'] == 'Pitcher Change']


def test_change_pitcher_yes_is_a_pitching_change_during_the_inning(page: Page, coachboard_url, asking):
    game_id = asking
    question = choose_new_pitcher(page, 'Shortstop Shawn')
    answer(question, 'Put Pitcher Pat at SS')
    _answer(page, 'Yes, inning started')
    wait_for_field(page, coachboard_url, game_id, dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat'))
    state = live_state(page, coachboard_url, game_id)
    assert [e['event_type'] for e in state['gameplay_events']] == ['Pitcher Change']
    assert _kinds(page, coachboard_url, game_id) == ['Inning Started', 'Pitcher Change']


# --- Several changes waiting on one question ----------------------------------------------------

def test_one_cancel_abandons_every_change_waiting_on_the_question(page: Page, coachboard_url, asking):
    game_id = asking
    base = sequence(live_state(page, coachboard_url, game_id))
    results = page.evaluate(
        """async ([gameId, base, first, second]) => {
          const post = alignment => fetch(`/api/live-game/${gameId}/defense-edit`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({alignment, base_sequence: base}),
          }).then(r => r.json());
          const pending = [post(first), post(second)];
          // Both are waiting on the same sheet.
          while (!document.querySelector('#cbInningStartModal.show')) {
            await new Promise(r => setTimeout(r, 50));
          }
          await new Promise(r => setTimeout(r, 300));
          const sheets = document.querySelectorAll('#cbInningStartModal').length;
          document.querySelector('#cbInningStartModal [data-cb-inning-start="cancel"]').click();
          return {sheets, answers: (await Promise.all(pending)).map(d => d.code)};
        }""",
        [game_id, base, SWAPPED, NO_LF],
    )
    assert results == {'sheets': 1, 'answers': ['inning_start_cancelled', 'inning_start_cancelled']}
    _no_change_saved(page, coachboard_url, game_id, BASE, [])
