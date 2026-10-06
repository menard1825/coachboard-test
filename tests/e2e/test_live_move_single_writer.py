"""Tap and drag make a live defensive move through one writer.

On the Field has one writer for a normal live defensive move:
CBQuickFieldMoves.commit (commitMove in live_game_dugout_mode.js). Tapping
(the Move and Fill sheets) and dragging both commit there; drag only works
out who the coach picked up and where they let go. So every case below is
run with both gestures and must give the same field -- the same request,
even -- and the same refusals, failure message and Retry.

A drag is decided on the field the coach picked the player up from: the
move context is captured when the gesture starts. If another device
changes the field before the drop, the drop is refused, never applied to
the newer field.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect  # noqa: E402

from test_live_change_pitcher_decision import (  # noqa: E402,F401 (live_field is a fixture)
    BASE,
    RELIEVER,
    edit_field,
    filled,
    live_field,
    live_state,
    sequence,
    wait_for_field,
)
from cdp_touch import (  # noqa: E402
    GHOST_SELECTOR,
    TouchDriver,
    centres,
    ghost_creations,
    make_overlay_scrollable,
    overlay_scroll_top,
    watch_ghosts,
)


GESTURES = ['tap', 'drag']
CARD = '#cbQuickDefense'
SHEET = '#cbQuickMoveModal'
BADGE = f'{CARD} .cb-save-state'
RETRY = f'{CARD} [data-cb-retry-move]'
PICKER = '#live-pitcher-picker-v2'
STALE = 'Defense changed on another device'
OPEN_SS = {pos: name for pos, name in BASE.items() if pos != 'SS'}
ELSEWHERE = dict(BASE, C=BASE['1B'], **{'1B': BASE['C']})   # another device swaps C and 1B

# Every drag's commit is recorded on its way to the one writer, with the
# context the drag carried.
SPY = """
(() => {
  window.__cbCommits = [];
  let api;
  Object.defineProperty(window, 'CBQuickFieldMoves', {
    configurable: true,
    get: () => api,
    set(real) {
      api = Object.freeze({...real, commit(name, destination, context) {
        window.__cbCommits.push({name, destination, context: JSON.parse(JSON.stringify(context ?? null))});
        return real.commit(name, destination, context);
      }});
    },
  });
})();
"""


# ------------------------------------------------------------- helpers


def marker(page: Page, name):
    return page.locator(f'{CARD} [data-cb-move-player="{name}"]')


def spot(page: Page, position):
    if position == 'BENCH':
        return page.locator(f'{CARD} .cb-qd-bench-wrap')
    return page.locator(f'{CARD} [data-cb-position="{position}"]')


def tap(page: Page, name, destination):
    marker(page, name).click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=10_000)
    if destination == 'BENCH':
        sheet.locator('[data-cb-bench-current]').click()
    else:
        sheet.locator(f'[data-cb-destination="{destination}"]').click()


def press(page: Page, name):
    """Pick a player up with the mouse (past the drag threshold)."""
    box = marker(page, name).bounding_box()
    assert box, name
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 14, y + 14, steps=4)


def release_on(page: Page, destination):
    box = spot(page, destination).bounding_box()
    assert box, destination
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2, steps=10)
    page.mouse.up()


def drag(page: Page, name, destination):
    press(page, name)
    release_on(page, destination)


# The drag controller swallows clicks on the board for 700 ms after a drop
# (the click a drop itself produces). A coach's next tap comes later.
AFTER_DROP_MS = 800


def move(page: Page, gesture, name, destination):
    (tap if gesture == 'tap' else drag)(page, name, destination)


def writes(page: Page):
    posts = []
    page.on(
        'request',
        lambda request: posts.append(request.post_data_json)
        if request.method == 'POST' and request.url.endswith('/defense-edit') else None,
    )
    return posts


def hold_writes(page: Page):
    """Hold every /defense-edit POST until released."""
    held = []
    page.route(re.compile(r'.*/defense-edit$'), lambda route: held.append(route))

    def release():
        for route in held:
            route.continue_()
        page.unroute(re.compile(r'.*/defense-edit$'))
    return held, release


def open_field(page: Page, live_field, field=BASE, spy=True):
    if spy:
        page.add_init_script(SPY)
    game_id = live_field()
    if field != BASE:
        edit_field(page, page.cb_url, game_id, field)
        page.reload(wait_until='domcontentloaded')
        expect(spot(page, 'SS')).to_contain_text('Open', timeout=15_000)
    expect(page.locator(BADGE)).to_contain_text('Saved', timeout=10_000)
    return game_id


@pytest.fixture
def field(page: Page, coachboard_url, live_field):
    page.cb_url = coachboard_url

    def _open(alignment=BASE, spy=True):
        game_id = open_field(page, live_field, alignment, spy)
        state = live_state(page, coachboard_url, game_id)
        return game_id, sequence(state)
    return _open


def commits(page: Page):
    return page.evaluate('() => window.__cbCommits')


def assert_one_writer(page: Page, gesture, name, destination, before):
    """A drag reached the one writer, carrying the field it started from."""
    recorded = commits(page)
    if gesture == 'tap':
        assert recorded == []          # the sheets call the writer directly
        return
    assert [(c['name'], c['destination']) for c in recorded] == [(name, destination)]
    assert filled(recorded[0]['context']['alignment']) == before


# --------------------------------------------------- the baseball rules


CASES = [
    # (start field, who, where, the field after)
    pytest.param(OPEN_SS, 'Second Sam', 'SS',
                 {**{p: n for p, n in OPEN_SS.items() if p != '2B'}, 'SS': 'Second Sam'},
                 id='field-to-open'),
    pytest.param(BASE, 'Left Lee', 'RF',
                 dict(BASE, LF=BASE['RF'], RF='Left Lee'), id='field-to-occupied-swap'),
    pytest.param(BASE, 'Shortstop Shawn', 'BENCH',
                 OPEN_SS, id='field-to-bench'),
    pytest.param(OPEN_SS, RELIEVER, 'SS',
                 dict(OPEN_SS, SS=RELIEVER), id='bench-to-open'),
    pytest.param(BASE, RELIEVER, 'LF',
                 dict(BASE, LF=RELIEVER), id='bench-to-occupied'),
]


@pytest.mark.parametrize('gesture', GESTURES)
@pytest.mark.parametrize('start, name, destination, after', CASES)
def test_both_gestures_make_the_same_move(
    page: Page, coachboard_url, field, gesture, start, name, destination, after
):
    game_id, base_sequence = field(start)
    posts = writes(page)

    move(page, gesture, name, destination)

    wait_for_field(page, coachboard_url, game_id, after)
    expect(page.locator(BADGE)).to_contain_text('Saved ✓', timeout=10_000)
    # One save, no question, no confirmation -- the same request either way.
    expect(page.locator(SHEET)).not_to_be_visible()
    assert len(posts) == 1
    assert filled(posts[0]['alignment']) == after
    assert posts[0]['base_sequence'] == base_sequence
    assert_one_writer(page, gesture, name, destination, start)
    # The board shows the saved field.
    for position, player in after.items():
        expect(spot(page, position)).to_contain_text(player)


@pytest.mark.parametrize('gesture', GESTURES)
def test_pitcher_moves_go_to_change_pitcher(page: Page, coachboard_url, field, gesture):
    game_id, _ = field(OPEN_SS)
    posts = writes(page)

    if gesture == 'tap':
        # The pitcher's own marker, and choosing the pitcher to fill a spot.
        spot(page, 'P').click()
        expect(page.locator(PICKER)).to_be_visible(timeout=10_000)
        page.locator(f'{PICKER} .btn-close').click()
        expect(page.locator(PICKER)).not_to_be_visible(timeout=10_000)
        spot(page, 'SS').click()
        sheet = page.locator(SHEET)
        expect(sheet).to_be_visible(timeout=10_000)
        sheet.locator('[data-cb-fill-from="P"]').click()
    else:
        # The pitcher cannot be picked up; dropping a fielder on P asks
        # Change Pitcher instead of moving anyone.
        drag(page, 'Left Lee', 'P')

    expect(page.locator(PICKER)).to_be_visible(timeout=10_000)
    page.wait_for_timeout(300)
    assert posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == OPEN_SS


# ---------------------------------------- the field the coach acted on


def test_a_stale_tap_is_refused(page: Page, coachboard_url, field):
    game_id, _ = field()
    posts = writes(page)
    marker(page, 'Left Lee').click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=10_000)

    edit_field(page, coachboard_url, game_id, ELSEWHERE)        # another device
    try:
        expect(sheet).not_to_be_visible(timeout=5_000)          # the sheet is withdrawn ...
    except AssertionError:
        sheet.locator('[data-cb-destination="RF"]').click()     # ... or the save is refused

    expect(page.locator(BADGE)).to_contain_text(STALE, timeout=10_000)
    expect(page.locator(RETRY)).to_have_count(0)
    assert posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == ELSEWHERE
    expect(spot(page, 'C')).to_contain_text(BASE['1B'])


def test_a_stale_drag_is_refused(page: Page, coachboard_url, field):
    """Picked up on one field, dropped after another device changed it."""
    game_id, _ = field()
    posts = writes(page)

    press(page, 'Shortstop Shawn')                             # A picks SS up ...
    edit_field(page, coachboard_url, game_id, ELSEWHERE)       # ... B moves others ...
    expect(spot(page, 'C')).to_contain_text(BASE['1B'], timeout=10_000)
    release_on(page, '2B')                                     # ... A drops on 2B

    expect(page.locator(BADGE)).to_contain_text(STALE, timeout=10_000)
    expect(page.locator(RETRY)).to_have_count(0)
    assert posts == []
    # Not reinterpreted as a swap on B's field.
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == ELSEWHERE
    expect(spot(page, 'SS')).to_contain_text('Shortstop Shawn')
    expect(spot(page, '2B')).to_contain_text('Second Sam')
    recorded = commits(page)
    assert len(recorded) == 1 and filled(recorded[0]['context']['alignment']) == BASE


@pytest.mark.parametrize('gesture', GESTURES)
def test_a_save_the_server_refuses_reads_the_same(page: Page, coachboard_url, field, gesture):
    """The field changed where this screen could not see it yet: the
    server refuses, the screen reloads the field and says so."""
    game_id, _ = field()
    page.route(re.compile(r'.*/defense-edit$'), lambda route: route.fulfill(
        status=409, content_type='application/json',
        json={'status': 'error', 'code': 'stale_live_state', 'message': 'stale'},
    ))

    move(page, gesture, 'Shortstop Shawn', 'BENCH')

    expect(page.locator(BADGE)).to_contain_text(STALE, timeout=10_000)
    expect(page.locator(RETRY)).to_have_count(0)
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE


# ------------------------------------------------------ failure, Retry
#
# Shortstop to the Bench: before the one writer, a drag made this move
# through its own save, which reported a failure with a blocking alert().


@pytest.mark.parametrize('gesture', GESTURES)
def test_a_failed_save_offers_retry_and_retry_saves(page: Page, coachboard_url, field, gesture):
    game_id, base_sequence = field()
    dialogs = []
    page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.route(re.compile(r'.*/defense-edit$'), lambda route: route.abort('internetdisconnected'))

    move(page, gesture, 'Shortstop Shawn', 'BENCH')

    expect(page.locator(BADGE)).to_have_text('Not saved — Retry', timeout=10_000)
    assert dialogs == []                                       # no blocking alert
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE

    page.unroute(re.compile(r'.*/defense-edit$'))
    posts = writes(page)
    page.wait_for_timeout(AFTER_DROP_MS)
    page.locator(RETRY).click()

    wait_for_field(page, coachboard_url, game_id, OPEN_SS)
    expect(page.locator(BADGE)).to_contain_text('Saved ✓', timeout=10_000)
    assert len(posts) == 1 and posts[0]['base_sequence'] == base_sequence
    assert dialogs == []


@pytest.mark.parametrize('gesture', GESTURES)
def test_retry_is_refused_once_the_field_has_changed(page: Page, coachboard_url, field, gesture):
    game_id, _ = field()
    page.route(re.compile(r'.*/defense-edit$'), lambda route: route.abort('internetdisconnected'))
    move(page, gesture, 'Shortstop Shawn', 'BENCH')
    expect(page.locator(BADGE)).to_have_text('Not saved — Retry', timeout=10_000)
    page.unroute(re.compile(r'.*/defense-edit$'))

    edit_field(page, coachboard_url, game_id, ELSEWHERE)       # another device
    expect(spot(page, 'C')).to_contain_text(BASE['1B'], timeout=10_000)
    posts = writes(page)
    page.wait_for_timeout(AFTER_DROP_MS)
    page.locator(RETRY).click()

    expect(page.locator(BADGE)).to_contain_text(STALE, timeout=10_000)
    page.wait_for_timeout(300)
    assert posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == ELSEWHERE


# ------------------------------------------------- one move at a time


def test_a_tap_while_a_drag_is_saving_waits_its_turn(page: Page, coachboard_url, field):
    game_id, _ = field()
    posts = writes(page)
    held, release = hold_writes(page)

    drag(page, 'Left Lee', 'RF')
    expect(page.locator(BADGE)).to_contain_text('Saving', timeout=10_000)
    assert len(held) == 1

    page.wait_for_timeout(AFTER_DROP_MS)
    marker(page, 'Catcher Cole').click()                       # a field player ...
    marker(page, RELIEVER).click()                             # ... and the bench
    page.wait_for_timeout(400)
    expect(page.locator(SHEET)).not_to_be_visible()

    release()
    expected = dict(BASE, LF=BASE['RF'], RF='Left Lee')
    wait_for_field(page, coachboard_url, game_id, expected)
    expect(page.locator(BADGE)).to_contain_text('Saved ✓', timeout=10_000)
    assert len(posts) == 1

    tap(page, 'Catcher Cole', 'BENCH')                         # and then it works
    wait_for_field(page, coachboard_url, game_id, {p: n for p, n in expected.items() if p != 'C'})


def test_a_drag_while_a_tap_is_saving_waits_its_turn(page: Page, coachboard_url, field):
    game_id, _ = field()
    posts = writes(page)
    held, release = hold_writes(page)

    tap(page, 'Left Lee', 'RF')
    expect(page.locator(SHEET)).not_to_be_visible(timeout=10_000)
    page.wait_for_timeout(200)
    assert len(held) == 1

    watch_ghosts(page)
    drag(page, 'Second Sam', 'SS')
    page.wait_for_timeout(400)
    assert ghost_creations(page) == 0
    expect(page.locator(SHEET)).not_to_be_visible()

    release()
    expected = dict(BASE, LF=BASE['RF'], RF='Left Lee')
    wait_for_field(page, coachboard_url, game_id, expected)
    assert len(posts) == 1
    page.wait_for_timeout(300)
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == expected


def test_two_quick_drags_save_one_move_at_a_time(page: Page, coachboard_url, field):
    game_id, _ = field()
    posts = writes(page)
    held, release = hold_writes(page)

    drag(page, 'Left Lee', 'RF')
    drag(page, 'Second Sam', 'SS')                             # while the first is saving
    page.wait_for_timeout(300)
    assert len(held) == 1
    release()
    first = dict(BASE, LF=BASE['RF'], RF='Left Lee')
    wait_for_field(page, coachboard_url, game_id, first)
    expect(page.locator(BADGE)).to_contain_text('Saved ✓', timeout=10_000)

    page.wait_for_timeout(AFTER_DROP_MS)
    drag(page, 'Second Sam', 'SS')                             # the next one, on the new field
    wait_for_field(page, coachboard_url, game_id, dict(first, SS='Second Sam', **{'2B': 'Shortstop Shawn'}))
    assert len(posts) == 2
    assert posts[1]['base_sequence'] > posts[0]['base_sequence']


@pytest.mark.parametrize('button', ['position', 'bench'])
def test_a_double_tap_saves_once(page: Page, coachboard_url, field, button):
    game_id, _ = field()
    posts = writes(page)
    marker(page, 'Left Lee').click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=10_000)

    choice = sheet.locator('[data-cb-destination="RF"]' if button == 'position' else '[data-cb-bench-current]')
    choice.dblclick()

    expected = (dict(BASE, LF=BASE['RF'], RF='Left Lee') if button == 'position'
                else {p: n for p, n in BASE.items() if p != 'LF'})
    wait_for_field(page, coachboard_url, game_id, expected)
    page.wait_for_timeout(500)
    assert len(posts) == 1


# ------------------------------------------------------------- touch


def test_a_long_press_touch_drag_commits_through_the_writer(page: Page, coachboard_url, field, browser_name):
    if browser_name != 'chromium':
        pytest.skip('CDP touch injection is Chromium-only.')
    game_id, _ = field(OPEN_SS)
    page.route('**/api/live-game/*/clock', lambda route: route.abort())   # hold the board still
    watch_ghosts(page)

    (sx, sy), (tx, ty) = centres(marker(page, RELIEVER), spot(page, 'SS'))
    touch = TouchDriver(page)
    touch.down(sx, sy).hold(470)
    touch.move_to(tx, ty, steps=12, pause_ms=8)
    expect(page.locator(GHOST_SELECTOR)).to_have_count(1, timeout=3_000)
    touch.up()

    wait_for_field(page, coachboard_url, game_id, dict(OPEN_SS, SS=RELIEVER))
    assert [(c['name'], c['destination']) for c in commits(page)] == [(RELIEVER, 'SS')]
    assert page.locator(GHOST_SELECTOR).count() == 0


def test_a_swipe_starting_on_a_player_still_scrolls(page: Page, coachboard_url, field, browser_name):
    if browser_name != 'chromium':
        pytest.skip('CDP touch injection is Chromium-only.')
    game_id, _ = field()
    posts = writes(page)
    scroller = make_overlay_scrollable(page)
    assert scroller['ok'], scroller
    watch_ghosts(page)
    (x, y), = centres(spot(page, 'SS'))
    assert overlay_scroll_top(page) == 0

    TouchDriver(page).down(x, y).move_to(x, y - 140, steps=14, pause_ms=6).up()
    page.wait_for_timeout(300)

    assert overlay_scroll_top(page) > 0
    assert ghost_creations(page) == 0
    assert commits(page) == [] and posts == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == BASE
