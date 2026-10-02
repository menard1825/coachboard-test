"""A next-inning plan with P open never puts the pitcher in two places.

A plan that leaves P open has the pitcher on the mound carry on. When that
same plan has him at another position too (here the 3rd's plan leaves P
open and puts Aiden, who is pitching, at 1B), filling P used to keep both:
Aiden at P and at 1B. End Inning then refused the defense ("A player cannot
occupy more than one defensive position").

Aiden keeps pitching and the 1B he was planned for is left open -- shown as
an open spot, for the coach to fill with the usual picker. No one is guessed
into it and no one else is moved or benched. Every other planned position,
a coach's saved defense and the saved plan are unchanged.
"""
from pitching_eligibility import project_planned_innings
from test_pitcher_carry_forward import (
    PREP, _end_inning, _field, _filled, _game, _prep, _sequence, _state,
)


BASE = {
    'P': 'Aiden', 'C': 'Bennett', '1B': 'Carter', '2B': 'Drew', '3B': 'Eli',
    'SS': 'Finn', 'LF': 'Gavin', 'CF': 'Hudson', 'RF': 'Isaac',
}
# P open; Aiden planned at 1B, Carter to RF, Isaac sits.
THIRD = dict(BASE, P='', **{'1B': 'Aiden', 'RF': 'Carter'})
PLAN = {'1': BASE, '2': BASE, '3': THIRD, '4': BASE}
# What the 3rd should start with: Aiden pitching, 1B open, the rest as planned.
EXPECTED = dict(THIRD, P='Aiden', **{'1B': ''})


def _open_p_game(monkeypatch):
    app, client = _game(monkeypatch)
    from db import db
    from models import Rotation

    with app.app_context():
        db.session.get(Rotation, 1).innings = {k: dict(v) for k, v in PLAN.items()}
        db.session.commit()
    _end_inning(client)                                             # in the 2nd: Aiden pitching
    return app, client


def _no_duplicates(alignment):
    names = [name for name in alignment.values() if name]
    return len(names) == len(set(names))


def test_the_automatic_next_defense_has_no_duplicate(monkeypatch):
    app, client = _open_p_game(monkeypatch)
    prep = _prep(client)
    confirmed = prep['confirmed']['alignment']
    assert confirmed == EXPECTED
    assert _no_duplicates(confirmed)
    assert _no_duplicates(prep['planned_seed'])
    assert prep['confirmed']['source'] == 'planned'
    # The saved plan is the reference, unchanged.
    assert prep['pregame_rotation']['3'] == THIRD
    assert prep['planned_alignment'] == THIRD
    # A reload prepares the same.
    assert _prep(client)['confirmed']['alignment'] == EXPECTED


def test_using_the_inning_plan_has_no_duplicate(monkeypatch):
    app, client = _open_p_game(monkeypatch)
    base = _prep(client)['confirmed']['alignment']
    assert client.post(PREP, json={'mode': 'current', 'base_alignment': base, 'inning': '3'}).status_code == 200
    base = _prep(client)['confirmed']['alignment']
    response = client.post(PREP, json={'mode': 'planned', 'base_alignment': base, 'inning': '3'})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()['confirmed']['alignment'] == EXPECTED


def test_end_inning_starts_it_with_the_open_spot_and_it_can_be_filled(monkeypatch):
    app, client = _open_p_game(monkeypatch)
    started = _end_inning(client)
    assert started['current_inning'] == '3'
    assert _field(started) == _filled(EXPECTED)                     # 1B open, Isaac not guessed into it
    # Filled the usual way (the field picker's change): Isaac to 1B.
    response = client.post('/api/live-game/70/defense-edit', json={
        'base_sequence': _sequence(client), 'alignment': dict(_filled(EXPECTED), **{'1B': 'Isaac'})})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert _field(_state(client))['1B'] == 'Isaac'


def test_a_coachs_saved_defense_is_not_changed(monkeypatch):
    app, client = _open_p_game(monkeypatch)
    base = _prep(client)['confirmed']['alignment']
    mine = dict(EXPECTED, **{'1B': 'Isaac'})
    response = client.post(PREP, json={'mode': 'custom', 'alignment': mine, 'base_alignment': base, 'inning': '3'})
    assert response.status_code == 200
    assert _prep(client)['confirmed']['alignment'] == mine
    assert _field(_end_inning(client)) == _filled(mine)


def test_a_projected_inning_with_p_open_has_no_duplicate():
    projected = project_planned_innings(PLAN, '2', BASE, [])
    assert projected['3'] == EXPECTED
    assert _no_duplicates(projected['3'])
