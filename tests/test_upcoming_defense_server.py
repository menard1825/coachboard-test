"""The upcoming inning's own plan, offered and kept (live_game_ui).

* planned_seed is the upcoming inning's plan as "Use 2nd-inning plan" sets
  it, or None when that inning has no separate plan (it carries forward).
* A live change carries the field forward over a plan the coach didn't
  choose; once the coach chooses the plan (mode 'planned'), later live
  changes and reads keep it.
"""

from test_start_game_contract import (  # noqa: F401 (app is a fixture)
    FULL,
    GAME_ID,
    _app,
    _client,
    _plan,
)


SECOND = dict(FULL, SS='Eli', **{'3B': 'Finn'})          # the 2nd's own plan
SWAPPED = dict(FULL, LF='Harper', CF='Gray')              # a live change in the 1st
PREP = f'/api/live-game/{GAME_ID}/next-inning-prep'


def _filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def _start(app, innings):
    _plan(app, innings)
    response = _client(app).post(f'/api/live-game/{GAME_ID}/start', json={'inning_one': FULL})
    assert response.status_code == 200, response.get_json()


def _sequence(app):
    state = _client(app).get(f'/api/live-game/{GAME_ID}/state').get_json()
    return max([e['sequence'] for e in state['rotation_events'] if not e.get('reverted')] or [0])


def _live_change(app, alignment):
    response = _client(app).post(f'/api/live-game/{GAME_ID}/defense-edit', json={
        'alignment': alignment, 'base_sequence': _sequence(app)})
    assert response.status_code == 200, response.get_json()


def _prep(app):
    return _client(app).get(PREP).get_json()


def test_a_planned_inning_offers_its_plan(app):
    _start(app, {'1': FULL, '2': SECOND})
    data = _prep(app)
    assert _filled(data['planned_seed']) == SECOND
    assert data['confirmed']['source'] == 'planned'


def test_an_unplanned_inning_has_nothing_to_offer(app):
    _start(app, {'1': FULL})
    _live_change(app, SWAPPED)
    data = _prep(app)
    assert data['planned_seed'] is None
    assert data['confirmed']['source'] == 'current'
    assert _filled(data['confirmed']['alignment']) == SWAPPED


def test_choosing_the_plan_survives_later_live_changes(app):
    _start(app, {'1': FULL, '2': SECOND})
    _live_change(app, SWAPPED)
    carried = _prep(app)
    assert carried['confirmed']['source'] == 'current'
    assert _filled(carried['confirmed']['alignment']) == SWAPPED

    chosen = _client(app).post(PREP, json={
        'mode': 'planned', 'base_alignment': carried['confirmed']['alignment'],
        'inning': carried['next_inning']})
    assert chosen.status_code == 200, chosen.get_json()
    assert _filled(chosen.get_json()['confirmed']['alignment']) == SECOND

    _live_change(app, FULL)                       # another change in the 1st
    kept = _prep(app)
    assert kept['confirmed']['source'] == 'planned'
    assert _filled(kept['confirmed']['alignment']) == SECOND
