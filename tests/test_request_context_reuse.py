"""Request-scoped authorization context reuse."""

from datetime import datetime

from flask import jsonify, session
from sqlalchemy import event


def _build_app(monkeypatch):
    monkeypatch.setenv(
        'SECRET_KEY',
        'request-context-reuse-test',
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
    from models import Game, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()

        team = Team(
            id=1,
            team_name='Context Team',
            registration_code='context-team',
        )
        user = User(
            id=1,
            username='context-coach',
            email='context@example.com',
            full_name='Context Coach',
            password_hash='not-used',
        )
        membership = TeamMembership(
            id=1,
            user_id=1,
            team_id=1,
            role='Head Coach',
            player_order=[],
        )
        game = Game(
            id=1,
            date=datetime(2026, 9, 17, 12, 0),
            opponent='Context Opponent',
            is_live=True,
            team_id=1,
        )

        db.session.add_all(
            [
                team,
                user,
                membership,
                game,
            ]
        )
        db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'context-coach'
        sess['team_id'] = 1
        sess['role'] = 'Head Coach'


def test_authorized_context_reuses_guard_user_and_membership(
    monkeypatch,
):
    app = _build_app(monkeypatch)

    from blueprints.live_game_api import (
        _authorized_context,
    )
    from db import db

    def probe(game_id):
        user, team, game = _authorized_context(
            game_id
        )

        assert user is not None
        assert team is not None
        assert game is not None

        return jsonify(
            {
                'user_id': user.id,
                'team_id': team.id,
                'game_id': game.id,
            }
        )

    app.add_url_rule(
        '/_test/request-context/<int:game_id>',
        endpoint='request_context_probe',
        view_func=probe,
    )

    client = app.test_client()
    _login(client)

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
            ' '.join(statement.split()).lower()
        )

    with app.app_context():
        engine = db.engine
        event.listen(
            engine,
            'before_cursor_execute',
            capture,
        )

        try:
            response = client.get(
                '/_test/request-context/1'
            )
        finally:
            event.remove(
                engine,
                'before_cursor_execute',
                capture,
            )

    assert response.status_code == 200
    assert response.get_json() == {
        'user_id': 1,
        'team_id': 1,
        'game_id': 1,
    }

    user_queries = [
        sql
        for sql in statements
        if ' from users ' in f' {sql} '
    ]
    membership_queries = [
        sql
        for sql in statements
        if ' from team_memberships ' in f' {sql} '
    ]

    # The security guard still performs the authoritative lookup.
    # _authorized_context() must reuse it instead of doing both again.
    assert len(user_queries) == 1
    assert len(membership_queries) == 1


def test_authorized_context_falls_back_without_guard_cache(
    monkeypatch,
):
    app = _build_app(monkeypatch)

    from blueprints.live_game_api import (
        _authorized_context,
    )

    # Calling the helper directly inside a request context bypasses
    # before_app_request, so flask.g has no cached user/membership.
    # The helper must retain its original database-query behavior.
    with app.test_request_context(
        '/_test/direct-context'
    ):
        session['logged_in'] = True
        session['username'] = 'context-coach'
        session['team_id'] = 1
        session['role'] = 'Head Coach'

        user, team, game = _authorized_context(1)

        assert user is not None
        assert user.id == 1
        assert team is not None
        assert team.id == 1
        assert game is not None
        assert game.id == 1
