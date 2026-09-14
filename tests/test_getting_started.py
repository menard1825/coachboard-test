from werkzeug.security import generate_password_hash


def _build_app(monkeypatch, role='Head Coach'):
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
            team_name='Existing Test Team',
            registration_code='existing-test-code',
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
            role=role,
            player_order=[],
        ))
        db.session.commit()

    return app


def _login(client, role='Head Coach', team_id=1):
    with client.session_transaction() as flask_session:
        flask_session['logged_in'] = True
        flask_session['username'] = 'coach'
        flask_session['full_name'] = 'Test Coach'
        flask_session['team_id'] = team_id
        flask_session['role'] = role


def test_existing_team_is_grandfathered_without_setup_prompt(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.get('/api/getting-started')
    assert response.status_code == 200
    data = response.get_json()
    assert data['legacy'] is True
    assert data['active'] is False
    assert data['show_home'] is False

    page = client.get('/getting-started')
    assert page.status_code == 200
    assert b'Your Team Is Ready' in page.data
    assert b'Review or update your team setup at any time.' in page.data
    assert b'guided setup was added' not in page.data
    assert b'already in CoachBoard' not in page.data


def test_new_team_state_shows_full_checklist_and_can_be_dismissed(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from blueprints.getting_started import NEW_TEAM_SETUP, TeamSetupState

    with app.app_context():
        db.session.add(TeamSetupState(team_id=1, setup_type=NEW_TEAM_SETUP, completed_steps=[]))
        db.session.commit()

    data = client.get('/api/getting-started').get_json()
    assert data['active'] is True
    assert data['setup_type'] == 'new_team'
    assert data['title'] == 'Finish Team Setup'
    assert data['total'] == 6
    assert data['show_home'] is True
    assert {step['key'] for step in data['steps']} >= {
        'team_settings', 'pitching', 'playing_time', 'roster', 'coaches', 'first_activity'
    }

    marked = client.post('/getting-started/step/team_settings')
    assert marked.status_code == 302
    data = client.get('/api/getting-started').get_json()
    team_settings = next(step for step in data['steps'] if step['key'] == 'team_settings')
    assert team_settings['complete'] is True

    dismissed = client.post('/getting-started/dismiss')
    assert dismissed.status_code == 302
    data = client.get('/api/getting-started').get_json()
    assert data['dismissed'] is True
    assert data['show_home'] is False


def test_super_admin_create_team_initializes_new_team_setup(monkeypatch):
    app = _build_app(monkeypatch, role='Super Admin')
    client = app.test_client()
    _login(client, role='Super Admin')

    response = client.post('/admin/create_team', data={'team_name': 'Brand New Team'})
    assert response.status_code == 302

    from db import db
    from models import Team
    from blueprints.getting_started import NEW_TEAM_SETUP, TeamSetupState

    with app.app_context():
        team = db.session.query(Team).filter_by(team_name='Brand New Team').one()
        state = db.session.query(TeamSetupState).filter_by(team_id=team.id).one()
        assert state.setup_type == NEW_TEAM_SETUP
        assert state.completed_steps == []
        assert state.dismissed is False


def test_season_rollover_initializes_season_checklist(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.post('/admin/rollover_season', data={
        'new_team_name': 'Existing Test Team 13U',
        'new_age_group': '13U',
    })
    assert response.status_code == 302

    from db import db
    from models import Team
    from blueprints.getting_started import SEASON_SETUP, TeamSetupState

    with app.app_context():
        team = db.session.query(Team).filter_by(team_name='Existing Test Team 13U').one()
        state = db.session.query(TeamSetupState).filter_by(team_id=team.id).one()
        assert state.setup_type == SEASON_SETUP

    with client.session_transaction() as flask_session:
        new_team_id = flask_session['team_id']
    assert new_team_id == team.id

    data = client.get('/api/getting-started').get_json()
    assert data['setup_type'] == 'season_rollover'
    assert data['title'] == 'Season Setup'
    assert data['total'] == 6
    templates = next(step for step in data['steps'] if step['key'] == 'templates')
    assert templates['required'] is False


def test_assistant_coach_does_not_receive_setup_card(monkeypatch):
    app = _build_app(monkeypatch, role='Assistant Coach')
    client = app.test_client()
    _login(client, role='Assistant Coach')

    data = client.get('/api/getting-started').get_json()
    assert data == {
        'active': False,
        'can_manage': False,
        'show_home': False,
        'steps': [],
    }
