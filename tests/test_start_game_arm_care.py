"""Start Game with no game pitching rules and a starter whose arm needs rest.

Without game rules every starter is "can't confirm" and Start asks "Pitching
rules aren't selected". That question alone never said the team's arm-care
check had the starter resting, so a coach could start a resting pitcher
without ever seeing why. Start now says it in the same question, and the
coach's answer counts only for exactly that wording (and is logged with it).
Pregame planning stays non-blocking (tests/e2e/test_prepare_game_coach_flow.py).
"""

import pytest

from test_start_game_contract import FULL, GAME_ID, _app, _client, _live, _start  # noqa: F401 (_app is a fixture)
from test_start_game_pitching import _answer, _decision_log, _outing, _rules

ARM_CARE = 'Arm care (MLB Pitch Smart): Resting.'


@pytest.fixture
def resting_without_rules(app):
    from test_start_game_contract import _plan
    _plan(app, {'1': FULL})
    _rules(app, None)
    _outing(app, 1, pitches=70)  # Alex threw 70 game pitches yesterday
    return app


def test_start_names_the_arm_care_concern_with_the_missing_rules(resting_without_rules):
    status, question = _start(resting_without_rules, inning_one=FULL)

    assert status == 409
    assert question['code'] == 'start_no_pitching_rules'
    assert question['eligibility_heading'] == "Pitching rules aren't selected"
    assert question['eligibility_message'].startswith(
        "CoachBoard can't confirm Alex's pitching eligibility without the game rules. " + ARM_CARE)
    assert '70 game pitches' in question['eligibility_message']
    assert 'Next available:' in question['eligibility_message']
    assert question['arm_care_concern'].startswith(ARM_CARE)
    # The answer is tied to wording that includes the concern.
    assert ARM_CARE in question['decision_reason']
    assert not _live(resting_without_rules)


def test_an_answer_given_without_seeing_the_arm_care_concern_is_asked_again(resting_without_rules):
    _, question = _start(resting_without_rules, inning_one=FULL)
    unseen = dict(_answer(question))
    unseen['pitching_decision_reason'] = unseen['pitching_decision_reason'].split(' Arm care')[0]

    status, again = _start(resting_without_rules, inning_one=FULL, **unseen)

    assert status == 409 and again['code'] == 'start_no_pitching_rules'
    assert again['decision_outdated'] is True
    assert not _live(resting_without_rules)


def test_starting_after_seeing_it_is_logged_with_the_arm_care_concern(resting_without_rules):
    _, question = _start(resting_without_rules, inning_one=FULL)

    status, body = _start(resting_without_rules, inning_one=FULL, **_answer(question))

    assert status == 200, body
    assert _live(resting_without_rules)
    (entry,) = _decision_log(resting_without_rules)
    assert entry.startswith(f'no_rules_acknowledged: game {GAME_ID}, Start Game (inning 1), pitcher Alex;')
    assert ARM_CARE in entry


def test_no_arm_care_concern_keeps_the_rules_question_as_it_was(app):
    from test_start_game_contract import _plan
    _plan(app, {'1': FULL})
    _rules(app, None)

    _, question = _start(app, inning_one=FULL)

    assert question['eligibility_message'] == (
        "CoachBoard can't confirm Alex's pitching eligibility without the game rules.")
    assert 'arm_care_concern' not in question


def test_planning_reports_the_concern_without_blocking(resting_without_rules):
    readiness = _client(resting_without_rules).get(f'/api/game-day/{GAME_ID}/readiness').get_json()
    assert readiness['ready'] is True          # Start is usable; it asks there
    assert readiness['pitching_rules_selected'] is False
    summary = _client(resting_without_rules).get(f'/api/live-game/{GAME_ID}/state').get_json()['pitch_count_summary']['Alex']
    assert summary['arm_care_status'] == 'Resting'
