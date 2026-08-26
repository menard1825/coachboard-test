from datetime import date, datetime, timedelta
from types import SimpleNamespace

from game_pitching_rules import gameplay_pitch_summary


PITCH_SMART_12U = {
    'rule_type': 'pitch_count',
    'max_daily': 85,
    'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)],
    'rule_set_name': 'MLB Pitch Smart',
    'configured_rule_set_name': 'MLB Pitch Smart',
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
