"""Start Game, Part 2, in the browser: the starting pitcher question.

The server classifies the starter (tests/test_start_game_pitching.py covers
the real policy). Here the first /start response is replaced with each kind
of question the server sends, and the browser must ask the coach, then send
back exactly the decision the question named -- status, rule set and reason
included. The real starter is Ready, so the answered request, passed through
to the server, starts the game.
"""

import pytest

from test_set_defense_simplified import (  # noqa: F401 (make_page is a fixture)
    _open_game,
    make_page,
)
from test_saved_defense_pitcher import setup  # noqa: F401 (fixture)
from live_fixtures import live_state

from playwright.sync_api import expect  # noqa: E402


pytestmark = pytest.mark.e2e

FULL = {'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam',
        '3B': 'Third Theo', 'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey',
        'RF': 'Right Riley'}
START = '#startLiveGameBtnAction'
SHEET = '#cbStartGameModal'

QUESTIONS = {
    'advisory': {
        'code': 'pitcher_advisory', 'eligibility': 'advisory', 'required_decision': 'advisory_acknowledged',
        'eligibility_heading': 'Pitcher Pat is eligible — please read this first',
        'eligibility_message': 'Pitch Smart recommends against pitching in a second game today.',
        'pitching_status': 'Same-Day Game Advisory', 'decision_rule_set': 'MLB Pitch Smart',
    },
    'rule_conflict': {
        'code': 'pitcher_rule_conflict', 'eligibility': 'rule_conflict', 'required_decision': 'rule_override',
        'eligibility_heading': 'Pitcher Pat appears ineligible to pitch',
        'eligibility_message': 'USSSA: Resting. Needs 1 day of rest.',
        'override_confirm': 'CoachBoard believes this may violate the selected USSSA rules.',
        'pitching_status': 'Resting', 'decision_rule_set': 'USSSA',
    },
    'unknown': {
        'code': 'pitcher_eligibility_unconfirmed', 'eligibility': 'unknown', 'required_decision': 'eligibility_verified',
        'eligibility_heading': "CoachBoard can't confirm Pitcher Pat's eligibility",
        'eligibility_message': "CoachBoard can't confirm Pitcher Pat's pitching eligibility (Innings Incomplete).",
        'pitching_status': 'Unavailable — Innings Incomplete', 'decision_rule_set': 'USSSA',
    },
    'no_rules': {
        'code': 'start_no_pitching_rules', 'eligibility': 'unknown', 'required_decision': 'no_rules_acknowledged',
        'eligibility_heading': "Pitching rules aren't selected",
        'eligibility_message': "CoachBoard can't confirm Pitcher Pat's pitching eligibility without the game rules.",
        'pitching_status': 'Unavailable — Select Game Rules', 'decision_rule_set': 'the selected',
    },
}


def _question(kind, outdated=False):
    question = dict(QUESTIONS[kind])
    question.update({
        'status': 'error', 'pitcher': 'Pitcher Pat', 'ready': True, 'hard_stops': [],
        'missing': [], 'open_positions': [], 'open_question': None,
        'decision_reason': f"{question['eligibility_message']} (as shown)",
        'decision_outdated': outdated, 'message': question['eligibility_message'],
    })
    return question


def _ask_first(page, *questions):
    """Answer the first /start requests with these questions; pass the rest
    through to the server. Returns the request bodies sent."""
    sent = []
    queue = list(questions)

    def handle(route):
        sent.append(route.request.post_data_json)
        if queue:
            route.fulfill(status=409, json=queue.pop(0))
        else:
            route.continue_()

    page.route('**/api/live-game/*/start', handle)
    return sent


def _open(setup, coachboard_url):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': FULL})
    _open_game(page, coachboard_url, game_id)
    expect(page.locator(START)).to_be_enabled(timeout=15_000)
    return page, game_id


def _button(page, label):
    return page.locator(SHEET).get_by_role('button', name=label, exact=True)


def _wait_live(page, game_id):
    page.wait_for_function(
        f"async () => (await (await fetch('/api/live-game/{game_id}/state')).json()).game.is_live",
        timeout=15_000,
    )


def _is_live(page, url, game_id):
    return bool(live_state(page, url, game_id)['game']['is_live'])


def _decision_sent(body, kind):
    question = _question(kind)
    assert body['pitching_decision'] == question['required_decision']
    assert body['pitching_decision_status'] == question['pitching_status']
    assert body['pitching_decision_rule_set'] == question['decision_rule_set']
    assert body['pitching_decision_reason'] == question['decision_reason']
    assert body['inning_one']['P'] == 'Pitcher Pat'


@pytest.mark.parametrize('kind, answer', [
    ('advisory', 'Continue with Pitcher'),
    ('unknown', 'I verified Pitcher is eligible'),
])
def test_advisory_and_cant_confirm_ask_then_start(setup, coachboard_url, kind, answer):
    page, game_id = _open(setup, coachboard_url)
    sent = _ask_first(page, _question(kind))
    page.locator(START).click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('.modal-title')).to_have_text(QUESTIONS[kind]['eligibility_heading'], timeout=10_000)
    expect(sheet).to_contain_text(QUESTIONS[kind]['eligibility_message'])
    expect(_button(page, 'Choose Another Pitcher')).to_be_visible()
    _button(page, answer).click()
    _wait_live(page, game_id)
    assert 'pitching_decision' not in sent[0]
    _decision_sent(sent[1], kind)


def test_a_rule_conflict_needs_two_deliberate_steps(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url)
    sent = _ask_first(page, _question('rule_conflict'))
    page.locator(START).click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('.modal-title')).to_have_text('Pitcher Pat appears ineligible to pitch', timeout=10_000)
    expect(sheet).to_contain_text('USSSA: Resting. Needs 1 day of rest.')
    _button(page, 'Use Pitcher Anyway').click()
    expect(sheet.locator('.modal-title')).to_have_text('Override pitching rule?', timeout=10_000)
    expect(sheet).to_contain_text('may violate the selected USSSA rules')
    assert len(sent) == 1  # nothing sent until the second step
    _button(page, 'Use Pitcher Anyway').click()
    _wait_live(page, game_id)
    _decision_sent(sent[1], 'rule_conflict')


def test_cancelling_the_override_does_not_start(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url)
    sent = _ask_first(page, _question('rule_conflict'))
    page.locator(START).click()
    _button(page, 'Use Pitcher Anyway').click()
    expect(page.locator(f'{SHEET} .modal-title')).to_have_text('Override pitching rule?', timeout=10_000)
    _button(page, 'Cancel').click()
    expect(page.locator(SHEET)).to_be_hidden(timeout=10_000)
    page.wait_for_timeout(500)
    assert len(sent) == 1
    assert not _is_live(page, coachboard_url, game_id)


def test_no_rules_offers_choose_rules_or_start_without_rules(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url)
    sent = _ask_first(page, _question('no_rules'))
    page.locator(START).click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('.modal-title')).to_have_text("Pitching rules aren't selected", timeout=10_000)
    expect(sheet).to_contain_text(
        "CoachBoard can't confirm Pitcher Pat's pitching eligibility without the game rules."
    )
    expect(_button(page, 'Choose Rules')).to_be_visible()
    _button(page, 'Start Without Rules').click()
    _wait_live(page, game_id)
    _decision_sent(sent[1], 'no_rules')


def test_choose_rules_opens_the_game_rules_instead_of_starting(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url)
    sent = _ask_first(page, _question('no_rules'))
    page.locator(START).click()
    _button(page, 'Choose Rules').click()
    expect(page.locator('#game-pitch-rule-editor-v2')).to_be_visible(timeout=10_000)
    page.wait_for_timeout(300)
    assert len(sent) == 1
    assert not _is_live(page, coachboard_url, game_id)


def test_choose_another_pitcher_returns_to_p_selection(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url)
    sent = _ask_first(page, _question('advisory'))
    page.locator(START).click()
    _button(page, 'Choose Another Pitcher').click()
    expect(page.locator('#pde-player-modal .modal-title')).to_have_text('P — Choose Player', timeout=10_000)
    assert len(sent) == 1
    assert not _is_live(page, coachboard_url, game_id)


def test_a_changed_status_is_asked_again_with_the_new_wording(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url)
    sent = _ask_first(page, _question('unknown'), _question('rule_conflict', outdated=True))
    page.locator(START).click()
    _button(page, 'I verified Pitcher is eligible').click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('.modal-title')).to_have_text('Pitcher Pat appears ineligible to pitch', timeout=10_000)
    expect(sheet).to_contain_text("Pitcher Pat's pitching status changed.")
    _button(page, 'Use Pitcher Anyway').click()
    _button(page, 'Use Pitcher Anyway').click()
    _wait_live(page, game_id)
    _decision_sent(sent[1], 'unknown')
    _decision_sent(sent[2], 'rule_conflict')
