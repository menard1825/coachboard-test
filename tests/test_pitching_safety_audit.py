from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from game_pitching_rules import gameplay_pitch_summary
from utils import calculate_pitch_count_summary


PITCH_SMART_12U = {
    'rule_type': 'pitch_count',
    'max_daily': 85,
    'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)],
    'rule_set_name': 'MLB Pitch Smart',
    'configured_rule_set_name': 'MLB Pitch Smart',
    'age_group': '12U',
}

USSSA_12U = {
    'rule_type': 'innings',
    'next_day_max_outs': 9,
    'max_daily_outs': 18,
    'rolling_3_day_max_outs': 24,
    'max_consecutive_days': 3,
    'rule_set_name': 'USSSA',
    'configured_rule_set_name': 'USSSA',
    'age_group': '12U',
}


def _player(player_id=1, name='Test Pitcher'):
    return SimpleNamespace(id=player_id, name=name)


def _outing(player_id, outing_date, pitches, *, innings=1.0, outing_type='Game', game_id=None):
    return SimpleNamespace(
        player_id=player_id,
        date=datetime.combine(outing_date, datetime.min.time()),
        pitches=pitches,
        innings=innings,
        outing_type=outing_type,
        game_id=game_id,
    )


def test_selected_pitch_smart_rules_preserve_rest_status():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [_outing(1, target_date - timedelta(days=1), 40)]

    summary = gameplay_pitch_summary(
        roster,
        outings,
        dict(PITCH_SMART_12U),
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
    )

    item = summary['Test Pitcher']
    assert item['status'] == 'Resting'
    assert '40 game pitches' in item['status_detail']
    assert item['next_available'] != 'Today'


@pytest.mark.parametrize(
    ('pitches_yesterday', 'expected_status'),
    [
        (1, 'Available'),
        (20, 'Available'),
        (21, 'Resting'),
        (35, 'Resting'),
        (36, 'Resting'),
        (50, 'Resting'),
        (51, 'Resting'),
        (65, 'Resting'),
        (66, 'Resting'),
        (85, 'Resting'),
    ],
)
def test_12u_pitch_smart_rest_threshold_boundaries(pitches_yesterday, expected_status):
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [_outing(1, target_date - timedelta(days=1), pitches_yesterday)]

    item = gameplay_pitch_summary(
        roster,
        outings,
        dict(PITCH_SMART_12U),
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
    )['Test Pitcher']

    assert item['status'] == expected_status


def test_pitch_smart_blocks_third_consecutive_pitching_day():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [
        _outing(1, target_date - timedelta(days=1), 10),
        _outing(1, target_date - timedelta(days=2), 10),
    ]

    item = gameplay_pitch_summary(
        roster,
        outings,
        dict(PITCH_SMART_12U),
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
    )['Test Pitcher']

    assert item['status'] == 'Resting'
    assert 'third consecutive day' in item['status_detail']


def test_pitch_smart_daily_max_blocks_more_pitches_in_same_game():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [_outing(1, target_date, 85, game_id=10)]

    item = gameplay_pitch_summary(
        roster,
        outings,
        dict(PITCH_SMART_12U),
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
        current_game_id=10,
    )['Test Pitcher']

    assert item['status'] == 'Resting'
    assert item['pitches_remaining_today'] is None
    assert 'maximum reached' in item['status_detail']


def test_practice_throwing_counts_as_workload_not_official_game_usage():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [_outing(1, target_date, 60, outing_type='Practice')]

    item = gameplay_pitch_summary(
        roster,
        outings,
        dict(PITCH_SMART_12U),
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
    )['Test Pitcher']

    assert item['status'] == 'Available'
    assert item['official_daily_pitches'] == 0
    assert item['workload_daily_pitches'] == 60


def test_unselected_competition_rules_fail_closed_but_preserve_arm_care_context():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [_outing(1, target_date - timedelta(days=1), 40)]
    rules = {
        **PITCH_SMART_12U,
        'competition_unselected': True,
        'competition_rule_set_name': None,
        'arm_care_rule_set': 'MLB Pitch Smart',
        'rule_set_name': 'Rules Not Selected',
        'configured_rule_set_name': None,
    }

    summary = gameplay_pitch_summary(
        roster,
        outings,
        rules,
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
    )

    item = summary['Test Pitcher']
    assert item['status'] == 'Unavailable — Select Game Rules'
    assert item['next_available'] == 'Verify event rules'
    assert 'Competition pitching rules are not selected' in item['status_detail']
    assert item['arm_care_status'] == 'Resting'
    assert item['arm_care_status_detail']
    assert item['arm_care_next_available'] != 'Today'
    assert item['max_daily'] == 85


def test_unselected_rules_never_report_available_even_when_arm_care_is_clear():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    rules = {
        **PITCH_SMART_12U,
        'competition_unselected': True,
        'competition_rule_set_name': None,
        'arm_care_rule_set': 'MLB Pitch Smart',
        'rule_set_name': 'Rules Not Selected',
        'configured_rule_set_name': None,
    }

    summary = gameplay_pitch_summary(
        roster,
        [],
        rules,
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
    )

    item = summary['Test Pitcher']
    assert item['arm_care_status'] == 'Available'
    assert item['status'] != 'Available'
    assert 'Unavailable' in item['status']


def test_base_calculator_error_returns_explicit_fail_closed_row():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [_outing(1, target_date, 'not-a-number')]

    summary = calculate_pitch_count_summary(
        roster,
        outings,
        dict(PITCH_SMART_12U),
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
    )

    item = summary['Test Pitcher']
    assert item['status'] == 'Eligibility Error'
    assert item['pitch_history_complete'] is False
    assert item['next_available'] == 'Verify pitching history'
    assert item['official_daily_pitches'] is None


def test_calculator_error_returns_fail_closed_gameplay_row():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [_outing(1, target_date, 'not-a-number')]

    summary = gameplay_pitch_summary(
        roster,
        outings,
        dict(PITCH_SMART_12U),
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
    )

    item = summary['Test Pitcher']
    assert item['status'] == 'Unavailable — Eligibility Error'
    assert item['pitch_history_complete'] is False
    assert item['next_available'] == 'Verify pitching history'
    assert item['pitches_remaining_today'] is None


def test_missing_pitch_count_is_visibly_unavailable_in_gameplay():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [_outing(1, target_date - timedelta(days=1), None)]

    summary = gameplay_pitch_summary(
        roster,
        outings,
        dict(PITCH_SMART_12U),
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
    )

    item = summary['Test Pitcher']
    assert item['status'] == 'Unavailable — Pitch Count Incomplete'
    assert item['pitch_history_complete'] is False
    assert item['next_available'] == 'Verify game pitch counts'


def test_missing_usssa_innings_is_visibly_unavailable_in_gameplay():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [_outing(1, target_date - timedelta(days=1), 25, innings=None)]

    item = gameplay_pitch_summary(
        roster,
        outings,
        dict(USSSA_12U),
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
    )['Test Pitcher']

    assert item['status'] == 'Unavailable — Innings Incomplete'
    assert item['next_available'] == 'Verify game innings'


def test_same_day_game_restriction_is_visibly_unavailable_in_gameplay():
    target_date = date(2026, 8, 26)
    roster = [_player()]
    outings = [_outing(1, target_date, 15, game_id=100)]

    summary = gameplay_pitch_summary(
        roster,
        outings,
        dict(PITCH_SMART_12U),
        target_date=target_date,
        team_timezone='America/Indiana/Indianapolis',
        current_game_id=200,
    )

    item = summary['Test Pitcher']
    assert item['status'] == 'Unavailable — Same-Day Game Restriction'
    assert 'multiple games on the same day' in item['status_detail']
    assert item['next_available'] != 'Today'
