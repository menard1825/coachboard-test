"""Additional named pitching-rule presets used by CoachBoard.

These presets deliberately reuse the existing pitch-count calculator where the
published rule structure matches it. Tournament/league rules can change, so the
UI still reminds coaches to verify the specific event rules they are playing
under.
"""


def install_additional_pitching_rules(rule_registry):
    """Mutate the shared pitching rule registry once and return it."""
    if 'Bullpen Tournaments' not in rule_registry:
        pitch_smart = rule_registry['MLB Pitch Smart']
        bullpen_note = (
            'Bullpen Tournaments publishes USA Baseball / MLB Pitch Smart pitch-count '
            'guidelines for arm care and notes that Bullpen does not police those '
            'guidelines as tournament pitching restrictions.'
        )
        bullpen = {}
        for age in ('7U', '8U', '9U', '10U', '11U', '12U', '13U', '14U', '15U', '16U', '17U', '18U'):
            bullpen[age] = {
                **dict(pitch_smart[age]),
                'rule_note': bullpen_note,
                'reference_label': 'Bullpen Tournaments / USA Pitch Smart',
            }
        bullpen['default'] = {
            'rule_type': 'unsupported',
            'rule_note': 'Bullpen publishes Pitch Smart guidance through 18U. Verify the event rules for this age group.',
            'reference_label': 'Bullpen Tournaments',
        }
        rule_registry['Bullpen Tournaments'] = bullpen

    if 'Little League Baseball' not in rule_registry:
        little_league_note = (
            'Little League Baseball uses age-based game pitch counts and calendar-day rest. '
            'CoachBoard automates this preset for 12U and younger; older Little League '
            'divisions have additional division-specific same-day pitching rules that '
            'should be verified before relying on automatic eligibility.'
        )
        little_league = {
            '7U': {'rule_type': 'pitch_count', 'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)], 'rule_note': little_league_note, 'reference_label': 'Little League Baseball'},
            '8U': {'rule_type': 'pitch_count', 'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)], 'rule_note': little_league_note, 'reference_label': 'Little League Baseball'},
            '9U': {'rule_type': 'pitch_count', 'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (75, 4)], 'rule_note': little_league_note, 'reference_label': 'Little League Baseball'},
            '10U': {'rule_type': 'pitch_count', 'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (75, 4)], 'rule_note': little_league_note, 'reference_label': 'Little League Baseball'},
            '11U': {'rule_type': 'pitch_count', 'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)], 'rule_note': little_league_note, 'reference_label': 'Little League Baseball'},
            '12U': {'rule_type': 'pitch_count', 'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)], 'rule_note': little_league_note, 'reference_label': 'Little League Baseball'},
        }
        for age in ('13U', '14U', '15U', '16U', '17U', '18U', '19U', '20U', '21U', '22U'):
            little_league[age] = {
                'rule_type': 'unsupported',
                'rule_note': little_league_note,
                'reference_label': 'Little League Baseball',
            }
        little_league['default'] = {
            'rule_type': 'unsupported',
            'rule_note': little_league_note,
            'reference_label': 'Little League Baseball',
        }
        rule_registry['Little League Baseball'] = little_league

    return rule_registry
