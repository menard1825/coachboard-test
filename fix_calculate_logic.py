with open("utils.py", "r") as f:
    content = f.read()

# We need to rewrite the override logic. If required_rest is > 0 from a previous day (or consecutive day calculation), they should NOT be available today!
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
                    active_day_pitches = pitches_on_last_day

                    # If they are ALREADY resting for today because of a PREVIOUS day's pitching,
                    # we do NOT make them available! The only time they are available is if they
                    # are pitching today AND they haven't crossed consecutive days threshold from yesterday.
                    # Actually, if last_outing_date == today, they MIGHT be forced to rest tomorrow,
                    # but today they are still Available for the current game day as long as they are under max_daily.
                    # Wait, if they pitched yesterday AND today, the consecutive rule triggers.
                    # `next_available_date` = today + 2 = tomorrow.
                    # `today < tomorrow` -> Resting.
                    # But they are ALREADY pitching today. Can they pitch MORE today?
                    # The Pitch Smart rule says: "Pitchers making a pitching appearance in two consecutive days must rest a minimum of one day."
                    # It doesn't explicitly ban them from finishing the second day.
                    # However, if they reached their max daily limit, they are done.

                    if active_day_pitches < rules.get('max_daily', 85):
                        status = 'Available'
                        next_available_str = next_available_date.strftime('%a, %b %d') if required_rest > 0 else 'Today'
                        daily_pitches = active_day_pitches
                    else:
                        status = 'Resting'

                    # Let's fix the case where last_outing_date == today, BUT they actually shouldn't have pitched today
                    # because they threw 85 pitches yesterday.
                    # If they threw 85 pitches yesterday, they required 4 days rest.
                    # But if the user logged an outing today anyway, the system currently considers them "Available" for today!
                    # This is bad. If they pitched yesterday and required rest today, we should mark them as Resting.
                    # How to check? Find the second-to-last outing that is NOT today.

                # Fix for the "override" logic:
                # We need to check if ANY historical outing requires them to rest today.
                for past_outing in player_outings:
                    if past_outing.date.date() >= today:
                        continue # We only check past days for rest requirements affecting today

                    p_date = past_outing.date.date()
                    p_pitches = sum(o.pitches or 0 for o in player_outings if o.date.date() == p_date)

                    p_req_rest = 0
                    for threshold, rest_days in rules.get('rest_thresholds', []):
                        if p_pitches <= threshold:
                            p_req_rest = rest_days
                            break
                    else:
                        if rules.get('rest_thresholds'):
                            p_req_rest = rules['rest_thresholds'][-1][1] + 1

                    # Check consecutive days for past outing
                    if any(o.date.date() == p_date - timedelta(days=1) for o in player_outings) and p_req_rest < 1:
                        p_req_rest = 1

                    p_next_avail = p_date + timedelta(days=p_req_rest + 1)
                    if today < p_next_avail:
                        status = 'Resting'
                        next_available_str = p_next_avail.strftime('%a, %b %d')
                        break # Found a past outing that forces rest today
"""

# Let's cleanly replace the inside of the try block in calculate_pitch_count_summary
import re
new_func_body = """        try:
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
                for past_outing in player_outings:
                    p_date = past_outing.date.date()
                    if p_date >= today:
                        continue # Evaluate future/today separately

                    p_pitches = sum(o.pitches or 0 for o in player_outings if o.date.date() == p_date)

                    p_req_rest = 0
                    for threshold, rest_days in rules.get('rest_thresholds', []):
                        if p_pitches <= threshold:
                            p_req_rest = rest_days
                            break
                    else:
                        if rules.get('rest_thresholds'):
                            p_req_rest = rules['rest_thresholds'][-1][1] + 1

                    # Check consecutive days for this past outing
                    if any(o.date.date() == p_date - timedelta(days=1) for o in player_outings) and p_req_rest < 1:
                        p_req_rest = 1

                    p_next_avail = p_date + timedelta(days=p_req_rest + 1)
                    if today < p_next_avail:
                        status = 'Resting'
                        next_available_str = p_next_avail.strftime('%a, %b %d')
                        break

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

                        # Did they pitch yesterday too?
                        if any(o.date.date() == today - timedelta(days=1) for o in player_outings) and req_rest < 1:
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
        except Exception as e:"""

with open("utils.py", "r") as f:
    text = f.read()

# We need to replace everything from "try:" to "except Exception as e:"
start = text.find("        try:")
end = text.find("        except Exception as e:")
if start != -1 and end != -1:
    text = text[:start] + new_func_body + text[end + len("        except Exception as e:"):]

with open("utils.py", "w") as f:
    f.write(text)
