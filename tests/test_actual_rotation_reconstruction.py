"""The private actual-game reconstruction helper, and its public wrapper.

build_game_readiness() already loads the rotation and this game's events, so it
reconstructs the played defense from those rather than calling
actual_game_rotation(), which would query both a second time.

That reuse is only safe because the helper normalizes event order itself. Order
is load-bearing twice over -- `actual[inning] = ...` is last-write-wins, and
_actual_pitcher_names() reports pitchers in first-seen order -- and the events
query in build_game_readiness() carries no ORDER BY. It happens to come back in
sequence order today because SQLite scans
idx_game_rotation_events_team_game_sequence_id, but that is an artifact of
index selection, not a guarantee.

So the central regression here is not "order matters" (it does) but
"the helper makes order not matter to its caller": ordered input and reversed
input must produce byte-identical reconstructions.
"""

from copy import deepcopy
from datetime import datetime

import pytest
from werkzeug.security import generate_password_hash


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


# (label, has_rotation, is_live, [(inning, sequence, event_type, before_P, after_P, reverted)])
SCENARIOS = [
    ('no rotation', False, False, []),
    ('rotation, no events', True, False, []),
    ('one event', True, False, [
        ('1', 1, 'Pitcher Change', 'Pitcher Pat', 'Left Lee', False)]),
    ('several ordered events', True, False, [
        ('1', 1, 'Pitcher Change', 'Pitcher Pat', 'Left Lee', False),
        ('2', 2, 'Pitcher Change', 'Left Lee', 'Center Casey', False),
        ('3', 3, 'Pitcher Change', 'Center Casey', 'Right Riley', False)]),
    # Stored so insertion (id) order and sequence order disagree.
    ('events out of sequence', True, False, [
        ('3', 30, 'Pitcher Change', 'Center Casey', 'Right Riley', False),
        ('1', 10, 'Pitcher Change', 'Pitcher Pat', 'Left Lee', False),
        ('2', 20, 'Pitcher Change', 'Left Lee', 'Center Casey', False)]),
    ('reverted events', True, False, [
        ('1', 1, 'Pitcher Change', 'Pitcher Pat', 'Left Lee', False),
        ('2', 2, 'Pitcher Change', 'Left Lee', 'Center Casey', True),
        ('3', 3, 'Pitcher Change', 'Center Casey', 'Right Riley', False)]),
    # Last write per inning wins, so ordering decides which alignment survives.
    ('multiple events one inning', True, False, [
        ('2', 1, 'Pitcher Change', 'Pitcher Pat', 'Left Lee', False),
        ('2', 2, 'Pitcher Change', 'Left Lee', 'Center Casey', False),
        ('2', 3, 'Pitcher Change', 'Center Casey', 'Right Riley', False)]),
    ('live game', True, True, [
        ('1', 1, 'Pitcher Change', 'Pitcher Pat', 'Left Lee', False),
        ('2', 2, 'Pitcher Change', 'Left Lee', 'Center Casey', False)]),
    ('completed game', True, False, [
        ('1', 1, 'Pitcher Change', 'Pitcher Pat', 'Left Lee', False),
        ('6', 2, 'End Game', 'Left Lee', 'Left Lee', False)]),
]

LABELS = [scenario[0] for scenario in SCENARIOS]


def _game_id(label):
    return 700 + LABELS.index(label)


def _build_app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'actual-rotation-reconstruction-test')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from models import (Game, GameRotationEvent, Lineup, LineupEntry, Player,
                        Rotation, Team, TeamMembership, User)

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(id=1, team_name='Reconstruction Team',
                 registration_code='reconstruction-code', age_group='11U',
                 pitching_rule_set='MLB Pitch Smart', outfielder_count=3,
                 timezone='America/Indiana/Indianapolis'),
            User(id=1, username='recon-coach', full_name='Recon Coach',
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

        for label, has_rotation, is_live, events in SCENARIOS:
            game_id = _game_id(label)
            db.session.add(Game(
                id=game_id, date=datetime(2026, 8, 31, 18, 0, 0),
                start_time='18:00', opponent=label, team_id=1,
                is_live=is_live, live_current_inning='1'))
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
            db.session.flush()
            for inning, sequence, event_type, before_p, after_p, reverted in events:
                db.session.add(GameRotationEvent(
                    inning=inning, sequence=sequence, event_type=event_type,
                    before_alignment=_with_pitcher(before_p),
                    after_alignment=_with_pitcher(after_p),
                    reverted=reverted, team_id=1, game_id=game_id))
                db.session.flush()
        db.session.commit()

    return app


def _inputs(label):
    """The rotation and the unordered event list, as build_game_readiness has them."""
    from db import db
    from models import Game, GameRotationEvent, Rotation

    game_id = _game_id(label)
    game = db.session.get(Game, game_id)
    rotation = db.session.query(Rotation).filter_by(
        associated_game_id=game_id, team_id=1).first()
    events = db.session.query(GameRotationEvent).filter_by(
        game_id=game_id, team_id=1).all()
    return game, rotation, events


def _signature(actual, ordered, reached):
    from game_day_helpers import _actual_pitcher_names
    return {
        'actual': actual,
        'event_ids': [event.id for event in ordered],
        'event_sequences': [event.sequence for event in ordered],
        'reached': sorted(reached),
        'expected_pitchers': _actual_pitcher_names(actual, ordered, reached),
    }


# --- the helper -----------------------------------------------------------

@pytest.mark.parametrize('label', LABELS)
def test_reconstruction_is_identical_for_ordered_and_reversed_input(monkeypatch, label):
    """The central regression.

    The helper owns ordering, so its caller may hand it any order. Reversing
    the list must change nothing -- unlike the raw reconstruction loop, where
    the audit showed reversal changes both `actual` and `expected_pitchers`.
    """
    from game_day_helpers import _reconstruct_actual_game_rotation

    app = _build_app(monkeypatch)
    with app.app_context():
        _, rotation, events = _inputs(label)

        forward = _signature(*_reconstruct_actual_game_rotation(rotation, list(events)))
        backward = _signature(*_reconstruct_actual_game_rotation(rotation, list(events)[::-1]))

    assert forward['actual'] == backward['actual']
    assert forward['event_ids'] == backward['event_ids']
    assert forward['event_sequences'] == backward['event_sequences']
    assert forward['reached'] == backward['reached']
    assert forward['expected_pitchers'] == backward['expected_pitchers']


def test_reversal_would_change_the_result_without_normalization(monkeypatch):
    """Proves the test above is not vacuous.

    Same fixture, same reversal, but reconstructing the way the helper would if
    it trusted its caller's order. If this ever stops differing, the ordered
    fixture has lost its teeth and the normalization test proves nothing.
    """
    app = _build_app(monkeypatch)
    with app.app_context():
        _, rotation, events = _inputs('multiple events one inning')
        ordered = sorted(events, key=lambda event: (event.sequence, event.id))

        def naive(event_list):
            actual = deepcopy(rotation.innings or {})
            for event in event_list:
                if event.reverted:
                    continue
                actual[str(event.inning)] = deepcopy(event.after_alignment or {})
            return actual

        assert naive(ordered) != naive(list(ordered)[::-1])


@pytest.mark.parametrize('label', LABELS)
def test_helper_orders_events_by_sequence_then_id(monkeypatch, label):
    from game_day_helpers import _reconstruct_actual_game_rotation

    app = _build_app(monkeypatch)
    with app.app_context():
        _, rotation, events = _inputs(label)
        _, ordered, _ = _reconstruct_actual_game_rotation(rotation, list(events)[::-1])

    keys = [(event.sequence, event.id) for event in ordered]
    assert keys == sorted(keys)


def test_helper_tolerates_a_missing_sequence(monkeypatch):
    """NULLs sort first in an ascending SQL clause; the key must not raise."""
    from game_day_helpers import _reconstruct_actual_game_rotation

    class Stub:
        def __init__(self, identifier, sequence, inning):
            self.id = identifier
            self.sequence = sequence
            self.inning = inning
            self.reverted = False
            self.after_alignment = _with_pitcher(f'P{identifier}')
            self.before_alignment = None

    app = _build_app(monkeypatch)
    with app.app_context():
        _, rotation, _ = _inputs('rotation, no events')
        stubs = [Stub(3, 2, '3'), Stub(1, None, '1'), Stub(2, 1, '2')]
        _, ordered, _ = _reconstruct_actual_game_rotation(rotation, stubs)

    assert [event.id for event in ordered] == [1, 2, 3]


def test_helper_makes_no_queries(monkeypatch):
    from sqlalchemy import event as sa_event

    from db import db
    from game_day_helpers import _reconstruct_actual_game_rotation

    app = _build_app(monkeypatch)
    with app.app_context():
        _, rotation, events = _inputs('several ordered events')
        rotation.innings, [e.after_alignment for e in events]  # force load

        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if not statement.strip().upper().startswith('PRAGMA '):
                statements.append(statement)

        engine = db.session.get_bind()
        sa_event.listen(engine, 'before_cursor_execute', capture)
        try:
            _reconstruct_actual_game_rotation(rotation, events)
        finally:
            sa_event.remove(engine, 'before_cursor_execute', capture)

    assert statements == []


@pytest.mark.parametrize('label', LABELS)
def test_helper_does_not_mutate_its_inputs(monkeypatch, label):
    import json

    from game_day_helpers import _reconstruct_actual_game_rotation

    app = _build_app(monkeypatch)
    with app.app_context():
        _, rotation, events = _inputs(label)
        supplied = list(events)

        before_innings = json.dumps(rotation.innings, sort_keys=True) if rotation else None
        before_alignments = [json.dumps(e.after_alignment, sort_keys=True) for e in supplied]
        before_order = [e.id for e in supplied]

        actual, ordered, reached = _reconstruct_actual_game_rotation(rotation, supplied)

        # A caller mutating what it got back must not reach the ORM objects.
        for key in list(actual):
            actual[key]['P'] = 'MUTATED BY CALLER'
        reached.add('mutated')
        ordered.append('mutated')

        after_innings = json.dumps(rotation.innings, sort_keys=True) if rotation else None
        after_alignments = [json.dumps(e.after_alignment, sort_keys=True) for e in supplied]

        assert after_innings == before_innings
        assert after_alignments == before_alignments
        # The caller's own list must not have been sorted in place or appended to.
        assert [e.id for e in supplied] == before_order
        assert len(supplied) == len(before_order)


# --- the public wrapper ---------------------------------------------------

def _oracle_actual_game_rotation(game, team_id):
    """actual_game_rotation() exactly as it was before the helper existed."""
    from db import db
    from models import GameRotationEvent, Rotation

    rotation = db.session.query(Rotation).filter_by(
        team_id=team_id, associated_game_id=game.id).first()
    actual = deepcopy(rotation.innings or {}) if rotation else {}
    events = db.session.query(GameRotationEvent).filter_by(
        team_id=team_id, game_id=game.id,
    ).order_by(GameRotationEvent.sequence.asc(), GameRotationEvent.id.asc()).all()
    reached = set()
    for item in events:
        if item.reverted:
            continue
        reached.add(str(item.inning))
        actual[str(item.inning)] = deepcopy(item.after_alignment or {})
    if events:
        reached.add('1')
    return rotation, actual, events, reached


@pytest.mark.parametrize('label', LABELS)
def test_public_actual_game_rotation_matches_the_pre_change_behaviour(monkeypatch, label):
    from game_day_helpers import actual_game_rotation

    app = _build_app(monkeypatch)
    with app.app_context():
        game, _, _ = _inputs(label)

        want_rotation, want_actual, want_events, want_reached = \
            _oracle_actual_game_rotation(game, 1)
        want = _signature(want_actual, want_events, want_reached)

        got_rotation, got_actual, got_events, got_reached = actual_game_rotation(game, 1)
        got = _signature(got_actual, got_events, got_reached)

        assert (got_rotation is None) == (want_rotation is None)
        if want_rotation is not None:
            assert got_rotation.id == want_rotation.id

    assert got == want


def test_public_signature_is_unchanged(monkeypatch):
    """No rotation=/events= parameters were added to the public function."""
    import inspect

    from game_day_helpers import actual_game_rotation

    signature = inspect.signature(actual_game_rotation)
    assert list(signature.parameters) == ['game', 'team_id']
    assert all(
        parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )
