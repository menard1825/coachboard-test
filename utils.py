import json
from datetime import date, timedelta, datetime
from sqlalchemy import func
from models import Player, PitchingOuting

# --- Constants ---
DEFAULT_TAB_ORDER = ['roster', 'player_development', 'lineups', 'pitching', 'scouting_list', 'rotations', 'games', 'collaboration', 'practice_plan', 'signs']
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
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}


# --- Helper Functions ---
def model_to_dict(obj):
    """
    Converts a SQLAlchemy model instance into a dictionary,
    correctly handling date/datetime objects and JSON strings.
    """
    if obj is None:
        return None

    d = {}
    for column in obj.__table__.columns:
        val = getattr(obj, column.name)

        # Format dates and datetimes
        if isinstance(val, (datetime, date)):
            d[column.name] = val.isoformat()
        # Parse JSON strings into objects/arrays
        elif isinstance(val, str) and column.name in ['innings', 'lineup_positions', 'tab_order', 'player_order', 'tasks', 'absences']:
            try:
                d[column.name] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                # If parsing fails, default to a sensible empty type
                if 'positions' in column.name or 'order' in column.name or 'tasks' in column.name or 'absences' in column.name:
                    d[column.name] = []
                else:
                    d[column.name] = {}
        else:
            d[column.name] = val
    return d

def pitching_outing_to_dict(outing):
    if not outing:
        return None
    d = model_to_dict(outing)
    d['player_name'] = outing.player.name if outing.player else "Unknown"
    return d

def parse_date(date_str):
    if not date_str or date_str == 'Never':
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%A, %m/%d/%y, %I:%M %p', '%A, %m/%d/%y'):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None

def allowed_file(filename):
    """Checks if the filename has an allowed extension."""
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
    """Calculates the number of games a player appeared at each position in a rotation."""
    stats = {player.name: {} for player in roster_players}

    game_rotations_counted = set()

    for rotation in rotations:
        rotation_key = rotation.associated_game_id or rotation.id

        if rotation_key in game_rotations_counted:
            continue

        try:
            innings_data = rotation.innings or {}
            if not isinstance(innings_data, dict):
                continue

            players_in_this_rotation = set()
            for inning, positions in innings_data.items():
                for position, player_name in positions.items():
                    player_position_tuple = (player_name, position)

                    if player_name in stats and player_position_tuple not in players_in_this_rotation:
                        stats[player_name][position] = stats[player_name].get(position, 0) + 1
                        players_in_this_rotation.add(player_position_tuple)

            game_rotations_counted.add(rotation_key)

        except Exception:
            continue
    return stats

def calculate_pitch_count_summary(roster, all_outings, rules):
    """Calculates the daily/weekly pitch counts and availability for all pitchers."""
    summary = {}
    today = datetime.utcnow().date()
    for player in roster:
        try:
            player_outings = sorted([o for o in all_outings if o.player_id == player.id and isinstance(o.date, (datetime, date))], key=lambda x: x.date, reverse=True)
            
            daily_pitches = sum(o.pitches or 0 for o in player_outings if o.date.date() == today)
            weekly_pitches = sum(o.pitches or 0 for o in player_outings if (today - o.date.date()).days < 7)

            status, next_available_str = 'Available', 'Today'
            required_rest = 0
            
            if player_outings:
                last_outing = player_outings[0]
                last_outing_date = last_outing.date.date()

                pitches_on_last_day = sum(o.pitches or 0 for o in player_outings if o.date.date() == last_outing_date)

                for threshold, rest_days in rules.get('rest_thresholds', []):
                    if pitches_on_last_day <= threshold:
                        required_rest = rest_days
                        break
                else:
                    if rules.get('rest_thresholds'):
                        required_rest = rules['rest_thresholds'][-1][1] + 1

                next_available_date = last_outing_date + timedelta(days=required_rest + 1)

                if today < next_available_date:
                    status = 'Resting'
                    next_available_str = next_available_date.strftime('%a, %b %d')

                if last_outing_date == today:
                    if daily_pitches < rules.get('max_daily', 85):
                        status = 'Available'
                        next_available_str = 'Today'
                    else:
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
