"""On the Field → Change Pitcher records the decision the coach made.

Choosing the new pitcher says who is going in to pitch. Where the pitcher
coming out goes is a separate baseball decision, so CoachBoard asks it and
changes nothing on the official field until it is answered. The answer is
saved as one pitching change: one event, one Undo.
"""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect
from start_helpers import start_body  # noqa: E402

from e2e_cleanup import delete_players_named
from test_next_inning_save_race import cleanup_game, login, post_json


PHONE = {'width': 430, 'height': 932}
QUESTION = '#live-pitcher-destination-v7'
RELIEVER = 'Bench Blake'
STALE = (
    'Defense changed on another device. '
    'Check the field and try the pitching change again.'
)

BASE = {
    'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
    '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
    'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
}


def filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def live_state(page: Page, url: str, game_id: int):
    response = page.request.get(f'{url}/api/live-game/{game_id}/state')
    assert response.ok, response.text()[:300]
    return response.json()


def sequence(state):
    return max(
        [int(e.get('sequence') or 0) for e in state.get('rotation_events', []) if not e.get('reverted')]
        or [0]
    )


def edit_field(page: Page, url: str, game_id: int, alignment):
    """Another coach's On the Field change."""
    state = live_state(page, url, game_id)
    response = page.request.post(
        f'{url}/api/live-game/{game_id}/defense-edit',
        data={'alignment': alignment, 'base_sequence': sequence(state)},
    )
    assert response.ok, response.text()[:300]


@pytest.fixture
def live_field(page: Page, coachboard_url: str):
    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    game_id = None
    try:
        response = page.request.post(
            f'{coachboard_url}/add_player',
            form={
                'name': RELIEVER, 'number': '10', 'position1': '', 'position2': '',
                'position3': '', 'throws': 'Right', 'bats': 'Right', 'notes': '',
                'pitcher_role': 'Starter', 'roster_status': 'regular',
            },
            headers={'X-Requested-With': 'XMLHttpRequest'},
            max_redirects=0,
        )
        assert response.status == 200 and response.json()['status'] == 'success'

        response = page.request.post(
            f'{coachboard_url}/game-day/add',
            form={
                'game_date': (date.today() + timedelta(days=14)).isoformat(),
                'game_start_time': '11:00',
                'game_opponent': 'Pitching Change Opponent',
                'game_location': 'Pitching Change Field',
                'pitching_rule_set': 'USSSA',
            },
            max_redirects=0,
        )
        game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
        post_json(page, coachboard_url, '/save_rotation', {
            'title': 'Pitching Change Plan',
            'innings': {'1': BASE},
            'associated_game_id': game_id,
        })
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', start_body(page.request, coachboard_url, game_id))

        def open_field(before_load=None):
            if before_load:
                before_load(game_id)
            page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
            expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
            expect(
                page.locator('#cbQuickDefense [data-cb-position="SS"]')
            ).to_contain_text('Shortstop Shawn', timeout=10_000)
            return game_id

        yield open_field
    finally:
        if game_id is not None:
            cleanup_game(page, coachboard_url, game_id)
        assert delete_players_named(page.request, coachboard_url, [RELIEVER]) == []


def record_pitching_changes(page: Page):
    posts = []
    page.on(
        'request',
        lambda request: posts.append(request.post_data_json)
        if request.method == 'POST' and 'complete-pitcher-change' in request.url
        else None,
    )
    return posts


def choose_new_pitcher(page: Page, name: str):
    page.locator('#liveChangePitcherBtn').click()
    picker = page.locator('#live-pitcher-picker-v2')
    expect(picker).to_be_visible(timeout=10_000)
    # Exact name: another suite's "Drag Bench Blake" contains "Bench Blake".
    picker.locator('.pitcher-choice-v2', has=page.get_by_text(name, exact=True)).click()
    expect(picker).not_to_be_visible(timeout=10_000)
    question = page.locator(QUESTION)
    expect(question).to_be_visible(timeout=10_000)
    return question


def answer(question, label):
    question.get_by_role('button', name=label, exact=True).click()
    expect(question).not_to_be_visible(timeout=10_000)


def choices(question):
    return [text.strip() for text in question.locator('[data-pc-choices] button').all_inner_texts()]


def pitcher_changes(state):
    return [
        event for event in state.get('rotation_events', [])
        if event.get('event_type') == 'Pitcher Change' and not event.get('reverted')
    ]


def player_id(state, name):
    return next(int(p['id']) for p in state['roster'] if p['name'] == name)


def wait_for_field(page, url, game_id, expected, timeout_ms=10_000):
    waited = 0
    while waited < timeout_ms:
        if filled(live_state(page, url, game_id)['current_alignment']) == expected:
            return
        page.wait_for_timeout(200)
        waited += 200
    assert filled(live_state(page, url, game_id)['current_alignment']) == expected


# ------------------------------------------------------ fielder → pitcher


def test_shortstop_pitches_and_coach_sends_pitcher_to_short(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    posts = record_pitching_changes(page)
    before = live_state(page, coachboard_url, game_id)

    question = choose_new_pitcher(page, 'Shortstop Shawn')
    expect(question).to_contain_text('Shortstop Shawn is going in to pitch')
    expect(question).to_contain_text('Where should Pitcher Pat go?')
    assert choices(question) == [
        'Put Pitcher Pat at SS', 'Move Pitcher Pat to another position…',
        'Bench Pitcher Pat · SS open', 'Cancel',
    ]

    # Nothing official happens while the coach decides.
    page.wait_for_timeout(600)
    assert posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE

    answer(question, 'Put Pitcher Pat at SS')
    swapped = dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat')
    wait_for_field(page, coachboard_url, game_id, swapped)
    assert len(posts) == 1

    # One pitching-change event, recording exactly the coach's choice.
    after = live_state(page, coachboard_url, game_id)
    events = pitcher_changes(after)
    assert len(events) == 1
    event = events[0]
    assert filled(event['before_alignment']) == BASE
    assert filled(event['after_alignment']) == swapped
    assert event['old_pitcher_id'] == player_id(before, 'Pitcher Pat')
    assert event['new_pitcher_id'] == player_id(before, 'Shortstop Shawn')
    expect(page.locator('#cbDugoutHeader [data-cb-pitcher]')).to_contain_text(
        'Shortstop Shawn', timeout=10_000
    )

    # One Undo restores the whole change: pitcher and field together.
    page.locator('#liveUndoBtn').click()
    wait_for_field(page, coachboard_url, game_id, BASE)
    assert pitcher_changes(live_state(page, coachboard_url, game_id)) == []


def test_shortstop_pitches_and_coach_benches_the_pitcher(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()

    question = choose_new_pitcher(page, 'Shortstop Shawn')
    answer(question, 'Bench Pitcher Pat · SS open')

    expected = {pos: name for pos, name in BASE.items() if pos != 'SS'}
    expected['P'] = 'Shortstop Shawn'
    wait_for_field(page, coachboard_url, game_id, expected)

    quick = page.locator('#cbQuickDefense')
    expect(quick.locator('[data-cb-position="SS"]')).to_contain_text('Open', timeout=10_000)
    expect(quick.locator('.cb-qd-bench')).to_contain_text('Pitcher Pat')
    expect(page.locator('#pitcher-change-toast-v6 .toast-body')).to_contain_text(
        'Shortstop Shawn is pitching · Pitcher Pat to Bench · SS is open'
    )


# -------------------------------------------------------- bench → pitcher


def test_bench_player_pitches_and_coach_places_the_pitcher(
    page: Page, coachboard_url, live_field
):
    # Left field is open when the change is made.
    open_lf = {pos: name for pos, name in BASE.items() if pos != 'LF'}
    game_id = live_field(
        lambda gid: edit_field(page, coachboard_url, gid, open_lf)
    )

    question = choose_new_pitcher(page, RELIEVER)
    expect(question).to_contain_text(f'{RELIEVER} is going in to pitch')
    # The open spot is offered by name and is still one tap; nothing is
    # decided for the coach.
    assert choices(question) == [
        'Put Pitcher Pat at LF', 'Move Pitcher Pat to another position…',
        'Bench Pitcher Pat', 'Cancel',
    ]

    answer(question, 'Put Pitcher Pat at LF')
    wait_for_field(
        page, coachboard_url, game_id,
        dict(open_lf, P=RELIEVER, LF='Pitcher Pat'),
    )


# -------------------------------------------------------- pitcher → field


def test_tapping_the_pitcher_asks_who_pitches_first(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    posts = record_pitching_changes(page)

    # "Pat is moving" starts with who is pitching; the SS is not assumed.
    page.locator('#cbQuickDefense [data-cb-position="P"]').click()
    picker = page.locator('#live-pitcher-picker-v2')
    expect(picker).to_be_visible(timeout=10_000)
    expect(picker).to_contain_text('Current:')
    page.wait_for_timeout(400)
    assert posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE

    picker.locator('.pitcher-choice-v2', has_text='Shortstop Shawn').click()
    question = page.locator(QUESTION)
    expect(question).to_be_visible(timeout=10_000)
    answer(question, 'Put Pitcher Pat at SS')
    wait_for_field(
        page, coachboard_url, game_id,
        dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat'),
    )


# ------------------------------------------------------------------ cancel


def test_cancel_changes_nothing(page: Page, coachboard_url, live_field):
    game_id = live_field()
    posts = record_pitching_changes(page)

    question = choose_new_pitcher(page, 'Shortstop Shawn')
    answer(question, 'Cancel')

    page.wait_for_timeout(800)
    assert posts == []
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == BASE
    assert pitcher_changes(state) == []
    expect(page.locator('#cbDugoutHeader [data-cb-pitcher]')).to_contain_text('Pitcher Pat')


# ------------------------------------------------------------- two coaches


def test_field_changed_by_another_coach_cancels_the_open_question(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    posts = record_pitching_changes(page)

    question = choose_new_pitcher(page, 'Shortstop Shawn')

    # While this coach is deciding, another coach swaps LF and RF.
    other = dict(BASE, LF='Right Riley', RF='Left Lee')
    edit_field(page, coachboard_url, game_id, other)

    # The stale question closes by itself; nothing is applied.
    expect(question).not_to_be_visible(timeout=10_000)
    expect(page.locator('#pitcher-change-toast-v6 .toast-body')).to_contain_text(STALE)
    page.wait_for_timeout(500)
    assert posts == []
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == other
    assert pitcher_changes(state) == []


# ------------------------------------------------ occupied destinations


def step(question, label):
    """A choice that continues the conversation (the question stays open)."""
    question.get_by_role('button', name=label, exact=True).click()


def expect_question(question, title, text):
    expect(question.locator('[data-pc-title]')).to_have_text(title)
    expect(question.locator('[data-pc-question]')).to_have_text(text)


def test_bench_pitcher_in_old_pitcher_to_occupied_first_displaced_to_bench(
    page: Page, coachboard_url, live_field
):
    """Blake from the bench pitches; the coach puts Pat at 1B, then decides
    Frank (who was at 1B) sits. Every other position is occupied."""
    game_id = live_field()
    posts = record_pitching_changes(page)

    question = choose_new_pitcher(page, RELIEVER)
    expect_question(question, f'{RELIEVER} is going in to pitch', 'Where should Pitcher Pat go?')
    # Nothing is open: the coach can move Pat or bench him.
    assert choices(question) == [
        'Move Pitcher Pat to another position…', 'Bench Pitcher Pat', 'Cancel',
    ]

    step(question, 'Move Pitcher Pat to another position…')
    # Every position, with who is there now.
    assert choices(question) == [
        'C · Catcher Cole', '1B · First Frank', '2B · Second Sam', '3B · Third Theo',
        'SS · Shortstop Shawn', 'LF · Left Lee', 'CF · Center Casey', 'RF · Right Riley',
        'Back', 'Cancel',
    ]
    step(question, '1B · First Frank')

    # Frank is not benched or moved for the coach: CoachBoard asks.
    expect_question(
        question, 'Pitcher Pat is moving to 1B',
        'First Frank is at 1B. Where should First Frank go?',
    )
    assert choices(question) == [
        'Move First Frank to another position…', 'Bench First Frank', 'Cancel',
    ]
    step(question, 'Bench First Frank')

    # The resulting field, before anything changes.
    expect(question.locator('[data-pc-title]')).to_have_text('Check the pitching change')
    expect(question.locator('[data-pc-summary] li')).to_have_text([
        f'{RELIEVER} → P (from Bench)',
        'Pitcher Pat: P → 1B',
        'First Frank: 1B → Bench',
    ])
    page.wait_for_timeout(500)
    assert posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE

    answer(question, 'Make this change')
    expected = dict(BASE, P=RELIEVER, **{'1B': 'Pitcher Pat'})
    wait_for_field(page, coachboard_url, game_id, expected)
    assert len(posts) == 1
    events = pitcher_changes(live_state(page, coachboard_url, game_id))
    assert len(events) == 1
    assert filled(events[0]['before_alignment']) == BASE
    assert filled(events[0]['after_alignment']) == expected
    expect(page.locator('#pitcher-change-toast-v6 .toast-body')).to_contain_text(
        f'{RELIEVER} is pitching · Pitcher Pat to 1B · First Frank to Bench'
    )

    # One Undo restores the whole change.
    page.locator('#liveUndoBtn').click()
    wait_for_field(page, coachboard_url, game_id, BASE)
    assert pitcher_changes(live_state(page, coachboard_url, game_id)) == []


def test_fielder_pitches_and_displaced_player_takes_the_vacated_spot(
    page: Page, coachboard_url, live_field
):
    """Shawn (SS) pitches; Pat to 1B; the coach sends Frank to short."""
    game_id = live_field()
    question = choose_new_pitcher(page, 'Shortstop Shawn')
    step(question, 'Move Pitcher Pat to another position…')
    step(question, '1B · First Frank')

    expect_question(
        question, 'Pitcher Pat is moving to 1B',
        'First Frank is at 1B. Where should First Frank go?',
    )
    # The open short is offered, as is the bench -- neither is chosen.
    assert choices(question) == [
        'Put First Frank at SS', 'Move First Frank to another position…',
        'Bench First Frank · SS open', 'Cancel',
    ]
    step(question, 'Put First Frank at SS')
    expect(question.locator('[data-pc-summary] li')).to_have_text([
        'Shortstop Shawn → P (from SS)',
        'Pitcher Pat: P → 1B',
        'First Frank: 1B → SS',
    ])
    answer(question, 'Make this change')
    wait_for_field(
        page, coachboard_url, game_id,
        dict(BASE, P='Shortstop Shawn', **{'1B': 'Pitcher Pat', 'SS': 'First Frank'}),
    )
    assert len(pitcher_changes(live_state(page, coachboard_url, game_id))) == 1


def test_three_player_rotation(page: Page, coachboard_url, live_field):
    """Blake pitches; Pat → 1B; Frank → LF; Lee → bench."""
    game_id = live_field()
    posts = record_pitching_changes(page)
    question = choose_new_pitcher(page, RELIEVER)
    step(question, 'Move Pitcher Pat to another position…')
    step(question, '1B · First Frank')
    step(question, 'Move First Frank to another position…')
    # Pat, already placed at 1B by this change, is never offered again.
    offered = choices(question)
    assert '1B · Pitcher Pat' not in offered
    assert offered[:2] == ['C · Catcher Cole', '2B · Second Sam']
    step(question, 'LF · Left Lee')

    expect_question(
        question, 'First Frank is moving to LF',
        'Left Lee is at LF. Where should Left Lee go?',
    )
    step(question, 'Bench Left Lee')
    expect(question.locator('[data-pc-summary] li')).to_have_text([
        f'{RELIEVER} → P (from Bench)',
        'Pitcher Pat: P → 1B',
        'First Frank: 1B → LF',
        'Left Lee: LF → Bench',
    ])
    assert posts == []
    answer(question, 'Make this change')

    expected = dict(BASE, P=RELIEVER, **{'1B': 'Pitcher Pat', 'LF': 'First Frank'})
    wait_for_field(page, coachboard_url, game_id, expected)
    after = filled(live_state(page, coachboard_url, game_id)['current_alignment'])
    # No player twice, no position twice.
    assert len(set(after.values())) == len(after)
    assert len(posts) == 1
    assert len(pitcher_changes(live_state(page, coachboard_url, game_id))) == 1


def test_cancel_halfway_through_a_chain_changes_nothing(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    posts = record_pitching_changes(page)
    question = choose_new_pitcher(page, RELIEVER)
    step(question, 'Move Pitcher Pat to another position…')
    step(question, '1B · First Frank')
    expect(question.locator('[data-pc-question]')).to_contain_text('Where should First Frank go?')
    answer(question, 'Cancel')

    page.wait_for_timeout(800)
    assert posts == []
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == BASE
    assert pitcher_changes(state) == []

    # Canceling at the final check changes nothing either.
    question = choose_new_pitcher(page, RELIEVER)
    step(question, 'Move Pitcher Pat to another position…')
    step(question, '1B · First Frank')
    step(question, 'Bench First Frank')
    answer(question, 'Cancel')
    page.wait_for_timeout(800)
    assert posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE


def test_another_coach_changing_the_field_mid_chain_discards_it(
    page: Page, coachboard_url, live_field
):
    game_id = live_field()
    posts = record_pitching_changes(page)
    question = choose_new_pitcher(page, RELIEVER)
    step(question, 'Move Pitcher Pat to another position…')
    step(question, '1B · First Frank')

    other = dict(BASE, LF='Right Riley', RF='Left Lee')
    edit_field(page, coachboard_url, game_id, other)

    expect(question).not_to_be_visible(timeout=10_000)
    expect(page.locator('#pitcher-change-toast-v6 .toast-body')).to_contain_text(STALE)
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
    question = choose_new_pitcher(page, 'Shortstop Shawn')

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
    answer(question, 'Put Pitcher Pat at SS')

    expect(page.locator('#pitcher-change-toast-v6 .toast-body').last).to_contain_text(
        STALE, timeout=10_000
    )
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == other
    assert pitcher_changes(state) == []
