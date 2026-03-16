def rebuild_calculate_pitch_count_summary():
    with open('utils.py', 'r') as f:
        lines = f.readlines()

    out_lines = []
    in_func = False
    for line in lines:
        if line.startswith('def calculate_pitch_count_summary('):
            in_func = True
            out_lines.append(line)
            out_lines.append('    """Calculates the daily/weekly pitch counts and availability for all pitchers."""\n')
            out_lines.append('    summary = {}\n')
            out_lines.append('    today = date.today()\n')

            # Write new body
            body = """    for player in roster:
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
            out_lines.append(body)
            # DONT break, just skip the old function
        elif in_func:
            if line.startswith('def '): # Another function started!
                in_func = False
                out_lines.append(line)
        else:
            out_lines.append(line)

    with open('utils.py', 'w') as f:
        f.writelines(out_lines)

rebuild_calculate_pitch_count_summary()
