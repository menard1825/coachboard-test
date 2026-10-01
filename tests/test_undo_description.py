"""What the live Undo says it took back (live_game_api._describe_undo)."""

from types import SimpleNamespace

from blueprints.live_game_api import _describe_undo


FIELD = {'P': 'Pat', 'C': 'Cole', 'SS': 'Shawn', 'LF': 'Lee'}


def _event(event_type, before, after, inning='1'):
    return SimpleNamespace(event_type=event_type, inning=inning, before_alignment=before, after_alignment=after)


def test_an_inning_change():
    assert _describe_undo(_event('End Inning', FIELD, FIELD, inning='2'), '1') == \
        'Undid starting the 2nd. Back in the 1st.'


def test_a_pitching_change():
    after = dict(FIELD, P='Shawn', SS='Pat')
    assert _describe_undo(_event('Pitcher Change', FIELD, after), '1') == \
        'Undid the pitching change: Pat is back on the mound.'


def test_a_field_change_names_who_came_back():
    after = {k: v for k, v in FIELD.items() if k != 'SS'}
    assert _describe_undo(_event('Bulk Defensive Change', FIELD, after), '1') == \
        'Undid the last change: Shawn back at SS.'
    swapped = dict(FIELD, SS='Lee', LF='Shawn')
    assert _describe_undo(_event('Bulk Defensive Change', FIELD, swapped), '1') == \
        'Undid the last change: Lee back at LF; Shawn back at SS.'


def test_a_filled_spot_opens_again():
    before = {k: v for k, v in FIELD.items() if k != 'SS'}
    assert _describe_undo(_event('Bulk Defensive Change', before, FIELD), '1') == \
        'Undid the last change: SS open again.'


def test_availability():
    assert _describe_undo(_event('Player Left', FIELD, FIELD), '1') == 'Undid marking a player as gone.'
