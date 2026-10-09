"""Use Previous Game Setup: what a coach's last game can give today's game.

Read-only. This module finds the most recent earlier game that has a batting
order or a 1st-inning defense, and works out exactly what of it fits today's
game. It never writes: the browser applies the result through the same
canonical paths the Prepare Game page already uses -- /add_lineup or
/edit_lineup (validate_lineup_payload + sync_lineup) for the batting order,
and the shared CBPregameRotation queue (/save_rotation, with its duplicate
check and game write lock) for the defense. The earlier game's rows are only
ever read.

The rules match the Saved Defense ("fielders only") rules in
static/js/live_game_board_prep.js, so both ways of filling a defense behave
the same:

* The pitcher is never copied. Today's 1st-inning P, if one is already
  chosen, stays; otherwise P stays open for the coach to choose.
* A player who is Out today, no longer on the roster, today's pitcher, or
  already placed is not copied; that position is left Open and the preview
  says why. So the result can never hold one player twice.
* Only the 1st inning (the starting defense) is filled. Later innings are
  left exactly as they are.
"""

import json

from db import db
from game_day_helpers import required_positions, roster_name
from lineup_service import lineup_to_dict
from models import Game, Lineup, Player, PlayerGameAbsence, Rotation


SKIP_REASONS = {
    'out': 'Out today',
    'roster': 'No longer on the roster',
    'pitching': "Today's pitcher",
    'placed': 'Already placed',
}


def _innings(rotation):
    innings = rotation.innings if rotation is not None else None
    if isinstance(innings, str):
        try:
            innings = json.loads(innings)
        except ValueError:
            innings = None
    return innings if isinstance(innings, dict) else {}


def _starting_alignment(rotation):
    alignment = _innings(rotation).get('1')
    if not isinstance(alignment, dict):
        return {}
    return {
        str(pos): str(name or '').strip()
        for pos, name in alignment.items()
        if str(name or '').strip()
    }


def _has_fielders(alignment):
    return any(pos != 'P' for pos in alignment)


def _date_label(value, today=None):
    label = f'{value:%a}, {value:%b} {value.day}'
    if today is not None and value.year != today.year:
        label += f', {value.year}'
    return label


def _earlier_games(game):
    return db.session.query(Game).filter(
        Game.team_id == game.team_id,
        Game.id != game.id,
        db.or_(
            Game.date < game.date,
            db.and_(Game.date == game.date, Game.id < game.id),
        ),
    ).order_by(Game.date.desc(), Game.id.desc())


def find_previous_setup_game(game):
    """The most recent earlier game with a batting order or a starting
    defense, with that game's Lineup and Rotation rows (either may be None).
    Returns (None, None, None) when no earlier game has either."""
    earlier = _earlier_games(game).all()
    if not earlier:
        return None, None, None
    ids = [item.id for item in earlier]
    lineups = {
        row.associated_game_id: row
        for row in db.session.query(Lineup).filter(
            Lineup.team_id == game.team_id,
            Lineup.associated_game_id.in_(ids),
        ).all()
    }
    rotations = {
        row.associated_game_id: row
        for row in db.session.query(Rotation).filter(
            Rotation.team_id == game.team_id,
            Rotation.associated_game_id.in_(ids),
        ).all()
    }
    for candidate in earlier:
        lineup = lineups.get(candidate.id)
        if lineup is not None and not (lineup_to_dict(lineup) or {}).get('lineup_entries'):
            lineup = None
        rotation = rotations.get(candidate.id)
        if rotation is not None and not _has_fielders(_starting_alignment(rotation)):
            rotation = None
        if lineup is not None or rotation is not None:
            return candidate, lineup, rotation
    return None, None, None


def source_summary(game):
    """Small label for the Prepare Game button, or None when there is no
    earlier game to copy from."""
    source, _lineup, _rotation = find_previous_setup_game(game)
    if source is None:
        return None
    return {
        'game_id': source.id,
        'opponent': source.opponent,
        'date_label': _date_label(source.date, game.date),
    }


def _plan_lineup(team, source_lineup, present, roster_by_id, roster_by_name):
    entries = (lineup_to_dict(source_lineup) or {}).get('lineup_entries') or []
    present_ids = {player.id for player in present}
    batters = []
    skipped = []
    used = set()
    for entry in entries:
        player = roster_by_id.get(entry.get('player_id'))
        if player is None and entry.get('player_id') is None:
            player = roster_by_name.get(str(entry.get('name') or '').strip())
        name = player.name if player is not None else (entry.get('name') or entry.get('player_name_snapshot') or 'Unknown player')
        if player is None:
            skipped.append({'name': name, 'reason': 'roster', 'label': SKIP_REASONS['roster']})
        elif player.id not in present_ids:
            skipped.append({'name': name, 'reason': 'out', 'label': SKIP_REASONS['out']})
        elif player.id not in used:
            used.add(player.id)
            batters.append({'player_id': player.id, 'name': player.name})

    mode = team.batting_order_mode or 'bat_all'
    added = []
    trimmed = []
    if mode == 'bat_all':
        # Bat Everyone: everyone playing today bats. Anyone who wasn't in the
        # last batting order goes to the bottom, where the coach can move them.
        for player in present:
            if player.id not in used:
                used.add(player.id)
                added.append({'player_id': player.id, 'name': player.name})
        expected = len(present)
    else:
        expected = min(int(team.fixed_lineup_size or 9), len(present))
        trimmed = batters[expected:]
        batters = batters[:expected]

    order = batters + added
    return {
        'available': bool(entries),
        'title': source_lineup.title if source_lineup is not None else None,
        'mode': mode,
        'expected_count': expected,
        'batters': [
            {**item, 'order': index, 'added': index > len(batters)}
            for index, item in enumerate(order, start=1)
        ],
        'player_ids': [item['player_id'] for item in order],
        'added': added,
        'skipped': skipped,
        'trimmed': trimmed,
        'short_by': max(0, expected - len(order)),
    }


def _plan_defense(team, source_rotation, current_alignment, rostered, available):
    source = _starting_alignment(source_rotation)
    positions = required_positions(team)
    fielding = [pos for pos in positions if pos != 'P']

    current_pitcher = current_alignment.get('P') or ''
    proposed = {'P': current_pitcher} if current_pitcher else {}
    placed = {current_pitcher} if current_pitcher else set()
    rows = []
    open_count = 0
    for pos in fielding:
        name = source.get(pos, '')
        reason = ''
        if name:
            if name not in rostered:
                reason = 'roster'
            elif name not in available:
                reason = 'out'
            elif name == current_pitcher:
                reason = 'pitching'
            elif name in placed:
                reason = 'placed'
        if name and not reason:
            proposed[pos] = name
            placed.add(name)
            rows.append({'position': pos, 'player': name, 'status': 'copy'})
        else:
            open_count += 1
            rows.append({
                'position': pos,
                'player': name or None,
                'status': 'open',
                'reason': reason or 'empty',
                'label': SKIP_REASONS.get(reason, 'Open last game'),
            })

    # Positions last game used that today's field doesn't (3 vs 4 outfielders).
    unused = [
        {'position': pos, 'player': name}
        for pos, name in source.items()
        if pos != 'P' and pos not in fielding
    ]
    current_fielders = {pos: name for pos, name in current_alignment.items() if pos != 'P'}
    return {
        'available': _has_fielders(source),
        'positions': rows,
        'proposed': proposed,
        'copied_count': len(rows) - open_count,
        'open_count': open_count,
        'unused_positions': unused,
        'previous_pitcher': source.get('P') or None,
        'today_pitcher': current_pitcher or None,
        'current_alignment': current_alignment,
        'current_fielder_count': len(current_fielders),
        'replaces_current': bool(current_fielders),
    }


def build_previous_setup_preview(game, team):
    """Everything the Use Previous Game Setup sheet shows, computed against
    today's roster, today's availability and today's current plan."""
    if game.is_live:
        return {'available': False, 'reason': 'live', 'message': 'The game has started. Use Live Game controls.'}

    source, source_lineup, source_rotation = find_previous_setup_game(game)
    if source is None:
        return {
            'available': False,
            'reason': 'none',
            'message': 'No earlier game has a batting order or starting defense to copy yet.',
        }

    roster = db.session.query(Player).filter_by(team_id=team.id).order_by(Player.name).all()
    absent_ids = {
        row.player_id
        for row in db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team.id).all()
    }
    present = [player for player in roster if player.id not in absent_ids]
    roster_by_id = {player.id: player for player in roster}
    names = [roster_name(player) for player in roster]
    roster_by_name = {
        roster_name(player): player
        for player in roster
        if names.count(roster_name(player)) == 1
    }
    rostered = set(names)
    available = {roster_name(player) for player in present}

    current_lineup = db.session.query(Lineup).filter_by(associated_game_id=game.id, team_id=team.id).first()
    current_lineup_data = lineup_to_dict(current_lineup) if current_lineup is not None else None
    current_rotation = db.session.query(Rotation).filter_by(associated_game_id=game.id, team_id=team.id).first()

    lineup = _plan_lineup(team, source_lineup, present, roster_by_id, roster_by_name)
    lineup['current_id'] = current_lineup.id if current_lineup is not None else None
    lineup['current_title'] = current_lineup.title if current_lineup is not None else None
    lineup['current_count'] = len((current_lineup_data or {}).get('lineup_entries') or [])
    lineup['replaces_current'] = lineup['current_count'] > 0

    defense = _plan_defense(team, source_rotation, _starting_alignment(current_rotation), rostered, available)

    return {
        'available': True,
        'game_id': game.id,
        'game_opponent': game.opponent,
        'source': {
            'game_id': source.id,
            'opponent': source.opponent,
            'date_label': _date_label(source.date, game.date),
        },
        'present_count': len(present),
        'lineup': lineup,
        'defense': defense,
    }
