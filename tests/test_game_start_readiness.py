from datetime import datetime

from werkzeug.security import generate_password_hash


def _build_app(monkeypatch, *, complete_defense=True, with_rules=True):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
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
        team = Team(
            id=1,
            team_name='Start Contract Team',
            registration_code='start-contract-code',
            age_group='11U',
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

        names = ['Aiden', 'Bennett', 'Carter', 'Drew', 'Eli', 'Finn', 'Gavin', 'Hudson', 'Isaac']
        players = [
            Player(id=index + 1, name=name, number=str(index + 1), team_id=team.id)
            for index, name in enumerate(names)
        ]
        db.session.add_all(players)

        if with_rules:
            db.session.add(TeamPitchingSettings(
                team_id=team.id,
                competition_default_rule='USSSA',
                arm_care_rule_set='MLB Pitch Smart',
            ))

        inning_one = {
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
        if not complete_defense:
            inning_one.pop('RF')

        game = Game(
            id=91,
            date=datetime(2026, 8, 31, 18, 0, 0),
            opponent='Start Contract Opponent',
            team_id=team.id,
            is_live=False,
            live_current_inning='1',
        )
        rotation = Rotation(
            id=1,
            title='Starting Defense',
            innings={'1': inning_one},
            associated_game_id=game.id,
            team_id=team.id,
        )
        db.session.add_all([game, rotation])
        db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'


def test_empty_batting_order_does_not_block_first_pitch(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    readiness_response = client.get('/api/game-day/91/readiness')
    assert readiness_response.status_code == 200
    readiness = readiness_response.get_json()

    assert readiness['readiness']['lineup_ready'] is False
    assert readiness['ready'] is True
    assert readiness['missing'] == []

    start_response = client.post('/api/live-game/91/start', json={})
    assert start_response.status_code == 200
    payload = start_response.get_json()
    assert payload['ready'] is True
    assert payload['missing'] == []
    assert payload['state']['game']['is_live'] is True


def test_missing_inning_one_defense_is_rejected_with_same_contract(monkeypatch):
    app = _build_app(monkeypatch, complete_defense=False)
    client = app.test_client()
    _login(client)

    readiness_response = client.get('/api/game-day/91/readiness')
    assert readiness_response.status_code == 200
    readiness = readiness_response.get_json()
    assert readiness['ready'] is False
    assert 'Finish the Inning 1 defense.' in readiness['missing']

    start_response = client.post('/api/live-game/91/start', json={})
    assert start_response.status_code == 409
    rejected = start_response.get_json()

    assert 'ready' in rejected, rejected
    assert 'missing' in rejected, rejected
    assert rejected['ready'] == readiness['ready']
    assert rejected['missing'] == readiness['missing']

    from db import db
    from models import Game

    with app.app_context():
        assert db.session.get(Game, 91).is_live is False


def test_missing_pitching_rules_blocks_first_pitch(monkeypatch):
    app = _build_app(monkeypatch, with_rules=False)
    client = app.test_client()
    _login(client)

    readiness = client.get('/api/game-day/91/readiness').get_json()
    assert readiness['ready'] is False
    assert 'Select the game pitching rules / tracking method.' in readiness['missing']

    rejected = client.post('/api/live-game/91/start', json={})
    assert rejected.status_code == 409
    payload = rejected.get_json()
    assert 'ready' in payload, payload
    assert 'missing' in payload, payload
    assert payload['missing'] == readiness['missing']
