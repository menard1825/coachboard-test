"""A live pitching change keeps the next inning's planned rotation.

Any live change in an inning used to make the next inning carry the whole
current field instead of its plan ("Same defense as the 3rd · Your 4th-inning
plan won't be used"). For a change of pitcher that dropped the next inning's
playing-time rotation, though the coach only changed who pitches
(walkthrough F2).

A change that only changes the pitcher (Change Pitcher, wherever the
relieved pitcher goes) now leaves the next inning on its plan, with the new
pitcher carried forward the way a planned takeover is
(carry_planned_pitcher): the relieved pitcher, already off the mound, takes
the new pitcher's planned spot. The live pitcher pitches the next inning
even if its plan names someone else; a new pitcher planned for a later
inning still takes over then. Any other live change still carries the
field. A Next Inning defense the coach saved is never replaced.
"""
from test_pitcher_carry_forward import (
    PREP, _end_inning, _field, _filled, _game, _prep, _sequence, _state,
)


BASE = {
    'P': 'Aiden', 'C': 'Bennett', '1B': 'Carter', '2B': 'Drew', '3B': 'Eli',
    'SS': 'Finn', 'LF': 'Gavin', 'CF': 'Hudson', 'RF': 'Isaac',
}
A = dict(BASE)                                                      # Jack sits
B = dict(BASE, **{'1B': 'Jack', '2B': 'Carter', 'LF': 'Drew'})     # Gavin sits
# Aiden pitches every inning; the rest rotate between A and B.
PLAN = {'1': A, '2': B, '3': A, '4': B, '5': A, '6': B}


def _rotation_game(monkeypatch, plan=PLAN):
    app, client = _game(monkeypatch)
    from db import db
    from models import Rotation

    with app.app_context():
        db.session.get(Rotation, 1).innings = {k: dict(v) for k, v in plan.items()}
        db.session.commit()
    for _ in range(2):
        _end_inning(client)                                         # in the 3rd
    return app, client


JACK, BENNETT = 10, 2


def _change_pitcher(client, new_pitcher=JACK, destination='BENCH'):
    """A new pitcher comes in: Jack from the bench (Aiden to the bench), or
    Bennett from C with Aiden taking C."""
    response = client.post('/api/live-game/70/change-pitcher', json={
        'base_sequence': _sequence(client), 'new_pitcher_id': new_pitcher,
        'outgoing_destination': destination})
    assert response.status_code == 200, response.get_data(as_text=True)
    return _state(client)


def _carried(plan, pitcher='Jack'):
    """The plan with the new pitcher pitching and Aiden in his planned spot."""
    alignment = dict(plan)
    spot = next(pos for pos, name in plan.items() if name == pitcher and pos != 'P')
    alignment['P'], alignment[spot] = pitcher, 'Aiden'
    return alignment


def test_benching_the_relieved_pitcher_keeps_the_4th_rotation(monkeypatch):
    app, client = _rotation_game(monkeypatch)
    field = _field(_change_pitcher(client))
    assert field['P'] == 'Jack' and 'Aiden' not in field.values()

    prep = _prep(client)
    confirmed = prep['confirmed']
    assert _filled(confirmed['alignment']) == _carried(B)           # the 4th's rotation, Bennett pitching
    assert (confirmed['source'], confirmed['updated_by']) == ('planned', 'Auto')
    assert _filled(prep['planned_seed']) == _carried(B)              # no "plan won't be used" question
    assert prep['pitcher_carry'] == {'pitcher': 'Jack', 'planned_pitcher': 'Aiden', 'position': '1B'}

    assert _field(_end_inning(client)) == _carried(B)
    # The 5th: plan A has Jack sitting, so Aiden takes that sit.
    fifth = _filled(_prep(client)['confirmed']['alignment'])
    assert fifth == dict(A, P='Jack') and 'Aiden' not in fifth.values()


def test_moving_the_relieved_pitcher_to_a_position_keeps_the_rotation(monkeypatch):
    app, client = _rotation_game(monkeypatch)
    field = _field(_change_pitcher(client, BENNETT, destination='C'))
    assert (field['P'], field['C']) == ('Bennett', 'Aiden')
    assert _filled(_prep(client)['confirmed']['alignment']) == _carried(B, 'Bennett')


def test_the_live_pitcher_pitches_the_next_inning_and_a_later_planned_one_takes_over(monkeypatch):
    # The 4th's plan has Carter pitching; the 5th's has Drew.
    fourth = dict(B, P='Carter', **{'2B': 'Aiden'})
    fifth = dict(A, P='Drew', **{'2B': 'Aiden'})
    plan = dict(PLAN, **{'4': fourth, '5': fifth})
    app, client = _rotation_game(monkeypatch, plan)
    _change_pitcher(client)                                         # Jack, live, in the 3rd

    # The coach's live choice pitches the 4th; Carter takes Jack's planned spot.
    confirmed = _filled(_prep(client)['confirmed']['alignment'])
    assert confirmed == dict(fourth, P='Jack', **{'1B': 'Carter'})
    _end_inning(client)
    # The 5th: Drew, a planned new pitcher, takes over as planned.
    assert _filled(_prep(client)['confirmed']['alignment']) == fifth
    assert _prep(client)['pitcher_carry'] is None


def test_any_other_live_change_still_carries_the_field(monkeypatch):
    app, client = _rotation_game(monkeypatch)
    _change_pitcher(client)
    state = _state(client)
    swapped = dict(_field(state), LF=_field(state)['RF'], RF=_field(state)['LF'])
    response = client.post('/api/live-game/70/defense-edit', json={
        'base_sequence': _sequence(client), 'alignment': swapped})
    assert response.status_code == 200, response.get_data(as_text=True)
    confirmed = _prep(client)['confirmed']
    assert _filled(confirmed['alignment']) == swapped
    assert confirmed['source'] == 'current'


def test_a_saved_next_inning_edit_is_kept(monkeypatch):
    app, client = _rotation_game(monkeypatch)
    base = _prep(client)['confirmed']['alignment']
    mine = dict(B, LF=B['RF'], RF=B['LF'])
    response = client.post(PREP, json={'mode': 'custom', 'alignment': mine,
                                       'base_alignment': base, 'inning': '4'})
    assert response.status_code == 200
    _change_pitcher(client)
    confirmed = _prep(client)['confirmed']
    assert _filled(confirmed['alignment']) == mine                  # the coach's 4th stands
    assert confirmed['source'] == 'custom'
