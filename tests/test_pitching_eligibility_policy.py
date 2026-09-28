"""Every eligibility status the pitch-count calculator produces, classified.

Real pitching histories run through utils.calculate_pitch_count_summary; the
shared policy (pitching_eligibility.classify) then decides whether the player
is ready, advisory, a rule conflict or unknown -- and which explicit coach
decision each one needs. Pitching rules inform; the coach decides.
"""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

import pitching_eligibility as policy
from utils import PITCHING_RULES, calculate_pitch_count_summary


GAME_DAY = date(2026, 9, 27)
PITCH_SMART_12U = dict(PITCHING_RULES['MLB Pitch Smart']['12U'], rule_set_name='MLB Pitch Smart')
USSSA_12U = dict(PITCHING_RULES['USSSA']['12U'], rule_set_name='USSSA')

PLAYER = SimpleNamespace(id=1, name='Graham')


def outing(days_ago, pitches=None, innings=None, game_id=None, kind='Game'):
    return SimpleNamespace(
        player_id=PLAYER.id,
        date=datetime.combine(GAME_DAY - timedelta(days=days_ago), datetime.min.time()),
        pitches=pitches,
        innings=innings,
        outing_type=kind,
        game_id=game_id,
    )


def status_for(outings, rules, current_game_id=99):
    item = calculate_pitch_count_summary(
        [PLAYER], outings, rules,
        target_date=GAME_DAY, current_game_id=current_game_id,
    )[PLAYER.name]
    return item['status'], policy.classify(item)


@pytest.mark.parametrize('outings, rules, status, kind', [
    # Ready.
    ([], PITCH_SMART_12U, 'Available', policy.READY),
    ([outing(5, pitches=30)], PITCH_SMART_12U, 'Available', policy.READY),
    # Practice throwing is workload, not an official restriction.
    ([outing(0, pitches=70, kind='Practice')], PITCH_SMART_12U, 'Available', policy.READY),

    # Pitch Smart rules the player appears to break.
    ([outing(1, pitches=66)], PITCH_SMART_12U, 'Resting', policy.RULE_CONFLICT),      # 3 days rest
    ([outing(1, pitches=10), outing(2, pitches=10)], PITCH_SMART_12U, 'Resting', policy.RULE_CONFLICT),  # 3rd day
    ([outing(0, pitches=85, game_id=99)], PITCH_SMART_12U, 'Resting', policy.RULE_CONFLICT),  # daily max
    # A second game today: Pitch Smart recommends against it (advisory)...
    ([outing(0, pitches=15, game_id=41)], PITCH_SMART_12U, 'Same-Day Game Advisory', policy.ADVISORY),
    # ...unless the selected rules prohibit it.
    ([outing(0, pitches=15, game_id=41)], dict(PITCH_SMART_12U, same_day_games_prohibited=True),
     'Same-Day Game Restriction', policy.RULE_CONFLICT),
    # USSSA has no same-day rule: within its innings limits a second game is fine.
    ([outing(0, innings=2.0, game_id=41)], USSSA_12U, 'Available', policy.READY),

    # Pitch Smart: history CoachBoard can't use.
    ([outing(2, pitches=None)], PITCH_SMART_12U, 'Pitch Count Incomplete', policy.UNKNOWN),

    # USSSA innings rules.
    ([outing(1, innings=3.1)], USSSA_12U, 'Resting', policy.RULE_CONFLICT),     # > 3 IP yesterday
    ([outing(1, innings=1.0), outing(2, innings=1.0), outing(3, innings=1.0)],
     USSSA_12U, 'Resting', policy.RULE_CONFLICT),                              # 3 straight days
    ([outing(0, innings=6.0, game_id=99)], USSSA_12U, 'Ineligible', policy.RULE_CONFLICT),  # daily outs
    ([outing(1, innings=None)], USSSA_12U, 'Innings Incomplete', policy.UNKNOWN),

    # A rule set CoachBoard can't evaluate.
    ([], {'rule_type': 'mystery'}, 'Verify Rules', policy.UNKNOWN),
], ids=[
    'no_history', 'rested', 'practice_only',
    'pitch_smart_rest_days', 'pitch_smart_third_day', 'pitch_smart_daily_max',
    'pitch_smart_second_game_today', 'second_game_prohibited_by_rules',
    'usssa_second_game_within_limits', 'pitch_smart_missing_counts',
    'usssa_over_3_ip_yesterday', 'usssa_three_days', 'usssa_daily_limit',
    'usssa_missing_innings', 'unsupported_rules',
])
def test_calculator_statuses_are_classified(outings, rules, status, kind):
    assert status_for(outings, rules) == (status, kind)


@pytest.mark.parametrize('status, kind', [
    # How game_pitching_rules presents them during a live game.
    ('Unavailable — Pitch Count Incomplete', policy.UNKNOWN),
    ('Unavailable — Innings Incomplete', policy.UNKNOWN),
    ('Unavailable — Verify Rules', policy.UNKNOWN),
    ('Unavailable — Eligibility Error', policy.UNKNOWN),
    ('Unavailable — Select Game Rules', policy.UNKNOWN),
    ('Unavailable — Eligibility Unknown', policy.UNKNOWN),
    ('Unavailable — Same-Day Game Restriction', policy.RULE_CONFLICT),
    ('Same-Day Game Advisory', policy.ADVISORY),
    ('Already Pitched This Game', policy.RULE_CONFLICT),
    ('Resting', policy.RULE_CONFLICT),
    ('Ineligible', policy.RULE_CONFLICT),
    # Never lighter than the strongest confirmation by accident.
    ('Something Nobody Has Invented Yet', policy.RULE_CONFLICT),
])
def test_live_statuses_are_classified(status, kind):
    assert policy.classify({'status': status}) == kind


def test_no_summary_at_all_is_unknown():
    assert policy.classify(None) == policy.UNKNOWN
    assert policy.classify({}) == policy.UNKNOWN
    assert policy.classify({'status': '  '}) == policy.UNKNOWN


def test_live_summary_carries_the_classification():
    summary = {
        'Graham': {'status': 'Available'},
        'Pat': {'status': 'Resting'},
        'Casey': {'status': 'Unavailable — Select Game Rules'},
        'Riley': {'status': 'Same-Day Game Advisory', 'advisory': True},
    }
    policy.annotate(summary)
    assert {name: item['eligibility'] for name, item in summary.items()} == {
        'Graham': policy.READY,
        'Pat': policy.RULE_CONFLICT,
        'Casey': policy.UNKNOWN,
        'Riley': policy.ADVISORY,
    }


def test_each_classification_needs_its_own_decision():
    assert policy.REQUIRED_DECISION == {
        policy.ADVISORY: 'advisory_acknowledged',
        policy.RULE_CONFLICT: 'rule_override',
        policy.UNKNOWN: 'eligibility_verified',
    }


def test_wording_names_the_rule_set_and_reason():
    resting = {'status': 'Resting', 'status_detail': '66 game pitches on Sun, Sep 27 require 3 day(s) rest.'}
    described = policy.describe('Graham', resting, USSSA_12U)
    assert described['eligibility'] == policy.RULE_CONFLICT
    assert described['required_decision'] == 'rule_override'
    assert described['eligibility_heading'] == 'Graham appears ineligible to pitch'
    assert described['eligibility_message'] == (
        'USSSA: Resting. 66 game pitches on Sun, Sep 27 require 3 day(s) rest.'
    )
    assert described['override_confirm'] == (
        'CoachBoard believes this may violate the selected USSSA rules. '
        "Continue only if you have verified the tournament's rules or are "
        'intentionally overriding this warning.'
    )


def test_unknown_wording_does_not_say_ineligible():
    described = policy.describe(
        'Graham', {'status': 'Unavailable — Pitch Count Incomplete'}, PITCH_SMART_12U
    )
    assert described['required_decision'] == 'eligibility_verified'
    assert described['eligibility_heading'] == "CoachBoard can't confirm Graham's eligibility"
    assert described['eligibility_message'] == (
        "CoachBoard can't confirm Graham's pitching eligibility "
        '(Pitch Count Incomplete).'
    )
    assert 'ineligible' not in ' '.join(described.values()).lower()
    assert 'override_confirm' not in described


def test_advisory_wording_is_a_recommendation():
    described = policy.describe('Graham', {
        'status': 'Same-Day Game Advisory', 'advisory': True,
        'status_detail': 'Pitch Smart recommends that players not pitch in multiple games on the same day.',
    }, PITCH_SMART_12U)
    assert described['required_decision'] == 'advisory_acknowledged'
    assert described['eligibility_heading'] == 'Graham is eligible — please read this first'
    assert described['eligibility_message'].startswith('Pitch Smart recommends')
    assert 'override_confirm' not in described


def test_ready_needs_no_decision():
    assert policy.describe('Graham', {'status': 'Available'}, USSSA_12U) == {'eligibility': policy.READY}
    assert policy.decision_accepted({'status': 'Available'}, None, None)


@pytest.mark.parametrize('item, decision, status, accepted', [
    ({'status': 'Resting'}, 'rule_override', 'Resting', True),
    # The wrong kind of decision is not enough...
    ({'status': 'Resting'}, 'eligibility_verified', 'Resting', False),
    ({'status': 'Resting'}, 'advisory_acknowledged', 'Resting', False),
    ({'status': 'Unavailable — Pitch Count Incomplete'}, 'rule_override', 'Pitch Count Incomplete', False),
    # ...nor a decision about a status the coach was not shown.
    ({'status': 'Already Pitched This Game'}, 'rule_override', 'Resting', False),
    ({'status': 'Unavailable — Pitch Count Incomplete'}, 'eligibility_verified',
     'Unavailable — Pitch Count Incomplete', True),
    ({'status': 'Same-Day Game Advisory', 'advisory': True}, 'advisory_acknowledged',
     'Same-Day Game Advisory', True),
    # No decision at all (the old pitch_anyway flag is not one).
    ({'status': 'Resting'}, None, None, False),
    (None, 'eligibility_verified', '', True),
], ids=[
    'override_rest', 'verify_is_not_override', 'ack_is_not_override',
    'override_is_not_verify', 'status_changed', 'verify_unknown',
    'ack_advisory', 'no_decision', 'no_summary_verified',
])
def test_decision_must_match_the_warning_shown(item, decision, status, accepted):
    assert policy.decision_accepted(item, decision, status) is accepted


# ------------------------------------------------------------------ re-entry


PITCH_SMART_AGES = [
    '7U', '8U', '9U', '10U', '11U', '12U', '13U', '14U', '15U', '16U',
    '17U', '18U', '19U', '20U', '21U', '22U',
]
EXPECTED_PITCH_SMART_REENTRY = {
    **{age: 'prohibited' for age in ('7U', '8U', '9U', '10U', '11U', '12U')},
    **{age: 'once_if_stayed_in' for age in ('13U', '14U', '15U', '16U', '17U', '18U')},
    **{age: 'unknown' for age in ('19U', '20U', '21U', '22U')},
}


def test_every_supported_pitch_smart_age_has_an_audited_reentry_rule():
    # Exactly the ages the Pitch Smart preset ships (plus its default).
    assert set(PITCHING_RULES['MLB Pitch Smart']) == set(PITCH_SMART_AGES) | {'default'}
    assert {
        age: policy.reentry_rule({'rule_set_name': 'MLB Pitch Smart', 'age_group': age})
        for age in PITCH_SMART_AGES
    } == EXPECTED_PITCH_SMART_REENTRY


@pytest.mark.parametrize('rules, rule', [
    # 4U-6U use the Pitch Smart 7-8 table, and its re-entry guidance.
    ({'rule_set_name': 'MLB Pitch Smart', 'age_group': '6U'}, 'prohibited'),
    ({'rule_set_name': 'MLB Pitch Smart', 'age_group': 'default'}, 'unknown'),
    ({'rule_set_name': 'USSSA', 'age_group': '12U'}, 'prohibited'),
    ({'rule_set_name': 'USSSA', 'age_group': '16U'}, 'prohibited'),
    # Presets that don't encode it: not guessed from the age.
    ({'rule_set_name': 'Little League Baseball', 'age_group': '12U'}, 'unknown'),
    ({'rule_set_name': 'Bullpen Tournaments', 'age_group': '12U'}, 'unknown'),
    ({'rule_set_name': 'Rules Not Selected', 'age_group': '12U'}, 'unknown'),
    # A preset can state it outright.
    ({'rule_set_name': 'Little League Baseball', 'age_group': '12U',
      'pitcher_reentry': 'prohibited'}, 'prohibited'),
    ({'rule_set_name': 'USSSA', 'age_group': '12U', 'pitcher_reentry': 'allowed'}, 'allowed'),
])
def test_reentry_rule_follows_the_preset(rules, rule):
    assert policy.reentry_rule(rules) == rule


@pytest.mark.parametrize('rules, rule', [
    ({'rule_set_name': 'MLB Pitch Smart', 'age_group': '12U'}, 'advisory'),
    ({'rule_set_name': 'MLB Pitch Smart', 'age_group': '16U'}, 'advisory'),
    ({'rule_set_name': 'MLB Pitch Smart', 'age_group': '12U',
      'same_day_games_prohibited': True}, 'prohibited'),
    ({'rule_set_name': 'USSSA', 'age_group': '12U'}, 'allowed'),
    ({'rule_set_name': 'Little League Baseball', 'age_group': '12U'}, 'unknown'),
    ({'rule_set_name': 'Bullpen Tournaments', 'age_group': '12U'}, 'unknown'),
    ({'rule_set_name': 'Little League Baseball', 'age_group': '12U',
      'same_day_games': 'prohibited'}, 'prohibited'),
])
def test_same_day_rule_follows_the_preset(rules, rule):
    assert policy.same_day_rule(rules) == rule


@pytest.mark.parametrize('preset', ['Little League Baseball', 'Bullpen Tournaments'])
def test_second_game_today_under_a_preset_that_does_not_say_is_unconfirmed(preset):
    rules = dict(PITCH_SMART_12U, rule_set_name=preset)
    status, kind = status_for([outing(0, pitches=15, game_id=41)], rules)
    assert (status, kind) == ('Same-Day Rule Unknown', policy.UNKNOWN)


FIELD = {'C': 'Cole', '1B': 'Frank', '2B': 'Sam', '3B': 'Theo', 'SS': 'Shawn',
         'LF': 'Lee', 'CF': 'Casey', 'RF': 'Riley'}


def field(pitcher, **moves):
    """A full field with `pitcher` at P; moves put players at positions."""
    alignment = dict(FIELD, P=pitcher)
    for position, name in moves.items():
        alignment[position] = name
    return alignment


def change(before, after, reverted=False):
    return SimpleNamespace(before_alignment=before, after_alignment=after, reverted=reverted)


def event(before_p, after_p, reverted=False):
    return SimpleNamespace(
        before_alignment={'P': before_p, 'SS': 'Somebody'},
        after_alignment={'P': after_p, 'SS': 'Somebody'},
        reverted=reverted,
    )


def test_removed_pitchers_come_from_this_games_history():
    history = [
        event('Graham', 'Graham'),       # innings 1-2: Graham pitching
        event('Graham', 'Pat'),          # Pat comes in; Graham to SS
        event('Pat', 'Casey', reverted=True),  # undone: Casey never pitched
    ]
    assert policy.pitchers_removed(history, current_pitcher='Pat') == {'Graham'}


def test_removed_pitcher_is_a_rule_conflict_with_the_reason():
    rules = {'rule_set_name': 'USSSA', 'age_group': '12U'}
    summary = {'Graham': {'status': 'Available'}, 'Pat': {'status': 'Available'}}
    policy.apply_reentry_rule(summary, rules, [event('Graham', 'Pat')], current_pitcher='Pat')
    graham = summary['Graham']
    assert graham['status'] == 'Already Pitched This Game'
    assert graham['eligibility'] == policy.RULE_CONFLICT
    assert policy.classify(graham) == policy.RULE_CONFLICT
    described = policy.describe('Graham', graham, rules)
    assert described['eligibility_message'] == (
        'Graham already pitched and was removed from the mound. USSSA rules '
        'indicate Graham cannot return to pitch in this game.'
    )
    # Overridable, deliberately: the coach decides.
    assert described['required_decision'] == 'rule_override'
    assert policy.decision_accepted(graham, 'rule_override', 'Already Pitched This Game')
    # The pitcher on the mound is not affected.
    assert summary['Pat']['status'] == 'Available'


@pytest.mark.parametrize('age', ['8U', '12U'])
def test_pitch_smart_8_and_under_and_9_to_12_prohibit_return(age):
    rules = {'rule_set_name': 'MLB Pitch Smart', 'age_group': age}
    summary = {'Graham': {'status': 'Available'}}
    # Graham pitched, moved to SS (stayed in the game): still not allowed back.
    history = [change(field('Graham'), field('Pat', SS='Graham'))]
    policy.apply_reentry_rule(summary, rules, history, 'Pat', field('Pat', SS='Graham'))
    assert summary['Graham']['status'] == 'Already Pitched This Game'
    assert summary['Graham']['eligibility'] == policy.RULE_CONFLICT


PS_14U = {'rule_set_name': 'MLB Pitch Smart', 'age_group': '14U'}


def test_pitch_smart_13_to_18_allows_one_return_after_staying_in():
    summary = {'Graham': {'status': 'Available'}}
    now = field('Pat', SS='Graham')
    history = [change(field('Graham'), now)]
    assert policy.mound_history(history, 'Graham', now) == (1, 0, False)
    policy.apply_reentry_rule(summary, PS_14U, history, 'Pat', now)
    # The one return is unused and Graham never left the field: Ready.
    assert summary['Graham'] == {'status': 'Available'}


def test_pitch_smart_13_to_18_second_return_is_a_rule_conflict():
    summary = {'Graham': {'status': 'Available'}}
    history = [
        change(field('Graham'), field('Pat', SS='Graham')),          # off P, to SS
        change(field('Pat', SS='Graham'), field('Graham', SS='Pat')),  # the one return
        change(field('Graham', SS='Pat'), field('Pat', SS='Graham')),  # off P again
    ]
    now = field('Pat', SS='Graham')
    assert policy.mound_history(history, 'Graham', now) == (2, 1, False)
    policy.apply_reentry_rule(summary, PS_14U, history, 'Pat', now)
    graham = summary['Graham']
    assert graham['status'] == 'Already Pitched This Game'
    assert graham['eligibility'] == policy.RULE_CONFLICT
    assert policy.describe('Graham', graham, PS_14U)['eligibility_message'] == (
        'Graham already returned to pitch once in this game. MLB Pitch Smart '
        'rules for this age group allow one return per game.'
    )


@pytest.mark.parametrize('history, now', [
    # Benched straight from the mound, still on the bench.
    ([change(field('Graham'), field('Pat'))], field('Pat')),
    # On the bench for a while after pitching, back in the field now.
    ([change(field('Graham'), field('Pat')),
      change(field('Pat'), field('Pat', SS='Graham'))], field('Pat', SS='Graham')),
], ids=['on_bench_now', 'benched_then_returned_to_field'])
def test_pitch_smart_13_to_18_off_the_field_cannot_be_confirmed(history, now):
    """Whether bench time left the game depends on the event's substitution
    rules, which CoachBoard doesn't know: the coach verifies."""
    summary = {'Graham': {'status': 'Available'}}
    policy.apply_reentry_rule(summary, PS_14U, history, 'Pat', now)
    graham = summary['Graham']
    assert graham['status'] == 'Re-entry Unconfirmed'
    assert graham['eligibility'] == policy.UNKNOWN
    assert policy.describe('Graham', graham, PS_14U)['required_decision'] == 'eligibility_verified'


def test_undone_changes_do_not_count_toward_the_one_return():
    history = [
        change(field('Graham'), field('Pat', SS='Graham')),
        change(field('Pat', SS='Graham'), field('Graham', SS='Pat'), reverted=True),
    ]
    now = field('Pat', SS='Graham')
    assert policy.mound_history(history, 'Graham', now) == (1, 0, False)


@pytest.mark.parametrize('rules', [
    {'rule_set_name': 'MLB Pitch Smart', 'age_group': '19U'},
    {'rule_set_name': 'Little League Baseball', 'age_group': '12U'},
    {'rule_set_name': 'Bullpen Tournaments', 'age_group': '12U'},
], ids=['pitch_smart_19U', 'little_league', 'bullpen'])
def test_reentry_the_preset_does_not_encode_cannot_be_confirmed(rules):
    summary = {'Graham': {'status': 'Available'}}
    now = field('Pat', SS='Graham')
    policy.apply_reentry_rule(summary, rules, [change(field('Graham'), now)], 'Pat', now)
    graham = summary['Graham']
    assert graham['status'] == 'Re-entry Rule Unknown'
    assert graham['eligibility'] == policy.UNKNOWN
    described = policy.describe('Graham', graham, rules)
    assert described['required_decision'] == 'eligibility_verified'
    assert "doesn't say whether a pitcher may return to pitch" in described['eligibility_message']
