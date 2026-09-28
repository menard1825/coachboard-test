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

import pitching_eligibility

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
    """Move source's player to target. For ordinary positions that is only
    half a swap: CoachBoard asks where target's player goes, and the coach
    explicitly sends them to the vacated spot. (Moves involving P ask the
    pitching question instead; those tests answer it themselves.)"""
    displaced = spot(board, target).get_attribute('data-next-player') or ''
    spot(board, source).click()
    spot(board, target).click()
    if displaced and 'P' not in (source, target):
        answer_displaced(board.page, displaced, source)


def answer_displaced(page: Page, displaced, vacated):
    sheet = page.locator('#cbNextPitchingChange')
    expect(sheet).to_contain_text(f'Where should {displaced} go?', timeout=5_000)
    # The answer applies at once; no wait for the sheet's fade, so callers
    # can still check the board "immediately" after the move.
    sheet.get_by_role('button', name=f'Put {displaced} at {vacated}', exact=True).click()


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
    # Each swap is now a move plus the coach's explicit answer, so give the
    # first save long enough in flight for the next moves to coalesce.
    slow_network(page, latency_ms=3000)

    moves = [('SS', '2B'), ('LF', 'CF'), ('1B', '3B')]
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

    moves = [('SS', '2B'), ('LF', 'RF')]
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
    swap(board, 'SS', '2B')
    swap(board, 'LF', 'CF')
    final = expected_after(('SS', '2B'), ('LF', 'CF'))

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
    swap(board, 'SS', '2B')
    expect(board.locator('.cb-next-save')).to_have_text(
        'Not synced — retrying', timeout=5_000
    )
    page.wait_for_timeout(8_000)
    assert len(posts) == 1, f'{len(posts)} save attempts while offline'
    page.context.set_offline(False)
    wait_for_server(
        page, coachboard_url, game_id, expected_after(('SS', '2B'))
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
    swap(board, 'SS', '2B')
    expect(board.locator('.cb-next-save')).to_have_text(
        'Not synced — retrying', timeout=5_000
    )

    page.locator('#liveEndInningBtn').click()

    expect(board.locator('.cb-next-error')).to_contain_text(
        'has not synced yet', timeout=15_000
    )
    expect(board).not_to_contain_text('Failed to fetch')
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'
    assert board_alignment(page) == expected_after(('SS', '2B'))


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
            'alignment': expected_after(('SS', '2B')),
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
            'alignment': expected_after(('SS', '2B')),
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
    swap(board, 'SS', '2B')
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

    swap(board, 'SS', '2B')
    expect(spot(board, '2B')).to_contain_text(
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


# ------------------------------------------------------ pitching changes


def pitching_question(page: Page):
    sheet = page.locator('#cbNextPitchingChange')
    expect(sheet).to_be_visible(timeout=5_000)
    return sheet


def choose(page: Page, label):
    sheet = pitching_question(page)
    sheet.get_by_role('button', name=label, exact=True).click()
    expect(sheet).to_be_hidden()


def test_fielder_to_pitcher_asks_where_the_pitcher_goes(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    posts = record_prep_posts(page)
    original = filled(starting_alignment())

    # SS -> P: nothing moves until the coach says where Pat goes.
    swap(board, 'SS', 'P')
    sheet = pitching_question(page)
    expect(sheet).to_contain_text('Shortstop Shawn is going in to pitch')
    expect(sheet).to_contain_text('Where should Pitcher Pat go?')
    assert board_alignment(page) == original
    page.wait_for_timeout(500)
    assert posts == [], 'nothing may be saved while the coach decides'

    # Cancel changes nothing.
    choose(page, 'Cancel')
    assert board_alignment(page) == original

    # The coach chooses the swap.
    swap(board, 'SS', 'P')
    choose(page, 'Put Pitcher Pat at SS')
    swapped = expected_after(('SS', 'P'))
    expect(spot(board, 'P')).to_contain_text('Shortstop Shawn')
    expect(spot(board, 'SS')).to_contain_text('Pitcher Pat')
    wait_for_server(page, coachboard_url, game_id, swapped)
    assert len(posts) == 1, 'the resolved defense is one save'


def test_fielder_to_pitcher_bench_choice_leaves_the_spot_open(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board

    swap(board, 'SS', 'P')
    choose(page, 'Bench Pitcher Pat · SS open')

    expect(spot(board, 'P')).to_contain_text('Shortstop Shawn')
    expect(spot(board, 'SS')).to_have_attribute('data-next-player', '')
    expect(
        board.locator('[data-next-bench-player="Pitcher Pat"]')
    ).to_be_visible()
    expected = {
        pos: name for pos, name in expected_after(('SS', 'P')).items()
        if pos != 'SS'
    }
    wait_for_server(page, coachboard_url, game_id, expected)

    # The deliberately open SS is still caught before the inning starts.
    expect(page.locator('#cbNextOpenWarning')).to_have_text(
        '⚠ Next inning: SS is open'
    )
    page.locator('#liveEndInningBtn').click()
    modal = page.locator('#cbIncompleteNextModal')
    expect(modal).to_be_visible(timeout=10_000)
    expect(modal).to_contain_text('SS is still open for the 2nd inning.')
    modal.get_by_role('button', name='Finish 2nd Inning Defense').click()
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'


def test_pitcher_to_field_asks_who_pitches(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    original = filled(starting_alignment())

    # P -> SS: Shawn is not silently put on the mound.
    swap(board, 'P', 'SS')
    sheet = pitching_question(page)
    expect(sheet).to_contain_text('Pitcher Pat is moving to SS')
    expect(sheet).to_contain_text("Who's pitching next inning?")
    assert board_alignment(page) == original
    choose(page, 'Cancel')
    assert board_alignment(page) == original

    # Benching the displaced shortstop leaves P visibly open.
    swap(board, 'P', 'SS')
    choose(page, 'Bench Shortstop Shawn · P open')
    expect(spot(board, 'SS')).to_contain_text('Pitcher Pat')
    expect(spot(board, 'P')).to_have_attribute('data-next-player', '')
    expect(board.locator('.cb-next-warnings')).to_contain_text(
        'Set a pitcher for the next inning'
    )
    expected = {
        pos: name for pos, name in original.items() if pos != 'P'
    }
    expected['SS'] = 'Pitcher Pat'
    wait_for_server(page, coachboard_url, game_id, expected)

    # Undo takes the whole answer back in one step.
    page.locator('#liveUndoBtn').click()
    wait_for_server(page, coachboard_url, game_id, original)

    # Choosing the shortstop to pitch is the swap, because the coach said so.
    swap(board, 'P', 'SS')
    choose(page, 'Shortstop Shawn pitches')
    wait_for_server(
        page, coachboard_url, game_id, expected_after(('SS', 'P'))
    )


def test_bench_to_pitcher_asks_where_the_pitcher_goes(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board

    bench(board, 'CF')
    swap_from_bench = board.locator(
        '[data-next-bench-player="Center Casey"]'
    )
    swap_from_bench.click()
    spot(board, 'P').click()

    sheet = pitching_question(page)
    expect(sheet).to_contain_text('Center Casey is going in to pitch')
    expect(sheet).to_contain_text('Where should Pitcher Pat go?')
    before = board_alignment(page)
    assert before['P'] == 'Pitcher Pat'

    # The open CF is offered by name; nothing is decided for the coach.
    choose(page, 'Put Pitcher Pat at CF')
    expected = dict(before, P='Center Casey', CF='Pitcher Pat')
    expect(spot(board, 'P')).to_contain_text('Center Casey')
    expect(spot(board, 'CF')).to_contain_text('Pitcher Pat')
    wait_for_server(page, coachboard_url, game_id, expected)


def test_pitching_change_through_a_slow_save_starts_the_next_inning(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    slow_network(page)

    swap(board, 'SS', 'P')
    choose(page, 'Put Pitcher Pat at SS')
    swap(board, 'LF', 'RF')
    final = expected_after(('SS', 'P'), ('LF', 'RF'))
    expect(spot(board, 'RF')).to_contain_text(
        final['RF'], timeout=IMMEDIATE_MS
    )

    # End Inning waits for the queued saves, then records the change.
    page.locator('#liveEndInningBtn').click()
    expect(page.locator('#live-inning-display')).to_have_text(
        '2', timeout=25_000
    )

    state = live_state(page, coachboard_url, game_id)
    assert filled(state['current_alignment']) == final
    end_inning = [
        event for event in state.get('rotation_events', [])
        if event.get('event_type') == 'End Inning' and not event.get('reverted')
    ]
    assert end_inning, state.get('rotation_events')
    assert end_inning[-1]['before_alignment']['P'] == 'Pitcher Pat'
    assert end_inning[-1]['after_alignment']['P'] == 'Shortstop Shawn'
    assert end_inning[-1]['after_alignment']['SS'] == 'Pitcher Pat'


# ------------------------------------------------- pitching readiness


def force_pitching_status(page: Page, game_id: int, name, status, daily, detail):
    """Show `name` with a pitching status, the way the live state reports it.

    Rewrites only what this browser reads (as the On the Field Change
    Pitcher test does); the server's own End Inning check is unaffected and
    covered by tests/test_live_game_feedback_pass.py.
    """
    def rewrite(route):
        response = route.fetch()
        payload = response.json()
        item = {'status': status, 'daily': daily, 'status_detail': detail}
        # What the server's shared policy says (and shows) about that status.
        item.update(pitching_eligibility.describe(
            name, item, {'rule_set_name': 'MLB Pitch Smart'}
        ))
        payload.setdefault('pitch_count_summary', {})[name] = item
        route.fulfill(status=response.status, headers=response.headers, json=payload)

    page.route(f'**/api/live-game/{game_id}/state', rewrite)
    page.reload(wait_until='domcontentloaded')
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator(CARD)
    expect(spot(board, 'P')).not_to_have_attribute(
        'data-next-player', '', timeout=10_000
    )
    return board


def test_ready_pitcher_shows_readiness_and_continues(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board

    swap(board, 'SS', 'P')
    sheet = pitching_question(page)
    expect(sheet.locator('[data-pitch-readiness]')).to_contain_text(
        'Shortstop Shawn: Ready'
    )
    choose(page, 'Put Pitcher Pat at SS')
    wait_for_server(
        page, coachboard_url, game_id, expected_after(('SS', 'P'))
    )


RESTING_REASON = (
    'Rule conflict · 0 pitches today · MLB Pitch Smart: Resting. '
    '66 game pitches on Sun, Sep 27 require 3 day(s) rest.'
)


def test_rule_conflict_pitcher_can_be_planned_with_the_reason(
    page: Page, coachboard_url, next_board
):
    """A plan is not the official field: a flagged pitcher can be planned.

    The sheet asks only the usual destination question and shows the rule
    conflict; End Inning asks for the coach's decision later. Cancel
    changes nothing.
    """
    _, game_id = next_board
    board = force_pitching_status(
        page, game_id, 'Shortstop Shawn', 'Resting', 0, '66 game pitches on Sun, Sep 27 require 3 day(s) rest.'
    )
    posts = record_prep_posts(page)
    original = filled(starting_alignment())

    swap(board, 'SS', 'P')
    sheet = pitching_question(page)
    expect(sheet).to_contain_text('Shortstop Shawn is going in to pitch')
    expect(sheet.locator('[data-pitch-readiness]')).to_have_text(
        f'Shortstop Shawn: {RESTING_REASON} '
        'End Inning will ask whether to use Shortstop Shawn anyway.'
    )

    choose(page, 'Cancel')
    page.wait_for_timeout(500)
    assert board_alignment(page) == original
    assert posts == []

    # From the other direction too, the flagged player is a choice.
    swap(board, 'P', 'SS')
    sheet = pitching_question(page)
    expect(sheet.locator('[data-pitch-readiness]')).to_contain_text('Rule conflict')
    expect(
        sheet.get_by_role('button', name='Shortstop Shawn pitches', exact=True)
    ).to_be_enabled()
    choose(page, 'Cancel')
    assert board_alignment(page) == original

    swap(board, 'SS', 'P')
    choose(page, 'Put Pitcher Pat at SS')
    wait_for_server(page, coachboard_url, game_id, expected_after(('SS', 'P')))
    expect(board.locator('[data-next-pitcher-status]')).to_contain_text('Rule conflict')


def test_unconfirmed_pitcher_can_be_planned_with_a_clear_note(
    page: Page, coachboard_url, next_board
):
    """Eligibility CoachBoard can't confirm is not "ineligible".

    The coach may plan the pitcher; the note says End Inning will ask them
    to confirm they verified it. Nothing is decided for them meanwhile.
    """
    _, game_id = next_board
    board = force_pitching_status(
        page, game_id, 'Center Casey', 'Unavailable — Pitch Count Incomplete', None,
        'Verify missing game pitch counts before using this pitcher.',
    )

    bench(board, 'CF')
    before = board_alignment(page)
    board.locator('[data-next-bench-player="Center Casey"]').click()
    spot(board, 'P').click()

    sheet = pitching_question(page)
    expect(sheet).to_contain_text('Center Casey is going in to pitch')
    expect(sheet).not_to_contain_text('ineligible')
    expect(sheet.locator('[data-pitch-readiness]')).to_have_text(
        "Center Casey: Can't confirm · CoachBoard can't confirm Center "
        "Casey's pitching eligibility (Pitch Count Incomplete). Verify "
        'missing game pitch counts before using this pitcher. End Inning '
        'will ask you to confirm you verified Center Casey is eligible.'
    )

    # Cancel changes nothing.
    choose(page, 'Cancel')
    assert board_alignment(page) == before

    board.locator('[data-next-bench-player="Center Casey"]').click()
    spot(board, 'P').click()
    choose(page, 'Bench Pitcher Pat')
    expected = dict(before, P='Center Casey')
    wait_for_server(page, coachboard_url, game_id, expected)
    expect(board.locator('[data-next-pitcher-status]')).to_have_text(
        "⚠ Pitcher: Center Casey · Can't confirm · CoachBoard can't confirm "
        "Center Casey's pitching eligibility (Pitch Count Incomplete). "
        'Verify missing game pitch counts before using this pitcher. · '
        'End Inning will ask you to decide'
    )


def planned_pitching_change():
    """Shawn planned to pitch next inning, Pat to short (a pitching change)."""
    return expected_after(('SS', 'P'))


def no_question_open(page: Page):
    page.wait_for_timeout(800)
    expect(page.locator('#cbNextPitchingChange')).not_to_be_visible()
    expect(page.locator('#cbIncompleteNextModal')).not_to_be_visible()


def test_board_shows_a_ready_planned_pitcher_quietly(
    page: Page, coachboard_url, next_board
):
    board, game_id = next_board
    status = board.locator('[data-next-pitcher-status]')

    # The pitcher on the mound carrying into the next inning. CoachBoard
    # can't count this game's pitches until it ends, and says so.
    expect(status).to_have_text(
        "Pitcher: Pitcher Pat · pitching now · this game's pitches aren't counted until it ends"
    )
    expect(status).to_have_class(re.compile(r'\bready\b'))

    other_coach_sets(page, coachboard_url, game_id, planned_pitching_change())
    expect(status).to_contain_text(
        'Pitcher: Shortstop Shawn · Ready', timeout=10_000
    )
    expect(status).to_have_class(re.compile(r'\bready\b'))
    expect(status).not_to_contain_text('⚠')
    no_question_open(page)


def test_board_flags_a_rule_conflict_planned_pitcher_without_a_modal(
    page: Page, coachboard_url, next_board
):
    _, game_id = next_board
    other_coach_sets(page, coachboard_url, game_id, planned_pitching_change())
    board = force_pitching_status(
        page, game_id, 'Shortstop Shawn', 'Resting', 0, '66 game pitches on Sun, Sep 27 require 3 day(s) rest.'
    )
    status = board.locator('[data-next-pitcher-status]')

    expect(status).to_have_text(
        f'⚠ Pitcher: Shortstop Shawn · {RESTING_REASON} · '
        'End Inning will ask you to decide',
        timeout=10_000,
    )
    expect(status).to_have_class(re.compile(r'\brule_conflict\b'))
    expect(status).to_be_in_viewport()
    no_question_open(page)


def test_board_says_unknown_eligibility_cannot_be_confirmed(
    page: Page, coachboard_url, next_board
):
    _, game_id = next_board
    other_coach_sets(page, coachboard_url, game_id, planned_pitching_change())
    board = force_pitching_status(page, game_id, 'Shortstop Shawn', '', None, '')
    status = board.locator('[data-next-pitcher-status]')

    expect(status).to_have_text(
        "⚠ Pitcher: Shortstop Shawn · Can't confirm · CoachBoard can't "
        "confirm Shortstop Shawn's pitching eligibility. · "
        'End Inning will ask you to decide',
        timeout=10_000,
    )
    expect(status).to_have_class(re.compile(r'\bunknown\b'))
    expect(status).not_to_contain_text('ineligible')
    no_question_open(page)


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
    expect(modal.locator('.modal-title')).to_have_text('2nd inning defense still open')
    expect(modal).to_contain_text('SS is still open for the 2nd inning.')
    modal.get_by_role('button', name='Finish 2nd Inning Defense').click()
    expect(modal).to_be_hidden()
    expect(board).to_be_visible()
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'

    # Several open spots: every one is named; Start inning anyway advances.
    bench(board, 'LF')
    expect(warning).to_have_text('⚠ Next inning: SS, LF are open')
    wait_for_server(page, coachboard_url, game_id, board_alignment(page))
    end_inning.click()
    expect(modal).to_be_visible(timeout=10_000)
    expect(modal).to_contain_text('SS and LF are still open for the 2nd inning.')
    modal.get_by_role('button', name='Start Inning Anyway').click()

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


def test_recorded_inning_gaps_and_next_inning_gaps_are_separate_questions(
    page: Page, coachboard_url, next_board
):
    """The inning being recorded and the next inning's plan are asked
    about separately, each naming its own inning. "Keep as Recorded" is
    remembered for that recorded defense; the plan is what gets sent."""
    board, game_id = next_board
    recorded = page.locator('#cbRecordedInningGapModal')
    incomplete = page.locator('#cbIncompleteNextModal')

    # On the Field has SS and LF open; the Next Inning plan has only SS open.
    open_on_the_field(page, coachboard_url, game_id, 'SS', 'LF')
    next_alignment = {
        pos: name for pos, name in starting_alignment().items() if pos != 'SS'
    }
    other_coach_sets(page, coachboard_url, game_id, next_alignment)
    expect(spot(board, 'SS')).to_have_attribute(
        'data-next-player', '', timeout=10_000
    )

    page.locator('#liveEndInningBtn').click()
    expect(recorded).to_be_visible(timeout=10_000)
    expect(recorded.locator('.modal-title')).to_have_text(
        '1st inning record has an open position'
    )
    expect(recorded).to_contain_text(
        'SS and LF were left open on the recorded defense for the 1st inning.'
    )
    recorded.get_by_role('button', name='Keep as Recorded').click()

    # Then the plan: only SS is open for the 2nd inning.
    expect(incomplete).to_be_visible(timeout=10_000)
    expect(incomplete.locator('.modal-title')).to_have_text(
        '2nd inning defense still open'
    )
    expect(incomplete).to_contain_text('SS is still open for the 2nd inning.')
    expect(incomplete).not_to_contain_text('LF')
    incomplete.get_by_role('button', name='Finish 2nd Inning Defense').click()
    expect(incomplete).to_be_hidden()
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '1'

    # A gap added to the plan is named too. The recorded gaps were already
    # kept, so they are not asked again; "Start Inning Anyway" sends
    # exactly the plan the warning described.
    bench(board, 'LF')
    wait_for_server(page, coachboard_url, game_id, board_alignment(page))
    planned = board_alignment(page)

    page.locator('#liveEndInningBtn').click()
    expect(incomplete).to_contain_text(
        'SS and LF are still open for the 2nd inning.', timeout=10_000
    )
    expect(recorded).not_to_be_visible()
    incomplete.get_by_role('button', name='Start Inning Anyway').click()
    expect(page.locator('#live-inning-display')).to_have_text(
        '2', timeout=20_000
    )
    assert filled(
        live_state(page, coachboard_url, game_id)['current_alignment']
    ) == planned
