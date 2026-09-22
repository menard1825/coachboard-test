"""Sharing one resolved rule payload across /readiness's two calculators.

can_start_game() needs the game's effective pitching rule to answer the
first-pitch question, and build_game_readiness() needs it entered as a context
so the legacy calculators see it. Each used to resolve it independently --
through rule_settings_payload() and through game_rule_context() -- so one
request read game_pitching_rules and team_pitching_settings twice each.

readiness_api() now resolves it once and hands the same dict to both. The
payload is a plain local, resolved from the game it is immediately used for:
nothing is memoized on g, the Team, the Game, a module global, or anything else
that outlives the call.

Everything else keeps the old path. /api/live-game/<id>/start still calls
can_start_game(game, team) bare, and the four other _readiness_for_game()
callers still go through game_rule_context().
"""

import json
import re
from collections import Counter
from datetime import datetime

import pytest
from sqlalchemy import event as sa_event, text
from werkzeug.security import generate_password_hash


ALIGNMENT = {
    'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
    '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
    'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
}
NAMES = list(ALIGNMENT.values())

INCOMPLETE, READY, LIVE = 901, 902, 903
FIXTURES = [('pregame_incomplete', INCOMPLETE), ('pregame_ready', READY), ('live', LIVE)]

SEEDED_TEAM_RULE = 'MLB Pitch Smart'

# (label, override rule_set stored on the game, team competition default)
RULE_STATES = [
    ('no override + valid team default', None, 'USSSA'),
    ('no override + no default', None, None),
    ('valid override + team default', 'MLB Pitch Smart', 'USSSA'),
    ('valid override + no default', 'MLB Pitch Smart', None),
    ('override equal to default', 'USSSA', 'USSSA'),
    ('invalid override + valid default', 'Not A Real Rule', 'USSSA'),
    ('invalid override + no default', 'Not A Real Rule', None),
]
STATE_IDS = [state[0] for state in RULE_STATES]

# The two states where no competition rule ends up selected. They legitimately
# read team_pitching_settings a second time, because request_aware_gameplay_rules()
# falls back to the arm-care preference when the competition rule is None.
UNSELECTED_STATES = {'no override + no default', 'invalid override + no default'}

# effective / source each state must produce. The two invalid-override rows are
# the pre-existing asymmetry: effective falls back, source stays 'game'.
EXPECTED_RULE = {
    'no override + valid team default': ('USSSA', 'team'),
    'no override + no default': (None, 'unselected'),
    'valid override + team default': ('MLB Pitch Smart', 'game'),
    'valid override + no default': ('MLB Pitch Smart', 'game'),
    'override equal to default': ('USSSA', 'game'),
    'invalid override + valid default': ('USSSA', 'game'),
    'invalid override + no default': (None, 'game'),
}

NON_DETERMINISTIC = {'local_today'}


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'readiness-rule-context-test')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import (Game, Lineup, LineupEntry, Player, Rotation, Team,
                        TeamMembership, User)

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(id=1, team_name='Rule Context Team',
                 registration_code='rule-context-code', age_group='11U',
                 pitching_rule_set=SEEDED_TEAM_RULE, outfielder_count=3,
                 timezone='America/Indiana/Indianapolis'),
            User(id=1, username='rule-context-coach', full_name='Rule Coach',
                 password_hash=generate_password_hash('password123')),
        ])
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=1, role='Head Coach',
                                      player_order=[]))
        db.session.add_all([
            Player(id=index + 1, name=name, number=str(index + 1), team_id=1,
                   pitcher_role='Pitcher')
            for index, name in enumerate(NAMES)
        ])
        for game_id, complete, with_lineup, is_live in (
            (INCOMPLETE, False, False, False),
            (READY, True, True, False),
            (LIVE, True, True, True),
        ):
            innings = {str(n): dict(ALIGNMENT) for n in range(1, 7)}
            if not complete:
                innings['1'].pop('RF')
                innings['3'] = {}
            db.session.add(Game(
                id=game_id, date=datetime(2026, 8, 31, 18, 0, 0),
                start_time='18:00', opponent=f'Opponent {game_id}', team_id=1,
                is_live=is_live, live_current_inning='1'))
            db.session.add(Rotation(
                title=f'Rotation {game_id}', innings=innings,
                associated_game_id=game_id, team_id=1))
            if with_lineup:
                lineup = Lineup(title=f'Lineup {game_id}',
                                associated_game_id=game_id, team_id=1)
                db.session.add(lineup)
                db.session.flush()
                for order, name in enumerate(NAMES, start=1):
                    player = db.session.query(Player).filter_by(name=name).first()
                    db.session.add(LineupEntry(
                        lineup_id=lineup.id, player_id=player.id,
                        player_name_snapshot=name, batting_order=order))
        db.session.commit()

    return app


def _set_rule_state(override_rule, team_default, game_ids=None):
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from game_pitching_rules import GamePitchingRule

    db.session.query(GamePitchingRule).delete()
    db.session.query(TeamPitchingSettings).delete()
    if override_rule is not None:
        for game_id in (game_ids or (INCOMPLETE, READY, LIVE)):
            db.session.add(GamePitchingRule(rule_set=override_rule,
                                            game_id=game_id, team_id=1))
    db.session.add(TeamPitchingSettings(
        team_id=1, competition_default_rule=team_default,
        arm_care_rule_set='MLB Pitch Smart'))
    db.session.commit()
    db.session.expire_all()


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['user_id'] = 1
        session['team_id'] = 1
        session['username'] = 'rule-context-coach'
        session['role'] = 'Head Coach'


def _table_of(statement):
    match = re.search(r'\bFROM\s+([a-zA-Z0-9_]+)', statement, re.IGNORECASE)
    return match.group(1) if match else '<other>'


def _measure(app, call):
    from db import db

    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if not statement.strip().upper().startswith('PRAGMA '):
            statements.append(statement)

    with app.app_context():
        engine = db.session.get_bind()
    sa_event.listen(engine, 'before_cursor_execute', capture)
    try:
        result = call()
    finally:
        sa_event.remove(engine, 'before_cursor_execute', capture)

    writes = [s for s in statements
              if s.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
    return result, statements, Counter(_table_of(s) for s in statements), writes


def _unshared(game_day):
    """Wrap the endpoint's collaborators so they resolve rules for themselves.

    This is the pre-change path exercised through the real endpoint: the
    payload readiness_api() computes is simply discarded, so can_start_game()
    falls back to rule_settings_payload() and _readiness_for_game() falls back
    to game_rule_context().
    """
    original_can_start = game_day.can_start_game
    original_readiness = game_day._readiness_for_game

    def can_start(*args, **kwargs):
        kwargs.pop('rule_payload', None)
        return original_can_start(*args, **kwargs)

    def readiness(*args, **kwargs):
        kwargs.pop('rule_payload', None)
        return original_readiness(*args, **kwargs)

    return can_start, readiness


# --- seven states x three fixtures ---------------------------------------

@pytest.mark.parametrize('label,override,default', RULE_STATES, ids=STATE_IDS)
@pytest.mark.parametrize('fixture,game_id', FIXTURES, ids=[f[0] for f in FIXTURES])
def test_shared_rule_payload_matches_the_unshared_path(
    monkeypatch, label, override, default, fixture, game_id
):
    import blueprints.game_day as game_day
    from game_pitching_rules import rule_settings_payload
    from models import Game, Team
    from db import db

    app = _build_app(monkeypatch)
    with app.app_context():
        # The override is applied to the game under test only, so the other two
        # games resolve differently. That is deliberate: if every game shared a
        # rule state, a payload accidentally resolved from the wrong game would
        # be indistinguishable and this matrix would not notice.
        _set_rule_state(override, default, game_ids=[game_id])

    client = app.test_client()
    _login(client)
    path = f'/api/game-day/{game_id}/readiness'

    shipped = client.get(path)

    can_start, readiness = _unshared(game_day)
    monkeypatch.setattr(game_day, 'can_start_game', can_start)
    monkeypatch.setattr(game_day, '_readiness_for_game', readiness)
    reference = client.get(path)

    assert shipped.status_code == reference.status_code == 200
    got, want = shipped.get_json(), reference.get_json()

    assert sorted(got) == ['missing', 'readiness', 'ready', 'status']
    assert got['status'] == want['status'] == 'success'
    assert got['ready'] == want['ready']
    assert got['missing'] == want['missing']

    assert set(got['readiness']) == set(want['readiness'])
    compared = {k: v for k, v in got['readiness'].items() if k not in NON_DETERMINISTIC}
    expected = {k: v for k, v in want['readiness'].items() if k not in NON_DETERMINISTIC}
    assert compared == expected
    assert len(compared) >= 32

    # The full rule payload, including the fields the response never exposes.
    with app.app_context():
        db.session.expire_all()
        payload = rule_settings_payload(db.session.get(Team, 1),
                                        db.session.get(Game, game_id))
        # A sibling game without this game's override: the response above must
        # reflect `payload`, not this one.
        other_id = next(gid for _, gid in FIXTURES if gid != game_id)
        other_payload = rule_settings_payload(db.session.get(Team, 1),
                                              db.session.get(Game, other_id))
    from game_pitching_rules import RULE_SET_OPTIONS
    if override in RULE_SET_OPTIONS and override != default:
        # Only a *valid* override that differs from the team default makes this
        # game's effective rule differ from its siblings'. An invalid override
        # falls back to the team default, so it legitimately coincides.
        assert other_payload['effective'] != payload['effective'], (
            'the fixtures must differ so a cross-game payload is detectable'
        )
    want_effective, want_source = EXPECTED_RULE[label]
    assert payload['effective'] == want_effective
    assert payload['source'] == want_source
    assert payload['team_default'] == default
    assert payload['override'] == override
    assert payload['arm_care_rule_set'] == 'MLB Pitch Smart'
    assert payload['options'] == list(RULE_SET_OPTIONS)


@pytest.mark.parametrize('label,override,default',
                         [s for s in RULE_STATES if s[0].startswith('invalid')],
                         ids=[s[0] for s in RULE_STATES if s[0].startswith('invalid')])
def test_invalid_override_keeps_source_game_with_a_fallback_effective(
    monkeypatch, label, override, default
):
    """The pre-existing asymmetry, pinned through the live endpoint path."""
    from game_pitching_rules import rule_settings_payload
    from db import db
    from models import Game, Team

    app = _build_app(monkeypatch)
    with app.app_context():
        _set_rule_state(override, default)
        payload = rule_settings_payload(db.session.get(Team, 1),
                                        db.session.get(Game, READY))

    assert payload['override'] == 'Not A Real Rule'
    assert payload['source'] == 'game'
    assert payload['effective'] == (default if default else None)


# --- effective=None parity ------------------------------------------------

def test_rule_name_context_none_matches_unselected_game_rule_context(monkeypatch):
    from flask import g
    from db import db
    from game_pitching_rules import (_CONTEXT_ATTR, effective_rule_set_name,
                                     game_rule_context, rule_name_context)
    from models import Game, Team
    from utils import get_pitching_rules_for_team

    app = _build_app(monkeypatch)
    with app.test_request_context('/'):
        _set_rule_state(None, None)
        team = db.session.get(Team, 1)
        game = db.session.get(Game, READY)
        assert effective_rule_set_name(team, game) is None

        seeded = team.pitching_rule_set

        with game_rule_context(team, game):
            old = (getattr(g, _CONTEXT_ATTR, '<absent>'), team.pitching_rule_set,
                   json.dumps(get_pitching_rules_for_team(team), sort_keys=True,
                              default=str))
        old_after = (team.pitching_rule_set, hasattr(g, _CONTEXT_ATTR))

        with rule_name_context(team, None):
            new = (getattr(g, _CONTEXT_ATTR, '<absent>'), team.pitching_rule_set,
                   json.dumps(get_pitching_rules_for_team(team), sort_keys=True,
                              default=str))
        new_after = (team.pitching_rule_set, hasattr(g, _CONTEXT_ATTR))

    assert old == new
    assert old[0] is None and old[1] is None
    assert old_after == new_after
    assert old_after == (seeded, False)


# --- nested contexts ------------------------------------------------------

def test_inner_context_restores_the_surrounding_one(monkeypatch):
    from flask import g
    from db import db
    from game_pitching_rules import (_CONTEXT_ATTR, effective_rule_set_name,
                                     game_rule_context, rule_name_context)
    from models import Game, Team

    app = _build_app(monkeypatch)
    with app.test_request_context('/'):
        _set_rule_state(None, 'USSSA')
        team = db.session.get(Team, 1)
        game = db.session.get(Game, READY)

        with rule_name_context(team, 'MLB Pitch Smart'):
            outer = (getattr(g, _CONTEXT_ATTR), team.pitching_rule_set)

            with game_rule_context(team, game):
                inner_old = (getattr(g, _CONTEXT_ATTR), team.pitching_rule_set)
            restored_old = (getattr(g, _CONTEXT_ATTR), team.pitching_rule_set)

            with rule_name_context(team, effective_rule_set_name(team, game)):
                inner_new = (getattr(g, _CONTEXT_ATTR), team.pitching_rule_set)
            restored_new = (getattr(g, _CONTEXT_ATTR), team.pitching_rule_set)

    assert outer == ('MLB Pitch Smart', 'MLB Pitch Smart')
    assert inner_old == inner_new == ('USSSA', 'USSSA')
    assert restored_old == restored_new == outer


def test_outermost_context_removes_the_g_attribute(monkeypatch):
    from flask import g
    from db import db
    from game_pitching_rules import _CONTEXT_ATTR, game_rule_context, rule_name_context
    from models import Game, Team

    app = _build_app(monkeypatch)
    with app.test_request_context('/'):
        _set_rule_state(None, 'USSSA')
        team = db.session.get(Team, 1)
        game = db.session.get(Game, READY)

        assert not hasattr(g, _CONTEXT_ATTR)
        with game_rule_context(team, game):
            assert hasattr(g, _CONTEXT_ATTR)
        after_old = hasattr(g, _CONTEXT_ATTR)

        with rule_name_context(team, 'USSSA'):
            assert hasattr(g, _CONTEXT_ATTR)
        after_new = hasattr(g, _CONTEXT_ATTR)

    assert after_old is False
    assert after_new is False


# --- no writes ------------------------------------------------------------

def test_rule_name_context_never_writes_the_team_row(monkeypatch):
    """Non-vacuous: the context value differs from the seeded value.

    set_committed_value() marks the attribute as already-persisted, so the
    Team never becomes dirty and no UPDATE is emitted even across a flush. A
    version of this test that entered the context with the seeded value would
    pass regardless.
    """
    from db import db
    from game_pitching_rules import rule_name_context
    from models import Team

    app = _build_app(monkeypatch)
    with app.test_request_context('/'):
        team = db.session.get(Team, 1)
        seeded = team.pitching_rule_set
        context_value = 'USSSA'
        assert context_value != seeded, 'the check would be vacuous'

        def body():
            with rule_name_context(team, context_value):
                assert team.pitching_rule_set == context_value
                db.session.flush()
            return None

        _, statements, _, writes = _measure(app, body)

        assert writes == [], statements
        assert statements == [], statements
        assert team.pitching_rule_set == seeded
        assert team not in db.session.dirty
        raw = db.session.execute(
            text('SELECT pitching_rule_set FROM teams WHERE id = 1')).scalar()
        assert raw == seeded


# --- /start isolation -----------------------------------------------------

START_CASES = [
    ('successful team-default start', None, 'USSSA', 200),
    ('missing rule -> 409', None, None, 409),
    ('valid game override', 'MLB Pitch Smart', 'USSSA', 200),
    ('invalid override fallback', 'Not A Real Rule', 'USSSA', 200),
    ('valid override + no team default', 'MLB Pitch Smart', None, 200),
]


@pytest.mark.parametrize('label,override,default,expected_status', START_CASES,
                         ids=[case[0] for case in START_CASES])
def test_start_passes_no_preloads_to_can_start_game(
    monkeypatch, label, override, default, expected_status
):
    import blueprints.live_game_api as live_game_api
    from db import db
    from models import Game

    app = _build_app(monkeypatch)
    with app.app_context():
        _set_rule_state(override, default)
        game = db.session.get(Game, READY)
        game.is_live = False
        db.session.commit()

    seen = []
    original = live_game_api.can_start_game

    def spy(*args, **kwargs):
        seen.append(dict(kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(live_game_api, 'can_start_game', spy)

    client = app.test_client()
    _login(client)
    response = client.post(f'/api/live-game/{READY}/start', json={})

    assert response.status_code == expected_status, response.get_data(as_text=True)
    assert seen == [{}], f'/start passed preloads: {seen}'

    payload = response.get_json()
    if expected_status == 409:
        assert payload['ready'] is False
        assert 'Select the game pitching rules / tracking method.' in payload['missing']
    else:
        assert payload['ready'] is True
        assert payload['state']['game']['is_live'] is True


def test_can_start_game_without_a_payload_reads_the_rule_tables(monkeypatch):
    from db import db
    from game_start_readiness import can_start_game
    from models import Game, Team

    app = _build_app(monkeypatch)
    with app.app_context():
        _set_rule_state(None, 'USSSA')
        team = db.session.get(Team, 1)
        game = db.session.get(Game, READY)
        team.team_name, game.opponent

        _, statements, counts, _ = _measure(
            app, lambda: can_start_game(game, team))

    assert counts['game_pitching_rules'] == 1, statements
    assert counts['team_pitching_settings'] == 1, statements


def test_can_start_game_with_a_payload_skips_the_rule_tables(monkeypatch):
    from db import db
    from game_pitching_rules import rule_settings_payload
    from game_start_readiness import can_start_game
    from models import Game, Team

    app = _build_app(monkeypatch)
    with app.app_context():
        _set_rule_state(None, 'USSSA')
        team = db.session.get(Team, 1)
        game = db.session.get(Game, READY)
        payload = rule_settings_payload(team, game)
        team.team_name, game.opponent

        result, statements, counts, _ = _measure(
            app, lambda: can_start_game(game, team, rule_payload=payload))

    assert counts['game_pitching_rules'] == 0, statements
    assert counts['team_pitching_settings'] == 0, statements
    assert result['ready'] is True


# --- other _readiness_for_game callers ------------------------------------

def test_other_readiness_callers_still_use_game_rule_context(monkeypatch):
    """The game-day home cards and the game report must not be affected.

    Proven by counting: without a payload the rule tables are read for the
    context as well as (inside can_start_game's absence) nothing else, so the
    game_rule_context() lookup is still happening.
    """
    import blueprints.game_day as game_day
    from db import db
    from models import Game, Team

    app = _build_app(monkeypatch)
    seen = []
    original = game_day.game_rule_context

    def spy(team, game):
        seen.append(game.id)
        return original(team, game)

    monkeypatch.setattr(game_day, 'game_rule_context', spy)

    with app.app_context():
        _set_rule_state(None, 'USSSA')
        team = db.session.get(Team, 1)
        game = db.session.get(Game, READY)
        game_day._readiness_for_game(game, team)

    assert seen == [READY], 'a payload-free caller must go through game_rule_context()'


def test_supplying_a_payload_bypasses_game_rule_context(monkeypatch):
    import blueprints.game_day as game_day
    from db import db
    from game_pitching_rules import rule_settings_payload
    from models import Game, Team

    app = _build_app(monkeypatch)
    seen = []
    original = game_day.game_rule_context

    def spy(team, game):
        seen.append(game.id)
        return original(team, game)

    monkeypatch.setattr(game_day, 'game_rule_context', spy)

    with app.app_context():
        _set_rule_state(None, 'USSSA')
        team = db.session.get(Team, 1)
        game = db.session.get(Game, READY)
        payload = rule_settings_payload(team, game)
        game_day._readiness_for_game(game, team, rule_payload=payload)

    assert seen == []


def test_game_day_home_and_report_views_render(monkeypatch):
    """The four payload-free callers still work end to end."""
    app = _build_app(monkeypatch)
    with app.app_context():
        _set_rule_state(None, 'USSSA')

    client = app.test_client()
    _login(client)

    assert client.get('/game-day').status_code == 200
    assert client.get(f'/game-day/{READY}/report').status_code == 200


# --- SQL counts -----------------------------------------------------------

@pytest.mark.parametrize('fixture,game_id,expected', [
    ('pregame_incomplete', INCOMPLETE, 15),
    ('pregame_ready', READY, 16),
    ('live', LIVE, 16),
], ids=['pregame_incomplete', 'pregame_ready', 'live'])
def test_selected_rule_endpoint_sql_counts(monkeypatch, fixture, game_id, expected, capsys):
    app = _build_app(monkeypatch)
    with app.app_context():
        _set_rule_state(None, 'USSSA')

    client = app.test_client()
    _login(client)
    path = f'/api/game-day/{game_id}/readiness'
    assert client.get(path).status_code == 200

    response, statements, counts, writes = _measure(app, lambda: client.get(path))

    with capsys.disabled():
        print(f'\n  [selected rule] {fixture}: {len(statements)} statements, '
              f'gpr={counts["game_pitching_rules"]}, '
              f'tps={counts["team_pitching_settings"]}, writes={len(writes)}')

    assert response.status_code == 200
    assert len(statements) == expected, '\n'.join(statements)
    assert counts['game_pitching_rules'] <= 1
    assert counts['team_pitching_settings'] <= 1
    assert writes == []


def test_unselected_rule_endpoint_justifies_the_budget_headroom(monkeypatch, capsys):
    """Why the budget is 17 rather than 16.

    With no competition rule selected, request_aware_gameplay_rules() reads the
    team preferences a second time to find the arm-care fallback. That is a
    pre-existing read in the unselected path, not a duplicate this slice left
    behind, and it is the one statement of headroom the budget allows for.
    """
    app = _build_app(monkeypatch)
    with app.app_context():
        _set_rule_state(None, None)

    client = app.test_client()
    _login(client)
    path = f'/api/game-day/{READY}/readiness'
    assert client.get(path).status_code == 200

    response, statements, counts, writes = _measure(app, lambda: client.get(path))

    with capsys.disabled():
        print(f'\n  [unselected rule] pregame_ready: {len(statements)} statements, '
              f'gpr={counts["game_pitching_rules"]}, '
              f'tps={counts["team_pitching_settings"]}, writes={len(writes)}')

    assert response.status_code == 200
    assert len(statements) == 17, '\n'.join(statements)
    assert counts['game_pitching_rules'] == 1, '\n'.join(statements)
    assert counts['team_pitching_settings'] == 2, '\n'.join(statements)
    assert writes == []


# --- stale payload --------------------------------------------------------

def test_a_payload_from_another_game_produces_the_wrong_answer(monkeypatch):
    """The boundary of this optimisation, stated as a test.

    A payload is only valid for the game it was resolved from. This is not a
    licence to accept stale payloads -- readiness_api() resolves its payload
    from the same `game` object it immediately passes to both consumers -- but
    the consequence of getting it wrong should be visible rather than silent.
    """
    from db import db
    from game_pitching_rules import rule_settings_payload
    from game_start_readiness import can_start_game
    from models import Game, Team

    app = _build_app(monkeypatch)
    with app.app_context():
        # Game A carries a valid override; game B has no rule at all.
        _set_rule_state('MLB Pitch Smart', None, game_ids=[INCOMPLETE])
        team = db.session.get(Team, 1)
        game_a = db.session.get(Game, INCOMPLETE)
        game_b = db.session.get(Game, READY)

        payload_a = rule_settings_payload(team, game_a)
        payload_b = rule_settings_payload(team, game_b)
        assert payload_a['effective'] == 'MLB Pitch Smart'
        assert payload_b['effective'] is None

        correct = can_start_game(game_b, team, rule_payload=payload_b)
        stale = can_start_game(game_b, team, rule_payload=payload_a)
        queried = can_start_game(game_b, team)

    blocker = 'Select the game pitching rules / tracking method.'
    assert blocker in correct['missing']
    assert correct == queried
    assert blocker not in stale['missing'], (
        'a stale payload must visibly change the answer, otherwise this test '
        'proves nothing about the boundary'
    )
    assert stale != correct
