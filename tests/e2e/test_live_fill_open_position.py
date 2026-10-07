"""On the Field → tap an Open position → choose who fills it.

Anyone can fill an open position: a bench player, or a player at another
position. A field player moves there and leaves their old position open --
the same move drag-and-drop makes -- and nothing else moves. The pitcher is
special: choosing the pitcher goes to Change Pitcher instead of moving P.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect

from live_fixtures import (  # noqa: F401 (fixture)
    BASE,
    RELIEVER,
    set_live_defense as edit_field,
    filled,
    live_field,
    live_state,
    pitcher_changes,
    wait_for_field,
)


OPEN_SS = {pos: name for pos, name in BASE.items() if pos != 'SS'}


def defense_writes(page: Page):
    posts = []
    page.on(
        'request',
        lambda request: posts.append(request.post_data_json)
        if request.method == 'POST' and 'defense-edit' in request.url
        else None,
    )
    return posts


def open_fill_sheet(page: Page, position='SS'):
    spot = page.locator(f'#cbQuickDefense [data-cb-position="{position}"]')
    expect(spot).to_contain_text('Open', timeout=10_000)
    spot.click()
    sheet = page.locator('#cbQuickMoveModal')
    expect(sheet).to_be_visible(timeout=10_000)
    expect(sheet.locator('.modal-title')).to_have_text(f'Fill {position}')
    return sheet


def choice(sheet, name):
    label = sheet.page.get_by_text(re.compile(rf'^(#\S+ )?{re.escape(name)}$'))
    return sheet.locator('[data-cb-fill-open-player]', has=label)


def events(state):
    return [e for e in state.get('rotation_events', []) if not e.get('reverted')]


def assert_one_player_per_position(alignment):
    names = list(filled(alignment).values())
    assert len(names) == len(set(names))


@pytest.fixture
def open_ss_field(page: Page, coachboard_url, live_field):
    game_id = live_field()
    edit_field(page, coachboard_url, game_id, OPEN_SS)
    page.reload(wait_until='domcontentloaded')
    expect(
        page.locator('#cbQuickDefense [data-cb-position="SS"]')
    ).to_contain_text('Open', timeout=15_000)
    return game_id


def test_sheet_offers_bench_and_field_players_with_where_they_are(
    page: Page, coachboard_url, open_ss_field
):
    sheet = open_fill_sheet(page)
    expect(sheet).to_contain_text('Choose a player to put at SS.')
    expect(sheet).not_to_contain_text('Choose a bench player')
    expect(choice(sheet, RELIEVER)).to_contain_text('Bench → SS')
    expect(choice(sheet, 'Shortstop Shawn')).to_contain_text('Bench → SS')
    expect(choice(sheet, 'Second Sam')).to_contain_text('2B → SS · 2B left open')
    expect(choice(sheet, 'Left Lee')).to_contain_text('LF → SS · LF left open')
    expect(choice(sheet, 'Pitcher Pat')).to_contain_text('P → SS · choose a new pitcher first')
    # Every player on the field is offered, once each.
    expect(
        sheet.locator('[data-cb-fill-open-player]:not([data-cb-fill-from="Bench"])')
    ).to_have_count(8)


def test_bench_player_fills_the_open_position(
    page: Page, coachboard_url, open_ss_field
):
    game_id = open_ss_field
    choice(open_fill_sheet(page), RELIEVER).click()
    expected = dict(OPEN_SS, SS=RELIEVER)
    wait_for_field(page, coachboard_url, game_id, expected)
    assert_one_player_per_position(live_state(page, coachboard_url, game_id)['current_alignment'])


@pytest.mark.parametrize('name, source', [
    ('Second Sam', '2B'),
    ('Left Lee', 'LF'),
], ids=['from_2B', 'from_LF'])
def test_field_player_moves_and_leaves_their_position_open(
    page: Page, coachboard_url, open_ss_field, name, source
):
    game_id = open_ss_field
    writes = defense_writes(page)
    before_events = len(events(live_state(page, coachboard_url, game_id)))

    sheet = open_fill_sheet(page)
    choice(sheet, name).click()
    expect(sheet).not_to_be_visible(timeout=10_000)

    # Exactly the chosen move: nobody else is swapped or benched.
    expected = {pos: player for pos, player in OPEN_SS.items() if pos != source}
    expected['SS'] = name
    wait_for_field(page, coachboard_url, game_id, expected)
    assert len(writes) == 1
    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == expected
    assert_one_player_per_position(state['current_alignment'])
    assert len(events(state)) == before_events + 1

    # The newly opened position is visibly Open and tappable.
    expect(
        page.locator(f'#cbQuickDefense [data-cb-position="{source}"]')
    ).to_contain_text('Open', timeout=10_000)

    # One Undo restores the original field.
    page.locator('#liveUndoBtn').click()
    wait_for_field(page, coachboard_url, game_id, OPEN_SS)


def test_choosing_the_pitcher_goes_to_change_pitcher(
    page: Page, coachboard_url, open_ss_field
):
    game_id = open_ss_field
    writes = defense_writes(page)

    sheet = open_fill_sheet(page)
    choice(sheet, 'Pitcher Pat').click()
    expect(sheet).not_to_be_visible(timeout=10_000)

    # Pat is not moved off P; the coach first says who pitches.
    picker = page.locator('#live-pitcher-picker-v2')
    expect(picker).to_be_visible(timeout=10_000)
    page.wait_for_timeout(400)
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == OPEN_SS

    # Then the open SS is Pat's one-tap destination in Change Pitcher.
    picker.locator('.pitcher-choice-v2', has=page.get_by_text(RELIEVER, exact=True)).click()
    question = page.locator('#live-pitcher-destination-v7')
    expect(question).to_be_visible(timeout=10_000)
    question.get_by_role('button', name='Put Pitcher Pat at SS', exact=True).click()
    wait_for_field(page, coachboard_url, game_id, dict(OPEN_SS, P=RELIEVER, SS='Pitcher Pat'))
    assert len(pitcher_changes(live_state(page, coachboard_url, game_id))) == 1


def test_cancel_changes_nothing(page: Page, coachboard_url, open_ss_field):
    game_id = open_ss_field
    writes = defense_writes(page)
    sheet = open_fill_sheet(page)
    sheet.locator('.btn-close').click()
    expect(sheet).not_to_be_visible(timeout=10_000)
    page.wait_for_timeout(500)
    assert writes == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == OPEN_SS


def drag(page: Page, source, target):
    source_box = source.bounding_box()
    target_box = target.bounding_box()
    assert source_box and target_box
    page.mouse.move(source_box['x'] + source_box['width'] / 2, source_box['y'] + source_box['height'] / 2)
    page.mouse.down()
    page.mouse.move(target_box['x'] + target_box['width'] / 2, target_box['y'] + target_box['height'] / 2, steps=12)
    page.mouse.up()


def test_tap_and_drag_make_the_same_move(page: Page, coachboard_url, open_ss_field):
    game_id = open_ss_field
    quick = page.locator('#cbQuickDefense')

    # Drag Sam from 2B onto the open SS.
    drag(page, quick.locator('[data-cb-position="2B"]'), quick.locator('[data-cb-position="SS"]'))
    dragged = {pos: player for pos, player in OPEN_SS.items() if pos != '2B'}
    dragged['SS'] = 'Second Sam'
    wait_for_field(page, coachboard_url, game_id, dragged)

    # Back to the same starting field, then the same move by tap.
    page.wait_for_timeout(750)
    page.locator('#liveUndoBtn').click()
    wait_for_field(page, coachboard_url, game_id, OPEN_SS)
    page.wait_for_timeout(300)
    choice(open_fill_sheet(page), 'Second Sam').click()
    wait_for_field(page, coachboard_url, game_id, dragged)
