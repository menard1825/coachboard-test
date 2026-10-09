"""Game Day cards say "Ready for First Pitch" by Start Game's own check.

build_game_readiness() (Game Day cards, the home Next Game card) and
can_start_game() (Start Game, Prepare Game) now share one first-pitch check,
game_start_readiness.first_pitch_hard_stops(). A ready 1st inning is ready:
the batting order and innings 2-6 are optional planning. Live and finished
games keep their own statuses.
"""

from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash


TEAM_ID = 1
GAME_ID = 1
NAMES = ['Alex', 'Blake', 'Casey', 'Drew', 'Eli', 'Finn', 'Gray', 'Harper', 'Indy']
POSITIONS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']
FULL = dict(zip(POSITIONS, NAMES))
FIELDERS = {pos: name for pos, name in FULL.items() if pos != 'P'}


@pytest.fixture(name='app')
def _app(monkeypatch, tmp_path):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "first_pitch.db"}')

    from app import create_app
    from db import db
    from models import Game, Player, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(id=TEAM_ID, team_name='Test Team', registration_code='code', age_group='12U',
                 pitching_rule_set='MLB Pitch Smart', outfielder_count=3,
                 timezone='America/Indiana/Indianapolis'),
            User(id=1, username='coach', full_name='Coach', password_hash=generate_password_hash('pw-123456')),
        ])
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=TEAM_ID, role='Head Coach', player_order=[]))
        db.session.add(Game(id=GAME_ID, team_id=TEAM_ID, date=datetime.now() + timedelta(days=3),
                            opponent='Visitors', is_live=False))
        for index, name in enumerate(NAMES, start=1):
            db.session.add(Player(id=index, team_id=TEAM_ID, name=name))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = TEAM_ID
        session['role'] = 'Head Coach'
    return client


def _plan(app, innings, absent=()):
    from db import db
    from models import PlayerGameAbsence, Rotation
    with app.app_context():
        db.session.add(Rotation(title='Rotation', team_id=TEAM_ID, associated_game_id=GAME_ID, innings=innings))
        for name in absent:
            db.session.add(PlayerGameAbsence(player_id=NAMES.index(name) + 1, game_id=GAME_ID, team_id=TEAM_ID))
        db.session.commit()


def _both(app):
    """Game Day's readiness and Start Game's check for the same game."""
    from db import db
    from game_day_helpers import build_game_readiness
    from game_start_readiness import can_start_game
    from models import Game, Team
    with app.app_context():
        game, team = db.session.get(Game, GAME_ID), db.session.get(Team, TEAM_ID)
        return build_game_readiness(game, team), can_start_game(game, team)


SIX_EMPTY = {str(n): {} for n in range(2, 7)}


@pytest.mark.parametrize('innings, absent', [
    ({'1': dict(FULL), **SIX_EMPTY}, ()),                     # 1st inning only
    ({'1': dict(FIELDERS), **SIX_EMPTY}, ()),                 # no starting pitcher
    ({'1': dict(FULL), **SIX_EMPTY}, ('Gray',)),              # Gray (LF) is Out
    ({'1': {**FULL, 'RF': 'Alex'}, **SIX_EMPTY}, ()),         # Alex twice
    ({'1': {'P': 'Alex', 'C': 'Blake'}, **SIX_EMPTY}, ()),    # open positions: Start asks
    ({}, ()),                                                 # nothing planned
])
def test_game_day_and_start_game_agree_on_first_pitch(app, innings, absent):
    if innings:
        _plan(app, innings, absent)
    readiness, start = _both(app)

    assert readiness['first_pitch_ready'] is start['ready']
    assert readiness['first_pitch_blockers'] == start['hard_stops']
    assert readiness['status'] == ('READY' if start['ready'] else 'PREP')


def test_a_ready_first_inning_is_ready_without_a_lineup_or_later_innings(app):
    _plan(app, {'1': dict(FULL), **SIX_EMPTY})
    readiness, _ = _both(app)

    assert readiness['status'] == 'READY'
    assert readiness['primary_label'] == 'Open Game'
    # Still reported as planning items, never as a reason it can't start.
    assert readiness['ready'] is False
    assert readiness['lineup_ready'] is False and readiness['defense_ready'] is False


def test_the_game_day_card_says_ready_for_first_pitch(app):
    _plan(app, {'1': dict(FULL), **SIX_EMPTY})
    page = _client(app).get('/game-day').get_data(as_text=True)

    assert 'Ready for First Pitch' in page
    assert '1st inning ready' in page
    assert 'Optional before first pitch: batting order and full-game defense.' in page
    assert 'setup items to finish' not in page


def test_the_game_day_card_lists_only_first_pitch_blockers(app):
    _plan(app, {'1': dict(FIELDERS), **SIX_EMPTY})
    page = _client(app).get('/game-day').get_data(as_text=True)

    assert '1 item before first pitch' in page
    assert 'Choose the starting pitcher for the 1st inning.' in page
    assert 'Defense needs attention in regulation inning' not in page
    assert 'Ready for First Pitch' not in page


def test_live_and_finished_games_keep_their_status(app):
    from db import db
    from models import Game, GameRotationEvent
    _plan(app, {'1': dict(FULL), **SIX_EMPTY})
    with app.app_context():
        db.session.get(Game, GAME_ID).is_live = True
        db.session.commit()
    assert _both(app)[0]['status'] == 'LIVE'

    with app.app_context():
        db.session.get(Game, GAME_ID).is_live = False
        db.session.add(GameRotationEvent(team_id=TEAM_ID, game_id=GAME_ID, inning='1', sequence=1,
                                         event_type='End Game', after_alignment=dict(FULL)))
        db.session.commit()
    assert _both(app)[0]['status'] in {'COMPLETE', 'GC STATS PENDING'}
