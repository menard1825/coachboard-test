from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import joinedload

from db import db
from models import (
    GamePitchingPlan,
    GameRotationEvent,
    Lineup,
    PitchingOuting,
    Player,
    PlayerGameAbsence,
    PlayerPitchTarget,
    Rotation,
)
from team_game_settings import regulation_innings_for_team
from lineup_service import lineup_to_dict
from utils import calculate_pitch_count_summary, get_pitching_rules_for_team


def team_now(team):
    try:
        return datetime.now(ZoneInfo(team.timezone or 'America/Indiana/Indianapolis'))
    except Exception:
        return datetime.now()


def required_positions(team):
    base = ['P', 'C', '1B', '2B', '3B', 'SS']
    outfield = ['LF', 'LCF', 'RCF', 'RF'] if int(team.outfielder_count or 3) == 4 else ['LF', 'CF', 'RF']
    return base + outfield


def _complete_alignment(alignment, required, present_names, optional_positions=None):
    if not isinstance(alignment, dict):
        return False, list(required)

    optional_positions = list(optional_positions or [])
    missing = [pos for pos in required if not alignment.get(pos)]
    positions_to_validate = list(dict.fromkeys([*required, *optional_positions]))
    names = [alignment.get(pos) for pos in positions_to_validate if alignment.get(pos)]
    required_names = [
        alignment.get(pos)
        for pos in required
        if alignment.get(pos)
    ]
    unique_and_present = (
        len(names) == len(set(names))
        and all(name in present_names for name in names)
    )

    # A defense can still be historically reliable when the team was
    # legitimately short-handed. Example: eight available players for
    # nine defensive positions, eight unique available players assigned,
    # and exactly one position left Open.
    short_handed_open_slots = max(
        0,
        len(required) - len(present_names),
    )
    accounted_for = (
        not missing
        or (
            short_handed_open_slots > 0
            and len(missing) == short_handed_open_slots
            and len(required_names) == len(present_names)
        )
    )

    valid = unique_and_present and accounted_for
    return valid, missing


# Distinct from None, which is a legitimate value for a preloaded rotation: a
# game with no rotation row queries to None, so None cannot mean "not supplied".
_UNSET = object()


def _event_order_key(event):
    """Python equivalent of ORDER BY sequence ASC, id ASC.

    SQLite sorts NULLs first in an ascending clause, so a row with a missing
    sequence or id has to sort ahead of any value rather than raising on a
    None/int comparison. The leading 0/1 flag reproduces that, instead of
    assuming both columns are always populated.
    """
    sequence = getattr(event, 'sequence', None)
    identifier = getattr(event, 'id', None)
    return (
        (1, sequence) if sequence is not None else (0, 0),
        (1, identifier) if identifier is not None else (0, 0),
    )


def _reconstruct_actual_game_rotation(rotation, events):
    """Rebuild the played defense from a rotation plan plus its events.

    Pure: issues no query, and mutates neither `rotation` nor `events` nor the
    event rows. The caller's list is never sorted in place -- sorted() returns
    a new list -- and every alignment that reaches the result is deepcopied, so
    a caller mutating what it gets back cannot reach the ORM objects.

    Ordering is load-bearing twice over, which is why this helper normalizes it
    rather than trusting its caller: `actual[inning] = ...` is last-write-wins,
    so the final event for an inning decides the alignment, and
    _actual_pitcher_names() reports pitchers in first-seen order. The ordered
    list is returned for exactly that reason.

    build_game_readiness() loads its events without an ORDER BY -- that query's
    other consumers only need bool()/any() -- and SQLite happens to return them
    in sequence order today purely because it scans
    idx_game_rotation_events_team_game_sequence_id. Normalizing here means the
    reconstruction does not depend on that accident.
    """
    ordered_events = sorted(events or [], key=_event_order_key)
    actual = deepcopy(rotation.innings or {}) if rotation else {}
    reached = set()
    for event in ordered_events:
        if event.reverted:
            continue
        reached.add(str(event.inning))
        actual[str(event.inning)] = deepcopy(event.after_alignment or {})
    if ordered_events:
        reached.add('1')
    return actual, ordered_events, reached


def actual_game_rotation(game, team_id):
    rotation = db.session.query(Rotation).filter_by(
        team_id=team_id,
        associated_game_id=game.id,
    ).first()
    events = db.session.query(GameRotationEvent).filter_by(
        team_id=team_id,
        game_id=game.id,
    ).order_by(GameRotationEvent.sequence.asc(), GameRotationEvent.id.asc()).all()
    actual, ordered_events, reached = _reconstruct_actual_game_rotation(rotation, events)
    return rotation, actual, ordered_events, reached


def _actual_pitcher_names(actual, events, reached=None):
    order = []
    reached_keys = {str(value) for value in reached} if reached is not None else None

    def add(name):
        if name and name not in order:
            order.append(name)

    for event in events or []:
        if event.reverted:
            continue
        add((event.before_alignment or {}).get('P'))
        add((event.after_alignment or {}).get('P'))

    def inning_key(item):
        try:
            return float(item[0])
        except (TypeError, ValueError):
            return 9999

    for inning, alignment in sorted((actual or {}).items(), key=inning_key):
        if reached_keys is not None and str(inning) not in reached_keys:
            continue
        add((alignment or {}).get('P'))

    return order


def _pitching_completion(expected_pitchers, outings):
    by_name = {
        outing.player.name: outing
        for outing in outings or []
        if outing.player is not None
    }
    missing = []
    for name in expected_pitchers:
        outing = by_name.get(name)
        if not outing or outing.pitches is None or outing.innings is None:
            missing.append(name)
    return not missing, missing


def build_game_readiness(game, team, *, roster=_UNSET, absences=_UNSET, rotation=_UNSET):
    """Full pregame/live readiness for one game.

    roster/absences/rotation are optional preloads, so a caller that also needs
    can_start_game() can load these three rows once and pass the same objects to
    both instead of each querying them. Callers that omit them -- Game Day's own
    helper and postgame navigation -- query exactly as before.

    The preloaded roster must be name-ordered when supplied: unlike
    can_start_game(), the ordering here reaches the response through
    lineup_missing_names and the pitching-alert list.
    """
    team_id = team.id
    if roster is _UNSET:
        roster = db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
    if absences is _UNSET:
        absences = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team_id).all()
    absent_ids = {row.player_id for row in absences}
    present = [player for player in roster if player.id not in absent_ids]
    present_names = {player.name for player in present}

    lineup = db.session.query(Lineup).filter_by(associated_game_id=game.id, team_id=team_id).first()
    if rotation is _UNSET:
        rotation = db.session.query(Rotation).filter_by(associated_game_id=game.id, team_id=team_id).first()
    plans = db.session.query(GamePitchingPlan).filter_by(game_id=game.id, team_id=team_id).all()
    events = db.session.query(GameRotationEvent).filter_by(game_id=game.id, team_id=team_id).all()
    game_outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(
        game_id=game.id,
        team_id=team_id,
    ).all()

    lineup_data = lineup_to_dict(lineup) if lineup else None
    lineup_entries = list((lineup_data or {}).get('lineup_entries') or [])
    lineup_names = [entry['name'] for entry in lineup_entries]
    lineup_player_ids = [entry['player_id'] for entry in lineup_entries if entry.get('player_id') is not None]
    present_ids = {player.id for player in present}
    unavailable_lineup_names = [
        entry['name'] for entry in lineup_entries
        if entry.get('player_id') is None or entry.get('player_id') not in present_ids
    ]
    batting_order_mode = team.batting_order_mode or 'bat_all'
    expected_lineup_count = (
        len(present)
        if batting_order_mode == 'bat_all'
        else min(int(team.fixed_lineup_size or 9), len(present))
    )
    unique_valid_ids = set(lineup_player_ids)
    lineup_ready = bool(lineup_entries) and not unavailable_lineup_names
    lineup_ready = lineup_ready and len(lineup_entries) == expected_lineup_count
    if batting_order_mode == 'bat_all':
        lineup_ready = lineup_ready and unique_valid_ids == present_ids
    else:
        lineup_ready = lineup_ready and len(unique_valid_ids) == expected_lineup_count
    lineup_count = len(lineup_entries)
    missing_lineup_names = [player.name for player in present if player.id not in unique_valid_ids]

    required = required_positions(team)
    future_required = [pos for pos in required if pos != 'P']
    innings = deepcopy(rotation.innings or {}) if rotation else {}
    regulation_innings = regulation_innings_for_team(team)
    regulation_keys = [str(number) for number in range(1, regulation_innings + 1)]
    incomplete_innings = []
    pitcher_tbd_innings = []
    complete_inning_count = 0
    for inning in regulation_keys:
        alignment = innings.get(inning)
        if inning == '1':
            valid, missing = _complete_alignment(alignment, required, present_names)
        else:
            valid, missing = _complete_alignment(
                alignment,
                future_required,
                present_names,
                optional_positions=['P'],
            )
            if valid and not (alignment or {}).get('P'):
                pitcher_tbd_innings.append(inning)

        if valid:
            complete_inning_count += 1
        else:
            incomplete_innings.append({'inning': inning, 'missing': missing})
    defense_ready = complete_inning_count == regulation_innings

    blockers = []
    if not present:
        blockers.append('No available players are marked for this game.')
    if not lineup_ready:
        if not lineup_entries:
            blockers.append('Batting lineup is not set.')
        elif unavailable_lineup_names:
            names = ', '.join(unavailable_lineup_names[:3])
            suffix = '…' if len(unavailable_lineup_names) > 3 else ''
            blockers.append(f'Remove unavailable lineup player(s): {names}{suffix}.')
        elif batting_order_mode == 'bat_all':
            blockers.append(f'Bat Everyone requires all {expected_lineup_count} available players in the lineup.')
        else:
            blockers.append(f'Fixed Lineup requires {expected_lineup_count} batter(s) for this game.')
    if not defense_ready:
        if not innings:
            blockers.append(f'Defensive rotation is not set for the {regulation_innings}-inning regulation game.')
        else:
            starting_pitcher_only = any(
                item['inning'] == '1' and item['missing'] == ['P']
                for item in incomplete_innings
            )
            if starting_pitcher_only:
                blockers.append('Choose the starting pitcher for Inning 1.')

            remaining = [
                item for item in incomplete_innings
                if not (item['inning'] == '1' and item['missing'] == ['P'])
            ]
            if remaining:
                labels = ', '.join(item['inning'] for item in remaining[:4])
                suffix = '…' if len(remaining) > 4 else ''
                blockers.append(f'Defense needs attention in regulation inning(s) {labels}{suffix}.')

    all_outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()
    all_targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team_id).all()
    rules = get_pitching_rules_for_team(team)
    pitch_summary = calculate_pitch_count_summary(
        roster,
        all_outings,
        rules,
        target_date=game.date,
        all_targets=all_targets,
        team_timezone=team.timezone,
        current_game_id=game.id,
    )
    pitching_alerts = []
    for player in present:
        summary = pitch_summary.get(player.name) or {}
        status = str(summary.get('status') or '')
        if status and status != 'Available' and player.pitcher_role and player.pitcher_role != 'Not a Pitcher':
            pitching_alerts.append({
                'name': player.name,
                'status': status,
                'detail': summary.get('status_detail'),
                'today': summary.get('official_daily_pitches'),
                'workload': summary.get('workload_daily_pitches'),
            })

    now = team_now(team)
    today = now.date()
    game_day = game.date.date()
    live_events = [event for event in events if not event.reverted]
    has_events = bool(live_events)
    has_end_game = any(event.event_type == 'End Game' for event in live_events)
    has_pitching = bool(game_outings)
    ready = not blockers

    # The rotation and events are already in hand, so reconstruct from them
    # rather than calling actual_game_rotation(), which would re-query both.
    # The helper normalizes the event order this path's query does not request.
    actual, actual_events, reached = _reconstruct_actual_game_rotation(rotation, events)
    expected_pitchers = _actual_pitcher_names(actual, actual_events, reached)
    pitching_stats_complete, pitching_missing = _pitching_completion(expected_pitchers, game_outings)
    pitching_stats_pending = bool(expected_pitchers) and not pitching_stats_complete

    if game.is_live:
        status = 'LIVE'
        status_tone = 'danger'
        primary_label = 'Resume Live Game'
    elif has_end_game and pitching_stats_pending:
        status = 'GC STATS PENDING'
        status_tone = 'warning'
        primary_label = 'Enter GameChanger Stats'
    elif has_end_game:
        status = 'COMPLETE'
        status_tone = 'success'
        primary_label = 'View Game Report'
    elif has_events and expected_pitchers and pitching_stats_complete and has_pitching:
        # Backward compatibility for older completed games created before the
        # durable End Game event existed.
        status = 'COMPLETE'
        status_tone = 'success'
        primary_label = 'View Game Report'
    elif has_events:
        status = 'NEEDS POSTGAME'
        status_tone = 'warning'
        primary_label = 'Finish Game'
    elif ready:
        status = 'READY'
        status_tone = 'success'
        primary_label = 'Open Game'
    else:
        status = 'PREP'
        status_tone = 'warning'
        primary_label = 'Prepare Game'

    if game_day < today and not has_events:
        status = 'PAST'
        status_tone = 'secondary'
        primary_label = 'Open Game'

    return {
        'game_id': game.id,
        'status': status,
        'status_tone': status_tone,
        'primary_label': primary_label,
        'ready': ready,
        'blockers': blockers,
        'present_count': len(present),
        'absent_count': len(absent_ids),
        'roster_count': len(roster),
        'lineup_ready': lineup_ready,
        'lineup_count': lineup_count,
        'lineup_expected_count': expected_lineup_count,
        'lineup_mode': batting_order_mode,
        'lineup_missing_names': missing_lineup_names,
        'lineup_unavailable_names': unavailable_lineup_names,
        'defense_ready': defense_ready,
        'defense_innings': regulation_innings,
        'defense_completed_innings': complete_inning_count,
        'regulation_innings': regulation_innings,
        'incomplete_innings': incomplete_innings,
        'pitcher_tbd_innings': pitcher_tbd_innings,
        'pitching_plan_ready': bool(plans),
        'pitching_plan_count': len(plans),
        'pitching_alerts': pitching_alerts,
        'has_events': has_events,
        'has_end_game': has_end_game,
        'has_pitching': has_pitching,
        'expected_pitchers': expected_pitchers,
        'pitching_stats_complete': pitching_stats_complete,
        'pitching_stats_pending': pitching_stats_pending,
        'pitching_missing': pitching_missing,
        'is_live': bool(game.is_live),
        'local_today': today.isoformat(),
    }


def build_actual_game_report(game, team):
    roster = db.session.query(Player).filter_by(team_id=team.id).order_by(Player.name).all()
    absences = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team.id).all()
    absent_ids = {row.player_id for row in absences}
    present_roster = [player for player in roster if player.id not in absent_ids]
    absent_names = [player.name for player in roster if player.id in absent_ids]
    player_by_name = {player.name: player for player in roster}

    def player_label(name):
        clean = str(name or '').strip()
        if not clean:
            return ''
        player = player_by_name.get(clean)
        number = str(player.number or '').strip() if player else ''
        return f'#{number} {clean}' if number else clean

    coach_names = {}
    for membership in getattr(team, 'memberships', []) or []:
        user = getattr(membership, 'user', None)
        username = str(getattr(user, 'username', '') or '').strip().lower()
        full_name = str(getattr(user, 'full_name', '') or '').strip()
        if username and full_name:
            coach_names[username] = full_name

    def coach_label(value):
        clean = str(value or '').strip()
        if not clean:
            return None
        matched = coach_names.get(clean.lower())
        if matched:
            return matched
        return clean if ' ' in clean else None

    _, actual, events, reached = actual_game_rotation(game, team.id)
    required = required_positions(team)
    present_names = {player.name for player in present_roster}
    position_order = {pos: index for index, pos in enumerate(required)}

    def inning_sort(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 999.0

    def location_map(alignment):
        result = {}
        for pos, name in (alignment or {}).items():
            if name:
                result[name] = pos
        for player in present_roster:
            result.setdefault(player.name, 'BENCH')
        return result

    def movement_rows(before, after, exclude=None):
        exclude = set(exclude or [])
        before_locations = location_map(before)
        after_locations = location_map(after)
        names = {
            *before_locations.keys(),
            *after_locations.keys(),
        }
        rows = []
        for name in names:
            if not name or name in exclude:
                continue
            old_pos = before_locations.get(name, 'BENCH')
            new_pos = after_locations.get(name, 'BENCH')
            if old_pos == new_pos:
                continue
            text = f'{player_label(name)} sits' if new_pos == 'BENCH' else f'{player_label(name)} to {new_pos}'
            rows.append({
                'name': name,
                'from': old_pos,
                'to': new_pos,
                'text': text,
            })
        rows.sort(key=lambda row: (
            1 if row['to'] == 'BENCH' else 0,
            position_order.get(row['to'], 99),
            row['name'],
        ))
        return rows

    def describe_change(event):
        if event.event_type == 'End Inning':
            return 'End of inning'
        if event.event_type == 'End Game':
            return 'Game over'

        before = event.before_alignment or {}
        after = event.after_alignment or {}

        if event.event_type == 'Pitcher Change':
            old_pitcher = before.get('P')
            new_pitcher = after.get('P')
            pieces = []
            if new_pitcher and new_pitcher != old_pitcher:
                pieces.append(f'{player_label(new_pitcher)} to the mound')
            if old_pitcher and old_pitcher != new_pitcher:
                old_destination = location_map(after).get(old_pitcher, 'BENCH')
                if old_destination == 'BENCH':
                    pieces.append(f'{player_label(old_pitcher)} to the bench')
                elif old_destination != 'P':
                    pieces.append(f'{player_label(old_pitcher)} stays in the field at {old_destination}')
            extras = movement_rows(before, after, exclude={old_pitcher, new_pitcher})
            pieces.extend(row['text'] for row in extras)
            return '. '.join(pieces) if pieces else 'Pitching change'

        if event.event_type in {'Defensive Change', 'Set New Defense'}:
            moves = movement_rows(before, after)
            return ', '.join(row['text'] for row in moves) if moves else 'Defense changed'

        return 'Game change'

    inning_keys = sorted(reached, key=inning_sort)
    innings = []
    bench_totals = {player.name: [] for player in present_roster}
    unreliable_innings = []

    for inning in inning_keys:
        alignment = actual.get(inning) or {}
        reliable, missing = _complete_alignment(alignment, required, present_names)
        if reliable:
            assigned = {alignment.get(pos) for pos in required if alignment.get(pos)}
            bench = [player.name for player in present_roster if player.name not in assigned]
            for name in bench:
                bench_totals[name].append(inning)
        else:
            bench = None
            unreliable_innings.append(inning)

        innings.append({
            'inning': inning,
            'alignment': alignment,
            'display_alignment': {
                pos: player_label(name)
                for pos, name in alignment.items()
                if name
            },
            'bench': bench,
            'display_bench': [player_label(name) for name in bench] if bench is not None else None,
            'reliable': reliable,
            'short_handed': bool(reliable and missing),
            'missing': missing,
        })

    pitching = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(
        game_id=game.id,
        team_id=team.id,
    ).order_by(PitchingOuting.id.asc()).all()
    expected_pitchers = _actual_pitcher_names(actual, events, reached)
    pitching_stats_complete, pitching_missing = _pitching_completion(expected_pitchers, pitching)
    pitching_stats_pending = bool(expected_pitchers) and not pitching_stats_complete

    changes = []
    for event in events:
        if event.reverted:
            continue
        if event.event_type in {'Defensive Change', 'Pitcher Change', 'End Inning', 'Set New Defense', 'End Game'}:
            changes.append({
                'inning': str(event.inning),
                'description': describe_change(event),
                'coach': coach_label(event.changed_by_user),
                'timestamp': event.timestamp,
            })

    bench_rows = [
        {
            'name': name,
            'display_name': player_label(name),
            'count': len(sat),
            'innings': sat,
        }
        for name, sat in bench_totals.items()
    ]
    bench_rows.sort(key=lambda row: (-row['count'], row['name']))

    lineup = db.session.query(Lineup).filter_by(
        associated_game_id=game.id,
        team_id=team.id,
    ).first()
    lineup_data = lineup_to_dict(lineup) if lineup else None
    lineup_entries = list((lineup_data or {}).get('lineup_entries') or [])
    batting_order = [
        {
            'order': index + 1,
            'name': entry.get('name') or '',
            'display_name': player_label(entry.get('name')),
        }
        for index, entry in enumerate(lineup_entries)
        if entry.get('name')
    ]

    player_labels = {player.name: player_label(player.name) for player in roster}

    return {
        'innings': innings,
        'bench_rows': bench_rows,
        'batting_order': batting_order,
        'pitching': pitching,
        'changes': changes,
        'unreliable_innings': unreliable_innings,
        'absent_names': absent_names,
        'absent_labels': [player_label(name) for name in absent_names],
        'player_labels': player_labels,
        'expected_pitchers': expected_pitchers,
        'expected_pitcher_labels': [player_label(name) for name in expected_pitchers],
        'pitching_stats_complete': pitching_stats_complete,
        'pitching_stats_pending': pitching_stats_pending,
        'pitching_missing': pitching_missing,
        'pitching_missing_labels': [player_label(name) for name in pitching_missing],
    }
