import json
from datetime import date, timedelta, datetime
from sqlalchemy import func
from models import Player, PitchingOuting
import zoneinfo


def model_to_dict(obj):
    """Converts a SQLAlchemy model instance into a dictionary."""
    if obj is None:
        return None

    d = {}
    for column in obj.__table__.columns:
        val = getattr(obj, column.name)
        if isinstance(val, datetime):
            # Preserve full exact timestamps for live events and sync accuracy
            d[column.name] = val.isoformat()
        elif isinstance(val, date):
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


# Rule configuration is intentionally explicit. Pitch Smart uses GAME pitch counts;
# USSSA uses innings/outs. Practice and lesson throws are workload context, not
# silently converted into official competition limits.
PITCHING_RULES = {
    'MLB Pitch Smart': {
        '7U': {'rule_type': 'pitch_count', 'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '8U': {'rule_type': 'pitch_count', 'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '9U': {'rule_type': 'pitch_count', 'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (75, 4)]},
        '10U': {'rule_type': 'pitch_count', 'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (75, 4)]},
        '11U': {'rule_type': 'pitch_count', 'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]},
        '12U': {'rule_type': 'pitch_count', 'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]},
        '13U': {'rule_type': 'pitch_count', 'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (95, 4)]},
        '14U': {'rule_type': 'pitch_count', 'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (95, 4)]},
        '15U': {'rule_type': 'pitch_count', 'max_daily': 95, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (75, 3), (95, 4)]},
        '16U': {'rule_type': 'pitch_count', 'max_daily': 95, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (75, 3), (95, 4)]},
        '17U': {'rule_type': 'pitch_count', 'max_daily': 105, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4)]},
        '18U': {'rule_type': 'pitch_count', 'max_daily': 105, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4)]},
        '19U': {'rule_type': 'pitch_count', 'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        '20U': {'rule_type': 'pitch_count', 'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        '21U': {'rule_type': 'pitch_count', 'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        '22U': {'rule_type': 'pitch_count', 'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        'default': {'rule_type': 'pitch_count', 'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]},
    },
    'USSSA': {
        # National-style youth limits: Column A = max in one day and still pitch
        # next day; Column B = one-day max; Column C = three-day max.
        **{
            age: {
                'rule_type': 'innings',
                'next_day_max_outs': 9,
                'max_daily_outs': 18,
                'rolling_3_day_max_outs': 24,
                'max_consecutive_days': 3,
            }
            for age in ('7U', '8U', '9U', '10U', '11U', '12U')
        },
        **{
            age: {
                'rule_type': 'innings',
                'next_day_max_outs': 9,
                'max_daily_outs': 21,
                'rolling_3_day_max_outs': 24,
                'max_consecutive_days': 3,
            }
            for age in ('13U', '14U')
        },
        'default': {
            'rule_type': 'innings',
            'next_day_max_outs': 9,
            'max_daily_outs': 18,
            'rolling_3_day_max_outs': 24,
            'max_consecutive_days': 3,
        },
    },
}


def allowed_file(filename):
    """Checks if a filename has an allowed extension."""
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def get_pitching_rules_for_team(team):
    """Return a copy of the configured rule set for the team's age group."""
    rule_set_name = getattr(team, 'pitching_rule_set', 'MLB Pitch Smart') or 'MLB Pitch Smart'
    age_group = getattr(team, 'age_group', 'default') or 'default'

    # Do not pretend an unknown ruleset is something else. Fall back only when
    # the stored value is genuinely unknown, and identify the effective source.
    rule_set = PITCHING_RULES.get(rule_set_name)
    effective_name = rule_set_name
    if rule_set is None:
        rule_set = PITCHING_RULES['MLB Pitch Smart']
        effective_name = 'MLB Pitch Smart'

    # Pitch Smart's published table begins at age 7. For younger legacy team
    # records, use the 7-8 guidance but clearly expose that it is a proxy.
    effective_age = age_group
    source_note = None
    if effective_name == 'MLB Pitch Smart' and age_group in {'4U', '5U', '6U'}:
        effective_age = '7U'
        source_note = 'Using MLB Pitch Smart 7-8 guidance for this younger age setting.'

    rules = dict(rule_set.get(effective_age, rule_set.get('default', {})))
    rules['rule_set_name'] = effective_name
    rules['configured_rule_set_name'] = rule_set_name
    rules['age_group'] = age_group
    rules['source_note'] = source_note
    return rules


def baseball_innings_to_outs(value):
    """Convert baseball innings notation (e.g. 2.1 = 7 outs) to outs.

    Returns None for blank/invalid values. Only .0, .1, and .2 are valid
    fractional components because baseball innings are recorded in outs.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    try:
        if '.' in text:
            whole_text, frac_text = text.split('.', 1)
            whole = int(whole_text or '0')
            frac_text = (frac_text or '0').rstrip('0') or '0'
            if frac_text not in {'0', '1', '2'}:
                return None
            partial_outs = int(frac_text)
        else:
            whole = int(text)
            partial_outs = 0
    except (TypeError, ValueError):
        return None

    if whole < 0:
        return None
    return whole * 3 + partial_outs


def outs_to_baseball_innings(outs):
    """Format a number of outs as baseball innings notation."""
    if outs is None:
        return None
    try:
        outs = int(outs)
    except (TypeError, ValueError):
        return None
    if outs < 0:
        return None
    return f'{outs // 3}.{outs % 3}'


def normalize_baseball_innings(value):
    """Validate user innings input and return storage-compatible float notation."""
    outs = baseball_innings_to_outs(value)
    if outs is None:
        return None
    return float(outs_to_baseball_innings(outs))


def _is_game_outing(outing):
    return str(getattr(outing, 'outing_type', None) or 'Game').strip().lower() == 'game'


def calculate_cumulative_pitching_stats(player_id, all_outings):
    """Calculate GAME pitching totals using outs, never decimal inning math."""
    total_outs = 0
    total_pitches = 0
    appearances = 0
    incomplete_innings = False

    for outing in all_outings:
        if outing.player_id != player_id or not _is_game_outing(outing):
            continue
        appearances += 1
        if outing.pitches is not None:
            try:
                total_pitches += int(outing.pitches)
            except (ValueError, TypeError):
                pass
        outs = baseball_innings_to_outs(outing.innings)
        if outs is None:
            incomplete_innings = True
        else:
            total_outs += outs

    return {
        'total_innings_pitched': outs_to_baseball_innings(total_outs),
        'total_outs_pitched': total_outs,
        'total_pitches_thrown': total_pitches,
        'appearances': appearances,
        'innings_history_complete': not incomplete_innings,
    }


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


def _required_rest_days(pitches, rest_thresholds):
    if pitches is None:
        return None
    if pitches <= 0:
        return 0
    for threshold, rest_days in rest_thresholds or []:
        if pitches <= threshold:
            return rest_days
    if rest_thresholds:
        return rest_thresholds[-1][1] + 1
    return 0


def calculate_pitch_count_summary(roster, all_outings, rules, target_date=None, all_targets=None, team_timezone=None, current_game_id=None):
    """Calculate official eligibility, recorded workload, and coach targets.

    Official eligibility uses only GAME outings. Practice/lesson throws remain
    visible as workload, but they are not silently treated as official game
    pitches or USSSA innings. Missing official data stays unknown.
    """
    summary = {}
    tz = zoneinfo.ZoneInfo(team_timezone) if team_timezone else zoneinfo.ZoneInfo('America/Indiana/Indianapolis')

    if target_date is None:
        today = datetime.now(tz).date()
    elif isinstance(target_date, datetime):
        today = target_date.date() if target_date.tzinfo is None else target_date.astimezone(tz).date()
    elif isinstance(target_date, str):
        today = datetime.strptime(target_date, '%Y-%m-%d').date()
    else:
        today = target_date

    all_targets = all_targets or []
    rule_type = rules.get('rule_type', 'pitch_count')
    rule_set_name = rules.get('rule_set_name', 'MLB Pitch Smart')

    def get_local_date(value):
        if isinstance(value, datetime):
            return value.date() if value.tzinfo is None else value.astimezone(tz).date()
        return value

    for player in roster:
        try:
            player_outings = sorted(
                [o for o in all_outings if o.player_id == player.id and isinstance(o.date, (datetime, date))],
                key=lambda x: x.date,
                reverse=True,
            )
            game_outings = [o for o in player_outings if _is_game_outing(o)]

            today_workload = [o for o in player_outings if get_local_date(o.date) == today]
            seven_day_workload = [o for o in player_outings if 0 <= (today - get_local_date(o.date)).days < 7]
            today_games = [o for o in game_outings if get_local_date(o.date) == today]
            seven_day_games = [o for o in game_outings if 0 <= (today - get_local_date(o.date)).days < 7]

            workload_daily_complete = all(o.pitches is not None for o in today_workload)
            workload_weekly_complete = all(o.pitches is not None for o in seven_day_workload)
            workload_daily_known = sum(int(o.pitches) for o in today_workload if o.pitches is not None)
            workload_weekly_known = sum(int(o.pitches) for o in seven_day_workload if o.pitches is not None)
            workload_daily_pitches = workload_daily_known if workload_daily_complete else None
            workload_weekly_pitches = workload_weekly_known if workload_weekly_complete else None

            official_daily_complete = all(o.pitches is not None for o in today_games)
            official_weekly_complete = all(o.pitches is not None for o in seven_day_games)
            official_daily_known = sum(int(o.pitches) for o in today_games if o.pitches is not None)
            official_weekly_known = sum(int(o.pitches) for o in seven_day_games if o.pitches is not None)
            official_daily_pitches = official_daily_known if official_daily_complete else None
            official_weekly_pitches = official_weekly_known if official_weekly_complete else None

            status = 'Available'
            status_detail = ''
            next_available_str = 'Today'
            last_game_outing_display = 'N/A'
            official_history_complete = True

            if game_outings:
                last_game_date = get_local_date(game_outings[0].date)
                last_game_outing_display = last_game_date.strftime('%a, %b %d')

            # Group official game outings by calendar date.
            games_by_date = {}
            for outing in game_outings:
                games_by_date.setdefault(get_local_date(outing.date), []).append(outing)

            daily_outs = None
            rolling_3_day_outs = None
            innings_remaining_today_outs = None

            if rule_type == 'pitch_count':
                max_daily = rules.get('max_daily', 85)
                rest_thresholds = rules.get('rest_thresholds', [])

                # Unknown GAME pitch counts in the recent window must never be zero-filled.
                relevant_dates = [d for d in games_by_date if 0 <= (today - d).days <= 7]
                missing_official = any(
                    outing.pitches is None
                    for d in relevant_dates
                    for outing in games_by_date[d]
                )
                if missing_official:
                    status = 'Pitch Count Incomplete'
                    status_detail = 'Verify missing game pitch counts.'
                    next_available_str = 'Verify game pitch counts'
                    official_history_complete = False
                else:
                    # Required rest from prior game-pitch totals.
                    for p_date in sorted((d for d in games_by_date if d < today), reverse=True):
                        p_pitches = sum(int(o.pitches) for o in games_by_date[p_date])
                        rest_days = _required_rest_days(p_pitches, rest_thresholds)
                        next_date = p_date + timedelta(days=rest_days + 1)
                        if today < next_date:
                            status = 'Resting'
                            status_detail = f'{p_pitches} game pitches on {p_date.strftime("%a, %b %d")} require {rest_days} day(s) rest.'
                            next_available_str = next_date.strftime('%a, %b %d')
                            break

                    # Pitch Smart: no appearance as a pitcher on a third consecutive day.
                    if status == 'Available' and (today - timedelta(days=1)) in games_by_date and (today - timedelta(days=2)) in games_by_date:
                        status = 'Resting'
                        status_detail = 'Pitch Smart: do not pitch on a third consecutive day.'
                        next_available_str = (today + timedelta(days=1)).strftime('%a, %b %d')

                    if status == 'Available' and today_games:
                        if not official_daily_complete:
                            status = 'Pitch Count Incomplete'
                            status_detail = 'Verify today\'s game pitch count.'
                            next_available_str = 'Verify game pitch counts'
                            official_history_complete = False
                        else:
                            # Pitch Smart 9-12 guidance also says not to pitch in multiple
                            # games on the same day. When evaluating a specific later game,
                            # distinguish an outing from that same game from another game.
                            other_game_today = any(
                                o.game_id is None or current_game_id is None or int(o.game_id) != int(current_game_id)
                                for o in today_games
                            )
                            if other_game_today:
                                status = 'Same-Day Game Restriction'
                                status_detail = 'Pitch Smart recommends no pitching in multiple games on the same day.'
                                next_available_str = (today + timedelta(days=1)).strftime('%a, %b %d')
                            elif official_daily_pitches is not None and official_daily_pitches >= max_daily:
                                status = 'Resting'
                                status_detail = f'Daily game-pitch maximum reached ({max_daily}).'

                            if official_daily_pitches is not None:
                                rest_days = _required_rest_days(official_daily_pitches, rest_thresholds)
                                if rest_days and status == 'Available':
                                    next_available_str = (today + timedelta(days=rest_days + 1)).strftime('%a, %b %d')

                pitches_remaining = None if official_daily_pitches is None else max(0, max_daily - official_daily_pitches)
                if status in {'Resting', 'Same-Day Game Restriction'}:
                    pitches_remaining = 0

            else:
                max_daily = None
                next_day_max_outs = int(rules.get('next_day_max_outs', 9))
                max_daily_outs = int(rules.get('max_daily_outs', 18))
                rolling_max_outs = int(rules.get('rolling_3_day_max_outs', 24))

                # Under USSSA-style innings rules, missing GAME innings are the
                # eligibility-critical unknown—not missing lesson/practice innings.
                relevant_dates = [d for d in games_by_date if 0 <= (today - d).days <= 3]
                missing_innings = any(
                    baseball_innings_to_outs(outing.innings) is None
                    for d in relevant_dates
                    for outing in games_by_date[d]
                )
                if missing_innings:
                    status = 'Innings Incomplete'
                    status_detail = 'Verify missing game innings/outs.'
                    next_available_str = 'Verify game innings'
                    official_history_complete = False
                else:
                    outs_by_date = {
                        d: sum(baseball_innings_to_outs(o.innings) or 0 for o in outings)
                        for d, outings in games_by_date.items()
                    }
                    daily_outs = outs_by_date.get(today, 0)
                    previous_two_outs = sum(outs_by_date.get(today - timedelta(days=n), 0) for n in (1, 2))
                    rolling_3_day_outs = daily_outs + previous_two_outs
                    innings_remaining_today_outs = max(
                        0,
                        min(max_daily_outs - daily_outs, rolling_max_outs - rolling_3_day_outs),
                    )

                    yesterday_outs = outs_by_date.get(today - timedelta(days=1), 0)
                    if yesterday_outs > next_day_max_outs:
                        status = 'Resting'
                        status_detail = f'Pitched {outs_to_baseball_innings(yesterday_outs)} innings yesterday; more than 3.0 requires today off.'
                        next_available_str = (today + timedelta(days=1)).strftime('%a, %b %d')
                    elif all(outs_by_date.get(today - timedelta(days=n), 0) > 0 for n in (1, 2, 3)):
                        status = 'Resting'
                        status_detail = 'USSSA: pitcher must rest after pitching three consecutive days.'
                        next_available_str = (today + timedelta(days=1)).strftime('%a, %b %d')
                    elif innings_remaining_today_outs <= 0:
                        status = 'Ineligible'
                        status_detail = 'Daily or three-day innings limit reached.'
                        next_available_str = (today + timedelta(days=1)).strftime('%a, %b %d')

                pitches_remaining = None

            today_str = today.strftime('%Y-%m-%d')
            player_targets = [t for t in all_targets if t.player_id == player.id and t.local_date == today_str]
            game_target = next((t for t in player_targets if t.game_id == current_game_id), None)
            daily_target = next((t for t in player_targets if t.game_id is None), None)
            coach_target_obj = game_target or daily_target
            coach_target = coach_target_obj.target_pitches if coach_target_obj else None
            coach_target_reason = coach_target_obj.reason if coach_target_obj else None
            coach_target_reached = False
            coach_target_remaining = None

            # Coach pitch targets are pitch-based guidance, so compare them with
            # total recorded throwing workload for the day, not USSSA innings.
            if coach_target is not None and workload_daily_pitches is not None:
                coach_target_remaining = max(0, coach_target - workload_daily_pitches)
                coach_target_reached = workload_daily_pitches >= coach_target

            summary[player.name] = {
                'id': player.id,
                'name': player.name,
                'rule_type': rule_type,
                'rule_set_name': rule_set_name,
                'daily': official_daily_pitches,
                'weekly': official_weekly_pitches,
                'daily_known_pitches': official_daily_known,
                'weekly_known_pitches': official_weekly_known,
                'official_daily_pitches': official_daily_pitches,
                'official_7_day_pitches': official_weekly_pitches,
                'workload_daily_pitches': workload_daily_pitches,
                'workload_7_day_pitches': workload_weekly_pitches,
                'workload_history_complete': workload_daily_complete and workload_weekly_complete,
                'pitch_history_complete': official_history_complete and official_weekly_complete,
                'status': status,
                'status_detail': status_detail,
                'next_available': next_available_str,
                'max_daily': max_daily,
                'pitches_remaining_today': pitches_remaining,
                'last_outing_display': last_game_outing_display,
                'daily_outs': daily_outs,
                'daily_innings': outs_to_baseball_innings(daily_outs) if daily_outs is not None else None,
                'rolling_3_day_outs': rolling_3_day_outs,
                'rolling_3_day_innings': outs_to_baseball_innings(rolling_3_day_outs) if rolling_3_day_outs is not None else None,
                'innings_remaining_today_outs': innings_remaining_today_outs,
                'innings_remaining_today': outs_to_baseball_innings(innings_remaining_today_outs) if innings_remaining_today_outs is not None else None,
                'coach_target': coach_target,
                'coach_target_reason': coach_target_reason,
                'coach_target_reached': coach_target_reached,
                'coach_target_remaining': coach_target_remaining,
            }
        except Exception as e:
            print(f"Error calculating pitch count summary for player {player.name} (ID: {player.id}): {e}")
            continue
    return summary
