"""Live Game has to fit a landscape tablet, not just a phone.

Both live fields used to be sized from the viewport width alone, in three
places at once (live_game_sync_status.js, live_game_field_realism.js and the
.cb-qd-field base min-height). Width is the wrong input: a 1024x768 iPad is
wide enough for a 690px diamond and nowhere near tall enough for the 539px of
height that implies, so Change Pitcher and End Inning ended up below the fold.
live_game_board_prep_v2.js now owns landscape sizing for both fields and
derives it from the viewport height.

The live field and the full-screen Next Inning planner do not share a
vertical budget -- the planner has its own bar (Live Field, Plan Undo) and a
heading above its field -- so they are measured separately here. End Inning
belongs to the live field; the planner is measured without it.
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
from live_fixtures import PLANNER, open_next_inning_planner, return_to_live_field  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

SWITCHER = '#cb-now-next-switch'
NOW_FIELD = '#cbQuickDefense .cb-qd-field'
NEXT_FIELD = '#live-board-prep-v3 .cb-next-field'

TABLET_LANDSCAPE = [
    (1024, 768),
    (1180, 820),
    (1376, 1032),
]

# A fielder marker stays tappable. 44px is the short edge everyone agrees on;
# the markers are wider than they are tall, so the floor is applied to both.
MIN_TOUCH = 44
MIN_MARKER_WIDTH = 56


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(
        re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:games|overview))?$')
    )


def post_json(page: Page, coachboard_url: str, path: str, data):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == 200, (
        f'POST {path} returned {response.status}: {response.text()}'
    )
    payload = response.json()
    assert payload.get('status') == 'success', payload
    return payload


def alignment():
    return {
        'P': 'Pitcher Pat',
        'C': 'Catcher Cole',
        '1B': 'First Frank',
        '2B': 'Second Sam',
        '3B': 'Third Theo',
        'SS': 'Shortstop Shawn',
        'LF': 'Left Lee',
        'CF': 'Center Casey',
        'RF': 'Right Riley',
    }


def create_live_game(page: Page, coachboard_url: str, opponent: str):
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=11)).isoformat(),
            'game_start_time': '15:00',
            'game_opponent': opponent,
            'game_location': 'Landscape Fit Field',
            'game_notes': 'Disposable landscape-fit browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    roster = page.request.get(f'{coachboard_url}/api/roster').json()
    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Landscape Fit Lineup',
        'lineup_player_ids': [int(player['id']) for player in roster],
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Landscape Fit Rotation',
        'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', start_body(page.request, coachboard_url, game_id))
    return game_id


def cleanup_game(page: Page, coachboard_url: str, game_id: int):
    """A live game left behind locks the roster for later tests."""
    state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
    if state.ok and state.json().get('game', {}).get('is_live'):
        page.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/end-with-pitching',
            data={
                'defer_pitching': True,
                'end_reason': 'manual',
                'current_inning_played': True,
            },
        )
    page.request.post(
        f'{coachboard_url}/game-day/{game_id}/delete',
        headers={'Accept': 'application/json'},
    )


def open_live_game(page: Page, coachboard_url: str, game_id: int):
    page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
    expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=20_000)
    expect(page.locator(SWITCHER)).to_be_visible(timeout=15_000)


def show(page: Page, surface: str):
    """'live': the live field. 'planner': the full-screen Next Inning planner,
    opened and closed with the coach's own controls."""
    planner = page.locator(PLANNER)
    if surface == 'planner':
        if not planner.is_visible():
            open_next_inning_planner(page)
        expect(planner).to_be_visible(timeout=15_000)
    else:
        if planner.is_visible():
            return_to_live_field(page)
        expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)


MEASURE = """
(selectors) => {
  // Dugout Mode scrolls #live-game-overlay, not the document. Start from the
  // top so every rectangle below is the position a coach opens onto.
  const overlay = document.getElementById('live-game-overlay');
  if (overlay) overlay.scrollTop = 0;

  const box = selector => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) return null;
    return {
      top: Math.round(r.top), bottom: Math.round(r.bottom),
      left: Math.round(r.left), right: Math.round(r.right),
      width: Math.round(r.width), height: Math.round(r.height),
    };
  };

  // The live field's "Plan next inning" button.
  const tabs = [...document.querySelectorAll('#cb-now-next-switch [data-now-next]')];
  const tabWraps = tabs.map(tab => {
    // A label that fits on one line paints as a single client rect.
    const range = document.createRange();
    range.selectNodeContents(tab);
    return {
      label: tab.textContent.trim(),
      lines: range.getClientRects().length,
      height: Math.round(tab.getBoundingClientRect().height),
    };
  });

  const markers = [...document.querySelectorAll(selectors.field + ' .cb-qd-spot')]
    .map(spot => {
      const r = spot.getBoundingClientRect();
      return {width: Math.round(r.width), height: Math.round(r.height)};
    });

  return {
    viewport: {width: window.innerWidth, height: window.innerHeight},
    overflowX: Math.max(
      0,
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ),
    boxes: Object.fromEntries(
      Object.entries(selectors).map(([name, sel]) => [name, box(sel)]),
    ),
    tabs: tabWraps,
    markers,
  };
}
"""


LIVE_CONTROLS = {
    'header': '#cbDugoutHeader',
    'switcher': SWITCHER,
    'changePitcher': '#liveChangePitcherBtn',
    'endInning': '#liveEndInningBtn',
}
PLANNER_CONTROLS = {
    'planBar': f'{PLANNER} .cb-next-bar',
    'liveField': f'{PLANNER} [data-next-close]',
    'planUndo': f'{PLANNER} [data-next-undo-local]',
}


def measure(page: Page, field: str, extra=None):
    selectors = {'field': field, **(LIVE_CONTROLS if field == NOW_FIELD else PLANNER_CONTROLS)}
    selectors.update(extra or {})
    return page.evaluate(MEASURE, selectors)


def assert_no_horizontal_overflow(data, label):
    assert data['overflowX'] <= 2, (
        f'{label}: page overflows horizontally by {data["overflowX"]}px'
    )


def assert_plan_button_on_one_line(data, label):
    assert data['tabs'], f'{label}: no Plan next inning button'
    for tab in data['tabs']:
        assert tab['lines'] == 1, (
            f'{label}: {tab["label"]!r} wrapped onto {tab["lines"]} lines'
        )


def assert_field_inside_card(page: Page, field: str, card: str, label: str):
    inset = page.evaluate(
        """([fieldSel, cardSel]) => {
          const field = document.querySelector(fieldSel);
          const card = document.querySelector(cardSel);
          const f = field.getBoundingClientRect();
          const c = card.getBoundingClientRect();
          return {
            top: Math.round(f.top - c.top),
            bottom: Math.round(c.bottom - f.bottom),
            left: Math.round(f.left - c.left),
            right: Math.round(c.right - f.right),
          };
        }""",
        [field, card],
    )
    for edge, value in inset.items():
        assert value >= -1, (
            f'{label}: field escapes its card on the {edge} by {-value}px '
            f'({inset})'
        )


def assert_markers_are_tappable(data, label):
    assert data['markers'], f'{label}: no fielder markers found'
    for marker in data['markers']:
        assert marker['width'] >= MIN_MARKER_WIDTH, (
            f'{label}: fielder marker collapsed to {marker["width"]}px wide'
        )
        assert marker['height'] >= MIN_TOUCH, (
            f'{label}: fielder marker collapsed to {marker["height"]}px tall'
        )


def test_on_the_field_fits_a_1024x768_tablet(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Landscape Now Fit')

    try:
        open_live_game(page, coachboard_url, game_id)
        show(page, 'live')

        data = measure(page, NOW_FIELD, {'bench': '#cbQuickDefense .cb-qd-bench-wrap'})
        height = data['viewport']['height']

        for name in ('header', 'switcher', 'field', 'bench',
                     'changePitcher', 'endInning'):
            box = data['boxes'][name]
            assert box, f'On the Field at 1024x768: {name} is missing'
            assert box['bottom'] <= height, (
                f'On the Field at 1024x768: {name} ends {box["bottom"] - height}px '
                f'below the fold (bottom={box["bottom"]}, viewport={height})'
            )

        assert_no_horizontal_overflow(data, 'On the Field at 1024x768')
        assert_plan_button_on_one_line(data, 'On the Field at 1024x768')
        assert_markers_are_tappable(data, 'On the Field at 1024x768')
        assert_field_inside_card(
            page, NOW_FIELD, '#cbQuickDefense', 'On the Field at 1024x768'
        )
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_next_inning_fits_a_1024x768_tablet(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Landscape Next Fit')

    try:
        open_live_game(page, coachboard_url, game_id)
        show(page, 'planner')
        # At rest there is no move instruction; the header shows the plan.
        expect(page.locator(HINT)).not_to_contain_text('Moving')

        data = measure(page, NEXT_FIELD, {
            'heading': '#live-board-prep-v3 .cb-next-title',
            'bench': '#live-board-prep-v3 .cb-next-bench',
        })
        height = data['viewport']['height']

        for name in ('planBar', 'liveField', 'planUndo', 'heading',
                     'field', 'bench'):
            box = data['boxes'][name]
            assert box, f'Next Inning at 1024x768: {name} is missing'
            assert box['bottom'] <= height, (
                f'Next Inning at 1024x768: {name} ends '
                f'{box["bottom"] - height}px below the fold '
                f'(bottom={box["bottom"]}, viewport={height})'
            )

        assert_no_horizontal_overflow(data, 'Next Inning at 1024x768')
        assert_markers_are_tappable(data, 'Next Inning at 1024x768')
        assert_field_inside_card(
            page, NEXT_FIELD, '#live-board-prep-v3', 'Next Inning at 1024x768'
        )
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_landscape_tablets_keep_both_fields_inside_their_cards(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Landscape Sweep')

    try:
        for width, height in TABLET_LANDSCAPE:
            page.set_viewport_size({'width': width, 'height': height})
            open_live_game(page, coachboard_url, game_id)

            for view, field, card in (
                ('live', NOW_FIELD, '#cbQuickDefense'),
                ('planner', NEXT_FIELD, '#live-board-prep-v3'),
            ):
                label = f'{view} at {width}x{height}'
                show(page, view)
                data = measure(page, field)

                assert_no_horizontal_overflow(data, label)
                if view == 'live':
                    assert_plan_button_on_one_line(data, label)
                assert_markers_are_tappable(data, label)
                assert_field_inside_card(page, field, card, label)

                box = data['boxes']['field']
                ratio = box['width'] / box['height']
                assert 1.2 <= ratio <= 1.36, (
                    f'{label}: field aspect ratio drifted to {ratio:.3f}'
                )

                if view == 'live':
                    assert data['boxes']['endInning']['bottom'] <= height, (
                        f'{label}: End Inning is below the fold'
                    )
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_landscape_fields_are_sized_by_height_not_only_width(page: Page, coachboard_url: str):
    """The same width at two heights must not produce the same live field.

    This is the regression that started B2: picking a fixed width per
    breakpoint made 1024x768 and 1024x1366 render an identical diamond, and
    only one of those screens had room for it. The full-screen planner has
    the whole screen to itself, in two columns: its field must fit the
    screen at both heights.
    """
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Landscape Height Aware')

    try:
        heights = {}
        for viewport_height in (720, 900):
            page.set_viewport_size({'width': 1280, 'height': viewport_height})
            open_live_game(page, coachboard_url, game_id)

            show(page, 'live')
            heights[viewport_height] = measure(page, NOW_FIELD)['boxes']['field']['height']

            show(page, 'planner')
            label = f'planner at 1280x{viewport_height}'
            data = measure(page, NEXT_FIELD)
            box = data['boxes']['field']
            assert box['top'] >= data['boxes']['planBar']['bottom'] - 1, f'{label}: field under the bar {data}'
            assert box['bottom'] <= viewport_height, (
                f'{label}: field ends {box["bottom"] - viewport_height}px below the fold'
            )
            assert_field_inside_card(page, NEXT_FIELD, PLANNER, label)

        short, tall = heights[720], heights[900]
        assert tall > short + 20, (
            f'live field measured {short}px at 1280x720 and {tall}px at '
            f'1280x900 -- it is not responding to the vertical budget'
        )
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_portrait_and_phone_are_untouched_by_landscape_sizing(page: Page, coachboard_url: str):
    """The landscape owner is landscape-scoped; these must not have moved."""
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Landscape Other Shapes')

    try:
        for width, height in ((768, 1024), (390, 844)):
            page.set_viewport_size({'width': width, 'height': height})
            open_live_game(page, coachboard_url, game_id)

            for view, field, card in (
                ('live', NOW_FIELD, '#cbQuickDefense'),
                ('planner', NEXT_FIELD, '#live-board-prep-v3'),
            ):
                label = f'{view} at {width}x{height}'
                show(page, view)
                data = measure(page, field)

                assert_no_horizontal_overflow(data, label)
                if view == 'live':
                    assert_plan_button_on_one_line(data, label)
                assert_field_inside_card(page, field, card, label)

                box = data['boxes']['field']
                assert box['width'] > 0 and box['height'] > 0, (
                    f'{label}: field collapsed to {box}'
                )
    finally:
        cleanup_game(page, coachboard_url, game_id)


HINT = '#live-board-prep-v3 [data-next-hint]'

# The move hint is one line in the card header, in place of the plan line.
HINT_LINE = """(sel) => {
  const el = document.querySelector(sel);
  const style = getComputedStyle(el);
  return {
    height: el.getBoundingClientRect().height,
    font: parseFloat(style.fontSize),
    clipped: el.scrollWidth > el.clientWidth + 1,
  };
}"""


def start_move(page: Page, position='SS'):
    page.locator(f'{NEXT_FIELD} [data-next-position="{position}"]').click()
    expect(page.locator(HINT)).to_contain_text('Moving')


def field_top(page: Page):
    return page.locator(NEXT_FIELD).bounding_box()['y']


def test_next_inning_mid_move_fits_a_1024x768_tablet(page: Page, coachboard_url: str):
    """The old STEP 2 panel pushed the field down and off the screen.
    Mid-move now changes one header line and nothing moves."""
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Landscape Mid Move')

    try:
        open_live_game(page, coachboard_url, game_id)
        show(page, 'planner')
        expect(page.locator(f'{NEXT_FIELD} [data-next-position="SS"]')).to_contain_text('Shortstop Shawn')
        at_rest = measure(page, NEXT_FIELD, {'bench': '#live-board-prep-v3 .cb-next-bench'})
        start_move(page)

        data = measure(page, NEXT_FIELD, {
            'hint': HINT, 'bench': '#live-board-prep-v3 .cb-next-bench',
        })
        height = data['viewport']['height']
        for name in ('planBar', 'hint', 'field', 'bench'):
            box = data['boxes'][name]
            assert box and box['bottom'] <= height, f'mid-move at 1024x768: {name} {box} below {height}'
        for name in ('planBar', 'field', 'bench'):
            assert abs(data['boxes'][name]['top'] - at_rest['boxes'][name]['top']) <= 1, (
                f'{name} moved when a player was tapped'
            )
        assert_no_horizontal_overflow(data, 'Next Inning mid-move at 1024x768')
        assert_markers_are_tappable(data, 'Next Inning mid-move at 1024x768')
        assert_field_inside_card(page, NEXT_FIELD, '#live-board-prep-v3', 'Next Inning mid-move at 1024x768')

        hint = page.evaluate(HINT_LINE, HINT)
        assert not hint['clipped'] and hint['font'] >= 10, hint

        # Finishing the move still works: SS onto 2B swaps the two at once.
        page.locator(f'{NEXT_FIELD} [data-next-position="2B"]').click()
        expect(page.locator(HINT)).not_to_contain_text('Moving', timeout=10_000)
        expect(page.locator(f'{NEXT_FIELD} [data-next-position="2B"]')).to_contain_text('Shortstop Shawn', timeout=10_000)
        expect(page.locator(f'{NEXT_FIELD} [data-next-position="SS"]')).to_contain_text('Second Sam')
        after = measure(page, NEXT_FIELD, {'bench': '#live-board-prep-v3 .cb-next-bench'})
        for name in ('field', 'bench'):
            assert after['boxes'][name]['bottom'] <= height, f'after the move: {name} below {height}'

        # Tapping the moving player again cancels; the field is as it was.
        start_move(page, 'CF')
        page.locator(f'{NEXT_FIELD} [data-next-position="CF"]').click()
        expect(page.locator(HINT)).not_to_contain_text('Moving')
        expect(page.locator(f'{NEXT_FIELD} [data-next-position="CF"]')).to_contain_text('Center Casey')
    finally:
        cleanup_game(page, coachboard_url, game_id)


@pytest.mark.parametrize('size', [(1180, 820), (1440, 900), (768, 1024), (390, 844)],
                         ids=lambda s: f'{s[0]}x{s[1]}')
def test_a_move_keeps_the_field_in_place_elsewhere(page: Page, coachboard_url: str, size):
    """Landscape, portrait and phone: the hint is one line and the field stays put."""
    width, height = size
    page.set_viewport_size({'width': width, 'height': height})
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, f'Mid Move {width}x{height}')

    try:
        open_live_game(page, coachboard_url, game_id)
        show(page, 'planner')
        expect(page.locator(f'{NEXT_FIELD} [data-next-position="SS"]')).to_contain_text('Shortstop Shawn')
        before = field_top(page)
        resting = page.evaluate(HINT_LINE, HINT)
        start_move(page)
        assert abs(field_top(page) - before) < 1, f'field moved at {width}x{height}'
        hint = page.evaluate(HINT_LINE, HINT)
        assert abs(hint['height'] - resting['height']) < 1, (resting, hint)
        assert_no_horizontal_overflow(measure(page, NEXT_FIELD), f'mid-move at {width}x{height}')
    finally:
        cleanup_game(page, coachboard_url, game_id)
