"""A planned pitching takeover carries forward; an old plan never brings a
removed pitcher back on its own.

The saved plan is one defense per inning. Filling every inning with the
starting defense and then planning "Bennett from the 3rd" leaves the 4th-6th
still naming Aiden at P -- the plan cannot say whether that is a leftover or
a decision to bring Aiden back. During the game, a plan that names a pitcher
who already came out is not applied automatically: the pitcher on the mound
carries on, trading places with the returning pitcher so every other
position keeps its plan. A plan naming a new pitcher (Carter in the 6th) is
a planned change and is kept. A coach's own Next Inning defense is never
overridden, and the saved plan (Pregame Plan) is unchanged.
"""
from test_live_game_pregame_plan_api import _build_app, _login


BASE = {
    'P': 'Aiden', 'C': 'Bennett', '1B': 'Carter', '2B': 'Drew', '3B': 'Eli',
    'SS': 'Finn', 'LF': 'Gavin', 'CF': 'Hudson', 'RF': 'Isaac',
}


def _rotated(inning):
    """The starting defense as first filled in, with the outfield and the
    bench rotating every inning (Jack in for one outfielder)."""
    alignment = dict(BASE)
    out = ['LF', 'CF', 'RF'][inning % 3]
    alignment[out] = 'Jack'
    return alignment


PLAN = {str(i): _rotated(i) for i in range(1, 7)}
# Bennett takes over from the 3rd: he pitches, Aiden catches -- the 3rd only.
PLAN['3'] = dict(_rotated(3), P='Bennett', C='Aiden')
# A third pitcher planned for the 6th: Carter pitches, Aiden plays first.
PLAN['6'] = dict(_rotated(6), P='Carter', **{'1B': 'Aiden'})

PREP = '/api/live-game/70/next-inning-prep'


def _game(monkeypatch):
    app = _build_app(monkeypatch)
    from db import db
    from game_pitching_rules import GamePitchingRule
    from models import Game, Rotation

    with app.app_context():
        db.session.get(Rotation, 1).innings = {k: dict(v) for k, v in PLAN.items()}
        db.session.get(Game, 70).live_current_inning = '1'
        # Event rules selected, so End Inning can check each new pitcher.
        db.session.add(GamePitchingRule(game_id=70, team_id=1, rule_set='USSSA'))
        db.session.commit()
    client = app.test_client()
    _login(client)
    return app, client


def _prep(client):
    response = client.get(PREP)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _state(client):
    return client.get('/api/live-game/70/state').get_json()


def _sequence(client):
    events = _state(client)['rotation_events']
    return max([int(e['sequence']) for e in events if not e['reverted']] or [0])


def _end_inning(client):
    confirmed = _prep(client)['confirmed']
    response = client.post('/api/live-game/70/advance-inning', json={
        'alignment': confirmed['alignment'], 'next_prep_id': confirmed['id'],
        'base_sequence': _sequence(client)})
    assert response.status_code == 200, response.get_data(as_text=True)
    return _state(client)


def _field(state):
    return {pos: name for pos, name in state['current_alignment'].items() if name}


def _filled(alignment):
    return {pos: name for pos, name in alignment.items() if name}


def _carried(inning):
    """The inning's plan with Bennett carried on at P and Aiden in his spot."""
    plan = dict(PLAN[inning])
    spot = next(pos for pos, name in plan.items() if name == 'Bennett')
    plan['P'], plan[spot] = 'Bennett', 'Aiden'
    return plan


def test_bennett_takes_over_from_the_3rd_and_keeps_pitching(monkeypatch):
    app, client = _game(monkeypatch)
    assert _field(_end_inning(client)) == PLAN['2']
    assert _field(_end_inning(client)) == PLAN['3']                 # the planned takeover

    prep = _prep(client)                                            # the 4th
    assert _filled(prep['confirmed']['alignment']) == _carried('4')
    assert prep['confirmed']['source'] == 'planned' and prep['confirmed']['updated_by'] == 'Auto'
    assert prep['pitcher_carry'] == {'pitcher': 'Bennett', 'planned_pitcher': 'Aiden', 'position': 'C'}
    assert _filled(prep['planned_seed']) == _carried('4')
    # The saved plan is the reference, unchanged.
    assert prep['planned_alignment'] == PLAN['4']
    assert prep['pregame_rotation']['4'] == PLAN['4']

    assert _field(_end_inning(client)) == _carried('4')
    assert _field(_end_inning(client)) == _carried('5')            # still Bennett in the 5th
    # The outfield and bench kept rotating as planned.
    assert [_carried(i)['LF'] for i in '45'] == [PLAN['4']['LF'], PLAN['5']['LF']]
    assert _carried('4')['CF'] == 'Jack' and _carried('5')['RF'] == 'Jack'


def test_a_later_third_pitcher_is_still_planned(monkeypatch):
    app, client = _game(monkeypatch)
    for _ in range(5):
        _end_inning(client)                                         # into the 5th
    prep = _prep(client)                                            # the 6th
    assert prep['pitcher_carry'] is None
    assert _filled(prep['confirmed']['alignment']) == PLAN['6']    # Carter pitches
    assert _field(_end_inning(client)) == PLAN['6']


def test_no_duplicates_and_no_one_else_moves(monkeypatch):
    app, client = _game(monkeypatch)
    for _ in range(2):
        _end_inning(client)
    alignment = _filled(_prep(client)['confirmed']['alignment'])
    assert len(set(alignment.values())) == len(alignment)
    moved = {pos for pos in alignment if alignment[pos] != PLAN['4'].get(pos)}
    assert moved == {'P', 'C'}


def test_using_the_saved_plan_uses_the_carried_pitcher(monkeypatch):
    app, client = _game(monkeypatch)
    for _ in range(2):
        _end_inning(client)
    base = _prep(client)['confirmed']['alignment']
    # The coach keeps the field, then picks the 4th-inning plan again.
    assert client.post(PREP, json={'mode': 'current', 'base_alignment': base, 'inning': '4'}).status_code == 200
    base = _prep(client)['confirmed']['alignment']
    response = client.post(PREP, json={'mode': 'planned', 'base_alignment': base, 'inning': '4'})
    assert response.status_code == 200, response.get_data(as_text=True)
    confirmed = response.get_json()['confirmed']
    assert _filled(confirmed['alignment']) == _carried('4')
    assert confirmed['source'] == 'planned'


def test_a_coach_can_still_bring_the_pitcher_back_explicitly(monkeypatch):
    app, client = _game(monkeypatch)
    for _ in range(2):
        _end_inning(client)
    base = _prep(client)['confirmed']['alignment']
    response = client.post(PREP, json={'mode': 'custom', 'alignment': PLAN['4'],
                                       'base_alignment': base, 'inning': '4'})
    assert response.status_code == 200
    prep = _prep(client)
    assert _filled(prep['confirmed']['alignment']) == PLAN['4']   # the coach's choice stands
    assert prep['confirmed']['source'] == 'custom'


def test_undo_and_reload_keep_the_carried_pitcher(monkeypatch):
    app, client = _game(monkeypatch)
    for _ in range(3):
        _end_inning(client)                                         # into the 4th
    assert _field(_state(client)) == _carried('4')

    # Live Undo of starting the 4th: back in the 3rd, and the 4th is
    # prepared with Bennett carried on again.
    response = client.post('/api/live-game/70/undo', json={'base_sequence': _sequence(client)})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()['state']['current_inning'] == '3'
    assert _filled(_prep(client)['confirmed']['alignment']) == _carried('4')

    # Undo of a next-inning edit puts the carried defense back.
    base = _prep(client)['confirmed']
    edited = dict(_carried('4'), LF=_carried('4')['RF'], RF=_carried('4')['LF'])
    saved = client.post(PREP, json={'mode': 'custom', 'alignment': edited,
                                    'base_alignment': base['alignment'], 'inning': '4'}).get_json()['confirmed']
    undone = client.post(PREP, json={'mode': 'undo', 'base_revision': saved['revision'],
                                     'base_alignment': saved['alignment'], 'inning': '4'})
    assert undone.status_code == 200, undone.get_data(as_text=True)
    assert _filled(undone.get_json()['confirmed']['alignment']) == _carried('4')

    # A fresh read (a reload) gives the same.
    assert _filled(_prep(client)['confirmed']['alignment']) == _carried('4')


def test_the_live_up_next_defense_agrees(monkeypatch):
    app, client = _game(monkeypatch)
    for _ in range(2):
        _end_inning(client)
    state = _state(client)
    assert _filled(state['planned_next_alignment']) == _carried('4')


def test_the_carry_rule_on_its_own():
    from types import SimpleNamespace
    from pitching_eligibility import carry_planned_pitcher

    def event(before, after):
        return SimpleNamespace(reverted=False, before_alignment={'P': before}, after_alignment={'P': after})

    history = [event('Aiden', 'Bennett')]
    plan = dict(BASE)                                               # names Aiden at P
    carried, carry = carry_planned_pitcher(plan, {'P': 'Bennett'}, history)
    assert carried['P'] == 'Bennett' and carried['C'] == 'Aiden' and carry['position'] == 'C'
    # A new pitcher is a planned change; the current one is no change.
    assert carry_planned_pitcher(dict(BASE, P='Carter', **{'1B': 'Aiden'}), {'P': 'Bennett'}, history)[1] is None
    assert carry_planned_pitcher(dict(BASE, P='Bennett', C='Aiden'), {'P': 'Bennett'}, history)[1] is None
    # An undone change removed no one.
    undone = [SimpleNamespace(reverted=True, before_alignment={'P': 'Aiden'}, after_alignment={'P': 'Bennett'})]
    assert carry_planned_pitcher(plan, {'P': 'Bennett'}, undone)[1] is None
    # The carried pitcher was planned to sit: the returning one sits instead.
    benched = {pos: name for pos, name in BASE.items() if pos != 'C'}
    carried, carry = carry_planned_pitcher(benched, {'P': 'Bennett'}, history)
    assert carried['P'] == 'Bennett' and 'Aiden' not in carried.values() and carry['position'] is None
    # The returning pitcher has left the game: their spot is left open.
    carried, _ = carry_planned_pitcher(plan, {'P': 'Bennett'}, history, present_names=set(BASE.values()) - {'Aiden'})
    assert carried['C'] == '' and 'Aiden' not in carried.values()
