"""Who is at the field for a game, inning by inning, and who played defense.

Availability
------------
PlayerGameAbsence means "Out at first pitch": a player marked Out before the
game is not here when it starts. It is locked once the game is live.

A player who arrives late or leaves during the game is a live event on the
same timeline as every other live change (GameRotationEvent), so it shares
the live version, locking, Undo and broadcast:

* 'Player Arrived' -- subject_player_id is here again; effective_inning is
  the first inning that counts toward their availability.
* 'Player Left'    -- subject_player_id has gone; effective_inning is the
  first inning that no longer counts.

Replay (unreverted events only, in sequence order):

* present_now starts as "not Out at first pitch". Each event sets it for its
  player: Arrived -> here, Left -> gone. The inning it counts from does not
  matter: a player who arrived during the 4th can go in during the 4th.
* An inning counts toward a player's availability window when the latest
  event (by sequence) whose effective_inning is at or before that inning is
  an Arrived. With no such event, the player's first-pitch status decides.
  So each event restates the player's availability from its inning onward,
  and a correction is simply a later event from the same inning: "Jake
  Arrived from the 4th" then "Jake Left from the 4th" leaves Jake with no
  innings at all, and "Sam Left from the 5th" then "Sam Arrived from the
  5th" gives Sam back every inning.

Innings are whole innings. Nothing here counts outs.

Inning started
--------------
CoachBoard's transition actions are the inning boundary, and nothing else
asks or decides whether an inning has begun:

* Start Game records the 1st inning as started ('Inning Started'), with the
  exact defense being started;
* End Inning -> Start Next Inning ("End 2nd -> Start 3rd") records the new
  inning as started, with the exact defense it sends out.

On the Field changes after that are changes during play (pre_start False);
the coach never classifies them. The marker is bookkeeping: ordinary Undo
passes over it, and undoing the End Inning that started an inning withdraws
it. Arrived / Left events never start an inning.

The one exception is asked where it matters: ending a game on a time limit
when the newly started inning was never played. The coach says so, and the
clock withdraws that inning's transition and its start marker
(live_game_clock). An inning with a defensive change recorded during it was
played and is not withdrawn.

Games recorded by an earlier version asked "Has the 4th inning started?" at
the first On the Field change instead; their "Not yet" edits (pre_start
True) stay setup edits, and live_history.py keeps them out of baseball
history. Older games with no markers at all keep their recorded defense.

Defensive participation
-----------------------
A player who fields any part of an inning after it begins played that
inning. For each reached inning:

* with a start marker: everyone in the marker's defense, plus the before
  and after alignments of every unreverted change after the marker. Changes
  before the marker (setup edits recorded by the earlier version) give no
  credit;
* without a marker, once the inning is completed: its final recorded
  defense (older games, and innings an earlier version never marked);
* without a marker in the inning being played now: nobody yet, and it is
  left out of the result.

A Postgame Correction restates an inning's record: anyone it removes from
the recorded alignment is taken out of that inning's participation too,
and everyone in the corrected alignment is in it.

Innings the game has not reached (the rest of the plan) never count. An
inning is reached when an unreverted event names it, inning 1 once there is
any event, and the current inning while the game is live; every reached
inning is completed except the one being played while the game is live.
Games recorded before start markers existed therefore keep exactly their
recorded defense per inning.
"""

from dataclasses import dataclass, field

from db import db
from game_day_helpers import _event_order_key, _reconstruct_actual_game_rotation, actual_game_rotation
from live_history import INNING_STARTED
from models import GameRotationEvent, Player, PlayerGameAbsence


ARRIVED = 'Player Arrived'
LEFT = 'Player Left'
AVAILABILITY_EVENTS = frozenset({ARRIVED, LEFT})

# An End Inning's before alignment is the previous inning's defense; a
# Postgame Correction's before alignment is the record it corrects.
_NOT_DURING_THE_INNING = frozenset({'End Inning', 'Postgame Correction'})
_CORRECTION = 'Postgame Correction'


def _inning_number(value):
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    return number


@dataclass(frozen=True)
class GameAvailability:
    """Availability for one game, replayed from its first-pitch Outs and events.

    windows maps every roster player id to its available innings as
    (first, last) pairs, inclusive; last is None for "the rest of the game".
    """

    roster_ids: frozenset
    out_at_first_pitch: frozenset
    present_now: frozenset
    left_game: frozenset
    windows: dict = field(default_factory=dict)

    def is_present(self, player_id):
        return player_id in self.present_now

    def not_here_now(self):
        return self.roster_ids - self.present_now

    def available_in(self, player_id, inning):
        number = _inning_number(inning)
        if number is None:
            return False
        return any(
            first <= number and (last is None or number <= last)
            for first, last in self.windows.get(player_id, ())
        )


def replay_availability(roster_ids, absent_ids, events):
    """Pure replay of first-pitch Outs plus availability events (see module doc)."""
    roster_ids = frozenset(roster_ids)
    out_at_first_pitch = frozenset(absent_ids) & roster_ids

    present = {player_id: player_id not in out_at_first_pitch for player_id in roster_ids}
    last_event_type = {}
    changes = {player_id: [] for player_id in roster_ids}  # (sequence order, from inning, available)

    ordered = sorted(
        (
            event for event in events or []
            if not event.reverted and event.event_type in AVAILABILITY_EVENTS
        ),
        key=_event_order_key,
    )
    for order, event in enumerate(ordered):
        player_id = event.subject_player_id
        if player_id not in present:
            continue
        arrived = event.event_type == ARRIVED
        present[player_id] = arrived
        last_event_type[player_id] = event.event_type
        from_inning = _inning_number(event.effective_inning)
        if from_inning is None:
            continue
        changes[player_id].append((order, max(1, from_inning), arrived))

    windows = {}
    for player_id in roster_ids:
        initial = player_id not in out_at_first_pitch
        player_changes = changes[player_id]
        boundaries = sorted({1} | {from_inning for _, from_inning, _ in player_changes})

        def available_from(boundary, initial=initial, player_changes=player_changes):
            applicable = [change for change in player_changes if change[1] <= boundary]
            if not applicable:
                return initial
            return max(applicable)[2]

        spans = []
        for index, boundary in enumerate(boundaries):
            if not available_from(boundary):
                continue
            last = boundaries[index + 1] - 1 if index + 1 < len(boundaries) else None
            if spans and spans[-1][1] == boundary - 1:
                spans[-1] = (spans[-1][0], last)
            else:
                spans.append((boundary, last))
        windows[player_id] = tuple(spans)

    left_game = frozenset(
        player_id for player_id, event_type in last_event_type.items()
        if event_type == LEFT
    )

    return GameAvailability(
        roster_ids=roster_ids,
        out_at_first_pitch=out_at_first_pitch,
        present_now=frozenset(player_id for player_id, here in present.items() if here),
        left_game=left_game,
        windows=windows,
    )


def game_availability(game, team_id, *, roster=None, absences=None, events=None):
    """Availability for this game from the database.

    Callers that already loaded the roster, the absence rows or the events
    pass them in, so the live state issues no extra statement.
    """
    if roster is None:
        roster = db.session.query(Player).filter_by(team_id=team_id).all()
    if absences is None:
        absences = db.session.query(PlayerGameAbsence).filter_by(
            game_id=game.id,
            team_id=team_id,
        ).all()
    if events is None:
        events = db.session.query(GameRotationEvent).filter_by(
            game_id=game.id,
            team_id=team_id,
        ).all()
    return replay_availability(
        {player.id for player in roster},
        {row.player_id for row in absences},
        events,
    )


def present_players(game, team_id):
    """Roster players who are here now, name-ordered."""
    roster = db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
    availability = game_availability(game, team_id, roster=roster)
    return [player for player in roster if availability.is_present(player.id)]


def reached_innings(events, *, is_live=False, current_inning=None):
    """Innings the game has reached; never an inning that is only planned.

    The same innings actual_game_rotation reports as reached (every inning
    an unreverted event names, and inning 1 once there is any event), plus
    the current inning while the game is live.
    """
    _, _, reached = _reconstruct_actual_game_rotation(None, events)
    if is_live:
        reached.add(str(current_inning or '1'))
    return reached


def completed_innings(reached, *, is_live=False, current_inning=None):
    """Reached innings that are over: all of them, except the one being played."""
    if not is_live:
        return {str(inning) for inning in reached}
    current = _inning_number(current_inning or '1')
    return {
        str(inning) for inning in reached
        if current is None or (_inning_number(inning) or 0) < current
    }


def inning_start_marker(events, inning):
    """The unreverted 'Inning Started' marker for this inning, or None."""
    markers = sorted(
        (
            event for event in events or []
            if not event.reverted
            and event.event_type == INNING_STARTED
            and str(event.inning) == str(inning)
        ),
        key=_event_order_key,
    )
    return markers[0] if markers else None


def inning_has_started(game, team_id, inning=None):
    """True once the coach has said this inning (default: the current one) began."""
    inning = str(inning if inning is not None else (game.live_current_inning or '1'))
    return db.session.query(GameRotationEvent.id).filter_by(
        game_id=game.id,
        team_id=team_id,
        inning=inning,
        event_type=INNING_STARTED,
        reverted=False,
    ).first() is not None


def inning_has_only_setup_edits(game, team_id, inning=None):
    """True while this inning (default: the current one) has only setup edits
    -- changes an earlier version saved as "Not yet" -- and nothing since
    shows it being played (a start marker, or a change made during play)."""
    inning = str(inning if inning is not None else (game.live_current_inning or '1'))
    rows = db.session.query(GameRotationEvent.event_type, GameRotationEvent.pre_start).filter_by(
        game_id=game.id,
        team_id=team_id,
        inning=inning,
        reverted=False,
    ).all()
    if any(event_type == INNING_STARTED or pre_start is False for event_type, pre_start in rows):
        return False
    return any(pre_start is True for _, pre_start in rows)


def _names(alignment):
    return {
        str(name).strip()
        for name in (alignment or {}).values()
        if name and str(name).strip()
    }


def defensive_participation(actual_rotation, events, reached, completed):
    """{inning: frozenset of names who played defense} for innings that began.

    Pure. actual_rotation is the recorded rotation (plan plus unreverted
    events, as _actual_rotation / actual_game_rotation build it); reached and
    completed come from reached_innings / completed_innings. An inning left
    out of the result has not begun (see module doc).
    """
    ordered = sorted(
        (event for event in events or [] if not event.reverted),
        key=_event_order_key,
    )
    completed = {str(inning) for inning in completed}
    participation = {}
    for inning in reached:
        inning = str(inning)
        inning_events = [event for event in ordered if str(event.inning) == inning]
        marker = inning_start_marker(inning_events, inning)
        if marker is None:
            if inning in completed:
                participation[inning] = frozenset(_names((actual_rotation or {}).get(inning)))
            continue

        names = _names(marker.after_alignment)
        after_marker = inning_events[inning_events.index(marker) + 1:]
        for event in after_marker:
            if event.event_type in (_CORRECTION, INNING_STARTED):
                continue
            names |= _names(event.after_alignment)
            if event.event_type not in _NOT_DURING_THE_INNING:
                names |= _names(event.before_alignment)
        for event in after_marker:
            if event.event_type != _CORRECTION:
                continue
            corrected = _names(event.after_alignment)
            names -= _names(event.before_alignment) - corrected
            names |= corrected
        participation[inning] = frozenset(names)
    return participation


def game_participation(game, team_id):
    """defensive_participation for this game from the database."""
    _, actual, events, _ = actual_game_rotation(game, team_id)
    live = bool(game.is_live)
    current = game.live_current_inning or '1'
    reached = reached_innings(events, is_live=live, current_inning=current)
    completed = completed_innings(reached, is_live=live, current_inning=current)
    return defensive_participation(actual, events, reached, completed)


PLAYED = 'played'
SAT = 'sat'
NOT_HERE = 'not_here'


def inning_status(player, inning, availability, participation):
    """Played / Sat / Not Here for one player in one inning, or None.

    None for an inning that has not begun (not in participation): nobody
    played or sat it yet. Played always wins: a player who appeared on
    defense at any point after the inning began played it, whatever the
    availability window says. Otherwise the inning is a sit only if it is
    inside the player's availability window.
    """
    inning = str(inning)
    if inning not in participation:
        return None
    if player.name in participation[inning]:
        return PLAYED
    if availability.available_in(player.id, inning):
        return SAT
    return NOT_HERE
