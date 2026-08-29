from werkzeug.security import generate_password_hash


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('COACHBOARD_USAGE_OWNER_USERNAME', 'mike1825')

    from app import create_app
    from db import db
    from models import Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Usage Test Team',
            registration_code='usage-test',
            timezone='America/Indiana/Indianapolis',
        )
        owner = User(
            id=1,
            username='mike1825',
            full_name='Usage Owner',
            email='owner@example.com',
            password_hash=generate_password_hash('password123'),
        )
        coach = User(
            id=2,
            username='assistant',
            full_name='Assistant Coach',
            email='assistant@example.com',
            password_hash=generate_password_hash('password123'),
        )
        db.session.add_all([team, owner, coach])
        db.session.flush()
        db.session.add_all([
            TeamMembership(user_id=1, team_id=1, role='Head Coach', player_order=[]),
            TeamMembership(user_id=2, team_id=1, role='Assistant Coach', player_order=[]),
        ])
        db.session.commit()

    return app


def _set_session(client, username, full_name, role):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = username
        session['full_name'] = full_name
        session['team_id'] = 1
        session['role'] = role
        session['player_order'] = []
        session['client_timezone'] = 'America/Indiana/Indianapolis'
        session['client_utc_offset_minutes'] = -240


def test_coach_usage_dashboard_is_owner_only(monkeypatch):
    app = _build_app(monkeypatch)

    non_owner = app.test_client()
    _set_session(non_owner, 'assistant', 'Assistant Coach', 'Assistant Coach')
    assert non_owner.get('/admin/coach-usage').status_code == 403

    owner = app.test_client()
    _set_session(owner, 'mike1825', 'Usage Owner', 'Head Coach')
    response = owner.get('/admin/coach-usage')
    assert response.status_code == 200
    assert 'Coach Usage' in response.get_data(as_text=True)
    assert 'Owner-only testing view' in response.get_data(as_text=True)


def test_presence_heartbeat_tracks_session_and_meaningful_area_changes(monkeypatch):
    app = _build_app(monkeypatch)
    coach = app.test_client()
    _set_session(coach, 'assistant', 'Assistant Coach', 'Assistant Coach')

    headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'}
    first = coach.post('/api/coach-usage/heartbeat', json={
        'browser_session_id': 'browser-session-1',
        'area': 'Game Day',
        'path': '/game-day',
        'timezone': 'America/Indiana/Indianapolis',
        'utc_offset_minutes': -240,
    }, headers=headers)
    assert first.status_code == 200

    second = coach.post('/api/coach-usage/heartbeat', json={
        'browser_session_id': 'browser-session-1',
        'area': 'Pitching',
        'path': '/pitching',
        'timezone': 'America/Indiana/Indianapolis',
        'utc_offset_minutes': -240,
    }, headers=headers)
    assert second.status_code == 200

    from blueprints.coach_usage import CoachPresence
    from blueprints.security_guard import ActivityLog
    from db import db

    with app.app_context():
        presence = db.session.query(CoachPresence).filter_by(user_id=2, team_id=1).one()
        assert presence.current_area == 'Pitching'
        assert presence.current_path == '/pitching'
        assert presence.client_timezone == 'America/Indiana/Indianapolis'
        assert 'iPhone' in (presence.user_agent or '')

        actions = [row.action for row in db.session.query(ActivityLog).filter_by(user_id=2, team_id=1).order_by(ActivityLog.id).all()]
        assert actions == ['session_start', 'page_view']

    owner = app.test_client()
    _set_session(owner, 'mike1825', 'Usage Owner', 'Head Coach')
    dashboard = owner.get('/admin/coach-usage')
    assert dashboard.status_code == 200
    html = dashboard.get_data(as_text=True)
    assert 'Assistant Coach' in html
    assert 'Pitching' in html
    assert 'Active now' in html
    assert 'iPhone · Safari' in html
    assert 'Opened Pitching.' in html
