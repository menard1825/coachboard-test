"""On the Field has one writer for a normal live defensive move.

live_game_dugout_mode.js owns it (commitMove, exported as
CBQuickFieldMoves.commit). The drag surface in
live_game_unified_field_entry.js only works out the gesture -- who was
picked up, with the field they were picked up from, and where they were
dropped -- and hands that to the writer. It must not grow its own save,
alignment rules or blocking alert again. The browser behaviour is in
tests/e2e/test_live_move_single_writer.py.
"""

import re
from pathlib import Path


JS = Path(__file__).resolve().parent.parent / 'static' / 'js'
DRAG = (JS / 'live_game_unified_field_entry.js').read_text()
WRITER = (JS / 'live_game_dugout_mode.js').read_text()


def test_the_drag_surface_does_not_save_or_alert():
    assert 'fetch(' not in DRAG
    assert 'defense-edit' not in DRAG
    assert 'alert(' not in DRAG
    assert 'current_alignment' not in DRAG      # no second copy of the move rules


def test_a_drop_commits_through_the_one_writer_with_the_start_context():
    assert re.search(r'context:\s*moves\(\)\.context\(\)', DRAG)          # captured on pick-up
    assert re.search(r'onDrop:.*moves\(\)\?\.commit\(source\.name, target\.position, source\.context\)', DRAG)
    assert re.search(r'canStart:.*!moves\(\)\.busy\(\)', DRAG)          # one move at a time


def test_the_writer_is_exported_once_and_saves_in_one_place():
    assert WRITER.count('window.CBQuickFieldMoves = Object.freeze(') == 1
    assert 'commit: commitMove' in WRITER
    assert WRITER.count('/defense-edit`') == 1                          # saveMove's POST only
    for gone in ('askOccupiedMove', 'saveDefenseDraft', 'lastFailedDraft', 'moveOrAsk'):
        assert gone not in WRITER
