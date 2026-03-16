import re

with open("utils.py", "r") as f:
    text = f.read()

# 1. Replace PITCHING_RULES
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

if old_rules in text:
    text = text.replace(old_rules, new_rules)
else:
    print("Could not find PITCHING_RULES!")

# 2. Re-write the calculate_pitch_count_summary function completely
start_idx = text.find("def calculate_pitch_count_summary")
if start_idx == -1:
    print("Could not find function")
    exit(1)

text = text[:start_idx]

new_func = """def calculate_pitch_count_summary(roster, all_outings, rules):
    \"\"\"Calculates the daily/weekly pitch counts and availability for all pitchers.\"\"\"
    summary = {}
    today = date.today()
    for player in roster:
        try:
            player_outings = sorted([o for o in all_outings if o.player_id == player.id and isinstance(o.date, (datetime, date))], key=lambda x: x.date, reverse=True)

            daily_pitches = sum(o.pitches or 0 for o in player_outings if o.date.date() == today)
            weekly_pitches = sum(o.pitches or 0 for o in player_outings if (today - o.date.date()).days < 7)

            status = 'Available'
            next_available_str = 'Today'
            max_daily = rules.get('max_daily', 85)

            last_outing_display = 'N/A'

            if player_outings:
                last_outing_date = player_outings[0].date.date()
                last_outing_display = last_outing_date.strftime('%a, %b %d')

                # Check ALL recent past outings to see if any enforce rest for TODAY
                past_outings = [o for o in player_outings if o.date.date() < today]

                if past_outings:
                    # Find the unique past dates
                    past_dates = sorted(list(set([o.date.date() for o in past_outings])), reverse=True)

                    for p_date in past_dates:
                        p_pitches = sum(o.pitches or 0 for o in past_outings if o.date.date() == p_date)

                        p_req_rest = 0
                        for threshold, rest_days in rules.get('rest_thresholds', []):
                            if p_pitches <= threshold:
                                p_req_rest = rest_days
                                break
                        else:
                            if rules.get('rest_thresholds'):
                                p_req_rest = rules['rest_thresholds'][-1][1] + 1

                        # Check consecutive days for this past outing
                        if any(o.date.date() == p_date - timedelta(days=1) for o in past_outings) and p_req_rest < 1:
                            p_req_rest = 1

                        p_next_avail = p_date + timedelta(days=p_req_rest + 1)
                        if today < p_next_avail:
                            status = 'Resting'
                            next_available_str = p_next_avail.strftime('%a, %b %d')
                            break # Found a past outing that forces rest today

                # If they are NOT already resting from a past outing, evaluate TODAY
                if status != 'Resting':
                    # Has the player pitched today?
                    if daily_pitches > 0:
                        if daily_pitches >= max_daily:
                            status = 'Resting'

                        # Calculate rest required FOR TOMORROW based on today's pitches
                        req_rest = 0
                        for threshold, rest_days in rules.get('rest_thresholds', []):
                            if daily_pitches <= threshold:
                                req_rest = rest_days
                                break
                        else:
                            if rules.get('rest_thresholds'):
                                req_rest = rules['rest_thresholds'][-1][1] + 1

                        # Did they pitch yesterday too? (Consecutive days rule)
                        if any(o.date.date() == today - timedelta(days=1) for o in player_outings):
                            if req_rest < 1:
                                req_rest = 1

                        next_avail = today + timedelta(days=req_rest + 1)
                        if req_rest > 0:
                            next_available_str = next_avail.strftime('%a, %b %d')
                            if status == 'Resting':
                                # Only set to next_avail if they are resting today
                                # Wait, if they are Resting TODAY because they hit 85 pitches TODAY,
                                # next available is next_avail (tomorrow + rest)
                                pass

            pitches_remaining = max(0, max_daily - daily_pitches)
            if status == 'Resting':
                pitches_remaining = 0

            summary[player.name] = {
                'daily': daily_pitches,
                'weekly': weekly_pitches,
                'status': status,
                'next_available': next_available_str,
                'max_daily': max_daily,
                'pitches_remaining_today': pitches_remaining,
                'last_outing_display': last_outing_display
            }
        except Exception as e:
            print(f"Error calculating pitch count summary for player {player.name} (ID: {player.id}): {e}")
            continue
    return summary
"""
text += new_func

with open("utils.py", "w") as f:
    f.write(text)
