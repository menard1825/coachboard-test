from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Clock Test Team',
            registration_code='clock-test-code',
            age_group='12U',
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
        db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'


def test_live_clock_pause_resume_excludes_delay_time(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from blueprints import live_game_clock as clock_module
    from db import db
    from models import Game

    now = [datetime(2026, 8, 19, 16, 0, 0)]
    monkeypatch.setattr(clock_module, '_utcnow_naive', lambda: now[0])

    with app.app_context():
        db.session.add(Game(
            id=40,
            date=datetime(2026, 8, 19),
            opponent='Delay Test',
            team_id=1,
            is_live=True,
            live_current_inning='3',
        ))
        db.session.commit()

    restarted = client.post('/api/live-game/40/clock', json={
        'action': 'restart',
        'time_limit_minutes': 100,
    })
    assert restarted.status_code == 200
    assert restarted.get_json()['clock']['is_paused'] is False

    now[0] += timedelta(minutes=10)
    paused = client.post('/api/live-game/40/clock', json={'action': 'pause'})
    assert paused.status_code == 200
    paused_clock = paused.get_json()['clock']
    assert paused_clock['is_paused'] is True
    assert paused_clock['elapsed_seconds'] == 600
    assert paused_clock['remaining_seconds'] == 90 * 60

    now[0] += timedelta(minutes=10)
    still_paused = client.get('/api/live-game/40/clock').get_json()['clock']
    assert still_paused['is_paused'] is True
    assert still_paused['elapsed_seconds'] == 600
    assert still_paused['remaining_seconds'] == 90 * 60

    now[0] += timedelta(minutes=10)
    resumed = client.post('/api/live-game/40/clock', json={'action': 'resume'})
    assert resumed.status_code == 200
    resumed_clock = resumed.get_json()['clock']
    assert resumed_clock['is_paused'] is False
    assert resumed_clock['ended_at_utc'] is None
    assert resumed_clock['elapsed_seconds'] == 600

    now[0] += timedelta(minutes=5)
    running_again = client.get('/api/live-game/40/clock').get_json()['clock']
    assert running_again['elapsed_seconds'] == 900
    assert running_again['remaining_seconds'] == 85 * 60


def test_clock_pause_is_rejected_when_game_is_not_live(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game

    with app.app_context():
        db.session.add(Game(
            id=41,
            date=datetime(2026, 8, 19),
            opponent='Not Live',
            team_id=1,
            is_live=False,
        ))
        db.session.commit()

    response = client.post('/api/live-game/41/clock', json={'action': 'pause'})
    assert response.status_code == 409
    assert 'Live Game' in response.get_json()['message']
