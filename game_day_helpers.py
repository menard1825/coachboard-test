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


def _complete_alignment(alignment, required, present_names):
    if not isinstance(alignment, dict):
        return False, list(required)
    missing = [pos for pos in required if not alignment.get(pos)]
    names = [alignment.get(pos) for pos in required if alignment.get(pos)]
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
    innings = deepcopy(rotation.innings or {}) if rotation else {}
    inning_keys = sorted(innings.keys(), key=lambda value: float(value)) if innings else []
    incomplete_innings = []
    for inning in inning_keys:
        valid, missing = _complete_alignment(innings.get(inning), required, present_names)
        if not valid:
            incomplete_innings.append({'inning': inning, 'missing': missing})
    defense_ready = bool(inning_keys) and not incomplete_innings

    blockers = []
    if not present:
        blockers.append('No available players are marked for this game.')
    if not lineup_ready:
        blockers.append('Batting lineup is not ready.')
    if not defense_ready:
        if not inning_keys:
            blockers.append('Defensive rotation is not set.')
        else:
            labels = ', '.join(item['inning'] for item in incomplete_innings[:4])
            blockers.append(f'Defense is incomplete in inning(s) {labels}.')

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
    has_events = bool(events)
    has_pitching = bool(game_outings)
    ready = not blockers

    if game.is_live:
        status = 'LIVE'
        status_tone = 'danger'
        primary_label = 'Resume Live Game'
    elif has_events and has_pitching:
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
        'defense_innings': len(inning_keys),
        'incomplete_innings': incomplete_innings,
        'pitching_plan_ready': bool(plans),
        'pitching_plan_count': len(plans),
        'pitching_alerts': pitching_alerts,
        'has_events': has_events,
        'has_pitching': has_pitching,
        'is_live': bool(game.is_live),
        'local_today': today.isoformat(),
    }


def build_actual_game_report(game, team):
    roster = db.session.query(Player).filter_by(team_id=team.id).order_by(Player.name).all()
    _, actual, events, reached = actual_game_rotation(game, team.id)
    required = required_positions(team)
    roster_names = {player.name for player in roster}

    def inning_sort(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 999.0

    inning_keys = sorted(reached, key=inning_sort)
    innings = []
    bench_totals = {player.name: [] for player in roster}
    unreliable_innings = []

    for inning in inning_keys:
        alignment = actual.get(inning) or {}
        reliable, missing = _complete_alignment(alignment, required, roster_names)
        if reliable:
            assigned = {alignment.get(pos) for pos in required if alignment.get(pos)}
            bench = [player.name for player in roster if player.name not in assigned]
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

    changes = []
    for event in events:
        if event.reverted:
            continue
        if event.event_type in {'Defensive Change', 'Pitcher Change', 'End Inning', 'Set New Defense'}:
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
    }
