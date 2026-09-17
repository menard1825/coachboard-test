"""Tests for reusing the already-authorized Game in live state."""

from datetime import datetime

from sqlalchemy import event


def _build_app(monkeypatch):
    monkeypatch.setenv(
        'SECRET_KEY',
        'game-reuse-test',
    )
    monkeypatch.setenv(
        'COACHBOARD_ENV',
        'test',
    )
    monkeypatch.setenv(
        'DATABASE_URL',
        'sqlite:///:memory:',
    )

    from app import create_app
    from db import db
    from models import Game, Team

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()

        team = Team(
            id=1,
            team_name='Game Reuse Team',
            registration_code='game-reuse',
        )
        game = Game(
            id=1,
            date=datetime(2026, 9, 17, 12, 0),
            opponent='Reuse Opponent',
            is_live=True,
            team_id=1,
        )

        db.session.add_all([team, game])
        db.session.commit()

    return app


def _game_selects(statements):
    return [
        sql
        for sql in statements
        if ' from games ' in f' {sql.lower()} '
    ]


def test_authoritative_state_reuses_supplied_game(monkeypatch):
    app = _build_app(monkeypatch)

    from blueprints.live_game_api import (
        get_authoritative_live_state,
    )
    from db import db
    from models import Game

    with app.app_context():
        game = db.session.get(Game, 1)

        statements = []

        def capture(
            conn,
            cursor,
            statement,
            parameters,
            context,
            executemany,
        ):
            statements.append(
                ' '.join(statement.split())
            )

        engine = db.engine
        event.listen(
            engine,
            'before_cursor_execute',
            capture,
        )

        try:
            state = get_authoritative_live_state(
                1,
                1,
                game=game,
            )
        finally:
            event.remove(
                engine,
                'before_cursor_execute',
                capture,
            )

        assert state is not None
        assert state['game']['id'] == 1
        assert len(_game_selects(statements)) == 0


def test_authoritative_state_keeps_query_fallback(monkeypatch):
    app = _build_app(monkeypatch)

    from blueprints.live_game_api import (
        get_authoritative_live_state,
    )
    from db import db

    with app.app_context():
        statements = []

        def capture(
            conn,
            cursor,
            statement,
            parameters,
            context,
            executemany,
        ):
            statements.append(
                ' '.join(statement.split())
            )

        engine = db.engine
        event.listen(
            engine,
            'before_cursor_execute',
            capture,
        )

        try:
            state = get_authoritative_live_state(
                1,
                1,
            )
        finally:
            event.remove(
                engine,
                'before_cursor_execute',
                capture,
            )

        assert state is not None
        assert state['game']['id'] == 1
        assert len(_game_selects(statements)) == 1


def test_authoritative_state_rejects_mismatched_game(monkeypatch):
    app = _build_app(monkeypatch)

    from blueprints.live_game_api import (
        get_authoritative_live_state,
    )
    from db import db
    from models import Game

    with app.app_context():
        game = db.session.get(Game, 1)

        assert (
            get_authoritative_live_state(
                999,
                1,
                game=game,
            )
            is None
        )

        assert (
            get_authoritative_live_state(
                1,
                999,
                game=game,
            )
            is None
        )
