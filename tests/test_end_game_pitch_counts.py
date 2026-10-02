"""End Game pitching stats: everyone who pitched, and nothing saved is lost.

POST /api/live-game/<id>/end-with-pitching saves each pitcher's GameChanger
count and innings. Only what is sent changes:

* a pitcher left out of a submission keeps their saved count and innings;
* a field left out (no 'pitches', or no innings) keeps its saved value;
* an explicit blank means "no count yet" -- never 0 -- and a 0 is a count;
* a pitcher with nothing sent and nothing saved gets no row, so the pitching
  summary keeps saying "count needed" (unrecorded_pitching).

Who pitched comes from the game's history, found on the whole team, so a
pitcher marked unavailable later in the game is still there.

The game (tests/test_live_game_pregame_plan_api.py) is in the 2nd: Aiden
pitched the 1st and the start of the 2nd, then Bennett came in. Aiden then
left the game.
"""
from datetime import date

from test_live_game_pregame_plan_api import INNING_ONE, INNING_TWO, _add_event, _build_app, _login


AIDEN, BENNETT = 1, 2
RELIEVED = dict(INNING_TWO, P='Bennett', C='Aiden', **{'1B': 'Carter'})
GAME_DAY = date(2026, 8, 30)


def _game(monkeypatch, aiden_left=True):
    app = _build_app(monkeypatch)
    _add_event(app, 1, 'End Inning', '2', before=INNING_ONE, after=INNING_TWO)
    _add_event(app, 2, 'Pitcher Change', '2', before=INNING_TWO, after=RELIEVED)
    if aiden_left:
        benched = {pos: name for pos, name in RELIEVED.items() if name != 'Aiden'}
        benched['C'] = 'Jack'
        _add_event(app, 3, 'Defensive Change', '2', before=RELIEVED, after=benched)
        _add_event(app, 4, 'Player Left', '2', before=benched, after=benched,
                   subject_player_id=AIDEN, effective_inning=2)
    client = app.test_client()
    _login(client)
    return app, client


def _finish(client, counts=None, **extra):
    body = dict(extra)
    if counts is not None:
        body['counts'] = counts
    response = client.post('/api/live-game/70/end-with-pitching', json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _rows(app):
    from models import PitchingOuting

    with app.app_context():
        return {o.player_id: (o.pitches, o.innings)
                for o in PitchingOuting.query.filter_by(game_id=70).order_by(PitchingOuting.id)}


def _state(client):
    return client.get('/api/live-game/70/state').get_json()


def test_a_pitcher_who_left_is_still_in_end_game_stats(monkeypatch):
    app, client = _game(monkeypatch)
    state = _state(client)
    assert 'Aiden' not in {p['name'] for p in state['roster']}           # not here now
    assert 'Aiden' in {p['name'] for p in state['not_here']}             # the stats screen finds them here

    data = _finish(client, [
        {'player_id': AIDEN, 'pitches': 38, 'innings_whole': 1, 'innings_outs': 2},
        {'player_id': BENNETT, 'pitches': 12, 'innings_whole': 0, 'innings_outs': 1},
    ])
    assert data['pitchers'] == ['Aiden', 'Bennett']
    assert data['warnings'] == []
    assert _rows(app) == {AIDEN: (38, 1.2), BENNETT: (12, 0.1)}


def test_reopening_the_stats_shows_the_saved_counts(monkeypatch):
    app, client = _game(monkeypatch)
    _finish(client, [
        {'player_id': AIDEN, 'pitches': 38, 'innings_whole': 1, 'innings_outs': 2},
        {'player_id': BENNETT, 'pitches': 12, 'innings_whole': 0, 'innings_outs': 1},
    ])
    # What the stats screen prefills from, including the pitcher who left.
    log = {o['player_name']: (o['pitches'], o['innings']) for o in _state(client)['game_pitching_log']}
    assert log == {'Aiden': (38, 1.2), 'Bennett': (12, 0.1)}


def test_a_partial_resubmission_keeps_the_other_pitchers_saved_line(monkeypatch):
    app, client = _game(monkeypatch)
    _finish(client, [
        {'player_id': AIDEN, 'pitches': 38, 'innings_whole': 1, 'innings_outs': 2},
        {'player_id': BENNETT, 'pitches': 12, 'innings_whole': 0, 'innings_outs': 1},
    ])

    # Correct Bennett only.
    data = _finish(client, [{'player_id': BENNETT, 'pitches': 14, 'innings_whole': 0, 'innings_outs': 2}])
    assert _rows(app) == {AIDEN: (38, 1.2), BENNETT: (14, 0.2)}
    assert data['warnings'] == []

    # A field left out keeps its value too: Bennett's count only.
    _finish(client, [{'player_id': BENNETT, 'pitches': 15}])
    assert _rows(app) == {AIDEN: (38, 1.2), BENNETT: (15, 0.2)}


def test_a_confirmed_zero_stays_zero(monkeypatch):
    app, client = _game(monkeypatch)
    data = _finish(client, [
        {'player_id': AIDEN, 'pitches': 0, 'innings_whole': 0, 'innings_outs': 0},
        {'player_id': BENNETT, 'pitches': 12, 'innings_whole': 0, 'innings_outs': 1},
    ])
    assert _rows(app)[AIDEN] == (0, 0.0)
    assert data['warnings'] == []

    _finish(client, [{'player_id': BENNETT, 'pitches': 13}])       # Aiden left out
    assert _rows(app)[AIDEN] == (0, 0.0)


def test_a_missing_count_stays_missing(monkeypatch):
    app, client = _game(monkeypatch)
    from unrecorded_pitching import unrecorded_game_outings

    # Only Bennett sent: Aiden has no row, and still reads "count needed".
    data = _finish(client, [{'player_id': BENNETT, 'pitches': 12, 'innings_whole': 0, 'innings_outs': 1}])
    assert _rows(app) == {BENNETT: (12, 0.1)}
    assert any('Pitch Count is missing for: Aiden' in w for w in data['warnings'])
    with app.app_context():
        from models import PitchingOuting
        saved = PitchingOuting.query.filter_by(game_id=70).all()
        placeholders = unrecorded_game_outings(1, saved, GAME_DAY)
    assert [(p.player_id, p.pitches) for p in placeholders] == [(AIDEN, None)]

    # An explicit blank is "no count yet", never 0.
    data = _finish(client, [{'player_id': AIDEN, 'pitches': '', 'innings_whole': None}])
    assert _rows(app)[AIDEN] == (None, None)
    assert any('Pitch Count is missing for: Aiden' in w for w in data['warnings'])


def test_not_ready_yet_still_saves_nothing(monkeypatch):
    app, client = _game(monkeypatch)
    data = _finish(client, defer_pitching=True)
    assert data['pitching_deferred'] is True and data['warnings'] == []
    assert _rows(app) == {}
    # Entered later through the same endpoint.
    _finish(client, [{'player_id': AIDEN, 'pitches': 38, 'innings_whole': 1, 'innings_outs': 2}])
    assert _rows(app) == {AIDEN: (38, 1.2)}


def test_a_bad_value_is_refused_and_changes_nothing(monkeypatch):
    app, client = _game(monkeypatch)
    _finish(client, [{'player_id': AIDEN, 'pitches': 38, 'innings_whole': 1, 'innings_outs': 2}])
    response = client.post('/api/live-game/70/end-with-pitching',
                           json={'counts': [{'player_id': AIDEN, 'pitches': -3}]})
    assert response.status_code == 400
    assert _rows(app) == {AIDEN: (38, 1.2)}
