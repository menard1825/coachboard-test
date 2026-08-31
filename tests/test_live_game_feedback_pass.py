from datetime import datetime

from werkzeug.security import generate_password_hash


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Game, Player, Rotation, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Real Game Feedback Team',
            registration_code='feedback-test-code',
            age_group='9U',
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

        names = ['Aiden', 'Bennett', 'Carter', 'Drew', 'Eli', 'Finn', 'Gavin', 'Hudson', 'Isaac', 'Jack']
        players = [Player(id=index + 1, name=name, number=str(index + 1), team_id=team.id) for index, name in enumerate(names)]
        db.session.add_all(players)

        inning_two = {
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
        inning_three = {
            'P': 'Aiden',
            'C': 'Bennett',
            '1B': 'Jack',
            '2B': 'Drew',
            '3B': 'Eli',
            'SS': 'Finn',
            'LF': 'Gavin',
            'CF': 'Hudson',
            'RF': 'Carter',
        }
        game = Game(
            id=70,
            date=datetime(2026, 8, 30, 17, 0, 0),
            opponent='Real Game Test',
            team_id=team.id,
            is_live=True,
            live_current_inning='2',
        )
        rotation = Rotation(
            id=1,
            title='Real Game Test Rotation',
            innings={'2': inning_two, '3': inning_three},
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


def _inning_two_with_jack_in_right():
    return {
        'P': 'Aiden',
        'C': 'Bennett',
        '1B': 'Carter',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Jack',
    }


def test_defense_edit_saves_one_event_and_returns_light_delta(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.post('/api/live-game/70/defense-edit', json={
        'base_sequence': 0,
        'alignment': _inning_two_with_jack_in_right(),
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'success'
    assert 'delta' in payload
    assert 'state' not in payload
    assert payload['delta']['sequence'] == 1
    assert payload['delta']['current_inning'] == '2'
    assert payload['delta']['current_alignment']['RF'] == 'Jack'
    assert {player['name'] for player in payload['delta']['bench']} == {'Isaac'}

    from db import db
    from models import GameRotationEvent

    with app.app_context():
        events = db.session.query(GameRotationEvent).filter_by(game_id=70, team_id=1).all()
        assert len(events) == 1
        assert events[0].event_type == 'Bulk Defensive Change'
        assert events[0].before_alignment['RF'] == 'Isaac'
        assert events[0].after_alignment['RF'] == 'Jack'


def test_stale_second_coach_edit_is_rejected_without_overwriting_first(monkeypatch):
    app = _build_app(monkeypatch)
    first_client = app.test_client()
    second_client = app.test_client()
    _login(first_client)
    _login(second_client)

    first = first_client.post('/api/live-game/70/defense-edit', json={
        'base_sequence': 0,
        'alignment': _inning_two_with_jack_in_right(),
    })
    assert first.status_code == 200

    stale_attempt = {
        'P': 'Aiden',
        'C': 'Bennett',
        '1B': 'Carter',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Jack',
        'RF': 'Isaac',
    }
    second = second_client.post('/api/live-game/70/defense-edit', json={
        'base_sequence': 0,
        'alignment': stale_attempt,
    })

    assert second.status_code == 409
    payload = second.get_json()
    assert payload['code'] == 'stale_live_state'
    assert payload['current_sequence'] == 1
    assert payload['current_alignment']['RF'] == 'Jack'
    assert payload['current_alignment']['CF'] == 'Hudson'

    from blueprints.live_game_api import _actual_rotation
    from db import db
    from models import Game, GameRotationEvent

    with app.app_context():
        game = db.session.get(Game, 70)
        _, actual, _ = _actual_rotation(game, 1)
        assert actual['2']['RF'] == 'Jack'
        assert actual['2']['CF'] == 'Hudson'
        assert db.session.query(GameRotationEvent).filter_by(game_id=70, team_id=1).count() == 1


def test_advance_inning_commits_new_defense_and_inning_together(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from blueprints.live_game_ui import GameNextInningPrep
    from db import db

    next_alignment = {
        'P': 'Aiden',
        'C': 'Bennett',
        '1B': 'Jack',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Carter',
    }

    with app.app_context():
        db.session.add(GameNextInningPrep(
            inning='3',
            alignment=next_alignment,
            source='custom',
            updated_by='Test Coach',
            game_id=70,
            team_id=1,
        ))
        db.session.commit()

    response = client.post('/api/live-game/70/advance-inning', json={
        'base_sequence': 0,
        'alignment': next_alignment,
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'success'
    assert payload['delta']['current_inning'] == '3'
    assert payload['delta']['current_alignment'] == next_alignment
    assert payload['delta']['event']['event_type'] == 'End Inning'
    assert payload['delta']['event']['inning'] == '3'

    from models import Game, GameRotationEvent

    with app.app_context():
        game = db.session.get(Game, 70)
        assert game.live_current_inning == '3'
        event = db.session.query(GameRotationEvent).filter_by(game_id=70, team_id=1).one()
        assert event.event_type == 'End Inning'
        assert event.inning == '3'
        assert event.after_alignment == next_alignment
        assert db.session.query(GameNextInningPrep).filter_by(game_id=70, team_id=1).first() is None


def test_field_player_can_take_mound_without_benching_outgoing_pitcher(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    # This test is about the defensive swap behavior. Keep pitching eligibility
    # deterministic here; the fail-closed eligibility rules have their own tests.
    from blueprints import live_game_bulk_api as bulk_module
    monkeypatch.setattr(
        bulk_module,
        'get_authoritative_live_state',
        lambda game_id, team_id: {'pitch_count_summary': {'Carter': {'status': 'Available'}}},
    )

    # Carter was at 1B. The common youth-baseball swap is Carter -> P and the
    # old pitcher Aiden -> 1B, with nobody unnecessarily sent to the bench.
    swapped = {
        'P': 'Carter',
        'C': 'Bennett',
        '1B': 'Aiden',
        '2B': 'Drew',
        '3B': 'Eli',
        'SS': 'Finn',
        'LF': 'Gavin',
        'CF': 'Hudson',
        'RF': 'Isaac',
    }
    response = client.post('/api/live-game/70/complete-pitcher-change', json={
        'base_sequence': 0,
        'fast': True,
        'new_pitcher_id': 3,
        'alignment': swapped,
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['delta']['current_alignment']['P'] == 'Carter'
    assert payload['delta']['current_alignment']['1B'] == 'Aiden'
    assert {player['name'] for player in payload['delta']['bench']} == {'Jack'}
    assert payload['delta']['event']['event_type'] == 'Pitcher Change'
