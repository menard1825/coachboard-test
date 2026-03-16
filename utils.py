import json
from datetime import date, timedelta, datetime
from sqlalchemy import func
from models import Player, PitchingOuting

def model_to_dict(obj):
    """Converts a SQLAlchemy model instance into a dictionary."""
    if obj is None:
        return None

    d = {}
    for column in obj.__table__.columns:
        val = getattr(obj, column.name)
        if isinstance(val, (datetime, date)):
            # Format dates and datetimes as 'YYYY-MM-DD'
            d[column.name] = val.strftime('%Y-%m-%d')
        else:
            d[column.name] = val
    return d

def pitching_outing_to_dict(outing):
    if not outing:
        return None
    d = model_to_dict(outing)
    d['player_name'] = outing.player.name if outing.player else "Unknown"
    return d

# This dictionary was originally in app.py
PITCHING_RULES = {
    'MLB Pitch Smart': {
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
        '17U': {'max_daily': 105, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4)]},
        '18U': {'max_daily': 105, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4)]},
        '19U': {'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        '20U': {'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        '21U': {'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        '22U': {'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        'default': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]}
    }
}


def allowed_file(filename):
    """Checks if the filename has an allowed extension."""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_pitching_rules_for_team(team):
    """Gets the appropriate pitching rule set for a given team."""
    rule_set_name = getattr(team, 'pitching_rule_set', 'MLB Pitch Smart') or 'MLB Pitch Smart'
    if rule_set_name == 'USSSA':
        rule_set_name = 'MLB Pitch Smart' # Fallback for old data
    age_group = getattr(team, 'age_group', 'default') or 'default'
    rule_set = PITCHING_RULES.get(rule_set_name, PITCHING_RULES['MLB Pitch Smart'])
    return rule_set.get(age_group, rule_set.get('default'))

def calculate_cumulative_pitching_stats(player_id, all_outings):
    """Calculates total innings, pitches, and appearances for a pitcher."""
    stats = {'total_innings_pitched': 0.0, 'total_pitches_thrown': 0, 'appearances': 0}
    for outing in all_outings:
        if outing.player_id == player_id:
            try:
                stats['total_innings_pitched'] += float(outing.innings or 0.0)
                stats['total_pitches_thrown'] += int(outing.pitches or 0)
                stats['appearances'] += 1
            except (ValueError, TypeError):
                continue
    stats['total_innings_pitched'] = round(stats['total_innings_pitched'], 1)
    return stats

def calculate_cumulative_position_stats(roster_players, rotations):
    """Calculates the number of games a player appeared at each position in a rotation."""
    stats = {player.name: {} for player in roster_players}

    # Create a set to track which players have already been counted for a specific game
    # to prevent counting them multiple times for the same game rotation.
    game_rotations_counted = set()

    for rotation in rotations:
        # A rotation is tied to a single game, so we use its ID to track.
        # If no associated game, we can use the rotation's own ID as a unique identifier.
        rotation_key = rotation.associated_game_id or rotation.id

        # Skip if we've already processed this game/rotation
        if rotation_key in game_rotations_counted:
            continue

        try:
            innings_data = rotation.innings or {}
            if not isinstance(innings_data, dict):
                continue

            players_in_this_rotation = set()
            # Iterate through each inning in the rotation
            for inning, positions in innings_data.items():
                # Iterate through each position assignment in the inning
                for position, player_name in positions.items():
                    # Add the player to a set for this rotation.
                    # We only count a player once per position per game rotation.
                    player_position_tuple = (player_name, position)

                    if player_name in stats and player_position_tuple not in players_in_this_rotation:
                        stats[player_name][position] = stats[player_name].get(position, 0) + 1
                        players_in_this_rotation.add(player_position_tuple)

            # Mark this game/rotation as counted
            game_rotations_counted.add(rotation_key)

        except Exception:
            # Safely skip any rotation that has malformed data
            continue
    return stats

def calculate_pitch_count_summary(roster, all_outings, rules):
    """Calculates the daily/weekly pitch counts and availability for all pitchers."""
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
