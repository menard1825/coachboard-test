"""On the Field: moving a player onto an occupied position asks the coach.

"Sam is moving to SS" says nothing about Shawn, who is at SS. CoachBoard
asks where Shawn goes -- never swapping, benching or moving him on its own
-- and follows the chain until every displaced player has a place the coach
chose. The whole chain is saved as one defensive change (one Undo): a
change involving two players as soon as the coach makes the second choice,
three or more after one final review. Tap and drag ask the same question.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect

from test_live_change_pitcher_decision import (  # noqa: F401 (fixture)
    BASE,
    RELIEVER,
    edit_field,
    filled,
    live_field,
    live_state,
    wait_for_field,
)


SHEET = '#cbQuickMoveModal'
STALE = 'Defense changed on another device. Check the field and try the move again.'


def defense_writes(page: Page):
    posts = []
    page.on(
        'request',
        lambda request: posts.append(request.post_data_json)
        if request.method == 'POST' and 'defense-edit' in request.url
        else None,
    )
    return posts


def events(state):
    return [e for e in state.get('rotation_events', []) if not e.get('reverted')]


def tap_move(page: Page, player_selector: str, destination: str):
    page.locator(f'#cbQuickDefense {player_selector}').click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=10_000)
    sheet.locator(f'[data-cb-destination="{destination}"]').click()
    return sheet


def field_player(position):
    return f'[data-cb-position="{position}"]'


def bench_player(name):
    return f'.cb-qd-bench-player[data-cb-move-player="{name}"]'


def choices(sheet):
    return [t.strip() for t in sheet.locator('[data-cb-chain-choices] button').all_inner_texts()]


def pick(sheet, label):
    sheet.get_by_role('button', name=label, exact=True).click()


def expect_question(sheet, title, question):
    expect(sheet.locator('.modal-title')).to_have_text(title)
    expect(sheet.locator('[data-cb-chain-question]')).to_have_text(question)


def expect_review(sheet, lines):
    expect(sheet.locator('.modal-title')).to_have_text('Check the defensive change')
    expect(sheet.locator('[data-cb-chain-summary] li')).to_have_text(lines)


def drag(page: Page, source, target):
    s, t = source.bounding_box(), target.bounding_box()
    page.mouse.move(s['x'] + s['width'] / 2, s['y'] + s['height'] / 2)
    page.mouse.down()
    page.mouse.move(t['x'] + t['width'] / 2, t['y'] + t['height'] / 2, steps=12)
    page.mouse.up()


SWAPPED = dict(BASE, SS='Second Sam', **{'2B': 'Shortstop Shawn'})


# ------------------------------------------------------- field → occupied


def test_explicit_swap_is_one_change_and_one_undo(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = defense_writes(page)
    before_events = len(events(live_state(page, coachboard_url, game_id)))

    sheet = tap_move(page, field_player('2B'), 'SS')
    expect_question(sheet, 'Second Sam is moving to SS', 'Where should Shortstop Shawn go?')
    # Offered, never chosen: Sam's vacated 2B, another position, the bench.
    assert choices(sheet) == [
        'Put Shortstop Shawn at 2B', 'Move Shortstop Shawn to another position…',
        'Bench Shortstop Shawn', 'Cancel',
    ]
    page.wait_for_timeout(400)
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE

    # The coach's second choice completes the swap: saved, no second confirmation.
    pick(sheet, 'Put Shortstop Shawn at 2B')
    wait_for_field(page, coachboard_url, game_id, SWAPPED)
    expect(sheet).not_to_be_visible(timeout=10_000)
    assert len(writes) == 1
    state = live_state(page, coachboard_url, game_id)
    assert len(events(state)) == before_events + 1

    page.locator('#liveUndoBtn').click()
    wait_for_field(page, coachboard_url, game_id, BASE)


def test_displaced_player_to_bench(page: Page, coachboard_url, live_field):
    game_id = live_field()
    sheet = tap_move(page, field_player('2B'), 'SS')
    pick(sheet, 'Bench Shortstop Shawn')
    expected = {pos: n for pos, n in BASE.items() if pos != '2B'}
    expected['SS'] = 'Second Sam'
    wait_for_field(page, coachboard_url, game_id, expected)


def test_three_player_rotation(page: Page, coachboard_url, live_field):
    """Sam 2B → SS; Shawn SS → 1B; Frank 1B → 2B."""
    game_id = live_field()
    writes = defense_writes(page)
    sheet = tap_move(page, field_player('2B'), 'SS')
    pick(sheet, 'Move Shortstop Shawn to another position…')
    offered = choices(sheet)
    # Sam, already placed at SS, is never offered; P is never an ordinary spot.
    assert 'SS · Second Sam' not in offered
    assert not any(label.startswith('P ·') for label in offered)
    pick(sheet, '1B · First Frank')
    expect_question(sheet, 'Shortstop Shawn is moving to 1B', 'Where should First Frank go?')
    pick(sheet, 'Put First Frank at 2B')
    expect_review(sheet, [
        'Second Sam: 2B → SS', 'Shortstop Shawn: SS → 1B', 'First Frank: 1B → 2B',
    ])
    assert writes == []
    pick(sheet, 'Make this change')
    expected = dict(BASE, SS='Second Sam', **{'1B': 'Shortstop Shawn', '2B': 'First Frank'})
    wait_for_field(page, coachboard_url, game_id, expected)
    after = filled(live_state(page, coachboard_url, game_id)['current_alignment'])
    assert len(set(after.values())) == len(after)
    assert len(writes) == 1


# ------------------------------------------------------- bench → occupied


def test_bench_player_in_occupant_to_bench(page: Page, coachboard_url, live_field):
    game_id = live_field()
    sheet = tap_move(page, bench_player(RELIEVER), 'SS')
    expect_question(sheet, f'{RELIEVER} is moving to SS', 'Where should Shortstop Shawn go?')
    # The field is full: no open spot is invented.
    assert choices(sheet) == [
        'Move Shortstop Shawn to another position…', 'Bench Shortstop Shawn', 'Cancel',
    ]
    pick(sheet, 'Bench Shortstop Shawn')
    wait_for_field(page, coachboard_url, game_id, dict(BASE, SS=RELIEVER))
    expect(sheet).not_to_be_visible(timeout=10_000)


def test_bench_player_in_occupant_to_another_position(page: Page, coachboard_url, live_field):
    game_id = live_field()
    sheet = tap_move(page, bench_player(RELIEVER), 'SS')
    pick(sheet, 'Move Shortstop Shawn to another position…')
    pick(sheet, 'LF · Left Lee')
    expect_question(sheet, 'Shortstop Shawn is moving to LF', 'Where should Left Lee go?')
    pick(sheet, 'Bench Left Lee')
    expect_review(sheet, [
        f'{RELIEVER}: Bench → SS', 'Shortstop Shawn: SS → LF', 'Left Lee: LF → Bench',
    ])
    pick(sheet, 'Make this change')
    wait_for_field(page, coachboard_url, game_id, dict(BASE, SS=RELIEVER, LF='Shortstop Shawn'))


# ------------------------------------------------------------------ cancel


def test_cancel_at_first_step_and_midway_changes_nothing(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = defense_writes(page)

    sheet = tap_move(page, field_player('2B'), 'SS')
    pick(sheet, 'Cancel')
    expect(sheet).not_to_be_visible(timeout=10_000)

    sheet = tap_move(page, field_player('2B'), 'SS')
    pick(sheet, 'Move Shortstop Shawn to another position…')
    pick(sheet, '1B · First Frank')
    pick(sheet, 'Cancel')
    expect(sheet).not_to_be_visible(timeout=10_000)

    sheet = tap_move(page, field_player('2B'), 'SS')
    pick(sheet, 'Move Shortstop Shawn to another position…')
    pick(sheet, '1B · First Frank')
    pick(sheet, 'Put First Frank at 2B')
    pick(sheet, 'Cancel')                      # at the three-player review
    expect(sheet).not_to_be_visible(timeout=10_000)

    page.wait_for_timeout(500)
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE


# ------------------------------------------------------------- two coaches


def test_another_coach_changing_the_field_discards_the_chain(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = defense_writes(page)
    sheet = tap_move(page, field_player('2B'), 'SS')
    pick(sheet, 'Move Shortstop Shawn to another position…')
    pick(sheet, '1B · First Frank')

    other = dict(BASE, LF='Right Riley', RF='Left Lee')
    edit_field(page, coachboard_url, game_id, other)

    expect(sheet.locator('[data-cb-chain-stale]')).to_have_text(STALE, timeout=10_000)
    expect(sheet.locator('[data-cb-chain-choices]')).to_have_count(0)
    page.wait_for_timeout(500)
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == other
    expect(page.locator('#cbQuickDefense [data-cb-position="LF"]')).to_contain_text(
        'Right Riley', timeout=10_000
    )


# ------------------------------------------------------------ drag / pitcher


def test_drag_asks_the_same_question_and_makes_the_same_change(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    writes = defense_writes(page)
    quick = page.locator('#cbQuickDefense')
    drag(page, quick.locator(field_player('2B')), quick.locator(field_player('SS')))

    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=10_000)
    expect_question(sheet, 'Second Sam is moving to SS', 'Where should Shortstop Shawn go?')
    assert choices(sheet) == [
        'Put Shortstop Shawn at 2B', 'Move Shortstop Shawn to another position…',
        'Bench Shortstop Shawn', 'Cancel',
    ]
    page.wait_for_timeout(400)
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE

    pick(sheet, 'Put Shortstop Shawn at 2B')
    wait_for_field(page, coachboard_url, game_id, SWAPPED)
    assert len(writes) == 1


def test_moving_onto_p_goes_to_change_pitcher(page: Page, coachboard_url, live_field):
    game_id = live_field()
    writes = defense_writes(page)
    quick = page.locator('#cbQuickDefense')

    # P is not an ordinary destination on the Move sheet...
    quick.locator(field_player('2B')).click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=10_000)
    expect(sheet.locator('[data-cb-destination="P"]')).to_have_count(0)
    sheet.locator('.btn-close').click()
    expect(sheet).not_to_be_visible(timeout=10_000)

    # ...and dropping a fielder on P opens Change Pitcher, changing nothing.
    page.wait_for_timeout(750)
    drag(page, quick.locator(field_player('2B')), quick.locator(field_player('P')))
    expect(page.locator('#live-pitcher-picker-v2')).to_be_visible(timeout=10_000)
    page.wait_for_timeout(400)
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE
