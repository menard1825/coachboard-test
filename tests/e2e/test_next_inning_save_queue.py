"""Next Inning on a slow or dropped connection, pitcher swaps, and End Inning
with an incomplete Next Inning defense.

Next Inning saves in the background: a tap changes the board at once, the
selection clears at once, and the saves queue behind it one at a time. These
tests hold the network at ~1 s per request (CDP latency), drop it entirely
(offline), and have "another coach" change the defense underneath, then check
what the coach sees and what the server ends up holding.
"""

import os
import re
import time
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect

from test_next_inning_save_race import (
    cleanup_game,
    login,
    post_json,
    starting_alignment,
)


PHONE = {'width': 390, 'height': 844}
CARD = '#live-board-prep-v3'
PREP_URL = re.compile(r'/api/live-game/\d+/next-inning-prep$')

# Every tap must show on the board well inside one slow round trip.
IMMEDIATE_MS = 400


def create_live_game(page: Page, url: str):
    response = page.request.post(
        f'{url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=9)).isoformat(),
            'game_start_time': '10:00',
            'game_opponent': 'Next Inning Queue Opponent',
            'game_location': 'Queue Field',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    game_id = int(
        re.search(r'/game/(\d+)', response.headers['location']).group(1)
    )
    post_json(page, url, '/save_rotation', {
        'title': 'Next Inning Queue Rotation',
        'innings': {'1': starting_alignment(), '2': starting_alignment()},
        'associated_game_id': game_id,
    })
    post_json(page, url, f'/api/live-game/{game_id}/start', {})
    return game_id


@pytest.fixture
def next_board(page: Page, coachboard_url: str, browser_name: str):
    if browser_name != 'chromium':
        pytest.skip('CDP network emulation is Chromium-only.')

    page.set_viewport_size(PHONE)
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url)
    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )
        expect(page.locator('#cb-now-next-switch')).to_be_visible(
            timeout=15_000
        )
        page.locator('#cb-now-next-switch [data-now-next="next"]').click()
        board = page.locator(CARD)
        expect(spot(board, 'SS')).to_contain_text(
            'Shortstop Shawn', timeout=10_000
        )
        yield board, game_id
    finally:
        page.context.set_offline(False)
        cleanup_game(page, coachboard_url, game_id)


def spot(board, position):
    return board.locator(f'[data-next-position="{position}"]')


def swap(board, source, target):
    spot(board, source).click()
    spot(board, target).click()


def slow_network(page: Page, latency_ms=1000):
    cdp = page.context.new_cdp_session(page)
    cdp.send('Network.enable')
    cdp.send('Network.emulateNetworkConditions', {
        'offline': False,
        'latency': latency_ms,
        'downloadThroughput': -1,
        'uploadThroughput': -1,
    })
    return cdp


def normal_network(cdp):
    cdp.send('Network.emulateNetworkConditions', {
        'offline': False,
        'latency': 0,
        'downloadThroughput': -1,
        'uploadThroughput': -1,
    })


def server_next(page: Page, url: str, game_id: int):
    response = page.request.get(
        f'{url}/api/live-game/{game_id}/next-inning-prep'
    )
    assert response.ok, response.text()[:300]
    return filled(response.json()['confirmed']['alignment'])


def live_state(page: Page, url: str, game_id: int):
    response = page.request.get(f'{url}/api/live-game/{game_id}/state')
    assert response.ok, response.text()[:300]
    return response.json()


def filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def board_alignment(page: Page):
    return filled(page.evaluate('() => window.CBNextDefense.getAlignment()'))


def wait_for_server(page, url, game_id, expected, timeout_s=15):
    deadline = timeout_s * 1000
    waited = 0
    while waited < deadline:
        if server_next(page, url, game_id) == expected:
            return
        page.wait_for_timeout(200)
        waited += 200
    assert server_next(page, url, game_id) == expected


def record_prep_posts(page: Page):
    """Every Next Inning save: the alignment it sent, and when it was
    in flight, so overlapping or out-of-order writes are visible."""
    posts = []

    def on_request(request):
        if request.method == 'POST' and PREP_URL.search(request.url):
            posts.append({
                'request': request,
                'body': request.post_data_json,
                'start': time.monotonic(),
                'end': None,
            })

    def on_done(request):
        for post in posts:
            if post['request'] is request:
                post['end'] = time.monotonic()

    page.on('request', on_request)
    page.on('requestfinished', on_done)
    page.on('requestfailed', on_done)
    return posts


def expected_after(*swaps):
    alignment = dict(starting_alignment())
    for source, target in swaps:
        alignment[source], alignment[target] = (
            alignment[target], alignment[source]
        )
    return alignment


# ------------------------------------------------------------ slow saves


def test_rapid_swaps_on_a_slow_connection_are_all_kept(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    posts = record_prep_posts(page)
    slow_network(page)

    moves = [('SS', 'P'), ('LF', 'CF'), ('1B', '2B')]
    done = []
    for source, target in moves:
        swap(board, source, target)
        done.append((source, target))
        want = expected_after(*done)
        # The tap took: the board shows it and the selection is gone,
        # long before the ~1 s save could have answered.
        expect(spot(board, source)).to_contain_text(
            want[source], timeout=IMMEDIATE_MS
        )
        expect(spot(board, target)).to_contain_text(
            want[target], timeout=IMMEDIATE_MS
        )
        expect(board.locator('[data-next-cancel]')).to_have_count(
            0, timeout=IMMEDIATE_MS
        )

    final = expected_after(*moves)
    assert board_alignment(page) == final

    expect(board.locator('.cb-next-save')).to_have_class(
        re.compile(r'\bsaving\b')
    )
    expect(board.locator('.cb-next-save')).to_have_class(
        re.compile(r'\bsaved\b'), timeout=15_000
    )
    assert server_next(page, coachboard_url, game_id) == final

    # One save at a time, never overlapping, and the last one written is
    # the final board -- so no older alignment can land after it.
    finished = [post for post in posts if post['end'] is not None]
    assert len(finished) == len(posts) >= 1
    assert len(posts) < len(moves), (
        'moves made during a save should be sent together', len(posts)
    )
    for earlier, later in zip(posts, posts[1:]):
        assert earlier['end'] <= later['start'], 'two saves overlapped'
    assert filled(posts[-1]['body']['alignment']) == final

    # Polls after the queue drained must not bring an older board back.
    page.wait_for_timeout(4_500)
    assert board_alignment(page) == final
    assert server_next(page, coachboard_url, game_id) == final


def test_end_inning_waits_for_the_queue_and_starts_with_the_final_defense(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    slow_network(page)

    moves = [('SS', 'P'), ('LF', 'RF')]
    for source, target in moves:
        swap(board, source, target)
    final = expected_after(*moves)
    expect(spot(board, 'RF')).to_contain_text(
        final['RF'], timeout=IMMEDIATE_MS
    )

    page.locator('#liveEndInningBtn').click()

    expect(page.locator('#live-inning-display')).to_have_text(
        '2', timeout=25_000
    )
    # A complete defense asks nothing.
    expect(page.locator('#cbIncompleteNextModal')).not_to_be_visible()

    state = live_state(page, coachboard_url, game_id)
    assert str(state['current_inning']) == '2'
    assert filled(state['current_alignment']) == final


# ----------------------------------------------- failed save, reconnect


def test_failed_save_keeps_the_board_and_syncs_on_reconnect(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    original = filled(starting_alignment())

    page.context.set_offline(True)
    swap(board, 'SS', 'P')
    swap(board, 'LF', 'CF')
    final = expected_after(('SS', 'P'), ('LF', 'CF'))

    badge = board.locator('.cb-next-save')
    expect(badge).to_have_text('Not synced — retrying', timeout=5_000)
    expect(board.locator('[data-next-notice]')).to_contain_text(
        'will sync automatically'
    )
    expect(board).not_to_contain_text('Failed to fetch')
    expect(board).not_to_contain_text('Not saved')

    # Still the coach's board, not reverted, and nothing reached the server.
    page.wait_for_timeout(1_500)
    assert board_alignment(page) == final
    assert server_next(page, coachboard_url, game_id) == original

    page.context.set_offline(False)

    wait_for_server(page, coachboard_url, game_id, final)
    expect(badge).to_have_class(re.compile(r'\bsaved\b'), timeout=10_000)
    expect(board.locator('[data-next-notice]')).to_be_hidden()
    assert board_alignment(page) == final


def test_failed_saves_do_not_hammer_the_server(
    page: Page, coachboard_url, next_board
):
    """Retries come only from the existing triggers, never a tight loop.

    Fully offline, the poll's read fails, so nothing is re-sent at all.
    With the reads working but every save failing, a save is retried at most
    once per successful poll (every 3.5 s), not continuously.
    """
    board, game_id = next_board
    posts = record_prep_posts(page)

    page.context.set_offline(True)
    swap(board, 'SS', 'P')
    expect(board.locator('.cb-next-save')).to_have_text(
        'Not synced — retrying', timeout=5_000
    )
    page.wait_for_timeout(8_000)
    assert len(posts) == 1, f'{len(posts)} save attempts while offline'
    page.context.set_offline(False)
    wait_for_server(
        page, coachboard_url, game_id, expected_after(('SS', 'P'))
    )

    page.route(
        PREP_URL,
        lambda route: (
            route.fulfill(status=503, json={'status': 'error', 'message': 'Busy'})
            if route.request.method == 'POST'
            else route.continue_()
        ),
    )
    posts.clear()
    swap(board, 'LF', 'CF')
    expect(board.locator('.cb-next-save')).to_have_text(
        'Not synced — retrying', timeout=5_000
    )
    page.wait_for_timeout(8_000)
    # The first attempt plus at most one retry per 3.5 s poll.
    assert 2 <= len(posts) <= 4, f'{len(posts)} save attempts in 8 s'


def test_end_inning_while_unsynced_explains_and_does_not_advance(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board

    page.route(
        PREP_URL,
        lambda route: (
            route.abort('internetdisconnected')
            if route.request.method == 'POST'
            else route.continue_()
        ),
    )
    swap(board, 'SS', 'P')
    expect(board.locator('.cb-next-save')).to_have_text(
        'Not synced — retrying', timeout=5_000
    )

    page.locator('#liveEndInningBtn').click()

    expect(board.locator('.cb-next-error')).to_contain_text(
        'has not synced yet', timeout=15_000
    )
    expect(board).not_to_contain_text('Failed to fetch')
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'
    assert board_alignment(page) == expected_after(('SS', 'P'))


# ------------------------------------------------------ stale conflicts


def other_coach_sets(page: Page, url: str, game_id: int, alignment):
    """Another coach's device: a plain save that does not know this board."""
    post_json(
        page, url,
        f'/api/live-game/{game_id}/next-inning-prep',
        {'mode': 'custom', 'alignment': alignment},
    )


def test_server_rejects_a_save_based_on_an_older_defense(
    page: Page, coachboard_url, next_board
):
    _, game_id = next_board
    other = expected_after(('LF', 'RF'))
    other_coach_sets(page, coachboard_url, game_id, other)

    response = page.request.post(
        f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep',
        data={
            'mode': 'custom',
            'alignment': expected_after(('SS', 'P')),
            'base_alignment': starting_alignment(),
            'inning': '2',
        },
    )
    assert response.status == 409
    assert response.json()['code'] == 'next_prep_conflict'

    response = page.request.post(
        f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep',
        data={
            'mode': 'custom',
            'alignment': expected_after(('SS', 'P')),
            'base_alignment': other,
            'inning': '3',
        },
    )
    assert response.status == 409
    assert response.json()['code'] == 'next_prep_conflict'

    assert server_next(page, coachboard_url, game_id) == other


def test_offline_change_does_not_overwrite_a_newer_defense(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    other = expected_after(('LF', 'RF'))

    page.context.set_offline(True)
    swap(board, 'SS', 'P')
    expect(board.locator('.cb-next-save')).to_have_text(
        'Not synced — retrying', timeout=5_000
    )

    # While this coach is offline, another coach changes Next Inning.
    other_coach_sets(page, coachboard_url, game_id, other)

    page.context.set_offline(False)

    expect(board.locator('[data-next-notice]')).to_contain_text(
        'changed on another device', timeout=15_000
    )
    expect(spot(board, 'LF')).to_contain_text(other['LF'])
    expect(spot(board, 'SS')).to_contain_text(other['SS'])
    assert board_alignment(page) == other
    page.wait_for_timeout(1_000)
    assert server_next(page, coachboard_url, game_id) == other


def test_slow_save_does_not_overwrite_a_newer_defense(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    other = expected_after(('LF', 'RF'))
    held = []

    def other_coach_first(route):
        # This coach's save is still on its way when another coach's save
        # reaches the server first.
        if route.request.method == 'POST' and not held:
            held.append(route.request.post_data_json)
            other_coach_sets(page, coachboard_url, game_id, other)
        route.continue_()

    page.route(PREP_URL, other_coach_first)

    swap(board, 'SS', 'P')
    expect(spot(board, 'P')).to_contain_text(
        'Shortstop Shawn', timeout=IMMEDIATE_MS
    )

    expect(board.locator('[data-next-notice]')).to_contain_text(
        'changed on another device', timeout=15_000
    )
    assert held, 'the save never left the page'
    assert board_alignment(page) == other
    page.wait_for_timeout(1_000)
    assert server_next(page, coachboard_url, game_id) == other


def test_another_coachs_change_clears_a_selection_with_a_notice(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    other = expected_after(('LF', 'RF'))

    spot(board, 'SS').click()
    expect(board.locator('[data-next-cancel]')).to_have_count(1)

    other_coach_sets(page, coachboard_url, game_id, other)

    expect(board.locator('[data-next-notice]')).to_have_text(
        'Defense updated by another coach.', timeout=10_000
    )
    expect(board.locator('[data-next-cancel]')).to_have_count(0)
    assert board_alignment(page) == other


# -------------------------------------------------------- pitcher swaps


def test_field_player_to_pitcher_swaps_and_bench_to_pitcher_benches(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board

    # SS -> P: the pitcher takes shortstop; nothing is left open.
    swap(board, 'SS', 'P')
    expect(spot(board, 'P')).to_contain_text('Shortstop Shawn')
    expect(spot(board, 'SS')).to_contain_text('Pitcher Pat')

    # P -> field: the same swap in the other direction.
    swap(board, 'P', '3B')
    expect(spot(board, 'P')).to_contain_text('Third Theo')
    expect(spot(board, '3B')).to_contain_text('Shortstop Shawn')

    swapped = expected_after(('SS', 'P'), ('P', '3B'))
    assert board_alignment(page) == swapped
    wait_for_server(page, coachboard_url, game_id, swapped)

    # Bench -> P keeps its own rule: the old pitcher goes to the bench.
    spot(board, 'CF').click()
    board.locator('[data-next-bench-selected]').click()
    expect(spot(board, 'CF')).not_to_contain_text('Center Casey')
    board.locator('[data-next-bench-player="Center Casey"]').click()
    spot(board, 'P').click()
    expect(spot(board, 'P')).to_contain_text('Center Casey')

    after = board_alignment(page)
    assert 'Third Theo' not in after.values()
    assert sorted(set(starting_alignment()) - set(after)) == ['CF'], (
        'only the spot the coach emptied may be open', after
    )
    wait_for_server(page, coachboard_url, game_id, after)


def test_shortstop_to_pitcher_swap_is_the_next_innings_pitching_change(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board

    swap(board, 'SS', 'P')
    final = expected_after(('SS', 'P'))
    wait_for_server(page, coachboard_url, game_id, final)

    page.locator('#liveEndInningBtn').click()
    expect(page.locator('#live-inning-display')).to_have_text(
        '2', timeout=20_000
    )

    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == final
    assert state['current_alignment']['SS'] == 'Pitcher Pat'
    end_inning = [
        event for event in state.get('rotation_events', [])
        if event.get('event_type') == 'End Inning' and not event.get('reverted')
    ]
    assert end_inning, state.get('rotation_events')
    assert end_inning[-1]['before_alignment']['P'] == 'Pitcher Pat'
    assert end_inning[-1]['after_alignment']['P'] == 'Shortstop Shawn'


# -------------------------------------------------- incomplete defense


def bench(board, position):
    spot(board, position).click()
    board.locator('[data-next-bench-selected]').click()
    expect(spot(board, position)).to_have_attribute(
        'data-next-player', '', timeout=IMMEDIATE_MS
    )


def test_incomplete_defense_warns_and_confirms_before_starting(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    end_inning = page.locator('#liveEndInningBtn')
    modal = page.locator('#cbIncompleteNextModal')

    bench(board, 'SS')

    # The warning sits right above End Inning, in view on a phone and not
    # covered by the fixed action bar.
    warning = page.locator('#cbNextOpenWarning')
    expect(warning).to_have_text('⚠ Next inning: SS is open')
    box = warning.bounding_box()
    button = end_inning.bounding_box()
    assert box and button
    assert box['y'] + box['height'] <= button['y'] + 1
    assert box['y'] >= 0 and button['y'] + button['height'] <= PHONE['height']
    assert page.evaluate(
        """() => {
            const w = document.getElementById('cbNextOpenWarning');
            const r = w.getBoundingClientRect();
            const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            return hit === w || w.contains(hit);
        }"""
    )

    # One open spot: the confirmation names it; Finish defense changes nothing.
    wait_for_server(page, coachboard_url, game_id, filled(board_alignment(page)))
    end_inning.click()
    expect(modal).to_be_visible(timeout=10_000)
    expect(modal.locator('.modal-title')).to_have_text('Defense is incomplete')
    expect(modal).to_contain_text('SS is still open.')
    modal.get_by_role('button', name='Finish defense').click()
    expect(modal).to_be_hidden()
    expect(board).to_be_visible()
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'

    # Several open spots: every one is named; Start inning anyway advances.
    bench(board, 'LF')
    expect(warning).to_have_text('⚠ Next inning: SS, LF are open')
    wait_for_server(page, coachboard_url, game_id, board_alignment(page))
    end_inning.click()
    expect(modal).to_be_visible(timeout=10_000)
    expect(modal).to_contain_text('SS and LF are still open.')
    modal.get_by_role('button', name='Start inning anyway').click()

    expect(page.locator('#live-inning-display')).to_have_text(
        '2', timeout=20_000
    )
    state = live_state(page, coachboard_url, game_id)
    assert not state['current_alignment'].get('SS')
    assert not state['current_alignment'].get('LF')


def open_on_the_field(page: Page, url: str, game_id: int, *positions):
    state = live_state(page, url, game_id)
    sequence = max(
        [
            int(event.get('sequence') or 0)
            for event in state.get('rotation_events', [])
            if not event.get('reverted')
        ]
        or [0]
    )
    alignment = {
        pos: name
        for pos, name in filled(state['current_alignment']).items()
        if pos not in positions
    }
    response = page.request.post(
        f'{url}/api/live-game/{game_id}/defense-edit',
        data={'alignment': alignment, 'base_sequence': sequence},
    )
    assert response.ok, response.text()[:300]


def end_inning_anyway_on_the_field(page: Page):
    page.locator('#liveEndInningBtn').click()
    field_warning = page.locator('#cbOpenDefenseEndModal')
    expect(field_warning).to_be_visible(timeout=10_000)
    field_warning.get_by_role('button', name='End Inning Anyway').click()


def test_accepted_field_gaps_are_not_asked_twice_but_different_gaps_are(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    incomplete = page.locator('#cbIncompleteNextModal')

    # On the Field has SS and LF open; Next Inning has only SS open.
    open_on_the_field(page, coachboard_url, game_id, 'SS', 'LF')
    next_alignment = {
        pos: name for pos, name in starting_alignment().items() if pos != 'SS'
    }
    other_coach_sets(page, coachboard_url, game_id, next_alignment)
    expect(spot(board, 'SS')).to_have_attribute(
        'data-next-player', '', timeout=10_000
    )

    end_inning_anyway_on_the_field(page)
    expect(incomplete).to_be_visible(timeout=10_000)
    expect(incomplete).to_contain_text('SS is still open.')
    incomplete.get_by_role('button', name='Finish defense').click()
    expect(incomplete).to_be_hidden()
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'

    # Next Inning now has exactly the gaps already accepted on the field:
    # no second question.
    bench(board, 'LF')
    wait_for_server(page, coachboard_url, game_id, board_alignment(page))

    end_inning_anyway_on_the_field(page)
    expect(page.locator('#live-inning-display')).to_have_text(
        '2', timeout=20_000
    )
    expect(incomplete).not_to_be_visible()
