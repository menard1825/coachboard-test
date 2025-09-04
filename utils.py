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
# MODIFIED: Expanded to include a full range of age groups for USSSA rules.
PITCHING_RULES = {
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
}


def allowed_file(filename):
    """Checks if the filename has an allowed extension."""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_pitching_rules_for_team(team):
    """Gets the appropriate pitching rule set for a given team."""
    rule_set_name = getattr(team, 'pitching_rule_set', 'USSSA') or 'USSSA'
    age_group = getattr(team, 'age_group', 'default') or 'default'
    rule_set = PITCHING_RULES.get(rule_set_name, PITCHING_RULES['USSSA'])
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
    """Calculates the number of INNINGS a player appeared at each position in a rotation."""
    stats = {player.name: {} for player in roster_players}

    for rotation in rotations:
        try:
            innings_data = rotation.innings or {}
            if not isinstance(innings_data, dict):
                continue

            # Iterate through each inning in the rotation
            for inning, positions in innings_data.items():
                if not isinstance(positions, dict):
                    continue
                # Iterate through each position assignment in the inning
                for position, player_name in positions.items():
                    if player_name in stats:
                        # Increment the count for that position for that player
                        stats[player_name][position] = stats[player_name].get(position, 0) + 1

        except Exception:
            # Safely skip any rotation that has malformed data
            continue
    return stats

def calculate_pitch_count_summary(roster, all_outings, rules, context_date=None):
    """Calculates the daily/weekly pitch counts and availability for all pitchers."""
    summary = {}
    today = context_date if context_date else date.today()
    for player in roster:
        try:
            # Filter for outings on or before the context date
            player_outings = sorted([o for o in all_outings if o.player_id == player.id and isinstance(o.date, (datetime, date)) and o.date.date() <= today], key=lambda x: x.date, reverse=True)
            
            daily_pitches = sum(o.pitches or 0 for o in player_outings if o.date.date() == today)
            weekly_pitches = sum(o.pitches or 0 for o in player_outings if (today - o.date.date()).days < 7)

            status, next_available_str = 'Available', 'Today'
            required_rest = 0
            
            if player_outings:
                last_outing = player_outings[0]
                last_outing_date = last_outing.date.date()

                # Sum pitches on the last day the pitcher threw
                pitches_on_last_day = sum(o.pitches or 0 for o in player_outings if o.date.date() == last_outing_date)

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

                # New logic: If the last outing was today, check if they can still pitch.
                if last_outing_date == today:
                    if daily_pitches < rules.get('max_daily', 85):
                        status = 'Available'
                        next_available_str = 'Today'
                    else:
                        # They've hit their daily max, so they are resting.
                        # The next_available_date calculated earlier is correct.
                        status = 'Resting'
                        next_available_str = next_available_date.strftime('%a, %b %d')

            summary[player.name] = {
                'daily': daily_pitches,
                'weekly': weekly_pitches,
                'status': status,
                'next_available': next_available_str,
                'max_daily': rules.get('max_daily', 85),
                'pitches_remaining_today': max(0, rules.get('max_daily', 85) - daily_pitches)
            }
        except Exception as e:
            print(f"Error calculating pitch count summary for player {player.name} (ID: {player.id}): {e}")
            continue
    return summary
