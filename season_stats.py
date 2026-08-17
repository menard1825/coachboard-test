from collections import defaultdict

from utils import baseball_innings_to_outs, outs_to_baseball_innings


def _inning_number(value):
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _add_alignment(bucket, inning, alignment, max_inning=None):
    if inning is None or inning < 1 or (max_inning is not None and inning > max_inning):
        return
    if not isinstance(alignment, dict) or not alignment:
        return
    signature = tuple(sorted((str(pos), str(name)) for pos, name in alignment.items() if name))
    if signature and signature not in bucket[inning]['signatures']:
        bucket[inning]['signatures'].add(signature)
        bucket[inning]['alignments'].append(dict(alignment))


def _live_max_played_inning(game, events):
    current = _inning_number(getattr(game, 'live_current_inning', None)) or 1
    if getattr(game, 'is_live', False):
        return current
    active = [e for e in events if not getattr(e, 'reverted', False)]
    if not active:
        return current
    has_current_play = any(
        _inning_number(e.inning) == current
        and str(e.event_type or '').lower() != 'end inning'
        for e in active
    )
    last = active[-1]
    last_is_transition = (
        str(last.event_type or '').lower() == 'end inning'
        and _inning_number(last.inning) == current
    )
    return current - 1 if last_is_transition and not has_current_play and current > 1 else current


def build_game_inning_records(roster, rotations, rotation_events, games, game_absences):
    roster_names = {p.name for p in roster}
    player_id_by_name = {p.name: p.id for p in roster}
    rotations_by_game = {}
    for rotation in rotations or []:
        if rotation.associated_game_id:
            rotations_by_game.setdefault(rotation.associated_game_id, rotation)

    events_by_game = defaultdict(list)
    for event in rotation_events or []:
        if event.game_id and not getattr(event, 'reverted', False):
            events_by_game[event.game_id].append(event)
    for events in events_by_game.values():
        events.sort(key=lambda item: (item.sequence or 0, item.id or 0))

    absent_by_game = defaultdict(set)
    for row in game_absences or []:
        absent_by_game[row.game_id].add(row.player_id)

    records = []
    for game in games or []:
        rotation = rotations_by_game.get(game.id)
        events = events_by_game.get(game.id, [])
        source = 'live' if events else 'legacy'
        innings = defaultdict(lambda: {'alignments': [], 'signatures': set()})
        planned = rotation.innings if rotation and isinstance(rotation.innings, dict) else {}

        if events:
            max_inning = _live_max_played_inning(game, events)
            for raw_inning, alignment in planned.items():
                _add_alignment(innings, _inning_number(raw_inning), alignment, max_inning)
            for event in events:
                event_inning = _inning_number(event.inning)
                if str(event.event_type or '').lower() == 'end inning':
                    _add_alignment(innings, event_inning - 1 if event_inning else None, event.before_alignment, max_inning)
                    _add_alignment(innings, event_inning, event.after_alignment, max_inning)
                else:
                    _add_alignment(innings, event_inning, event.before_alignment, max_inning)
                    _add_alignment(innings, event_inning, event.after_alignment, max_inning)
        else:
            for raw_inning, alignment in planned.items():
                _add_alignment(innings, _inning_number(raw_inning), alignment)

        absent_ids = absent_by_game.get(game.id, set())
        available_names = {name for name, pid in player_id_by_name.items() if pid not in absent_ids}
        inning_rows = []
        for inning in sorted(innings):
            snapshots = innings[inning]['alignments']
            field_names = set()
            positions_by_player = defaultdict(set)
            for alignment in snapshots:
                for position, player_name in alignment.items():
                    if player_name and player_name in roster_names:
                        field_names.add(player_name)
                        positions_by_player[player_name].add(position)
            if field_names:
                inning_rows.append({
                    'inning': inning,
                    'field_names': field_names,
                    'available_names': available_names,
                    'positions_by_player': dict(positions_by_player),
                })

        if inning_rows:
            records.append({
                'game': game,
                'source': source,
                'innings': inning_rows,
                'absent_ids': absent_ids,
            })
    return records


def build_season_usage_dashboard(roster, rotations, rotation_events, games, game_absences,
                                 practice_plans, practice_absences, pitching_outings):
    game_records = build_game_inning_records(roster, rotations, rotation_events, games, game_absences)
    id_by_name = {p.name: p.id for p in roster}
    rows = {
        p.id: {
            'player_id': p.id, 'name': p.name, 'available_games': 0,
            'defensive_games': 0, 'field_innings': 0, 'bench_innings': 0,
            'positions': defaultdict(int), 'live_field_innings': 0,
            'legacy_field_innings': 0,
        }
        for p in roster
    }

    live_games = legacy_games = live_innings = legacy_innings = 0
    for record in game_records:
        if record['source'] == 'live':
            live_games += 1; live_innings += len(record['innings'])
        else:
            legacy_games += 1; legacy_innings += len(record['innings'])
        field_names_for_game = set()
        for p in roster:
            if p.id not in record['absent_ids']:
                rows[p.id]['available_games'] += 1
        for inning in record['innings']:
            for name in inning['field_names']:
                pid = id_by_name.get(name)
                if pid not in rows:
                    continue
                row = rows[pid]
                row['field_innings'] += 1
                row[f"{record['source']}_field_innings"] += 1
                field_names_for_game.add(name)
                for pos in inning['positions_by_player'].get(name, set()):
                    row['positions'][pos] += 1
            for name in inning['available_names'] - inning['field_names']:
                pid = id_by_name.get(name)
                if pid in rows:
                    rows[pid]['bench_innings'] += 1
        for name in field_names_for_game:
            pid = id_by_name.get(name)
            if pid in rows:
                rows[pid]['defensive_games'] += 1

    game_ids = {g.id for g in games}
    game_missed = defaultdict(int)
    for a in game_absences or []:
        if a.game_id in game_ids:
            game_missed[a.player_id] += 1
    practice_ids = {p.id for p in practice_plans or []}
    practice_missed = defaultdict(int)
    for a in practice_absences or []:
        if a.practice_plan_id in practice_ids:
            practice_missed[a.player_id] += 1

    total_games = len(games or [])
    total_practices = len(practice_plans or [])
    attendance = []
    present_total = opportunity_total = 0
    for p in roster:
        gp = max(0, total_games - game_missed[p.id])
        pp = max(0, total_practices - practice_missed[p.id])
        present_total += gp; opportunity_total += total_games
        attendance.append({
            'player_id': p.id, 'name': p.name,
            'games_present': gp, 'games_total': total_games, 'games_missed': game_missed[p.id],
            'game_attendance_pct': round(gp / total_games * 100) if total_games else None,
            'practices_present': pp, 'practices_total': total_practices, 'practices_missed': practice_missed[p.id],
            'practice_attendance_pct': round(pp / total_practices * 100) if total_practices else None,
        })
    attendance_by_id = {r['player_id']: r for r in attendance}

    player_usage = []
    for p in roster:
        row = rows[p.id]
        opportunities = row['field_innings'] + row['bench_innings']
        bench_pct = round(row['bench_innings'] / opportunities * 100) if opportunities else None
        positions = dict(sorted(row['positions'].items()))
        flags = []
        if opportunities >= 6 and bench_pct is not None and bench_pct >= 30:
            flags.append('High bench usage')
        if row['field_innings'] >= 6 and len(positions) <= 1:
            flags.append('Limited position variety')
        catcher = positions.get('C', 0)
        if row['field_innings'] >= 6 and catcher >= max(4, round(row['field_innings'] * .45)):
            flags.append('Heavy catcher workload')
        att = attendance_by_id[p.id]
        if att['games_total'] >= 4 and att['game_attendance_pct'] is not None and att['game_attendance_pct'] < 80:
            flags.append('Lower game availability')
        player_usage.append({
            **{k: v for k, v in row.items() if k != 'positions'},
            'bench_pct': bench_pct, 'position_variety': len(positions),
            'positions': positions, 'flags': flags,
            'game_attendance_pct': att['game_attendance_pct'],
            'practice_attendance_pct': att['practice_attendance_pct'],
        })

    selected_game_ids = {g.id for g in games}
    selected_date_opponents = {(g.date.date(), g.opponent) for g in games if g.date}
    game_outings = []
    for o in pitching_outings or []:
        if str(o.outing_type or 'Game').strip().lower() != 'game':
            continue
        if o.game_id in selected_game_ids or (o.game_id is None and o.date and (o.date.date(), o.opponent) in selected_date_opponents):
            game_outings.append(o)

    pitch = defaultdict(lambda: {'appearances': 0, 'starts': 0, 'relief': 0, 'pitches': 0,
                                 'pitch_known': 0, 'outs': 0, 'innings_known': 0, 'missing_innings': False})
    for o in game_outings:
        r = pitch[o.player_id]; r['appearances'] += 1
        if 'start' in str(o.pitcher_type or '').lower(): r['starts'] += 1
        else: r['relief'] += 1
        if o.pitches is not None:
            try: r['pitches'] += int(o.pitches); r['pitch_known'] += 1
            except (TypeError, ValueError): pass
        outs = baseball_innings_to_outs(o.innings)
        if outs is None: r['missing_innings'] = True
        else: r['outs'] += outs; r['innings_known'] += 1

    team_pitches = sum(r['pitches'] for r in pitch.values())
    team_outs = sum(r['outs'] for r in pitch.values())
    pitching_usage = []
    for p in roster:
        r = pitch.get(p.id)
        if not r or not r['appearances']:
            continue
        pitching_usage.append({
            'player_id': p.id, 'name': p.name, 'appearances': r['appearances'],
            'starts': r['starts'], 'relief_appearances': r['relief'],
            'total_pitches': r['pitches'], 'total_innings': outs_to_baseball_innings(r['outs']),
            'innings_history_complete': not r['missing_innings'],
            'pitches_per_appearance': round(r['pitches'] / r['pitch_known'], 1) if r['pitch_known'] else None,
            'innings_per_appearance': round((r['outs'] / 3) / r['innings_known'], 2) if r['innings_known'] else None,
            'pitch_share_pct': round(r['pitches'] / team_pitches * 100) if team_pitches else None,
            'outs_share_pct': round(r['outs'] / team_outs * 100) if team_outs else None,
        })

    insights = []
    eligible_bench = [r for r in player_usage if r['bench_pct'] is not None and r['field_innings'] + r['bench_innings'] >= 6]
    if len(eligible_bench) >= 2:
        spread = max(r['bench_pct'] for r in eligible_bench) - min(r['bench_pct'] for r in eligible_bench)
        if spread >= 20:
            insights.append({'level': 'attention', 'title': 'Bench usage varies across the roster',
                             'detail': f'There is a {spread}-point spread between the highest and lowest recorded bench percentages.'})
    if pitching_usage:
        key = 'pitch_share_pct' if team_pitches else 'outs_share_pct'
        top = max(pitching_usage, key=lambda r: r.get(key) or 0)
        if (top.get(key) or 0) >= 40 and len(pitching_usage) >= 3:
            insights.append({'level': 'attention', 'title': 'Pitching workload is concentrated',
                             'detail': f"{top['name']} accounts for about {top[key]}% of the recorded team pitching workload in this view."})
    if legacy_games:
        insights.append({'level': 'info', 'title': 'Some defensive data is estimated',
                         'detail': f'{legacy_games} game(s) use saved legacy rotations because no Live Game event history exists.'})

    avg_available = None
    if game_records:
        avg_available = round(sum(len(roster) - len(r['absent_ids']) for r in game_records) / len(game_records), 1)

    player_usage.sort(key=lambda r: r['name'])
    attendance.sort(key=lambda r: r['name'])
    pitching_usage.sort(key=lambda r: (-r['appearances'], r['name']))
    return {
        'summary': {
            'games': total_games, 'games_with_defensive_data': len(game_records), 'practices': total_practices,
            'team_attendance_pct': round(present_total / opportunity_total * 100) if opportunity_total else None,
            'avg_available_per_game': avg_available,
            'defensive_innings_recorded': live_innings + legacy_innings,
            'team_pitching_innings': outs_to_baseball_innings(team_outs),
            'team_pitching_pitches': team_pitches,
        },
        'player_usage': player_usage, 'attendance': attendance, 'pitching_usage': pitching_usage,
        'insights': insights,
        'data_quality': {
            'live_games': live_games, 'legacy_games': legacy_games,
            'live_innings': live_innings, 'legacy_innings': legacy_innings,
            'note': 'Live Game history is authoritative when available. Legacy games use the saved defensive rotation as an estimate. Mid-inning substitutions count each player who appeared in that inning once.'
        },
    }
