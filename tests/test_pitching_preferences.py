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


def _add_heavy_previous_day_outing(app):
    from db import db
    from models import Game, PitchingOuting

    with app.app_context():
        game = db.session.get(Game, 1)
        db.session.add(PitchingOuting(
            date=game.date - timedelta(days=1),
            opponent='Heavy Previous Day',
            pitches=60,
            innings=3.0,
            pitcher_type='Starter',
            outing_type='Game',
            team_id=1,
            player_id=1,
        ))
        db.session.commit()


def _set_complete_live_defense(app):
    from db import db
    from models import Game, Player, Rotation

    alignment = {
        'P': 'Current Pitcher',
        'C': 'Catcher',
        '1B': 'First Base',
        '2B': 'Second Base',
        '3B': 'Third Base',
        'SS': 'Shortstop',
        'LF': 'Left Field',
        'CF': 'Center Field',
        'RF': 'Right Field',
    }

    with app.app_context():
        game = db.session.get(Game, 1)
        game.is_live = True
        for index, name in enumerate(alignment.values(), start=2):
            db.session.add(Player(id=index, name=name, team_id=1, pitcher_role='Not a Pitcher'))
        db.session.add(Rotation(
            title='Live defense',
            innings={'1': alignment},
            associated_game_id=1,
            team_id=1,
        ))
        db.session.commit()


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


def test_live_pitcher_change_blocks_officially_ineligible_pitcher(monkeypatch):
    app = _build_app(monkeypatch)
    _add_heavy_previous_day_outing(app)
    _set_complete_live_defense(app)
    client = app.test_client()
    _login(client)

    settings = client.post('/api/pitching-preferences/settings', json={
        'competition_default_rule': 'MLB Pitch Smart',
        'arm_care_rule_set': 'MLB Pitch Smart',
    })
    assert settings.status_code == 200

    response = client.post('/api/live-game/1/change-pitcher', json={
        'new_pitcher_id': 1,
        'outgoing_destination': 'BENCH',
    })
    assert response.status_code == 409
    payload = response.get_json()
    assert payload['status'] == 'error'
    assert payload['pitching_status'] != 'Available'
    assert payload['next_available']
    assert 'cannot be selected to pitch' in payload['message']
    assert 'Can pitch again' in payload['message']


def test_arm_care_rest_does_not_become_competition_block_without_rules(monkeypatch):
    app = _build_app(monkeypatch)
    _add_heavy_previous_day_outing(app)
    client = app.test_client()
    _login(client)

    # No competition default is configured, while the default arm-care setting is
    # still MLB Pitch Smart. The advisory rest flag must not masquerade as an
    # official competition restriction for an inactive game.
    arm = client.get('/api/pitching-preferences/arm-care-summary?game_id=1').get_json()
    assert arm['players']['Test Pitcher']['status'] != 'Available'

    response = client.post('/api/live-game/1/change-pitcher', json={
        'new_pitcher_id': 1,
        'outgoing_destination': 'BENCH',
    })
    assert response.status_code == 409
    assert response.get_json()['message'] == 'Game is not live.'


def test_live_game_requires_competition_rules_before_pitcher_change(monkeypatch):
    app = _build_app(monkeypatch)
    _set_complete_live_defense(app)
    client = app.test_client()
    _login(client)

    response = client.post('/api/live-game/1/change-pitcher', json={
        'new_pitcher_id': 1,
        'outgoing_destination': 'BENCH',
    })

    assert response.status_code == 409
    payload = response.get_json()
    assert payload['status'] == 'error'
    assert payload['pitching_status'] == 'Unavailable — Select Game Rules'
    assert payload['next_available'] == 'Verify event rules'
    assert 'cannot be selected to pitch' in payload['message']
