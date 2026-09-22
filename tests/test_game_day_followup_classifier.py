"""Postgame Follow-Up classification, and its parity with full readiness.

Game Day's follow-up loop scans up to 20 candidates and keeps six. Running
build_game_readiness() on each cost 12 statements per candidate; the section
renders only status and pitching_missing, so the loop now calls
build_game_followup_status(), which needs three.

Every test here exists to hold one line: for the follow-up decision, and for
the text that decision renders, the cheap answer must equal the expensive one.
The classifier is built on the same _reconstruct_actual_game_rotation(),
_actual_pitcher_names() and _pitching_completion() helpers the full path uses,
so reverted events, End Game handling, same-inning last-write-wins and
pitching_missing ordering are shared by construction -- but shared code is not
proof, so the parity matrix below checks them against the real payload.
"""

import re
from collections import Counter
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event as sa_event
from werkzeug.security import generate_password_hash


FOLLOWUP_STATUSES = {'GC STATS PENDING', 'NEEDS POSTGAME'}

ALIGNMENT = {
    'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
    '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
    'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
}
NAMES = list(ALIGNMENT.values())


def _with_pitcher(name):
    out = dict(ALIGNMENT)
    out['P'] = name
    return out


def _event(inning, sequence, pitcher_before, pitcher_after,
           event_type='Pitcher Change', reverted=False):
    return dict(inning=str(inning), sequence=sequence, event_type=event_type,
                before=pitcher_before, after=pitcher_after, reverted=reverted)


def _outing(name, pitches=40, innings=2.0):
    return dict(name=name, pitches=pitches, innings=innings)


# (label, is_live, has_rotation, events, outings)
CASES = [
    ('no events', False, False, [], []),
    ('rotation but no events', False, True, [], []),
    ('live game', True, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee')], []),
    ('one normal event', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee')], []),
    ('end game, complete stats', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(6, 2, 'Left Lee', 'Left Lee', 'End Game')],
     [_outing('Pitcher Pat'), _outing('Left Lee')]),
    ('end game, all stats missing', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(6, 2, 'Left Lee', 'Left Lee', 'End Game')], []),
    ('end game, partially missing', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(6, 2, 'Left Lee', 'Left Lee', 'End Game')],
     [_outing('Pitcher Pat')]),
    ('legacy complete, no end game', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee')],
     [_outing('Pitcher Pat'), _outing('Left Lee')]),
    ('needs postgame', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(2, 2, 'Left Lee', 'Center Casey')], []),
    ('reverted end game', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(6, 2, 'Left Lee', 'Left Lee', 'End Game', reverted=True)], []),
    ('reverted pitcher event', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(2, 2, 'Left Lee', 'Center Casey', reverted=True),
      _event(3, 3, 'Center Casey', 'Right Riley')], []),
    ('multiple events one inning', False, True,
     [_event(2, 1, 'Pitcher Pat', 'Left Lee'),
      _event(2, 2, 'Left Lee', 'Center Casey'),
      _event(2, 3, 'Center Casey', 'Right Riley')], []),
    ('events out of sequence', False, True,
     [_event(3, 30, 'Center Casey', 'Right Riley'),
      _event(1, 10, 'Pitcher Pat', 'Left Lee'),
      _event(2, 20, 'Left Lee', 'Center Casey')], []),
    ('no rotation', False, False,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(6, 2, 'Left Lee', 'Left Lee', 'End Game')], []),
    ('expected pitcher with no outing', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(6, 2, 'Left Lee', 'Left Lee', 'End Game')],
     [_outing('Left Lee')]),
    ('outing with pitches missing', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(6, 2, 'Left Lee', 'Left Lee', 'End Game')],
     [_outing('Pitcher Pat', pitches=None), _outing('Left Lee')]),
    ('outing with innings missing', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(6, 2, 'Left Lee', 'Left Lee', 'End Game')],
     [_outing('Pitcher Pat'), _outing('Left Lee', innings=None)]),
    # Inning 1 has no event, so actual['1'] comes from the rotation plan and
    # contributes a pitcher the events alone would never name. This is the case
    # that fails if the classifier stops loading the rotation.
    ('late-inning event only', False, True,
     [_event(3, 1, 'Center Casey', 'Right Riley'),
      _event(6, 2, 'Right Riley', 'Right Riley', 'End Game')], []),
    ('several pitchers, some complete', False, True,
     [_event(1, 1, 'Pitcher Pat', 'Left Lee'),
      _event(2, 2, 'Left Lee', 'Center Casey'),
      _event(3, 3, 'Center Casey', 'Right Riley'),
      _event(6, 4, 'Right Riley', 'Right Riley', 'End Game')],
     [_outing('Left Lee'), _outing('Right Riley')]),
]
CASE_IDS = [case[0] for case in CASES]


def _build_app(monkeypatch, cases=CASES, day_offset=-3):
    monkeypatch.setenv('SECRET_KEY', 'game-day-followup-test')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from game_day_helpers import team_now
    from models import (Game, GameRotationEvent, Lineup, LineupEntry,
                        PitchingOuting, Player, Rotation, Team, TeamMembership,
                        User)

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(id=1, team_name='Follow-Up Team',
                    registration_code='followup-code', age_group='11U',
                    pitching_rule_set='MLB Pitch Smart', outfielder_count=3,
                    timezone='America/Indiana/Indianapolis')
        db.session.add_all([
            team,
            User(id=1, username='followup-coach', full_name='Follow Coach',
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
        db.session.add(TeamPitchingSettings(
            team_id=1, competition_default_rule='USSSA',
            arm_care_rule_set='MLB Pitch Smart'))
        db.session.commit()

        today = team_now(team).date()
        base = datetime.combine(today, datetime.min.time())

        for index, (label, is_live, has_rotation, events, outings) in enumerate(cases):
            game_id = 3000 + index
            when = base + timedelta(days=day_offset, hours=12)
            db.session.add(Game(
                id=game_id, date=when, start_time='12:00', opponent=label,
                team_id=1, is_live=is_live, live_current_inning='1'))
            db.session.flush()
            if has_rotation:
                db.session.add(Rotation(
                    title=f'Rotation {game_id}',
                    innings={str(n): dict(ALIGNMENT) for n in range(1, 7)},
                    associated_game_id=game_id, team_id=1))
            lineup = Lineup(title=f'Lineup {game_id}',
                            associated_game_id=game_id, team_id=1)
            db.session.add(lineup)
            db.session.flush()
            for order, name in enumerate(NAMES, start=1):
                player = db.session.query(Player).filter_by(name=name).first()
                db.session.add(LineupEntry(
                    lineup_id=lineup.id, player_id=player.id,
                    player_name_snapshot=name, batting_order=order))
            for item in events:
                db.session.add(GameRotationEvent(
                    inning=item['inning'], sequence=item['sequence'],
                    event_type=item['event_type'],
                    before_alignment=_with_pitcher(item['before']),
                    after_alignment=_with_pitcher(item['after']),
                    reverted=item['reverted'], team_id=1, game_id=game_id))
            for item in outings:
                player = db.session.query(Player).filter_by(name=item['name']).first()
                db.session.add(PitchingOuting(
                    date=when.date(), opponent=label, pitches=item['pitches'],
                    innings=item['innings'], pitcher_type='Starter',
                    outing_type='Game', team_id=1, player_id=player.id,
                    game_id=game_id))
            db.session.commit()

    return app


def _login(client):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['user_id'] = 1
        session['team_id'] = 1
        session['username'] = 'followup-coach'
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


# --- parity matrix --------------------------------------------------------

@pytest.mark.parametrize('index,case', list(enumerate(CASES)), ids=CASE_IDS)
def test_classifier_matches_full_readiness(monkeypatch, index, case):
    import blueprints.game_day as game_day
    from db import db
    from game_day_helpers import build_game_followup_status
    from models import Game, Team

    app = _build_app(monkeypatch)
    with app.test_request_context('/'):
        team = db.session.get(Team, 1)
        game = db.session.get(Game, 3000 + index)

        full = game_day._readiness_for_game(game, team)
        light = build_game_followup_status(game, team.id)

    qualifies = full['status'] in FOLLOWUP_STATUSES
    assert (light is not None) == qualifies, (
        f'{case[0]}: full status {full["status"]!r}, classifier {light!r}')

    if light is not None:
        assert light['status'] == full['status']
        # Byte-for-byte, including order.
        assert light['pitching_missing'] == full['pitching_missing'], (
            f'{case[0]}: {light["pitching_missing"]} != {full["pitching_missing"]}')
        assert sorted(light) == ['pitching_missing', 'status']


def test_the_matrix_actually_exercises_both_follow_up_statuses(monkeypatch):
    """Guard against a fixture set that only ever produces one answer."""
    import blueprints.game_day as game_day
    from db import db
    from models import Game, Team

    app = _build_app(monkeypatch)
    with app.test_request_context('/'):
        team = db.session.get(Team, 1)
        statuses = [
            game_day._readiness_for_game(db.session.get(Game, 3000 + index), team)['status']
            for index in range(len(CASES))
        ]

    seen = Counter(statuses)
    assert seen['GC STATS PENDING'] >= 3, seen
    assert seen['NEEDS POSTGAME'] >= 3, seen
    assert seen['COMPLETE'] >= 2, seen
    assert seen['LIVE'] >= 1, seen
    assert seen['PAST'] >= 1, seen


def test_pitching_missing_order_is_expected_pitcher_order(monkeypatch):
    """Not just equal to the full payload -- the order has to be meaningful."""
    from db import db
    from game_day_helpers import build_game_followup_status
    from models import Game, Team

    index = CASE_IDS.index('several pitchers, some complete')
    app = _build_app(monkeypatch)
    with app.test_request_context('/'):
        team = db.session.get(Team, 1)
        light = build_game_followup_status(db.session.get(Game, 3000 + index), team.id)

    assert light['status'] == 'GC STATS PENDING'
    # Pitchers appear in first-seen order across the ordered events; Left Lee
    # and Right Riley have outings, so the gaps are Pat then Casey.
    assert light['pitching_missing'] == ['Pitcher Pat', 'Center Casey']


# --- classifier SQL cost --------------------------------------------------

@pytest.mark.parametrize('index,case', list(enumerate(CASES)), ids=CASE_IDS)
def test_classifier_query_budget(monkeypatch, index, case):
    from db import db
    from game_day_helpers import build_game_followup_status
    from models import Game, Team

    app = _build_app(monkeypatch)
    with app.test_request_context('/'):
        team = db.session.get(Team, 1)
        game = db.session.get(Game, 3000 + index)
        team.team_name, game.opponent, game.is_live

        _, statements, counts, writes = _measure(
            app, lambda: build_game_followup_status(game, team.id))

    assert counts['rotations'] <= 1, statements
    assert counts['game_rotation_events'] <= 1, statements
    assert counts['pitching_outings'] <= 1, statements
    assert len(statements) <= 3, statements
    assert writes == [], statements
    # Nothing the full payload needs and this does not.
    for table in ('players', 'player_game_absences', 'lineups', 'lineup_entries',
                  'game_pitching_plans', 'player_pitch_targets',
                  'game_pitching_rules', 'team_pitching_settings'):
        assert counts[table] == 0, (table, statements)


# --- delegation to the shared, order-normalizing helpers -------------------

def test_classifier_delegates_reconstruction_to_the_shared_helper(monkeypatch):
    """Ordering safety cannot be proven through a DB fixture here.

    SQLite serves the events query from
    idx_game_rotation_events_team_game_sequence_id, so the rows already arrive
    in (sequence, id) order and a deliberately out-of-sequence fixture looks
    identical whether the caller sorts or not. The real protection is that the
    classifier hands its raw list to _reconstruct_actual_game_rotation(), whose
    own tests prove it normalizes order and drops reverted events.

    So assert the delegation itself, and feed the helper a reversed list while
    doing it: the answer must not move. An inlined loop that trusted query
    order would never call the patched helper, and this fails.
    """
    import game_day_helpers
    from db import db
    from game_day_helpers import build_game_followup_status
    from models import Game, Team

    index = CASE_IDS.index('several pitchers, some complete')
    app = _build_app(monkeypatch)

    original = game_day_helpers._reconstruct_actual_game_rotation
    seen = []

    def reversing(rotation, events):
        seen.append(len(list(events)))
        return original(rotation, list(events)[::-1])

    with app.test_request_context('/'):
        team = db.session.get(Team, 1)
        game = db.session.get(Game, 3000 + index)
        expected = build_game_followup_status(game, team.id)

        monkeypatch.setattr(game_day_helpers,
                            '_reconstruct_actual_game_rotation', reversing)
        got = build_game_followup_status(game, team.id)

    assert seen, 'the classifier must reconstruct through the shared helper'
    assert got == expected


def test_classifier_uses_the_shared_pitching_completion_helper(monkeypatch):
    import game_day_helpers
    from db import db
    from game_day_helpers import build_game_followup_status
    from models import Game, Team

    index = CASE_IDS.index('end game, partially missing')
    app = _build_app(monkeypatch)

    original = game_day_helpers._pitching_completion
    seen = []

    def spy(expected_pitchers, outings):
        seen.append(list(expected_pitchers))
        return original(expected_pitchers, outings)

    monkeypatch.setattr(game_day_helpers, '_pitching_completion', spy)
    with app.test_request_context('/'):
        team = db.session.get(Team, 1)
        result = build_game_followup_status(db.session.get(Game, 3000 + index), team.id)

    assert seen, 'pitching completion must come from the shared helper'
    assert result['status'] == 'GC STATS PENDING'
