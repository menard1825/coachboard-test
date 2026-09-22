"""Optional preloads on can_start_game() and build_game_readiness().

/api/game-day/<id>/readiness needs both calculations for one request, and each
used to load the roster, this game's absences and its rotation for itself. The
endpoint now loads those three once and passes the same objects to both.

Two properties have to hold for that to be safe, and both are tested here:

1. Omitting a preload must behave exactly as before -- a real query. This is
   what /api/live-game/<id>/start depends on: it calls can_start_game(game,
   team) with no preloads and must keep querying for itself.
2. Supplying a preload must suppress that query, including when the supplied
   value is None. A game with no rotation row legitimately loads as None, which
   is why the sentinel is a private object() and not None.
"""

import re
from collections import Counter
from datetime import datetime

import pytest
from sqlalchemy import event
from werkzeug.security import generate_password_hash


ALIGNMENT = {
    'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
    '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
    'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
}
NAMES = list(ALIGNMENT.values())

WITH_ROTATION = 201
NO_ROTATION = 202
EMPTY_ROTATION = 203


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'readiness-shared-inputs-test')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from models import Game, Player, Rotation, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(
                id=1,
                team_name='Shared Inputs Team',
                registration_code='shared-inputs-code',
                age_group='11U',
                pitching_rule_set='MLB Pitch Smart',
                outfielder_count=3,
                timezone='America/Indiana/Indianapolis',
            ),
            User(
                id=1,
                username='shared-coach',
                full_name='Shared Coach',
                password_hash=generate_password_hash('password123'),
            ),
        ])
        db.session.flush()
        db.session.add(TeamMembership(
            user_id=1, team_id=1, role='Head Coach', player_order=[]))
        db.session.add_all([
            Player(id=index + 1, name=name, number=str(index + 1), team_id=1)
            for index, name in enumerate(NAMES)
        ])
        db.session.add(TeamPitchingSettings(
            team_id=1,
            competition_default_rule='USSSA',
            arm_care_rule_set='MLB Pitch Smart',
        ))

        for game_id in (WITH_ROTATION, NO_ROTATION, EMPTY_ROTATION):
            db.session.add(Game(
                id=game_id,
                date=datetime(2026, 8, 31, 18, 0, 0),
                start_time='18:00',
                opponent=f'Opponent {game_id}',
                team_id=1,
            ))
        db.session.add(Rotation(
            title='Full Rotation',
            innings={str(number): dict(ALIGNMENT) for number in range(1, 7)},
            associated_game_id=WITH_ROTATION,
            team_id=1,
        ))
        db.session.add(Rotation(
            title='Empty Rotation',
            innings={},
            associated_game_id=EMPTY_ROTATION,
            team_id=1,
        ))
        db.session.commit()

    return app


def _table_of(statement):
    match = re.search(r'\bFROM\s+([a-zA-Z0-9_]+)', statement, re.IGNORECASE)
    return match.group(1) if match else '<other>'


def _count_tables(call):
    """Run `call` and return a Counter of the tables it read."""
    from db import db

    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith('PRAGMA '):
            return
        statements.append(statement)

    engine = db.session.get_bind()
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        result = call()
    finally:
        event.remove(engine, 'before_cursor_execute', capture)

    return result, Counter(_table_of(statement) for statement in statements), statements


def _fixtures(game_id=WITH_ROTATION):
    from db import db
    from models import Game, Player, PlayerGameAbsence, Rotation, Team

    team = db.session.get(Team, 1)
    game = db.session.get(Game, game_id)
    roster = db.session.query(Player).filter_by(team_id=1).order_by(Player.name).all()
    absences = db.session.query(PlayerGameAbsence).filter_by(
        game_id=game_id, team_id=1).all()
    rotation = db.session.query(Rotation).filter_by(
        associated_game_id=game_id, team_id=1).first()
    # Touch the lazy attributes so the measured call cannot be charged for them.
    team.team_name, game.opponent
    return team, game, roster, absences, rotation


# --- can_start_game -------------------------------------------------------

def test_supplied_roster_prevents_the_player_query(monkeypatch):
    app = _build_app(monkeypatch)
    from game_start_readiness import can_start_game

    with app.app_context():
        team, game, roster, _, _ = _fixtures()
        _, counts, statements = _count_tables(
            lambda: can_start_game(game, team, roster=roster))

    assert counts['players'] == 0, statements


def test_supplied_absences_prevent_the_absence_query(monkeypatch):
    app = _build_app(monkeypatch)
    from game_start_readiness import can_start_game

    with app.app_context():
        team, game, _, absences, _ = _fixtures()
        _, counts, statements = _count_tables(
            lambda: can_start_game(game, team, absences=absences))

    assert counts['player_game_absences'] == 0, statements


def test_supplied_rotation_prevents_the_rotation_query(monkeypatch):
    app = _build_app(monkeypatch)
    from game_start_readiness import can_start_game

    with app.app_context():
        team, game, _, _, rotation = _fixtures()
        assert rotation is not None
        _, counts, statements = _count_tables(
            lambda: can_start_game(game, team, rotation=rotation))

    assert counts['rotations'] == 0, statements


def test_a_preloaded_rotation_of_none_still_prevents_the_query(monkeypatch):
    """None is a real value here, not "not supplied".

    A game with no rotation row loads as None. If the sentinel were None, this
    call would silently fall back to a query -- and worse, a caller that had
    already established there is no rotation would pay for it on every request.
    """
    app = _build_app(monkeypatch)
    from game_start_readiness import can_start_game

    with app.app_context():
        team, game, _, _, rotation = _fixtures(NO_ROTATION)
        assert rotation is None
        result, counts, statements = _count_tables(
            lambda: can_start_game(game, team, rotation=None))

    assert counts['rotations'] == 0, statements
    assert result['ready'] is False
    assert 'Finish the Inning 1 defense.' in result['missing']


def test_a_preloaded_rotation_with_empty_innings_is_handled(monkeypatch):
    app = _build_app(monkeypatch)
    from game_start_readiness import can_start_game

    with app.app_context():
        team, game, _, _, rotation = _fixtures(EMPTY_ROTATION)
        assert rotation is not None and rotation.innings == {}
        result, counts, statements = _count_tables(
            lambda: can_start_game(game, team, rotation=rotation))

    assert counts['rotations'] == 0, statements
    assert result['ready'] is False
    assert 'Finish the Inning 1 defense.' in result['missing']


@pytest.mark.parametrize('omitted', ['roster', 'absences', 'rotation'])
def test_omitting_a_preload_still_performs_its_legacy_query(monkeypatch, omitted):
    """What /api/live-game/<id>/start relies on."""
    app = _build_app(monkeypatch)
    from game_start_readiness import can_start_game

    table = {
        'roster': 'players',
        'absences': 'player_game_absences',
        'rotation': 'rotations',
    }[omitted]

    with app.app_context():
        team, game, roster, absences, rotation = _fixtures()
        supplied = {'roster': roster, 'absences': absences, 'rotation': rotation}
        supplied.pop(omitted)
        _, counts, statements = _count_tables(
            lambda: can_start_game(game, team, **supplied))

    assert counts[table] == 1, (
        f'omitting {omitted} must still query {table}\n' + '\n'.join(statements))


def test_no_preloads_at_all_queries_all_three(monkeypatch):
    app = _build_app(monkeypatch)
    from game_start_readiness import can_start_game

    with app.app_context():
        team, game, _, _, _ = _fixtures()
        _, counts, statements = _count_tables(lambda: can_start_game(game, team))

    assert counts['players'] == 1, statements
    assert counts['player_game_absences'] == 1, statements
    assert counts['rotations'] == 1, statements


@pytest.mark.parametrize('game_id', [WITH_ROTATION, NO_ROTATION, EMPTY_ROTATION],
                         ids=['with_rotation', 'no_rotation', 'empty_rotation'])
def test_preloaded_and_queried_inputs_agree(monkeypatch, game_id):
    app = _build_app(monkeypatch)
    from game_start_readiness import can_start_game

    with app.app_context():
        team, game, roster, absences, rotation = _fixtures(game_id)
        preloaded = can_start_game(
            game, team, roster=roster, absences=absences, rotation=rotation)
        queried = can_start_game(game, team)

    assert preloaded == queried


def test_ordered_and_unordered_rosters_give_the_same_answer(monkeypatch):
    """The endpoint hands can_start_game() a name-ordered roster.

    can_start_game() previously loaded the roster unordered. It uses the list
    for membership and set comparisons only, so ordering cannot reach its
    result -- proven here rather than argued, over a reversed list as well as
    the two natural orders.
    """
    app = _build_app(monkeypatch)
    from db import db
    from game_start_readiness import can_start_game
    from models import Player

    with app.app_context():
        team, game, ordered, absences, rotation = _fixtures()
        unordered = db.session.query(Player).filter_by(team_id=1).all()
        reversed_roster = list(ordered)[::-1]

        assert [p.name for p in ordered] == sorted(p.name for p in ordered)
        assert [p.name for p in ordered] != [p.name for p in reversed_roster]

        answers = [
            can_start_game(game, team, roster=candidate,
                           absences=absences, rotation=rotation)
            for candidate in (ordered, unordered, reversed_roster)
        ]

    assert answers[0] == answers[1] == answers[2]


# --- build_game_readiness -------------------------------------------------

def test_build_game_readiness_honours_the_same_preloads(monkeypatch):
    app = _build_app(monkeypatch)
    from blueprints.game_day import _readiness_for_game

    with app.app_context():
        team, game, roster, absences, rotation = _fixtures()
        _, counts, statements = _count_tables(
            lambda: _readiness_for_game(
                game, team, roster=roster, absences=absences, rotation=rotation))

    assert counts['players'] == 0, statements
    assert counts['player_game_absences'] == 0, statements
    # Zero, not one: the actual-game reconstruction now reuses this preloaded
    # rotation instead of calling actual_game_rotation(), which used to load it
    # a second time.
    assert counts['rotations'] == 0, statements
    assert counts['game_rotation_events'] == 1, statements


def test_build_game_readiness_without_preloads_queries_as_before(monkeypatch):
    app = _build_app(monkeypatch)
    from blueprints.game_day import _readiness_for_game

    with app.app_context():
        team, game, _, _, _ = _fixtures()
        _, counts, statements = _count_tables(
            lambda: _readiness_for_game(game, team))

    assert counts['players'] == 1, statements
    assert counts['player_game_absences'] == 1, statements
    # One, not two: without preloads build_game_readiness() loads the rotation
    # for itself, and the reconstruction reuses that one load.
    assert counts['rotations'] == 1, statements
    assert counts['game_rotation_events'] == 1, statements


@pytest.mark.parametrize('game_id', [WITH_ROTATION, NO_ROTATION, EMPTY_ROTATION],
                         ids=['with_rotation', 'no_rotation', 'empty_rotation'])
def test_build_game_readiness_preloaded_matches_queried(monkeypatch, game_id):
    app = _build_app(monkeypatch)
    from blueprints.game_day import _readiness_for_game

    with app.app_context():
        team, game, roster, absences, rotation = _fixtures(game_id)
        preloaded = _readiness_for_game(
            game, team, roster=roster, absences=absences, rotation=rotation)
        queried = _readiness_for_game(game, team)

    assert preloaded == queried


# --- /api/live-game/<id>/start --------------------------------------------

def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['user_id'] = 1
        session['team_id'] = 1
        session['username'] = 'shared-coach'
        session['role'] = 'Head Coach'


def test_start_calls_can_start_game_with_no_preloads(monkeypatch):
    """/start must keep asking the database itself.

    The preloads exist for one endpoint. If /start ever started receiving them
    it would be trusting rows another caller loaded, which is exactly the kind
    of coupling this slice is meant not to introduce.
    """
    import blueprints.live_game_api as live_game_api

    app = _build_app(monkeypatch)
    seen = []

    original = live_game_api.can_start_game

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(live_game_api, 'can_start_game', spy)

    client = app.test_client()
    _login(client)
    response = client.post(f'/api/live-game/{WITH_ROTATION}/start', json={})

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload['ready'] is True
    assert payload['missing'] == []
    assert payload['state']['game']['is_live'] is True

    assert seen == [{}], f'/start passed preloads: {seen}'


def test_start_still_queries_its_own_readiness_inputs(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    with app.app_context():
        from db import db
        db.session.expire_all()

    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith('PRAGMA '):
            return
        statements.append(statement)

    from db import db
    with app.app_context():
        engine = db.session.get_bind()
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        response = client.post(f'/api/live-game/{WITH_ROTATION}/start', json={})
    finally:
        event.remove(engine, 'before_cursor_execute', capture)

    assert response.status_code == 200
    counts = Counter(_table_of(statement) for statement in statements)
    assert counts['players'] >= 1, statements
    assert counts['player_game_absences'] >= 1, statements
    assert counts['rotations'] >= 1, statements
