"""A Next Inning defense saved before pitcher choices were recorded keeps
its pitcher.

pitcher_chosen (migration f3c9a7d1b8e4) is NULL on defenses saved before it
existed: whether the coach chose that pitcher is unknown. A coach-saved
defense with NULL keeps its pitcher through a live pitching change, like a
chosen one -- intent is never guessed from the saved assignments. The same
holds for the Undo state (previous_pitcher_chosen) and for End Inning
snapshots taken before the keys existed. Automatic defenses carry the live
pitcher as before, and new saves record the choice.

The game is tests/test_pitching_change_keeps_rotation.py's.
"""
from test_pitching_change_keeps_rotation import (
    B, PREP, _change_pitcher, _end_inning, _filled, _prep, _rotation_game, _sequence,
)
from test_saved_next_inning_pitcher import EDIT, _save


def _make_legacy(app, previous=True):
    """As the row would read after the migration: nothing recorded."""
    from db import db
    from blueprints.live_game_ui import GameNextInningPrep

    with app.app_context():
        prep = GameNextInningPrep.query.filter_by(game_id=70).one()
        prep.pitcher_chosen = None
        if previous:
            prep.previous_pitcher_chosen = None
        db.session.commit()


def _undo_next(client):
    confirmed = _prep(client)['confirmed']
    response = client.post(PREP, json={'mode': 'undo', 'base_revision': confirmed['revision'],
                                       'base_alignment': confirmed['alignment'], 'inning': '4'})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()['confirmed']


def test_a_legacy_saved_defense_keeps_its_pitcher(monkeypatch):
    app, client = _rotation_game(monkeypatch)                         # in the 3rd
    assert _save(client, EDIT).status_code == 200
    _make_legacy(app)

    _change_pitcher(client)                                           # Jack in, Aiden to the bench
    prep = _prep(client)
    assert _filled(prep['confirmed']['alignment']) == EDIT            # Aiden still at P, as saved
    assert prep['confirmed']['pitcher_chosen'] is None
    assert prep['pitcher_carry'] is None


def test_a_fielding_edit_on_a_legacy_defense_does_not_guess(monkeypatch):
    app, client = _rotation_game(monkeypatch)
    assert _save(client, EDIT).status_code == 200
    _make_legacy(app)
    # P unchanged from what the board showed: still unknown, not "not chosen".
    later = dict(EDIT, CF='Isaac', RF='Hudson')
    saved = _save(client, later).get_json()['confirmed']
    assert saved['pitcher_chosen'] is None

    _change_pitcher(client)
    assert _filled(_prep(client)['confirmed']['alignment']) == later
    # Its Undo brings back the legacy defense, still unknown, pitcher kept.
    back = _undo_next(client)
    assert _filled(back['alignment']) == EDIT
    assert back['pitcher_chosen'] is None


def test_a_legacy_undo_state_stays_unknown(monkeypatch):
    app, client = _rotation_game(monkeypatch)
    first = dict(B, P='Carter', **{'2B': 'Aiden'})
    assert _save(client, first).status_code == 200
    assert _save(client, dict(first, RF='Gavin')).status_code == 200
    _make_legacy(app)                                                 # both levels unknown

    _change_pitcher(client)
    back = _undo_next(client)
    assert _filled(back['alignment']) == first                        # Carter kept, as saved
    assert back['pitcher_chosen'] is None
    assert _prep(client)['pitcher_carry'] is None


def test_a_legacy_end_inning_snapshot_restores_as_unknown(monkeypatch):
    from db import db
    from models import GameRotationEvent

    app, client = _rotation_game(monkeypatch)
    assert _save(client, EDIT).status_code == 200
    assert _save(client, dict(EDIT, CF='Isaac', RF='Hudson')).status_code == 200
    _end_inning(client)                                               # the 4th starts
    with app.app_context():                                           # a snapshot from e8b2f4a6c913
        event = (GameRotationEvent.query.filter_by(game_id=70)
                 .filter(GameRotationEvent.started_prep.isnot(None))
                 .order_by(GameRotationEvent.sequence.desc()).first())
        snapshot = dict(event.started_prep)
        snapshot.pop('pitcher_chosen')
        snapshot.pop('previous_pitcher_chosen')
        event.started_prep = snapshot
        db.session.commit()

    response = client.post('/api/live-game/70/undo', json={'base_sequence': _sequence(client)})
    assert response.status_code == 200, response.get_data(as_text=True)
    restored = _prep(client)['confirmed']
    assert _filled(restored['alignment']) == dict(EDIT, CF='Isaac', RF='Hudson')
    assert restored['pitcher_chosen'] is None

    _change_pitcher(client)                                           # back in the 3rd
    assert _filled(_prep(client)['confirmed']['alignment']) == dict(EDIT, CF='Isaac', RF='Hudson')
    back = _undo_next(client)                                         # its own Undo, intact
    assert _filled(back['alignment']) == EDIT
    assert back['pitcher_chosen'] is None


def test_an_automatic_defense_still_carries_the_live_pitcher(monkeypatch):
    app, client = _rotation_game(monkeypatch)
    _prep(client)                                                     # seeded, Auto, NULL
    _make_legacy(app)
    _change_pitcher(client)
    confirmed = _prep(client)['confirmed']
    assert confirmed['updated_by'] == 'Auto'
    assert _filled(confirmed['alignment']) == dict(B, P='Jack', **{'1B': 'Aiden'})


def test_a_legacy_use_inning_plan_save_keeps_its_pitcher_and_no_carry_note(monkeypatch):
    app, client = _rotation_game(monkeypatch)
    base = _prep(client)['confirmed']['alignment']
    response = client.post(PREP, json={'mode': 'planned', 'base_alignment': base, 'inning': '4'})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()['confirmed']['updated_by'] != 'Auto'
    _make_legacy(app)

    _change_pitcher(client)
    prep = _prep(client)
    assert _filled(prep['confirmed']['alignment']) == B               # Aiden at P, as saved
    assert prep['pitcher_carry'] is None                              # no "Jack keeps pitching"
