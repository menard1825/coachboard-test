"""Setup edits before an inning begins are not baseball history (live_history).

"Not yet" at "Has the 4th inning started?" saves an official field edit
(pre_start True): it builds the field, the inning's starting defense and
Undo, but no substitution or pitching change happened. Every consumer that
reads events as history -- who pitched, pitching changes and re-entry, the
game report's changes, End Game's pitch-count list, season and position
appearances -- reads gameplay_events(). Games recorded before the question
existed (pre_start None) keep their history exactly.

The pitcher example: End Inning loads Jules at P for the 2nd; before the
2nd begins the coach makes Indy the pitcher. Indy pitched the 2nd. Jules did
not pitch, was never removed from the mound, and there was no Jules -> Indy
pitching change. Said after "Yes, inning started", the same change is a real
pitching change.
"""

from types import SimpleNamespace

from live_history import INNING_STARTED, gameplay_events, setup_starting_defenses
from test_game_availability import (  # noqa: F401 (app is a fixture)
    FULL,
    GAME_ID,
    TEAM_ID,
    _app,
    _client,
    _enter_inning,
    _go_live,
    _sequence,
)


# --- The helper (pure) ---------------------------------------------------------------------------

TOM_P = {'P': 'Tom', 'C': 'Cole', 'SS': 'Jake'}
JAKE_P = {'P': 'Jake', 'C': 'Cole', 'SS': 'Tom'}
MIKE_P = {'P': 'Mike', 'C': 'Cole', 'SS': 'Jake'}


def _e(sequence, event_type, inning, before, after, pre_start=None, reverted=False):
    return SimpleNamespace(
        id=sequence, sequence=sequence, event_type=event_type, inning=str(inning), reverted=reverted,
        before_alignment=dict(before), after_alignment=dict(after), game_id=1,
        old_pitcher_id=None, new_pitcher_id=None, pre_start=pre_start,
        subject_player_id=None, effective_inning=None, timestamp=None, changed_by_user=None, team_id=1,
    )


def _pitchers(events):
    seen = []
    for event in events:
        for alignment in (event.before_alignment, event.after_alignment):
            name = (alignment or {}).get('P')
            if name and name not in seen:
                seen.append(name)
    return seen


def test_a_setup_pitching_change_is_not_history():
    events = [
        _e(1, 'End Inning', 4, MIKE_P, TOM_P),
        _e(2, 'Pitcher Change', 4, TOM_P, JAKE_P, pre_start=True),   # Not yet
        _e(3, 'End Inning', 5, JAKE_P, JAKE_P),
    ]
    history = gameplay_events(events)
    assert [e.event_type for e in history] == ['End Inning', 'End Inning']
    assert history[0].after_alignment == JAKE_P       # the 4th began with Jake pitching
    assert history[0].source is events[0]              # a copy: the stored event is untouched
    assert events[0].after_alignment == TOM_P
    assert _pitchers(history) == ['Mike', 'Jake']      # Tom never pitched
    assert setup_starting_defenses(events) == {(1, '4'): JAKE_P}


def test_after_yes_the_same_change_is_a_pitching_change():
    events = [
        _e(1, 'End Inning', 4, MIKE_P, TOM_P),
        _e(2, INNING_STARTED, 4, TOM_P, TOM_P),
        _e(3, 'Pitcher Change', 4, TOM_P, JAKE_P, pre_start=False),
    ]
    history = gameplay_events(events)
    assert [e.event_type for e in history] == ['End Inning', 'Pitcher Change']
    assert history[0] is events[0]
    assert _pitchers(history) == ['Mike', 'Tom', 'Jake']


def test_setup_then_yes_begins_with_the_edited_defense():
    events = [
        _e(1, 'End Inning', 4, MIKE_P, TOM_P),
        _e(2, 'Pitcher Change', 4, TOM_P, JAKE_P, pre_start=True),
        _e(3, INNING_STARTED, 4, JAKE_P, JAKE_P),
        _e(4, 'Defensive Change', 4, JAKE_P, dict(JAKE_P, SS='Sam'), pre_start=False),
    ]
    history = gameplay_events(events)
    assert [e.event_type for e in history] == ['End Inning', 'Defensive Change']
    assert history[0].after_alignment == JAKE_P
    assert 'Tom' not in _pitchers(history)


def test_games_recorded_before_the_question_keep_their_history():
    legacy = [
        _e(1, 'End Inning', 4, MIKE_P, TOM_P),
        _e(2, 'Pitcher Change', 4, TOM_P, JAKE_P),   # pre_start None
    ]
    history = gameplay_events(legacy)
    assert history == legacy
    assert _pitchers(history) == ['Mike', 'Tom', 'Jake']


def test_undone_setup_edits_do_not_change_the_start():
    events = [
        _e(1, 'End Inning', 4, MIKE_P, TOM_P),
        _e(2, 'Pitcher Change', 4, TOM_P, JAKE_P, pre_start=True, reverted=True),
    ]
    history = gameplay_events(events)
    assert history == [events[0]]
    assert history[0].after_alignment == TOM_P


# --- Every history consumer, on a real game ------------------------------------------------------

LOADED = dict(FULL, P='Jules', RF='Indy')          # End Inning loads Jules at P for the 2nd
INDY_P = dict(FULL, P='Indy', RF='Jules')          # before the 2nd: Indy pitches, Jules to RF


def _change_pitcher_in_the_2nd(app, started):
    _go_live(app)
    _enter_inning(app, '2', LOADED)
    response = _client(app).post(f'/api/live-game/{GAME_ID}/complete-pitcher-change', json={
        'new_pitcher_id': 9, 'alignment': INDY_P, 'base_sequence': _sequence(app),
        'inning_started': started,
    })
    assert response.status_code == 200, response.get_json()


def _state(app):
    return _client(app).get(f'/api/live-game/{GAME_ID}/state').get_json()


def _game(app):
    from db import db
    from models import Game

    return db.session.get(Game, GAME_ID)


def _end_game_pitchers(app):
    from blueprints.live_game_pitching_api import _actual_pitcher_order

    with app.app_context():
        return _actual_pitcher_order(_game(app), TEAM_ID)


def _report(app):
    from db import db
    from game_day_helpers import build_actual_game_report
    from models import Team

    with app.app_context():
        return build_actual_game_report(_game(app), db.session.get(Team, TEAM_ID))


def _season_positions(app):
    from actual_stats import calculate_actual_position_game_stats
    from db import db
    from models import GameRotationEvent, Player, Rotation
    from season_stats import build_game_inning_records

    with app.app_context():
        roster = db.session.query(Player).all()
        rotations = db.session.query(Rotation).all()
        events = db.session.query(GameRotationEvent).all()
        records = build_game_inning_records(roster, rotations, events, [_game(app)], [])
        second = next(row for row in records[0]['innings'] if row['inning'] == 2)
        positions = calculate_actual_position_game_stats(roster, rotations, events, [_game(app)])
        return second['positions_by_player'], positions


def test_not_yet_the_loaded_pitcher_did_not_pitch(app):
    _change_pitcher_in_the_2nd(app, started=False)
    state = _state(app)

    # The field still has the setup edit.
    assert state['current_alignment']['P'] == 'Indy'
    assert [e['event_type'] for e in state['rotation_events']][-1] == 'Pitcher Change'

    # Pitching history: Alex pitched the 1st, Indy took the mound for the 2nd.
    assert [e['event_type'] for e in state['gameplay_events']] == ['End Inning']
    assert state['gameplay_events'][0]['after_alignment']['P'] == 'Indy'
    # Re-entry: Jules never pitched, so was never removed from the mound.
    assert state['pitch_count_summary'].get('Jules', {}).get('status') != 'Already Pitched This Game'
    # End Game asks for Alex and Indy only.
    assert _end_game_pitchers(app) == ['Alex', 'Indy']
    report = _report(app)
    assert report['expected_pitchers'] == ['Alex', 'Indy']
    assert not [c for c in report['changes'] if c['inning'] == '2' and c['description'] != 'End of inning']
    # Season and position history: Jules played RF in the 2nd, never P.
    second, positions = _season_positions(app)
    assert second['Jules'] == {'RF'}
    assert 'P' not in positions['Jules']


def test_yes_the_same_change_is_a_real_pitching_change(app):
    _change_pitcher_in_the_2nd(app, started=True)
    state = _state(app)
    assert [e['event_type'] for e in state['gameplay_events']] == ['End Inning', 'Pitcher Change']
    assert state['pitch_count_summary']['Jules']['status'] == 'Already Pitched This Game'
    assert _end_game_pitchers(app) == ['Alex', 'Jules', 'Indy']
    report = _report(app)
    assert report['expected_pitchers'] == ['Alex', 'Jules', 'Indy']
    assert any(c['inning'] == '2' and 'Indy to the mound' in c['description'] for c in report['changes'])
    second, positions = _season_positions(app)
    assert second['Jules'] == {'P', 'RF'}
    assert positions['Jules']['P'] == 1


def test_a_setup_edit_in_the_1st_is_not_the_plan(app):
    _go_live(app)
    response = _client(app).post(f'/api/live-game/{GAME_ID}/complete-pitcher-change', json={
        'new_pitcher_id': 9, 'alignment': dict(FULL, P='Indy', RF='Alex'), 'base_sequence': 0,
        'inning_started': False,
    })
    assert response.status_code == 200, response.get_json()
    indy_p = dict(FULL, P='Indy', RF='Alex')
    _enter_inning(app, '2', indy_p, before=indy_p)
    assert _end_game_pitchers(app) == ['Indy']
    first = next(row for row in _season_record(app) if row['inning'] == 1)
    assert first['positions_by_player']['Alex'] == {'RF'}      # the plan had Alex at P


def _season_record(app):
    from db import db
    from models import GameRotationEvent, Player, Rotation
    from season_stats import build_game_inning_records

    with app.app_context():
        records = build_game_inning_records(
            db.session.query(Player).all(), db.session.query(Rotation).all(),
            db.session.query(GameRotationEvent).all(), [_game(app)], [],
        )
        return records[0]['innings']


def test_plan_notes_call_setup_edits_setup_not_in_game_adjustments(app):
    prep = f'/api/live-game/{GAME_ID}/next-inning-prep'
    _go_live(app)
    _enter_inning(app, '2', LOADED)
    assert _client(app).get(prep).get_json()['current_inning_setup_only'] is False   # loaded only
    _change_pitcher_in_the_2nd_answered(app, False)
    assert _client(app).get(prep).get_json()['current_inning_setup_only'] is True
    edit = _client(app).post(f'/api/live-game/{GAME_ID}/defense-edit', json={
        'alignment': dict(INDY_P, SS='Harper', CF='Finn'), 'base_sequence': _sequence(app), 'inning_started': True,
    })
    assert edit.status_code == 200, edit.get_json()
    assert _client(app).get(prep).get_json()['current_inning_setup_only'] is False


def _change_pitcher_in_the_2nd_answered(app, started):
    response = _client(app).post(f'/api/live-game/{GAME_ID}/complete-pitcher-change', json={
        'new_pitcher_id': 9, 'alignment': INDY_P, 'base_sequence': _sequence(app), 'inning_started': started,
    })
    assert response.status_code == 200, response.get_json()
