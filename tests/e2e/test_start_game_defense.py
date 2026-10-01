"""Start Game, Part 1, in the browser: the coach decides open positions, and
the game starts with exactly the 1st-inning defense the coach reviewed.

* A data problem disables Start with a specific reason.
* An open fielding position leaves Start usable; Start asks
  ("Fix 1st Inning Defense" / "Start with CF Open").
* Start waits for a pending defense save, refuses while a save has failed,
  and refuses a 1st inning that changed underneath the coach.
* "Start with CF Open" also answers End Inning's "1st inning record has an
  open position" for that same field.
"""

import pytest

from test_set_defense_simplified import (  # noqa: F401 (make_page is a fixture)
    PANEL,
    _open_game,
    make_page,
)
from test_saved_defense_pitcher import setup  # noqa: F401 (fixture)
from test_next_inning_save_queue import live_state, open_on_the_field, slow_network

from playwright.sync_api import expect  # noqa: E402


pytestmark = pytest.mark.e2e

FULL = {'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam',
        '3B': 'Third Theo', 'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey',
        'RF': 'Right Riley'}
NO_CF = {pos: n for pos, n in FULL.items() if pos != 'CF'}
START = '#startLiveGameBtnAction'
SHEET = '#cbStartGameModal'


def _filled(alignment):
    return {pos: n for pos, n in (alignment or {}).items() if n}


def _open(setup, coachboard_url, inning_one):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': inning_one})
    _open_game(page, coachboard_url, game_id)
    expect(page.locator(START)).to_be_enabled(timeout=15_000)
    return page, game_id


def _is_live(page, url, game_id):
    return bool(live_state(page, url, game_id)['game']['is_live'])


def _sheet_button(page, label):
    return page.locator(SHEET).get_by_role('button', name=label, exact=True)


def test_a_complete_first_inning_starts(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, FULL)
    page.locator(START).click()
    page.wait_for_function(
        f"async () => (await (await fetch('/api/live-game/{game_id}/state')).json()).game.is_live",
        timeout=15_000,
    )
    assert _filled(live_state(page, coachboard_url, game_id)['current_alignment']) == FULL
    expect(page.locator(SHEET)).to_have_count(0)


def test_a_missing_pitcher_disables_start_with_the_reason(setup, coachboard_url):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': {pos: n for pos, n in FULL.items() if pos != 'P'}})
    _open_game(page, coachboard_url, game_id)
    expect(page.locator('#start-live-blockers')).to_contain_text(
        'Choose the starting pitcher for the 1st inning.', timeout=15_000
    )
    expect(page.locator(START)).to_be_disabled()
    expect(page.locator('#start-live-blockers')).not_to_contain_text('Finish the Inning 1 defense')


def test_an_open_position_asks_and_fix_does_not_start(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, NO_CF)
    expect(page.locator('#start-live-blockers')).to_contain_text('1st inning: CF is open')
    page.locator(START).click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('.modal-title')).to_have_text('1st inning: CF is open', timeout=10_000)
    expect(sheet).to_contain_text('CF is open for the 1st inning. On the bench:')
    _sheet_button(page, 'Fix 1st Inning Defense').click()
    expect(sheet).to_be_hidden(timeout=10_000)
    page.wait_for_timeout(500)
    assert not _is_live(page, coachboard_url, game_id)
    expect(page.locator(PANEL)).to_be_visible()


def test_start_with_cf_open_starts_with_exactly_that_defense(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, NO_CF)
    page.locator(START).click()
    _sheet_button(page, 'Start with CF Open').click()
    page.wait_for_function(
        f"async () => (await (await fetch('/api/live-game/{game_id}/state')).json()).game.is_live",
        timeout=15_000,
    )
    assert _filled(live_state(page, coachboard_url, game_id)['current_alignment']) == NO_CF


def test_ending_the_first_with_the_same_open_field_does_not_ask_again(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, NO_CF)
    page.locator(START).click()
    _sheet_button(page, 'Start with CF Open').click()
    page.wait_for_function(
        f"async () => (await (await fetch('/api/live-game/{game_id}/state')).json()).game.is_live",
        timeout=15_000,
    )
    page.reload(wait_until='domcontentloaded')
    page.locator('#liveEndInningBtn').click()
    # The 2nd inning's plan still has CF open, which End Inning asks about;
    # the 1st inning's record was already decided at first pitch.
    expect(page.locator('#cbIncompleteNextModal')).to_contain_text(
        'CF is open, and players are available on the bench.', timeout=15_000
    )
    expect(page.locator('#cbRecordedInningGapModal')).not_to_be_visible()


def test_a_field_changed_after_start_gets_the_normal_record_warning(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, NO_CF)
    page.locator(START).click()
    _sheet_button(page, 'Start with CF Open').click()
    page.wait_for_function(
        f"async () => (await (await fetch('/api/live-game/{game_id}/state')).json()).game.is_live",
        timeout=15_000,
    )
    open_on_the_field(page, coachboard_url, game_id, 'LF')
    page.reload(wait_until='domcontentloaded')
    page.locator('#liveEndInningBtn').click()
    expect(page.locator('#cbRecordedInningGapModal .modal-title')).to_have_text(
        '1st inning record has an open position', timeout=15_000
    )


def test_a_first_inning_changed_underneath_the_coach_is_refused(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, NO_CF)
    # What this tab shows differs from what is stored (as if another coach's
    # save had not reached this tab yet).
    page.evaluate("() => { window.CBPregameRotation.getRotation().innings['1'].CF = 'Relief Rex'; }")
    page.locator(START).click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('.modal-title')).to_have_text('1st inning defense changed', timeout=10_000)
    expect(sheet).to_contain_text('The 1st inning defense changed. Review it before starting.')
    _sheet_button(page, 'Review 1st Inning Defense').click()
    page.wait_for_timeout(500)
    assert not _is_live(page, coachboard_url, game_id)
    # The tab reloads the stored plan for the coach to review.
    page.wait_for_function("() => !window.CBPregameRotation.getRotation().innings['1'].CF", timeout=10_000)


def test_start_waits_for_a_pending_defense_save(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, NO_CF)
    slow_network(page, 1200)
    page.locator(f'{PANEL} [data-pde-pos="CF"]').click()
    page.locator('#pde-list .pde-choice[data-player="Relief Rex"]').click()
    expect(page.locator('#pde-player-modal')).to_be_hidden(timeout=10_000)
    # Start right away, while that save is still on the wire: no CF question,
    # and the game starts with the saved defense.
    page.locator(START).click()
    page.wait_for_function(
        f"async () => (await (await fetch('/api/live-game/{game_id}/state')).json()).game.is_live",
        timeout=30_000,
    )
    expect(page.locator(SHEET)).to_have_count(0)
    assert _filled(live_state(page, coachboard_url, game_id)['current_alignment']) == dict(NO_CF, CF='Relief Rex')


def test_a_failed_defense_save_prevents_start(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, NO_CF)
    page.route('**/save_rotation', lambda route: route.fulfill(
        status=500, content_type='application/json',
        body='{"status": "error", "message": "Server unavailable"}',
    ))
    page.locator(f'{PANEL} [data-pde-pos="CF"]').click()
    page.locator('#pde-list .pde-choice[data-player="Relief Rex"]').click()
    expect(page.locator(f'{PANEL} #pde-save-status')).to_contain_text('Save failed', timeout=10_000)
    page.locator(START).click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('.modal-title')).to_have_text("Your last change hasn't saved", timeout=10_000)
    _sheet_button(page, 'OK').click()
    page.wait_for_timeout(500)
    assert not _is_live(page, coachboard_url, game_id)


def test_the_start_button_sends_the_reviewed_first_inning(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, FULL)
    with page.expect_request(lambda r: r.method == 'POST' and r.url.endswith(f'/api/live-game/{game_id}/start')) as start:
        page.locator(START).click()
    assert _filled(start.value.post_data_json['inning_one']) == FULL
    page.wait_for_function(
        f"async () => (await (await fetch('/api/live-game/{game_id}/state')).json()).game.is_live",
        timeout=15_000,
    )


def test_a_tab_that_cannot_say_what_was_reviewed_is_asked_to_refresh(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, FULL)
    # As if this tab had no Pregame plan to send.
    page.evaluate("() => { window.CBPregameRotation.getRotation = () => ({}); }")
    page.locator(START).click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('.modal-title')).to_have_text('Refresh Prepare Game before starting.', timeout=10_000)
    expect(sheet).to_contain_text("CoachBoard needs to verify the 1st inning defense you're starting with.")
    assert not _is_live(page, coachboard_url, game_id)
    with page.expect_navigation():
        _sheet_button(page, 'Refresh').click()
    assert not _is_live(page, coachboard_url, game_id)
