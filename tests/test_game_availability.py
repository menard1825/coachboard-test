"""Game availability, inning by inning, and defensive participation.

PlayerGameAbsence is "Out at first pitch". A late arrival or a departure is a
'Player Arrived' / 'Player Left' live event (game_availability.py), replayed
with the first-pitch Outs into:

* present_now -- who can be put on the field now (every live check and the
  live state use it);
* availability windows -- the whole innings that count for each player.

Defensive participation comes from the event timeline: anyone who fielded
any part of an inning after it began played it. End Inning only loads the
next defense; the first On the Field change to an inning without an
'Inning Started' marker asks "Has the 4th inning started?", and "Yes"
records the marker just before the change. Played beats Sat beats Not Here.

There are no Arrived / Left endpoints yet; these tests write the events the
way the live endpoints will (same table, same sequence).
"""

from types import SimpleNamespace

import pytest

from game_availability import (
    ARRIVED,
    INNING_STARTED,
    LEFT,
    NOT_HERE,
    PLAYED,
    SAT,
    completed_innings,
    defensive_participation,
    inning_status,
    reached_innings,
    replay_availability,
)
from test_start_game_contract import (  # noqa: F401 (app is a fixture)
    FULL,
    GAME_ID,
    TEAM_ID,
    _app,
    _client,
    _out,
    _plan,
    _without,
)


# --- Replay (pure) ----------------------------------------------------------------------------

ROSTER = {1, 2, 3, 4}


def _change(sequence, event_type, player_id, from_inning, *, reverted=False, inning='1'):
    return SimpleNamespace(
        id=sequence, sequence=sequence, event_type=event_type, reverted=reverted, inning=inning,
        subject_player_id=player_id, effective_inning=from_inning,
        before_alignment={}, after_alignment={},
    )


def test_no_events_is_first_pitch_availability():
    availability = replay_availability(ROSTER, {4}, [])
    assert availability.present_now == {1, 2, 3}
    assert availability.not_here_now() == {4}
    assert availability.windows[1] == ((1, None),)
    assert availability.windows[4] == ()
    assert availability.left_game == frozenset()
    assert availability.available_in(1, 9) and not availability.available_in(4, 1)


def test_out_at_first_pitch_stays_out_without_an_arrival():
    other_events = [SimpleNamespace(id=1, sequence=1, event_type='End Inning', reverted=False, inning='2',
                                    subject_player_id=None, effective_inning=None)]
    availability = replay_availability(ROSTER, {4}, other_events)
    assert not availability.is_present(4)
    assert availability.windows[4] == ()


def test_a_late_arrival_counts_from_the_inning_the_coach_chose():
    availability = replay_availability(ROSTER, {4}, [_change(1, ARRIVED, 4, 5, inning='4')])
    # Here now -- he can go in during the 4th -- but the 4th is not his to sit.
    assert availability.is_present(4)
    assert availability.windows[4] == ((5, None),)
    assert not availability.available_in(4, 4)
    assert availability.available_in(4, 5)


def test_a_departure_ends_the_window_and_the_player_is_not_here():
    availability = replay_availability(ROSTER, set(), [_change(1, LEFT, 2, 5)])
    assert not availability.is_present(2)
    assert availability.left_game == {2}
    assert availability.windows[2] == ((1, 4),)


def test_leaving_and_coming_back_gives_two_windows():
    availability = replay_availability(ROSTER, set(), [_change(1, LEFT, 2, 5), _change(2, ARRIVED, 2, 7)])
    assert availability.is_present(2)
    assert availability.left_game == frozenset()
    assert availability.windows[2] == ((1, 4), (7, None))


@pytest.mark.parametrize('events, absent, present, window', [
    # "Jake Arrived" by mistake, then "Jake isn't here" from the same inning.
    ([_change(1, ARRIVED, 4, 4), _change(2, LEFT, 4, 4)], {4}, False, ()),
    # "Sam Left" by mistake, then "Sam is back" from the same inning.
    ([_change(1, LEFT, 4, 5), _change(2, ARRIVED, 4, 5)], set(), True, ((1, None),)),
    # A later correction with an earlier inning restates from that inning on.
    ([_change(1, LEFT, 4, 6), _change(2, LEFT, 4, 5)], set(), False, ((1, 4),)),
    ([_change(1, LEFT, 4, 5), _change(2, ARRIVED, 4, 3)], set(), True, ((1, None),)),
])
def test_a_counter_event_corrects_without_rewriting(events, absent, present, window):
    availability = replay_availability(ROSTER, absent, events)
    assert availability.is_present(4) is present
    assert availability.windows[4] == window


def test_reverted_events_do_not_count():
    availability = replay_availability(ROSTER, {4}, [
        _change(1, ARRIVED, 4, 2, reverted=True),
        _change(2, LEFT, 1, 3, reverted=True),
    ])
    assert availability.present_now == {1, 2, 3}
    assert availability.windows[4] == ()
    assert availability.windows[1] == ((1, None),)


def test_events_replay_in_sequence_order_not_list_order():
    availability = replay_availability(ROSTER, set(), [_change(2, ARRIVED, 3, 5), _change(1, LEFT, 3, 5)])
    assert availability.is_present(3)
    assert availability.windows[3] == ((1, None),)


def test_an_event_for_another_team_player_is_ignored():
    availability = replay_availability(ROSTER, set(), [_change(1, LEFT, 99, 2)])
    assert availability.present_now == ROSTER
    assert 99 not in availability.windows


# --- Defensive participation (pure) ------------------------------------------------------------

A = {'P': 'Pat', 'C': 'Cole', 'CF': 'Graham'}
B = {'P': 'Pat', 'C': 'Cole', 'CF': 'Rylan'}
WRONG = {'P': 'Pat', 'C': 'Cole', 'CF': 'Wes'}
PLAN = {str(n): A for n in range(1, 7)}
PLAN['5'] = {'P': 'Pat', 'C': 'Cole', 'CF': 'Future'}


def _event(sequence, event_type, inning, before, after, *, reverted=False):
    return SimpleNamespace(
        id=sequence, sequence=sequence, event_type=event_type, inning=str(inning), reverted=reverted,
        before_alignment=dict(before), after_alignment=dict(after),
        subject_player_id=None, effective_inning=None,
    )


def _started(sequence, inning, alignment, *, reverted=False):
    return _event(sequence, INNING_STARTED, inning, alignment, alignment, reverted=reverted)


def _actual(plan, events):
    # As _actual_rotation builds it: the plan, then each event's after.
    actual = {inning: dict(alignment) for inning, alignment in plan.items()}
    for event in sorted(events, key=lambda e: e.sequence):
        if not event.reverted:
            actual[event.inning] = dict(event.after_alignment)
    return actual


def _participation(events, *, is_live=False, current='1', plan=PLAN):
    reached = reached_innings(events, is_live=is_live, current_inning=current)
    completed = completed_innings(reached, is_live=is_live, current_inning=current)
    return defensive_participation(_actual(plan, events), events, reached, completed)


def _to_the_4th():
    return [_event(1, 'End Inning', 2, A, A), _event(2, 'End Inning', 3, A, A), _event(3, 'End Inning', 4, A, A)]


# The seven cases.

def test_1_a_loaded_player_removed_before_the_inning_starts_did_not_play():
    # End 3rd loads Graham at CF; before the 4th begins CF becomes Rylan ("Not yet").
    events = _to_the_4th() + [_event(4, 'Defensive Change', 4, A, B), _event(5, 'End Inning', 5, B, B)]
    participation = _participation(events, is_live=True, current='5')
    assert 'Graham' not in participation['4']
    assert 'Rylan' in participation['4']


def test_2_a_loaded_defense_left_alone_played_the_completed_inning():
    events = _to_the_4th() + [_event(4, 'End Inning', 5, A, A)]
    participation = _participation(events, is_live=True, current='5')
    assert participation['4'] == frozenset(A.values())


def test_3_a_player_who_began_the_inning_then_was_substituted_played_it():
    events = _to_the_4th() + [_started(4, 4, A), _event(5, 'Defensive Change', 4, A, B), _event(6, 'End Inning', 5, B, B)]
    participation = _participation(events, is_live=True, current='5')
    assert {'Graham', 'Rylan'} <= participation['4']
    assert '5' not in participation  # loaded, not begun


def test_4_a_player_who_entered_after_the_inning_began_played_it():
    open_cf = {'P': 'Pat', 'C': 'Cole'}
    events = _to_the_4th()[:2] + [_event(3, 'End Inning', 4, A, open_cf), _started(4, 4, open_cf),
                                  _event(5, 'Defensive Change', 4, open_cf, B)]
    participation = _participation(events, is_live=True, current='4')
    assert 'Rylan' in participation['4']


def test_5_a_pre_start_mis_tap_corrected_before_the_inning_did_not_play():
    events = _to_the_4th() + [
        _event(4, 'Defensive Change', 4, A, WRONG),   # Not yet: Wes by mistake
        _event(5, 'Defensive Change', 4, WRONG, A),   # Not yet: back to Graham
        _event(6, 'End Inning', 5, A, A),
    ]
    participation = _participation(events, is_live=True, current='5')
    assert 'Wes' not in participation['4']
    assert 'Graham' in participation['4']


def test_6_undoing_an_in_inning_appearance_removes_it_and_keeps_the_start():
    events = _to_the_4th() + [_started(4, 4, A), _event(5, 'Defensive Change', 4, A, B, reverted=True)]
    participation = _participation(events, is_live=True, current='4')
    assert 'Rylan' not in participation['4']
    assert 'Graham' in participation['4']


def test_7_planned_innings_never_count():
    events = [_event(1, 'End Inning', 2, A, A)]
    participation = _participation(events, is_live=True, current='2')
    assert set(participation) == {'1'}  # the 2nd hasn't begun; the 3rd-6th are only planned
    assert not any('Future' in names for names in participation.values())


# More of the rule.

def test_repeated_pre_start_edits_stay_pre_start_until_yes():
    events = _to_the_4th() + [
        _event(4, 'Defensive Change', 4, A, WRONG),        # Not yet
        _event(5, 'Defensive Change', 4, WRONG, B),        # Not yet
        _started(6, 4, B),                                 # Yes, at the next change
        _event(7, 'Defensive Change', 4, B, A),
    ]
    participation = _participation(events, is_live=True, current='4')
    assert participation['4'] == {'Pat', 'Cole', 'Rylan', 'Graham'}
    assert 'Wes' not in participation['4']


def test_the_inning_being_played_counts_once_it_has_started():
    assert '4' not in _participation(_to_the_4th(), is_live=True, current='4')
    started = _participation(_to_the_4th() + [_started(4, 4, A)], is_live=True, current='4')
    assert started['4'] == frozenset(A.values())


def test_a_completed_game_counts_its_last_inning():
    events = _to_the_4th() + [_event(4, 'End Game', 4, A, A)]
    assert _participation(events)['4'] == frozenset(A.values())


def test_the_first_inning_is_unstarted_until_the_coach_says_so_or_it_ends():
    assert _participation([], is_live=True, current='1') == {}
    assert _participation([], is_live=False) == {}  # a game that never started
    ended_first = [_event(1, 'End Inning', 2, A, B)]
    assert _participation(ended_first, is_live=True, current='2')['1'] == frozenset(A.values())


def test_availability_events_do_not_start_an_inning():
    arrived = _to_the_4th() + [_event(4, ARRIVED, 4, A, A)]
    assert '4' not in _participation(arrived, is_live=True, current='4')


def test_a_player_who_left_while_fielding_after_the_start_played_that_inning():
    events = _to_the_4th() + [_started(4, 4, A), _event(5, LEFT, 4, A, _without(A, 'CF'))]
    assert 'Graham' in _participation(events, is_live=True, current='4')['4']


def test_a_reverted_marker_does_not_start_the_inning():
    events = _to_the_4th() + [_started(4, 4, A, reverted=True)]
    assert '4' not in _participation(events, is_live=True, current='4')


def test_a_postgame_correction_restates_the_record():
    events = [
        _started(1, 1, A),
        _event(2, 'Defensive Change', 1, A, B),                     # Graham -> Rylan during the 1st
        _event(3, 'End Game', 1, B, B),
        _event(4, 'Postgame Correction', 1, B, dict(B, CF='Max')),  # it was Max, not Rylan
    ]
    assert _participation(events)['1'] == {'Pat', 'Cole', 'Graham', 'Max'}


def test_a_correction_of_an_inning_without_a_start_is_its_recorded_defense():
    events = [_event(1, 'End Game', 1, A, A), _event(2, 'Postgame Correction', 1, A, B)]
    assert _participation(events)['1'] == frozenset(B.values())


def test_played_beats_sat_beats_not_here():
    availability = replay_availability({1, 2, 3}, set(), [_change(1, LEFT, 1, 2), _change(2, LEFT, 2, 2)])
    graham = SimpleNamespace(id=1, name='Graham')
    sam = SimpleNamespace(id=2, name='Sam')
    jo = SimpleNamespace(id=3, name='Jo')
    participation = {'1': frozenset({'Graham'}), '2': frozenset({'Graham'})}
    # Graham's window ends after the 1st, but he fielded part of the 2nd.
    assert inning_status(graham, '2', availability, participation) == PLAYED
    assert inning_status(sam, '1', availability, participation) == SAT
    assert inning_status(sam, '2', availability, participation) == NOT_HERE
    assert inning_status(jo, '2', availability, participation) == SAT
    # An inning that hasn't begun is nobody's sit.
    assert inning_status(jo, '3', availability, participation) is None


# --- Live state and live writes ---------------------------------------------------------------

JULES = 10  # on the bench in FULL
INDY = 9    # RF in FULL
STATE = f'/api/live-game/{GAME_ID}/state'


def _go_live(app, inning_one=FULL):
    from db import db
    from models import Game

    _plan(app, {'1': inning_one, '2': inning_one})
    with app.app_context():
        game = db.session.get(Game, GAME_ID)
        game.is_live = True
        game.live_current_inning = '1'
        db.session.commit()


def _write_event(app, event_type, *, subject=None, from_inning=None, after=FULL, inning='1', before=FULL):
    from db import db
    from models import GameRotationEvent

    with app.app_context():
        last = db.session.query(GameRotationEvent).order_by(GameRotationEvent.sequence.desc()).first()
        event = GameRotationEvent(
            team_id=TEAM_ID, game_id=GAME_ID, inning=inning, sequence=(last.sequence + 1) if last else 1,
            event_type=event_type, before_alignment=dict(before), after_alignment=dict(after),
            subject_player_id=subject, effective_inning=from_inning,
        )
        db.session.add(event)
        db.session.commit()
        return event.id, event.sequence


def _revert(app, event_id):
    from db import db
    from models import GameRotationEvent

    with app.app_context():
        db.session.get(GameRotationEvent, event_id).reverted = True
        db.session.commit()


def _state(app):
    return _client(app).get(STATE).get_json()


def _names(players):
    return sorted(player['name'] for player in players)


def _place(app, player_id, position, sequence, started=False):
    return _client(app).post(f'/api/live-game/{GAME_ID}/defensive-change', json={
        'player_id': player_id, 'destination_position': position, 'base_sequence': sequence,
        'inning_started': started,
    })


def test_live_state_without_availability_events_is_first_pitch_outs(app):
    _out(app, 'Jules')
    _go_live(app)
    state = _state(app)
    assert 'Jules' not in _names(state['roster'])
    assert _names(state['bench']) == []
    assert state['absent_player_ids'] == [JULES]
    assert state['alignment_valid'] is True


def test_a_late_arrival_is_on_the_bench_and_can_go_in(app):
    _out(app, 'Jules')
    _go_live(app)
    _, sequence = _write_event(app, ARRIVED, subject=JULES, from_inning=2)
    state = _state(app)
    assert _names(state['bench']) == ['Jules']
    assert state['absent_player_ids'] == []
    response = _place(app, JULES, 'RF', sequence)
    assert response.status_code == 200, response.get_json()
    assert _state(app)['current_alignment']['RF'] == 'Jules'


def test_a_player_who_left_is_not_here_and_cannot_go_in(app):
    _go_live(app)
    _, sequence = _write_event(app, LEFT, subject=JULES, from_inning=1)
    state = _state(app)
    assert 'Jules' not in _names(state['roster'])
    assert _names(state['bench']) == []
    assert state['absent_player_ids'] == [JULES]

    placed = _place(app, JULES, 'RF', sequence)
    assert placed.status_code == 409
    assert 'Jules is not available for this game.' in placed.get_json()['message']

    edited = _client(app).post(f'/api/live-game/{GAME_ID}/defense-edit', json={
        'base_sequence': sequence, 'alignment': dict(FULL, RF='Jules'),
    })
    assert edited.status_code == 409
    assert 'Jules is not available for this game.' in edited.get_json()['message']

    prep = _client(app).post(f'/api/live-game/{GAME_ID}/next-inning-prep', json={
        'mode': 'custom', 'alignment': dict(FULL, RF='Jules'), 'inning': '2',
    })
    assert prep.status_code in (400, 409)
    assert 'Jules is not available for this game.' in prep.get_json()['message']


def test_a_reverted_departure_does_not_count(app):
    _go_live(app)
    event_id, _ = _write_event(app, LEFT, subject=JULES, from_inning=1)
    _revert(app, event_id)
    assert _names(_state(app)['bench']) == ['Jules']


def test_a_player_recorded_as_left_but_still_on_the_field_is_flagged(app):
    _go_live(app)
    _write_event(app, LEFT, subject=INDY, from_inning=2)  # the field still has Indy at RF
    state = _state(app)
    assert state['alignment_valid'] is False
    assert state['alignment_availability_conflicts'] == ['Indy']
    assert state['alignment_warning'] == 'Indy left the game.'


def test_an_availability_event_is_part_of_the_live_version_and_undo(app):
    _out(app, 'Jules')
    _go_live(app)
    _, sequence = _write_event(app, ARRIVED, subject=JULES, from_inning=1)

    stale = _place(app, JULES, 'RF', sequence - 1)
    assert stale.status_code == 409
    assert stale.get_json()['code'] == 'stale_live_state'

    undone = _client(app).post(f'/api/live-game/{GAME_ID}/undo', json={'base_sequence': sequence})
    assert undone.status_code == 200, undone.get_json()
    state = undone.get_json()['state']
    assert state['absent_player_ids'] == [JULES]
    assert state['current_inning'] == '1'


def test_a_guest_keeps_defaulting_out_and_can_arrive(app):
    from db import db
    from models import Player

    with app.app_context():
        db.session.get(Player, JULES).is_guest = True
        db.session.commit()
    _out(app, 'Jules')
    _go_live(app)
    assert _state(app)['absent_player_ids'] == [JULES]
    _write_event(app, ARRIVED, subject=JULES, from_inning=1)
    assert _names(_state(app)['bench']) == ['Jules']


def test_deleting_a_player_keeps_their_availability_history_without_blocking(app):
    # subject_player_id is ON DELETE SET NULL (as lineup_entries.player_id):
    # an arrival or departure never prevents removing the player later.
    from db import db
    from models import GameRotationEvent, Player

    event_id, _ = _write_event(app, LEFT, subject=JULES, from_inning=2)
    response = _client(app).get(f'/delete_player/{JULES}')
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Player, JULES) is None
        event = db.session.get(GameRotationEvent, event_id)
        assert event is not None and event.subject_player_id is None


# --- "Has the 4th inning started?" on the server ------------------------------------------------

EDIT = f'/api/live-game/{GAME_ID}/defense-edit'
UNDO = f'/api/live-game/{GAME_ID}/undo'
WITH_JULES = dict(FULL, RF='Jules')    # Indy (RF) out, Jules in
WITH_INDY_CF = dict(FULL, CF='Indy', RF='Harper')


def _sequence(app):
    from blueprints.live_game_api import _current_sequence

    with app.app_context():
        return _current_sequence(GAME_ID, TEAM_ID)


def _edit(app, alignment, **answer):
    return _client(app).post(EDIT, json={'alignment': alignment, 'base_sequence': _sequence(app), **answer})


def _events(app):
    from db import db
    from models import GameRotationEvent

    with app.app_context():
        return [
            (e.event_type, e.inning, bool(e.reverted), dict(e.before_alignment or {}), dict(e.after_alignment or {}))
            for e in db.session.query(GameRotationEvent).order_by(GameRotationEvent.sequence).all()
        ]


def _has_started(app, inning=None):
    from db import db
    from game_availability import inning_has_started
    from models import Game

    with app.app_context():
        return inning_has_started(db.session.get(Game, GAME_ID), TEAM_ID, inning)


def _played(app):
    from db import db
    from game_availability import game_participation
    from models import Game

    with app.app_context():
        return game_participation(db.session.get(Game, GAME_ID), TEAM_ID)


def _enter_inning(app, inning, alignment=FULL, before=FULL):
    """As End Inning does: load the next inning's defense."""
    from db import db
    from models import Game

    _write_event(app, 'End Inning', inning=inning, after=alignment, before=before)
    with app.app_context():
        db.session.get(Game, GAME_ID).live_current_inning = inning
        db.session.commit()


def test_the_first_change_of_an_unstarted_inning_asks(app):
    _go_live(app)
    response = _edit(app, WITH_JULES)
    assert response.status_code == 409
    body = response.get_json()
    assert body['code'] == 'inning_start_question'
    assert body['title'] == 'Has the 1st inning started?'
    assert (body['not_yet_label'], body['yes_label']) == ('Not yet', 'Yes, inning started')
    assert _events(app) == []


def test_not_yet_saves_a_pre_start_edit_and_the_next_change_asks_again(app):
    _go_live(app)
    assert _edit(app, WITH_JULES, inning_started=False).status_code == 200
    assert [e[0] for e in _events(app)] == ['Bulk Defensive Change']
    assert not _has_started(app)
    assert _edit(app, FULL).get_json()['code'] == 'inning_start_question'


def test_yes_records_the_start_just_before_the_first_in_inning_change(app):
    _go_live(app)
    _edit(app, WITH_JULES, inning_started=False)                   # before the 1st
    assert _edit(app, WITH_INDY_CF, inning_started=True).status_code == 200
    kinds = [e[0] for e in _events(app)]
    assert kinds == ['Bulk Defensive Change', INNING_STARTED, 'Bulk Defensive Change']
    marker = _events(app)[1]
    assert marker[3] == marker[4] == WITH_JULES                   # the defense that began the 1st
    # Started: the next change is not asked about.
    assert _edit(app, FULL).status_code == 200
    played = _played(app)['1']
    assert {'Jules', 'Indy', 'Harper', 'Casey'} <= played        # began, moved, or came in
    assert 'Indy' in played


def test_undo_passes_over_the_start_marker(app):
    _go_live(app)
    _edit(app, WITH_JULES, inning_started=True)
    undone = _client(app).post(UNDO, json={'base_sequence': _sequence(app)})
    assert undone.status_code == 200, undone.get_json()
    assert [(e[0], e[2]) for e in _events(app)] == [(INNING_STARTED, False), ('Bulk Defensive Change', True)]
    assert _has_started(app)
    nothing = _client(app).post(UNDO, json={'base_sequence': _sequence(app)})
    assert nothing.status_code == 409
    assert nothing.get_json()['message'] == 'There is nothing to undo.'
    assert _has_started(app)
    # Still started: no question.
    assert _edit(app, WITH_JULES).status_code == 200


def test_undoing_the_end_inning_withdraws_that_innings_start(app):
    _go_live(app)
    _enter_inning(app, '2')
    _edit(app, WITH_JULES, inning_started=True)
    client = _client(app)
    assert client.post(UNDO, json={'base_sequence': _sequence(app)}).status_code == 200   # the change
    assert _has_started(app, '2')
    assert client.post(UNDO, json={'base_sequence': _sequence(app)}).status_code == 200   # End Inning
    assert not _has_started(app, '2')
    assert _state(app)['current_inning'] == '1'


def test_availability_events_do_not_start_an_inning(app):
    _out(app, 'Jules')
    _go_live(app)
    _write_event(app, ARRIVED, subject=JULES, from_inning=1)
    assert not _has_started(app)
    assert '1' not in _played(app)
    assert _edit(app, WITH_JULES).get_json()['code'] == 'inning_start_question'


def test_an_inning_without_changes_needs_no_answer_and_its_defense_played(app):
    from blueprints.live_game_ui import GameNextInningPrep
    from db import db

    _go_live(app)
    with app.app_context():
        db.session.add(GameNextInningPrep(inning='2', alignment=dict(FULL), source='custom',
                                          updated_by='Test Coach', game_id=GAME_ID, team_id=TEAM_ID))
        db.session.commit()
    ended = _client(app).post(f'/api/live-game/{GAME_ID}/advance-inning', json={
        'base_sequence': 0, 'alignment': dict(FULL),
    })
    assert ended.status_code == 200, ended.get_json()
    assert _played(app)['1'] == frozenset(FULL.values())
    assert '2' not in _played(app)


def _end_for_time_limit(app, played):
    return _client(app).post(f'/api/live-game/{GAME_ID}/end-with-pitching', json={
        'defer_pitching': True, 'end_reason': 'time_limit', 'current_inning_played': played,
    })


def test_time_limit_can_drop_an_inning_that_never_started(app):
    _out(app, 'Jules')
    _go_live(app)
    _enter_inning(app, '2')
    _write_event(app, ARRIVED, subject=JULES, from_inning=2, inning='2')
    _edit(app, WITH_JULES, inning_started=False)                   # a lineup fix before the 2nd
    response = _end_for_time_limit(app, False)
    assert response.status_code == 200, response.get_json()
    events = _events(app)
    assert ('End Inning', '2', True) == events[0][:3]
    assert ('Bulk Defensive Change', '2', True) == events[2][:3]    # withdrawn with the inning
    assert (ARRIVED, '1', False) == events[1][:3]                  # still happened, in the last inning played
    assert _state(app)['current_inning'] == '1'
    assert set(_played(app)) == {'1'}


def test_time_limit_keeps_an_inning_that_started(app):
    _go_live(app)
    _enter_inning(app, '2')
    _edit(app, WITH_JULES, inning_started=True)
    refused = _end_for_time_limit(app, False)
    assert refused.status_code == 409
    assert 'was recorded as started' in refused.get_json()['message']
    assert _end_for_time_limit(app, True).status_code == 200
    assert 'Jules' in _played(app)['2']
