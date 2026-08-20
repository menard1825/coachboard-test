from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash


def _build_app(monkeypatch, role='Head Coach'):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Game, PitchingOuting, Player, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Pitching Preference Test',
            registration_code='pitching-pref-test',
            age_group='12U',
            pitching_rule_set='MLB Pitch Smart',  # legacy field should not force the new default
            outfielder_count=3,
            timezone='America/Indiana/Indianapolis',
        )
        user = User(
            id=1,
            username='coach',
            full_name='Test Coach',
            password_hash=generate_password_hash('password123'),
        )
        player = Player(
            id=1,
            name='Test Pitcher',
            team_id=1,
            pitcher_role='Starter',
        )
        game = Game(
            id=1,
            date=datetime.now() + timedelta(days=1),
            opponent='Tournament Opponent',
            team_id=1,
        )
        db.session.add_all([team, user, player, game])
        db.session.flush()
        db.session.add(TeamMembership(
            user_id=user.id,
            team_id=team.id,
            role=role,
            player_order=[],
        ))
        db.session.add(PitchingOuting(
            date=datetime.now() - timedelta(days=1),
            opponent='Previous Opponent',
            pitches=30,
            innings=2.0,
            pitcher_type='Starter',
            outing_type='Game',
            team_id=1,
            player_id=1,
        ))
        db.session.commit()

    return app


def _login(client, role='Head Coach'):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['full_name'] = 'Test Coach'
        session['team_id'] = 1
        session['role'] = role


def test_new_team_does_not_require_competition_default(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.get('/api/pitching-preferences/settings')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['settings']['competition_default_rule'] is None
    assert payload['settings']['arm_care_rule_set'] == 'MLB Pitch Smart'
    assert 'USSSA' in payload['competition_options']
    assert 'Bullpen Tournaments' in payload['competition_options']

    game_rules = client.get('/api/game-day/1/pitching-rules').get_json()
    assert game_rules['effective'] is None
    assert game_rules['source'] == 'unselected'
    assert game_rules['arm_care_rule_set'] == 'MLB Pitch Smart'


def test_team_can_save_optional_default_and_arm_care_independently(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.post('/api/pitching-preferences/settings', json={
        'competition_default_rule': 'USSSA',
        'arm_care_rule_set': 'MLB Pitch Smart',
    })
    assert response.status_code == 200
    assert response.get_json()['settings'] == {
        'competition_default_rule': 'USSSA',
        'arm_care_rule_set': 'MLB Pitch Smart',
    }

    game_rules = client.get('/api/game-day/1/pitching-rules').get_json()
    assert game_rules['effective'] == 'USSSA'
    assert game_rules['source'] == 'team'

    override = client.post('/api/game-day/1/pitching-rules', json={'rule_set': 'Little League Baseball'})
    assert override.status_code == 200
    override_payload = override.get_json()
    assert override_payload['effective'] == 'Little League Baseball'
    assert override_payload['source'] == 'game'
    assert override_payload['arm_care_rule_set'] == 'MLB Pitch Smart'

    clear_default = client.post('/api/pitching-preferences/settings', json={
        'competition_default_rule': '',
        'arm_care_rule_set': '',
    })
    assert clear_default.status_code == 200
    assert clear_default.get_json()['settings']['competition_default_rule'] is None
    assert clear_default.get_json()['settings']['arm_care_rule_set'] is None


def test_arm_care_summary_is_available_without_competition_default(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.get('/api/pitching-preferences/arm-care-summary?game_id=1')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['enabled'] is True
    assert payload['rule_set'] == 'MLB Pitch Smart'
    assert 'Test Pitcher' in payload['players']
    assert payload['players']['Test Pitcher']['game_pitches_7_day'] == 30

    pitching_page = client.get('/pitching')
    assert pitching_page.status_code == 200

    rules_page = client.get('/rules')
    assert rules_page.status_code in {301, 302}
    assert '/admin/settings' in rules_page.headers['Location']


def test_assistant_coach_cannot_change_pitching_preferences(monkeypatch):
    app = _build_app(monkeypatch, role='Assistant Coach')
    client = app.test_client()
    _login(client, role='Assistant Coach')

    response = client.post('/api/pitching-preferences/settings', json={
        'competition_default_rule': 'USSSA',
        'arm_care_rule_set': 'MLB Pitch Smart',
    })
    assert response.status_code == 403
