"""Change Pitcher records the one decision the coach made.

Choosing the incoming pitcher says who is going in to pitch. Where the
pitcher coming out goes is a separate baseball decision, so CoachBoard asks
it once -- every choice naming the complete result -- and changes nothing on
the official field until it is answered. The answer is saved as one pitching
change: one event, one Undo.

* Incoming from the bench: the outgoing pitcher sits, takes an open spot, or
  takes an occupied spot whose fielder goes to the bench.
* Incoming from the field: the spot they left is open unless the coach fills
  it -- with the outgoing pitcher, or with the fielder the outgoing pitcher
  displaces ("Pat → 1B · Frank → SS").
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

from change_pitcher_flow import (
    DESTINATION_QUESTION,
    PICKER,
    STALE,
    TOAST,
    choose_incoming_pitcher,
    choose_outgoing_destination,
    expect_destination_question,
    incoming_pitcher_row,
    outcome_of,
    pitcher_outcome_choices,
    record_pitching_changes,
    wait_for_pitcher_change,
)
from live_fixtures import (  # noqa: F401 (live_field is a fixture)
    BASE,
    RELIEVER,
    filled,
    live_field,
    live_state,
    pitcher_changes,
    set_live_defense as edit_field,
    wait_for_field,
)


OUTGOING = 'Pitcher Pat'
FIELDERS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']


def occupied_choices(field, to):
    """The occupied-spot choices, in field order: Pat there, its fielder `to`."""
    return [f'{OUTGOING} → {pos} · {field[pos]} → {to}' for pos in FIELDERS if field.get(pos)]


def player_id(state, name):
    return next(int(p['id']) for p in state['roster'] if p['name'] == name)


def expect_pitcher(page: Page, name: str):
    expect(page.locator('#cbDugoutHeader [data-cb-pitcher]')).to_contain_text(name, timeout=10_000)


def undo_restores(page: Page, url: str, game_id: int, field):
    page.locator('#liveUndoBtn').click()
    wait_for_field(page, url, game_id, field)
    assert pitcher_changes(live_state(page, url, game_id)) == []


# ------------------------------------------------------ fielder → pitcher


def test_shortstop_pitches_and_coach_sends_pitcher_to_short(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    posts = record_pitching_changes(page)
    before = live_state(page, coachboard_url, game_id)

    question = choose_incoming_pitcher(page, 'Shortstop Shawn')
    expect_destination_question(question, 'Shortstop Shawn', OUTGOING)
    # One decision. Every choice names the whole result: the open SS, or an
    # occupied spot whose fielder takes the SS Shawn left.
    vacated = {pos: name for pos, name in BASE.items() if pos != 'SS'}
    assert pitcher_outcome_choices(question) == [
        f'Bench {OUTGOING} · SS open',
        f'{OUTGOING} → SS',
        *occupied_choices(vacated, 'SS'),
        'Cancel',
    ]

    # Nothing official happens while the coach decides.
    page.wait_for_timeout(600)
    assert posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE

    label = f'{OUTGOING} → SS'
    swapped = dict(BASE, P='Shortstop Shawn', SS=OUTGOING)
    assert outcome_of(label, BASE, 'Shortstop Shawn', OUTGOING) == swapped
    choose_outgoing_destination(question, label)

    # One pitching-change event, recording exactly the coach's choice.
    event = wait_for_pitcher_change(page, coachboard_url, game_id, swapped)
    assert len(posts) == 1
    assert filled(posts[0]['alignment']) == swapped
    assert filled(event['before_alignment']) == BASE
    assert event['old_pitcher_id'] == player_id(before, OUTGOING)
    assert event['new_pitcher_id'] == player_id(before, 'Shortstop Shawn')
    expect_pitcher(page, 'Shortstop Shawn')
    expect(page.locator(TOAST)).to_contain_text(f'Shortstop Shawn is pitching · {OUTGOING} to SS')

    # One Undo restores the whole change: pitcher and field together.
    undo_restores(page, coachboard_url, game_id, BASE)


def test_shortstop_pitches_and_coach_benches_the_pitcher(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()

    question = choose_incoming_pitcher(page, 'Shortstop Shawn')
    label = f'Bench {OUTGOING} · SS open'
    expected = {pos: name for pos, name in BASE.items() if pos != 'SS'}
    expected['P'] = 'Shortstop Shawn'
    assert outcome_of(label, BASE, 'Shortstop Shawn', OUTGOING) == expected
    choose_outgoing_destination(question, label)

    wait_for_pitcher_change(page, coachboard_url, game_id, expected)
    quick = page.locator('#cbQuickDefense')
    expect(quick.locator('[data-cb-position="SS"]')).to_contain_text('Open', timeout=10_000)
    expect(quick.locator('.cb-qd-bench')).to_contain_text(OUTGOING)
    expect(page.locator(TOAST)).to_contain_text(
        f'Shortstop Shawn is pitching · {OUTGOING} to Bench · SS open'
    )


def test_fielder_pitches_and_displaced_player_takes_the_vacated_spot(
    page: Page, coachboard_url, live_field
):
    """Shawn (SS) pitches; Pat to 1B; Frank, who was at 1B, to short -- one
    choice, three players, one change."""
    game_id = live_field()
    posts = record_pitching_changes(page)

    question = choose_incoming_pitcher(page, 'Shortstop Shawn')
    label = f'{OUTGOING} → 1B · First Frank → SS'
    expected = dict(BASE, P='Shortstop Shawn', **{'1B': OUTGOING, 'SS': 'First Frank'})
    assert outcome_of(label, BASE, 'Shortstop Shawn', OUTGOING) == expected
    choose_outgoing_destination(question, label)

    event = wait_for_pitcher_change(page, coachboard_url, game_id, expected)
    assert filled(event['before_alignment']) == BASE
    assert len(posts) == 1
    after = filled(live_state(page, coachboard_url, game_id)['current_alignment'])
    # Nine positions, nine different players: nobody twice, nobody lost.
    assert len(after) == 9 and len(set(after.values())) == 9
    quick = page.locator('#cbQuickDefense')
    expect(quick.locator('[data-cb-position="1B"]')).to_contain_text(OUTGOING, timeout=10_000)
    expect(quick.locator('[data-cb-position="SS"]')).to_contain_text('First Frank')
    expect(page.locator(TOAST)).to_contain_text(
        f'Shortstop Shawn is pitching · {OUTGOING} to 1B · First Frank to SS'
    )

    undo_restores(page, coachboard_url, game_id, BASE)


def test_fielder_pitches_and_the_pitcher_takes_another_open_spot(
    page: Page, coachboard_url, live_field
):
    """LF is open. Shawn (SS) pitches and Pat goes to LF: the SS Shawn left
    stays open -- nobody is moved there for the coach."""
    open_lf = {pos: name for pos, name in BASE.items() if pos != 'LF'}
    game_id = live_field(lambda gid: edit_field(page, coachboard_url, gid, open_lf))

    question = choose_incoming_pitcher(page, 'Shortstop Shawn')
    vacated = {pos: name for pos, name in open_lf.items() if pos != 'SS'}
    assert pitcher_outcome_choices(question) == [
        f'Bench {OUTGOING} · SS open',
        f'{OUTGOING} → SS',
        f'{OUTGOING} → LF',
        *occupied_choices(vacated, 'SS'),
        'Cancel',
    ]

    label = f'{OUTGOING} → LF'
    expected = dict(vacated, P='Shortstop Shawn', LF=OUTGOING)
    assert outcome_of(label, open_lf, 'Shortstop Shawn', OUTGOING) == expected
    choose_outgoing_destination(question, label)

    wait_for_pitcher_change(page, coachboard_url, game_id, expected)
    expect(page.locator('#cbQuickDefense [data-cb-position="SS"]')).to_contain_text('Open', timeout=10_000)
    expect(page.locator(TOAST)).to_contain_text(f'Shortstop Shawn is pitching · {OUTGOING} to LF')


# -------------------------------------------------------- bench → pitcher


def test_bench_player_pitches_and_coach_places_the_pitcher(
    page: Page, coachboard_url, live_field
):
    # Left field is open when the change is made.
    open_lf = {pos: name for pos, name in BASE.items() if pos != 'LF'}
    game_id = live_field(lambda gid: edit_field(page, coachboard_url, gid, open_lf))

    question = choose_incoming_pitcher(page, RELIEVER)
    expect_destination_question(question, RELIEVER, OUTGOING)
    # The open spot is one tap; an occupied spot says its fielder sits.
    assert pitcher_outcome_choices(question) == [
        f'Bench {OUTGOING}',
        f'{OUTGOING} → LF',
        *occupied_choices(open_lf, 'Bench'),
        'Cancel',
    ]

    label = f'{OUTGOING} → LF'
    expected = dict(open_lf, P=RELIEVER, LF=OUTGOING)
    assert outcome_of(label, open_lf, RELIEVER, OUTGOING) == expected
    choose_outgoing_destination(question, label)
    wait_for_pitcher_change(page, coachboard_url, game_id, expected)
    expect(page.locator(TOAST)).to_contain_text(f'{RELIEVER} is pitching · {OUTGOING} to LF')


def test_bench_pitcher_in_old_pitcher_to_occupied_first_displaced_to_bench(
    page: Page, coachboard_url, live_field
):
    """Blake from the bench pitches; Pat to 1B; Frank, who was at 1B, sits.
    Every position is occupied."""
    game_id = live_field()
    posts = record_pitching_changes(page)

    question = choose_incoming_pitcher(page, RELIEVER)
    expect_destination_question(question, RELIEVER, OUTGOING)
    # Nothing is open: Pat sits, or takes a spot whose fielder sits.
    assert pitcher_outcome_choices(question) == [
        f'Bench {OUTGOING}',
        *occupied_choices(BASE, 'Bench'),
        'Cancel',
    ]
    page.wait_for_timeout(500)
    assert posts == []

    label = f'{OUTGOING} → 1B · First Frank → Bench'
    expected = dict(BASE, P=RELIEVER, **{'1B': OUTGOING})
    assert outcome_of(label, BASE, RELIEVER, OUTGOING) == expected
    choose_outgoing_destination(question, label)

    event = wait_for_pitcher_change(page, coachboard_url, game_id, expected)
    assert len(posts) == 1
    assert filled(event['before_alignment']) == BASE
    assert 'First Frank' not in live_state(page, coachboard_url, game_id)['current_alignment'].values()
    expect(page.locator('#cbQuickDefense .cb-qd-bench')).to_contain_text('First Frank', timeout=10_000)
    expect(page.locator(TOAST)).to_contain_text(
        f'{RELIEVER} is pitching · {OUTGOING} to 1B · First Frank to Bench'
    )

    undo_restores(page, coachboard_url, game_id, BASE)


def test_bench_player_pitches_and_the_old_pitcher_sits(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    question = choose_incoming_pitcher(page, RELIEVER)
    label = f'Bench {OUTGOING}'
    expected = dict(BASE, P=RELIEVER)
    assert outcome_of(label, BASE, RELIEVER, OUTGOING) == expected
    choose_outgoing_destination(question, label)

    wait_for_pitcher_change(page, coachboard_url, game_id, expected)
    expect(page.locator('#cbQuickDefense .cb-qd-bench')).to_contain_text(OUTGOING, timeout=10_000)
    expect(page.locator(TOAST)).to_contain_text(f'{RELIEVER} is pitching · {OUTGOING} to Bench')


def test_every_choice_names_a_complete_field(page: Page, coachboard_url, live_field):
    """Read as a coach reads them, the choices are each a whole defense: the
    new pitcher on the mound, nobody twice, and only the spot a choice says
    is open left open. Every position is offered once."""
    game_id = live_field()
    for incoming in ('Shortstop Shawn', RELIEVER):
        question = choose_incoming_pitcher(page, incoming)
        labels = pitcher_outcome_choices(question)
        assert labels[-1] == 'Cancel'
        destinations = []
        for label in labels[:-1]:
            after = outcome_of(label, BASE, incoming, OUTGOING)
            assert after['P'] == incoming, label
            assert len(set(after.values())) == len(after), (label, after)
            assert len(after) == (8 if label.endswith(' open') else 9), (label, after)
            destinations.append(label.split(' · ')[0])
        # Bench first, then every fielding position once (open spots first).
        assert destinations[0] == f'Bench {OUTGOING}'
        assert sorted(destinations[1:]) == sorted(f'{OUTGOING} → {pos}' for pos in FIELDERS)
        choose_outgoing_destination(question, 'Cancel')
    page.wait_for_timeout(500)
    assert pitcher_changes(live_state(page, coachboard_url, game_id)) == []


# -------------------------------------------------------- pitcher → field


def test_tapping_the_pitcher_asks_who_pitches_first(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    posts = record_pitching_changes(page)

    # "Pat is moving" starts with who is pitching; the SS is not assumed.
    page.locator('#cbQuickDefense [data-cb-position="P"]').click()
    picker = page.locator(PICKER)
    expect(picker).to_be_visible(timeout=10_000)
    expect(picker).to_contain_text('Current:')
    page.wait_for_timeout(400)
    assert posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE

    incoming_pitcher_row(picker, 'Shortstop Shawn').click()
    question = page.locator(DESTINATION_QUESTION)
    expect(question).to_be_visible(timeout=10_000)
    expect_destination_question(question, 'Shortstop Shawn', OUTGOING)
    choose_outgoing_destination(question, f'{OUTGOING} → SS')
    wait_for_pitcher_change(
        page, coachboard_url, game_id, dict(BASE, P='Shortstop Shawn', SS=OUTGOING),
    )


# ------------------------------------------------------------------ cancel


def test_cancel_changes_nothing(page: Page, coachboard_url, live_field):
    game_id = live_field()
    posts = record_pitching_changes(page)

    question = choose_incoming_pitcher(page, 'Shortstop Shawn')
    choose_outgoing_destination(question, 'Cancel')

    page.wait_for_timeout(800)
    assert posts == []
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == BASE
    assert pitcher_changes(state) == []
    expect(page.locator('#cbDugoutHeader [data-cb-pitcher]')).to_contain_text(OUTGOING)


def test_closing_the_question_changes_nothing(page: Page, coachboard_url, live_field):
    """Escape and the close button are Cancel too, and Change Pitcher opens
    again normally afterwards."""
    game_id = live_field()
    posts = record_pitching_changes(page)

    question = choose_incoming_pitcher(page, RELIEVER)
    # Escape once the question has the focus, as a keyboard user would.
    page.wait_for_function(
        f"() => document.querySelector('{DESTINATION_QUESTION}').contains(document.activeElement)")
    page.keyboard.press('Escape')
    expect(question).not_to_be_visible(timeout=10_000)

    question = choose_incoming_pitcher(page, 'Shortstop Shawn')
    question.locator('.btn-close').click()
    expect(question).not_to_be_visible(timeout=10_000)

    page.wait_for_timeout(800)
    assert posts == []
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == BASE
    assert pitcher_changes(state) == []
    question = choose_incoming_pitcher(page, 'Shortstop Shawn')
    expect_destination_question(question, 'Shortstop Shawn', OUTGOING)


# ------------------------------------------------------------- two coaches


def test_field_changed_by_another_coach_cancels_the_open_question(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    posts = record_pitching_changes(page)

    question = choose_incoming_pitcher(page, 'Shortstop Shawn')

    # While this coach is deciding, another coach swaps LF and RF.
    other = dict(BASE, LF='Right Riley', RF='Left Lee')
    edit_field(page, coachboard_url, game_id, other)

    # The stale question closes by itself; nothing is applied.
    expect(question).not_to_be_visible(timeout=10_000)
    expect(page.locator(TOAST)).to_contain_text(STALE)
    page.wait_for_timeout(500)
    assert posts == []
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == other
    assert pitcher_changes(state) == []


def test_stale_save_is_refused_with_the_same_message(
    page: Page, coachboard_url, live_field
):
    """If the change still reaches the server, the version check refuses it."""
    game_id = live_field()
    question = choose_incoming_pitcher(page, 'Shortstop Shawn')

    # Hide the other coach's update from this page, then answer.
    page.evaluate(
        """() => {
            const stop = event => event.stopImmediatePropagation();
            document.addEventListener('coachboard:live-delta', stop, true);
            document.addEventListener('coachboard:live-state', stop, true);
        }"""
    )
    other = dict(BASE, LF='Right Riley', RF='Left Lee')
    edit_field(page, coachboard_url, game_id, other)
    choose_outgoing_destination(question, f'{OUTGOING} → SS')

    expect(page.locator(TOAST).last).to_contain_text(STALE, timeout=10_000)
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == other
    assert pitcher_changes(state) == []
