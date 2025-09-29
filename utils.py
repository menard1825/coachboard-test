import json
from datetime import date, timedelta, datetime
from sqlalchemy import func
from models import Player, PitchingOuting

def parse_date(date_str):
    """Tries to parse a date string with multiple formats, returning a datetime object."""
    if not date_str:
        return None
    for fmt in (
        '%Y-%m-%d',
        '%A, %m/%d/%y, %I:%M %p',
        '%A, %m/%d/%y',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M'
    ):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            pass
    return None

def model_to_dict(obj):
    """Converts a SQLAlchemy model instance into a dictionary."""
    if obj is None:
        return None
    d = {}
    for column in obj.__table__.columns:
        val = getattr(obj, column.name)
        # MODIFIED: Output dates in ISO 8601 format for unambiguous parsing in JavaScript.
        if isinstance(val, (datetime, date)):
            d[column.name] = val.isoformat()
        else:
            d[column.name] = val
    return d

def pitching_outing_to_dict(outing):
    if not outing:
        return None
    d = model_to_dict(outing)
    d['player_name'] = outing.player.name if outing.player else "Unknown"
    return d

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
}

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_pitching_rules_for_team(team):
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

def calculate_cumulative_position_stats(roster_players, rotations, games):
    stats = {player.name: {} for player in roster_players}
    today = datetime.now().date()

    past_game_ids = {game.id for game in games if game.date.date() <= today}

    for rotation in rotations:
        if rotation.associated_game_id not in past_game_ids:
            continue

        try:
            innings_data = rotation.innings or {}
            if not isinstance(innings_data, dict):
                continue

            for inning, positions in innings_data.items():
                for position, player_name in positions.items():
                    if player_name in stats and not position.startswith('_'):
                        stats[player_name][position] = stats[player_name].get(position, 0) + 1

                substitutions = positions.get('_substitutions', {})
                for position, subbed_players in substitutions.items():
                    for player_name in subbed_players:
                        if player_name in stats:
                            stats[player_name][position] = stats[player_name].get(position, 0) + 1

        except Exception as e:
            print(f"Error processing rotation ID {rotation.id}: {e}")
            continue

    return stats

def calculate_pitch_count_summary(roster, all_outings, rules):
    summary = {}
    today = date.today()
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

def get_player_order_as_list(player_order_data):
    if not player_order_data:
        return []

    order_list = []
    if isinstance(player_order_data, list):
        order_list = player_order_data
    elif isinstance(player_order_data, str):
        try:
            loaded = json.loads(player_order_data)
            if isinstance(loaded, list):
                order_list = loaded
        except (json.JSONDecodeError, TypeError):
            return []

    if not isinstance(order_list, list):
        return []

    result = []
    for item in order_list:
        try:
            result.append(int(item))
        except (ValueError, TypeError):
            continue
    return result