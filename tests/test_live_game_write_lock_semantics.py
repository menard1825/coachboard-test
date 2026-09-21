"""Guardrail: the live-game optimistic-version contract.

Every bulk live-game write is version-checked. The version is the sequence
number of the latest live rotation event, and an event that has been undone
must not count -- that is what makes an Undo invalidate an editor a second
coach opened before it, instead of letting their stale save silently overwrite
the undo.

Nothing tested that. These tests do, entirely through observable behaviour:
they exercise the sequence the bulk-write path actually computes and the 409
that ``_stale_write_response`` returns.

They are deliberately indifferent to *where* that implementation lives. At
1a06777 ``live_game_write_lock`` rebinds ``live_game_bulk_api._current_sequence``
at import time, and the definition written in ``live_game_bulk_api.py`` is
shadowed and wrong. When a later slice de-shadows it -- moving the corrected
implementation into ``live_game_bulk_api`` and deleting the patch -- every test
here should keep passing unchanged. That is the point: the guardrail protects
the behaviour, not the current arrangement of it.
"""

from datetime import datetime

import pytest
from werkzeug.security import generate_password_hash

from guardrail_support import build_app


TEAM_ID = 1
GAME_ID = 1


@pytest.fixture(name='app')
def _app(monkeypatch):
    app = build_app(monkeypatch)

    from db import db
    from models import Game, Team, TeamMembership, User

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
            live_current_inning='2',
        ))
        db.session.commit()

    return app


def _add_event(sequence, inning='1', reverted=False, alignment=None):
    from db import db
    from models import GameRotationEvent

    event = GameRotationEvent(
        game_id=GAME_ID,
        team_id=TEAM_ID,
        inning=inning,
        sequence=sequence,
        event_type='Defensive Change',
        reverted=reverted,
        after_alignment=alignment or {'P': 'Alex'},
    )
    db.session.add(event)
    db.session.commit()
    return event


def _game():
    from db import db
    from models import Game

    return db.session.get(Game, GAME_ID)


def _team():
    from db import db
    from models import Team

    return db.session.get(Team, TEAM_ID)


def _effective_sequence(game_id, team_id):
    """The live version number as the bulk-write path computes it.

    Resolved through the module attribute rather than a direct import so these
    tests describe behaviour, not wiring. They pass today, where
    ``live_game_write_lock`` rebinds this name at import, and they will keep
    passing once that patch is removed and the corrected implementation lives
    in ``live_game_bulk_api`` directly.
    """
    from blueprints import live_game_bulk_api

    return live_game_bulk_api._current_sequence(game_id, team_id)


# --------------------------------------------------------------------------
# Effective sequence behaviour
# --------------------------------------------------------------------------

def test_effective_sequence_is_zero_with_no_events(app):
    with app.app_context():
        assert _effective_sequence(GAME_ID, TEAM_ID) == 0


def test_effective_sequence_tracks_the_latest_live_event(app):
    with app.app_context():
        _add_event(sequence=1)
        assert _effective_sequence(GAME_ID, TEAM_ID) == 1

        _add_event(sequence=2)
        assert _effective_sequence(GAME_ID, TEAM_ID) == 2


def test_effective_sequence_excludes_reverted_events(app):
    """An undone event must not count toward the live version."""
    with app.app_context():
        _add_event(sequence=1)
        _add_event(sequence=2)
        _add_event(sequence=3, reverted=True)

        assert _effective_sequence(GAME_ID, TEAM_ID) == 2


def test_effective_sequence_ignores_other_games_and_teams(app):
    from db import db
    from models import Game, GameRotationEvent

    with app.app_context():
        _add_event(sequence=1)

        db.session.add(Game(
            id=2,
            team_id=TEAM_ID,
            date=datetime(2026, 9, 22, 10, 0, 0),
            opponent='Other',
            is_live=True,
            live_current_inning='1',
        ))
        db.session.commit()
        db.session.add(GameRotationEvent(
            game_id=2,
            team_id=TEAM_ID,
            inning='1',
            sequence=99,
            event_type='Defensive Change',
            reverted=False,
            after_alignment={},
        ))
        db.session.commit()

        assert _effective_sequence(GAME_ID, TEAM_ID) == 1


# --------------------------------------------------------------------------
# The behaviour that matters to a coach: Undo invalidates a stale editor
# --------------------------------------------------------------------------

def test_undo_makes_an_older_editor_stale(app):
    """Two coaches, one Undo.

    Coach B opened the live field while events 1 and 2 existed, so their editor
    holds base_sequence=2. Coach A then undoes event 2. Coach B's save must be
    rejected as stale rather than silently overwriting the undo.

    This goes through ``_stale_write_response`` -- the real call site used by
    every bulk write -- not through the sequence function directly.
    """
    from blueprints import live_game_bulk_api

    with app.app_context():
        _add_event(sequence=1)
        undone = _add_event(sequence=2)

        with app.test_request_context():
            # Before the undo, coach B's version is current.
            assert live_game_bulk_api._stale_write_response(
                {'base_sequence': 2}, _game(), _team(),
            ) is None

        # Coach A undoes event 2.
        undone.reverted = True
        from db import db
        db.session.commit()

        with app.test_request_context():
            stale = live_game_bulk_api._stale_write_response(
                {'base_sequence': 2}, _game(), _team(),
            )

            assert stale is not None, (
                'an editor opened before the Undo was accepted as current; '
                'the undo can be silently overwritten'
            )
            response, status = stale
            assert status == 409
            payload = response.get_json()
            assert payload['code'] == 'stale_live_state'
            assert payload['current_sequence'] == 1


def test_a_current_editor_is_not_rejected_after_an_unrelated_revert(app):
    """The guard must not become a blanket rejection.

    A coach who reloads after the undo holds base_sequence=1 and must be
    allowed to save.
    """
    from blueprints import live_game_bulk_api
    from db import db

    with app.app_context():
        _add_event(sequence=1)
        undone = _add_event(sequence=2)
        undone.reverted = True
        db.session.commit()

        with app.test_request_context():
            assert live_game_bulk_api._stale_write_response(
                {'base_sequence': 1}, _game(), _team(),
            ) is None


def test_missing_base_sequence_is_rejected_with_the_effective_version(app):
    """A client that sends no version is told the *effective* one."""
    from blueprints import live_game_bulk_api

    with app.app_context():
        _add_event(sequence=1)
        _add_event(sequence=2, reverted=True)

        with app.test_request_context():
            response, status = live_game_bulk_api._stale_write_response(
                {}, _game(), _team(),
            )

            assert status == 409
            payload = response.get_json()
            assert payload['code'] == 'missing_live_state_version'
            assert payload['current_sequence'] == 1
