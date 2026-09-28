"""Pregame moves involving P are the coach's decision.

In the starting-defense editor a non-P swap stays one tap, but a move that
changes who pitches -- or where the pitcher goes -- asks. CoachBoard never
sends the old pitcher to a vacated spot, never makes a fielder the pitcher,
and never saves a half-resolved move: the resolved inning is saved once, and
Cancel (or closing the sheet) at any question changes nothing.
"""

import re

import pytest

from test_set_defense_simplified import (  # noqa: F401 (make_page is a fixture)
    DESKTOP,
    DEVICES,
    PANEL,
    _choose_inning,
    _filled,
    _innings,
    _open_game,
    _saved,
    make_page,
)
from test_saved_defense_pitcher import setup  # noqa: F401 (fixture)

from playwright.sync_api import expect  # noqa: E402


pytestmark = pytest.mark.e2e

BASE = {'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam',
        '3B': 'Third Theo', 'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey',
        'RF': 'Right Riley'}
TITLE = '#pde-player-modal .modal-title'
HELP = '#pde-help'
FOUR_WORDS = re.compile(r"Ready|Advisory|Rule conflict|Can't confirm")


def _record_saves(page):
    saves = []
    page.on('request', lambda r: saves.append(r) if r.method == 'POST' and r.url.endswith('/save_rotation') else None)
    return saves


def _pick(page, pos, name=None, clear=False):
    page.locator(f'{PANEL} [data-pde-pos="{pos}"]').click()
    expect(page.locator('#pde-player-modal')).to_be_visible(timeout=10_000)
    if clear:
        page.locator('#pde-list .pde-choice[data-clear]').click()
    else:
        page.locator(f'#pde-list .pde-choice[data-player="{name}"]').click()


def _answer(page, label):
    page.locator('#pde-list .pde-question-choice').filter(
        has=page.locator('strong', has_text=re.compile(rf'^{re.escape(label)}$'))
    ).click()


def _expect_question(page, title, help_text=None):
    expect(page.locator(TITLE)).to_have_text(title, timeout=10_000)
    if help_text:
        expect(page.locator(HELP)).to_have_text(help_text)


def _canonical(page, inning='1'):
    return _filled(page.evaluate(f"() => window.CBPregameRotation.getRotation().innings['{inning}']"))


def _assert_one_pitcher_no_duplicates(defense):
    names = list(_filled(defense).values())
    assert len(names) == len(set(names)), defense
    assert list(_filled(defense)).count('P') <= 1


def _done(page, coachboard_url, game_id, saves, expected, inning='1'):
    expect(page.locator('#pde-player-modal')).to_be_hidden(timeout=10_000)
    _saved(page)
    assert saves, 'the resolved move is saved'
    defense = _filled(_innings(page, coachboard_url, game_id)[inning])
    assert defense == expected, defense
    _assert_one_pitcher_no_duplicates(defense)


def _open(setup, coachboard_url, innings, page=None):
    setup_page, plan_game, _, _ = setup
    game_id = plan_game(innings)
    page = page or setup_page
    _open_game(page, coachboard_url, game_id)
    return page, game_id


# --- A new pitcher: where does the old one go? ------------------------------------------

def test_bench_player_to_p_old_pitcher_to_bench(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, {'1': BASE})
    saves = _record_saves(page)
    _pick(page, 'P', 'Relief Rex')
    _expect_question(page, 'Relief Rex is your starting pitcher', 'Where should Pitcher Pat go?')
    # No vacated spot and no open position: no "Put ... at" guesses.
    expect(page.locator('#pde-list')).not_to_contain_text('Put Pitcher Pat at')
    assert saves == []
    _answer(page, 'Bench Pitcher Pat')
    _done(page, coachboard_url, game_id, saves, {**BASE, 'P': 'Relief Rex'})


@DEVICES
def test_field_player_to_p_old_pitcher_to_the_vacated_spot(setup, make_page, coachboard_url, device):
    page, game_id = _open(setup, coachboard_url, {'1': BASE}, make_page(device))
    saves = _record_saves(page)
    _pick(page, 'P', 'Shortstop Shawn')
    _expect_question(page, 'Shortstop Shawn is your starting pitcher', 'Where should Pitcher Pat go?')
    assert saves == [] and _canonical(page) == BASE
    _answer(page, 'Put Pitcher Pat at SS')
    _done(page, coachboard_url, game_id, saves, {**BASE, 'P': 'Shortstop Shawn', 'SS': 'Pitcher Pat'})


def test_field_player_to_p_old_pitcher_to_another_position(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, {'1': BASE})
    saves = _record_saves(page)
    _pick(page, 'P', 'Shortstop Shawn')
    _answer(page, 'Move Pitcher Pat to another position…')
    _answer(page, '2B — Second Sam')
    _expect_question(page, 'Pitcher Pat plays 2B', 'Where should Second Sam go?')
    _answer(page, 'Put Second Sam at SS')
    # Three players moved: one light review before saving.
    _expect_question(page, 'Review this change',
                     'Shortstop Shawn → P · Pitcher Pat → 2B · Second Sam → SS')
    assert saves == []
    _answer(page, 'Save plan')
    _done(page, coachboard_url, game_id, saves,
          {**BASE, 'P': 'Shortstop Shawn', '2B': 'Pitcher Pat', 'SS': 'Second Sam'})


def test_field_player_to_p_old_pitcher_benched_leaves_the_spot_open(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, {'1': BASE})
    saves = _record_saves(page)
    _pick(page, 'P', 'Shortstop Shawn')
    _answer(page, 'Bench Pitcher Pat · leave SS open')
    expected = {pos: n for pos, n in BASE.items() if pos != 'SS'}
    _done(page, coachboard_url, game_id, saves, {**expected, 'P': 'Shortstop Shawn'})
    expect(page.locator('#pde-toast')).to_contain_text('SS is open.')


# --- The pitcher moves to a fielding position: who pitches? -----------------------------

def test_pitcher_to_occupied_ss_asks_who_pitches_then_places_the_ss(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, {'1': BASE})
    saves = _record_saves(page)
    _pick(page, 'SS', 'Pitcher Pat')
    _expect_question(page, 'Pitcher Pat moves to SS', 'Who pitches instead?')
    # The server's own eligibility classification is shown for candidates.
    rex = page.locator('#pde-list .pde-question-choice').filter(has_text='Relief Rex pitches')
    expect(rex).to_contain_text(FOUR_WORDS)
    # Inning 1 needs a pitcher: no "decide later".
    expect(page.locator('#pde-list')).not_to_contain_text('Pitcher TBD')
    _answer(page, 'Relief Rex pitches')
    _expect_question(page, 'Pitcher Pat plays SS', 'Where should Shortstop Shawn go?')
    assert saves == []
    _answer(page, 'Bench Shortstop Shawn')
    _done(page, coachboard_url, game_id, saves, {**BASE, 'P': 'Relief Rex', 'SS': 'Pitcher Pat'})


def test_pitcher_to_occupied_ss_the_ss_can_be_the_new_pitcher(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, {'1': BASE})
    saves = _record_saves(page)
    _pick(page, 'SS', 'Pitcher Pat')
    _answer(page, 'Shortstop Shawn pitches')
    _done(page, coachboard_url, game_id, saves, {**BASE, 'P': 'Shortstop Shawn', 'SS': 'Pitcher Pat'})


def test_pitcher_to_an_open_position_asks_who_pitches(setup, coachboard_url):
    plan = {pos: n for pos, n in BASE.items() if pos != 'CF'}
    page, game_id = _open(setup, coachboard_url, {'1': plan})
    saves = _record_saves(page)
    _pick(page, 'CF', 'Pitcher Pat')
    _expect_question(page, 'Pitcher Pat moves to CF', 'Who pitches instead?')
    _answer(page, 'Relief Rex pitches')
    _done(page, coachboard_url, game_id, saves, {**plan, 'P': 'Relief Rex', 'CF': 'Pitcher Pat'})


# --- Taking the pitcher off P ------------------------------------------------------------

def test_take_the_pitcher_off_p_requires_a_replacement(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, {'1': BASE})
    saves = _record_saves(page)
    _pick(page, 'P', clear=True)
    _expect_question(page, 'Take Pitcher Pat off P', 'Who pitches instead?')
    assert saves == []
    _answer(page, 'Shortstop Shawn pitches')
    expected = {pos: n for pos, n in BASE.items() if pos != 'SS'}
    _done(page, coachboard_url, game_id, saves, {**expected, 'P': 'Shortstop Shawn'})
    expect(page.locator('#pde-toast')).to_contain_text('Pitcher Pat → Bench · Shortstop Shawn → P. SS is open.')


def test_a_later_inning_may_leave_the_pitcher_to_be_decided(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, {'1': BASE, '2': BASE})
    _choose_inning(page, 2)
    saves = _record_saves(page)
    _pick(page, 'P', clear=True)
    _expect_question(page, 'Take Pitcher Pat off P', 'Who pitches instead?')
    _answer(page, 'Decide later — Pitcher TBD')
    expected = {pos: n for pos, n in BASE.items() if pos != 'P'}
    _done(page, coachboard_url, game_id, saves, expected, inning='2')


# --- Cancel anywhere changes nothing -----------------------------------------------------

CANCEL_POINTS = {
    'where-old-pitcher-goes': (('P', 'Shortstop Shawn', False), []),
    'choose-another-position': (('P', 'Shortstop Shawn', False), ['Move Pitcher Pat to another position…']),
    'displaced-by-the-chain': (('P', 'Shortstop Shawn', False),
                               ['Move Pitcher Pat to another position…', '2B — Second Sam']),
    'review': (('P', 'Shortstop Shawn', False),
               ['Move Pitcher Pat to another position…', '2B — Second Sam', 'Put Second Sam at SS']),
    'who-pitches': (('SS', 'Pitcher Pat', False), []),
    'displaced-ss': (('SS', 'Pitcher Pat', False), ['Relief Rex pitches']),
    'take-off-p': (('P', None, True), []),
}


@pytest.mark.parametrize('how', ['Cancel', 'close'])
@pytest.mark.parametrize('point', list(CANCEL_POINTS))
def test_cancel_at_any_question_changes_nothing(setup, coachboard_url, point, how):
    page, game_id = _open(setup, coachboard_url, {'1': BASE})
    saves = _record_saves(page)
    (pos, name, clear), answers = CANCEL_POINTS[point]
    _pick(page, pos, name, clear=clear)
    for label in answers:
        _answer(page, label)
    expect(page.locator('#pde-list .pde-question-choice').first).to_be_visible(timeout=10_000)
    if how == 'Cancel':
        _answer(page, 'Cancel')
    else:
        page.locator('#pde-player-modal .btn-close').click()
    expect(page.locator('#pde-player-modal')).to_be_hidden(timeout=10_000)
    page.wait_for_timeout(600)
    assert saves == []
    assert _canonical(page) == BASE
    assert _filled(_innings(page, coachboard_url, game_id)['1']) == BASE
    expect(page.locator(f'{PANEL} [data-pde-pos="P"] .pde-name')).to_have_text('Pitcher Pat')


# --- Non-P swaps are unchanged -----------------------------------------------------------

def test_non_p_swap_is_still_one_tap(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, {'1': BASE})
    saves = _record_saves(page)
    page.locator(f'{PANEL} [data-pde-pos="SS"]').click()
    sam = page.locator('#pde-list .pde-choice[data-player="Second Sam"]')
    expect(sam).to_contain_text('swaps with Shortstop Shawn')
    # The pitcher is offered, but as a decision, not a swap.
    expect(page.locator('#pde-list .pde-choice[data-player="Pitcher Pat"]')).to_contain_text(
        "Currently at P — you'll choose who pitches"
    )
    sam.click()
    _done(page, coachboard_url, game_id, saves, {**BASE, 'SS': 'Second Sam', '2B': 'Shortstop Shawn'})
    expect(page.locator('#pde-toast')).to_contain_text('swapped')


def test_a_plan_changed_while_deciding_is_not_overwritten(setup, coachboard_url):
    page, game_id = _open(setup, coachboard_url, {'1': BASE})
    saves = _record_saves(page)
    _pick(page, 'P', 'Shortstop Shawn')
    _expect_question(page, 'Shortstop Shawn is your starting pitcher')
    # Another coach's change arrives while the question is open.
    page.evaluate("() => { window.CBPregameRotation.getRotation().innings['1'].C = 'Relief Rae'; }")
    _answer(page, 'Put Pitcher Pat at SS')
    expect(page.locator('#pde-toast')).to_contain_text('The plan changed while you were deciding')
    page.wait_for_timeout(600)
    assert saves == []
    assert _canonical(page) == {**BASE, 'C': 'Relief Rae'}
