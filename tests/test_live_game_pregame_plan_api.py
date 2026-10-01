"""next-inning-prep exposes whole-game defensive reference data.

Pregame Plan needs two things the endpoint did not previously return: the
plan exactly as it was written before first pitch, and what actually took the
field. The distinction is the whole point of the tab, so the tests below pin
it: an in-game defensive change must move `actual_rotation` and must leave
`pregame_rotation` alone.

`planned_alignment` keeps its old, narrower meaning -- the plan for the
upcoming inning only -- and the existing response contract is asserted
field by field so the new keys cannot quietly displace anything.
"""
from datetime import datetime

from werkzeug.security import generate_password_hash


INNING_ONE = {
    'P': 'Aiden',
    'C': 'Bennett',
    '1B': 'Carter',
    '2B': 'Drew',
    '3B': 'Eli',
    'SS': 'Finn',
    'LF': 'Gavin',
    'CF': 'Hudson',
    'RF': 'Isaac',
}

INNING_TWO = dict(INNING_ONE, RF='Jack', LF='Isaac')

INNING_THREE = dict(INNING_ONE, P='Bennett', C='Aiden')

PREGAME_PLAN = {
    '1': INNING_ONE,
    '2': INNING_TWO,
    '3': INNING_THREE,
}


def _build_app(monkeypatch, *, with_rotation=True):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Game, Player, Rotation, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Pregame Plan Team',
            registration_code='pregame-plan-code',
            age_group='9U',
            pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3,
            timezone='America/Indiana/Indianapolis',
        )
        user = User(
            id=1,
            username='coach',
            full_name='Test Coach',
            password_hash=generate_password_hash('password123'),
        )
        db.session.add_all([team, user])
        db.session.flush()
        db.session.add(TeamMembership(
            user_id=user.id,
            team_id=team.id,
            role='Head Coach',
            player_order=[],
        ))

        names = [
            'Aiden', 'Bennett', 'Carter', 'Drew', 'Eli',
            'Finn', 'Gavin', 'Hudson', 'Isaac', 'Jack',
        ]
        db.session.add_all([
            Player(id=index + 1, name=name, number=str(index + 1), team_id=team.id)
            for index, name in enumerate(names)
        ])

        game = Game(
            id=70,
            date=datetime(2026, 8, 30, 17, 0, 0),
            opponent='Pregame Plan Test',
            team_id=team.id,
            is_live=True,
            live_current_inning='2',
        )
        db.session.add(game)

        if with_rotation:
            db.session.add(Rotation(
                id=1,
                title='Pregame Plan Rotation',
                innings={key: dict(value) for key, value in PREGAME_PLAN.items()},
                associated_game_id=game.id,
                team_id=team.id,
            ))

        db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'


def _prep(client):
    response = client.get('/api/live-game/70/next-inning-prep')
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_get_returns_the_full_pregame_rotation(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    payload = _prep(client)

    assert payload['pregame_rotation'] == PREGAME_PLAN
    assert sorted(payload['pregame_rotation']) == ['1', '2', '3']


def test_get_returns_the_actual_rotation(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    payload = _prep(client)

    # With no defensive events yet, actual still mirrors the plan.
    assert payload['actual_rotation'] == PREGAME_PLAN


def test_existing_response_contract_is_unchanged(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    payload = _prep(client)

    assert payload['status'] == 'success'
    assert payload['game_id'] == 70
    assert payload['current_inning'] == '2'
    assert payload['next_inning'] == '3'
    assert payload['current_alignment'] == INNING_TWO
    # planned_alignment keeps meaning "the plan for the upcoming inning".
    assert payload['planned_alignment'] == INNING_THREE
    assert payload['confirmed'] is not None
    assert payload['confirmed']['inning'] == '3'
    assert payload['outfielder_count'] == 3
    assert {player['name'] for player in payload['roster']} == {
        'Aiden', 'Bennett', 'Carter', 'Drew', 'Eli',
        'Finn', 'Gavin', 'Hudson', 'Isaac', 'Jack',
    }


def test_defensive_change_moves_actual_but_never_the_pregame_plan(monkeypatch):
    """The reason the tab exists: the plan must stay readable as written even
    after the game has gone a different way."""
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    before = _prep(client)
    assert before['pregame_rotation']['2']['RF'] == 'Jack'

    edit = client.post('/api/live-game/70/defense-edit', json={
        'base_sequence': 0,
        'alignment': dict(INNING_TWO, RF='Gavin', LF='Jack'),
    })
    assert edit.status_code == 200, edit.get_data(as_text=True)

    after = _prep(client)

    assert after['actual_rotation']['2']['RF'] == 'Gavin'
    assert after['actual_rotation']['2']['LF'] == 'Jack'
    # The written plan is untouched, both in the response and in the row.
    assert after['pregame_rotation'] == PREGAME_PLAN
    assert after['pregame_rotation']['2']['RF'] == 'Jack'

    from db import db
    from models import Rotation

    with app.app_context():
        stored = db.session.query(Rotation).filter_by(associated_game_id=70).first()
        assert stored.innings == PREGAME_PLAN


def test_get_does_not_mutate_the_stored_plan(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    _prep(client)
    _prep(client)

    from db import db
    from models import Rotation

    with app.app_context():
        stored = db.session.query(Rotation).filter_by(associated_game_id=70).first()
        assert stored.innings == PREGAME_PLAN


def test_game_without_a_saved_plan_returns_an_empty_pregame_rotation(monkeypatch):
    app = _build_app(monkeypatch, with_rotation=False)
    client = app.test_client()
    _login(client)

    payload = _prep(client)

    assert payload['pregame_rotation'] == {}
    # Nothing is invented from the current defense to fill the gap.
    assert payload['actual_rotation'] == {}


def test_non_live_game_keeps_its_inactive_shape(monkeypatch):
    app = _build_app(monkeypatch)

    from db import db
    from models import Game

    with app.app_context():
        game = db.session.get(Game, 70)
        game.is_live = False
        db.session.commit()

    client = app.test_client()
    _login(client)

    response = client.get('/api/live-game/70/next-inning-prep')
    assert response.status_code == 200
    payload = response.get_json()

    assert payload['status'] == 'inactive'
    assert payload['is_live'] is False
    assert payload['pregame_rotation'] == {}
    assert payload['actual_rotation'] == {}


def test_get_returns_the_games_scheduled_innings(monkeypatch):
    """Pregame Plan shows one inning button per scheduled inning: the team's
    effective regulation innings (Auto from the age group, or its override),
    not just the innings the plan happens to cover."""
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    # 9U on Auto: six innings, although the plan covers only three.
    assert _prep(client)['regulation_innings'] == 6

    from db import db
    from models import Team

    with app.app_context():
        db.session.get(Team, 1).regulation_innings = 7
        db.session.commit()

    assert _prep(client)['regulation_innings'] == 7


# How a played inning ended: recorded evidence only ---------------------------

ENDED_ONE = dict(INNING_ONE, RF='Jack')     # the 1st as the game recorded it


def _add_event(app, sequence, event_type, inning, before=None, after=None, **extra):
    from db import db
    from models import GameRotationEvent

    with app.app_context():
        db.session.add(GameRotationEvent(
            game_id=70,
            team_id=1,
            sequence=sequence,
            event_type=event_type,
            inning=inning,
            before_alignment=before,
            after_alignment=after,
            reverted=extra.pop('reverted', False),
            **extra,
        ))
        db.session.commit()


def test_an_untouched_plan_is_not_how_a_played_inning_ended(monkeypatch):
    """The game is in the 2nd but nothing recorded how the 1st ended: the
    plan, copied into actual_rotation, must not be presented as the record."""
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    payload = _prep(client)

    assert payload['actual_rotation']['1'] == INNING_ONE      # the plan, as before
    assert payload['played_innings']['1']['alignment'] is None
    assert payload['played_innings']['1']['recorded_by'] is None
    assert list(payload['played_innings']) == ['1']          # the 2nd is being played


def test_end_inning_records_how_the_inning_ended(monkeypatch):
    app = _build_app(monkeypatch)
    _add_event(app, 1, 'End Inning', '2', before=ENDED_ONE, after=INNING_TWO)
    client = app.test_client()
    _login(client)

    played = _prep(client)['played_innings']['1']

    assert played['alignment'] == ENDED_ONE
    assert played['recorded_by'] == 'end_inning'


def test_an_undone_end_inning_is_no_record(monkeypatch):
    app = _build_app(monkeypatch)
    _add_event(app, 1, 'End Inning', '2', before=ENDED_ONE, after=INNING_TWO, reverted=True)
    client = app.test_client()
    _login(client)

    assert _prep(client)['played_innings']['1']['alignment'] is None


def test_a_later_correction_is_the_record(monkeypatch):
    corrected = dict(ENDED_ONE, LF='Jack', RF='Gavin')
    app = _build_app(monkeypatch)
    _add_event(app, 1, 'End Inning', '2', before=ENDED_ONE, after=INNING_TWO)
    _add_event(app, 2, 'Postgame Correction', '1', before=ENDED_ONE, after=corrected)
    client = app.test_client()
    _login(client)

    played = _prep(client)['played_innings']['1']

    assert played['alignment'] == corrected
    assert played['recorded_by'] == 'correction'


def test_a_played_innings_availability_is_that_innings_not_todays(monkeypatch):
    """Jack was Out at first pitch and arrived for the 2nd: here now, but not
    available in the 1st -- so not on the 1st inning's bench."""
    app = _build_app(monkeypatch)

    from db import db
    from models import PlayerGameAbsence

    with app.app_context():
        db.session.add(PlayerGameAbsence(player_id=10, game_id=70, team_id=1))
        db.session.commit()
    _add_event(app, 1, 'End Inning', '2', before=INNING_ONE, after=INNING_TWO)
    _add_event(app, 2, 'Player Arrived', '2', before=INNING_TWO, after=INNING_TWO,
               subject_player_id=10, effective_inning=2)
    client = app.test_client()
    _login(client)

    payload = _prep(client)

    assert 'Jack' in {player['name'] for player in payload['roster']}      # here now
    assert 'Jack' not in payload['played_innings']['1']['available']       # not in the 1st
    assert set(payload['played_innings']['1']['available']) == {
        'Aiden', 'Bennett', 'Carter', 'Drew', 'Eli', 'Finn', 'Gavin', 'Hudson', 'Isaac'}
