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
            team_name='History Test Team',
            registration_code='history-test-code',
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

        db.session.add_all([
            Game(
                date=datetime(2025, 6, 1),
                start_time='14:00',
                opponent='Past Opponent One',
                location='Old Field',
                team_id=team.id,
            ),
            Game(
                date=datetime(2025, 5, 15),
                opponent='Past Opponent Two',
                team_id=team.id,
            ),
        ])
        db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'


def test_game_day_schedule_shows_past_games_with_coach_friendly_time(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.get('/game-day')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Past Games' in html
    assert 'Past Opponent One' in html
    assert 'Past Opponent Two' in html
    assert '/game-day/1/report' in html
    assert '2:00 PM' in html
    assert '>14:00<' not in html


def test_same_day_game_is_not_repeated_in_past_games(monkeypatch):
    app = _build_app(monkeypatch)

    # Keep the route deterministic and create a completed game on the same date.
    monkeypatch.setattr(
        'blueprints.game_day.team_now',
        lambda team: datetime(2026, 8, 24, 16, 42),
    )

    from db import db
    from models import Game, GameRotationEvent

    with app.app_context():
        game = Game(
            date=datetime(2026, 8, 24),
            start_time='14:00',
            opponent='Same Day Opponent',
            team_id=1,
        )
        db.session.add(game)
        db.session.flush()
        db.session.add(GameRotationEvent(
            inning='1',
            sequence=1,
            event_type='End Game',
            before_alignment={},
            after_alignment={},
            changed_by_user='coach',
            team_id=1,
            game_id=game.id,
        ))
        db.session.commit()

    client = app.test_client()
    _login(client)
    response = client.get('/game-day')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.count('vs Same Day Opponent') == 1
    assert '2:00 PM' in html
