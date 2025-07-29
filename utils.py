import json
from datetime import date, timedelta, datetime
from models import Player, PitchingOuting

# This dictionary was originally in app.py
PITCHING_RULES = {
    'USSSA': {
        'default': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '11U': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
    }
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

def calculate_cumulative_pitching_stats(pitcher_name, all_outings):
    """Calculates total innings, pitches, and appearances for a pitcher."""
    stats = {'total_innings_pitched': 0.0, 'total_pitches_thrown': 0, 'appearances': 0}
    for outing in all_outings:
        if outing.pitcher == pitcher_name:
            try:
                stats['total_innings_pitched'] += float(outing.innings or 0.0)
                stats['total_pitches_thrown'] += int(outing.pitches or 0)
                stats['appearances'] += 1
            except (ValueError, TypeError):
                continue
    stats['total_innings_pitched'] = round(stats['total_innings_pitched'], 1)
    return stats

def calculate_cumulative_position_stats(roster_players, lineups):
    """Calculates the number of games each player played at each position."""
    stats = {player.name: {} for player in roster_players}
    for lineup in lineups:
        try:
            positions = json.loads(lineup.lineup_positions or "[]")
            for item in positions:
                if item.get('name') in stats and item.get('position'):
                    pos = item['position']
                    stats[item['name']][pos] = stats[item['name']].get(pos, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue
    return stats

def calculate_pitch_count_summary(roster, all_outings, rules):
    """Calculates the daily/weekly pitch counts and availability for all pitchers."""
    summary = {}
    today = date.today()
    for player in roster:
        if player.pitcher_role == 'Not a Pitcher':
            continue
        
        player_outings = sorted([o for o in all_outings if o.pitcher == player.name], key=lambda x: datetime.strptime(x.date, '%Y-%m-%d'), reverse=True)
        
        daily_pitches = sum(o.pitches for o in player_outings if datetime.strptime(o.date, '%Y-%m-%d').date() == today)
        weekly_pitches = sum(o.pitches for o in player_outings if (today - datetime.strptime(o.date, '%Y-%m-%d').date()).days < 7)

        status, next_available_str = 'Available', 'Today'
        required_rest = 0
        
        if player_outings:
            last_outing = player_outings[0]
            last_outing_date = datetime.strptime(last_outing.date, '%Y-%m-%d').date()
            pitches_in_last_outing = last_outing.pitches
            
            # Determine rest days based on the rules thresholds
            for threshold, rest_days in rules.get('rest_thresholds', []):
                if pitches_in_last_outing <= threshold:
                    required_rest = rest_days
                    break
            else: # If pitch count is over the highest threshold
                if rules.get('rest_thresholds'):
                    required_rest = rules['rest_thresholds'][-1][1] + 1
            
            next_available_date = last_outing_date + timedelta(days=required_rest + 1)
            
            if today < next_available_date:
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
    return summary
