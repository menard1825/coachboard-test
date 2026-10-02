"""Here now / Left this inning: live availability changes.

The Bench Report's actions write the 'Player Arrived' / 'Player Left' events
game_availability already replays, from the inning being played. First-pitch
attendance (PlayerGameAbsence) is never rewritten, earlier innings keep who
was here in them, and live Undo takes the change back.

The game (tests/test_live_game_pregame_plan_api.py) is in the 2nd. Kai, an
11th player added here, sits the 2nd and is not in the 3rd-inning plan.
"""
from test_live_game_pregame_plan_api import INNING_ONE, INNING_TWO, _add_event, _build_app, _login, _prep


KAI = 11
JACK = 10


def _game(monkeypatch, jack_out=False):
    app = _build_app(monkeypatch)

    from db import db
    from models import Player, PlayerGameAbsence

    with app.app_context():
        db.session.add(Player(id=KAI, name='Kai', number='11', team_id=1))
        if jack_out:
            db.session.add(PlayerGameAbsence(player_id=JACK, game_id=70, team_id=1))
        db.session.commit()
    _add_event(app, 1, 'End Inning', '2', before=INNING_ONE, after=INNING_TWO)
    client = app.test_client()
    _login(client)
    return app, client


def _state(client):
    response = client.get('/api/live-game/70/state')
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _change(client, action, player_id, base_sequence=1):
    return client.post('/api/live-game/70/availability', json={
        'action': action, 'player_id': player_id, 'base_sequence': base_sequence})


def _events(app):
    from models import GameRotationEvent

    with app.app_context():
        return [(e.event_type, e.inning, e.subject_player_id, e.effective_inning, e.reverted)
                for e in GameRotationEvent.query.order_by(GameRotationEvent.sequence).all()]


def _absences(app):
    from models import PlayerGameAbsence

    with app.app_context():
        return sorted(a.player_id for a in PlayerGameAbsence.query.all())


def test_left_this_inning_records_a_departure_from_this_inning(monkeypatch):
    app, client = _game(monkeypatch)

    response = _change(client, 'left', KAI)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert _events(app)[-1] == ('Player Left', '2', KAI, 2, False)
    assert _absences(app) == []                                  # first-pitch attendance untouched
    state = response.get_json()['state']
    assert 'Kai' not in {p['name'] for p in state['roster']}
    assert [p['name'] for p in state['not_here']] == ['Kai']
    # Kai was here for the 1st: still available there.
    assert 'Kai' in _prep(client)['played_innings']['1']['available']


def test_here_now_records_an_arrival_and_keeps_first_pitch_outs(monkeypatch):
    app, client = _game(monkeypatch, jack_out=True)
    assert [p['name'] for p in _state(client)['not_here']] == ['Jack']

    response = _change(client, 'arrived', JACK)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert _events(app)[-1] == ('Player Arrived', '2', JACK, 2, False)
    assert _absences(app) == [JACK]                              # still Out at first pitch
    state = response.get_json()['state']
    assert state['not_here'] == []
    assert 'Jack' in {p['name'] for p in state['roster']}
    assert 'Jack' not in _prep(client)['played_innings']['1']['available']


def test_a_player_on_the_field_or_in_the_next_defense_cannot_leave(monkeypatch):
    app, client = _game(monkeypatch)
    before = _events(app)

    on_field = _change(client, 'left', 1)                         # Aiden pitches the 2nd
    assert on_field.status_code == 409
    assert on_field.get_json()['message'] == 'Aiden is at P. Take them off the field first.'

    in_next = _change(client, 'left', 7)                          # Gavin: LF in the 3rd's plan
    assert in_next.status_code == 409
    assert 'Gavin is at LF in the next inning' in in_next.get_json()['message']

    assert _events(app) == before


def test_no_double_arrival_or_departure_and_stale_screens_are_refused(monkeypatch):
    app, client = _game(monkeypatch)

    assert _change(client, 'arrived', KAI).status_code == 409    # already here
    assert _change(client, 'left', KAI, base_sequence=0).get_json()['code'] == 'stale_live_state'
    assert _change(client, 'left', KAI).status_code == 200
    assert _change(client, 'left', KAI, base_sequence=2).status_code == 409   # already gone
    assert _change(client, 'shrug', KAI, base_sequence=2).status_code == 400


def test_undo_takes_back_the_departure_and_leaves_earlier_innings_alone(monkeypatch):
    app, client = _game(monkeypatch)
    assert _change(client, 'left', KAI).status_code == 200
    played_before = _prep(client)['played_innings']

    response = client.post('/api/live-game/70/undo', json={'base_sequence': 2})

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()['undone'] == 'Undid marking a player as gone.'
    state = response.get_json()['state']
    assert state['current_inning'] == '2'                         # the End Inning stands
    assert 'Kai' in {p['name'] for p in state['roster']}
    assert state['not_here'] == []
    assert _events(app)[0] == ('End Inning', '2', None, None, False)
    assert _prep(client)['played_innings'] == played_before
