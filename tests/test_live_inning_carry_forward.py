"""End Inning keeps the decisions a coach made during the live game.

The NEXT board is seeded automatically the first time it is read in an
inning. That seed used to be a snapshot: if the coach then changed pitchers
(or moved anyone else) mid-inning, End Inning committed the snapshot and put
the old defense back on the field.

Precedence for the next inning's defense is now:

1. a NEXT the coach set by hand during the live game (Same defense means
   "carry the field forward", so it keeps following the field);
2. otherwise, if the field changed during this inning, the whole field as it
   stands -- a pregame plan for the next inning does not undo it;
3. otherwise, the pregame plan for the next inning (or the field, if none).
"""

from datetime import datetime

from werkzeug.security import generate_password_hash


NAMES = ['Aiden', 'Bennett', 'Carter', 'Drew', 'Eli', 'Finn', 'Gavin', 'Hudson', 'Isaac', 'Jack']
JACK_ID = 10

INNING_ONE = {
    'P': 'Aiden', 'C': 'Bennett', '1B': 'Carter', '2B': 'Drew', '3B': 'Eli',
    'SS': 'Finn', 'LF': 'Gavin', 'CF': 'Hudson', 'RF': 'Isaac',
}


def _build_app(monkeypatch, planned_innings):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from blueprints import live_game_bulk_api
    from db import db
    from models import Game, Player, Rotation, Team, TeamMembership, User

    # Eligibility has its own tests; every pitcher here is available.
    monkeypatch.setattr(
        live_game_bulk_api,
        'get_authoritative_live_state',
        lambda game_id, team_id: {'pitch_count_summary': {name: {'status': 'Available'} for name in NAMES}},
    )

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        team = Team(id=1, team_name='Carry Forward Team', registration_code='carry-forward',
                    age_group='9U', pitching_rule_set='MLB Pitch Smart', outfielder_count=3,
                    timezone='America/Indiana/Indianapolis')
        user = User(id=1, username='coach', full_name='Test Coach',
                    password_hash=generate_password_hash('password123'))
        db.session.add_all([team, user])
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=1, role='Head Coach', player_order=[]))
        db.session.add_all([Player(id=i + 1, name=name, number=str(i + 1), team_id=1)
                            for i, name in enumerate(NAMES)])
        game = Game(id=80, date=datetime(2026, 9, 24, 17, 0, 0), opponent='Carry Forward',
                    team_id=1, is_live=True, live_current_inning='1')
        db.session.add_all([game, Rotation(id=1, title='Carry Forward Rotation', innings=planned_innings,
                                           associated_game_id=80, team_id=1)])
        db.session.commit()

    client = app.test_client()
    with client.session_transaction() as session:
        session.update(logged_in=True, username='coach', full_name='Test Coach', team_id=1, role='Head Coach')
    return client


def _state(client):
    return client.get('/api/live-game/80/state').get_json()


def _sequence(client):
    events = _state(client).get('rotation_events') or []
    return max([int(e.get('sequence') or 0) for e in events if not e.get('reverted')] or [0])


def _prep(client):
    response = client.get('/api/live-game/80/next-inning-prep')
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _change_pitcher_to_jack(client):
    alignment = dict(_state(client)['current_alignment'], P='Jack')
    response = client.post('/api/live-game/80/complete-pitcher-change', json={
        'base_sequence': _sequence(client), 'fast': True, 'new_pitcher_id': JACK_ID, 'alignment': alignment,
    })
    assert response.status_code == 200, response.get_data(as_text=True)


def _swap_left_and_right(client):
    current = _state(client)['current_alignment']
    alignment = dict(current, LF=current['RF'], RF=current['LF'])
    response = client.post('/api/live-game/80/defense-edit', json={
        'base_sequence': _sequence(client), 'alignment': alignment,
    })
    assert response.status_code == 200, response.get_data(as_text=True)


def _end_inning(client):
    """What End Inning on the live screen does: read NEXT, then commit it."""
    prep = _prep(client)
    response = client.post('/api/live-game/80/advance-inning', json={
        'alignment': prep['confirmed']['alignment'],
        'next_prep_id': prep['confirmed']['id'],
        'base_sequence': _sequence(client),
    })
    assert response.status_code == 200, response.get_data(as_text=True)
    state = _state(client)
    assert state['current_inning'] == '2'
    return state['current_alignment']


def test_mid_inning_pitcher_carries_into_an_unplanned_inning(monkeypatch):
    client = _build_app(monkeypatch, {'1': INNING_ONE})
    assert _prep(client)['confirmed']['alignment']['P'] == 'Aiden'   # NEXT is seeded at first pitch

    _change_pitcher_to_jack(client)

    assert _prep(client)['confirmed']['alignment']['P'] == 'Jack'
    assert _end_inning(client)['P'] == 'Jack'


def test_whole_live_alignment_carries_into_an_unplanned_inning(monkeypatch):
    client = _build_app(monkeypatch, {'1': INNING_ONE})
    _prep(client)

    _change_pitcher_to_jack(client)
    _swap_left_and_right(client)
    live = _state(client)['current_alignment']
    assert (live['P'], live['LF'], live['RF']) == ('Jack', 'Isaac', 'Gavin')

    after = _end_inning(client)
    assert {pos: after.get(pos) for pos in INNING_ONE} == {pos: live.get(pos) for pos in INNING_ONE}


def _inning_two_plan():
    return dict(INNING_ONE, P='Carter', **{'1B': 'Aiden'})


def test_live_changes_beat_the_pregame_plan_for_the_next_inning(monkeypatch):
    client = _build_app(monkeypatch, {'1': INNING_ONE, '2': _inning_two_plan()})
    assert _prep(client)['confirmed']['alignment']['P'] == 'Carter'   # the plan, before any change

    _change_pitcher_to_jack(client)
    _swap_left_and_right(client)
    live = _state(client)['current_alignment']

    after = _end_inning(client)
    assert after['P'] == 'Jack'
    assert {pos: after.get(pos) for pos in INNING_ONE} == {pos: live.get(pos) for pos in INNING_ONE}


def test_next_the_coach_edits_live_can_still_choose_the_planned_pitcher(monkeypatch):
    client = _build_app(monkeypatch, {'1': INNING_ONE, '2': _inning_two_plan()})
    _prep(client)
    _change_pitcher_to_jack(client)
    assert _prep(client)['confirmed']['alignment']['P'] == 'Jack'

    # The coach sets NEXT back to the plan, with Carter pitching.
    response = client.post('/api/live-game/80/next-inning-prep',
                           json={'mode': 'custom', 'alignment': _inning_two_plan()})
    assert response.status_code == 200

    after = _end_inning(client)
    assert {pos: after.get(pos) for pos in INNING_ONE} == _inning_two_plan()


def test_pregame_plan_applies_when_nothing_changed_this_inning(monkeypatch):
    client = _build_app(monkeypatch, {'1': INNING_ONE, '2': _inning_two_plan()})
    _prep(client)
    after = _end_inning(client)
    assert {pos: after.get(pos) for pos in INNING_ONE} == _inning_two_plan()


def test_an_undone_change_leaves_the_pregame_plan_in_place(monkeypatch):
    client = _build_app(monkeypatch, {'1': INNING_ONE, '2': _inning_two_plan()})
    _prep(client)
    _change_pitcher_to_jack(client)
    response = client.post('/api/live-game/80/undo', json={'base_sequence': _sequence(client)})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert _state(client)['current_alignment']['P'] == 'Aiden'

    after = _end_inning(client)
    assert {pos: after.get(pos) for pos in INNING_ONE} == _inning_two_plan()


def test_a_change_in_a_later_inning_carries_past_that_innings_plan(monkeypatch):
    inning_three = dict(_inning_two_plan(), P='Drew', **{'2B': 'Carter'})
    client = _build_app(monkeypatch, {'1': INNING_ONE, '2': _inning_two_plan(), '3': inning_three})
    _prep(client)
    _end_inning(client)                                    # inning 2 follows its plan

    assert _prep(client)['confirmed']['alignment']['P'] == 'Drew'
    _change_pitcher_to_jack(client)                         # Carter -> Jack in inning 2
    live = _state(client)['current_alignment']

    prep = _prep(client)
    assert prep['confirmed']['alignment']['P'] == 'Jack'
    response = client.post('/api/live-game/80/advance-inning', json={
        'alignment': prep['confirmed']['alignment'], 'next_prep_id': prep['confirmed']['id'],
        'base_sequence': _sequence(client),
    })
    assert response.status_code == 200, response.get_data(as_text=True)
    state = _state(client)
    assert state['current_inning'] == '3'
    assert {pos: state['current_alignment'].get(pos) for pos in INNING_ONE} == \
        {pos: live.get(pos) for pos in INNING_ONE}


def test_next_the_coach_set_is_not_overwritten_by_live_changes(monkeypatch):
    client = _build_app(monkeypatch, {'1': INNING_ONE})
    _prep(client)
    coach_next = dict(INNING_ONE, P='Eli', **{'3B': 'Aiden'})
    response = client.post('/api/live-game/80/next-inning-prep', json={'mode': 'custom', 'alignment': coach_next})
    assert response.status_code == 200

    _change_pitcher_to_jack(client)

    assert _prep(client)['confirmed']['alignment']['P'] == 'Eli'
    after = _end_inning(client)
    assert {pos: after.get(pos) for pos in coach_next} == coach_next


def test_same_defense_keeps_following_the_live_field(monkeypatch):
    client = _build_app(monkeypatch, {'1': INNING_ONE, '2': _inning_two_plan()})
    _prep(client)
    response = client.post('/api/live-game/80/next-inning-prep', json={'mode': 'current'})
    assert response.status_code == 200
    assert response.get_json()['confirmed']['alignment']['P'] == 'Aiden'

    # Later in the inning the coach changes pitchers and swaps the corners.
    _change_pitcher_to_jack(client)
    _swap_left_and_right(client)
    live = _state(client)['current_alignment']

    after = _end_inning(client)
    assert after['P'] == 'Jack'
    assert {pos: after.get(pos) for pos in INNING_ONE} == {pos: live.get(pos) for pos in INNING_ONE}


def test_reading_next_without_live_changes_does_not_rewrite_it(monkeypatch):
    client = _build_app(monkeypatch, {'1': INNING_ONE})
    first = _prep(client)['confirmed']
    second = _prep(client)['confirmed']
    assert second == first
