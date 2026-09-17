"""Regression budget for the hot live-game state endpoint.

The integrated performance work measured 15 SQL statements for the real
Test App 2 /state path.  The budget intentionally allows two statements of
headroom so normal evolution is not brittle, while preventing a silent
return to the original 18-statement baseline.

The dedicated request-context and Game-reuse tests separately protect the
specific duplicate queries that were removed.
"""

from collections import Counter
from datetime import datetime
from pathlib import Path
import re
import traceback

from sqlalchemy import event


MAX_LIVE_STATE_STATEMENTS = 17

PROJECT_ROOT = Path(__file__).resolve().parents[1]
THIS_TEST = Path(__file__).resolve()


def _build_app(monkeypatch):
    monkeypatch.setenv(
        "SECRET_KEY",
        "live-state-query-budget-test",
    )
    monkeypatch.setenv(
        "COACHBOARD_ENV",
        "test",
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "sqlite:///:memory:",
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
            team_name="Query Budget Team",
            registration_code="query-budget",
        )

        user = User(
            id=1,
            username="budget-coach",
            email="budget@example.com",
            full_name="Budget Coach",
            password_hash="not-used",
        )

        membership = TeamMembership(
            id=1,
            user_id=1,
            team_id=1,
            role="Head Coach",
            player_order=[],
        )

        game = Game(
            id=1,
            date=datetime(2026, 9, 17, 12, 0),
            opponent="Budget Opponent",
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


def _normalize(statement):
    return re.sub(
        r"\s+",
        " ",
        statement,
    ).strip()


def _table_from_sql(statement):
    match = re.search(
        r"\bFROM\s+([a-zA-Z0-9_]+)",
        statement,
        re.IGNORECASE,
    )

    return match.group(1) if match else "<other>"


def _project_origin():
    """Return the nearest CoachBoard call site, excluding this test helper."""

    matches = []

    for frame in traceback.extract_stack():
        try:
            path = Path(frame.filename).resolve()
            relative = path.relative_to(PROJECT_ROOT)
        except (OSError, ValueError):
            continue

        if path == THIS_TEST:
            continue

        relative_text = str(relative)

        if (
            relative_text.startswith(".venv/")
            or relative_text.startswith("venv/")
        ):
            continue

        matches.append(
            f"{relative}:{frame.lineno}:{frame.name}"
        )

    return matches[-1] if matches else "<unknown>"


def test_live_state_stays_within_sql_statement_budget(monkeypatch):
    app = _build_app(monkeypatch)

    from db import db

    client = app.test_client()

    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "budget-coach"
        sess["team_id"] = 1
        sess["role"] = "Head Coach"

    # Warm framework/request machinery outside the measured request.
    warm = client.get("/api/live-game/1/state")

    assert warm.status_code == 200

    statements = []

    def capture(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        sql = _normalize(statement)

        if sql.upper().startswith("PRAGMA "):
            return

        statements.append(
            {
                "sql": sql,
                "table": _table_from_sql(sql),
                "origin": _project_origin(),
            }
        )

    with app.app_context():
        engine = db.engine

        event.listen(
            engine,
            "before_cursor_execute",
            capture,
        )

        try:
            response = client.get(
                "/api/live-game/1/state"
            )
        finally:
            event.remove(
                engine,
                "before_cursor_execute",
                capture,
            )

    assert response.status_code == 200

    table_counts = Counter(
        item["table"]
        for item in statements
    )

    details = "\n".join(
        (
            f"{number:02d}: "
            f"{item['table']:<28} "
            f"{item['origin']}\n"
            f"    {item['sql']}"
        )
        for number, item in enumerate(
            statements,
            start=1,
        )
    )

    summary = ", ".join(
        f"{table}={count}"
        for table, count in sorted(
            table_counts.items()
        )
    )

    assert len(statements) <= MAX_LIVE_STATE_STATEMENTS, (
        "\nLive /state SQL statement budget exceeded.\n"
        f"Budget:   <= {MAX_LIVE_STATE_STATEMENTS}\n"
        f"Observed: {len(statements)}\n"
        f"Tables:   {summary}\n\n"
        "Statements and CoachBoard origins:\n"
        f"{details}"
    )
