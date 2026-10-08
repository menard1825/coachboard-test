from datetime import datetime

from werkzeug.security import generate_password_hash



def _stored_inning_one(client, game_id):
    """What the Start button sends: the stored 1st inning the coach reviewed."""
    rotation = client.get(f'/api/game_data/{game_id}').get_json().get('rotation') or {}
    innings = rotation.get('innings') or {}
    if isinstance(innings, str):
        import json
        innings = json.loads(innings)
    return dict(innings.get('1') or {})

def _build_app(monkeypatch, *, complete_defense=True, with_rules=True):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from models import Game, Player, Rotation, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Start Contract Team',
            registration_code='start-contract-code',
            age_group='11U',
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

        names = ['Aiden', 'Bennett', 'Carter', 'Drew', 'Eli', 'Finn', 'Gavin', 'Hudson', 'Isaac']
        players = [
            Player(id=index + 1, name=name, number=str(index + 1), team_id=team.id)
            for index, name in enumerate(names)
        ]
        db.session.add_all(players)

        if with_rules:
            db.session.add(TeamPitchingSettings(
                team_id=team.id,
                competition_default_rule='USSSA',
                arm_care_rule_set='MLB Pitch Smart',
            ))

        inning_one = {
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
        if not complete_defense:
            inning_one.pop('RF')

        game = Game(
            id=91,
            date=datetime(2026, 8, 31, 18, 0, 0),
            opponent='Start Contract Opponent',
            team_id=team.id,
            is_live=False,
            live_current_inning='1',
        )
        rotation = Rotation(
            id=1,
            title='Starting Defense',
            innings={'1': inning_one},
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


def test_empty_batting_order_does_not_block_first_pitch(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    readiness_response = client.get('/api/game-day/91/readiness')
    assert readiness_response.status_code == 200
    readiness = readiness_response.get_json()

    assert readiness['readiness']['lineup_ready'] is False
    assert readiness['ready'] is True
    assert readiness['missing'] == []

    start_response = client.post('/api/live-game/91/start', json={'inning_one': _stored_inning_one(client, 91)})
    assert start_response.status_code == 200
    payload = start_response.get_json()
    assert payload['ready'] is True
    assert payload['missing'] == []
    assert payload['state']['game']['is_live'] is True


def test_an_open_inning_one_position_is_asked_about_not_blocked(monkeypatch):
    """RF open in the 1st inning is the coach's call: Start stays usable,
    asks about exactly RF, and starts once RF Open is acknowledged."""
    app = _build_app(monkeypatch, complete_defense=False)
    client = app.test_client()
    _login(client)

    readiness_response = client.get('/api/game-day/91/readiness')
    assert readiness_response.status_code == 200
    readiness = readiness_response.get_json()
    assert readiness['ready'] is True
    assert readiness['missing'] == []
    assert readiness['open_positions'] == ['RF']
    assert readiness['open_question']['title'] == '1st inning: RF is open'

    start_response = client.post('/api/live-game/91/start', json={'inning_one': _stored_inning_one(client, 91)})
    assert start_response.status_code == 409
    asked = start_response.get_json()
    assert asked['code'] == 'start_open_positions'
    assert asked['open_positions'] == readiness['open_positions']
    assert asked['open_question'] == readiness['open_question']

    from db import db
    from models import Game

    with app.app_context():
        assert db.session.get(Game, 91).is_live is False

    started = client.post('/api/live-game/91/start', json={'inning_one': _stored_inning_one(client, 91), 'open_positions': ['RF']})
    assert started.status_code == 200, started.get_json()
    with app.app_context():
        db.session.expire_all()
        assert db.session.get(Game, 91).is_live is True


def test_missing_pitching_rules_ask_about_the_starter_instead_of_blocking(monkeypatch):
    """No rules is not a data problem: Start stays usable and asks, because
    CoachBoard can't confirm the starter's eligibility."""
    app = _build_app(monkeypatch, with_rules=False)
    client = app.test_client()
    _login(client)

    readiness = client.get('/api/game-day/91/readiness').get_json()
    assert readiness['ready'] is True
    assert readiness['missing'] == []
    assert readiness['pitching_rules_selected'] is False

    asked = client.post('/api/live-game/91/start', json={'inning_one': _stored_inning_one(client, 91)})
    assert asked.status_code == 409
    payload = asked.get_json()
    assert payload['code'] == 'start_no_pitching_rules'
    assert payload['required_decision'] == 'no_rules_acknowledged'


def _six_innings_with_a_padded_roster_name(app, *, raw_innings=(1, 2), trimmed_innings=(3, 4, 5, 6)):
    """Drew's roster name was saved as typed on a phone: 'Drew ' (autocomplete
    adds the space). Some innings hold that exact name, others the trimmed one."""
    from db import db
    from models import Player, Rotation

    with app.app_context():
        db.session.get(Player, 4).name = 'Drew '
        rotation = db.session.get(Rotation, 1)
        base = dict(rotation.innings['1'])
        innings = {}
        for number in raw_innings:
            innings[str(number)] = dict(base, **{'2B': 'Drew '})
        for number in trimmed_innings:
            innings[str(number)] = dict(base, **{'2B': 'Drew'})
        rotation.innings = innings
        db.session.commit()


def test_a_roster_name_with_a_trailing_space_does_not_block_first_pitch(monkeypatch):
    # Start Game was greyed out with "Drew is at 2B in the 1st inning but is
    # not on the roster" while Home said READY: the start check trimmed the
    # plan's names but compared them with untrimmed roster names.
    app = _build_app(monkeypatch)
    _six_innings_with_a_padded_roster_name(app)
    client = app.test_client()
    _login(client)

    payload = client.get('/api/game-day/91/readiness').get_json()
    assert payload['hard_stops'] == []
    assert payload['ready'] is True
    # Home and Manage Game read the same answer: every inning counts.
    assert payload['readiness']['defense_completed_innings'] == 6
    assert payload['readiness']['defense_ready'] is True

    started = client.post('/api/live-game/91/start', json={'inning_one': _stored_inning_one(client, 91)})
    assert started.status_code == 200, started.get_json()
    assert started.get_json()['status'] == 'success'


def test_a_player_really_off_the_roster_still_blocks_first_pitch(monkeypatch):
    from db import db
    from models import Rotation

    app = _build_app(monkeypatch)
    with app.app_context():
        rotation = db.session.get(Rotation, 1)
        rotation.innings = {'1': dict(rotation.innings['1'], **{'2B': 'Somebody Else'})}
        db.session.commit()
    client = app.test_client()
    _login(client)

    payload = client.get('/api/game-day/91/readiness').get_json()
    assert payload['ready'] is False
    assert payload['hard_stops'] == ['Somebody Else is at 2B in the 1st inning but is not on the roster.']
    started = client.post('/api/live-game/91/start', json={'inning_one': _stored_inning_one(client, 91)})
    assert started.status_code == 409
    assert started.get_json()['code'] == 'start_hard_stops'


def test_a_padded_starting_pitcher_is_still_checked_for_eligibility(monkeypatch):
    # The starter's roster name carries the space; the eligibility check must
    # still find their pitching record, not treat them as unknown.
    from db import db
    from models import Player

    app = _build_app(monkeypatch)
    with app.app_context():
        db.session.get(Player, 1).name = 'Aiden '
        db.session.commit()
    client = app.test_client()
    _login(client)

    payload = client.get('/api/game-day/91/readiness').get_json()
    assert payload['ready'] is True and payload['hard_stops'] == []
    started = client.post('/api/live-game/91/start', json={'inning_one': _stored_inning_one(client, 91)})
    body = started.get_json()
    assert started.status_code == 200, body
