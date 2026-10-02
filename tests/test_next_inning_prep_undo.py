"""Undo next-inning edit: one previous saved defense, kept on the server.

Every coach save of the Next Inning defense keeps the defense it replaced --
alignment, source, and who chose it ('Auto' when nobody did). Undo restores
exactly that, so it survives a reload and puts back "not chosen" (the
automatic defense that follows the field and the plan) as well as a choice.
An Undo names the revision it saw; one from a screen that missed a newer
save (another device's) is refused instead of overwriting it.

The game (tests/test_live_game_pregame_plan_api.py) is in the 2nd; the 3rd
is planned as INNING_THREE.
"""
from test_live_game_pregame_plan_api import INNING_THREE, INNING_TWO, _build_app, _login


PATH = '/api/live-game/70/next-inning-prep'
EDIT = dict(INNING_THREE, LF='Jack')          # Jack in for Gavin
OTHER = dict(INNING_THREE, CF='Jack')         # another device: Jack in for Hudson


def _client(app):
    client = app.test_client()
    _login(client)
    return client


def _get(client):
    response = client.get(PATH)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()['confirmed']


def _save(client, alignment=None, mode='custom'):
    confirmed = _get(client)
    body = {'mode': mode, 'base_alignment': confirmed['alignment'], 'inning': '3'}
    if alignment is not None:
        body['alignment'] = alignment
    response = client.post(PATH, json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()['confirmed']


def _undo(client, revision):
    confirmed = _get(client)
    return client.post(PATH, json={
        'mode': 'undo', 'base_alignment': confirmed['alignment'], 'inning': '3', 'base_revision': revision})


def _filled(alignment):
    return {pos: name for pos, name in alignment.items() if name}


def test_undo_restores_the_automatic_defense_and_its_status(monkeypatch):
    app = _build_app(monkeypatch)
    client = _client(app)
    auto = _get(client)
    assert auto['updated_by'] == 'Auto' and auto['source'] == 'planned' and auto['previous'] is None

    saved = _save(client, EDIT)
    assert saved['previous'] == {'alignment': auto['alignment'], 'source': 'planned', 'updated_by': 'Auto'}

    response = _undo(client, saved['revision'])
    assert response.status_code == 200, response.get_data(as_text=True)
    restored = response.get_json()['confirmed']
    assert _filled(restored['alignment']) == INNING_THREE
    assert restored['source'] == 'planned'
    assert restored['updated_by'] == 'Auto'            # nobody chose it, again
    assert restored['previous'] is None                # one step

    again = _undo(client, restored['revision'])
    assert again.status_code == 409
    assert again.get_json()['message'] == 'There is no next-inning edit to undo.'


def test_undo_survives_a_reload(monkeypatch):
    app = _build_app(monkeypatch)
    saved = _save(_client(app), EDIT)

    reloaded = _client(app)                            # a fresh page, same coach
    confirmed = _get(reloaded)
    assert confirmed['previous']['alignment'] is not None
    response = _undo(reloaded, confirmed['revision'])
    assert response.status_code == 200
    assert _filled(response.get_json()['confirmed']['alignment']) == INNING_THREE
    assert saved['revision'] == confirmed['revision']


def test_undo_restores_an_explicit_choice_with_its_source(monkeypatch):
    app = _build_app(monkeypatch)
    client = _client(app)
    kept = _save(client, mode='current')               # "Same defense": the coach's choice
    assert kept['source'] == 'current' and kept['updated_by'] != 'Auto'

    edited = _save(client, EDIT)
    restored = _undo(client, edited['revision']).get_json()['confirmed']
    assert _filled(restored['alignment']) == INNING_TWO
    assert restored['source'] == 'current'
    assert restored['updated_by'] == kept['updated_by']


def test_an_undo_from_a_screen_that_missed_a_newer_save_is_refused(monkeypatch):
    app = _build_app(monkeypatch)
    phone, tablet = _client(app), _client(app)
    mine = _save(phone, EDIT)
    theirs = _save(tablet, OTHER)                      # another device, after mine
    assert theirs['revision'] == mine['revision'] + 1

    stale = _undo(phone, mine['revision'])
    assert stale.status_code == 409
    assert stale.get_json()['code'] == 'next_prep_conflict'
    assert _filled(_get(phone)['alignment']) == OTHER  # theirs stands

    # Seen the newer save, Undo takes that one back.
    response = _undo(phone, theirs['revision'])
    assert response.status_code == 200
    assert _filled(response.get_json()['confirmed']['alignment']) == EDIT


def test_an_undo_without_a_revision_is_refused(monkeypatch):
    app = _build_app(monkeypatch)
    client = _client(app)
    _save(client, EDIT)
    response = client.post(PATH, json={'mode': 'undo', 'inning': '3'})
    assert response.status_code == 409
    assert response.get_json()['code'] == 'next_prep_conflict'
    assert _filled(_get(client)['alignment']) == EDIT


def test_an_unchanged_save_keeps_what_undo_brings_back(monkeypatch):
    app = _build_app(monkeypatch)
    client = _client(app)
    saved = _save(client, EDIT)
    again = _save(client, EDIT)
    assert again['previous'] == saved['previous']


def test_undo_will_not_put_back_a_player_who_left(monkeypatch):
    app = _build_app(monkeypatch)
    client = _client(app)
    saved = _save(client, EDIT)                        # Gavin out of the 3rd
    left = client.post('/api/live-game/70/availability',
                       json={'action': 'left', 'player_id': 7, 'base_sequence': 0})
    assert left.status_code == 200, left.get_data(as_text=True)

    response = _undo(client, saved['revision'])
    assert response.status_code == 409
    assert response.get_json()['message'] == "Can't undo: Gavin is not available for this game."
    assert _filled(_get(client)['alignment']) == EDIT
