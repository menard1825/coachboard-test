"""Two coaches saving one game's pregame defense: merged or refused, never
silently overwritten (rotation_merge.py, /save_rotation's base_innings).

The browser's shared save queue sends the plan it started from. If another
coach saved in between, changes to different positions are merged; a
position both changed differently is refused with code 'rotation_conflict'
and nothing is saved. A save without base_innings (a direct API call) keeps
the old whole-plan behavior.
"""

from datetime import datetime

import pytest
from werkzeug.security import generate_password_hash

from rotation_merge import merge, normalize


TEAM_ID = 1
GAME_ID = 1
NAMES = ['Alex', 'Blake', 'Casey', 'Drew', 'Eli', 'Finn', 'Gray', 'Harper', 'Indy', 'Jo']
POSITIONS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']
FULL = dict(zip(POSITIONS, NAMES))


# --- The rule (pure) --------------------------------------------------------------------

def _with(alignment, **changes):
    result = dict(alignment)
    for position, player in changes.items():
        if player is None:
            result.pop(position, None)
        else:
            result[position] = player
    return result


def test_changes_to_different_positions_are_both_kept():
    base = {'1': FULL, '2': {}}
    mine = {'1': _with(FULL, RF='Jo'), '2': {}}
    theirs = {'1': FULL, '2': {'P': 'Blake'}}
    merged, conflicts = merge(base, mine, theirs)
    assert conflicts == []
    assert merged == {'1': _with(FULL, RF='Jo'), '2': {'P': 'Blake'}}


def test_the_same_position_changed_differently_is_a_conflict():
    base = {'1': FULL}
    merged, conflicts = merge(base, {'1': _with(FULL, CF='Jo')}, {'1': _with(FULL, CF=None)})
    assert conflicts == [{'inning': '1', 'position': 'CF', 'yours': 'Jo', 'theirs': None}]


def test_the_same_change_by_both_is_not_a_conflict():
    base = {'1': _with(FULL, CF=None)}
    both = {'1': FULL}
    assert merge(base, both, both) == (both, [])


def test_a_swap_against_a_change_to_one_of_its_positions_is_a_conflict():
    base = {'1': FULL}
    swapped = {'1': _with(FULL, LF=FULL['CF'], CF=FULL['LF'])}
    theirs = {'1': _with(FULL, CF='Jo')}
    _, conflicts = merge(base, swapped, theirs)
    assert [item['position'] for item in conflicts] == ['CF']


def test_a_merge_that_would_place_a_player_twice_is_a_conflict():
    base = {'1': _with(FULL, RF=None)}
    mine = {'1': _with(FULL)}                           # Indy to RF
    theirs = {'1': _with(FULL, RF=None, LF='Indy')}     # Indy to LF (Gray out)
    _, conflicts = merge(base, mine, theirs)
    assert conflicts == [{'inning': '1', 'player': 'Indy', 'kind': 'duplicate'}]


def test_innings_added_and_removed():
    base = {'1': FULL, '7': {}}
    # Removed by me, untouched by them: removed.
    assert merge(base, {'1': FULL}, base)[0] == {'1': FULL}
    # Removed by both: removed, no conflict.
    assert merge(base, {'1': FULL}, {'1': FULL}) == ({'1': FULL}, [])
    # Removed by me, changed by them: a conflict.
    _, conflicts = merge(base, {'1': FULL}, {'1': FULL, '7': {'P': 'Alex'}})
    assert any(item['inning'] == '7' and item['position'] is None for item in conflicts)
    # Added by them: kept.
    assert merge(base, base, {**base, '8': {}})[0] == {**base, '8': {}}


def test_normalize_drops_open_positions_and_keeps_open_innings():
    assert normalize({1: {'P': ' Alex ', 'C': '', 'SS': None}, '2': None}) == {'1': {'P': 'Alex'}, '2': {}}


# --- /save_rotation ---------------------------------------------------------------------

@pytest.fixture(name='app')
def _app(monkeypatch, tmp_path):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "concurrency.db"}')

    from app import create_app
    from db import db
    from models import Game, Player, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(id=TEAM_ID, team_name='Test Team', registration_code='test-code', age_group='12U',
                 pitching_rule_set='MLB Pitch Smart', outfielder_count=3, timezone='America/Indiana/Indianapolis'),
            User(id=1, username='coach', full_name='Coach', password_hash=generate_password_hash('password123')),
            User(id=2, username='assistant', full_name='Assistant', password_hash=generate_password_hash('password123')),
        ])
        db.session.flush()
        db.session.add_all([
            TeamMembership(user_id=1, team_id=TEAM_ID, role='Head Coach', player_order=[]),
            TeamMembership(user_id=2, team_id=TEAM_ID, role='Assistant Coach', player_order=[]),
            Game(id=GAME_ID, team_id=TEAM_ID, date=datetime(2026, 10, 30, 10, 0), opponent='Visitors', is_live=False),
        ])
        for index, name in enumerate(NAMES, start=1):
            db.session.add(Player(id=index, team_id=TEAM_ID, name=name))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _client(app, username='coach'):
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(logged_in=True, username=username, team_id=TEAM_ID,
                       role='Head Coach' if username == 'coach' else 'Assistant Coach')
    return client


def _save(app, innings, base=None, rotation_id=None, username='coach'):
    body = {'id': rotation_id, 'title': 'Rotation for vs Visitors', 'innings': innings,
            'associated_game_id': GAME_ID}
    if base is not None:
        body['base_innings'] = base
    response = _client(app, username).post('/save_rotation', json=body)
    return response.status_code, response.get_json()


def _stored(app):
    from db import db
    from models import Rotation
    with app.app_context():
        db.session.expire_all()
        rows = db.session.query(Rotation).filter_by(team_id=TEAM_ID, associated_game_id=GAME_ID).all()
        return [row.innings for row in rows]


def _seed(app, innings):
    status, body = _save(app, innings)
    assert status == 200, body
    return body['new_id']


def test_a_save_from_the_current_plan_saves_as_before(app):
    rotation_id = _seed(app, {'1': FULL})
    status, body = _save(app, {'1': _with(FULL, CF='Jo')}, base={'1': FULL}, rotation_id=rotation_id)
    assert status == 200, body
    assert _stored(app) == [{'1': _with(FULL, CF='Jo')}]
    assert body['innings'] == {'1': _with(FULL, CF='Jo')}


def test_another_coachs_save_to_a_different_position_is_merged(app):
    rotation_id = _seed(app, {'1': FULL, '2': {}})
    # The assistant saves the 2nd inning's pitcher...
    status, _ = _save(app, {'1': FULL, '2': {'P': 'Blake'}}, base={'1': FULL, '2': {}},
                      rotation_id=rotation_id, username='assistant')
    assert status == 200
    # ...then the coach, from the older plan, moves Jo into RF.
    status, body = _save(app, {'1': _with(FULL, RF='Jo'), '2': {}}, base={'1': FULL, '2': {}},
                         rotation_id=rotation_id)
    assert status == 200, body
    both = {'1': _with(FULL, RF='Jo'), '2': {'P': 'Blake'}}
    assert _stored(app) == [both]
    assert body['innings'] == both


def test_a_stale_save_to_the_same_position_is_refused_and_nothing_changes(app):
    rotation_id = _seed(app, {'1': FULL})
    status, _ = _save(app, {'1': _with(FULL, CF='Jo')}, base={'1': FULL},
                      rotation_id=rotation_id, username='assistant')
    assert status == 200
    status, body = _save(app, {'1': _with(FULL, CF=None, RF=None)}, base={'1': FULL}, rotation_id=rotation_id)
    assert status == 409
    assert body['code'] == 'rotation_conflict'
    assert body['conflicts'] == [{'inning': '1', 'position': 'CF', 'yours': None, 'theirs': 'Jo'}]
    assert body['innings'] == {'1': _with(FULL, CF='Jo')}
    assert _stored(app) == [{'1': _with(FULL, CF='Jo')}]


def test_without_a_base_the_plan_is_replaced_as_before(app):
    rotation_id = _seed(app, {'1': FULL})
    _save(app, {'1': _with(FULL, CF='Jo')}, rotation_id=rotation_id, username='assistant')
    status, _ = _save(app, {'1': FULL}, rotation_id=rotation_id)
    assert status == 200
    assert _stored(app) == [{'1': FULL}]


def test_the_existing_checks_still_come_first(app):
    rotation_id = _seed(app, {'1': FULL})
    # A player twice in the coach's own change: refused as before.
    status, body = _save(app, {'1': _with(FULL, CF='Alex')}, base={'1': FULL}, rotation_id=rotation_id)
    assert (status, body['code']) == (400, 'duplicate_player')
    # A live game: the pregame plan is locked, whatever the base.
    from db import db
    from models import Game
    with app.app_context():
        db.session.get(Game, GAME_ID).is_live = True
        db.session.commit()
    status, body = _save(app, {'1': _with(FULL, CF='Jo')}, base={'1': FULL}, rotation_id=rotation_id)
    assert status == 409 and 'locked while the game is live' in body['message']
    assert _stored(app) == [{'1': FULL}]


def test_a_first_save_never_adds_a_second_plan_for_the_game(app):
    _seed(app, {'1': {'P': 'Alex'}})
    # A page that loaded before the plan existed saves its own first change.
    status, body = _save(app, {'1': {'C': 'Blake'}}, base={})
    assert status == 200, body
    assert _stored(app) == [{'1': {'P': 'Alex', 'C': 'Blake'}}]
