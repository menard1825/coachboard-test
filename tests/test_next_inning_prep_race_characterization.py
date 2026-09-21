"""Guardrail: concurrent creation of a next-inning prep row.

``GET /api/live-game/<id>/next-inning-prep`` writes. When a live game has no
prep row for the upcoming inning, ``_next_inning_context`` seeds one and
commits -- on a GET. ``live_game_board_prep_v2.js`` polls that endpoint every
3.5 seconds, so at each inning rollover every coach with the page open races to
create the same row.

Two facts make that a real window:

* ``live_game_write_lock._live_game_write()`` only serialises POST/PUT/PATCH/
  DELETE, so this GET does not take the per-game semaphore;
* ``_next_inning_context`` reads, decides ``prep is None``, then inserts, with
  no handling for the row having appeared in between.

The tests that describe the *current* situation pass. The two that describe the
behaviour a fix should produce are marked ``xfail(strict=True)``, so the desired
contract is written down as the goal rather than today's HTTP 500 being frozen
in as a permanent expectation. When the race is handled, both flip to XPASS,
``strict=True`` turns that into a failure, and the markers have to be removed.

This slice does not fix the race.

How the race is simulated, and what that does and does not prove
---------------------------------------------------------------
The application runs under eventlet, where the interleaving happens between
greenlets at an I/O yield. Reproducing that faithfully would need a real
eventlet hub and a shared database connection -- more machinery than this slice
warrants.

``_install_stale_first_read`` substitutes for it: the next read of the prep
table misses once and then delegates to the real query. That is exactly the
losing request's view -- it reads just before the winner commits, but the row is
there by the time it inserts, and it is there for any retry the code makes.
Crucially, the miss is not permanent, so a correct recovery path can succeed
here; a simulation that returned ``None`` forever would make a real fix look
broken.

What this proves is that the *assumption is unguarded*. It does not measure how
often the window is hit; the audit's estimate is that it is rare, and
self-healing on the next poll.
"""

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from guardrail_support import build_app


TEAM_ID = 1
GAME_ID = 1


@pytest.fixture(name='app')
def _app(monkeypatch):
    app = build_app(monkeypatch)

    from db import db
    from models import Game, Player, Team, TeamMembership, User

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
        for index, name in enumerate(
            ['Alex', 'Blake', 'Casey', 'Drew', 'Eli', 'Finn', 'Gray', 'Harper', 'Indy'],
            start=1,
        ):
            db.session.add(Player(id=index, team_id=TEAM_ID, name=name))
        db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = TEAM_ID
        session['role'] = 'Head Coach'


def _prep_rows():
    from db import db
    from blueprints.live_game_ui import GameNextInningPrep

    return db.session.query(GameNextInningPrep).filter_by(
        game_id=GAME_ID, team_id=TEAM_ID,
    ).all()


# --------------------------------------------------------------------------
# The two conditions that open the window
# --------------------------------------------------------------------------

def test_the_polled_get_is_not_covered_by_the_live_write_lock(app):
    """The per-game semaphore does not serialise this GET.

    Fully deterministic: it exercises the real predicate that decides whether a
    request takes the lock.
    """
    from flask import request

    from blueprints.live_game_write_lock import _live_game_write

    path = f'/api/live-game/{GAME_ID}/next-inning-prep'

    # A POST to the same endpoint is serialised...
    with app.test_request_context(path, method='POST'):
        assert request.endpoint == 'live_game_ui.next_inning_prep', (
            'the endpoint did not resolve, so this test proves nothing'
        )
        assert _live_game_write() is True

    # ...the polled GET is not.
    with app.test_request_context(path, method='GET'):
        assert request.endpoint == 'live_game_ui.next_inning_prep'
        assert _live_game_write() is False, (
            'the GET now takes the write lock -- if that was deliberate, this '
            'characterization test should be replaced by a real concurrency '
            'regression test'
        )


def test_a_read_of_the_prep_endpoint_writes_a_row(app):
    """Characterize write-on-GET: the first poll of an inning creates state."""
    client = app.test_client()
    _login(client)

    with app.app_context():
        assert _prep_rows() == []

    response = client.get(f'/api/live-game/{GAME_ID}/next-inning-prep')
    assert response.status_code == 200

    with app.app_context():
        rows = _prep_rows()
        assert len(rows) == 1, 'a GET no longer seeds the prep row'
        assert rows[0].inning == '2'
        assert rows[0].updated_by == 'Auto'


def test_a_repeat_read_does_not_write_again(app):
    """Steady-state polling is a read.

    This bounds the finding: the write happens once per inning per game, not on
    every one of the ~17 polls a minute.
    """
    client = app.test_client()
    _login(client)

    client.get(f'/api/live-game/{GAME_ID}/next-inning-prep')
    with app.app_context():
        first = _prep_rows()[0]
        first_id, first_updated = first.id, first.updated_at

    for _ in range(3):
        assert client.get(
            f'/api/live-game/{GAME_ID}/next-inning-prep'
        ).status_code == 200

    with app.app_context():
        rows = _prep_rows()
        assert len(rows) == 1
        assert rows[0].id == first_id
        assert rows[0].updated_at == first_updated


# --------------------------------------------------------------------------
# What the losing request actually experiences
# --------------------------------------------------------------------------

def _install_stale_first_read(monkeypatch):
    """Make the next read of the prep table miss, then behave normally.

    This is the losing request's view of the race: it reads the table in the
    instant before the winning request commits, so it sees no row -- but the
    row *is* there by the time it tries to insert, and it is there for any
    retry the code might make.

    Returning ``None`` forever (an earlier version of this test) would have
    misrepresented the race: it would make a correct retry loop spin, and would
    let a fix look broken. Delegating from the second call on is what lets a
    real recovery path succeed here.
    """
    from blueprints import live_game_ui

    real_prep_for_game = live_game_ui._prep_for_game
    calls = {'count': 0}

    def stale_first_read(game_id, team_id):
        calls['count'] += 1
        if calls['count'] == 1:
            return None
        return real_prep_for_game(game_id, team_id)

    monkeypatch.setattr(live_game_ui, '_prep_for_game', stale_first_read)
    return calls


def test_the_unique_constraint_prevents_duplicate_prep_rows(app):
    """Two inserts for one game cannot both land.

    The database refuses the second. That is the protection -- there is none in
    the application code. This assertion should hold whatever the race fix
    turns out to be.
    """
    from db import db
    from blueprints.live_game_ui import GameNextInningPrep

    client = app.test_client()
    _login(client)
    client.get(f'/api/live-game/{GAME_ID}/next-inning-prep')

    with app.app_context():
        db.session.add(GameNextInningPrep(
            game_id=GAME_ID,
            team_id=TEAM_ID,
            inning='2',
            alignment={},
            source='Auto',
            updated_by='Auto',
            updated_at=datetime.utcnow(),
        ))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    with app.app_context():
        assert len(_prep_rows()) == 1, 'duplicate prep rows are now possible'


def test_the_stale_read_simulation_is_wired_correctly(app, monkeypatch):
    """The simulation must miss once and then tell the truth.

    Without this, the two xfails below could be xfailing for the wrong reason.
    """
    from blueprints import live_game_ui

    client = app.test_client()
    _login(client)
    client.get(f'/api/live-game/{GAME_ID}/next-inning-prep')

    with app.app_context():
        calls = _install_stale_first_read(monkeypatch)

        assert live_game_ui._prep_for_game(GAME_ID, TEAM_ID) is None, (
            'the first read should miss, as the losing request does'
        )
        recovered = live_game_ui._prep_for_game(GAME_ID, TEAM_ID)
        assert recovered is not None, (
            'a retry should find the row the winning request committed'
        )
        assert recovered.inning == '2'
        assert calls['count'] == 2


def test_a_stale_first_read_recovers_the_committed_row(app, monkeypatch):
    """The losing request adopts the winning row instead of raising.

    Held as a strict xfail until the IntegrityError recovery landed in
    _next_inning_context. The row it returns must be the one already committed,
    not a second row and not None.
    """
    from db import db
    from blueprints import live_game_ui
    from models import Game, Team

    client = app.test_client()
    _login(client)
    client.get(f'/api/live-game/{GAME_ID}/next-inning-prep')

    with app.app_context():
        calls = _install_stale_first_read(monkeypatch)

        game = db.session.get(Game, GAME_ID)
        team = db.session.get(Team, TEAM_ID)

        winner = _prep_rows()[0]
        winner_id = winner.id

        _, next_inning, _, _, prep, _, _ = live_game_ui._next_inning_context(game, team)

        assert calls['count'] >= 1, 'the stale read was never consumed'
        assert next_inning == '2'
        assert prep is not None, 'the losing request produced no prep row'
        assert prep.id == winner_id, (
            'the losing request did not adopt the row the winner committed'
        )
        assert prep.inning == '2'
        assert len(_prep_rows()) == 1, 'recovery created a second prep row'


def test_the_losing_poll_still_serves_the_prep(app, monkeypatch):
    """End-to-end: the coach's poll succeeds and serves the committed prep.

    Held as a strict xfail while the losing poll returned HTTP 500. The refresh
    a coach sees must carry the real alignment, not merely avoid erroring.
    """
    app.config['PROPAGATE_EXCEPTIONS'] = False

    client = app.test_client()
    _login(client)
    assert client.get(f'/api/live-game/{GAME_ID}/next-inning-prep').status_code == 200

    calls = _install_stale_first_read(monkeypatch)

    response = client.get(f'/api/live-game/{GAME_ID}/next-inning-prep')

    assert calls['count'] >= 1, 'the stale read was never consumed'
    assert response.status_code == 200

    payload = response.get_json()
    assert payload['next_inning'] == '2'
    assert payload['confirmed'], 'the poll succeeded but served no prep'

    with app.app_context():
        assert len(_prep_rows()) == 1


# --------------------------------------------------------------------------
# The recovery must stay narrow
#
# Adopting the winning row is correct only for *this* race. An IntegrityError
# from anything else, or one after which the expected row still is not there,
# must reach the caller untouched rather than being quietly turned into a 200.
# --------------------------------------------------------------------------

def _fail_next_commit_with(monkeypatch, app, error):
    """Make the next db.session.commit() raise ``error``, once."""
    from db import db

    real_commit = db.session.commit
    state = {'raised': False}

    def commit_once_failing():
        if not state['raised']:
            state['raised'] = True
            raise error
        return real_commit()

    monkeypatch.setattr(db.session, 'commit', commit_once_failing)
    return state


def test_an_unrelated_integrity_error_is_not_swallowed(app, monkeypatch):
    """A constraint failure that leaves no recoverable row must propagate.

    If the recovery caught IntegrityError broadly, this would return a prep
    row -- or None -- instead of surfacing a real database failure.
    """
    from db import db
    from blueprints import live_game_ui
    from models import Game, Team

    with app.app_context():
        assert _prep_rows() == []

        game = db.session.get(Game, GAME_ID)
        team = db.session.get(Team, TEAM_ID)

        unrelated = IntegrityError(
            'INSERT INTO something_else', {}, Exception('FOREIGN KEY constraint failed'),
        )
        state = _fail_next_commit_with(monkeypatch, app, unrelated)

        with pytest.raises(IntegrityError) as caught:
            live_game_ui._next_inning_context(game, team)

        assert state['raised'], 'the failing commit was never reached'
        assert caught.value is unrelated, (
            'a different error surfaced; the original was not re-raised intact'
        )


def test_a_recovered_row_for_the_wrong_inning_is_not_adopted(app, monkeypatch):
    """Recovery only accepts a row that answers *this* request.

    If the row found after the rollback is for another inning, the request has
    not recovered -- it would otherwise serve a coach the wrong inning's
    defense. The error propagates instead.
    """
    from db import db
    from blueprints import live_game_ui
    from blueprints.live_game_ui import GameNextInningPrep
    from models import Game, Team

    with app.app_context():
        # A row exists, but for an inning this request is not preparing.
        db.session.add(GameNextInningPrep(
            game_id=GAME_ID,
            team_id=TEAM_ID,
            inning='3',
            alignment={},
            source='Auto',
            updated_by='Auto',
            updated_at=datetime.utcnow(),
        ))
        db.session.commit()

        # The losing request's read misses it, so it tries to insert inning 2
        # and trips the unique constraint on (game_id, team_id).
        _install_stale_first_read(monkeypatch)

        game = db.session.get(Game, GAME_ID)
        team = db.session.get(Team, TEAM_ID)

        with pytest.raises(IntegrityError):
            live_game_ui._next_inning_context(game, team)

    with app.app_context():
        rows = _prep_rows()
        assert len(rows) == 1
        assert rows[0].inning == '3', 'the wrong-inning row was modified'


def test_the_recovery_catches_only_integrity_errors(app, monkeypatch):
    """A non-IntegrityError propagates even when a row could be adopted.

    The recoverable row has to exist for this to mean anything. If it did not,
    a broad ``except Exception`` would re-raise for want of something to return
    and the test would pass against the wrong code -- which is exactly what an
    earlier version of this test did.

    Here the winning row is present and matches the requested inning, so a
    broad catch would swallow the error and return 'successfully'. Catching
    only IntegrityError lets the real failure through.
    """
    from db import db
    from blueprints import live_game_ui
    from models import Game, Team

    client = app.test_client()
    _login(client)
    client.get(f'/api/live-game/{GAME_ID}/next-inning-prep')

    with app.app_context():
        assert len(_prep_rows()) == 1, 'the adoptable row was not created'

        # The request misses the existing row and tries to insert its own...
        _install_stale_first_read(monkeypatch)
        # ...but the commit fails for a reason that is not a constraint.
        boom = RuntimeError('database went away')
        state = _fail_next_commit_with(monkeypatch, app, boom)

        game = db.session.get(Game, GAME_ID)
        team = db.session.get(Team, TEAM_ID)

        with pytest.raises(RuntimeError) as caught:
            live_game_ui._next_inning_context(game, team)

        assert state['raised'], 'the failing commit was never reached'
        assert caught.value is boom, (
            'the recovery swallowed a non-IntegrityError; the except clause is '
            'too broad'
        )
