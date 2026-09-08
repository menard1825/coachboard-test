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
            team_name='Guest Test Team',
            registration_code='guest-test-code',
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
    with client.session_transaction() as flask_session:
        flask_session['logged_in'] = True
        flask_session['username'] = 'coach'
        flask_session['full_name'] = 'Test Coach'
        flask_session['team_id'] = 1
        flask_session['role'] = 'Head Coach'


def test_guest_defaults_out_for_existing_future_games(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game, Player, PlayerGameAbsence

    with app.app_context():
        past = Game(
            date=datetime.now() - timedelta(days=2),
            opponent='Past Team',
            team_id=1,
        )
        future_one = Game(
            date=datetime.now() + timedelta(days=2),
            opponent='Future One',
            team_id=1,
        )
        future_two = Game(
            date=datetime.now() + timedelta(days=3),
            opponent='Future Two',
            team_id=1,
        )
        db.session.add_all([past, future_one, future_two])
        db.session.commit()

        past_id = past.id
        future_ids = {future_one.id, future_two.id}

    response = client.post('/add_player', data={
        'name': 'Guest Player',
        'number': '42',
        'pitcher_role': 'Not a Pitcher',
        'roster_status': 'guest',
    })
    assert response.status_code == 302

    with app.app_context():
        guest = db.session.query(Player).filter_by(
            team_id=1,
            name='Guest Player',
        ).one()

        assert guest.is_guest is True

        absent_ids = {
            row.game_id
            for row in db.session.query(PlayerGameAbsence).filter_by(
                team_id=1,
                player_id=guest.id,
            ).all()
        }

        assert future_ids <= absent_ids
        assert past_id not in absent_ids


def test_regular_player_does_not_default_out(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game, Player, PlayerGameAbsence

    with app.app_context():
        game = Game(
            date=datetime.now() + timedelta(days=2),
            opponent='Future Team',
            team_id=1,
        )
        db.session.add(game)
        db.session.commit()

    response = client.post('/add_player', data={
        'name': 'Regular Player',
        'number': '12',
        'pitcher_role': 'Not a Pitcher',
        'roster_status': 'regular',
    })
    assert response.status_code == 302

    with app.app_context():
        player = db.session.query(Player).filter_by(
            team_id=1,
            name='Regular Player',
        ).one()

        assert player.is_guest is False
        assert db.session.query(PlayerGameAbsence).filter_by(
            team_id=1,
            player_id=player.id,
        ).count() == 0


def test_new_game_defaults_existing_guest_out(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game, Player, PlayerGameAbsence

    with app.app_context():
        guest = Player(
            name='Existing Guest',
            number='77',
            pitcher_role='Not a Pitcher',
            is_guest=True,
            team_id=1,
        )
        db.session.add(guest)
        db.session.commit()
        guest_id = guest.id

    game_date = (datetime.now() + timedelta(days=5)).strftime('%Y-%m-%d')

    response = client.post('/add_game', data={
        'game_date': game_date,
        'game_start_time': '10:00',
        'game_opponent': 'New Opponent',
        'game_location': 'Test Field',
    })
    assert response.status_code == 302

    with app.app_context():
        game = db.session.query(Game).filter_by(
            team_id=1,
            opponent='New Opponent',
        ).one()

        absence = db.session.query(PlayerGameAbsence).filter_by(
            team_id=1,
            game_id=game.id,
            player_id=guest_id,
        ).one_or_none()

        assert absence is not None


def test_guest_can_be_marked_playing_for_selected_game(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Game, Player, PlayerGameAbsence

    with app.app_context():
        game = Game(
            date=datetime.now() + timedelta(days=2),
            opponent='Selected Game',
            team_id=1,
        )
        db.session.add(game)
        db.session.commit()
        game_id = game.id

    client.post('/add_player', data={
        'name': 'Weekend Guest',
        'number': '55',
        'pitcher_role': 'Not a Pitcher',
        'roster_status': 'guest',
    })

    with app.app_context():
        guest = db.session.query(Player).filter_by(
            team_id=1,
            name='Weekend Guest',
        ).one()
        guest_id = guest.id

        assert db.session.query(PlayerGameAbsence).filter_by(
            game_id=game_id,
            player_id=guest_id,
            team_id=1,
        ).count() == 1

    # Submitting no absent_players means everybody is Playing.
    response = client.post(
        f'/game/{game_id}/update_absences',
        data={},
    )
    assert response.status_code == 302

    with app.app_context():
        assert db.session.query(PlayerGameAbsence).filter_by(
            game_id=game_id,
            player_id=guest_id,
            team_id=1,
        ).count() == 0


def test_roster_api_exposes_guest_status(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import Player

    with app.app_context():
        db.session.add(Player(
            name='API Guest',
            is_guest=True,
            pitcher_role='Not a Pitcher',
            team_id=1,
        ))
        db.session.commit()

    response = client.get('/api/roster')
    assert response.status_code == 200

    guest = next(
        player
        for player in response.get_json()
        if player['name'] == 'API Guest'
    )

    assert guest['is_guest'] is True
