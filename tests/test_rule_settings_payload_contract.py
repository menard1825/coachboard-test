"""Contract and query cost for rule_settings_payload().

rule_settings_payload() used to derive `effective` by calling
effective_rule_set_name(team, game), which re-read both game_pitching_rules and
team_pitching_settings even though this function had already loaded them. It
now computes the same value from the rows in hand.

`effective` and `source` deliberately disagree for one rule state: an override
row naming a rule set that is no longer in RULE_SET_OPTIONS falls back to the
team default for `effective` while still reporting source='game'. That is
pre-existing behaviour, it is the only case the membership check affects, and
it is pinned below so the check cannot be "simplified" away.

The two consumers of this helper are can_start_game() (and therefore the
first-pitch contract shared with /start's 409) and the
/api/game-day/<id>/pitching-rules endpoint. Both are covered here.
"""

import re
from collections import Counter
from datetime import datetime

import pytest
from sqlalchemy import event
from werkzeug.security import generate_password_hash


# (label, override rule_set stored on the game, team competition default)
RULE_STATES = [
    ('no override, team default set', None, 'USSSA'),
    ('no override, team default unset', None, None),
    ('valid override', 'MLB Pitch Smart', 'USSSA'),
    ('override equals team default', 'USSSA', 'USSSA'),
    ('invalid override', 'Not A Real Rule', 'USSSA'),
    ('invalid override, no team default', 'Not A Real Rule', None),
    ('valid override, no team default', 'MLB Pitch Smart', None),
]

# What each state must produce for (team_default, override, effective, source).
EXPECTED = {
    'no override, team default set': ('USSSA', None, 'USSSA', 'team'),
    'no override, team default unset': (None, None, None, 'unselected'),
    'valid override': ('USSSA', 'MLB Pitch Smart', 'MLB Pitch Smart', 'game'),
    'override equals team default': ('USSSA', 'USSSA', 'USSSA', 'game'),
    # Invalid override: source stays 'game', effective falls back to the team
    # default. Removing the RULE_SET_OPTIONS check would make effective
    # 'Not A Real Rule' here.
    'invalid override': ('USSSA', 'Not A Real Rule', 'USSSA', 'game'),
    'invalid override, no team default': (None, 'Not A Real Rule', None, 'game'),
    'valid override, no team default': (None, 'MLB Pitch Smart', 'MLB Pitch Smart', 'game'),
}


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'rule-settings-payload-test')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Game, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(
                id=1,
                team_name='Rule Payload Team',
                registration_code='rule-payload-code',
                age_group='11U',
                outfielder_count=3,
                timezone='America/Indiana/Indianapolis',
            ),
            User(
                id=1,
                username='rule-coach',
                full_name='Rule Coach',
                password_hash=generate_password_hash('password123'),
            ),
        ])
        db.session.flush()
        db.session.add(TeamMembership(
            user_id=1, team_id=1, role='Head Coach', player_order=[]))
        db.session.add(Game(
            id=7,
            date=datetime(2026, 8, 31, 18, 0, 0),
            start_time='18:00',
            opponent='Rule Payload Opponent',
            team_id=1,
        ))
        db.session.commit()

    return app


def _configure(override_rule, team_default):
    """Put the team + game into one of the seven rule states."""
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from game_pitching_rules import GamePitchingRule

    db.session.query(GamePitchingRule).delete()
    db.session.query(TeamPitchingSettings).delete()
    if override_rule is not None:
        db.session.add(GamePitchingRule(rule_set=override_rule, game_id=7, team_id=1))
    db.session.add(TeamPitchingSettings(
        team_id=1,
        competition_default_rule=team_default,
        arm_care_rule_set='MLB Pitch Smart',
    ))
    db.session.commit()
    db.session.expire_all()


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['user_id'] = 1
        session['team_id'] = 1
        session['username'] = 'rule-coach'
        session['role'] = 'Head Coach'


@pytest.mark.parametrize('label,override_rule,team_default', RULE_STATES,
                         ids=[state[0] for state in RULE_STATES])
def test_rule_settings_payload_matches_the_expected_state(
    monkeypatch, label, override_rule, team_default
):
    app = _build_app(monkeypatch)

    from db import db
    from game_pitching_rules import RULE_SET_OPTIONS, rule_settings_payload
    from models import Game, Team

    with app.app_context():
        _configure(override_rule, team_default)
        team = db.session.get(Team, 1)
        game = db.session.get(Game, 7)
        payload = rule_settings_payload(team, game)

    want_default, want_override, want_effective, want_source = EXPECTED[label]

    # The whole dict, not a field at a time.
    assert payload == {
        'team_default': want_default,
        'override': want_override,
        'effective': want_effective,
        'source': want_source,
        'options': list(RULE_SET_OPTIONS),
        'arm_care_rule_set': 'MLB Pitch Smart',
    }


def test_an_invalid_override_keeps_source_game_but_falls_back_for_effective(monkeypatch):
    """The one state where `effective` and `source` intentionally disagree.

    This is the behaviour the RULE_SET_OPTIONS membership check exists for.
    Dropping the check would leave a retired rule-set name in `effective` and
    hand it to can_start_game(), and therefore to /start.
    """
    app = _build_app(monkeypatch)

    from db import db
    from game_pitching_rules import rule_settings_payload
    from models import Game, Team

    with app.app_context():
        _configure('Not A Real Rule', 'USSSA')
        payload = rule_settings_payload(db.session.get(Team, 1), db.session.get(Game, 7))

    assert payload['override'] == 'Not A Real Rule'
    assert payload['source'] == 'game'
    assert payload['effective'] == 'USSSA'


def test_payload_with_no_game_uses_the_team_default(monkeypatch):
    app = _build_app(monkeypatch)

    from db import db
    from game_pitching_rules import rule_settings_payload
    from models import Team

    with app.app_context():
        _configure('MLB Pitch Smart', 'USSSA')
        payload = rule_settings_payload(db.session.get(Team, 1), None)

    assert payload['override'] is None
    assert payload['effective'] == 'USSSA'
    assert payload['source'] == 'team'


@pytest.mark.parametrize('label,override_rule,team_default', RULE_STATES,
                         ids=[state[0] for state in RULE_STATES])
def test_pitching_rules_endpoint_contract_is_unchanged(
    monkeypatch, label, override_rule, team_default
):
    """The non-readiness consumer of this helper returns it verbatim."""
    app = _build_app(monkeypatch)

    from game_pitching_rules import RULE_SET_OPTIONS

    with app.app_context():
        _configure(override_rule, team_default)

    client = app.test_client()
    _login(client)
    response = client.get('/api/game-day/7/pitching-rules')

    assert response.status_code == 200
    want_default, want_override, want_effective, want_source = EXPECTED[label]
    assert response.get_json() == {
        'status': 'success',
        'team_default': want_default,
        'override': want_override,
        'effective': want_effective,
        'source': want_source,
        'options': list(RULE_SET_OPTIONS),
        'arm_care_rule_set': 'MLB Pitch Smart',
    }


def _table_of(statement):
    match = re.search(r'\bFROM\s+([a-zA-Z0-9_]+)', statement, re.IGNORECASE)
    return match.group(1) if match else '<other>'


@pytest.mark.parametrize('label,override_rule,team_default', RULE_STATES,
                         ids=[state[0] for state in RULE_STATES])
def test_one_call_reads_each_rule_table_at_most_once(
    monkeypatch, label, override_rule, team_default
):
    """Per-table occurrence counts, not a total-statement number.

    A total would pass again the moment some other query was removed
    elsewhere. What must not come back is a *second* read of either rule
    table inside one rule_settings_payload() call.
    """
    app = _build_app(monkeypatch)

    from db import db
    from game_pitching_rules import rule_settings_payload
    from models import Game, Team

    with app.app_context():
        _configure(override_rule, team_default)
        team = db.session.get(Team, 1)
        game = db.session.get(Game, 7)
        # Load both so the measured call cannot be charged for refreshing them.
        team.team_name, game.opponent

        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.strip().upper().startswith('PRAGMA '):
                return
            statements.append(statement)

        engine = db.session.get_bind()
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            rule_settings_payload(team, game)
        finally:
            event.remove(engine, 'before_cursor_execute', capture)

    counts = Counter(_table_of(statement) for statement in statements)
    detail = '\n'.join(f'  {i:02d} {s}' for i, s in enumerate(statements, 1))

    assert counts['game_pitching_rules'] <= 1, (
        f'game_pitching_rules read {counts["game_pitching_rules"]} times in one '
        f'rule_settings_payload() call ({label}).\n{detail}'
    )
    assert counts['team_pitching_settings'] <= 1, (
        f'team_pitching_settings read {counts["team_pitching_settings"]} times in one '
        f'rule_settings_payload() call ({label}).\n{detail}'
    )
    assert not [s for s in statements
                if s.strip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))], (
        f'rule_settings_payload() must not write.\n{detail}'
    )
