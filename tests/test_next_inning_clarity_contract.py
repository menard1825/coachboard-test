from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "static/js/live_game_board_prep_v2.js"


def test_next_inning_ux_uses_authoritative_next_inning():
    source = BOARD.read_text()

    assert "latest?.next_inning" in source
    assert "function inningOrdinal(value)" in source
    assert "`${inningLabel} Inning`" in source
    assert "${esc(inningLabel)} Inning Defense" in source
    assert "`End ${currentLabel} → Start ${inningLabel}`" in source
    assert "`Use ${esc(currentLabel)} Inning Defense`" in source


def test_next_inning_ux_avoids_redundant_status_chrome():
    source = BOARD.read_text()

    assert 'class="cb-next-up-pill"' not in source
    assert ".cb-next-up-pill{" not in source
    assert "cb-next-ready" not in source
    assert "inning defense ready" not in source

def test_idle_next_board_does_not_show_step_one_instructions():
    source = BOARD.read_text()

    assert "STEP 1" not in source
    assert (
        "Tap a player to move them. Mouse or trackpad users can also drag."
        not in source
    )

    # Contextual guidance remains available once a coach begins a move.
    assert "STEP 2 · CHOOSE DESTINATION" in source
    assert "STEP 2 · CHOOSE PLAYER" in source

def test_next_inning_ux_uses_baseball_language_not_next_state_language():
    source = BOARD.read_text()

    assert "Same defense as the ${currentLabel}" in source
    assert "Changes saved for the ${nextLabel}" in source
    assert "Pregame plan for the ${nextLabel}" in source

    assert "NEXT is ready" not in source
    assert "NEXT edited" not in source
    assert "Current defense copied to NEXT" not in source
    assert "NEXT restored" not in source

def test_phone_live_actions_have_an_explicit_end_inning_owner():
    source = BOARD.read_text()

    assert "#coach-action-slot{" in source
    assert "position:fixed!important;" in source
    assert "#coach-action-slot.cb-single-live-action{" in source
    assert "#coach-action-slot #liveEndInningBtn{" in source
    assert "endInning.removeAttribute('hidden')" in source
    assert "endInning.classList.remove('d-none')" in source
