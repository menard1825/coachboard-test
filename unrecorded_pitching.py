"""Pitching that happened but has no entered pitch count yet.

A game's pitch counts are entered when it ends (or later, from GameChanger).
Until then the only PitchingOuting rows are the ones already saved, so a
pitcher who is on the mound right now -- or who pitched earlier in a game
whose counts are still to come -- has no outing at all, and the pitch-count
summary would read "0 pitches today · Available".

CoachBoard does know who pitched: the live game's own history (the same
reading End Game uses to list its pitchers). This module turns that into
placeholder game outings with an UNKNOWN count -- never a zero -- so the
summary reports "Pitching now" or "Pitched today — count needed" and keeps
the pitcher out of Ready until a count is entered.

Nothing is stored: these are read-only stand-ins. A saved outing for the same
game and player (with or without a count) always wins.

Each pitcher is checked on their own: a game where one pitcher's count is
saved and another's isn't still reports the missing one. A confirmed 0 is a
saved count, never a missing one; a reopened game keeps its saved counts.

Cost: one SQL statement per request when no other started game falls in
the look-back window, cached for the request. Otherwise the events and plans
of those games are read once, in bulk (two statements) -- never per game or
per player.
"""

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import g, has_app_context
from sqlalchemy import exists, or_

from db import db
from live_history import _event_order_key, gameplay_events
from models import Game, GameRotationEvent, Player, Rotation


# Outings older than this do not change a day's eligibility (pitch-count
# rules look back 7 days; innings rules 3).
LOOKBACK_DAYS = 8


def local_today(team):
    """Today's calendar date where the team plays."""
    try:
        return datetime.now(ZoneInfo(getattr(team, 'timezone', None) or 'America/Indiana/Indianapolis')).date()
    except ZoneInfoNotFoundError:
        return datetime.now().date()


def _inning_number(value):
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _pitchers(game, plan, events):
    """Who pitched, in first-appearance order -- End Game's reading
    (live_game_pitching_api._actual_pitcher_order): the plan with every
    unreverted event applied, for the innings the game reached, plus every
    pitcher an event replaced. So the starter counts before any change, and
    a pitcher removed earlier still counts.
    Returns (pitchers, pitcher now on the mound)."""
    actual = deepcopy(plan or {})
    for event in sorted(events, key=_event_order_key):
        if not event.reverted:
            actual[str(event.inning)] = deepcopy(event.after_alignment or {})

    order = []

    def add(name):
        if name and name not in order:
            order.append(name)

    for event in gameplay_events(events):
        add((event.before_alignment or {}).get('P'))
        add((event.after_alignment or {}).get('P'))
    reached = _inning_number(game.live_current_inning or '1') or 1.0
    for inning, alignment in sorted(actual.items(), key=lambda item: _inning_number(item[0]) or 9999):
        number = _inning_number(inning)
        if number is not None and number <= reached:
            add((alignment or {}).get('P'))
    on_mound = (actual.get(str(game.live_current_inning or '1')) or {}).get('P') or ''
    add(on_mound)
    return order, on_mound


def _request_cache():
    return g.setdefault('_cb_unrecorded_pitching', {}) if has_app_context() else {}


def _started_games(team_id):
    """Every game a live game started (live now, finished, or reopened).
    Whether each of its pitchers has a saved count is decided per pitcher
    below, from the outings the caller already loaded. One statement,
    cached for the request."""
    cache = _request_cache()
    key = ('games', team_id)
    if key not in cache:
        cache[key] = db.session.query(Game).filter(
            Game.team_id == team_id,
            or_(
                Game.is_live.is_(True),
                exists().where(GameRotationEvent.game_id == Game.id),
            ),
        ).all()
    return cache[key]


def _pitchers_by_game(team_id, games):
    """{game id: (pitchers, pitcher now on the mound)}, reading the events
    and plans of games not seen yet in this request -- one statement each,
    for all of those games at once, never one per game or per player."""
    cache = _request_cache()
    known = cache.setdefault(('pitchers', team_id), {})
    missing = [game for game in games if game.id not in known]
    if missing:
        ids = [game.id for game in missing]
        events = defaultdict(list)
        for event in db.session.query(GameRotationEvent).filter(
            GameRotationEvent.team_id == team_id, GameRotationEvent.game_id.in_(ids),
        ).all():
            events[event.game_id].append(event)
        plans = {
            rotation.associated_game_id: rotation.innings or {}
            for rotation in db.session.query(Rotation).filter(
                Rotation.team_id == team_id, Rotation.associated_game_id.in_(ids),
            ).all()
        }
        for game in missing:
            pitchers, on_mound = _pitchers(game, plans.get(game.id), events[game.id])
            known[game.id] = (pitchers, on_mound if game.is_live else '')
    return {game.id: known[game.id] for game in games}


def unrecorded_game_outings(team_id, outings, today, exclude_game_id=None, roster=None):
    """Placeholder outings (pitches unknown) for pitchers with no saved outing
    in a started game within the look-back window before `today`.
    `exclude_game_id` is the game being viewed, whose own live pitching that
    screen shows itself. `roster`, when the caller has it, saves a read."""
    start = today - timedelta(days=LOOKBACK_DAYS)
    games = [
        game for game in _started_games(team_id)
        if start <= game.date.date() <= today
        and (exclude_game_id is None or int(game.id) != int(exclude_game_id))
    ]
    if not games:
        return []

    recorded = {
        (int(o.game_id), int(o.player_id))
        for o in outings
        if getattr(o, 'game_id', None) is not None and getattr(o, 'player_id', None) is not None
    }
    if roster is None:
        roster = db.session.query(Player).filter_by(team_id=team_id).all()
    players = {player.name: player for player in roster}

    placeholders = []
    pitching = _pitchers_by_game(team_id, games)
    for game in games:
        pitchers, on_mound = pitching[game.id]
        for name in pitchers:
            player = players.get(name)
            if not player or (int(game.id), int(player.id)) in recorded:
                continue
            placeholders.append(SimpleNamespace(
                id=None,
                player_id=player.id,
                player=player,
                game_id=game.id,
                date=game.date,
                opponent=game.opponent,
                pitches=None,
                innings=None,
                outing_type='Game',
                pitcher_type=None,
                unrecorded=True,
                pitching_now=bool(on_mound and name == on_mound),
            ))
    return placeholders


def with_unrecorded(team_id, outings, today, exclude_game_id=None, roster=None):
    """`outings` plus placeholders for started games' unentered pitching."""
    outings = list(outings)
    return outings + unrecorded_game_outings(team_id, outings, today, exclude_game_id, roster)
