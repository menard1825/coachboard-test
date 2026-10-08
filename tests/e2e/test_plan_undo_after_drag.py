"""Plan Undo works the instant a coach drops a player in the planner.

A drag used to arm click suppression on the whole board for 700 ms. The
full-screen planner holds its own bar -- Plan Undo and Live Field -- inside
that board, so a coach who dropped a player and tapped Undo straight away
lost the tap. Suppression now swallows only the click the drop itself makes;
a new tap is a new gesture.

On a phone and an iPad (touch: long press, drag, release, tap) and on a
desktop (mouse), with no pause: one Undo is sent, the plan on screen and on
the server is back to before the drag -- not further back -- and the live
field is untouched.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect  # noqa: E402

from cdp_touch import TouchDriver  # noqa: E402
from test_live_game_shared_drag_contract import (  # noqa: E402
    ARMED_MS,
    NEXT_INNING,
    board_state,
    centres,
    cleanup,
    dismiss_flashes,
    ghost_creations,
    login,
    quiesce,
    start_live_game,
    watch_ghosts,
)


BOARD = NEXT_INNING
UNDO = '#live-board-prep-v3 [data-next-undo-local]'
DEVICES = [
    pytest.param(('touch', {'width': 390, 'height': 844}), id='phone'),
    pytest.param(('touch', {'width': 1024, 'height': 768}), id='ipad-landscape'),
    pytest.param(('touch', {'width': 768, 'height': 1024}), id='ipad-portrait'),
    pytest.param(('mouse', {'width': 1440, 'height': 900}), id='desktop'),
]


def record_writes(page: Page):
    writes = []

    def seen(request):
        if request.method == 'POST' and ('next-inning-prep' in request.url or 'defense-edit' in request.url):
            body = request.post_data_json or {}
            writes.append(('undo' if body.get('mode') == 'undo' else request.url.rsplit('/', 1)[-1]))

    page.on('request', seen)
    return writes


def live(page: Page, url: str, game_id):
    return page.request.get(f'{url}/api/live-game/{game_id}/state').json()


def wait_for_plan(page: Page, url: str, game_id, expected):
    for _ in range(50):
        if board_state(page, url, game_id, BOARD) == expected:
            return
        page.wait_for_timeout(200)
    assert board_state(page, url, game_id, BOARD) == expected


@pytest.mark.parametrize('surface', DEVICES)
def test_plan_undo_tapped_right_after_a_drag_takes_the_drag_back(page: Page, coachboard_url, browser_name, surface):
    if browser_name != 'chromium':
        pytest.skip('CDP touch injection is Chromium-only.')
    pointer, viewport = surface
    page.set_viewport_size(viewport)
    login(page, coachboard_url)
    game_id, player_name = start_live_game(page, coachboard_url)
    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        dismiss_flashes(page)
        page.locator(BOARD.switch).click()
        planner = page.locator(BOARD.card)
        expect(planner).to_be_visible(timeout=10_000)
        live_before = live(page, coachboard_url, game_id)

        # An earlier plan edit, saved: a second Undo would take it back too.
        page.locator(BOARD.marker('LF')).click()
        planner.locator('[data-next-bench-selected]').click()
        expect(page.locator(BOARD.marker('LF'))).to_contain_text(BOARD.open_text, timeout=5_000)
        before_drag = board_state(page, coachboard_url, game_id, BOARD)
        wait_for_plan(page, coachboard_url, game_id, before_drag)
        assert not before_drag.get('LF'), before_drag
        quiesce(page)

        writes = record_writes(page)
        watch_ghosts(page)
        source = page.locator(BOARD.marker('SS'))
        (sx, sy), (tx, ty) = centres(source, page.locator(BOARD.bench_drop))
        (ux, uy), = centres(page.locator(UNDO))

        # Drag Shortstop Shawn to the bench, then tap Plan Undo at once.
        if pointer == 'touch':
            touch = TouchDriver(page)
            touch.down(sx, sy).hold(ARMED_MS)
            touch.move_to(tx, ty, steps=12, pause_ms=8)
            touch.up()
            touch.down(ux, uy).up()
        else:
            page.mouse.move(sx, sy)
            page.mouse.down()
            page.mouse.move(tx, ty, steps=12)
            page.mouse.up()
            page.mouse.click(ux, uy)

        # The drag is taken back, on screen and on the server.
        expect(source).to_contain_text('Shortstop Shawn', timeout=10_000)
        wait_for_plan(page, coachboard_url, game_id, before_drag)
        page.wait_for_timeout(1_000)                      # anything late would land by now
        assert writes.count('undo') == 1, writes        # exactly one Undo
        assert board_state(page, coachboard_url, game_id, BOARD) == before_drag   # not further back
        expect(page.locator(BOARD.marker('LF'))).to_contain_text(BOARD.open_text)

        # Planning only: the live field and its history are untouched.
        assert 'defense-edit' not in writes, writes
        live_after = live(page, coachboard_url, game_id)
        assert live_after['current_alignment'] == live_before['current_alignment']
        assert len(live_after.get('rotation_events') or []) == len(live_before.get('rotation_events') or [])
        assert ghost_creations(page) == 1
        expect(page.locator('.cb-drag-ghost')).to_have_count(0)
    finally:
        cleanup(page, coachboard_url, game_id, player_name)
