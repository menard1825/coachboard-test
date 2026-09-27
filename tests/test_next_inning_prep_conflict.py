"""Two Next Inning saves from the same starting defense: exactly one lands.

A Next Inning save sends the defense it was based on (``base_alignment``).
The server compares that with the stored defense, then writes. That compare
and the write must be atomic for the game: if two coaches' saves could both
pass the compare before either wrote, the second would silently overwrite the
first -- the very thing the base check exists to stop.

What makes it atomic is the per-game write lock
(``blueprints/live_game_write_lock.py``): every POST to this endpoint takes
the game's semaphore before the view runs and releases it only in teardown,
after the commit. CoachBoard runs as one eventlet process (``run.py``), so a
second save for the same game waits for the first to finish entirely.

The test forces the worst interleaving instead of hoping for it: it yields to
the other request right after the compare and before the write. Without the
lock both saves would pass the compare and the later one would win.
"""

from datetime import datetime

import eventlet
import pytest
from werkzeug.security import generate_password_hash


TEAM_ID = 1
GAME_ID = 1
PATH = f'/api/live-game/{GAME_ID}/next-inning-prep'
NAMES = ['Alex', 'Blake', 'Casey', 'Drew', 'Eli', 'Finn', 'Gray', 'Harper', 'Indy']
POSITIONS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']


@pytest.fixture(name='app')
def _app(monkeypatch, tmp_path):
    # A file database, so each request has its own connection and
    # transaction, as in the running app.
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "prep.db"}')

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
            date=datetime(2026, 9, 21, 10, 0, 0),
            opponent='Visitors',
            is_live=True,
            live_current_inning='1',
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


def _alignment(names):
    return dict(zip(POSITIONS, names))


def _stored():
    from db import db
    from blueprints.live_game_ui import GameNextInningPrep

    db.session.expire_all()
    prep = db.session.query(GameNextInningPrep).filter_by(
        game_id=GAME_ID, team_id=TEAM_ID,
    ).one()
    return {pos: name for pos, name in (prep.alignment or {}).items() if name}


def test_concurrent_saves_from_the_same_base_exactly_one_wins(app, monkeypatch):
    from blueprints import live_game_ui

    base = _alignment(NAMES)
    seeded = _client(app).post(PATH, json={'mode': 'custom', 'alignment': base})
    assert seeded.status_code == 200, seeded.get_json()

    # Coach A swaps P and C; coach B swaps SS and 2B. Both start from `base`.
    a = _alignment(['Blake', 'Alex'] + NAMES[2:])
    b = dict(base, SS='Drew', **{'2B': 'Finn'})

    checked = []
    real_check = live_game_ui._next_prep_conflict

    def check_then_yield(*args, **kwargs):
        result = real_check(*args, **kwargs)
        checked.append(result)
        # Hand the hub to the other request between the compare and the write.
        eventlet.sleep(0.05)
        return result

    monkeypatch.setattr(live_game_ui, '_next_prep_conflict', check_then_yield)

    def save(alignment):
        response = _client(app).post(PATH, json={
            'mode': 'custom',
            'alignment': alignment,
            'base_alignment': base,
            'inning': '2',
        })
        return response.status_code, response.get_json(), alignment

    first = eventlet.spawn(save, a)
    second = eventlet.spawn(save, b)
    results = [first.wait(), second.wait()]

    statuses = sorted(status for status, _, _ in results)
    assert statuses == [200, 409], results
    assert len(checked) == 2, 'both saves should have reached the compare'

    (winner,) = [alignment for status, _, alignment in results if status == 200]
    (loser,) = [body for status, body, _ in results if status == 409]
    assert loser['code'] == 'next_prep_conflict'

    with app.app_context():
        assert _stored() == winner


def test_a_save_from_the_current_base_is_accepted(app):
    base = _alignment(NAMES)
    client = _client(app)
    assert client.post(PATH, json={'mode': 'custom', 'alignment': base}).status_code == 200

    moved = dict(base, P='Blake', C='Alex')
    response = client.post(PATH, json={
        'mode': 'custom',
        'alignment': moved,
        'base_alignment': base,
        'inning': '2',
    })
    assert response.status_code == 200, response.get_json()

    stale = client.post(PATH, json={
        'mode': 'custom',
        'alignment': dict(base, SS='Drew', **{'2B': 'Finn'}),
        'base_alignment': base,
        'inning': '2',
    })
    assert stale.status_code == 409
    assert stale.get_json()['code'] == 'next_prep_conflict'

    with app.app_context():
        assert _stored() == moved
