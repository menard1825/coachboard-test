from datetime import datetime

from werkzeug.security import generate_password_hash


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Game, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Pitching Preset Test Team',
            registration_code='pitching-preset-test',
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
        db.session.add(Game(
            id=1,
            date=datetime(2026, 8, 22),
            start_time='10:00',
            opponent='Preset Opponent',
            team_id=team.id,
        ))
        db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['full_name'] = 'Test Coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'


def test_team_and_game_rule_lists_include_common_presets(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.get('/api/game-day/pitching-rule-options')
    assert response.status_code == 200
    options = response.get_json()['options']
    assert 'MLB Pitch Smart' in options
    assert 'USSSA' in options
    assert 'Bullpen Tournaments' in options
    assert 'Little League Baseball' in options

    settings = client.get('/admin/settings')
    assert settings.status_code == 200
    html = settings.get_data(as_text=True)
    assert 'Bullpen Tournaments' in html
    assert 'Little League Baseball' in html


def test_bullpen_and_little_league_12u_use_pitch_count_rules(monkeypatch):
    app = _build_app(monkeypatch)

    from db import db
    from models import Team
    from utils import get_pitching_rules_for_team

    with app.app_context():
        team = db.session.get(Team, 1)

        team.pitching_rule_set = 'Bullpen Tournaments'
        bullpen = get_pitching_rules_for_team(team)
        assert bullpen['rule_type'] == 'pitch_count'
        assert bullpen['max_daily'] == 85
        assert bullpen['rest_thresholds'][-1] == (85, 4)
        assert 'Bullpen' in bullpen['rule_note']

        team.pitching_rule_set = 'Little League Baseball'
        little_league = get_pitching_rules_for_team(team)
        assert little_league['rule_type'] == 'pitch_count'
        assert little_league['max_daily'] == 85
        assert little_league['rest_thresholds'][-1] == (85, 4)


def test_game_can_override_team_default_with_bullpen(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.post('/api/game-day/1/pitching-rules', json={'rule_set': 'Bullpen Tournaments'})
    assert response.status_code == 200
    data = response.get_json()
    assert data['override'] == 'Bullpen Tournaments'
    assert data['effective'] == 'Bullpen Tournaments'
    assert data['source'] == 'game'


def test_older_little_league_age_fails_safe_for_automatic_eligibility(monkeypatch):
    app = _build_app(monkeypatch)

    from db import db
    from models import Team
    from utils import get_pitching_rules_for_team

    with app.app_context():
        team = db.session.get(Team, 1)
        team.age_group = '14U'
        team.pitching_rule_set = 'Little League Baseball'
        rules = get_pitching_rules_for_team(team)
        assert rules['rule_type'] == 'unsupported'
        assert 'division-specific' in rules['rule_note']
