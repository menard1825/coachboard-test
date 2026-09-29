
from db import db
from game_day_helpers import duplicate_assignment_message, field_order, required_positions
from game_pitching_rules import rule_settings_payload
from models import Player, PlayerGameAbsence, Rotation


# Distinct from None, which is a legitimate value for a preloaded rotation: a
# game with no rotation row queries to None, so None cannot mean "not supplied".
_UNSET = object()


def can_start_game(game, team, *, roster=_UNSET, absences=_UNSET, rotation=_UNSET,
                   rule_payload=_UNSET):
    """Return the one authoritative first-pitch readiness contract.

    This intentionally answers a narrower question than build_game_readiness():
    can the coach safely start Live Game right now? Batting order, later innings,
    pitching plans, and fair-play planning do not block first pitch.

    roster/absences/rotation/rule_payload are optional preloads. They exist so
    one caller -- /api/game-day/<id>/readiness -- can resolve these once and hand
    the same objects to this function and to build_game_readiness(), instead of
    each querying them separately. Omit them and this function queries exactly as
    it always has, which is what /api/live-game/<id>/start relies on.

    A supplied rule_payload must have been resolved for this same game: it is
    consumed only for the 'effective' check below, and a payload from another
    game would silently answer the first-pitch question with the wrong rules.

    A preloaded roster may be ordered or unordered: everything below uses it for
    membership and set comparisons only, never for sequence.
    """
    team_id = team.id
    if roster is _UNSET:
        roster = db.session.query(Player).filter_by(team_id=team_id).all()
    if absences is _UNSET:
        absences = db.session.query(PlayerGameAbsence).filter_by(
            game_id=game.id,
            team_id=team_id,
        ).all()
    absent_ids = {row.player_id for row in absences}
    present = [player for player in roster if player.id not in absent_ids]
    present_names = {player.name for player in present}
    roster_names = {player.name for player in roster}

    hard_stops = []
    if not present:
        hard_stops.append('Mark at least one player available for this game.')

    if rotation is _UNSET:
        rotation = db.session.query(Rotation).filter_by(
            associated_game_id=game.id,
            team_id=team_id,
        ).first()
    stored = (rotation.innings or {}).get('1', {}) if rotation else {}
    required = required_positions(team)
    inning_one = normalized_inning_one(stored, required)

    # Hard stops: the 1st-inning record would be invalid, so the coach must
    # fix it. Each says exactly what is wrong.
    if not inning_one.get('P'):
        hard_stops.append('Choose the starting pitcher for the 1st inning.')
    duplicate = duplicate_assignment_message(inning_one, '1')
    if duplicate:
        hard_stops.append(duplicate)
    for position in sorted(inning_one, key=field_order):
        name = inning_one[position]
        if name not in roster_names:
            hard_stops.append(f'{name} is at {position} in the 1st inning but is not on the roster.')
        elif name not in present_names:
            hard_stops.append(f'{name} is marked Out but is at {position} in the 1st inning.')

    if rule_payload is _UNSET:
        rule_payload = rule_settings_payload(team, game)
    if not rule_payload.get('effective'):
        hard_stops.append('Select the game pitching rules / tracking method.')

    # An open fielding position is a baseball choice, not an error: Start asks.
    open_positions = [position for position in required if position != 'P' and position not in inning_one]
    placed = set(inning_one.values())
    bench = sorted(player.name for player in present if player.name not in placed)

    return {
        # `ready`/`missing` keep their meaning for existing consumers: can
        # the Start button be used, and what must be fixed first. An open
        # position no longer makes a game "not ready" -- Start asks about it.
        'ready': not hard_stops,
        'missing': list(hard_stops),
        'hard_stops': list(hard_stops),
        'inning_one': inning_one,
        'open_positions': open_positions,
        'open_question': open_position_question(open_positions, len(present), len(required), bench),
    }


def normalized_inning_one(alignment, required):
    """The filled positions of a 1st-inning defense, names trimmed."""
    alignment = alignment if isinstance(alignment, dict) else {}
    return {
        position: str(alignment.get(position)).strip()
        for position in required
        if str(alignment.get(position) or '').strip()
    }


_COUNT_WORDS = {1: 'one', 2: 'two', 3: 'three', 4: 'four'}


def _listed(items):
    items = list(items)
    if len(items) <= 2:
        return ' and '.join(items)
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def open_position_question(open_positions, present_count, position_count, bench):
    """What Start asks when fielding positions are open in the 1st inning."""
    if not open_positions:
        return None
    listed = _listed(open_positions)
    verb = 'is' if len(open_positions) == 1 else 'are'
    parts = []
    short = position_count - present_count
    if short > 0:
        count = _COUNT_WORDS.get(short, str(short))
        parts.append(
            f'Only {present_count} players are available, so {count} '
            f'position{" is" if short == 1 else "s are"} open.'
        )
    parts.append(f'{listed} {verb} open for the 1st inning.')
    if bench:
        parts.append(f'On the bench: {", ".join(bench)}.')
    return {
        'title': f'1st inning: {listed} {verb} open',
        'message': ' '.join(parts),
        'positions': list(open_positions),
        'start_label': f'Start with {listed} Open',
    }
