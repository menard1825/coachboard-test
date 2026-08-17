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
    valid = (
        not missing
        and len(names) == len(set(names))
        and all(name in present_names for name in names)
    )
    return valid, missing


def actual_game_rotation(game, team_id):
    rotation = db.session.query(Rotation).filter_by(
        team_id=team_id,
        associated_game_id=game.id,
    ).first()
    actual = deepcopy(rotation.innings or {}) if rotation else {}
    events = db.session.query(GameRotationEvent).filter_by(
        team_id=team_id,
        game_id=game.id,
    ).order_by(GameRotationEvent.sequence.asc(), GameRotationEvent.id.asc()).all()
    reached = set()
    for event in events:
        if event.reverted:
            continue
        reached.add(str(event.inning))
        actual[str(event.inning)] = deepcopy(event.after_alignment or {})
    if events:
        reached.add('1')
    return rotation, actual, events, reached


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


def build_game_readiness(game, team):
    team_id = team.id
    roster = db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
    absences = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team_id).all()
    absent_ids = {row.player_id for row in absences}
    present = [player for player in roster if player.id not in absent_ids]
    present_names = {player.name for player in present}

    lineup = db.session.query(Lineup).filter_by(associated_game_id=game.id, team_id=team_id).first()
    rotation = db.session.query(Rotation).filter_by(associated_game_id=game.id, team_id=team_id).first()
    plans = db.session.query(GamePitchingPlan).filter_by(game_id=game.id, team_id=team_id).all()
    events = db.session.query(GameRotationEvent).filter_by(game_id=game.id, team_id=team_id).all()
    game_outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(
        game_id=game.id,
        team_id=team_id,
    ).all()

    lineup_names = list(lineup.lineup_positions or []) if lineup else []
    lineup_ready = bool(lineup_names) and all(name in present_names for name in lineup_names)
    lineup_count = len(lineup_names)

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
        blockers.append('Batting lineup is not ready.')
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

    _, actual, actual_events, reached = actual_game_rotation(game, team_id)
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

    _, actual, events, reached = actual_game_rotation(game, team.id)
    required = required_positions(team)
    present_names = {player.name for player in present_roster}

    def inning_sort(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 999.0

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
            'bench': bench,
            'reliable': reliable,
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
                'type': event.event_type,
                'changed_by': event.changed_by_user,
                'timestamp': event.timestamp,
            })

    bench_rows = [
        {'name': name, 'count': len(sat), 'innings': sat}
        for name, sat in bench_totals.items()
    ]
    bench_rows.sort(key=lambda row: (-row['count'], row['name']))

    return {
        'innings': innings,
        'bench_rows': bench_rows,
        'pitching': pitching,
        'changes': changes,
        'unreliable_innings': unreliable_innings,
        'absent_names': absent_names,
        'expected_pitchers': expected_pitchers,
        'pitching_stats_complete': pitching_stats_complete,
        'pitching_stats_pending': pitching_stats_pending,
        'pitching_missing': pitching_missing,
    }
