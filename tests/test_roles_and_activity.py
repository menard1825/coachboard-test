from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash


def _build_app(monkeypatch, role='Head Coach'):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Game, Lineup, Player, Rotation, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Role Test Team',
            registration_code='role-test',
            age_group='12U',
            pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3,
            timezone='America/Indiana/Indianapolis',
        )
        user = User(
            id=1,
            username='coach',
            full_name='Role Test Coach',
            email='coach@example.com',
            password_hash=generate_password_hash('password123'),
        )
        db.session.add_all([team, user])
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=1, role=role, player_order=[]))
        db.session.add_all([
            Player(id=1, name='Alpha', number='7', team_id=1),
            Player(id=2, name='Bravo', number='12', team_id=1),
            Player(id=3, name='Charlie', number='21', team_id=1),
        ])
        game = Game(
            id=10,
            date=datetime.now() + timedelta(days=1),
            opponent='Pregame Opponent',
            location='Test Field',
            team_id=1,
        )
        db.session.add(game)
        db.session.add(Lineup(
            id=10,
            title='Pregame Lineup',
            lineup_positions=['Alpha', 'Bravo', 'Charlie'],
            associated_game_id=10,
            team_id=1,
        ))
        db.session.add(Rotation(
            id=10,
            title='Pregame Defense',
            associated_game_id=10,
            team_id=1,
            innings={
                '1': {'P': 'Alpha', 'C': 'Bravo', '1B': 'Charlie'},
                '2': {'P': 'Bravo', 'C': 'Charlie', '1B': 'Alpha'},
            },
        ))
        db.session.commit()

    return app


def _login_session(client, role):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['full_name'] = 'Role Test Coach'
        session['team_id'] = 1
        session['role'] = role
        session['player_order'] = []


def test_game_changer_gets_read_only_pregame_sheet(monkeypatch):
    app = _build_app(monkeypatch, role='Game Changer')
    client = app.test_client()
    _login_session(client, 'Game Changer')

    home = client.get('/', follow_redirects=False)
    assert home.status_code == 302
    assert home.headers['Location'].endswith('/game-day')

    response = client.get('/game/10')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'GameChanger Pregame Setup' in html
    assert 'Batting Order' in html
    assert 'Defensive Rotation' in html
    assert 'Alpha' in html
    assert 'Bravo' in html
    assert 'Read-only' in html
    assert 'Start Live Game' not in html


def test_game_changer_cannot_mutate_game_or_live_state(monkeypatch):
    app = _build_app(monkeypatch, role='Game Changer')
    client = app.test_client()
    _login_session(client, 'Game Changer')

    start = client.post('/api/live-game/10/start', json={})
    assert start.status_code == 403
    assert 'read-only' in start.get_json()['message'].lower()

    lineup = client.post('/add_lineup', json={
        'title': 'Should Not Save',
        'lineup_player_ids': [1, 2, 3],
        'associated_game_id': 10,
    })
    assert lineup.status_code == 403

    from db import db
    from models import Game
    with app.app_context():
        game = db.session.get(Game, 10)
        assert game.is_live is False


def test_assistant_coach_cannot_permanently_delete_game(monkeypatch):
    app = _build_app(monkeypatch, role='Assistant Coach')
    client = app.test_client()
    _login_session(client, 'Assistant Coach')

    response = client.post('/game-day/10/delete', json={})
    assert response.status_code == 403
    assert 'Head Coach' in response.get_json()['message']

    from db import db
    from models import Game
    with app.app_context():
        assert db.session.get(Game, 10) is not None


def test_successful_login_records_utc_activity(monkeypatch):
    app = _build_app(monkeypatch, role='Head Coach')
    client = app.test_client()

    response = client.post('/login', data={
        'identity': 'coach',
        'password': 'password123',
    }, follow_redirects=False)
    assert response.status_code == 302

    from blueprints.security_guard import ActivityLog
    from db import db
    from models import User
    with app.app_context():
        user = db.session.get(User, 1)
        assert user.last_login is not None
        row = db.session.query(ActivityLog).filter_by(user_id=1, team_id=1, action='login').first()
        assert row is not None
        assert row.role_snapshot == 'Head Coach'
        assert row.username_snapshot == 'coach'
        assert row.created_at is not None

    activity = client.get('/admin/activity')
    assert activity.status_code == 200
    html = activity.get_data(as_text=True)
    assert 'Coach Activity' in html
    assert 'Role Test Coach' in html
    assert 'Signed in to Role Test Team' in html
