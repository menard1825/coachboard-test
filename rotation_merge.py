"""Two coaches editing one game's pregame defense: merge or refuse, never
overwrite.

The browser sends the whole plan to /save_rotation, together with the plan it
started from (``base_innings``). If another coach saved in between, the
stored plan is no longer that base. The save is then decided position by
position, against the base:

* a position only this coach changed takes this coach's player;
* a position only the other coach changed keeps theirs;
* a position both changed to the same player is fine;
* a position both changed to different players is a **conflict**: nothing is
  saved, and the coach is asked which to keep.

An inning works the same way: adding or removing it is a change of its own,
and removing an inning the other coach changed is a conflict. The merged
plan must also still have no player twice in one inning; if combining the
two coaches' changes would do that, it is a conflict too. So every saved
position is exactly one coach's deliberate choice, and no coach's saved
change is ever silently replaced.

Pure functions; no database access.
"""

from game_day_helpers import duplicate_assignment_message


def normalize(innings):
    """A plan as ``{inning: {position: player}}``: string keys, players
    trimmed, open positions left out. An inning with no positions is kept
    (it exists, it is just open)."""
    clean = {}
    if not isinstance(innings, dict):
        return clean
    for key, alignment in innings.items():
        positions = {}
        if isinstance(alignment, dict):
            for position, player in alignment.items():
                name = str(player or '').strip()
                if name:
                    positions[str(position)] = name
        clean[str(key)] = positions
    return clean


def _inning_order(key):
    try:
        return (0, float(key))
    except (TypeError, ValueError):
        return (1, str(key))


def merge(base, mine, theirs):
    """Three-way merge of normalized plans. Returns ``(merged, conflicts)``.

    ``conflicts`` lists what both coaches changed differently:
    ``{'inning', 'position', 'yours', 'theirs'}`` (``position`` None for an
    inning one coach removed and the other changed; a player None for an
    open position), or ``{'inning', 'player', 'kind': 'duplicate'}`` when the
    combined plan would put one player in two positions of an inning.
    """
    merged = {}
    conflicts = []
    for inning in sorted(set(base) | set(mine) | set(theirs), key=_inning_order):
        in_base, in_mine, in_theirs = inning in base, inning in mine, inning in theirs
        present = in_mine if in_mine != in_base else in_theirs
        b, m, t = base.get(inning, {}), mine.get(inning, {}), theirs.get(inning, {})
        alignment = {}
        for position in sorted(set(b) | set(m) | set(t)):
            bv, mv, tv = b.get(position), m.get(position), t.get(position)
            if mv == bv:
                value = tv
            elif tv == bv or mv == tv:
                value = mv
            else:
                conflicts.append({'inning': inning, 'position': position, 'yours': mv, 'theirs': tv})
                value = tv
            if value:
                alignment[position] = value
        if not present:
            # Removed by one coach: a conflict only if the other kept it and
            # changed it.
            if (not in_mine and in_theirs and t != b) or (not in_theirs and in_mine and m != b):
                conflicts.append({'inning': inning, 'position': None,
                                  'yours': None if not in_mine else 'kept',
                                  'theirs': None if not in_theirs else 'kept'})
            continue
        merged[inning] = alignment
    if not conflicts:
        for inning, alignment in merged.items():
            if alignment in (mine.get(inning), theirs.get(inning)):
                continue  # exactly one coach's inning: their own save checks it
            if duplicate_assignment_message(alignment, inning):
                names = list(alignment.values())
                player = next(name for name in names if names.count(name) > 1)
                conflicts.append({'inning': inning, 'player': player, 'kind': 'duplicate'})
    return merged, conflicts
