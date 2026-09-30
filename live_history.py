"""Live events as baseball history: setup before an inning begins vs play.

End Inning (and Start Game, for the 1st) only loads an inning's defense.
The coach may still edit it before the inning begins: the first On the
Field change of an inning asks "Has the 4th inning started?"
(game_availability.py). The answer is saved on the change:

* pre_start = True  -- "Not yet": a setup edit. It is an official field edit
  (it builds the current alignment and the inning's starting defense, and
  Undo takes it back), but no baseball happened: it is not a substitution
  or a pitching change.
* pre_start = False -- made after the coach said the inning had started (an
  'Inning Started' marker precedes it in that inning): an in-game change.
* pre_start = None  -- recorded before this question existed. Such games keep
  exactly their existing history.

Field reconstruction (_actual_rotation, actual_game_rotation) uses every
event: the field needs the setup edits. Consumers that read before/after
alignments as *history* -- who pitched, pitching changes and re-entry,
change descriptions, appearances by position or inning -- read
gameplay_events() instead:

* setup edits and 'Inning Started' markers (bookkeeping) are left out;
* the End Inning that loaded an inning with setup edits is shown taking
  the field with the defense that actually began it (the defense after the
  last setup edit), not the loaded one. The loaded defense never played.

So in "End 3rd loads Tom at P; before the 4th the coach puts Jake at P, Not
yet": the 3rd ends and Jake takes the mound for the 4th. Tom did not pitch
the 4th, and there is no Tom -> Jake pitching change in it.

Pure: no queries, and the events passed in are never modified.
"""

from types import SimpleNamespace


INNING_STARTED = 'Inning Started'

_EVENT_FIELDS = (
    'id', 'sequence', 'event_type', 'inning', 'timestamp', 'changed_by_user',
    'before_alignment', 'after_alignment', 'old_pitcher_id', 'new_pitcher_id',
    'reverted', 'team_id', 'game_id', 'subject_player_id', 'effective_inning',
    'pre_start',
)


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


def is_setup_edit(event):
    return getattr(event, 'pre_start', None) is True


def _took_the_field(transition, starting_defense):
    """This End Inning, showing the defense that actually began its inning."""
    shown = SimpleNamespace(**{name: getattr(transition, name, None) for name in _EVENT_FIELDS})
    shown.source = transition
    shown.after_alignment = dict(starting_defense or {})
    before_p = (transition.before_alignment or {}).get('P')
    loaded_p = (transition.after_alignment or {}).get('P')
    started_p = shown.after_alignment.get('P')
    if started_p == before_p:
        shown.old_pitcher_id = shown.new_pitcher_id = None
    elif started_p != loaded_p:
        # The id of the pitcher who took the mound isn't on this event.
        shown.new_pitcher_id = None
    return shown


def setup_starting_defenses(events):
    """{(game_id, inning): the defense that began the inning} for innings with
    setup edits -- the defense after the last one. Innings without setup
    edits began with what was loaded (or, for older games, as recorded)."""
    ordered = sorted(
        (event for event in events or [] if not getattr(event, 'reverted', False)),
        key=_event_order_key,
    )
    return {
        (getattr(event, 'game_id', None), str(event.inning)): dict(event.after_alignment or {})
        for event in ordered
        if is_setup_edit(event)
    }


def gameplay_events(events):
    """Unreverted events as baseball history, in timeline order (module doc).

    Returns the original event objects, except an End Inning whose inning had
    setup edits, which is a copy (with .source, the original) showing the
    defense that actually took the field.
    """
    ordered = sorted(
        (event for event in events or [] if not getattr(event, 'reverted', False)),
        key=_event_order_key,
    )
    starting_defense = setup_starting_defenses(ordered)

    history = []
    for event in ordered:
        if event.event_type == INNING_STARTED or is_setup_edit(event):
            continue
        key = (getattr(event, 'game_id', None), str(event.inning))
        if event.event_type == 'End Inning' and key in starting_defense:
            event = _took_the_field(event, starting_defense[key])
        history.append(event)
    return history
