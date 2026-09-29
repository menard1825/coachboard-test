"""Start Game, Part 1: defense integrity and open-position decisions.

Start (POST /api/live-game/<id>/start) runs under the game's write lock and
sorts what it finds in the stored 1st-inning defense into:

* hard stops -- the record would be invalid, so the coach must fix it: no
  pitcher, one player at two positions, a player not on the roster, a player
  marked Out on the field, or (when the request says what the coach
  reviewed) a stored defense that differs from it;
* questions -- open fielding positions are a baseball choice. Start asks, and
  "Start with CF Open" acknowledges exactly the positions open now;
* information -- batting order and later innings never block first pitch.
"""

from datetime import datetime

import eventlet
import pytest
from werkzeug.security import generate_password_hash


TEAM_ID = 1
GAME_ID = 1
START = f'/api/live-game/{GAME_ID}/start'
READINESS = f'/api/game-day/{GAME_ID}/readiness'
NAMES = ['Alex', 'Blake', 'Casey', 'Drew', 'Eli', 'Finn', 'Gray', 'Harper', 'Indy', 'Jules']
POSITIONS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']
FULL = dict(zip(POSITIONS, NAMES))  # Jules on the bench


@pytest.fixture(name='app')
def _app(monkeypatch, tmp_path):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path / "start.db"}')

    from app import create_app
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from models import Game, Player, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(id=TEAM_ID, team_name='Test Team', registration_code='test-code',
                 age_group='11U', pitching_rule_set='MLB Pitch Smart', outfielder_count=3,
                 timezone='America/Indiana/Indianapolis'),
            User(id=1, username='coach', full_name='Test Coach',
                 password_hash=generate_password_hash('password123')),
        ])
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=TEAM_ID, role='Head Coach', player_order=[]))
        db.session.add(TeamPitchingSettings(team_id=TEAM_ID, competition_default_rule='USSSA',
                                            arm_care_rule_set='MLB Pitch Smart'))
        db.session.add(Game(id=GAME_ID, team_id=TEAM_ID, date=datetime(2026, 10, 10, 10, 0, 0),
                            opponent='Visitors', is_live=False))
        for index, name in enumerate(NAMES, start=1):
            db.session.add(Player(id=index, team_id=TEAM_ID, name=name, number=str(index)))
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['team_id'] = TEAM_ID
        session['role'] = 'Head Coach'
    return client


def _plan(app, innings):
    from db import db
    from models import Rotation

    with app.app_context():
        rotation = db.session.query(Rotation).filter_by(associated_game_id=GAME_ID).first()
        if rotation is None:
            db.session.add(Rotation(title='Rotation', innings=innings,
                                    associated_game_id=GAME_ID, team_id=TEAM_ID))
        else:
            rotation.innings = innings
        db.session.commit()


def _out(app, *names):
    from db import db
    from models import Player, PlayerGameAbsence

    with app.app_context():
        for name in names:
            player = db.session.query(Player).filter_by(name=name).one()
            db.session.add(PlayerGameAbsence(player_id=player.id, game_id=GAME_ID, team_id=TEAM_ID))
        db.session.commit()


def _live(app):
    from db import db
    from models import Game

    with app.app_context():
        db.session.expire_all()
        return bool(db.session.get(Game, GAME_ID).is_live)


def _start(app, **body):
    response = _client(app).post(START, json=body)
    return response.status_code, response.get_json()


def _without(alignment, *positions):
    return {pos: name for pos, name in alignment.items() if pos not in positions}


# --- Starts normally --------------------------------------------------------------------------

def test_a_complete_first_inning_starts_with_exactly_that_defense(app):
    _plan(app, {'1': FULL})
    status, body = _start(app, inning_one=FULL)
    assert status == 200, body
    assert _live(app)
    assert body['state']['current_alignment'] == FULL


def test_batting_order_and_later_innings_never_block(app):
    # No lineup at all; innings 2-6 empty.
    _plan(app, {'1': FULL, '2': {}, '3': _without(FULL, 'P', 'CF')})
    readiness = _client(app).get(READINESS).get_json()
    assert readiness['ready'] is True and readiness['missing'] == []
    status, body = _start(app, inning_one=FULL)
    assert status == 200, body


# --- Hard stops -------------------------------------------------------------------------------

@pytest.mark.parametrize('inning_one, out, message', [
    (_without(FULL, 'P'), (), 'Choose the starting pitcher for the 1st inning.'),
    (dict(FULL, SS='Alex'), (), 'Alex is assigned to both P and SS in the 1st inning.'),
    (dict(FULL, CF='Zed'), (), 'Zed is at CF in the 1st inning but is not on the roster.'),
    (FULL, ('Eli',), 'Eli is marked Out but is at 3B in the 1st inning.'),
], ids=['no-pitcher', 'duplicate', 'not-on-roster', 'marked-out'])
def test_integrity_problems_are_hard_stops_with_specific_messages(app, inning_one, out, message):
    _plan(app, {'1': inning_one})
    _out(app, *out)

    readiness = _client(app).get(READINESS).get_json()
    assert readiness['ready'] is False
    assert message in readiness['hard_stops']
    assert readiness['missing'] == readiness['hard_stops']
    assert 'Finish the Inning 1 defense.' not in readiness['missing']

    status, body = _start(app, inning_one=inning_one, open_positions=readiness['open_positions'])
    assert status == 409, body
    assert body['code'] == 'start_hard_stops'
    assert message in body['hard_stops']
    assert not _live(app)


# --- Open positions are the coach's call ------------------------------------------------------

def test_one_open_position_is_asked_about_not_blocked(app):
    _plan(app, {'1': _without(FULL, 'CF')})
    readiness = _client(app).get(READINESS).get_json()
    assert readiness['ready'] is True
    assert readiness['open_positions'] == ['CF']
    assert readiness['open_question'] == {
        'title': '1st inning: CF is open',
        'message': 'CF is open for the 1st inning. On the bench: Harper, Jules.',
        'positions': ['CF'],
        'start_label': 'Start with CF Open',
    }

    status, body = _start(app, inning_one=_without(FULL, 'CF'))
    assert status == 409, body
    assert body['code'] == 'start_open_positions'
    assert body['acknowledgement_outdated'] is False
    assert not _live(app)


def test_start_with_cf_open_starts_with_exactly_that_defense(app):
    plan = _without(FULL, 'CF')
    _plan(app, {'1': plan})
    status, body = _start(app, inning_one=plan, open_positions=['CF'])
    assert status == 200, body
    assert _live(app)
    assert {pos: n for pos, n in body['state']['current_alignment'].items() if n} == plan


def test_eight_players_can_deliberately_start_short_handed(app):
    _out(app, 'Jules', 'Harper')  # 8 available for 9 positions
    plan = _without(FULL, 'CF')
    _plan(app, {'1': plan})
    question = _client(app).get(READINESS).get_json()['open_question']
    assert question['message'] == (
        'Only 8 players are available, so one position is open. CF is open for the 1st inning.'
    )
    # CoachBoard asks even here: which position is open is the coach's call.
    status, body = _start(app, inning_one=plan)
    assert status == 409 and body['code'] == 'start_open_positions', body
    status, body = _start(app, inning_one=plan, open_positions=['CF'])
    assert status == 200, body


@pytest.mark.parametrize('open_positions, title, start_label', [
    (['CF', 'RF'], '1st inning: CF and RF are open', 'Start with CF and RF Open'),
    (['LF', 'CF', 'RF'], '1st inning: LF, CF, and RF are open', 'Start with LF, CF, and RF Open'),
])
def test_several_open_positions_are_named_together(app, open_positions, title, start_label):
    _plan(app, {'1': _without(FULL, *open_positions)})
    question = _client(app).get(READINESS).get_json()['open_question']
    assert question['title'] == title
    assert question['start_label'] == start_label
    assert question['positions'] == open_positions


def test_an_acknowledgement_for_other_open_positions_does_not_count(app):
    # The acknowledgement must name exactly the positions open now: here the
    # request says only CF, but CF and LF are open.
    plan = _without(FULL, 'CF', 'LF')
    _plan(app, {'1': plan})
    status, body = _start(app, inning_one=plan, open_positions=['CF'])
    assert status == 409, body
    assert body['code'] == 'start_open_positions'
    assert body['acknowledgement_outdated'] is True
    assert body['open_positions'] == ['LF', 'CF']
    assert not _live(app)


# --- The reviewed defense is the stored one ---------------------------------------------------

@pytest.mark.parametrize('stored', [
    FULL,                               # another tab filled CF
    _without(FULL, 'CF', 'LF'),         # another tab also opened LF
    dict(_without(FULL, 'CF'), SS='Jules', LF='Finn'),  # a move elsewhere
], ids=['cf-filled', 'lf-opened', 'moved'])
def test_a_stale_reviewed_defense_is_refused(app, stored):
    reviewed = _without(FULL, 'CF')
    _plan(app, {'1': stored})
    status, body = _start(app, inning_one=reviewed, open_positions=['CF'])
    assert status == 409, body
    assert body['code'] == 'start_defense_changed'
    assert body['message'] == 'The 1st inning defense changed. Review it before starting.'
    assert not _live(app)


def test_blank_positions_in_the_reviewed_defense_are_just_open(app):
    plan = _without(FULL, 'CF')
    _plan(app, {'1': dict(plan, CF='')})
    status, body = _start(app, inning_one=dict(plan, CF='  '), open_positions=['CF'])
    assert status == 200, body


def test_a_save_arriving_during_start_cannot_replace_the_reviewed_defense(app, monkeypatch):
    """Start holds the game lock from its read to its commit; a plan save
    that arrives meanwhile waits, then sees the live game and is refused."""
    from blueprints import live_game_api

    plan = _without(FULL, 'CF')
    _plan(app, {'1': plan})
    rotation_id = None
    from db import db
    from models import Rotation
    with app.app_context():
        rotation_id = db.session.query(Rotation).filter_by(associated_game_id=GAME_ID).one().id

    real = live_game_api.can_start_game

    def check_then_yield(*args, **kwargs):
        result = real(*args, **kwargs)
        eventlet.sleep(0.1)  # between Start's checks and its commit
        return result

    monkeypatch.setattr(live_game_api, 'can_start_game', check_then_yield)

    starting = eventlet.spawn(_start, app, inning_one=plan, open_positions=['CF'])
    eventlet.sleep(0.02)
    saving = eventlet.spawn(lambda: _client(app).post('/save_rotation', json={
        'id': rotation_id, 'title': 'Rotation', 'associated_game_id': GAME_ID,
        'innings': {'1': FULL},
    }))

    status, body = starting.wait()
    saved = saving.wait()
    assert status == 200, body
    assert saved.status_code == 409, saved.get_json()
    assert {pos: n for pos, n in body['state']['current_alignment'].items() if n} == plan
    with app.app_context():
        db.session.expire_all()
        stored = db.session.get(Rotation, rotation_id).innings['1']
        assert {pos: n for pos, n in stored.items() if n} == plan


# --- A Start request must say what the coach reviewed ------------------------------------------

@pytest.mark.parametrize('body', [{}, {'open_positions': []}, {'inning_one': None},
                                  {'inning_one': 'P,C,1B'}],
                         ids=['empty', 'no-inning-one', 'null', 'not-a-defense'])
def test_a_start_without_the_reviewed_first_inning_never_starts(app, body):
    _plan(app, {'1': FULL})
    response = _client(app).post(START, json=body)
    assert response.status_code == 409
    payload = response.get_json()
    assert payload['code'] == 'start_refresh_required'
    assert payload['title'] == 'Refresh Prepare Game before starting.'
    assert payload['message'] == "CoachBoard needs to verify the 1st inning defense you're starting with."
    assert not _live(app)


def test_an_old_tab_cannot_start_after_another_coach_changes_the_defense(app):
    reviewed = dict(FULL)
    _plan(app, {'1': reviewed})
    # Another coach moves players; the old tab still shows `reviewed`.
    _plan(app, {'1': dict(FULL, SS='Jules', LF='Finn', RF='Gray', **{'2B': 'Indy'})})
    status, body = _start(app, inning_one=reviewed)
    assert status == 409, body
    assert body['code'] == 'start_defense_changed'
    assert not _live(app)
