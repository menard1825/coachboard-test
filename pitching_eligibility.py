"""One classification of a pitcher's eligibility, shared by every live screen.

The pitch-count summary (utils.calculate_pitch_count_summary, wrapped for live
games by game_pitching_rules.gameplay_pitch_summary) reports a status string.
Change Pitcher, Next Inning and End Inning all need the same answer to "can
this player go in to pitch?", so they read it from here -- the server decides,
and the live state carries the result to the browser as `eligibility`.

CoachBoard informs; the coach decides. A pitching-rule finding is never a
software block: it asks the coach for an explicit decision, which the server
checks and records. Only software-safety problems (a stale field, a player
who isn't in the game, a request that can't be applied) are hard stops.

* ready         -- "Available": no decision needed.
* advisory      -- eligible, with a recommendation the coach should see first
                   (Pitch Smart: not pitching in two games the same day).
                   Decision: advisory_acknowledged ("Continue with ...").
* rule_conflict -- CoachBoard believes the selected rules say no (required
                   rest, an innings or pitch limit, a prohibited second game
                   the same day, pitcher re-entry). Decision: rule_override,
                   after a warning naming the rule set and the reason.
* unknown       -- CoachBoard cannot confirm either way (missing pitch counts
                   or innings, rules not selected or unsupported, a
                   calculation error, no summary at all). Decision:
                   eligibility_verified ("I verified ... is eligible").

A decision covers only the status the coach was shown: if the status has
changed since (End Inning re-evaluates the plan), the coach is asked again.

Re-entry and same-day games follow what the selected preset actually says
(reentry_rule, same_day_rule, by rule set and age group). Where a preset says
nothing, the answer is "can't confirm", never a guess. Re-entry is decided
from this game's pitching-change history, not from where anyone stands now.

What CoachBoard cannot check: pitches thrown in the game being played. They
are recorded when the game ends, so the pitcher continuing on the mound is
not re-evaluated and no in-game Pitch Smart limit is enforced.

A status nobody has named here is treated as a rule conflict: an unrecognized
status must never pass without the coach's strongest confirmation.
"""

from types import SimpleNamespace

READY = 'ready'
ADVISORY = 'advisory'
RULE_CONFLICT = 'rule_conflict'
UNKNOWN = 'unknown'

ADVISORY_ACKNOWLEDGED = 'advisory_acknowledged'
RULE_OVERRIDE = 'rule_override'
ELIGIBILITY_VERIFIED = 'eligibility_verified'

# The decision each classification needs before the pitcher goes in.
REQUIRED_DECISION = {
    ADVISORY: ADVISORY_ACKNOWLEDGED,
    RULE_CONFLICT: RULE_OVERRIDE,
    UNKNOWN: ELIGIBILITY_VERIFIED,
}

ADVISORY_STATUSES = {'Same-Day Game Advisory'}
REENTRY_STATUS = 'Already Pitched This Game'

# Status names as utils.calculate_pitch_count_summary and
# game_pitching_rules produce them (the live wrapper may prefix them with
# "Unavailable — ").
UNKNOWN_STATUSES = {
    'Pitch Count Incomplete',
    'Innings Incomplete',
    'Verify Rules',
    'Eligibility Error',
    'Select Game Rules',
    'Eligibility Unknown',
    'Same-Day Rule Unknown',
    'Re-entry Rule Unknown',
    'Re-entry Unconfirmed',
}

UNAVAILABLE_PREFIX = 'Unavailable — '


def base_status(status):
    status = str(status or '').strip()
    if status.startswith(UNAVAILABLE_PREFIX):
        return status[len(UNAVAILABLE_PREFIX):].strip()
    return status


def classify(summary_item):
    """READY, ADVISORY, RULE_CONFLICT or UNKNOWN for one summary entry."""
    status = str((summary_item or {}).get('status') or '').strip()
    if status == 'Available':
        return READY
    if not summary_item or not status or base_status(status) in UNKNOWN_STATUSES:
        return UNKNOWN
    if summary_item.get('advisory') or base_status(status) in ADVISORY_STATUSES:
        return ADVISORY
    return RULE_CONFLICT


def rule_set_label(rules):
    name = str((rules or {}).get('rule_set_name') or '').strip()
    if not name or name == 'Rules Not Selected':
        return 'the selected'
    return name


def _detail(item):
    return str(item.get('status_detail') or item.get('next_available') or '').strip()


def arm_care_note(summary_item):
    """The team arm-care concern for a pitcher when no game rules are
    selected, as one sentence -- or ''.

    Without game rules every pitcher is "can't confirm", and that question
    alone never said a pitcher's arm needs rest. The arm-care check still ran
    (game_pitching_rules keeps it as arm_care_*), so it is said wherever the
    coach decides: the Start Game question and its logged reason.
    """
    item = summary_item or {}
    if item.get('rule_type') != 'none':
        return ''
    status = str(item.get('arm_care_status') or '').strip()
    if not status or status.lower().startswith(('available', 'unknown')):
        return ''
    detail = str(item.get('arm_care_status_detail') or '').strip()
    next_available = str(item.get('arm_care_next_available') or '').strip()
    rule = str(item.get('arm_care_rule_set') or '').strip()
    note = f"Arm care{f' ({rule})' if rule else ''}: {status}."
    if detail:
        note += f" {detail if detail.endswith('.') else detail + '.'}"
    if next_available and next_available.lower() != 'today':
        note += f' Next available: {next_available}.'
    return note


def describe(pitcher_name, summary_item, rules=None):
    """What the coach is shown before deciding: heading, the rule reason,
    and (for a rule conflict) the override confirmation. Empty for ready."""
    item = summary_item or {}
    kind = classify(summary_item)
    status = base_status(item.get('status')) or 'Eligibility Unknown'
    detail = _detail(item)
    rule_set = rule_set_label(rules)

    if kind == READY:
        return {'eligibility': kind}

    if kind == ADVISORY:
        heading = f'{pitcher_name} is eligible — please read this first'
        message = detail or status
    elif kind == UNKNOWN:
        heading = f"CoachBoard can't confirm {pitcher_name}'s eligibility"
        message = (
            f"CoachBoard can't confirm {pitcher_name}'s pitching eligibility"
            + (f' ({status}).' if status != 'Eligibility Unknown' else '.')
            + (f' {detail}' if detail else '')
        )
        arm_care = arm_care_note(item)
        if arm_care:
            message += f' {arm_care}'
    else:
        heading = f'{pitcher_name} appears ineligible to pitch'
        if status == REENTRY_STATUS and detail:
            message = detail
        else:
            message = f'{rule_set}: {status}.' + (f' {detail}' if detail else '')

    described = {
        'eligibility': kind,
        'required_decision': REQUIRED_DECISION[kind],
        'rule_set': rule_set,
        'eligibility_heading': heading,
        'eligibility_message': message,
    }
    if kind == RULE_CONFLICT:
        described['override_confirm'] = (
            f'CoachBoard believes this may violate the selected {rule_set} '
            "rules. Continue only if you have verified the tournament's "
            'rules or are intentionally overriding this warning.'
        )
    return described


def annotate(summary, rules=None):
    """Add the shared classification (and, with rules, the wording) to each
    entry of a pitch-count summary."""
    for name, item in (summary or {}).items():
        if not isinstance(item, dict):
            continue
        if rules is None:
            item['eligibility'] = classify(item)
        else:
            item.update(describe(name, item, rules))
    return summary


def decision_accepted(summary_item, decision, decision_status):
    """Whether the coach's decision covers the pitcher's current status.

    READY needs none. Otherwise the decision must be the one this
    classification requires, made for the status CoachBoard shows now.
    """
    kind = classify(summary_item)
    if kind == READY:
        return True
    current = base_status((summary_item or {}).get('status')) or 'Eligibility Unknown'
    return (
        decision == REQUIRED_DECISION[kind]
        and (base_status(decision_status) or 'Eligibility Unknown') == current
    )


# ------------------------------------------------------------ rule table
#
# What each preset CoachBoard ships actually says. Where a preset says
# nothing, the answer is UNKNOWN -- never Ready and never a rule conflict.

SAME_DAY_PROHIBITED = 'prohibited'
SAME_DAY_ADVISORY = 'advisory'
SAME_DAY_ALLOWED = 'allowed'

REENTRY_PROHIBITED = 'prohibited'
# May return to pitch once, only after staying in the game at another position.
REENTRY_ONCE_IF_STAYED_IN = 'once_if_stayed_in'
REENTRY_ALLOWED = 'allowed'
RULE_UNKNOWN = 'unknown'

# MLB Pitch Smart age-group guidance on returning to pitch in the same game:
# 8 & under and 9-12 -- "Pitchers once removed from the mound may not return
# as pitchers"; 13-14 and 15-18 -- a pitcher remaining in the game at another
# position may return as pitcher once per game. 19-22 states no re-entry
# guidance, so it is not guessed. CoachBoard uses the 7-8 table for 4U-6U.
PITCH_SMART_REENTRY = {
    **{age: REENTRY_PROHIBITED for age in (
        '4U', '5U', '6U', '7U', '8U', '9U', '10U', '11U', '12U')},
    **{age: REENTRY_ONCE_IF_STAYED_IN for age in (
        '13U', '14U', '15U', '16U', '17U', '18U')},
}


def same_day_rule(rules):
    """The selected preset's rule on pitching a second game the same day.

    A preset may state it (`same_day_games`, or `same_day_games_prohibited`).
    MLB Pitch Smart recommends against it (advisory); USSSA limits innings,
    not games. Little League and Bullpen Tournaments presets don't encode it.
    """
    rules = rules or {}
    if rules.get('same_day_games') in (SAME_DAY_PROHIBITED, SAME_DAY_ADVISORY, SAME_DAY_ALLOWED):
        return rules['same_day_games']
    if rules.get('same_day_games_prohibited'):
        return SAME_DAY_PROHIBITED
    name = rules.get('rule_set_name')
    if name == 'MLB Pitch Smart':
        return SAME_DAY_ADVISORY
    if name == 'USSSA':
        return SAME_DAY_ALLOWED
    return RULE_UNKNOWN


def reentry_rule(rules):
    """The selected preset's rule on a removed pitcher returning to pitch.

    A preset may state it (`pitcher_reentry`). Otherwise: USSSA -- prohibited;
    MLB Pitch Smart -- by age group (PITCH_SMART_REENTRY); anything the preset
    doesn't encode (Little League, Bullpen Tournaments, Pitch Smart 19U+) --
    unknown.
    """
    rules = rules or {}
    explicit = rules.get('pitcher_reentry')
    if explicit in (REENTRY_PROHIBITED, REENTRY_ONCE_IF_STAYED_IN, REENTRY_ALLOWED):
        return explicit
    name = rules.get('rule_set_name')
    if name == 'USSSA':
        return REENTRY_PROHIBITED
    if name == 'MLB Pitch Smart':
        return PITCH_SMART_REENTRY.get(rules.get('age_group'), RULE_UNKNOWN)
    return RULE_UNKNOWN


def mound_history(events, name, current_alignment):
    """One player's pitching history in this game, from its change events.

    Every non-reverted event records the whole field before and after, so
    between events the field is known. Returns (removals, returns,
    left_field): how often the player came off P, how often they went back
    on after a removal, and whether at any point after first coming off P
    they were not on the field (bench -- CoachBoard can't tell whether that
    left the game under the event's substitution rules).
    """
    removals = returns = 0
    left_field = False
    for event in events or ():
        if getattr(event, 'reverted', False):
            continue
        before = event.before_alignment or {}
        after = event.after_alignment or {}
        was_p = str(before.get('P') or '').strip() == name
        is_p = str(after.get('P') or '').strip() == name
        if was_p and not is_p:
            removals += 1
        elif is_p and not was_p and removals:
            returns += 1
        if removals and name not in {str(v or '').strip() for v in after.values()}:
            left_field = True
    if removals and name not in {str(v or '').strip() for v in (current_alignment or {}).values()}:
        left_field = True
    return removals, returns, left_field


def pitchers_removed(events, current_pitcher):
    """Players who pitched in this game and are no longer on the mound.

    Read from the game's pitching-change history: every non-reverted event's
    pitcher before and after. An undone change never counts.
    """
    used = set()
    for event in events or ():
        if getattr(event, 'reverted', False):
            continue
        for alignment in (event.before_alignment, event.after_alignment):
            name = str((alignment or {}).get('P') or '').strip()
            if name:
                used.add(name)
    return used - {str(current_pitcher or '').strip(), ''}


def carry_planned_pitcher(planned, current_alignment, events, present_names=None, live_change=False):
    """The next inning's plan with its pitcher carried forward when the plan
    would bring back a pitcher who already came out.

    The saved plan is one defense per inning, so it cannot say whether
    "Reed at P in the 4th" is a leftover from filling every inning with the
    starting defense or a decision to bring Reed back. A plan that names a
    new pitcher ("Hansen from the 3rd", "Cole in the 6th") is a planned
    takeover and is kept. A plan that names a pitcher who already pitched in
    this game and is off the mound (pitchers_removed -- what the re-entry
    rule reads) is not applied automatically: the pitcher now on the mound
    keeps pitching until the next planned change. Bringing a pitcher back
    stays an explicit coach decision (Change Pitcher, or the Next Inning
    board), with its eligibility check.

    The two players trade places so every other position keeps its plan: the
    returning pitcher takes the spot the plan gave the pitcher who carries
    on (or sits, if that pitcher was planned to sit; the spot is left open if
    the returning pitcher is no longer here). No one is duplicated and no
    one else is moved.

    `live_change`: the pitcher now on the mound came in by a live pitching
    change this inning. That is the coach's decision for the next inning
    too, so he carries on whoever the plan names; innings after that follow
    their plans (a later planned new pitcher still takes over).

    Returns (alignment, carry) -- carry is None when the plan is used as
    written, else {'pitcher', 'planned_pitcher', 'position'}.
    """
    alignment = dict(planned or {})
    planned_p = str(alignment.get('P') or '').strip()
    current_p = str((current_alignment or {}).get('P') or '').strip()
    if not planned_p or not current_p or planned_p == current_p:
        return alignment, None
    if not live_change and planned_p not in pitchers_removed(events, current_p):
        return alignment, None

    spot = next(
        (pos for pos, name in alignment.items()
         if pos != 'P' and str(name or '').strip() == current_p),
        None,
    )
    alignment['P'] = current_p
    if spot:
        here = present_names is None or planned_p in present_names
        alignment[spot] = planned_p if here else ''
    return alignment, {'pitcher': current_p, 'planned_pitcher': planned_p, 'position': spot}


def fill_open_pitcher(alignment, pitcher):
    """A plan that leaves P open keeps the pitcher on the mound. If the plan
    also has him at another position, that spot is left open -- never the
    same player twice, never a guessed replacement, no one else moved. The
    open spot shows like any other, for the coach to fill.
    Returns the spot left open, or None."""
    pitcher = str(pitcher or '').strip()
    if str(alignment.get('P') or '').strip() or not pitcher:
        return None
    alignment['P'] = pitcher
    vacated = None
    for pos in list(alignment):
        if pos != 'P' and str(alignment.get(pos) or '').strip() == pitcher:
            alignment[pos] = ''
            vacated = vacated or pos
    return vacated


def project_planned_innings(plan, first_inning, first_alignment, events, present_names=None):
    """The defenses later innings would start with, inning by inning, as the
    live game prepares them: each inning's saved plan with the pitcher
    carried forward (carry_planned_pitcher) from the inning before, starting
    from `first_alignment` -- the next inning's actual saved defense.

    A projected change of pitcher counts as removing the earlier pitcher for
    the innings after it, so a later plan naming him again is carried too.
    Those changes exist only in this calculation; nothing is recorded, and
    the played history (`events`) is only read. A plan with an open P takes
    the pitcher before it, as the live seed does. Innings with no plan are
    left out (the caller reports them as not projected) and keep the
    pitcher from the inning before.

    Returns {inning: alignment} for planned innings after `first_inning`.
    """
    def number(value):
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    start = number(first_inning)
    if start is None:
        return {}
    history = list(events or ())
    pitcher = str((first_alignment or {}).get('P') or '').strip()
    projected = {}
    later = sorted(
        (key for key in (plan or {}) if number(key) is not None and number(key) > start and number(key) == int(number(key))),
        key=number,
    )
    for inning in later:
        planned = dict((plan or {}).get(inning) or {})
        if not any(str(name or '').strip() for name in planned.values()):
            continue
        alignment, _ = carry_planned_pitcher(planned, {'P': pitcher}, history, present_names)
        fill_open_pitcher(alignment, pitcher)
        projected[str(inning)] = alignment
        new_pitcher = str(alignment.get('P') or '').strip()
        if pitcher and new_pitcher and new_pitcher != pitcher:
            history.append(SimpleNamespace(
                reverted=False, before_alignment={'P': pitcher}, after_alignment={'P': new_pitcher}))
        pitcher = new_pitcher or pitcher
    return projected


def _flag(summary, name, status, detail, kind, next_available):
    item = summary.setdefault(name, {'name': name})
    item['status'] = status
    item['status_detail'] = detail
    item['next_available'] = next_available
    item['advisory'] = False
    item['eligibility'] = kind


def apply_reentry_rule(summary, rules, events, current_pitcher, current_alignment=None):
    """Flag pitchers removed earlier in this game by the selected rules.

    prohibited        -- rule conflict.
    once_if_stayed_in -- ready while the one return is unused and the player
                         stayed on the field; a rule conflict once it is used;
                         can't confirm if the player was ever off the field.
    unknown           -- can't confirm (the preset doesn't say).
    allowed           -- nothing to flag.
    """
    rule = reentry_rule(rules)
    if rule == REENTRY_ALLOWED:
        return summary
    rule_set = rule_set_label(rules)
    alignment = current_alignment if current_alignment is not None else {'P': current_pitcher}
    for name in pitchers_removed(events, current_pitcher):
        if rule == REENTRY_PROHIBITED:
            _flag(
                summary, name, REENTRY_STATUS,
                f'{name} already pitched and was removed from the mound. '
                f'{rule_set} rules indicate {name} cannot return to pitch in '
                'this game.',
                RULE_CONFLICT, 'Next game',
            )
        elif rule == REENTRY_ONCE_IF_STAYED_IN:
            _, returns, left_field = mound_history(events, name, alignment)
            if returns:
                _flag(
                    summary, name, REENTRY_STATUS,
                    f'{name} already returned to pitch once in this game. '
                    f'{rule_set} rules for this age group allow one return '
                    'per game.',
                    RULE_CONFLICT, 'Next game',
                )
            elif left_field:
                _flag(
                    summary, name, 'Re-entry Unconfirmed',
                    f'{name} already pitched and later left the field. '
                    f'{rule_set} rules for this age group allow a return to '
                    f'pitch only for a pitcher who stayed in the game; '
                    f"CoachBoard can't confirm whether {name} did.",
                    UNKNOWN, 'Verify the event rules',
                )
            # Otherwise: stayed on the field, one return unused -- the
            # pitcher's own status stands.
        else:
            _flag(
                summary, name, 'Re-entry Rule Unknown',
                f'{name} already pitched in this game and was removed from '
                f"the mound. CoachBoard's {rule_set} preset doesn't say "
                'whether a pitcher may return to pitch.',
                UNKNOWN, 'Verify the event rules',
            )
    return summary
