"""The shared drag contract, asserted identically on both live boards.

Every test here is parametrized over a board descriptor so that "On the
Field and Next Inning behave the same for a coach" is a property the
suite enforces, not a claim in a design note. If the two boards ever
diverge, one half of a parametrized pair goes red.

Touch input goes through CDP (see cdp_touch.py). That matters: the
pre-existing drag tests drive `page.mouse` at a phone viewport, which
reports `pointerType: 'mouse'` and therefore exercises the mouse branch
no matter how small the viewport is. They are phone-sized mouse tests.
Nothing in the suite touched the finger contract before this file.
"""

import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect

from cdp_touch import (
    DRAG_OVER_SELECTOR,
    GHOST_SELECTOR,
    TouchDriver,
    centre,
    centres,
    ghost_creations,
    make_overlay_scrollable,
    overlay_scroll_top,
    watch_ghosts,
)


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
# Each test gets its own bench player. add_player (roster.py:137-140)
# answers a duplicate name with a flash + redirect -- HTTP 200 carrying
# HTML -- and its AJAX success path (roster.py:171) returns no player id,
# so a test that relies on deleting its player by id cannot clean up and
# poisons the next one.
def bench_name():
    return f'Contract Bench {uuid.uuid4().hex[:8]}'

PHONE = {'width': 390, 'height': 844}

LONG_PRESS_MS = 350
ARMED_MS = LONG_PRESS_MS + 120
DRIFT_TOLERANCE_PX = 10


# ---------------------------------------------------------------- boards


@dataclass(frozen=True)
class Board:
    key: str
    label: str
    card: str
    switch: str | None
    state_path: str
    state_field: str
    tap_affordance: str
    open_text: str

    def marker(self, position):
        if self.key == 'on-field':
            return f'{self.card} [data-cb-position="{position}"]'
        return f'{self.card} [data-next-position="{position}"]'

    @property
    def bench_drop(self):
        return (
            f'{self.card} .cb-qd-bench-wrap'
            if self.key == 'on-field'
            else f'{self.card} .cb-next-bench'
        )


ON_FIELD = Board(
    key='on-field',
    label='On the Field',
    card='#cbQuickDefense',
    switch=None,
    state_path='/state',
    state_field='current_alignment',
    tap_affordance='#cbQuickMoveModal [data-cb-destination]',
    open_text='Open',
)

NEXT_INNING = Board(
    key='next',
    label='Next Inning',
    card='#live-board-prep-v3',
    switch='[data-now-next="next"]',
    state_path='/next-inning-prep',
    state_field='confirmed.alignment',
    tap_affordance='#live-board-prep-v3 .cb-next-destination',
    open_text='OPEN',
)

BOARDS = [
    pytest.param(ON_FIELD, id='on-the-field'),
    pytest.param(NEXT_INNING, id='next-inning'),
]


# ---------------------------------------------------------------- setup


def alignment():
    return {
        'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
        '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
        'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
    }


def login(page: Page, url: str):
    page.goto(f'{url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(url)}/?(?:#(?:overview|games))?$'))


def post_json(page: Page, url: str, path: str, data):
    response = page.request.post(f'{url}{path}', data=data)
    assert response.status == 200, f'POST {path} -> {response.status}: {response.text()}'
    payload = response.json()
    assert payload.get('status') == 'success', payload
    return payload


def add_bench_player(page: Page, url: str):
    name = bench_name()
    response = page.request.post(
        f'{url}/add_player',
        form={
            'name': name, 'number': '47', 'position1': 'SS',
            'throws': 'Right', 'bats': 'Right', 'pitcher_role': 'Not a Pitcher',
        },
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert response.status == 200, response.text()[:400]
    payload = response.json()
    assert payload['status'] == 'success', payload
    return name


def create_game(page: Page, url: str):
    response = page.request.post(
        f'{url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=9)).isoformat(),
            'game_start_time': '13:00', 'game_opponent': 'Drag Contract Opponent',
            'game_location': 'Contract Field', 'game_notes': 'Disposable drag contract test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))
    post_json(page, url, '/add_lineup', {
        'title': 'Contract Lineup', 'lineup_data': list(alignment().values()),
        'associated_game_id': game_id,
    })
    post_json(page, url, '/save_rotation', {
        'title': 'Contract Rotation', 'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def cleanup(page: Page, url: str, game_id, player_name):
    if game_id:
        state = page.request.get(f'{url}/api/live-game/{game_id}/state')
        if state.ok and state.json().get('game', {}).get('is_live'):
            page.request.post(
                f'{url}/api/live-game/{game_id}/end-with-pitching',
                data={'defer_pitching': True, 'end_reason': 'manual', 'current_inning_played': True},
            )
        page.request.post(f'{url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
    # The bench player is deliberately left on the disposable roster.
    # delete_player needs an id, and add_player's AJAX response does not
    # return one (roster.py:171); the roster is also locked while a game
    # is live. Unique names are what keep tests independent, so there is
    # nothing here that has to succeed.


def is_vacant(state, position):
    """Both spellings of "nobody is playing here".

    On the Field drops the key entirely; Next Inning keeps the key with
    an empty value. A test that only checks for absence silently passes
    on one board and fails on the other.
    """
    return not (state.get(position) or '').strip()


def assert_armed(page: Page, board, note=''):
    """Wait for the long press to arm, with context if it never does.

    Arming is a browser-side setTimeout, so it is asynchronous with
    respect to the test. Asserting immediately after a fixed hold
    assumes that timer is punctual, and under load it is not -- a busy
    main thread pushes it past the hold and the test fails while the
    product is behaving correctly. Measured at roughly one full-suite
    run in four before this waited.
    """
    try:
        expect(page.locator(GHOST_SELECTOR)).to_have_count(1, timeout=3_000)
        return
    except AssertionError:
        pass
    count = page.locator(GHOST_SELECTOR).count()
    if count != 1:
        state = page.evaluate('() => window.CoachBoardDrag?.debugActive?.() ?? "no-manager"')
        surfaces = page.evaluate('() => window.CoachBoardDrag?.surfaceIds?.() ?? []')
        source_present = page.locator(board.marker('SS')).count()
        raise AssertionError(
            f'{board.label}: long press did not arm{note}; ghosts={count} '
            f'active={state} surfaces={surfaces} source_nodes={source_present}'
        )


def quiesce(page: Page):
    """Stop the boards' background state polls for the rest of the test.

    Both boards rebuild their card wholesale when an update lands. If
    that happens while a finger is held down, the touched node is
    replaced and Chrome fires pointercancel -- which correctly tears the
    drag down, but means a 350ms long press sometimes never arms for a
    reason unrelated to the gesture contract. Measured at roughly one
    run in five across this suite.

    That race is a real product characteristic worth fixing separately
    (On the Field re-renders unconditionally where Next Inning
    signature-checks first). These tests are about the gesture, so they
    hold the board still and let the dedicated cancel-on-rerender tests
    cover the other half.
    """
    page.route('**/api/live-game/*/clock', lambda route: route.abort())


def dismiss_flashes(page: Page):
    page.evaluate(
        "() => document.querySelectorAll('.alert-dismissible, .alert')"
        ".forEach(el => el.remove())"
    )


def board_state(page: Page, url: str, game_id, board: Board):
    """The alignment each board actually writes.

    On the Field owns current_alignment. Next Inning's coach edits land
    in confirmed.alignment -- `planned_alignment` on the same payload is
    the read-only pregame reference plan, which never reflects an edit.
    """
    response = page.request.get(f'{url}/api/live-game/{game_id}{board.state_path}')
    assert response.ok, response.text()[:400]
    node = response.json()
    for part in board.state_field.split('.'):
        node = (node or {}).get(part)
    return node or {}


@pytest.fixture
def live_board(page: Page, coachboard_url: str, browser_name: str, request):
    """A started live game with the requested board on screen."""
    if browser_name != 'chromium':
        pytest.skip('CDP touch injection is Chromium-only.')

    board = request.param if hasattr(request, 'param') else ON_FIELD
    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    player_name = add_bench_player(page, coachboard_url)
    game_id = create_game(page, coachboard_url)
    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        dismiss_flashes(page)
        if board.switch:
            page.locator(board.switch).click()
            expect(page.locator(board.card)).to_be_visible(timeout=10_000)
        expect(page.locator(board.marker('SS'))).to_contain_text('Shortstop Shawn', timeout=10_000)
        yield board, game_id
    finally:
        cleanup(page, coachboard_url, game_id, player_name)


def _boards(fixture):
    return pytest.mark.parametrize('live_board', BOARDS, indirect=True)(fixture)


# ---------------------------------------------------------------- tests


@_boards
def test_swipe_on_player_scrolls_and_does_not_drag(page: Page, coachboard_url, live_board):
    """An ordinary swipe that happens to start on a player must scroll it.

    This is the contract validated on a real device at 153464d, and it
    must stay green through every commit of the shared-controller work.

    The scroll is asserted on #live-game-overlay, never on window.scrollY:
    the app pins body and html to the viewport and does its scrolling
    inside that overlay, so document scroll is always 0 by design. At
    390x844 the overlay's content also happens to fit exactly, leaving
    maxScroll at 0 and nothing on the page able to move -- so the test
    creates the scroll opportunity itself and asserts it exists before
    swiping. Without that step this asserted something physically
    impossible, and only passed where missing stylesheets accidentally
    left the page tall enough to scroll.
    """
    board, game_id = live_board
    before = board_state(page, coachboard_url, game_id, board)

    scroller = make_overlay_scrollable(page)
    assert scroller['ok'], (
        f'{board.label}: no scrollable surface to test against ({scroller})'
    )

    watch_ghosts(page)
    (x, y), = centres(page.locator(board.marker('SS')))
    assert overlay_scroll_top(page) == 0, f'{board.label}: overlay did not start at the top'

    touch = TouchDriver(page)
    touch.down(x, y).move_to(x, y - 140, steps=14, pause_ms=6).up()
    page.wait_for_timeout(300)

    assert overlay_scroll_top(page) > 0, (
        f'{board.label}: a swipe starting on a player did not scroll the overlay '
        f'(maxScroll was {scroller["maxScroll"]})'
    )
    assert ghost_creations(page) == 0, f'{board.label}: a swipe created a drag ghost'
    assert board_state(page, coachboard_url, game_id, board) == before, (
        f'{board.label}: a swipe changed the defense'
    )


@_boards
def test_long_press_then_move_drags_on_touch(page: Page, coachboard_url, live_board):
    """350ms hold arms the drag; the move then carries the player."""
    board, game_id = live_board
    quiesce(page)
    watch_ghosts(page)

    source = page.locator(board.marker('SS'))
    target = page.locator(board.bench_drop)
    (sx, sy), (tx, ty) = centres(source, target)

    touch = TouchDriver(page)
    touch.down(sx, sy).hold(ARMED_MS)
    touch.move_to(tx, ty, steps=12, pause_ms=8)
    assert_armed(page, board)
    touch.up()

    expect(source).to_contain_text(board.open_text, timeout=10_000)
    after = board_state(page, coachboard_url, game_id, board)
    assert is_vacant(after, 'SS'), f'{board.label}: long-press drag did not save; state={after}'
    assert ghost_creations(page) == 1
    assert page.locator(GHOST_SELECTOR).count() == 0, f'{board.label}: ghost leaked after drop'


@_boards
def test_long_press_cancelled_by_drift(page: Page, coachboard_url, live_board):
    """Moving past the drift tolerance during the hold must abandon the arm.

    This asserts the coach-facing outcome -- a swipe that lingers does
    not become a drag -- but it cannot attribute that outcome to the
    manager's drift rule. Measured by mutation: deleting the drift check
    leaves this green, because Chrome claims the gesture as a scroll and
    fires pointercancel a few moves in, which tears the drag down first.
    Both directions behave the same way.

    The drift rule is kept as defence for the engines and situations
    where that rescue is not guaranteed, but no Chromium test proves it
    fires. Treat a green here as "swiping is safe", not as "the drift
    rule works".
    """
    board, game_id = live_board
    before = board_state(page, coachboard_url, game_id, board)
    quiesce(page)
    watch_ghosts(page)

    (x, y), (tx, ty) = centres(
        page.locator(board.marker('SS')), page.locator(board.bench_drop)
    )
    touch = TouchDriver(page)
    touch.down(x, y)
    touch.move_to(x, y - (DRIFT_TOLERANCE_PX * 3), steps=4, pause_ms=8)
    touch.hold(ARMED_MS)
    touch.move_to(tx, ty, steps=10, pause_ms=8)
    touch.up()
    page.wait_for_timeout(300)

    assert ghost_creations(page) == 0, (
        f'{board.label}: drifting past {DRIFT_TOLERANCE_PX}px still armed a drag'
    )
    assert board_state(page, coachboard_url, game_id, board) == before, (
        f'{board.label}: a drifted long press changed the defense'
    )


@_boards
def test_short_tap_still_enters_tap_workflow(page: Page, coachboard_url, live_board):
    """Tap-to-move must survive the addition of long-press drag.

    Asserts the whole workflow, not just the absence of a drag: tap the
    source, get a destination affordance, choose it, and see it save.
    """
    board, game_id = live_board
    watch_ghosts(page)

    (x, y), = centres(page.locator(board.marker('SS')))
    touch = TouchDriver(page)
    touch.down(x, y).hold(90).up()
    page.wait_for_timeout(250)

    assert ghost_creations(page) == 0, f'{board.label}: a short tap created a drag ghost'

    assert page.locator(board.tap_affordance).count() > 0, (
        f'{board.label}: a tap did not open the tap-move workflow'
    )


@_boards
def test_pointercancel_leaves_no_ghost_and_no_save(page: Page, coachboard_url, live_board):
    """An interrupted gesture must tear down fully and leave no residue.

    The follow-up tap matters as much as the ghost assertion: a
    controller that removes its ghost but stays armed looks clean and
    then eats the coach's next gesture.
    """
    board, game_id = live_board
    before = board_state(page, coachboard_url, game_id, board)
    quiesce(page)
    watch_ghosts(page)

    (x, y), (tx, ty) = centres(
        page.locator(board.marker('SS')), page.locator(board.bench_drop)
    )
    touch = TouchDriver(page)
    touch.down(x, y).hold(ARMED_MS)
    touch.move_to(tx, ty, steps=8, pause_ms=8)
    assert_armed(page, board)
    touch.cancel()
    page.wait_for_timeout(250)

    assert page.locator(GHOST_SELECTOR).count() == 0, f'{board.label}: ghost survived pointercancel'
    assert page.locator(DRAG_OVER_SELECTOR).count() == 0, (
        f'{board.label}: drop highlight survived pointercancel'
    )
    assert board_state(page, coachboard_url, game_id, board) == before, (
        f'{board.label}: a cancelled drag still saved'
    )

    # The controller must be usable again, not stuck armed.
    (x2, y2), = centres(page.locator(board.marker('CF')))
    TouchDriver(page).down(x2, y2).hold(90).up()
    page.wait_for_timeout(250)
    assert page.locator(board.tap_affordance).count() > 0, (
        f'{board.label}: tap workflow broken after a cancelled drag -- controller left armed'
    )


@_boards
def test_pinch_does_not_drag(page: Page, coachboard_url, live_board):
    """A second finger means pinch-zoom, never a drag."""
    board, game_id = live_board
    before = board_state(page, coachboard_url, game_id, board)
    watch_ghosts(page)

    (x, y), = centres(page.locator(board.marker('SS')))
    touch = TouchDriver(page)
    touch.down(x, y)
    touch.down(x + 60, y + 60, finger=1)
    touch.hold(ARMED_MS)
    touch.move_to(x - 40, y - 40, finger=0, steps=6, pause_ms=8)
    touch.move_to(x + 110, y + 110, finger=1, steps=6, pause_ms=8)
    touch.up(finger=1)
    touch.up(finger=0)
    page.wait_for_timeout(250)

    assert ghost_creations(page) == 0, f'{board.label}: a two-finger gesture armed a drag'
    assert board_state(page, coachboard_url, game_id, board) == before, (
        f'{board.label}: a pinch changed the defense'
    )


@_boards
def test_mouse_drag_unchanged(page: Page, coachboard_url, live_board):
    """The mouse contract must be byte-for-byte preserved by the refactor.

    Green from the first commit. This is the safety net, not a RED test.
    """
    board, game_id = live_board
    source = page.locator(board.marker('SS'))
    target = page.locator(board.bench_drop)
    (sx, sy), (tx, ty) = centres(source, target)

    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move(tx, ty, steps=12)
    page.mouse.up()

    expect(source).to_contain_text(board.open_text, timeout=10_000)
    after = board_state(page, coachboard_url, game_id, board)
    assert is_vacant(after, 'SS'), f'{board.label}: mouse drag regressed; state={after}'


def test_drag_controller_is_a_singleton_with_two_surfaces(
    page: Page, coachboard_url, browser_name
):
    """One gesture manager, two registered surfaces.

    Two root-scoped instances cannot implement the second-pointer rule:
    the cancelling pointerdown often lands outside the armed root (the
    sibling card, the header, the page background), and a root-scoped
    listener is blind to it.
    """
    if browser_name != 'chromium':
        pytest.skip('CDP touch injection is Chromium-only.')

    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    player_name = add_bench_player(page, coachboard_url)
    game_id = create_game(page, coachboard_url)
    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        page.locator('[data-now-next="next"]').click()
        expect(page.locator('#live-board-prep-v3')).to_be_visible(timeout=10_000)

        assert page.evaluate('() => window.CoachBoardDrag?.version') == 1
        assert page.evaluate('() => typeof window.CoachBoardDrag?.registerSurface') == 'function'
        assert page.evaluate('() => window.CoachBoardDrag?.create') is None, (
            'create() is the two-instance API; the manager must expose registerSurface()'
        )
        surfaces = page.evaluate('() => window.CoachBoardDrag?.surfaceIds?.() ?? []')
        assert sorted(surfaces) == ['next', 'on-field'], (
            f'expected both boards registered on one manager, got {surfaces}'
        )
    finally:
        cleanup(page, coachboard_url, game_id, player_name)


def test_board_click_handlers_survive_the_migration(page: Page, coachboard_url, browser_name):
    """Draft-cancel and Next Inning Undo must not be deleted with the drag listeners.

    Both boards' click listeners do double duty -- suppression plus a
    board feature (unified_field_entry.js:514-530 handles
    [data-cb-cancel-main-draft]; board_prep_v2.js:2354-2389 intercepts
    #liveUndoBtn while Next Inning is showing). Only the suppression
    half moves to the manager. Deleting either wholesale breaks a
    feature no drag test would notice.
    """
    if browser_name != 'chromium':
        pytest.skip('Chromium-only.')

    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    player_name = add_bench_player(page, coachboard_url)
    game_id = create_game(page, coachboard_url)
    try:
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)

        page.locator('[data-now-next="next"]').click()
        expect(page.locator('#live-board-prep-v3')).to_be_visible(timeout=10_000)

        source = page.locator('#live-board-prep-v3 [data-next-position="SS"]')
        target = page.locator('#live-board-prep-v3 .cb-next-bench')
        (sx, sy), (tx, ty) = centres(source, target)
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(tx, ty, steps=12)
        page.mouse.up()
        expect(source).to_contain_text('OPEN', timeout=10_000)

        undo = page.locator('#liveUndoBtn')
        expect(undo).to_be_enabled(timeout=10_000)
        undo.click()
        expect(source).to_contain_text('Shortstop Shawn', timeout=10_000)
    finally:
        cleanup(page, coachboard_url, game_id, player_name)


# ------------------------------------------------- board-semantics pins
#
# The shared manager must not flatten the two boards into one set of
# rules. Source eligibility and drop semantics stay board-owned, in
# resolveSource/onDrop, and the boards genuinely disagree:
#
#   On the Field refuses P and refuses the Open placeholder
#   (live_game_unified_field_entry.js:387-389).
#   Next Inning accepts P on purpose, and movePlayer() gives it
#   asymmetric semantics (live_game_board_prep_v2.js:1730-1740).
#
# These are green at baseline and must stay green. A refactor that
# "helpfully" unified eligibility would pass every gesture test in this
# file and fail here.

_on_field = pytest.mark.parametrize(
    'live_board', [pytest.param(ON_FIELD, id='on-the-field')], indirect=True
)
_next_inning = pytest.mark.parametrize(
    'live_board', [pytest.param(NEXT_INNING, id='next-inning')], indirect=True
)


def mouse_drag(page: Page, source, target):
    (sx, sy), (tx, ty) = centres(source, target)
    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move(tx, ty, steps=12)
    page.mouse.up()


@_on_field
def test_on_the_field_pitcher_is_not_a_drag_source(page: Page, coachboard_url, live_board):
    """Dragging P on the live field must do nothing.

    The live pitcher changes through Change Pitcher, never by dragging
    someone off the mound.
    """
    board, game_id = live_board
    before = board_state(page, coachboard_url, game_id, board)
    watch_ghosts(page)

    mouse_drag(page, page.locator(board.marker('P')), page.locator(board.bench_drop))
    page.wait_for_timeout(600)

    assert ghost_creations(page) == 0, 'On the Field: P armed a drag'
    after = board_state(page, coachboard_url, game_id, board)
    assert after.get('P') == 'Pitcher Pat', f'On the Field: P was dragged off the mound; {after}'
    assert after == before, f'On the Field: dragging P changed the defense; {after}'


@_on_field
def test_on_the_field_open_spot_is_not_a_drag_source(page: Page, coachboard_url, live_board):
    """An empty position is a drop target, never a thing to pick up."""
    board, game_id = live_board

    # Vacate SS so the spot renders as Open (and disabled).
    mouse_drag(page, page.locator(board.marker('SS')), page.locator(board.bench_drop))
    expect(page.locator(board.marker('SS'))).to_contain_text(board.open_text, timeout=10_000)

    vacated = board_state(page, coachboard_url, game_id, board)
    assert is_vacant(vacated, 'SS')
    watch_ghosts(page)

    mouse_drag(page, page.locator(board.marker('SS')), page.locator(board.marker('CF')))
    page.wait_for_timeout(600)

    assert ghost_creations(page) == 0, 'On the Field: an Open spot armed a drag'
    after = board_state(page, coachboard_url, game_id, board)
    assert after.get('CF') == 'Center Casey', f'On the Field: Open was dragged onto CF; {after}'
    assert after == vacated, f'On the Field: dragging Open changed the defense; {after}'


@_next_inning
def test_next_inning_pitcher_is_a_drag_source(page: Page, coachboard_url, live_board):
    """Next Inning deliberately lets the pitcher be moved.

    Field-to-field with a non-P target is a true two-player swap
    (live_game_board_prep_v2.js:1726-1733).
    """
    board, game_id = live_board
    watch_ghosts(page)

    mouse_drag(page, page.locator(board.marker('P')), page.locator(board.marker('SS')))
    expect(page.locator(board.marker('SS'))).to_contain_text('Pitcher Pat', timeout=10_000)

    after = board_state(page, coachboard_url, game_id, board)
    assert ghost_creations(page) == 1, 'Next Inning: P did not arm a drag'
    assert after.get('SS') == 'Pitcher Pat', f'Next Inning: P did not move to SS; {after}'
    assert after.get('P') == 'Shortstop Shawn', (
        f'Next Inning: field-to-field move off P was not a swap; {after}'
    )


@_next_inning
def test_next_inning_move_to_pitcher_benches_the_old_pitcher(
    page: Page, coachboard_url, live_board
):
    """Moving onto P is asymmetric: the old pitcher is benched, not swapped.

    Every other field-to-field move swaps the two players. A move whose
    target is P deliberately does not (live_game_board_prep_v2.js:1730-1740)
    -- the outgoing pitcher goes to the bench and the source position is
    left vacant. A refactor that unified the drop path would turn this
    into a swap and silently put the old pitcher at shortstop.
    """
    board, game_id = live_board

    mouse_drag(page, page.locator(board.marker('SS')), page.locator(board.marker('P')))
    expect(page.locator(board.marker('P'))).to_contain_text('Shortstop Shawn', timeout=10_000)

    after = board_state(page, coachboard_url, game_id, board)
    assert after.get('P') == 'Shortstop Shawn', f'Next Inning: move onto P failed; {after}'
    assert is_vacant(after, 'SS'), (
        f'Next Inning: moving onto P swapped instead of benching; SS={after.get("SS")!r}'
    )
    assert 'Pitcher Pat' not in after.values(), (
        f'Next Inning: the outgoing pitcher stayed on the field; {after}'
    )


@_boards
def test_armed_drag_released_without_moving_does_not_save(
    page: Page, coachboard_url, live_board
):
    """Hold until the drag arms, then let go without going anywhere.

    A coach picks a player up, sees the drag arm, and thinks better of
    it. That must cost nothing: no save, no move, no ghost left behind,
    and the board still usable afterwards.
    """
    board, game_id = live_board
    before = board_state(page, coachboard_url, game_id, board)
    quiesce(page)
    watch_ghosts(page)

    (x, y), = centres(page.locator(board.marker('SS')))
    touch = TouchDriver(page)
    touch.down(x, y).hold(ARMED_MS)
    assert_armed(page, board)
    touch.up()
    page.wait_for_timeout(300)

    assert page.locator(GHOST_SELECTOR).count() == 0, f'{board.label}: ghost survived release'
    assert page.locator(DRAG_OVER_SELECTOR).count() == 0, (
        f'{board.label}: drop highlight survived release'
    )
    assert board_state(page, coachboard_url, game_id, board) == before, (
        f'{board.label}: releasing without moving saved a change'
    )

    # Past the click-suppression window, the board must still respond.
    page.wait_for_timeout(800)
    (x2, y2), = centres(page.locator(board.marker('CF')))
    TouchDriver(page).down(x2, y2).hold(90).up()
    page.wait_for_timeout(300)
    assert page.locator(board.tap_affordance).count() > 0, (
        f'{board.label}: board unusable after an abandoned drag -- left armed'
    )


# ------------------------------------------------ stale-DOM cancellation


@_on_field
def test_live_state_event_mid_drag_cancels_cleanly(page: Page, coachboard_url, live_board):
    """On the Field cancels on any authoritative update, not just undo.

    #cbQuickDefense is rebuilt by live_game_dugout_mode.js whenever live
    state changes, so an update from another coach can replace the node
    under an in-flight drag. Before this change the board only cancelled
    on source == 'undo'; a mouse drag was short enough to hide the gap,
    but a 350ms long press is not.

    Driving the real coachboard:live-state event is what makes this
    deterministic. Removing the node instead races the board's own
    renderer, which legitimately puts it straight back.
    """
    board, game_id = live_board
    before = board_state(page, coachboard_url, game_id, board)
    quiesce(page)
    watch_ghosts(page)

    (x, y), (tx, ty) = centres(
        page.locator(board.marker('SS')), page.locator(board.bench_drop)
    )
    touch = TouchDriver(page)
    touch.down(x, y).hold(ARMED_MS)
    # Confirm the arm before moving at all: a nudge that arrives while
    # the arm timer is still pending counts as drift, and anything past
    # the tolerance correctly cancels it. Moving first made this test
    # fail about one full-suite run in three.
    assert_armed(page, board)
    touch.move_to(x, y + 12, steps=2, pause_ms=8)

    page.evaluate(
        '(id) => document.dispatchEvent(new CustomEvent("coachboard:live-state", '
        '{detail: {game_id: id, source: "socket"}}))',
        game_id,
    )
    page.wait_for_timeout(150)

    assert page.locator(GHOST_SELECTOR).count() == 0, (
        'On the Field: ghost survived an authoritative live-state update; '
        f'active={page.evaluate("() => window.CoachBoardDrag.debugActive()")} '
        f'surfaces={page.evaluate("() => window.CoachBoardDrag.surfaceIds()")}'
    )

    touch.move_to(tx, ty, steps=6, pause_ms=8)
    touch.up()
    page.wait_for_timeout(400)

    assert page.locator(DRAG_OVER_SELECTOR).count() == 0, (
        'On the Field: drop highlight survived a cancelled drag'
    )
    assert board_state(page, coachboard_url, game_id, board) == before, (
        'On the Field: a cancelled drag still saved'
    )


@_next_inning
def test_authoritative_refresh_mid_drag_cancels_cleanly(
    page: Page, coachboard_url, live_board
):
    """Next Inning's own poller must cancel a drag before it hydrates.

    A second coach saving the next-inning defense makes any in-flight
    drag stale. refresh() cancels before hydrate() replaces the card, so
    the gesture cannot land on a board that no longer exists.
    """
    board, game_id = live_board
    # Only the clock poll is stopped here; next-inning-prep must keep
    # polling, since this test's whole point is that its refresh cancels
    # the drag before hydrating.
    page.route('**/api/live-game/*/clock', lambda route: route.abort())

    (x, y), (tx, ty) = centres(
        page.locator(board.marker('SS')), page.locator(board.bench_drop)
    )
    touch = TouchDriver(page)
    touch.down(x, y).hold(ARMED_MS)
    # Confirm the arm before moving at all: a nudge that arrives while
    # the arm timer is still pending counts as drift, and anything past
    # the tolerance correctly cancels it. Moving first made this test
    # fail about one full-suite run in three.
    assert_armed(page, board)
    touch.move_to(x, y + 12, steps=2, pause_ms=8)

    # Another editor rewrites the next-inning defense.
    other = dict(alignment())
    other['CF'] = ''
    response = page.request.post(
        f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep',
        data={'mode': 'custom', 'alignment': other},
    )
    assert response.ok, response.text()[:400]

    # refresh() runs on a 3500ms cadence (live_game_board_prep_v2.js).
    page.wait_for_timeout(5_000)

    assert page.locator(GHOST_SELECTOR).count() == 0, (
        'Next Inning: ghost survived an authoritative refresh'
    )

    touch.move_to(tx, ty, steps=8, pause_ms=8)
    touch.up()
    page.wait_for_timeout(500)

    after = board_state(page, coachboard_url, game_id, board)
    assert after.get('SS') == 'Shortstop Shawn', (
        f'Next Inning: a stale drag saved over the newer defense; {after}'
    )
    assert is_vacant(after, 'CF'), (
        f"Next Inning: the other editor's change was lost; {after}"
    )


# ---------------------------------------------------- manager lifecycle
#
# These drive a synthetic surface rather than either live board. The
# manager's lifecycle is its own contract -- it should hold for any
# surface, and testing it through a board would entangle it with that
# board's rendering.

SYNTH_SETUP = """
() => {
  document.getElementById('cbSynthRoot')?.remove();
  const root = document.createElement('div');
  root.id = 'cbSynthRoot';
  root.style.cssText =
    'position:fixed;left:20px;top:180px;width:300px;height:220px;'
    + 'z-index:99999;background:#fff;border:1px solid #000';
  root.innerHTML =
    '<button type="button" id="cbSynthSrc" style="display:block;height:60px;width:280px">A</button>'
    + '<div id="cbSynthTgt" style="height:120px;width:280px;background:#eee">T</div>';
  document.body.appendChild(root);

  window.__dropped = false;
  window.__clicked = false;
  document.addEventListener('click', () => { window.__clicked = true; });

  window.__synth = window.CoachBoardDrag.registerSurface({
    id: 'synthetic',
    root: () => document.getElementById('cbSynthRoot'),
    canStart: () => true,
    sourceSelector: '#cbSynthSrc',
    targetSelector: '#cbSynthTgt',
    resolveSource: () => ({kind: 'marker', key: 'a', label: 'A'}),
    findSource: () => document.getElementById('cbSynthSrc'),
    resolveTarget: () => ({slot: 'T'}),
    onDrop: () => { window.__dropped = true; },
  });
}
"""


def _open_live_page(page: Page, coachboard_url: str):
    """A started live game with both boards registered."""
    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    player_name = add_bench_player(page, coachboard_url)
    game_id = create_game(page, coachboard_url)
    post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
    page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
    expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
    dismiss_flashes(page)
    return game_id, player_name


def test_click_suppression_follows_a_replaced_root(page: Page, coachboard_url, browser_name):
    """Suppression must survive the surface swapping its root element.

    Holding the root element between event turns looks harmless until a
    board replaces its card: the retained node is detached, contains()
    stops matching, and the click a drop was supposed to swallow gets
    through to the board underneath. Resolving root() at click time is
    what makes this hold.
    """
    if browser_name != 'chromium':
        pytest.skip('Chromium-only.')
    game_id, player_name = _open_live_page(page, coachboard_url)
    try:
        page.evaluate(SYNTH_SETUP)

        page.mouse.move(160, 210)
        page.mouse.down()
        page.mouse.move(160, 300, steps=8)
        page.mouse.up()
        assert page.evaluate('() => window.__dropped') is True, 'synthetic drop did not fire'

        # The board rerenders: same id, brand new node.
        page.evaluate("""() => {
          const old = document.getElementById('cbSynthRoot');
          const fresh = old.cloneNode(true);
          old.replaceWith(fresh);
          window.__clicked = false;
        }""")

        # Well inside the 700ms suppression window.
        page.mouse.click(160, 300)
        assert page.evaluate('() => window.__clicked') is False, (
            'a post-drop click reached the page after the surface replaced its root'
        )
    finally:
        page.evaluate('() => window.__synth?.unregister()')
        cleanup(page, coachboard_url, game_id, player_name)


def test_manager_listeners_unwind_when_the_last_surface_unregisters(
    page: Page, coachboard_url, browser_name
):
    """The document listener set is installed once and removed on the way out.

    It exists to serve registered surfaces; with none left it is pure
    overhead on every pointer event on the page, and a gesture manager
    that cannot be unwound cannot be torn down by whatever embeds it
    next. Re-registering must bring it back.
    """
    if browser_name != 'chromium':
        pytest.skip('Chromium-only.')
    game_id, player_name = _open_live_page(page, coachboard_url)
    try:
        expect(page.locator('#live-board-prep-v3')).to_be_attached(timeout=10_000)
        assert page.evaluate('() => window.CoachBoardDrag.listenersInstalled()') is True
        assert sorted(page.evaluate('() => window.CoachBoardDrag.surfaceIds()')) == [
            'next', 'on-field'
        ]

        # Unregistering one surface while others remain must NOT unwind.
        page.evaluate(SYNTH_SETUP)
        assert sorted(page.evaluate('() => window.CoachBoardDrag.surfaceIds()')) == [
            'next', 'on-field', 'synthetic'
        ]
        page.evaluate('() => window.__synth.unregister()')
        assert page.evaluate('() => window.CoachBoardDrag.listenersInstalled()') is True, (
            'listeners were removed while both boards were still registered'
        )

        # Dropping the last surface unwinds.
        page.evaluate('() => window.CoachBoardDrag.unregisterAll()')
        assert page.evaluate('() => window.CoachBoardDrag.surfaceIds()') == []
        assert page.evaluate('() => window.CoachBoardDrag.listenersInstalled()') is False, (
            'the listener set survived the last surface unregistering'
        )

        # With nothing registered, a gesture on a real marker is inert.
        # The synthetic panel is position:fixed over the board, so it has
        # to go before touching anything underneath it.
        page.evaluate("() => document.getElementById('cbSynthRoot')?.remove()")
        (x, y), = centres(page.locator('#cbQuickDefense [data-cb-position="SS"]'))
        touch = TouchDriver(page)
        touch.down(x, y).hold(ARMED_MS)
        assert page.locator(GHOST_SELECTOR).count() == 0, (
            'a drag armed with no surfaces registered'
        )
        touch.up()

        # Registering again brings the set back.
        page.evaluate(SYNTH_SETUP)
        assert page.evaluate('() => window.CoachBoardDrag.listenersInstalled()') is True
        assert page.evaluate('() => window.CoachBoardDrag.surfaceIds()') == ['synthetic']
        page.evaluate('() => window.__synth.unregister()')
        assert page.evaluate('() => window.CoachBoardDrag.listenersInstalled()') is False
    finally:
        cleanup(page, coachboard_url, game_id, player_name)


def test_stale_source_cancels_on_the_next_move(page: Page, coachboard_url, browser_name):
    """findSource(), isolated on a surface nothing else re-renders.

    The manager holds no element across event turns, so the only way it
    can notice its source has gone is to ask the surface on each move.
    Driving this through a live board does not work: both boards rebuild
    their card on their own schedule and put the marker straight back,
    so the test races the renderer instead of testing the check. A
    synthetic surface has no renderer.

    Mouse, not touch, and for the same reason the drift test cannot
    isolate its rule: under touch, Chrome fires pointercancel when the
    touched node is removed and tears the drag down before findSource()
    is consulted.
    """
    if browser_name != 'chromium':
        pytest.skip('Chromium-only.')
    game_id, player_name = _open_live_page(page, coachboard_url)
    try:
        page.evaluate(SYNTH_SETUP)

        page.mouse.move(160, 210)
        page.mouse.down()
        page.mouse.move(160, 230, steps=4)
        assert page.locator(GHOST_SELECTOR).count() == 1, 'synthetic drag never armed'

        page.evaluate("() => document.getElementById('cbSynthSrc').remove()")
        page.mouse.move(160, 300, steps=4)

        assert page.locator(GHOST_SELECTOR).count() == 0, (
            'ghost survived the source being removed'
        )
        page.mouse.up()
        assert page.evaluate('() => window.__dropped') is False, (
            'a drag whose source had vanished still dropped'
        )
    finally:
        page.evaluate('() => window.__synth?.unregister()')
        cleanup(page, coachboard_url, game_id, player_name)


def test_armed_gesture_state_retains_no_borrowed_element(
    page: Page, coachboard_url, browser_name
):
    """Gesture state must hold no element borrowed from a surface.

    Retaining one is how a manager ends up pinning a detached node and
    silently acting on stale DOM -- it is what suppressRoot did, and
    what captureNode did after it. The manager asks the surface for a
    live element and drops it inside the same event turn, so an armed
    drag should be carrying nothing but plain data.

    The drag ghost is exempt and excluded by the accessor: the manager
    creates it, owns it, and is the only code that removes it, so it
    cannot go stale under a rerender.
    """
    if browser_name != 'chromium':
        pytest.skip('Chromium-only.')
    game_id, player_name = _open_live_page(page, coachboard_url)
    try:
        page.evaluate(SYNTH_SETUP)

        page.mouse.move(160, 210)
        page.mouse.down()
        page.mouse.move(160, 240, steps=4)

        state = page.evaluate('() => window.CoachBoardDrag.debugActive()')
        assert state and state['armed'] is True, f'synthetic drag never armed: {state}'
        assert state['borrowedElements'] == [], (
            f'armed gesture state retains borrowed element(s): {state["borrowedElements"]}'
        )

        # And still nothing after the drag has moved a few times, which
        # is where a lazily-cached element would show up.
        page.mouse.move(160, 280, steps=4)
        page.mouse.move(160, 300, steps=4)
        state = page.evaluate('() => window.CoachBoardDrag.debugActive()')
        assert state['borrowedElements'] == [], (
            f'gesture state picked up borrowed element(s) mid-drag: {state["borrowedElements"]}'
        )
        page.mouse.up()
    finally:
        page.evaluate('() => window.__synth?.unregister()')
        cleanup(page, coachboard_url, game_id, player_name)
