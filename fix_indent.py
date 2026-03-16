with open("utils.py", "r") as f:
    text = f.read()

# Fix indentation around try/except
fixed_text = """    for player in roster:
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
                            next_available_str = (today + timedelta(days=1)).strftime('%a, %b %d')

                        # Calculate rest required FOR TOMORROW based on today's pitches
                        req_rest = 0
                        for threshold, rest_days in rules.get('rest_thresholds', []):
                            if daily_pitches <= threshold:
                                req_rest = rest_days
                                break
                        else:
                            if rules.get('rest_thresholds'):
                                req_rest = rules['rest_thresholds'][-1][1] + 1

                        # Did they pitch yesterday too?
                        if any(o.date.date() == today - timedelta(days=1) for o in player_outings):
                            if req_rest < 1:
                                req_rest = 1

                        next_avail = today + timedelta(days=req_rest + 1)
                        if req_rest > 0:
                            next_available_str = next_avail.strftime('%a, %b %d')

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
"""

import re
match = re.search(r'    for player in roster:\n.*continue', text, re.DOTALL)
if match:
    text = text.replace(match.group(0), fixed_text + "            print(f\"Error calculating pitch count summary for player {player.name} (ID: {player.id}): {e}\")\n            continue")

with open("utils.py", "w") as f:
    f.write(text)
