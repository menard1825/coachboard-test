import re

with open("utils.py", "r") as f:
    content = f.read()

# Replace PITCHING_RULES dictionary
old_rules = """PITCHING_RULES = {
    'USSSA': {
        '4U': {'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '5U': {'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '6U': {'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '7U': {'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '8U': {'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '9U': {'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '10U': {'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '11U': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '12U': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '13U': {'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '14U': {'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        'default': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]}
    }
    # You could add other rule sets like 'Little League' here in the future
}"""

new_rules = """PITCHING_RULES = {
    'USSSA': {
        # Using MLB Pitch Smart Guidelines for all age groups
        '4U': {'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '5U': {'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '6U': {'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '7U': {'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '8U': {'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '9U': {'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (75, 4)]},
        '10U': {'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (75, 4)]},
        '11U': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]},
        '12U': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]},
        '13U': {'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (95, 4)]},
        '14U': {'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (95, 4)]},
        '15U': {'max_daily': 95, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (75, 3), (95, 4)]},
        '16U': {'max_daily': 95, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (75, 3), (95, 4)]},
        '17U': {'max_daily': 105, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (75, 3), (105, 4)]},
        '18U': {'max_daily': 105, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (75, 3), (105, 4)]},
        'default': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]}
    }
}"""

content = content.replace(old_rules, new_rules)

# Replace calculate_pitch_count_summary logic
old_logic = """
                # Determine rest days based on the total pitches on that day
                for threshold, rest_days in rules.get('rest_thresholds', []):
                    if pitches_on_last_day <= threshold:
                        required_rest = rest_days
                        break
                else: # If pitch count is over the highest threshold
                    if rules.get('rest_thresholds'):
                        required_rest = rules['rest_thresholds'][-1][1] + 1

                next_available_date = last_outing_date + timedelta(days=required_rest + 1)

                if today < next_available_date:
                    status = 'Resting'
                    next_available_str = next_available_date.strftime('%a, %b %d')

                # --- CORRECTION FOR SAME-DAY OR PRE-LOGGED GAMES ---
                # If the last outing is Today OR in the Future (pre-logging),
                # check if they have room left in the daily limit.
                if last_outing_date >= today:
                    # Recalculate daily_pitches to be based on the ACTIVE game day, not just 'today'
                    # This handles the case where you pre-log a game for tomorrow.
                    active_day_pitches = pitches_on_last_day

                    if active_day_pitches < rules.get('max_daily', 85):
                        status = 'Available'
                        next_available_str = 'Today' # Or "Game Day"
                        # Update the displayed remaining count to match the active day
                        daily_pitches = active_day_pitches
                    else:
                        status = 'Resting'
                        # next_available_str is already correct from the calculation above
"""

new_logic = """
                # Determine rest days based on the total pitches on that day
                for threshold, rest_days in rules.get('rest_thresholds', []):
                    if pitches_on_last_day <= threshold:
                        required_rest = rest_days
                        break
                else: # If pitch count is over the highest threshold
                    if rules.get('rest_thresholds'):
                        required_rest = rules['rest_thresholds'][-1][1] + 1

                # MLB Pitch Smart Rule: Pitchers making a pitching appearance in two consecutive days must rest a minimum of one day.
                # Find if they pitched on the day before the last_outing_date
                day_before_last_outing = last_outing_date - timedelta(days=1)
                pitched_day_before = any(o.date.date() == day_before_last_outing for o in player_outings)

                if pitched_day_before and required_rest < 1:
                    required_rest = 1 # Force at least 1 day of rest

                next_available_date = last_outing_date + timedelta(days=required_rest + 1)

                if today < next_available_date:
                    status = 'Resting'
                    next_available_str = next_available_date.strftime('%a, %b %d')

                # --- CORRECTION FOR SAME-DAY OR PRE-LOGGED GAMES ---
                # If the last outing is Today OR in the Future (pre-logging),
                # check if they have room left in the daily limit.
                if last_outing_date >= today:
                    # Recalculate daily_pitches to be based on the ACTIVE game day, not just 'today'
                    # This handles the case where you pre-log a game for tomorrow.
                    active_day_pitches = pitches_on_last_day

                    if active_day_pitches < rules.get('max_daily', 85):
                        status = 'Available'
                        next_available_str = 'Today' # Or "Game Day"
                        # Update the displayed remaining count to match the active day
                        daily_pitches = active_day_pitches
                    else:
                        status = 'Resting'
                        # next_available_str is already correct from the calculation above
"""

content = content.replace(old_logic, new_logic)

with open("utils.py", "w") as f:
    f.write(content)
