"""Regression coverage for the canonical game-deletion implementation.

Background: two independent game-delete routes used to exist.
blueprints/gameday.py's legacy `GET /delete_game/<id>` only cleaned up
Lineup/Rotation, while blueprints/game_day.py's `POST /game-day/<id>/delete`
also cleaned PlayerPitchTarget/GamePitchingRule/GameNextInningPrep. Because
those three tables (plus several others) are real foreign keys with no
database-level cascade, calling the legacy route against a game that had
ever gone live or had a pitching target set raised an unhandled
sqlite3.IntegrityError. Worse: a freshly-started live game has no
GameNextInningPrep row yet (it is seeded lazily, the first time the NEXT
board is opened), so during that window the legacy route had no FK to trip
over and no is_live check either -- it silently deleted the live game
outright.

The fix consolidates all deletion into one canonical helper
(game_day.delete_game_and_related), used only by the canonical POST route.
The legacy GET route no longer touches the database at all.
"""

from datetime import datetime

from werkzeug.security import generate_password_hash


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Player, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()

        home_team = Team(
            id=1, team_name='Home Team', registration_code='home-code',
            age_group='12U', pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3, timezone='America/Indiana/Indianapolis',
        )
        other_team = Team(
            id=2, team_name='Other Team', registration_code='other-code',
            age_group='12U', pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3, timezone='America/Indiana/Indianapolis',
        )
        head_coach = User(
            id=1, username='coach', full_name='Head Coach',
            password_hash=generate_password_hash('password123'),
        )
        assistant = User(
            id=2, username='assistant', full_name='Assistant Coach',
            password_hash=generate_password_hash('password123'),
        )
        scorekeeper = User(
            id=3, username='scorekeeper', full_name='Game Changer',
            password_hash=generate_password_hash('password123'),
        )
        db.session.add_all([home_team, other_team, head_coach, assistant, scorekeeper])
        db.session.flush()
        db.session.add_all([
            TeamMembership(user_id=head_coach.id, team_id=home_team.id, role='Head Coach', player_order=[]),
            TeamMembership(user_id=assistant.id, team_id=home_team.id, role='Assistant Coach', player_order=[]),
            TeamMembership(user_id=scorekeeper.id, team_id=home_team.id, role='Game Changer', player_order=[]),
        ])
        db.session.add(Player(id=1, name='Pitcher Pat', number='1', team_id=home_team.id))
        db.session.commit()

    return app


def _login(client, username, team_id=1):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = username
        session['team_id'] = team_id


def _seed_fully_populated_game(team_id=1, game_id=100, is_live=False):
    """Seed a game plus one row in every table that references a game.

    Returns the Game object. Caller must be inside an app_context.
    """
    from db import db
    from models import (
        Game, GamePitchingPlan, GameRotationEvent, Lineup,
        PitchingOuting, PlayerGameAbsence, PlayerPitchTarget, Rotation,
    )
    from blueprints.live_game_ui import GameNextInningPrep
    from blueprints.live_game_clock import GameClockState
    from game_pitching_rules import GamePitchingRule

    game = Game(
        id=game_id,
        date=datetime(2026, 8, 30, 17, 0, 0),
        opponent='Deletion Probe Opponent',
        team_id=team_id,
        is_live=is_live,
        live_current_inning='1',
    )
    db.session.add(game)
    db.session.commit()

    db.session.add_all([
        Lineup(
            title='Probe Lineup', lineup_positions=[],
            associated_game_id=game_id, team_id=team_id,
        ),
        Rotation(
            title='Probe Rotation', innings={'1': {'P': 'Pitcher Pat'}},
            associated_game_id=game_id, team_id=team_id,
        ),
        PlayerPitchTarget(
            player_id=1, game_id=game_id, team_id=team_id,
            target_pitches=50, local_date='2026-08-30',
        ),
        GamePitchingRule(rule_set='USSSA', game_id=game_id, team_id=team_id),
        GameNextInningPrep(
            inning='2', alignment={'P': 'Pitcher Pat'}, source='custom',
            updated_by='coach', game_id=game_id, team_id=team_id,
        ),
        PlayerGameAbsence(player_id=1, game_id=game_id, team_id=team_id),
        PitchingOuting(
            date=datetime(2026, 8, 30), opponent='Deletion Probe Opponent',
            pitches=40, innings=2.0, team_id=team_id, player_id=1, game_id=game_id,
        ),
        GameRotationEvent(
            team_id=team_id, game_id=game_id, inning='1', sequence=1,
            event_type='Defensive Change', before_alignment={},
            after_alignment={'P': 'Pitcher Pat'},
        ),
        GamePitchingPlan(
            role='Starter', expected_innings='3',
            player_id=1, game_id=game_id, team_id=team_id,
        ),
        GameClockState(game_id=game_id, team_id=team_id),
    ])
    db.session.commit()
    return game


GAME_LINKED_TABLE_QUERIES = (
    ('Lineup', lambda db, models, game_id, team_id: db.session.query(
        models['Lineup']
    ).filter_by(associated_game_id=game_id, team_id=team_id).count()),
    ('Rotation', lambda db, models, game_id, team_id: db.session.query(
        models['Rotation']
    ).filter_by(associated_game_id=game_id, team_id=team_id).count()),
    ('PlayerPitchTarget', lambda db, models, game_id, team_id: db.session.query(
        models['PlayerPitchTarget']
    ).filter_by(game_id=game_id, team_id=team_id).count()),
    ('GamePitchingRule', lambda db, models, game_id, team_id: db.session.query(
        models['GamePitchingRule']
    ).filter_by(game_id=game_id, team_id=team_id).count()),
    ('GameNextInningPrep', lambda db, models, game_id, team_id: db.session.query(
        models['GameNextInningPrep']
    ).filter_by(game_id=game_id, team_id=team_id).count()),
    ('PlayerGameAbsence', lambda db, models, game_id, team_id: db.session.query(
        models['PlayerGameAbsence']
    ).filter_by(game_id=game_id, team_id=team_id).count()),
    ('PitchingOuting', lambda db, models, game_id, team_id: db.session.query(
        models['PitchingOuting']
    ).filter_by(game_id=game_id, team_id=team_id).count()),
    ('GameRotationEvent', lambda db, models, game_id, team_id: db.session.query(
        models['GameRotationEvent']
    ).filter_by(game_id=game_id, team_id=team_id).count()),
    ('GamePitchingPlan', lambda db, models, game_id, team_id: db.session.query(
        models['GamePitchingPlan']
    ).filter_by(game_id=game_id, team_id=team_id).count()),
    ('GameClockState', lambda db, models, game_id, team_id: db.session.query(
        models['GameClockState']
    ).filter_by(game_id=game_id, team_id=team_id).count()),
)


def _related_row_counts(game_id, team_id=1):
    """Return {table_name: row_count} for every game-linked table."""
    from db import db
    from models import (
        GamePitchingPlan, GameRotationEvent, Lineup,
        PitchingOuting, PlayerGameAbsence, PlayerPitchTarget, Rotation,
    )
    from blueprints.live_game_ui import GameNextInningPrep
    from blueprints.live_game_clock import GameClockState
    from game_pitching_rules import GamePitchingRule

    models = {
        'Lineup': Lineup, 'Rotation': Rotation, 'PlayerPitchTarget': PlayerPitchTarget,
        'GamePitchingRule': GamePitchingRule, 'GameNextInningPrep': GameNextInningPrep,
        'PlayerGameAbsence': PlayerGameAbsence, 'PitchingOuting': PitchingOuting,
        'GameRotationEvent': GameRotationEvent, 'GamePitchingPlan': GamePitchingPlan,
        'GameClockState': GameClockState,
    }
    return {
        name: query(db, models, game_id, team_id)
        for name, query in GAME_LINKED_TABLE_QUERIES
    }


def test_canonical_post_deletes_every_game_linked_record(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client, 'coach')

    with app.app_context():
        _seed_fully_populated_game(team_id=1, game_id=100, is_live=False)
        before = _related_row_counts(100)
        assert all(count == 1 for count in before.values()), before

    response = client.post('/game-day/100/delete')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

    with app.app_context():
        from db import db
        from models import Game
        assert db.session.get(Game, 100) is None
        after = _related_row_counts(100)
        for table_name, count in after.items():
            assert count == 0, f'{table_name} row survived canonical delete'


def test_legacy_get_deletes_nothing_even_for_a_populated_game(monkeypatch):
    """The exact scenario that used to raise sqlite3.IntegrityError."""
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client, 'coach')

    with app.app_context():
        _seed_fully_populated_game(team_id=1, game_id=101, is_live=False)
        before = _related_row_counts(101)

    response = client.get('/delete_game/101')
    assert response.status_code == 302

    with app.app_context():
        from db import db
        from models import Game
        assert db.session.get(Game, 101) is not None
        after = _related_row_counts(101)
        assert after == before, 'legacy GET route mutated a related record'


def test_legacy_get_does_not_delete_a_freshly_started_live_game(monkeypatch):
    """Regression for the confirmed live-game data-loss bug.

    A freshly started live game has no GameNextInningPrep row yet (it is
    seeded lazily on first NEXT-board access), so the legacy route's old
    behavior had neither a foreign-key error nor an is_live check to stop
    it from silently deleting an in-progress game.
    """
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client, 'coach')

    from db import db
    from models import Game

    with app.app_context():
        game = Game(
            id=102, date=datetime(2026, 8, 30, 17, 0, 0),
            opponent='Live Probe Opponent', team_id=1,
            is_live=True, live_current_inning='1',
        )
        db.session.add(game)
        db.session.commit()

    response = client.get('/delete_game/102')
    assert response.status_code == 302

    with app.app_context():
        assert db.session.get(Game, 102) is not None


def test_canonical_post_rejects_live_game_before_any_mutation(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client, 'coach')

    with app.app_context():
        _seed_fully_populated_game(team_id=1, game_id=103, is_live=True)
        before = _related_row_counts(103)

    response = client.post('/game-day/103/delete')
    assert response.status_code == 409
    assert response.get_json()['status'] == 'error'

    with app.app_context():
        from db import db
        from models import Game
        assert db.session.get(Game, 103) is not None
        after = _related_row_counts(103)
        assert after == before, 'rejected live-game delete mutated a related record'


def test_canonical_post_cross_team_delete_is_refused(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client, 'coach', team_id=1)

    with app.app_context():
        _seed_fully_populated_game(team_id=2, game_id=104, is_live=False)
        before = _related_row_counts(104, team_id=2)

    response = client.post('/game-day/104/delete')
    assert response.status_code == 404
    assert response.get_json()['message'] == 'Game not found.'

    with app.app_context():
        from db import db
        from models import Game
        assert db.session.get(Game, 104) is not None
        after = _related_row_counts(104, team_id=2)
        assert after == before, 'cross-team delete mutated another team\'s data'


def test_legacy_get_cross_team_game_is_safe(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client, 'coach', team_id=1)

    with app.app_context():
        _seed_fully_populated_game(team_id=2, game_id=105, is_live=False)
        before = _related_row_counts(105, team_id=2)

    response = client.get('/delete_game/105')
    # The legacy route now redirects unconditionally without ever querying the
    # database, so a cross-team id gets the same safe response as any other
    # id -- no mutation, and no information about who owns game 105.
    assert response.status_code == 302
    assert 'Other Team' not in response.get_data(as_text=True)
    assert 'Deletion Probe Opponent' not in response.get_data(as_text=True)

    with app.app_context():
        from db import db
        from models import Game
        assert db.session.get(Game, 105) is not None
        after = _related_row_counts(105, team_id=2)
        assert after == before


def test_assistant_coach_cannot_delete_via_either_route(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client, 'assistant')

    with app.app_context():
        _seed_fully_populated_game(team_id=1, game_id=106, is_live=False)

    post_response = client.post('/game-day/106/delete')
    assert post_response.status_code == 403

    get_response = client.get('/delete_game/106')
    assert get_response.status_code == 302

    with app.app_context():
        from db import db
        from models import Game
        assert db.session.get(Game, 106) is not None


def test_game_changer_cannot_delete_via_either_route(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client, 'scorekeeper')

    with app.app_context():
        _seed_fully_populated_game(team_id=1, game_id=107, is_live=False)

    post_response = client.post('/game-day/107/delete')
    assert post_response.status_code == 403

    get_response = client.get('/delete_game/107')
    assert get_response.status_code == 302

    with app.app_context():
        from db import db
        from models import Game
        assert db.session.get(Game, 107) is not None


def test_deleting_one_game_leaves_other_games_and_teams_untouched(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client, 'coach')

    with app.app_context():
        _seed_fully_populated_game(team_id=1, game_id=108, is_live=False)
        _seed_fully_populated_game(team_id=1, game_id=109, is_live=False)
        untouched_before = _related_row_counts(109)

    response = client.post('/game-day/108/delete')
    assert response.status_code == 200

    with app.app_context():
        from db import db
        from models import Game
        assert db.session.get(Game, 108) is None
        assert db.session.get(Game, 109) is not None
        untouched_after = _related_row_counts(109)
        assert untouched_after == untouched_before
