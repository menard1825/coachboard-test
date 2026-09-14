from werkzeug.security import generate_password_hash


def _build_app(monkeypatch, membership_role='Head Coach'):
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
            team_name='Fair Play Test Team',
            registration_code='fair-play-test-code',
            age_group='10U',
            pitching_rule_set='MLB Pitch Smart',
            outfielder_count=4,
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
            role=membership_role,
            player_order=[],
        ))
        db.session.commit()

    return app


def _login(client, role='Head Coach'):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = 1
        session['role'] = role


def test_fair_play_defaults_off_and_persists_team_rules(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    default_response = client.get('/api/fair-play/settings')
    assert default_response.status_code == 200
    default_data = default_response.get_json()
    assert default_data['settings']['mode'] == 'off'
    assert default_data['settings']['infield_positions'] == ['1B', '2B', '3B', 'SS']

    saved = client.post('/api/fair-play/settings', json={
        'mode': 'rules',
        'min_infield_innings': 1,
        'max_consecutive_bench': 1,
        'infield_positions': ['1B', '2B', '3B', 'SS'],
    })
    assert saved.status_code == 200
    assert saved.get_json()['settings']['mode'] == 'rules'

    reloaded = client.get('/api/fair-play/settings')
    assert reloaded.status_code == 200
    assert reloaded.get_json()['settings'] == {
        'mode': 'rules',
        'min_infield_innings': 1,
        'max_consecutive_bench': 1,
        'infield_positions': ['1B', '2B', '3B', 'SS'],
    }


def test_assistant_coach_cannot_change_team_fair_play_settings(monkeypatch):
    app = _build_app(monkeypatch, membership_role='Assistant Coach')
    client = app.test_client()
    _login(client, role='Assistant Coach')

    response = client.post('/api/fair-play/settings', json={
        'mode': 'rules',
        'min_infield_innings': 1,
        'max_consecutive_bench': 1,
        'infield_positions': ['SS'],
    })
    assert response.status_code == 403

    settings = client.get('/api/fair-play/settings')
    assert settings.status_code == 200
    assert settings.get_json()['can_edit'] is False
    assert settings.get_json()['settings']['mode'] == 'off'


def test_fair_play_rejects_invalid_position(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.post('/api/fair-play/settings', json={
        'mode': 'rules',
        'min_infield_innings': 1,
        'max_consecutive_bench': 1,
        'infield_positions': ['1B', 'LF'],
    })
    assert response.status_code == 400
    assert 'Unsupported position' in response.get_json()['message']
