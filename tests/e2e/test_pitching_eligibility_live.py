"""Pitching eligibility from real pitching history, across every live screen.

CoachBoard informs; the coach decides. Earlier games give the roster real
history under MLB Pitch Smart:

* yesterday Shawn threw 70 pitches -> "Resting": a rule conflict. CoachBoard
  says which rule set and why, and the coach may use Shawn only by an
  explicit, deliberate override;
* two days ago Theo pitched but no pitch count was entered ->
  "Pitch Count Incomplete": CoachBoard can't confirm either way, so the coach
  confirms they verified Theo's eligibility (a different decision);
* this morning Casey threw 15 pitches in another game -> Pitch Smart
  recommends against a second game today: an advisory, one Continue.

In today's game a pitcher taken off the mound is flagged if brought back
(Pitch Smart 9-12, and USSSA) -- a rule conflict, overridable explicitly.
USSSA games check its innings limits instead of any same-day rule.

Change Pitcher, Next Inning and End Inning must all agree, and the old
generic pitch_anyway flag lets nobody in.
"""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect

from test_next_inning_save_race import cleanup_game, login, post_json


PHONE = {'width': 430, 'height': 932}
GAME_DAY = date.today() + timedelta(days=30)
RULES = 'MLB Pitch Smart'

BASE = {
    'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
    '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
    'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
}

OVERRIDE_CONFIRM = (
    'CoachBoard believes this may violate the selected MLB Pitch Smart rules. '
    "Continue only if you have verified the tournament's rules or are "
    'intentionally overriding this warning.'
)


def filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def create_game(page: Page, url: str, day: date, pitcher: str, opponent: str, rules=RULES):
    response = page.request.post(
        f'{url}/game-day/add',
        form={
            'game_date': day.isoformat(),
            'game_start_time': '10:00',
            'game_opponent': opponent,
            'game_location': 'Eligibility Field',
            'pitching_rule_set': rules,
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
    lineup = dict(BASE)
    if pitcher != 'Pitcher Pat':
        old_spot = next(pos for pos, name in BASE.items() if name == pitcher)
        lineup['P'], lineup[old_spot] = pitcher, 'Pitcher Pat'
    post_json(page, url, '/save_rotation', {
        'title': f'{opponent} Plan',
        'innings': {'1': lineup, '2': lineup},
        'associated_game_id': game_id,
    })
    post_json(page, url, f'/api/live-game/{game_id}/start', {})
    return game_id


def finish_game(page: Page, url: str, game_id: int, pitcher: str, pitches, innings='3'):
    roster = page.request.get(f'{url}/api/roster').json()
    player_id = next(p['id'] for p in roster if p['name'] == pitcher)
    response = page.request.post(
        f'{url}/api/live-game/{game_id}/end-with-pitching',
        data={
            'end_reason': 'manual',
            'current_inning_played': True,
            'counts': [{'player_id': player_id, 'pitches': pitches, 'innings': innings}],
        },
    )
    assert response.ok, response.text()[:300]


def live_state(page: Page, url: str, game_id: int):
    response = page.request.get(f'{url}/api/live-game/{game_id}/state')
    assert response.ok, response.text()[:300]
    return response.json()


@pytest.fixture
def game_with_history(page: Page, coachboard_url: str):
    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    games = []
    try:
        yesterday = create_game(
            page, coachboard_url, GAME_DAY - timedelta(days=1),
            'Shortstop Shawn', 'Yesterday Opponent',
        )
        games.append(yesterday)
        finish_game(page, coachboard_url, yesterday, 'Shortstop Shawn', 70)

        two_days_ago = create_game(
            page, coachboard_url, GAME_DAY - timedelta(days=2),
            'Third Theo', 'Two Days Ago Opponent',
        )
        games.append(two_days_ago)
        finish_game(page, coachboard_url, two_days_ago, 'Third Theo', '')

        this_morning = create_game(
            page, coachboard_url, GAME_DAY, 'Center Casey', 'Morning Opponent',
        )
        games.append(this_morning)
        finish_game(page, coachboard_url, this_morning, 'Center Casey', 15)

        today = create_game(page, coachboard_url, GAME_DAY, 'Pitcher Pat', 'Today Opponent')
        games.append(today)

        summary = live_state(page, coachboard_url, today)['pitch_count_summary']
        assert summary['Shortstop Shawn']['status'] == 'Resting'
        assert summary['Third Theo']['status'].endswith('Pitch Count Incomplete')
        assert summary['Center Casey']['status'] == 'Same-Day Game Advisory'
        assert summary['Left Lee']['status'] == 'Available'

        page.goto(f'{coachboard_url}/game/{today}', wait_until='domcontentloaded')
        expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        yield today
    finally:
        for game_id in reversed(games):
            cleanup_game(page, coachboard_url, game_id)


def open_picker(page: Page):
    page.locator('#liveChangePitcherBtn').click()
    picker = page.locator('#live-pitcher-picker-v2')
    expect(picker).to_be_visible(timeout=10_000)
    return picker


def pitcher_changes(state):
    return [
        e for e in state.get('rotation_events', [])
        if e.get('event_type') == 'Pitcher Change' and not e.get('reverted')
    ]


def watch_posts(page: Page, fragment: str):
    posts = []
    page.on(
        'request',
        lambda r: posts.append(r.post_data_json)
        if r.method == 'POST' and fragment in r.url else None,
    )
    return posts


def test_live_state_carries_the_shared_classification(
    page: Page, coachboard_url, game_with_history
):
    summary = live_state(page, coachboard_url, game_with_history)['pitch_count_summary']
    shawn = summary['Shortstop Shawn']
    assert shawn['eligibility'] == 'rule_conflict'
    assert shawn['required_decision'] == 'rule_override'
    assert shawn['rule_set'] == 'MLB Pitch Smart'
    assert shawn['eligibility_message'].startswith('MLB Pitch Smart: Resting. 70 game pitches')
    assert shawn['override_confirm'] == OVERRIDE_CONFIRM
    assert summary['Third Theo']['eligibility'] == 'unknown'
    assert summary['Third Theo']['required_decision'] == 'eligibility_verified'
    assert summary['Center Casey']['eligibility'] == 'advisory'
    assert summary['Center Casey']['required_decision'] == 'advisory_acknowledged'
    assert summary['Left Lee']['eligibility'] == 'ready'


# ---------------------------------------------------------- Change Pitcher


def test_change_pitcher_rest_is_a_rule_conflict_the_coach_can_override(
    page: Page, coachboard_url, game_with_history
):
    game_id = game_with_history
    posts = watch_posts(page, 'complete-pitcher-change')

    picker = open_picker(page)
    shawn = picker.locator('.pitcher-choice-v2', has_text='Shortstop Shawn')
    expect(shawn).to_contain_text('Resting')
    expect(shawn).to_contain_text('Rule conflict')

    # The warning names the rule set and the reason.
    shawn.click()
    expect(picker.locator('[data-eligibility-heading]')).to_have_text(
        'Shortstop Shawn appears ineligible to pitch'
    )
    expect(picker.locator('[data-eligibility-reason]')).to_contain_text(
        'MLB Pitch Smart: Resting. 70 game pitches'
    )
    expect(picker.locator('[data-pitching-decision="eligibility_verified"]')).to_have_count(0)

    # Use Anyway asks again, deliberately; Cancel changes nothing.
    picker.get_by_role('button', name='Use Shortstop Anyway').click()
    expect(picker.locator('[data-eligibility-heading]')).to_have_text('Override pitching rule?')
    expect(picker.locator('[data-eligibility-reason]')).to_contain_text('MLB Pitch Smart: Resting.')
    expect(picker.locator('[data-override-confirm-text]')).to_have_text(OVERRIDE_CONFIRM)
    picker.get_by_role('button', name='Cancel').click()
    expect(picker.locator('.pitcher-choice-v2', has_text='Shortstop Shawn')).to_be_visible()
    page.wait_for_timeout(300)
    assert posts == []
    assert pitcher_changes(live_state(page, coachboard_url, game_id)) == []

    # The explicit override, then the outgoing pitcher's destination.
    picker.locator('.pitcher-choice-v2', has_text='Shortstop Shawn').click()
    picker.get_by_role('button', name='Use Shortstop Anyway').click()
    picker.get_by_role('button', name='Use Shortstop Anyway').click()
    question = page.locator('#live-pitcher-destination-v7')
    expect(question).to_be_visible(timeout=10_000)
    question.get_by_role('button', name='Put Pitcher Pat at SS', exact=True).click()

    expect(page.locator('#cbDugoutHeader [data-cb-pitcher]')).to_contain_text(
        'Shortstop Shawn', timeout=10_000
    )
    assert posts[-1]['pitching_decision'] == 'rule_override'
    assert posts[-1]['pitching_decision_status'] == 'Resting'
    assert 'pitch_anyway' not in posts[-1]
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat')
    assert len(pitcher_changes(state)) == 1


def test_change_pitcher_unknown_needs_verification_not_an_override(
    page: Page, coachboard_url, game_with_history
):
    game_id = game_with_history
    posts = watch_posts(page, 'complete-pitcher-change')

    picker = open_picker(page)
    theo = picker.locator('.pitcher-choice-v2', has_text='Third Theo')
    expect(theo).to_contain_text("Can't confirm")
    theo.click()
    expect(picker.locator('[data-eligibility-heading]')).to_have_text(
        "CoachBoard can't confirm Third Theo's eligibility"
    )
    expect(picker).not_to_contain_text('appears ineligible')
    expect(picker.locator('[data-override-step]')).to_have_count(0)
    picker.get_by_role('button', name='Go Back').click()
    page.wait_for_timeout(300)
    assert posts == []

    theo.click()
    picker.get_by_role('button', name='I verified Third is eligible').click()
    question = page.locator('#live-pitcher-destination-v7')
    expect(question).to_be_visible(timeout=10_000)
    question.get_by_role('button', name='Put Pitcher Pat at 3B', exact=True).click()

    expect(page.locator('#cbDugoutHeader [data-cb-pitcher]')).to_contain_text(
        'Third Theo', timeout=10_000
    )
    assert posts[-1]['pitching_decision'] == 'eligibility_verified'
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == dict(BASE, P='Third Theo', **{'3B': 'Pitcher Pat'})
    assert len(pitcher_changes(state)) == 1


def test_old_pitch_anyway_cannot_bypass_the_warning(
    page: Page, coachboard_url, game_with_history
):
    game_id = game_with_history
    state = live_state(page, coachboard_url, game_id)
    shawn_id = next(p['id'] for p in state['roster'] if p['name'] == 'Shortstop Shawn')
    for flags in ({'pitch_anyway': True}, {'eligibility_verified': True}):
        response = page.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/complete-pitcher-change',
            data={
                'base_sequence': 0, 'fast': True, 'new_pitcher_id': shawn_id,
                'alignment': dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat'),
                **flags,
            },
        )
        assert response.status == 409
        assert response.json()['code'] == 'pitcher_rule_conflict'
        assert response.json()['required_decision'] == 'rule_override'
    # The deprecated route has no decision path at all.
    response = page.request.post(
        f'{coachboard_url}/api/live-game/{game_id}/change-pitcher',
        data={'base_sequence': 0, 'new_pitcher_id': shawn_id, 'pitch_anyway': True},
    )
    assert response.status == 409, response.text()
    assert response.json().get('code') == 'pitcher_rule_conflict', response.text()
    assert response.json()['message'].endswith('Refresh CoachBoard to decide on this warning.')
    assert pitcher_changes(live_state(page, coachboard_url, game_id)) == []


# ------------------------------------------------ Next Inning / End Inning


def open_next(page: Page):
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator('#live-board-prep-v3')
    expect(board.locator('[data-next-position="P"]')).to_contain_text(
        'Pitcher Pat', timeout=10_000
    )
    return board


def wait_for_next_p(page, url, game_id, name):
    for _ in range(50):
        prep = page.request.get(f'{url}/api/live-game/{game_id}/next-inning-prep').json()
        if prep['confirmed']['alignment'].get('P') == name:
            return
        page.wait_for_timeout(200)
    raise AssertionError(f'Next Inning P never became {name}')


def test_next_inning_plans_a_flagged_pitcher_and_end_inning_decides(
    page: Page, coachboard_url, game_with_history
):
    game_id = game_with_history
    posts = watch_posts(page, 'advance-inning')
    board = open_next(page)
    sheet = page.locator('#cbNextPitchingChange')

    # Planning Shawn is allowed: only the destination question, with the
    # rule conflict shown -- no extra confirmation while arranging.
    board.locator('[data-next-position="SS"]').click()
    board.locator('[data-next-position="P"]').click()
    expect(sheet).to_be_visible(timeout=5_000)
    expect(sheet).to_contain_text('Where should Pitcher Pat go?')
    expect(sheet).to_contain_text('Rule conflict')
    expect(sheet).to_contain_text('MLB Pitch Smart: Resting.')
    sheet.get_by_role('button', name='Put Pitcher Pat at SS', exact=True).click()
    wait_for_next_p(page, coachboard_url, game_id, 'Shortstop Shawn')
    status = board.locator('[data-next-pitcher-status]')
    expect(status).to_contain_text('Rule conflict')
    expect(status).to_contain_text('End Inning will ask you to decide')
    expect(status).to_have_class(re.compile(r'\brule_conflict\b'))

    # End Inning re-evaluates on the server and asks. Go Back / Cancel
    # change nothing.
    modal = page.locator('#cbPitchingDecisionModal')
    page.locator('#liveEndInningBtn').click()
    expect(modal).to_be_visible(timeout=15_000)
    expect(modal.locator('.modal-title')).to_have_text('Shortstop Shawn appears ineligible to pitch')
    expect(modal).to_contain_text('MLB Pitch Smart: Resting. 70 game pitches')
    modal.get_by_role('button', name='Go Back').click()
    expect(modal).to_be_hidden()

    page.locator('#liveEndInningBtn').click()
    expect(modal).to_be_visible(timeout=15_000)
    modal.get_by_role('button', name='Use Shortstop Anyway').click()
    expect(modal.locator('.modal-title')).to_have_text('Override pitching rule?')
    expect(modal).to_contain_text('MLB Pitch Smart: Resting.')
    expect(modal).to_contain_text(OVERRIDE_CONFIRM)
    modal.get_by_role('button', name='Cancel').click()
    expect(modal).to_be_hidden()
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'

    # The override: honored for this End Inning without asking again.
    page.locator('#liveEndInningBtn').click()
    expect(modal).to_be_visible(timeout=15_000)
    modal.get_by_role('button', name='Use Shortstop Anyway').click()
    modal.get_by_role('button', name='Use Shortstop Anyway').click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    state = live_state(page, coachboard_url, game_id)
    assert state['current_alignment']['P'] == 'Shortstop Shawn'
    decided = [p for p in posts if p.get('pitching_decision')]
    assert len(decided) == 1
    assert decided[0]['pitching_decision'] == 'rule_override'
    assert decided[0]['pitching_decision_status'] == 'Resting'


def test_end_inning_unknown_asks_for_verification(
    page: Page, coachboard_url, game_with_history
):
    game_id = game_with_history
    board = open_next(page)
    sheet = page.locator('#cbNextPitchingChange')

    board.locator('[data-next-position="3B"]').click()
    board.locator('[data-next-position="P"]').click()
    expect(sheet).to_be_visible(timeout=5_000)
    expect(sheet).to_contain_text("Can't confirm")
    sheet.get_by_role('button', name='Put Pitcher Pat at 3B', exact=True).click()
    wait_for_next_p(page, coachboard_url, game_id, 'Third Theo')
    expect(board.locator('[data-next-pitcher-status]')).to_contain_text("Can't confirm")

    modal = page.locator('#cbPitchingDecisionModal')
    page.locator('#liveEndInningBtn').click()
    expect(modal).to_be_visible(timeout=15_000)
    expect(modal.locator('.modal-title')).to_have_text(
        "CoachBoard can't confirm Third Theo's eligibility"
    )
    modal.get_by_role('button', name='Cancel').click()
    expect(modal).to_be_hidden()
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'

    page.locator('#liveEndInningBtn').click()
    expect(modal).to_be_visible(timeout=15_000)
    modal.get_by_role('button', name='I verified Third is eligible').click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    assert live_state(page, coachboard_url, game_id)['current_alignment']['P'] == 'Third Theo'


def test_continuing_pitcher_is_not_rechecked(
    page: Page, coachboard_url, game_with_history
):
    """Pat carrying into the next inning is not a new pitcher (current rule)."""
    game_id = game_with_history
    page.locator('#liveEndInningBtn').click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    expect(page.locator('#cbPitchingDecisionModal')).not_to_be_visible()
    assert live_state(page, coachboard_url, game_id)['current_alignment']['P'] == 'Pitcher Pat'


# ------------------------------------------------ Pitch Smart same-day advisory


def test_pitch_smart_second_game_today_is_an_advisory(
    page: Page, coachboard_url, game_with_history
):
    game_id = game_with_history
    posts = watch_posts(page, 'complete-pitcher-change')

    picker = open_picker(page)
    casey = picker.locator('.pitcher-choice-v2', has_text='Center Casey')
    expect(casey).to_contain_text('Advisory')
    expect(casey).not_to_contain_text('Rule conflict')
    casey.click()
    expect(picker.locator('[data-eligibility-heading]')).to_have_text(
        'Center Casey is eligible — please read this first'
    )
    expect(picker).to_contain_text(
        'Pitch Smart recommends that players not pitch in multiple games on the same day.'
    )
    expect(picker.locator('[data-override-step]')).to_have_count(0)
    # One confirmation is enough.
    picker.get_by_role('button', name='Continue with Center').click()

    question = page.locator('#live-pitcher-destination-v7')
    expect(question).to_be_visible(timeout=10_000)
    question.get_by_role('button', name='Put Pitcher Pat at CF', exact=True).click()
    expect(page.locator('#cbDugoutHeader [data-cb-pitcher]')).to_contain_text(
        'Center Casey', timeout=10_000
    )
    assert posts[-1]['pitching_decision'] == 'advisory_acknowledged'
    assert live_state(page, coachboard_url, game_id)['current_alignment']['P'] == 'Center Casey'


# ------------------------------------------------------------------ re-entry


def take_pat_off_the_mound(page: Page, url: str, game_id: int):
    """Frank comes in to pitch; Pat moves to first base (a real change)."""
    state = live_state(page, url, game_id)
    frank = next(p['id'] for p in state['roster'] if p['name'] == 'First Frank')
    post_json(page, url, f'/api/live-game/{game_id}/complete-pitcher-change', {
        'base_sequence': 0, 'fast': True, 'new_pitcher_id': frank,
        'alignment': dict(BASE, P='First Frank', **{'1B': 'Pitcher Pat'}),
    })


REENTRY = (
    'Pitcher Pat already pitched and was removed from the mound. '
    'MLB Pitch Smart rules indicate Pitcher Pat cannot return to pitch in '
    'this game.'
)


def test_removed_pitcher_is_flagged_everywhere_and_overridable_explicitly(
    page: Page, coachboard_url, game_with_history
):
    game_id = game_with_history
    take_pat_off_the_mound(page, coachboard_url, game_id)

    summary = live_state(page, coachboard_url, game_id)['pitch_count_summary']
    assert summary['Pitcher Pat']['status'] == 'Already Pitched This Game'
    assert summary['Pitcher Pat']['eligibility'] == 'rule_conflict'
    assert summary['Pitcher Pat']['eligibility_message'] == REENTRY

    # Next Inning: Pat can be planned at P; the board says why it's flagged.
    page.reload(wait_until='domcontentloaded')
    expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
    board = page.locator('#live-board-prep-v3')
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    expect(board.locator('[data-next-position="1B"]')).to_contain_text('Pitcher Pat', timeout=10_000)
    board.locator('[data-next-position="1B"]').click()
    board.locator('[data-next-position="P"]').click()
    sheet = page.locator('#cbNextPitchingChange')
    expect(sheet).to_be_visible(timeout=5_000)
    expect(sheet).to_contain_text('removed from the mound')
    sheet.get_by_role('button', name='Put First Frank at 1B', exact=True).click()
    wait_for_next_p(page, coachboard_url, game_id, 'Pitcher Pat')
    expect(board.locator('[data-next-pitcher-status]')).to_contain_text('Rule conflict')

    # The server: old flags and a mere verification are not an override.
    state = live_state(page, coachboard_url, game_id)
    prep = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep').json()
    sequence = max(int(e['sequence']) for e in state['rotation_events'] if not e.get('reverted'))
    for flags in (
        {},
        {'pitch_anyway': True, 'eligibility_verified': True},
        {'pitching_decision': 'eligibility_verified',
         'pitching_decision_status': 'Already Pitched This Game'},
    ):
        response = page.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/advance-inning',
            data={
                'alignment': prep['confirmed']['alignment'],
                'next_prep_id': prep['confirmed']['id'],
                'base_sequence': sequence,
                **flags,
            },
        )
        assert response.status == 409
        assert response.json()['code'] == 'pitcher_rule_conflict'
        assert response.json()['eligibility_message'] == REENTRY
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'

    # End Inning: the re-entry warning, then the explicit override.
    modal = page.locator('#cbPitchingDecisionModal')
    page.locator('#liveEndInningBtn').click()
    expect(modal).to_be_visible(timeout=15_000)
    expect(modal).to_contain_text(REENTRY)
    modal.get_by_role('button', name='Use Pitcher Anyway').click()
    expect(modal.locator('.modal-title')).to_have_text('Override pitching rule?')
    modal.get_by_role('button', name='Use Pitcher Anyway').click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    assert live_state(page, coachboard_url, game_id)['current_alignment']['P'] == 'Pitcher Pat'


def test_change_pitcher_shows_reentry_as_a_rule_conflict(
    page: Page, coachboard_url, game_with_history
):
    game_id = game_with_history
    take_pat_off_the_mound(page, coachboard_url, game_id)
    page.reload(wait_until='domcontentloaded')
    expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)

    picker = open_picker(page)
    pat = picker.locator('.pitcher-choice-v2', has_text='Pitcher Pat')
    expect(pat).to_contain_text('Rule conflict')
    pat.click()
    expect(picker.locator('[data-eligibility-reason]')).to_have_text(REENTRY)
    picker.get_by_role('button', name='Use Pitcher Anyway').click()
    expect(picker.locator('[data-eligibility-reason]')).to_have_text(REENTRY)
    picker.get_by_role('button', name='Use Pitcher Anyway').click()
    question = page.locator('#live-pitcher-destination-v7')
    expect(question).to_be_visible(timeout=10_000)
    question.get_by_role('button', name='Put First Frank at 1B', exact=True).click()
    expect(page.locator('#cbDugoutHeader [data-cb-pitcher]')).to_contain_text(
        'Pitcher Pat', timeout=10_000
    )
    assert live_state(page, coachboard_url, game_id)['current_alignment']['P'] == 'Pitcher Pat'


# ------------------------------------------------------------------- USSSA


def test_usssa_uses_innings_limits_not_a_same_day_rule(
    page: Page, coachboard_url: str
):
    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    day = date.today() + timedelta(days=40)
    games = []
    try:
        # Two morning games: Riley throws 6.0 IP (the 12U daily limit),
        # Casey 2.0 IP.
        morning = create_game(page, coachboard_url, day, 'Right Riley', 'USSSA Morning', rules='USSSA')
        games.append(morning)
        finish_game(page, coachboard_url, morning, 'Right Riley', 80, innings='6')
        midday = create_game(page, coachboard_url, day, 'Center Casey', 'USSSA Midday', rules='USSSA')
        games.append(midday)
        finish_game(page, coachboard_url, midday, 'Center Casey', 30, innings='2')

        today = create_game(page, coachboard_url, day, 'Pitcher Pat', 'USSSA Evening', rules='USSSA')
        games.append(today)
        summary = live_state(page, coachboard_url, today)['pitch_count_summary']
        assert summary['Right Riley']['status'] == 'Ineligible'
        assert summary['Right Riley']['eligibility'] == 'rule_conflict'
        assert summary['Right Riley']['eligibility_message'].startswith('USSSA: Ineligible.')
        assert summary['Center Casey']['status'] == 'Available'
        assert summary['Center Casey']['eligibility'] == 'ready'

        page.goto(f'{coachboard_url}/game/{today}', wait_until='domcontentloaded')
        expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        picker = open_picker(page)
        riley = picker.locator('.pitcher-choice-v2', has_text='Right Riley')
        expect(riley).to_contain_text('Rule conflict')
        riley.click()
        expect(picker.locator('[data-eligibility-reason]')).to_contain_text('USSSA: Ineligible.')
        picker.get_by_role('button', name='Use Right Anyway').click()
        expect(picker.locator('[data-override-confirm-text]')).to_contain_text(
            'CoachBoard believes this may violate the selected USSSA rules.'
        )
        picker.get_by_role('button', name='Cancel').click()

        # Within the limits, a second game the same day is allowed.
        casey = picker.locator('.pitcher-choice-v2', has_text='Center Casey')
        expect(casey).to_contain_text('Ready')
        expect(casey).not_to_contain_text('Advisory')
        casey.click()
        question = page.locator('#live-pitcher-destination-v7')
        expect(question).to_be_visible(timeout=10_000)
        question.get_by_role('button', name='Put Pitcher Pat at CF', exact=True).click()
        expect(page.locator('#cbDugoutHeader [data-cb-pitcher]')).to_contain_text(
            'Center Casey', timeout=10_000
        )
    finally:
        for game_id in reversed(games):
            cleanup_game(page, coachboard_url, game_id)
