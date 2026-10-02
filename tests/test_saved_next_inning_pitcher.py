"""A saved Next Inning fielding edit follows a live pitching change.

Saving the 4th on the 2nd Inning tab used to fix its pitcher too: a coach
who moved two fielders, then changed pitchers live, still had the old
pitcher in the saved 4th, and End Inning asked to send him back out.

A save now records whether the coach chose the pitcher (changed P on the
board). A defense whose pitcher was not chosen follows the pitcher the game
would carry -- the shared carry rule: the new pitcher trades places with the
old one, every saved fielding edit stays. A pitcher the coach chose stays
chosen. The saved defense itself is kept, so undoing the live change brings
it back as saved.

The game (tests/test_pitching_change_keeps_rotation.py): Aiden pitches every
inning, the rest rotate A/B; Jack sits in A and plays 1B in B (the 4th).
"""
from test_pitching_change_keeps_rotation import (
    A, B, PREP, _change_pitcher, _end_inning, _field, _filled, _prep, _rotation_game, _sequence,
)


# The coach's 4th: Gavin to RF, Isaac to the bench.
EDIT = dict(B, RF='Gavin')
# After Jack takes over live: Jack pitches, Aiden takes Jack's 1B.
EXPECTED = dict(EDIT, P='Jack', **{'1B': 'Aiden'})


def _save(client, alignment, base=None):
    base = base if base is not None else _prep(client)['confirmed']['alignment']
    return client.post(PREP, json={'mode': 'custom', 'alignment': alignment, 'base_alignment': base, 'inning': '4'})


def _saved_edit(monkeypatch):
    app, client = _rotation_game(monkeypatch)                         # in the 3rd
    response = _save(client, EDIT)
    assert response.status_code == 200, response.get_data(as_text=True)
    saved = response.get_json()['confirmed']
    assert saved['pitcher_chosen'] is False                           # a fielding edit
    return app, client, saved


def test_a_saved_fielding_edit_follows_the_live_pitching_change(monkeypatch):
    app, client, saved = _saved_edit(monkeypatch)
    _change_pitcher(client)                                           # Jack in, Aiden to the bench

    prep = _prep(client)
    confirmed = prep['confirmed']
    assert _filled(confirmed['alignment']) == EXPECTED
    assert (confirmed['source'], confirmed['updated_by']) == ('custom', saved['updated_by'])
    assert prep['pitcher_carry'] == {'pitcher': 'Jack', 'planned_pitcher': 'Aiden', 'position': '1B'}
    assert _prep(client)['confirmed']['alignment'] == confirmed['alignment']     # reload

    # End Inning starts it as shown, with no question about Aiden.
    assert _field(_end_inning(client)) == EXPECTED


def test_a_pitcher_the_coach_chose_stays_chosen(monkeypatch):
    app, client = _rotation_game(monkeypatch)
    chosen = dict(B, P='Carter', **{'2B': 'Aiden'})                   # Carter, picked on the board
    saved = _save(client, chosen).get_json()['confirmed']
    assert saved['pitcher_chosen'] is True
    # A later fielding edit keeps the choice.
    later = dict(chosen, RF='Gavin')
    assert _save(client, later).get_json()['confirmed']['pitcher_chosen'] is True

    _change_pitcher(client)
    prep = _prep(client)
    assert _filled(prep['confirmed']['alignment']) == later           # Carter stays
    assert prep['pitcher_carry'] is None


def test_undoing_the_live_change_brings_the_saved_edit_back(monkeypatch):
    app, client, saved = _saved_edit(monkeypatch)
    _change_pitcher(client)
    assert _filled(_prep(client)['confirmed']['alignment']) == EXPECTED

    response = client.post('/api/live-game/70/undo', json={'base_sequence': _sequence(client)})
    assert response.status_code == 200, response.get_data(as_text=True)
    prep = _prep(client)
    assert _filled(prep['confirmed']['alignment']) == EDIT            # Aiden pitching again, as saved
    assert prep['pitcher_carry'] is None


def test_undoing_the_next_inning_edit_after_the_live_change(monkeypatch):
    app, client, saved = _saved_edit(monkeypatch)
    _change_pitcher(client)
    confirmed = _prep(client)['confirmed']
    response = client.post(PREP, json={'mode': 'undo', 'base_revision': confirmed['revision'],
                                       'base_alignment': confirmed['alignment'], 'inning': '4'})
    assert response.status_code == 200, response.get_data(as_text=True)
    back = response.get_json()['confirmed']
    # The automatic 4th again: its plan, with Jack carried on.
    assert back['updated_by'] == 'Auto'
    assert _filled(back['alignment']) == dict(B, P='Jack', **{'1B': 'Aiden'})


def test_a_screen_that_missed_the_change_cannot_save_over_it(monkeypatch):
    app, client, saved = _saved_edit(monkeypatch)
    _change_pitcher(client)
    stale = _save(client, dict(EDIT, CF='Isaac'), base=saved['alignment'])  # still showing Aiden at P
    assert stale.status_code == 409
    assert stale.get_json()['code'] == 'next_prep_conflict'
    assert _filled(_prep(client)['confirmed']['alignment']) == EXPECTED

    # Seen the adjusted defense, a fielding edit saves -- still not a pitcher choice.
    response = _save(client, dict(EXPECTED, CF='Isaac'))
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()['confirmed']['pitcher_chosen'] is False


def test_the_bench_report_projection_starts_from_the_adjusted_4th(monkeypatch):
    app, client, saved = _saved_edit(monkeypatch)
    _change_pitcher(client)
    projected = _prep(client)['projected_innings']
    # The 5th follows plan A with Jack carried on; Aiden takes Jack's sit.
    assert _filled(projected['5']) == dict(A, P='Jack')
    assert 'Aiden' not in projected['5'].values()
