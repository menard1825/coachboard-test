import re
from copy import deepcopy
from datetime import datetime

from flask import Blueprint, jsonify, request, session
from sqlalchemy import JSON, UniqueConstraint
from sqlalchemy.exc import IntegrityError

from asset_versioning import asset_url
from db import db
from extensions import socketio
from game_availability import ARRIVED, LEFT, game_availability, inning_has_only_setup_edits, present_players
from live_history import INNING_STARTED, _event_order_key
from models import Game, Player, Rotation
from pitching_eligibility import carry_planned_pitcher, fill_open_pitcher, project_planned_innings
from team_game_settings import regulation_innings_for_team
from blueprints.live_game_api import (
    _actual_rotation,
    _authorized_context,
    _events,
)


# Compatibility blueprint: the existing gameday route still owns /game/<id>,
# while this layer protects planned rotations and owns coach-confirmed next-inning prep.
live_game_ui_bp = Blueprint('live_game_ui', __name__)


class GameNextInningPrep(db.Model):
    __tablename__ = 'game_next_inning_preps'

    id = db.Column(db.Integer, primary_key=True)
    inning = db.Column(db.String, nullable=False)
    alignment = db.Column(JSON, nullable=False)
    source = db.Column(db.String, nullable=True)
    updated_by = db.Column(db.String, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    # "Undo next-inning edit": the defense as saved before the last coach
    # save, with its source and updated_by ('Auto' = nobody chose it). One
    # step, kept on the row so it survives a reload. revision counts coach
    # saves and Undos (not the automatic follow-the-field updates); an Undo
    # must name the revision it saw.
    previous_alignment = db.Column(JSON, nullable=True)
    previous_source = db.Column(db.String, nullable=True)
    previous_updated_by = db.Column(db.String, nullable=True)
    revision = db.Column(db.Integer, nullable=True, default=0)
    # Who made the coach save that Undo would take back: the user's id, as
    # updated_by is only a display name. Undo is "undo my last plan edit",
    # so only that coach may undo it (_undo_belongs_to). NULL: automatic, an
    # Undo's result, or saved before this was recorded.
    updated_by_user_id = db.Column(db.Integer, nullable=True)
    # Whether the coach chose this defense's pitcher (a save that changed P
    # on the board). A saved defense whose pitcher was not chosen (False)
    # follows a live pitching change (_effective_prep); one whose pitcher was
    # chosen (True) keeps it. NULL is unknown -- saved before this was
    # recorded -- and a coach-saved defense with NULL keeps its pitcher like
    # a chosen one; it is never inferred. previous_pitcher_chosen goes with
    # the Undo state, NULL kept as NULL.
    pitcher_chosen = db.Column(db.Boolean, nullable=True)
    previous_pitcher_chosen = db.Column(db.Boolean, nullable=True)

    __table_args__ = (
        UniqueConstraint('game_id', 'team_id', name='uq_game_next_inning_prep'),
    )


def _next_inning_key(current):
    try:
        return str(int(float(str(current or '1'))) + 1)
    except (TypeError, ValueError):
        return None


def _allowed_positions(team):
    base = ['P', 'C', '1B', '2B', '3B', 'SS']
    outfield = ['LF', 'LCF', 'RCF', 'RF'] if int(team.outfielder_count or 3) == 4 else ['LF', 'CF', 'RF']
    return base + outfield


def _present_players(game, team_id):
    # Here now, including late arrivals and departures (game_availability).
    return present_players(game, team_id)


def _clean_draft_alignment(candidate, game, team):
    """Validate a NEXT draft without requiring every position to be filled."""
    if not isinstance(candidate, dict):
        return None, 'A defensive alignment is required.'

    allowed = _allowed_positions(team)
    unknown = [pos for pos in candidate if pos not in allowed]
    if unknown:
        return None, f'Invalid defensive position: {unknown[0]}.'

    present = _present_players(game, team.id)
    present_names = {player.name for player in present}

    cleaned = {
        pos: candidate.get(pos) or ''
        for pos in allowed
    }

    invalid = sorted({
        name
        for name in cleaned.values()
        if name and name not in present_names
    })

    if invalid:
        return None, (
            f'{invalid[0]} is not available for this game.'
        )

    # A NEXT draft is intentionally allowed to be incomplete or temporarily
    # contain the same player twice. The coach can fix that directly on NEXT.
    # End Inning performs the final physically-valid check.
    return cleaned, None


# Recorded with the field unchanged: not a coach's defensive change.
_BOOKKEEPING_EVENTS = frozenset({'End Inning', INNING_STARTED, ARRIVED, LEFT})


def _field_changed_this_inning(events, current_inning, current_alignment, team):
    """Whether the coach changed the live field during the current inning.

    The inning starts with the field End Inning put out (or, before the
    first change of a game, the field that change replaced). Reverted events
    do not count, and a change undone by hand leaves the field as it began.

    A change of pitcher alone (Change Pitcher, wherever the relieved pitcher
    went) is not a field change for the next inning: it keeps its plan, and
    the new pitcher carries forward (carry_planned_pitcher) -- the coach
    changed who pitches, not the playing-time rotation. Any other change in
    the inning still carries the whole field forward.
    """
    allowed = _allowed_positions(team)

    def filled(alignment):
        return {pos: (alignment or {}).get(pos) for pos in allowed if (alignment or {}).get(pos)}

    inning_events = [
        event for event in events
        if not event.reverted and str(event.inning) == str(current_inning)
    ]
    if not inning_events:
        return False
    if _pitching_changed_this_inning(events, current_inning):
        return False
    first = inning_events[0]
    start = first.after_alignment if first.event_type == 'End Inning' else first.before_alignment
    return filled(start) != filled(current_alignment)


def _seed_next_alignment(current_alignment, planned_alignment, team, field_changed=False):
    """Build the automatic NEXT board for the upcoming inning."""
    allowed = _allowed_positions(team)
    current = current_alignment or {}
    planned = planned_alignment or {}

    # A live change this inning (a new pitcher, a swap) is a decision made
    # in the game; the pregame plan for the next inning must not undo it.
    has_plan = not field_changed and any(planned.get(pos) for pos in allowed)

    if has_plan:
        seeded = {
            pos: planned.get(pos) or ''
            for pos in allowed
        }

        # A specifically planned pitcher wins. Only carry the current
        # pitcher when the written next-inning plan leaves P blank -- and if
        # the plan has him elsewhere too, that spot is left open
        # (fill_open_pitcher), never the same player twice.
        fill_open_pitcher(seeded, current.get('P'))

        return seeded, 'planned'

    return {
        pos: current.get(pos) or ''
        for pos in allowed
    }, 'current'


def _planned_seed(current_alignment, planned_alignment, team):
    seeded, source = _seed_next_alignment(current_alignment, planned_alignment, team)
    return seeded if source == 'planned' else None


def prep_alignment(prep):
    """The defense a Next Inning row stands for now: its saved alignment,
    with the pitcher a live pitching change carries when the coach saved the
    fielders but did not choose the pitcher (_effective_prep). The board,
    the save conflict check and End Inning all use this."""
    if prep is None:
        return {}
    effective = getattr(prep, 'effective_alignment', None)
    return effective if effective is not None else (prep.alignment or {})


def _coach_name(user):
    """The name a coach's saves are recorded under (updated_by)."""
    return session.get('full_name') or user.full_name or user.username


def _undo_belongs_to(prep, user):
    """Whether the save Undo would take back is this coach's own.

    Undo next-inning edit means "undo my last plan edit", never "undo
    whoever saved last": another coach's newer save is theirs to undo.
    Ownership is the saving coach's user id; a save recorded before ids were
    kept falls back to the name it was saved under.
    """
    if not prep or prep.previous_alignment is None or user is None:
        return False
    if prep.updated_by_user_id is not None:
        return prep.updated_by_user_id == user.id
    return prep.updated_by not in (None, '', 'Auto') and prep.updated_by == _coach_name(user)


NOT_YOURS = 'That plan was changed by another coach. Nothing was undone.'


def _prep_dict(prep, viewer=None):
    if not prep:
        return None
    return {
        'id': prep.id,
        'inning': prep.inning,
        'alignment': deepcopy(prep_alignment(prep)),
        'source': prep.source,
        'updated_by': prep.updated_by,
        'updated_at': prep.updated_at.isoformat() if prep.updated_at else None,
        'revision': int(prep.revision or 0),
        'pitcher_chosen': prep.pitcher_chosen,
        # Whether this coach may undo the last save: there is one, and it is
        # theirs (_undo_belongs_to). The server refuses any other Undo.
        'can_undo': _undo_belongs_to(prep, viewer),
        # What "Undo next-inning edit" would bring back, or None.
        'previous': {
            'alignment': deepcopy(prep.previous_alignment),
            'source': prep.previous_source,
            'updated_by': prep.previous_updated_by,
        } if prep.previous_alignment is not None else None,
    }


def _next_prep_conflict(data, next_inning, prep, team):
    """Why a Next Inning save no longer applies, or None when it does."""
    if 'inning' in data and str(data.get('inning') or '') != str(next_inning):
        return 'The inning changed before this Next Inning change was saved.'

    base = data.get('base_alignment')
    if not isinstance(base, dict):
        return None

    allowed = _allowed_positions(team)

    def filled(alignment):
        return {
            pos: (alignment or {}).get(pos)
            for pos in allowed
            if (alignment or {}).get(pos)
        }

    if filled(base) != filled(prep_alignment(prep)):
        return 'The Next Inning defense changed on another device.'
    return None


def _next_prep_undo_conflict(data, prep):
    """Why an Undo no longer applies: it must name the revision it saw, and
    a newer save (another device's) means the screen is out of date."""
    try:
        seen = int(data.get('base_revision'))
    except (TypeError, ValueError):
        return 'Reload the Next Inning defense before undoing.'
    if not prep or seen != int(prep.revision or 0):
        return 'The Next Inning defense changed on another device.'
    return None


def _played_innings(game, team, current_inning):
    """For each inning before the current one: how it ended, if the game
    recorded it, and who was here that inning.

    The record is evidence, never the plan. End Inning stores the field
    exactly as the inning ended (its before_alignment) on the event for the
    inning it starts; a later postgame correction of an inning stores the
    corrected defense. An inning with neither -- an untouched plan, an older
    game -- has 'alignment': None, however its plan reads.

    'available' is who was here in that inning: first-pitch Outs plus the
    arrivals and departures recorded during the game, as the availability
    windows replay them -- not today's availability.
    """
    try:
        playing = float(str(current_inning))
    except (TypeError, ValueError):
        return {}
    if playing <= 1:
        return {}

    events = sorted(_events(game.id, team.id), key=_event_order_key)
    records = {}
    inning = '1'
    for event in events:
        if event.reverted:
            continue
        if event.event_type == 'End Inning':
            records[inning] = {
                'alignment': deepcopy(event.before_alignment or {}),
                'recorded_by': 'end_inning',
            }
            inning = str(event.inning)
        elif event.event_type == 'Postgame Correction':
            records[str(event.inning)] = {
                'alignment': deepcopy(event.after_alignment or {}),
                'recorded_by': 'correction',
            }
        elif event.event_type == 'Resume Game':
            inning = str(event.inning)

    roster = db.session.query(Player).filter_by(team_id=team.id).all()
    availability = game_availability(game, team.id, roster=roster, events=events)
    played = {}
    for number in range(1, int(playing)):
        key = str(number)
        record = records.get(key)
        if record and not any((record['alignment'] or {}).values()):
            record = None
        played[key] = {
            'alignment': record['alignment'] if record else None,
            'recorded_by': record['recorded_by'] if record else None,
            'available': sorted(
                player.name for player in roster
                if availability.available_in(player.id, key)
            ),
        }
    return played


def prep_snapshot(prep):
    """A saved Next Inning defense, kept on the End Inning that started it."""
    return {
        'inning': str(prep.inning),
        'alignment': deepcopy(prep.alignment or {}),
        'source': prep.source,
        'updated_by': prep.updated_by,
        'updated_by_user_id': prep.updated_by_user_id,
        'revision': int(prep.revision or 0),
        'previous_alignment': deepcopy(prep.previous_alignment),
        'previous_source': prep.previous_source,
        'previous_updated_by': prep.previous_updated_by,
        # As recorded: None (unknown) stays None.
        'pitcher_chosen': prep.pitcher_chosen,
        'previous_pitcher_chosen': prep.previous_pitcher_chosen,
    }


def restore_started_prep(game, team_id, event):
    """Undo of an inning start: the Next Inning defense that started it is
    the Next Inning defense again -- alignment, source, who chose it and its
    own Undo -- with a newer revision than any it has had, so a screen that
    never saw the restore cannot undo against it. Returns the restored row,
    or None when the event kept nothing (recorded before this existed)."""
    snapshot = event.started_prep or None
    if not snapshot or str(snapshot.get('inning')) != str(event.inning):
        return None
    existing = _prep_for_game(game.id, team_id)
    revision = max(int(snapshot.get('revision') or 0), int(getattr(existing, 'revision', 0) or 0)) + 1
    if existing:
        db.session.delete(existing)
        db.session.flush()
    prep = GameNextInningPrep(
        game_id=game.id,
        team_id=team_id,
        inning=str(event.inning),
        alignment=deepcopy(snapshot.get('alignment') or event.after_alignment or {}),
        source=snapshot.get('source'),
        updated_by=snapshot.get('updated_by'),
        updated_by_user_id=snapshot.get('updated_by_user_id'),
        previous_alignment=deepcopy(snapshot.get('previous_alignment')),
        previous_source=snapshot.get('previous_source'),
        previous_updated_by=snapshot.get('previous_updated_by'),
        # A snapshot from before these were recorded: unknown (None).
        pitcher_chosen=snapshot.get('pitcher_chosen'),
        previous_pitcher_chosen=snapshot.get('previous_pitcher_chosen'),
        revision=revision,
        updated_at=datetime.utcnow(),
    )
    db.session.add(prep)
    return prep


def _prep_for_game(game_id, team_id):
    return db.session.query(GameNextInningPrep).filter_by(game_id=game_id, team_id=team_id).first()


def _clear_prep(game_id, team_id):
    prep = _prep_for_game(game_id, team_id)
    if prep:
        db.session.delete(prep)
        return True
    return False


def _carried_plan(game, team, planned_alignment, current_alignment, events, live_change=False):
    present = {player.name for player in _present_players(game, team.id)}
    return carry_planned_pitcher(planned_alignment, current_alignment, events, present, live_change)


def _inning_changes(events, current_inning):
    return [
        event for event in events
        if not event.reverted
        and str(event.inning) == str(current_inning)
        and event.event_type not in _BOOKKEEPING_EVENTS
    ]


def _pitching_changed_this_inning(events, current_inning):
    """Whether this inning's live changes were changes of pitcher only."""
    changes = _inning_changes(events, current_inning)
    return bool(changes) and all(event.event_type == 'Pitcher Change' for event in changes)


def _effective_prep(game, team, prep, current_inning, current_alignment, events):
    """Set prep.effective_alignment / prep.pitcher_adjustment.

    A Next Inning defense the coach saved records whether its pitcher was
    chosen (pitcher_chosen: the save changed P). If not -- a fielding edit,
    or "Use inning plan" -- its P is just whoever was there, and a live
    pitching change carries the new pitcher in, the way it does for the
    automatic defense: carry_planned_pitcher, live_change for a pitching
    change this inning; the two pitchers trade places, every saved fielding
    assignment stays. The saved row is not rewritten, so undoing the live
    change brings the defense back as saved. A chosen pitcher, the automatic
    defense (re-seeded from the field) and "Same defense" are left alone, and
    so is a defense saved before pitcher_chosen was recorded (None): its
    intent is unknown, so its pitcher is kept as saved.
    """
    if prep is None:
        return None
    prep.effective_alignment = None
    prep.pitcher_adjustment = None
    if (
        prep.updated_by == 'Auto'
        or prep.source == 'current'
        or prep.pitcher_chosen is not False
        or str(prep.inning) != str(_next_inning_key(current_inning))
    ):
        return prep
    effective, carry = _carried_plan(
        game, team, prep.alignment or {}, current_alignment, events,
        live_change=_pitching_changed_this_inning(events, current_inning),
    )
    if carry:
        prep.effective_alignment = effective
        prep.pitcher_adjustment = carry
    return prep


def _next_inning_context(game, team):
    rotation, actual_rotation, events = _actual_rotation(game, team.id)
    current_inning = str(game.live_current_inning or '1')
    next_inning = _next_inning_key(current_inning)
    current_alignment = deepcopy(
        actual_rotation.get(current_inning, {}) or {}
    )
    field_changed = _field_changed_this_inning(
        events,
        current_inning,
        current_alignment,
        team,
    )
    planned_alignment = deepcopy(
        (rotation.innings or {}).get(next_inning, {})
        if rotation and next_inning
        else {}
    )
    # The plan as the next inning will use it: a pitcher who already came out
    # is not brought back just because the old plan still names him -- the
    # pitcher now on the mound carries on (carry_planned_pitcher). The saved
    # plan itself is unchanged.
    planned_alignment, _ = _carried_plan(
        game, team, planned_alignment, current_alignment, events,
        live_change=_pitching_changed_this_inning(events, current_inning),
    )

    prep = _prep_for_game(game.id, team.id)

    if prep and prep.inning != next_inning:
        db.session.delete(prep)
        db.session.commit()
        prep = None

    # An automatic NEXT is a default, not a coach decision. Keep it in step
    # with the live field so a mid-inning change (a new pitcher, a swap)
    # carries into the next inning instead of the field as it was when NEXT
    # was first seeded. Same defense is the coach choosing "carry the field
    # forward", so it follows the field too, without the plan. Any other NEXT
    # a coach set during the game (NEXT is only writable while live) is
    # never touched.
    if prep and (prep.updated_by == 'Auto' or prep.source == 'current'):
        if prep.updated_by == 'Auto':
            seeded, source = _seed_next_alignment(
                current_alignment,
                planned_alignment,
                team,
                field_changed,
            )
        else:
            seeded, source = _seed_next_alignment(current_alignment, {}, team)
        if prep.alignment != seeded or prep.source != source:
            prep.alignment = seeded
            prep.source = source
            prep.updated_at = datetime.utcnow()
            db.session.commit()

    if not prep and next_inning:
        seeded, source = _seed_next_alignment(
            current_alignment,
            planned_alignment,
            team,
            field_changed,
        )

        prep = GameNextInningPrep(
            game_id=game.id,
            team_id=team.id,
            inning=next_inning,
            alignment=seeded,
            source=source,
            updated_by='Auto',
            updated_at=datetime.utcnow(),
        )
        db.session.add(prep)
        try:
            db.session.commit()
        except IntegrityError:
            # Another request created this game's prep row between our read
            # above and this commit. The board polls this endpoint every 3.5
            # seconds and the GET is not covered by the live-write semaphore,
            # so at an inning rollover several coaches race to seed the same
            # row. uq_game_next_inning_prep is what stops a duplicate landing;
            # losing that race is normal, not an error to show a coach.
            #
            # This does not inspect which constraint failed. What it
            # guarantees is: roll back, re-read the expected prep row, adopt
            # that row only if it exists and is for the exact inning this
            # request computed, and otherwise re-raise the original
            # IntegrityError unchanged.
            db.session.rollback()
            prep = _prep_for_game(game.id, team.id)
            if prep is None or prep.inning != next_inning:
                raise

    # A coach-saved defense whose pitcher the coach did not choose follows a
    # live pitching change; the saved row itself is unchanged.
    _effective_prep(game, team, prep, current_inning, current_alignment, events)

    # pregame_rotation is the plan as it was written before first pitch.
    # _planned_rotation already hands _actual_rotation its own deep copy to
    # apply events onto, so rotation.innings here is still pristine; copying
    # again keeps the response from aliasing the ORM attribute either way.
    return (
        current_inning,
        next_inning,
        current_alignment,
        planned_alignment,
        prep,
        deepcopy(rotation.innings or {}) if rotation else {},
        deepcopy(actual_rotation),
    )


@live_game_ui_bp.route('/api/live-game/<int:game_id>/next-inning-prep', methods=['GET', 'POST', 'DELETE'])
def next_inning_prep(game_id):
    user, team, game = _authorized_context(game_id)
    if not game:
        return jsonify({'status': 'error', 'message': 'Unauthorized or game not found.'}), 403

    # The board-prep helper is present on Game Management before Live Game starts.
    # A harmless GET should not fill DevTools with 409s while a coach is planning.
    # Writes remain live-only so pregame code cannot accidentally create live state.
    if not game.is_live:
        if request.method == 'GET':
            return jsonify({
                'status': 'inactive',
                'game_id': game.id,
                'is_live': False,
                'current_inning': str(game.live_current_inning or '1'),
                'next_inning': _next_inning_key(game.live_current_inning or '1'),
                'current_alignment': {},
                'planned_alignment': {},
                'pregame_rotation': {},
                'actual_rotation': {},
                'confirmed': None,
                'roster': [],
                'outfielder_count': team.outfielder_count,
            })
        return jsonify({'status': 'error', 'message': 'Game is not live.'}), 409

    (
        current_inning,
        next_inning,
        current_alignment,
        planned_alignment,
        prep,
        pregame_rotation,
        actual_rotation,
    ) = _next_inning_context(game, team)
    if not next_inning:
        return jsonify({'status': 'error', 'message': 'Current inning is invalid.'}), 409

    if request.method == 'DELETE':
        if prep:
            db.session.delete(prep)
            db.session.commit()
            socketio.emit('next_inning_prep_update', {'game_id': game.id, 'inning': next_inning}, room=f'team_{team.id}_game_{game.id}')
        return jsonify({'status': 'success', 'confirmed': None})

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        mode = (data.get('mode') or 'custom').lower()

        # Next Inning saves in the background while the coach keeps moving
        # players, so a save can land after the board changed elsewhere (a
        # new inning, another coach's edit). Clients that send what they
        # last saw get a conflict instead of silently overwriting it; older
        # callers that send neither field keep the previous behavior.
        #
        # Technical debt: that unversioned path exists only for tabs opened
        # before this deploy (the current board always sends both fields).
        # Remove it once such tabs are no longer a compatibility concern.
        #
        # The compare and the write are atomic only because this POST holds
        # the per-game lock in live_game_write_lock.py, which is valid for
        # the single-process eventlet deployment. Moving to multiple workers
        # or processes needs a database/Redis/distributed lock first.
        # Undo takes back only this coach's own last save. Checked first: a
        # screen that missed another coach's newer save gets this answer too,
        # not a generic conflict, and nothing of theirs is undone.
        if mode == 'undo' and prep is not None and prep.previous_alignment is not None \
                and not _undo_belongs_to(prep, user):
            return jsonify({
                'status': 'error',
                'code': 'next_prep_not_yours',
                'message': NOT_YOURS,
            }), 409

        conflict = _next_prep_conflict(data, next_inning, prep, team)
        if not conflict and mode == 'undo':
            conflict = _next_prep_undo_conflict(data, prep)
        if conflict:
            return jsonify({
                'status': 'error',
                'code': 'next_prep_conflict',
                'message': conflict,
            }), 409

        if mode == 'undo':
            # Back to the defense as saved before the last coach save: its
            # alignment, source, and who chose it ('Auto' = nobody, so it
            # follows the field and the plan again). One step only.
            if not prep or prep.previous_alignment is None:
                return jsonify({
                    'status': 'error',
                    'code': 'next_prep_nothing_to_undo',
                    'message': 'There is no next-inning edit to undo.',
                }), 409
            cleaned, message = _clean_draft_alignment(prep.previous_alignment, game, team)
            if cleaned is None:
                return jsonify({
                    'status': 'error',
                    'message': f"Can't undo: {message}",
                }), 409
            prep.alignment = cleaned
            prep.source = prep.previous_source
            prep.updated_by = prep.previous_updated_by
            # Nothing is left to undo, and whose the restored defense was is
            # only known by name.
            prep.updated_by_user_id = None
            prep.pitcher_chosen = prep.previous_pitcher_chosen
            prep.previous_alignment = None
            prep.previous_source = None
            prep.previous_updated_by = None
            prep.previous_pitcher_chosen = None
            prep.revision = int(prep.revision or 0) + 1
            prep.updated_at = datetime.utcnow()
            db.session.commit()
            socketio.emit(
                'next_inning_prep_update',
                {'game_id': game.id, 'inning': next_inning},
                room=f'team_{team.id}_game_{game.id}',
            )
            # Read back as the board will: an automatic defense follows the
            # field again, a saved one gets its effective pitcher.
            (current_inning, next_inning, current_alignment, planned_alignment,
             prep, pregame_rotation, actual_rotation) = _next_inning_context(game, team)
            return _next_prep_response(game, team, current_inning, next_inning, current_alignment,
                                       planned_alignment, prep, pregame_rotation, actual_rotation,
                                       viewer=user)

        if mode == 'current':
            candidate = deepcopy(current_alignment)
            source = 'current'

        elif mode == 'planned':
            candidate, source = _seed_next_alignment(
                current_alignment,
                planned_alignment,
                team,
            )

        elif mode == 'custom':
            candidate = data.get('alignment')
            source = 'custom'

        else:
            return jsonify({
                'status': 'error',
                'message': 'Unknown NEXT defense action.',
            }), 400

        cleaned, message = _clean_draft_alignment(
            candidate,
            game,
            team,
        )

        if cleaned is None:
            return jsonify({
                'status': 'error',
                'message': message,
            }), 409

        updated_by = _coach_name(user)
        # A pitcher the coach chose: this save changed P from what the board
        # showed, or an earlier save chose it. A fielding edit, "Use inning
        # plan" and "Same defense" do not choose the pitcher. A fielding edit
        # on a coach-saved defense keeps what that defense recorded -- None
        # (saved before this was recorded) stays unknown, not guessed from P.
        seen_pitcher = (prep_alignment(prep) if prep else {}).get('P') or ''
        if mode != 'custom':
            pitcher_chosen = False
        elif (cleaned.get('P') or '') != seen_pitcher:
            pitcher_chosen = True
        elif prep is not None and prep.updated_by != 'Auto' and prep.source != 'current':
            pitcher_chosen = prep.pitcher_chosen
        else:
            pitcher_chosen = False
        if prep and (prep.alignment != cleaned or prep.source != source or prep.updated_by != updated_by):
            # What Undo brings back: the defense as it was saved before this.
            prep.previous_alignment = deepcopy(prep.alignment)
            prep.previous_source = prep.source
            prep.previous_updated_by = prep.updated_by
            prep.previous_pitcher_chosen = prep.pitcher_chosen

        prep = prep or GameNextInningPrep(
            game_id=game.id,
            team_id=team.id,
        )

        prep.inning = next_inning
        prep.alignment = cleaned
        prep.source = source
        prep.updated_by = updated_by
        prep.updated_by_user_id = user.id
        prep.pitcher_chosen = pitcher_chosen
        prep.revision = int(prep.revision or 0) + 1
        prep.updated_at = datetime.utcnow()

        db.session.add(prep)
        db.session.commit()

        socketio.emit(
            'next_inning_prep_update',
            {
                'game_id': game.id,
                'inning': next_inning,
            },
            room=f'team_{team.id}_game_{game.id}',
        )

    return _next_prep_response(game, team, current_inning, next_inning, current_alignment,
                               planned_alignment, prep, pregame_rotation, actual_rotation,
                               viewer=user)


def _next_prep_response(game, team, current_inning, next_inning, current_alignment,
                        planned_alignment, prep, pregame_rotation, actual_rotation, viewer=None):
    # planned_alignment is the plan as the next inning uses it; the saved one
    # differs only when its pitcher was carried forward (_next_inning_context).
    events = _events(game.id, team.id)
    _effective_prep(game, team, prep, current_inning, current_alignment, events)
    saved_plan = (pregame_rotation or {}).get(next_inning) or {}
    # Why the pitcher differs from what was saved: a coach-saved defense's
    # pitcher carried by a live change, else (for a plan-based defense) the
    # plan's pitcher carried forward -- only when the defense shows that
    # pitcher (a plan-based one saved before pitcher_chosen keeps its own).
    # A coach's defense as saved has none.
    pitcher_carry = getattr(prep, 'pitcher_adjustment', None) if prep else None
    plan_based = prep is None or (
        prep.source == 'planned' and prep_alignment(prep).get('P') == planned_alignment.get('P')
    )
    if (not pitcher_carry and plan_based and saved_plan.get('P')
            and saved_plan.get('P') != planned_alignment.get('P')):
        pitcher = planned_alignment.get('P')
        pitcher_carry = {
            'pitcher': pitcher,
            'planned_pitcher': saved_plan.get('P'),
            'position': next((pos for pos, name in saved_plan.items() if pos != 'P' and name == pitcher), None),
        }
    # The innings after the next one as they would start: the saved plan,
    # with the pitcher carried forward inning by inning from the next
    # inning's actual saved defense. For the Bench Report's projected sits.
    projected_innings = {}
    if prep and next_inning:
        projected_innings = project_planned_innings(
            pregame_rotation,
            next_inning,
            prep_alignment(prep),
            events,
            {player.name for player in _present_players(game, team.id)},
        )
    return jsonify({
        'status': 'success',
        'game_id': game.id,
        'current_inning': current_inning,
        # The current inning has only setup edits so far ("Not yet",
        # live_history): they are not in-game adjustments.
        'current_inning_setup_only': inning_has_only_setup_edits(game, team.id, current_inning),
        'next_inning': next_inning,
        'current_alignment': current_alignment,
        # planned_alignment stays the saved plan for the upcoming inning
        # only. The two below are whole-game reference data for Pregame Plan.
        'planned_alignment': deepcopy((pregame_rotation or {}).get(next_inning) or {}),
        # When that plan would bring back a pitcher who already came out:
        # who carries on instead ({'pitcher', 'planned_pitcher', 'position'}),
        # else None. planned_seed and the automatic defense already use it.
        'pitcher_carry': pitcher_carry,
        'projected_innings': projected_innings,
        # The upcoming inning's own plan as "Use 2nd-inning plan" would set it
        # (mode 'planned'), or None when the inning has no separate plan --
        # then the field simply carries forward.
        'planned_seed': _planned_seed(current_alignment, planned_alignment, team),
        'pregame_rotation': pregame_rotation,
        'actual_rotation': actual_rotation,
        # The game's scheduled innings (the team's effective regulation
        # innings, as Game Prep and the live state use), for Pregame Plan.
        'regulation_innings': regulation_innings_for_team(team),
        # Innings already played: how each ended, only where the game
        # recorded it, and who was here that inning (see _played_innings).
        'played_innings': _played_innings(game, team, current_inning),
        'confirmed': _prep_dict(prep, viewer),
        'roster': [
            {
                'id': player.id,
                'name': player.name,
                'number': getattr(player, 'number', None),
            }
            for player in _present_players(game, team.id)
        ],
        'outfielder_count': team.outfielder_count,
    })


def _versioned_static(filename):
    """Return a static URL carrying the application asset version.

    This used to version by file mtime. That gave a more precise URL but a
    different one from what the browser-side loaders produced, so a module
    injected here and also chain-loaded by another module arrived under two
    URLs and was downloaded twice. asset_versioning.py now owns the single
    value all three loading routes share.
    """
    return asset_url(filename)


@live_game_ui_bp.before_app_request
def protect_live_game_workflows():
    """Protect the pregame plan and require an explicit next-inning decision."""
    if request.method == 'POST' and request.endpoint == 'live_game_api.end_inning':
        return jsonify({
            'status': 'error',
            'code': 'legacy_live_write_disabled',
            'message': (
                'This End Inning action is no longer available from here. '
                'Use End Inning on the live game screen — it applies the '
                'prepared NEXT defense and advances the inning immediately.'
            ),
        }), 409

    # Start readiness belongs exclusively to live_game_api.start via
    # can_start_game(). This compatibility layer only clears staged next-inning
    # prep when a game is actually being finalized.
    if request.method == 'POST' and request.endpoint in {
        'live_game_api.end_game',
        'live_game_pitching.end_with_pitching',
    }:
        try:
            game_id = int((request.view_args or {}).get('game_id'))
        except (TypeError, ValueError):
            game_id = None
        if game_id:
            user, team, game = _authorized_context(game_id)
            if game and _clear_prep(game.id, team.id):
                db.session.commit()

    if request.method != 'POST' or request.endpoint != 'gameday.save_rotation':
        return None

    team_id = session.get('team_id')
    if not team_id:
        return None

    payload = request.get_json(silent=True) or {}
    game_id = payload.get('associated_game_id')

    if not game_id and payload.get('id'):
        try:
            rotation_id = int(payload.get('id'))
        except (TypeError, ValueError):
            rotation_id = None
        if rotation_id:
            rotation = db.session.query(Rotation).filter_by(id=rotation_id, team_id=team_id).first()
            if rotation:
                game_id = rotation.associated_game_id

    try:
        game_id = int(game_id) if game_id not in (None, '') else None
    except (TypeError, ValueError):
        game_id = None

    if not game_id:
        return None

    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if game and game.is_live:
        return jsonify({
            'status': 'error',
            'message': 'Pregame defense is locked while the game is live. Use Live Game controls.'
        }), 409

    return None


@live_game_ui_bp.after_app_request
def inject_live_game_assets(response):
    """Load the final live-game helpers and avoid a legacy first-paint flash."""
    if response.mimetype != 'text/html' or not re.fullmatch(r'/game/\d+/?', request.path):
        return response

    html = response.get_data(as_text=True)

    if 'coach-live-first-paint' not in html:
        first_paint = '''
<style id="coach-live-first-paint">
  #live-game-overlay:not(.coach-live-polished):not(.coach-live-boot-fallback) {
    visibility: hidden !important;
  }
  #pregame-checklist-container > .d-flex:first-child .bi {
    display: none !important;
  }
</style>
'''
        if '</head>' in html:
            html = html.replace('</head>', first_paint + '</head>', 1)
        else:
            html = first_paint + html

    # The style above hides the overlay until live_game_coach_ui.js polishes
    # it, so the reveal is what keeps a coach from staring at nothing when
    # that script never arrives. It is injected on its own, guarded by its own
    # marker: it used to ride along with the board assets below, which meant a
    # page that already carried those assets shipped no reveal at all and left
    # the overlay hidden for the whole session.
    if 'coach-live-boot-reveal' not in html:
        boot_reveal = '''
<script id="coach-live-boot-reveal">
  (function () {
    var GRACE_MS = 400;
    var CEILING_MS = 2500;
    var settled = false;
    var pending = false;
    var observer = null;

    function overlay() {
      return document.getElementById('live-game-overlay');
    }

    function has(node, name) {
      return node.classList.contains(name);
    }

    function stopWatching() {
      if (!observer) return;
      observer.disconnect();
      observer = null;
    }

    // The lifecycle is over: either the coach UI polished the overlay or the
    // fallback took the gate off. Nothing left to watch or wait for.
    function finish() {
      settled = true;
      pending = false;
      stopWatching();
    }

    function reveal() {
      // Whatever queued this attempt has now been spent, so a later visible
      // transition is free to arm a fresh one.
      pending = false;
      if (settled) return;
      var node = overlay();
      if (!node) return;
      if (has(node, 'coach-live-polished')) {
        finish();
        return;
      }
      // d-none means the overlay is deliberately off screen, so the gate is
      // not what is hiding it. Stripping the gate here would only spend it
      // early and let the raw board flash when the overlay is shown later.
      // Deliberately does not settle: the watcher stays armed for the show.
      if (has(node, 'd-none')) return;
      finish();
      node.classList.add('coach-live-boot-fallback');
    }

    // The coach UI polishes on DOMContentLoaded, so an overlay still
    // unpolished once every resource has settled is never getting polished --
    // no reason to make the dugout wait out the ceiling below.
    window.addEventListener('load', reveal);
    // Ceiling for the case where a hung request means load never fires.
    window.setTimeout(reveal, CEILING_MS);

    // An overlay left d-none above is shown later by the live game
    // controller, and the coach UI polishes it from its own class observer
    // within a frame. If that never happens the overlay would sit invisible
    // behind the gate with nothing left to reveal it, so watch for the
    // transition and fall back once a grace window has passed.
    function watch() {
      if (settled || !window.MutationObserver) return;
      var node = overlay();
      if (!node) return;
      observer = new window.MutationObserver(function () {
        if (settled) {
          stopWatching();
          return;
        }
        var current = overlay();
        if (!current) return;
        // The coach UI won the race, so settle here rather than holding the
        // observer open until some later mutation happens to re-enter it.
        if (has(current, 'coach-live-polished')) {
          finish();
          return;
        }
        if (has(current, 'd-none')) return;
        // One grace timer at a time. Class churn on the overlay would
        // otherwise queue a fresh one per mutation.
        if (pending) return;
        pending = true;
        window.setTimeout(reveal, GRACE_MS);
      });
      observer.observe(node, {attributes: true, attributeFilter: ['class']});
    }

    // This script runs in <head>, before the overlay has been parsed. The
    // ceiling can also beat a slow parse, hence the settled guard in watch().
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', watch);
    } else {
      watch();
    }
  })();
</script>
'''
        if '</head>' in html:
            html = html.replace('</head>', boot_reveal + '</head>', 1)
        else:
            html = boot_reveal + html

    # The shared drag manager must be defined before either live board
    # registers a surface with it. The two boards load by different
    # routes -- On the Field from the template, Next Inning injected
    # before </body> below -- so </head> is the only point that precedes
    # both.
    # Focus around every live dialog (live_game_modal_focus.js) listens at
    # the document, so it only has to load before the first dialog opens.
    if 'live_game_modal_focus.js' not in html:
        focus_asset = f'<script src="{_versioned_static("js/live_game_modal_focus.js")}"></script>\n'
        if '</head>' in html:
            html = html.replace('</head>', focus_asset + '</head>', 1)
        else:
            html = focus_asset + html

    if 'live_game_drag_controller.js' not in html:
        drag_asset = f'<script src="{_versioned_static("js/live_game_drag_controller.js")}"></script>\n'
        if '</head>' in html:
            html = html.replace('</head>', drag_asset + '</head>', 1)
        else:
            html = drag_asset + html

    # This controller must register before live_game_v2.js so it owns the End
    # Game click and prevents the old pitch-count-only finalization workflow.
    if 'live_game_pitching_finalize.js' not in html:
        finalize_asset = f'<script src="{_versioned_static("js/live_game_pitching_finalize.js")}"></script>\n'
        v2_marker = '<script src="/static/js/live_game_v2.js"></script>'
        if v2_marker in html:
            html = html.replace(v2_marker, finalize_asset + v2_marker, 1)
        elif '</head>' in html:
            html = html.replace('</head>', finalize_asset + '</head>', 1)
        else:
            html = finalize_asset + html

    if 'live_game_board_prep_v2.js' not in html:
        assets = f'''
<script src="{_versioned_static('js/live_game_pitcher_change_complete.js')}"></script>
<script src="{_versioned_static('js/live_game_board_prep_v2.js')}"></script>
<script src="{_versioned_static('js/live_game_postgame_cleanup.js')}"></script>
'''
        if '</body>' in html:
            html = html.replace('</body>', assets + '</body>', 1)
        else:
            html += assets

    response.set_data(html)
    return response