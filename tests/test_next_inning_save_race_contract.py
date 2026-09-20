from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "static/js/live_game_board_prep_v2.js"
CONTRACT = ROOT / "static/js/live_game_contract.js"
BULK = ROOT / "blueprints/live_game_bulk_api.py"


def test_next_board_exposes_real_save_flush():
    source = BOARD.read_text()

    assert "let activeSavePromise = null;" in source
    assert "async function flushPendingSave()" in source
    assert "flush: flushPendingSave" in source
    assert "isSaveInFlightOrQueued" in source

    # Regression for game 78: End Inning must be able to await the actual
    # /next-inning-prep POST, not infer NEXT persistence from rotation events.
    save_index = source.index("activeSavePromise = request;")
    flush_index = source.index("async function flushPendingSave()")
    assert save_index < flush_index


def test_end_inning_flushes_next_before_reading_confirmed_prep():
    source = CONTRACT.read_text()

    flush_index = source.index("?.flush?.();")
    prep_get_index = source.index(
        "`/api/live-game/${gameId}/next-inning-prep`",
        flush_index,
    )

    assert flush_index < prep_get_index
    assert "next_prep_id:" in source


def test_advance_inning_rejects_stale_next_prep_version():
    source = BULK.read_text()

    assert "expected_prep_id = data.get('next_prep_id')" in source
    assert "'code': 'stale_next_inning_prep'" in source
    assert "def canonical_alignment(alignment):" in source
    assert "canonical_alignment(" in source
