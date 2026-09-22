"""SQL budget and response equivalence for GET /api/game-day/<id>/readiness.

Modelled on tests/test_live_state_query_budget.py, which does the same job for
the live /state endpoint.

The audit measured 25 statements for the pregame-ready shape. Deduplicating
the rule queries took it to 23; sharing the roster, absence and rotation loads
between can_start_game() and build_game_readiness() took it to 20; reusing the
already-loaded rotation and events for the actual-game reconstruction took it
to 18. The budget is 19, not 21, on purpose: a looser ceiling would let one of
those duplicate reads come back without failing anything. One statement of
headroom absorbs harmless auth or session changes -- three of the 18 statements
(users, team_memberships, teams) belong to login handling, not to readiness.

The equivalence test deliberately avoids a 33-field golden file. It runs the
endpoint twice: once as shipped, once with rule_settings_payload() monkeypatched
back to its pre-optimisation body, and compares the two responses. That proves
the change is behaviour-preserving without a fixture that has to be
hand-maintained every time an unrelated readiness field is added.
"""

import re
from collections import Counter
from datetime import datetime

import pytest
from sqlalchemy import event
from werkzeug.security import generate_password_hash


MAX_READINESS_STATEMENTS = 19

ALIGNMENT = {
    'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
    '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
    'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
}
NAMES = list(ALIGNMENT.values())

PREGAME_INCOMPLETE = 101
PREGAME_READY = 102
LIVE = 103

# Recomputed per request from the team's clock, so it is the one field that can
# legitimately differ between two calls straddling local midnight.
NON_DETERMINISTIC = {'local_today'}


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'readiness-query-budget-test')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from models import (Game, Lineup, LineupEntry, Player, Rotation, Team,
                        TeamMembership, User)

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(
                id=1,
                team_name='Readiness Budget Team',
                registration_code='readiness-budget-code',
                age_group='11U',
                pitching_rule_set='MLB Pitch Smart',
                outfielder_count=3,
                timezone='America/Indiana/Indianapolis',
            ),
            User(
                id=1,
                username='budget-coach',
                full_name='Budget Coach',
                password_hash=generate_password_hash('password123'),
            ),
        ])
        db.session.flush()
        db.session.add(TeamMembership(
            user_id=1, team_id=1, role='Head Coach', player_order=[]))
        db.session.add_all([
            Player(
                id=index + 1,
                name=name,
                number=str(index + 1),
                team_id=1,
                pitcher_role='Pitcher' if name == 'Pitcher Pat' else 'Not a Pitcher',
            )
            for index, name in enumerate(NAMES)
        ])
        db.session.add(TeamPitchingSettings(
            team_id=1,
            competition_default_rule='USSSA',
            arm_care_rule_set='MLB Pitch Smart',
        ))
        db.session.commit()

        for game_id, complete, with_lineup, is_live in (
            (PREGAME_INCOMPLETE, False, False, False),
            (PREGAME_READY, True, True, False),
            (LIVE, True, True, True),
        ):
            innings = {str(number): dict(ALIGNMENT) for number in range(1, 7)}
            if not complete:
                innings['1'].pop('RF')
                innings['3'] = {}

            db.session.add(Game(
                id=game_id,
                date=datetime(2026, 8, 31, 18, 0, 0),
                start_time='18:00',
                opponent=f'Opponent {game_id}',
                team_id=1,
                is_live=is_live,
                live_current_inning='1',
            ))
            db.session.add(Rotation(
                title=f'Rotation {game_id}',
                innings=innings,
                associated_game_id=game_id,
                team_id=1,
            ))
            if with_lineup:
                lineup = Lineup(title=f'Lineup {game_id}',
                                associated_game_id=game_id, team_id=1)
                db.session.add(lineup)
                db.session.flush()
                for order, name in enumerate(NAMES, start=1):
                    player = db.session.query(Player).filter_by(name=name, team_id=1).first()
                    db.session.add(LineupEntry(
                        lineup_id=lineup.id,
                        player_id=player.id,
                        player_name_snapshot=name,
                        batting_order=order,
                    ))
        db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['user_id'] = 1
        session['team_id'] = 1
        session['username'] = 'budget-coach'
        session['role'] = 'Head Coach'


def _normalize(statement):
    return ' '.join(statement.split())


def _table_of(statement):
    match = re.search(r'\bFROM\s+([a-zA-Z0-9_]+)', statement, re.IGNORECASE)
    return match.group(1) if match else '<other>'


def _measure(app, client, path):
    from db import db

    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith('PRAGMA '):
            return
        statements.append(_normalize(statement))

    with app.app_context():
        engine = db.session.get_bind()
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            response = client.get(path)
        finally:
            event.remove(engine, 'before_cursor_execute', capture)

    return response, statements


def test_readiness_stays_within_sql_statement_budget(monkeypatch, capsys):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    path = f'/api/game-day/{PREGAME_READY}/readiness'

    # Warm framework/request machinery outside the measured request.
    warm = client.get(path)
    assert warm.status_code == 200

    response, statements = _measure(app, client, path)
    assert response.status_code == 200

    writes = [s for s in statements
              if s.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
    table_counts = Counter(_table_of(s) for s in statements)
    detail = '\n'.join(f'  {number:02d} {sql}'
                       for number, sql in enumerate(statements, start=1))
    summary = ', '.join(f'{table}={count}'
                        for table, count in sorted(table_counts.items()))

    with capsys.disabled():
        print(f'\n  /readiness measured SQL statements: {len(statements)} '
              f'(budget <= {MAX_READINESS_STATEMENTS}), writes: {len(writes)}')
        print(f'  tables: {summary}')

    assert writes == [], (
        f'/readiness must be read-only; observed {len(writes)} write(s):\n'
        + '\n'.join(writes)
    )
    assert len(statements) <= MAX_READINESS_STATEMENTS, (
        '\n/api/game-day/<id>/readiness SQL statement budget exceeded.\n'
        f'Budget:   <= {MAX_READINESS_STATEMENTS}\n'
        f'Observed: {len(statements)}\n'
        f'Tables:   {summary}\n\n'
        f'{detail}'
    )


@pytest.mark.parametrize('game_id', [PREGAME_INCOMPLETE, PREGAME_READY, LIVE],
                         ids=['pregame_incomplete', 'pregame_ready', 'live'])
def test_readiness_does_not_reread_its_shared_inputs(monkeypatch, game_id):
    """The duplicate reads removed by earlier slices must not come back.

    Every bound here is a ceiling, never an equality, so a later reduction to
    one or zero lands without editing a regression test.

    Current measurements and what each ceiling catches:

      players               1  -- 2 means the shared roster preload was dropped
      player_game_absences  1  -- 2 means the shared absence preload was dropped
      rotations             1  -- 2 means build_game_readiness() went back to
                                  calling actual_game_rotation(), or the shared
                                  rotation preload was dropped
      game_rotation_events  1  -- 2 means the reconstruction is re-querying
                                  events instead of reusing the loaded list
      game_pitching_rules      2  -- rule_settings_payload + game_rule_context;
      team_pitching_settings   2     3 means the duplicate inside
                                     rule_settings_payload() has returned
    """
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    path = f'/api/game-day/{game_id}/readiness'
    assert client.get(path).status_code == 200

    response, statements = _measure(app, client, path)
    assert response.status_code == 200

    counts = Counter(_table_of(s) for s in statements)
    detail = '\n'.join(f'  {n:02d} {s}' for n, s in enumerate(statements, 1))

    assert counts['players'] <= 1, (
        f'players read {counts["players"]} times; the endpoint loads the roster '
        'once and shares it between can_start_game() and build_game_readiness(). '
        'More than one means a shared preload was dropped.\n'
        f'{detail}'
    )
    assert counts['player_game_absences'] <= 1, (
        f'player_game_absences read {counts["player_game_absences"]} times; the '
        'endpoint loads absences once and shares them. More than one means a '
        'shared preload was dropped.\n'
        f'{detail}'
    )
    assert counts['rotations'] <= 1, (
        f'rotations read {counts["rotations"]} times; the endpoint loads the '
        'rotation once and the actual-game reconstruction reuses it. More than '
        'one means the preload was dropped or build_game_readiness() is calling '
        'actual_game_rotation() again.\n'
        f'{detail}'
    )
    assert counts['game_rotation_events'] <= 1, (
        f'game_rotation_events read {counts["game_rotation_events"]} times; '
        'build_game_readiness() loads the events once and the reconstruction '
        'reuses that list. More than one means it is re-querying them.\n'
        f'{detail}'
    )
    assert counts['game_pitching_rules'] <= 2, (
        f'game_pitching_rules read {counts["game_pitching_rules"]} times; at most 2 '
        'are expected (rule_settings_payload + game_rule_context). More than that '
        'means the duplicate read inside rule_settings_payload() is back.\n'
        f'{detail}'
    )
    assert counts['team_pitching_settings'] <= 2, (
        f'team_pitching_settings read {counts["team_pitching_settings"]} times; at '
        'most 2 are expected (rule_settings_payload + game_rule_context). More than '
        'that means the duplicate read inside rule_settings_payload() is back.\n'
        f'{detail}'
    )


def _reference_rule_settings_payload(team, game=None):
    """rule_settings_payload() exactly as it was before the slice.

    Kept as an oracle, not as production code: it derives `effective` through
    effective_rule_set_name(), which re-queries the rule tables. If this and
    the shipped helper ever disagree, the optimisation changed behaviour.
    """
    from blueprints.fair_play import pitching_preferences_for_team
    from game_pitching_rules import (RULE_SET_OPTIONS, effective_rule_set_name,
                                     game_rule_override)

    override = game_rule_override(game.id, team.id) if game is not None else None
    preferences = pitching_preferences_for_team(team)
    team_default = preferences['competition_default_rule']
    effective = effective_rule_set_name(team, game)
    if override:
        source = 'game'
    elif team_default:
        source = 'team'
    else:
        source = 'unselected'
    return {
        'team_default': team_default,
        'override': override.rule_set if override else None,
        'effective': effective,
        'source': source,
        'options': list(RULE_SET_OPTIONS),
        'arm_care_rule_set': preferences['arm_care_rule_set'],
    }


@pytest.mark.parametrize('game_id', [PREGAME_INCOMPLETE, PREGAME_READY, LIVE],
                         ids=['pregame_incomplete', 'pregame_ready', 'live'])
def test_readiness_response_is_unchanged_by_the_optimisation(monkeypatch, game_id):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    path = f'/api/game-day/{game_id}/readiness'

    shipped = client.get(path).get_json()

    monkeypatch.setattr('game_start_readiness.rule_settings_payload',
                        _reference_rule_settings_payload)
    monkeypatch.setattr('blueprints.game_day.rule_settings_payload',
                        _reference_rule_settings_payload)
    reference = client.get(path).get_json()

    assert sorted(shipped) == ['missing', 'readiness', 'ready', 'status']
    assert shipped['status'] == reference['status'] == 'success'
    assert shipped['ready'] == reference['ready']
    assert shipped['missing'] == reference['missing']

    # Whole nested object, minus only the clock-dependent field, which is
    # still required to be present and identically shaped.
    assert set(shipped['readiness']) == set(reference['readiness'])
    for field in NON_DETERMINISTIC:
        assert field in shipped['readiness']
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', shipped['readiness'][field])

    compared = {k: v for k, v in shipped['readiness'].items()
                if k not in NON_DETERMINISTIC}
    expected = {k: v for k, v in reference['readiness'].items()
                if k not in NON_DETERMINISTIC}
    assert compared == expected
    assert len(compared) >= 32, (
        f'only {len(compared)} readiness fields compared; the nested payload '
        'should be almost entirely deterministic'
    )


def _ignoring_preloads(func):
    """Wrap a readiness calculator so it discards the endpoint's preloads.

    This restores the pre-shared-inputs behaviour through the real HTTP
    endpoint: both calculators query the roster, absences and rotation for
    themselves again. Comparing the two responses proves sharing the loads
    changed nothing observable, without a hand-maintained golden payload.
    """
    def wrapper(*args, **kwargs):
        for key in ('roster', 'absences', 'rotation'):
            kwargs.pop(key, None)
        return func(*args, **kwargs)
    return wrapper


@pytest.mark.parametrize('game_id', [PREGAME_INCOMPLETE, PREGAME_READY, LIVE],
                         ids=['pregame_incomplete', 'pregame_ready', 'live'])
def test_readiness_response_is_unchanged_by_sharing_the_inputs(monkeypatch, game_id):
    import blueprints.game_day as game_day

    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    path = f'/api/game-day/{game_id}/readiness'

    shipped = client.get(path).get_json()

    monkeypatch.setattr(game_day, 'can_start_game',
                        _ignoring_preloads(game_day.can_start_game))
    monkeypatch.setattr(game_day, 'build_game_readiness',
                        _ignoring_preloads(game_day.build_game_readiness))
    reference = client.get(path).get_json()

    assert sorted(shipped) == ['missing', 'readiness', 'ready', 'status']
    assert shipped['status'] == reference['status'] == 'success'
    assert shipped['ready'] == reference['ready']
    assert shipped['missing'] == reference['missing']

    assert set(shipped['readiness']) == set(reference['readiness'])
    for field in NON_DETERMINISTIC:
        assert field in shipped['readiness']
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', shipped['readiness'][field])

    compared = {k: v for k, v in shipped['readiness'].items()
                if k not in NON_DETERMINISTIC}
    expected = {k: v for k, v in reference['readiness'].items()
                if k not in NON_DETERMINISTIC}
    assert compared == expected
    assert len(compared) >= 32, (
        f'only {len(compared)} readiness fields compared; the nested payload '
        'should be almost entirely deterministic'
    )


@pytest.mark.parametrize('game_id', [PREGAME_INCOMPLETE, PREGAME_READY, LIVE],
                         ids=['pregame_incomplete', 'pregame_ready', 'live'])
def test_discarding_the_preloads_makes_both_calculators_load_again(monkeypatch, game_id):
    """Proves the equivalence oracle above really does bypass the sharing.

    Without this, _ignoring_preloads() could quietly stop working and the
    equivalence test would be comparing the new implementation against itself.

    The oracle is not a byte-for-byte replay of the pre-slice endpoint: it
    discards the preloads but the endpoint still performs its three (now
    unused) loads, so each shared table is read three times rather than two.
    That is exactly the signal wanted here -- the point is that both
    calculators go back to loading for themselves.
    """
    import blueprints.game_day as game_day

    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    path = f'/api/game-day/{game_id}/readiness'
    assert client.get(path).status_code == 200

    _, shared = _measure(app, client, path)

    monkeypatch.setattr(game_day, 'can_start_game',
                        _ignoring_preloads(game_day.can_start_game))
    monkeypatch.setattr(game_day, 'build_game_readiness',
                        _ignoring_preloads(game_day.build_game_readiness))
    assert client.get(path).status_code == 200
    _, unshared = _measure(app, client, path)

    shared_counts = Counter(_table_of(item) for item in shared)
    unshared_counts = Counter(_table_of(item) for item in unshared)

    # One shared load each, versus one endpoint load plus one per calculator.
    assert shared_counts['players'] == 1
    assert unshared_counts['players'] == 3
    assert shared_counts['player_game_absences'] == 1
    assert unshared_counts['player_game_absences'] == 3
    # The actual-game reconstruction reuses the loaded rotation in both cases,
    # so this tracks the shared preload alone.
    assert shared_counts['rotations'] == 1
    assert unshared_counts['rotations'] == 3

    assert len(unshared) == len(shared) + 6, (
        f'shared={len(shared)} unshared={len(unshared)}; discarding the preloads '
        'should add two extra reads for each of the three shared inputs'
    )
