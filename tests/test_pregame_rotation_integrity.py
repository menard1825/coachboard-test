"""A game's pregame plan is saved whole, valid, and never under a live write.

/save_rotation is the one writer of a game's plan from the browser. It now:

* refuses an inning that puts one player at two positions (open positions,
  including a P not yet chosen for a later inning, are fine), saving nothing;
* runs its read/check/write under the game's write lock
  (blueprints/live_game_write_lock.py), the same lock every live write --
  Start Game included -- holds for its whole request.

So Start Game can take the lock, read the stored Inning 1 defense, validate
it and start the game knowing no plan save lands in between; a save that
arrives meanwhile waits, then sees the game is live and is refused.

The interleaving tests force the worst ordering (a yield between the check
and the write) instead of hoping for it, as tests/test_next_inning_prep_
conflict.py does. CoachBoard runs as one eventlet process (run.py).
"""

from datetime import datetime

import eventlet
import pytest
from werkzeug.security import generate_password_hash


TEAM_ID = 1
GAME_ID = 1
NAMES = ['Alex', 'Blake', 'Casey', 'Drew', 'Eli', 'Finn', 'Gray', 'Harper', 'Indy']
POSITIONS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']
FULL = dict(zip(POSITIONS, NAMES))


@pytest.fixture(name='app')
def _app(monkeypatch, tmp_path):
    # A file database, so each request has its own connection and
    # transaction, as in the running app.
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "rotation.db"}')

    from app import create_app
    from db import db
    from models import Game, Player, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(
                id=TEAM_ID,
                team_name='Test Team',
                registration_code='test-code',
                age_group='12U',
                pitching_rule_set='MLB Pitch Smart',
                outfielder_count=3,
                timezone='America/Indiana/Indianapolis',
            ),
            User(
                id=1,
                username='coach',
                full_name='Test Coach',
                password_hash=generate_password_hash('password123'),
            ),
        ])
        db.session.flush()
        db.session.add(TeamMembership(
            user_id=1, team_id=TEAM_ID, role='Head Coach', player_order=[],
        ))
        db.session.add(Game(
            id=GAME_ID,
            team_id=TEAM_ID,
            date=datetime(2026, 10, 10, 10, 0, 0),
            opponent='Visitors',
            is_live=False,
        ))
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


def _save(app, innings, rotation_id=None, game_id=GAME_ID):
    response = _client(app).post('/save_rotation', json={
        'id': rotation_id,
        'title': 'Rotation for vs Visitors',
        'innings': innings,
        'associated_game_id': game_id,
    })
    return response.status_code, response.get_json()


def _stored(app, rotation_id=None):
    from db import db
    from models import Rotation

    with app.app_context():
        db.session.expire_all()
        query = db.session.query(Rotation).filter_by(team_id=TEAM_ID)
        rotation = (query.filter_by(id=rotation_id) if rotation_id else
                    query.filter_by(associated_game_id=GAME_ID)).first()
        return rotation.innings if rotation else None


def _seed(app, innings):
    status, body = _save(app, innings)
    assert status == 200, body
    return body['new_id']


# --- What saves ---------------------------------------------------------------------------

def test_a_valid_rotation_saves_and_updates_normally(app):
    rotation_id = _seed(app, {'1': FULL, '2': FULL})
    assert _stored(app) == {'1': FULL, '2': FULL}

    moved = dict(FULL, SS='Harper', CF='Finn')
    status, body = _save(app, {'1': FULL, '2': moved}, rotation_id)
    assert status == 200 and body['new_id'] == rotation_id, body
    assert _stored(app) == {'1': FULL, '2': moved}


def test_an_open_fielding_position_saves(app):
    open_cf = {pos: name for pos, name in FULL.items() if pos != 'CF'}
    open_cf['CF'] = ''
    _seed(app, {'1': open_cf})
    assert _stored(app) == {'1': open_cf}


def test_a_later_inning_with_the_pitcher_to_be_decided_saves(app):
    no_p = {pos: name for pos, name in FULL.items() if pos != 'P'}
    _seed(app, {'1': FULL, '2': no_p, '3': {}})
    assert _stored(app) == {'1': FULL, '2': no_p, '3': {}}


def test_a_reusable_template_is_not_a_game_plan(app):
    # No game: no game lock and no game-plan rule change here.
    status, body = _save(app, {'1': FULL}, game_id=None)
    assert status == 200, body
    assert _stored(app, body['new_id']) == {'1': FULL}


# --- Duplicates are refused, whole ---------------------------------------------------------

def test_a_player_at_two_fielding_positions_is_refused(app):
    rotation_id = _seed(app, {'1': FULL, '2': FULL})
    bad = dict(FULL, CF='Finn')  # Finn at SS and CF
    status, body = _save(app, {'1': FULL, '2': bad}, rotation_id)
    assert status == 400, body
    assert body['code'] == 'duplicate_player'
    assert body['message'] == 'Finn is assigned to both SS and CF in the 2nd inning.'
    assert _stored(app) == {'1': FULL, '2': FULL}


def test_a_duplicate_involving_the_pitcher_is_refused(app):
    rotation_id = _seed(app, {'1': FULL})
    bad = dict(FULL, SS='Alex')  # Alex pitching and at SS
    status, body = _save(app, {'1': bad}, rotation_id)
    assert status == 400, body
    assert body['message'] == 'Alex is assigned to both P and SS in the 1st inning.'
    assert _stored(app) == {'1': FULL}


def test_a_refused_save_changes_nothing_not_even_its_valid_innings(app):
    rotation_id = _seed(app, {'1': FULL, '2': FULL})
    good_first = dict(FULL, SS='Harper', CF='Finn')
    bad_second = dict(FULL, LF='Alex', RF='Alex')
    status, body = _save(app, {'1': good_first, '2': bad_second}, rotation_id)
    assert status == 400, body
    assert 'Alex is assigned to P, LF and RF in the 2nd inning.' == body['message']
    assert _stored(app) == {'1': FULL, '2': FULL}


def test_a_first_save_with_a_duplicate_creates_nothing(app):
    status, body = _save(app, {'1': dict(FULL, SS='Alex')})
    assert status == 400, body
    assert _stored(app) is None


def test_an_older_duplicate_elsewhere_never_blocks_an_edit_and_its_fix_saves(app):
    from db import db
    from models import Rotation

    legacy = dict(FULL, SS='Alex')  # saved before this rule existed
    rotation_id = _seed(app, {'1': FULL, '2': FULL})
    with app.app_context():
        rotation = db.session.get(Rotation, rotation_id)
        rotation.innings = {'1': FULL, '2': legacy}
        db.session.commit()

    # Only changed innings are validated: the browser sends the whole rotation,
    # so an untouched old duplicate must not block editing another inning.
    # Editing the 1st inning is not blocked by the 2nd inning's old duplicate.
    edited = dict(FULL, CF='Harper', LF='Gray', RF='Indy')
    status, body = _save(app, {'1': edited, '2': legacy}, rotation_id)
    assert status == 200, body

    # The edit that fixes the 2nd inning saves.
    fixed = dict(FULL, SS='Finn')
    status, body = _save(app, {'1': edited, '2': fixed}, rotation_id)
    assert status == 200, body
    assert _stored(app) == {'1': edited, '2': fixed}


def test_a_live_game_plan_is_refused(app):
    from db import db
    from models import Game

    rotation_id = _seed(app, {'1': FULL})
    with app.app_context():
        db.session.get(Game, GAME_ID).is_live = True
        db.session.commit()
    status, body = _save(app, {'1': dict(FULL, SS='Harper', CF='Finn')}, rotation_id)
    assert status == 409, body
    assert _stored(app) == {'1': FULL}


# --- The game write lock ---------------------------------------------------------------------

def test_a_plan_save_waits_for_the_games_write_lock(app):
    from blueprints.live_game_write_lock import _game_locks

    rotation_id = _seed(app, {'1': FULL})
    lock = _game_locks[GAME_ID]
    lock.acquire()
    try:
        saving = eventlet.spawn(_save, app, {'1': dict(FULL, SS='Harper', CF='Finn')}, rotation_id)
        eventlet.sleep(0.2)
        assert not saving.dead, 'the save must wait while another write holds the game'
        assert _stored(app) == {'1': FULL}
    finally:
        lock.release()
    status, body = saving.wait()
    assert status == 200, body
    assert _stored(app) == {'1': dict(FULL, SS='Harper', CF='Finn')}


def test_another_games_lock_does_not_hold_up_this_plan(app):
    from blueprints.live_game_write_lock import _game_locks

    rotation_id = _seed(app, {'1': FULL})
    other = _game_locks[GAME_ID + 1]
    other.acquire()
    try:
        status, body = _save(app, {'1': dict(FULL, SS='Harper', CF='Finn')}, rotation_id)
        assert status == 200, body
    finally:
        other.release()


def _slow_start_check(monkeypatch, validated):
    """Start Game's readiness check, recording the Inning 1 it read, then
    handing the hub to any other request before Start writes."""
    from blueprints import live_game_api
    from db import db
    from models import Rotation

    def check(game, team, **kwargs):
        rotation = db.session.query(Rotation).filter_by(
            associated_game_id=game.id, team_id=team.id,
        ).first()
        inning_one = dict((rotation.innings or {}).get('1') or {})
        validated.append(inning_one)
        eventlet.sleep(0.1)
        return {'ready': True, 'missing': [], 'hard_stops': [], 'inning_one': inning_one,
                'open_positions': [], 'open_question': None}

    monkeypatch.setattr(live_game_api, 'can_start_game', check)


def test_start_game_validates_the_plan_it_starts_with_a_save_arriving_mid_start(app, monkeypatch):
    """Start holds the lock from its read to its commit; the save waits,
    then sees the game is live and is refused. The game starts with exactly
    the Inning 1 defense Start validated."""
    rotation_id = _seed(app, {'1': FULL})
    validated = []
    _slow_start_check(monkeypatch, validated)
    replacement = dict(FULL, SS='Harper', CF='Finn')

    starting = eventlet.spawn(lambda: _client(app).post(f'/api/live-game/{GAME_ID}/start', json={'inning_one': FULL}))
    eventlet.sleep(0.02)  # Start is inside its check, holding the lock
    saving = eventlet.spawn(_save, app, {'1': replacement}, rotation_id)

    started = starting.wait()
    status, body = saving.wait()
    assert started.status_code == 200, started.get_json()
    assert status == 409, body
    assert validated == [FULL]
    assert _stored(app) == {'1': FULL}


def test_a_save_in_progress_finishes_before_start_game_reads_the_plan(app, monkeypatch):
    """The save holds the lock from its read to its commit; Start waits and
    then validates the saved plan, never the one it replaced."""
    from blueprints import gameday

    rotation_id = _seed(app, {'1': FULL})
    validated = []
    _slow_start_check(monkeypatch, validated)
    replacement = dict(FULL, SS='Harper', CF='Finn')

    real_check = gameday._duplicate_assignment

    def check_then_yield(*args, **kwargs):
        result = real_check(*args, **kwargs)
        eventlet.sleep(0.1)  # between the plan save's check and its write
        return result

    monkeypatch.setattr(gameday, '_duplicate_assignment', check_then_yield)

    saving = eventlet.spawn(_save, app, {'1': replacement}, rotation_id)
    eventlet.sleep(0.02)  # the save is inside its check, holding the lock
    # The coach starts after the save lands (the browser settles saves first).
    starting = eventlet.spawn(lambda: _client(app).post(f'/api/live-game/{GAME_ID}/start', json={'inning_one': replacement}))

    status, body = saving.wait()
    started = starting.wait()
    assert status == 200, body
    assert started.status_code == 200, started.get_json()
    assert validated == [replacement]
    assert _stored(app) == {'1': replacement}
