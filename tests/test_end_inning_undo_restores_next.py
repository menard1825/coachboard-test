"""Undoing an inning start gives back the Next Inning defense that started it.

End Inning starts the next inning with the saved Next Inning defense and
then clears it. Undo used to bring the inning back without that defense: the
board re-seeded an automatic one ("Same defense as the 3rd"), and the
coach's edits for the inning were gone, reload or not. Undo now restores the
exact saved defense -- alignment, source, who chose it, and what its own
Undo would bring back -- with a new revision, so a screen that never saw the
restore can't undo against it.

The game (tests/test_pitcher_carry_forward.py) follows the planned
rotation; Bennett takes over from the 3rd.
"""
from test_pitcher_carry_forward import (
    PLAN, PREP, _end_inning, _field, _filled, _game, _prep, _sequence, _state,
)


def _undo(client):
    response = client.post('/api/live-game/70/undo', json={'base_sequence': _sequence(client)})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _edit_4th(client):
    """The coach swaps left and right field in the 4th."""
    base = _prep(client)['confirmed']
    edited = dict(base['alignment'], LF=base['alignment']['RF'], RF=base['alignment']['LF'])
    response = client.post(PREP, json={'mode': 'custom', 'alignment': edited,
                                       'base_alignment': base['alignment'], 'inning': '4'})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()['confirmed']


def test_undo_restores_the_coachs_saved_defense_for_the_inning(monkeypatch):
    app, client = _game(monkeypatch)
    for _ in range(2):
        _end_inning(client)                                         # in the 3rd
    saved = _edit_4th(client)
    assert saved['source'] == 'custom' and saved['updated_by'] != 'Auto'

    assert _field(_end_inning(client)) == _filled(saved['alignment'])
    undone = _undo(client)
    assert undone['undone'] == 'Undid starting the 4th. Back in the 3rd.'

    restored = _prep(client)['confirmed']
    assert restored['inning'] == '4'
    assert restored['alignment'] == saved['alignment']
    assert (restored['source'], restored['updated_by']) == (saved['source'], saved['updated_by'])
    assert restored['previous'] == saved['previous']                # its own Undo still works
    assert restored['revision'] > saved['revision']

    # A reload reads the same.
    assert _prep(client)['confirmed'] == restored


def test_the_restored_defense_keeps_its_safeguards(monkeypatch):
    app, client = _game(monkeypatch)
    for _ in range(2):
        _end_inning(client)
    saved = _edit_4th(client)
    _end_inning(client)
    _undo(client)
    restored = _prep(client)['confirmed']

    # An Undo from a screen that saw the defense before the inning started
    # is refused; one that saw the restore takes back the coach's edit.
    stale = client.post(PREP, json={'mode': 'undo', 'base_revision': saved['revision'],
                                    'base_alignment': restored['alignment'], 'inning': '4'})
    assert stale.status_code == 409 and stale.get_json()['code'] == 'next_prep_conflict'
    response = client.post(PREP, json={'mode': 'undo', 'base_revision': restored['revision'],
                                       'base_alignment': restored['alignment'], 'inning': '4'})
    assert response.status_code == 200, response.get_data(as_text=True)
    back = response.get_json()['confirmed']
    assert back['updated_by'] == 'Auto' and back['source'] == 'planned'

    # Starting the inning again sends the defense now saved.
    assert _field(_end_inning(client)) == _filled(back['alignment'])


def test_an_automatic_defense_comes_back_automatic(monkeypatch):
    app, client = _game(monkeypatch)
    for _ in range(2):
        _end_inning(client)
    auto = _prep(client)['confirmed']
    assert auto['updated_by'] == 'Auto'
    _end_inning(client)
    _undo(client)
    restored = _prep(client)['confirmed']
    assert restored['alignment'] == auto['alignment']
    assert (restored['source'], restored['updated_by']) == ('planned', 'Auto')


def test_undoing_two_starts_restores_each_inning(monkeypatch):
    app, client = _game(monkeypatch)
    for _ in range(2):
        _end_inning(client)
    third = _prep(client)['confirmed']                              # (already started)
    saved = _edit_4th(client)
    _end_inning(client)                                             # the 4th
    _undo(client)                                                   # back in the 3rd
    assert _prep(client)['confirmed']['alignment'] == saved['alignment']
    _undo(client)                                                   # back in the 2nd
    state = _state(client)
    assert state['current_inning'] == '2'
    restored = _prep(client)['confirmed']
    assert restored['inning'] == '3'
    assert _filled(restored['alignment']) == PLAN['3']
    assert third['inning'] == '4'
