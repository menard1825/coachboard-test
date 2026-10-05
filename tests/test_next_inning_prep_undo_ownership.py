"""Undo next-inning edit takes back only the coach's own last save.

Undo used to mean "undo whoever saved last": a coach who had already
received another coach's newer save sent its revision, base_revision
matched, and the other coach's work was reverted. The server now refuses an
Undo unless the save it would take back was made by the signed-in coach
(next_prep_not_yours), and every read says whether this coach may undo
(confirmed.can_undo). Ownership is the saving coach's user id, kept on the
row -- so it survives a reload and the End Inning undo that restores the
row; a row saved before ids were kept falls back to the saved name.

The game (tests/test_live_game_pregame_plan_api.py) is in the 2nd; the 3rd
is planned as INNING_THREE. "coach" (Test Coach) is the head coach;
"assistant" (Second Coach) is added here.
"""

from werkzeug.security import generate_password_hash

from test_live_game_pregame_plan_api import INNING_THREE, _build_app, _login


PATH = '/api/live-game/70/next-inning-prep'
MINE = dict(INNING_THREE, LF='Jack')       # Jack in for Gavin
THEIRS = dict(INNING_THREE, CF='Jack')     # Jack in for Hudson


def _app(monkeypatch):
    app = _build_app(monkeypatch)
    from db import db
    from models import TeamMembership, User

    with app.app_context():
        db.session.add(User(id=2, username='assistant', full_name='Second Coach',
                            password_hash=generate_password_hash('password123')))
        db.session.flush()
        db.session.add(TeamMembership(user_id=2, team_id=1, role='Assistant Coach', player_order=[]))
        db.session.commit()
    return app


def _coach(app):
    client = app.test_client()
    _login(client)
    return client


def _assistant(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'assistant'
        session['team_id'] = 1
        session['role'] = 'Assistant Coach'
    return client


def _get(client):
    response = client.get(PATH)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()['confirmed']


def _save(client, alignment):
    confirmed = _get(client)
    response = client.post(PATH, json={'mode': 'custom', 'alignment': alignment,
                                       'base_alignment': confirmed['alignment'], 'inning': '3'})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()['confirmed']


def _undo(client, confirmed):
    return client.post(PATH, json={'mode': 'undo', 'base_alignment': confirmed['alignment'],
                                   'inning': '3', 'base_revision': confirmed['revision']})


def _filled(alignment):
    return {pos: name for pos, name in alignment.items() if name}


def test_a_coach_may_undo_their_own_save(monkeypatch):
    app = _app(monkeypatch)
    coach = _coach(app)
    assert _get(coach)['can_undo'] is False            # nothing saved yet
    saved = _save(coach, MINE)
    assert saved['can_undo'] is True                    # the save's own response
    response = _undo(coach, saved)
    assert response.status_code == 200, response.get_data(as_text=True)
    restored = response.get_json()['confirmed']
    assert _filled(restored['alignment']) == INNING_THREE
    assert restored['can_undo'] is False                # one step


def test_own_undo_survives_a_reload(monkeypatch):
    app = _app(monkeypatch)
    _save(_coach(app), MINE)
    reloaded = _coach(app)                               # a fresh page, same coach
    confirmed = _get(reloaded)
    assert confirmed['can_undo'] is True
    response = _undo(reloaded, confirmed)
    assert response.status_code == 200, response.get_data(as_text=True)
    assert _filled(response.get_json()['confirmed']['alignment']) == INNING_THREE


def test_another_coach_cannot_undo_my_save(monkeypatch):
    app = _app(monkeypatch)
    coach, assistant = _coach(app), _assistant(app)
    _save(coach, MINE)
    seen = _get(assistant)                               # has received the newest plan
    assert seen['previous'] is not None and seen['can_undo'] is False

    response = _undo(assistant, seen)                    # current revision, not theirs
    assert response.status_code == 409
    body = response.get_json()
    assert body['code'] == 'next_prep_not_yours'
    assert body['message'] == 'That plan was changed by another coach. Nothing was undone.'
    assert _filled(_get(coach)['alignment']) == MINE     # untouched
    assert _get(coach)['can_undo'] is True               # still the coach's to undo


def test_after_another_coach_saves_my_undo_is_refused(monkeypatch):
    app = _app(monkeypatch)
    coach, assistant = _coach(app), _assistant(app)
    mine = _save(coach, MINE)
    _save(assistant, THEIRS)

    # This coach has received the assistant's save: no Undo offered ...
    current = _get(coach)
    assert current['can_undo'] is False
    response = _undo(coach, current)
    assert response.status_code == 409
    assert response.get_json()['code'] == 'next_prep_not_yours'

    # ... and a stale screen still showing its own save gets the same answer.
    stale = _undo(coach, mine)
    assert stale.status_code == 409
    assert stale.get_json()['code'] == 'next_prep_not_yours'
    assert _filled(_get(coach)['alignment']) == THEIRS   # theirs stands

    # The assistant may undo their own save.
    theirs = _get(assistant)
    assert theirs['can_undo'] is True
    assert _undo(assistant, theirs).status_code == 200
    assert _filled(_get(coach)['alignment']) == MINE


def test_the_same_coach_on_two_devices_may_undo_either_save(monkeypatch):
    app = _app(monkeypatch)
    phone, tablet = _coach(app), _coach(app)
    _save(phone, MINE)
    newest = _save(tablet, THEIRS)
    assert _get(phone)['can_undo'] is True
    assert _undo(phone, newest).status_code == 200
    assert _filled(_get(tablet)['alignment']) == MINE


def test_nothing_left_to_undo_has_its_own_code(monkeypatch):
    app = _app(monkeypatch)
    coach = _coach(app)
    saved = _save(coach, MINE)
    restored = _undo(coach, saved).get_json()['confirmed']
    again = _undo(coach, restored)
    assert again.status_code == 409
    assert again.get_json()['code'] == 'next_prep_nothing_to_undo'


def test_a_save_recorded_before_ids_falls_back_to_its_name(monkeypatch):
    app = _app(monkeypatch)
    coach, assistant = _coach(app), _assistant(app)
    _save(coach, MINE)
    from blueprints.live_game_ui import GameNextInningPrep
    from db import db

    with app.app_context():                              # as an older save left it
        prep = GameNextInningPrep.query.filter_by(game_id=70).one()
        prep.updated_by_user_id = None
        assert prep.updated_by == 'Test Coach'
        db.session.commit()

    assert _get(assistant)['can_undo'] is False
    assert _undo(assistant, _get(assistant)).get_json()['code'] == 'next_prep_not_yours'
    assert _get(coach)['can_undo'] is True
    assert _undo(coach, _get(coach)).status_code == 200


def test_ownership_survives_the_end_inning_undo_that_restores_the_row(monkeypatch):
    from blueprints.live_game_ui import GameNextInningPrep, prep_snapshot

    app = _app(monkeypatch)
    _save(_coach(app), MINE)
    with app.app_context():
        snapshot = prep_snapshot(GameNextInningPrep.query.filter_by(game_id=70).one())
    assert snapshot['updated_by_user_id'] == 1
