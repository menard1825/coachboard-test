"""Shared setup for live-game browser tests.

Starting a live game, reading and changing it over the API, and opening the
Next Inning planner, for every live-game test module to import. Fixtures are
imported into a test module like any other name (`from live_fixtures import
live`) and then requested as arguments.

Three ways to get a live game, each with its own players:

* `live` -- a fresh browser context per device; the named LINEUP players
  (live_field_markers) and a pregame plan of three innings. The page carries
  `cb_api` (a second, logged-in page for API calls), `cb_game`, `cb_errors`
  and `cb_writes`.
* `live_field` -- the test's own `page` at phone size, the BASE players plus
  RELIEVER on the bench; yields `open_field()`, which opens the game.
* `next_board` -- the test's own `page` at phone size, the BASE players, the
  game open with the Next Inning planner showing; yields (planner, game_id).
"""

import re
import time
from datetime import date, timedelta

import pytest
from playwright.sync_api import Page, expect

import cdn_assets
import live_field_markers
from e2e_cleanup import delete_players_named
from live_field_markers import LINEUP, create_named_live_game, remove_named_live_game
from start_helpers import start_body


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


# ------------------------------------------------------- account and API


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()

    expect(page).to_have_url(
        re.compile(
            rf'^{re.escape(coachboard_url)}/?'
            rf'(?:#(?:overview|games))?$'
        )
    )


def post_json(page: Page, coachboard_url: str, path: str, data):
    response = page.request.post(
        f'{coachboard_url}{path}',
        data=data,
    )

    assert response.status == 200, (
        f'POST {path} returned '
        f'{response.status}: {response.text()}'
    )

    payload = response.json()
    assert payload.get('status') == 'success', payload
    return payload


def cleanup_game(
    page: Page,
    coachboard_url: str,
    game_id: int,
):
    state_response = page.request.get(
        f'{coachboard_url}/api/live-game/'
        f'{game_id}/state'
    )

    if (
        state_response.ok
        and state_response.json()
        .get('game', {})
        .get('is_live')
    ):
        page.request.post(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/end-with-pitching',
            data={
                'defer_pitching': True,
                'end_reason': 'manual',
                'current_inning_played': True,
            },
        )

    page.request.post(
        f'{coachboard_url}/game-day/'
        f'{game_id}/delete',
        headers={
            'Accept': 'application/json',
        },
    )


# ------------------------------------------------------ the live defense


def starting_alignment():
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


BASE = starting_alignment()
RELIEVER = 'Bench Blake'


def filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def last_sequence(state):
    """The newest live event still in effect (a defensive change's base_sequence)."""
    return max([int(e.get('sequence') or 0) for e in state.get('rotation_events') or [] if not e.get('reverted')] or [0])


def live_state(page: Page, url: str, game_id: int):
    response = page.request.get(f'{url}/api/live-game/{game_id}/state')
    assert response.ok, response.text()[:300]
    return response.json()


def set_live_defense(page: Page, url: str, game_id: int, alignment):
    """Another coach's live defensive change: the whole field."""
    state = live_state(page, url, game_id)
    response = page.request.post(
        f'{url}/api/live-game/{game_id}/defense-edit',
        data={'alignment': alignment, 'base_sequence': last_sequence(state)},
    )
    assert response.ok, response.text()[:300]


def leave_live_positions_open(page: Page, url: str, game_id: int, *positions):
    """A live defensive change that leaves `positions` open."""
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


def wait_for_field(page, url, game_id, expected, timeout_ms=10_000):
    waited = 0
    while waited < timeout_ms:
        if filled(live_state(page, url, game_id)['current_alignment']) == expected:
            return
        page.wait_for_timeout(200)
        waited += 200
    assert filled(live_state(page, url, game_id)['current_alignment']) == expected


def pitcher_changes(state):
    return [
        event for event in state.get('rotation_events', [])
        if event.get('event_type') == 'Pitcher Change' and not event.get('reverted')
    ]


# ------------------------------------------- moves on the live field


MOVE_SHEET = '#cbQuickMoveModal'


def defense_writes(page: Page):
    posts = []
    page.on(
        'request',
        lambda request: posts.append(request.post_data_json)
        if request.method == 'POST' and 'defense-edit' in request.url
        else None,
    )
    return posts


def live_events(state):
    return [e for e in state.get('rotation_events', []) if not e.get('reverted')]


def field_player(position):
    return f'[data-cb-position="{position}"]'


def bench_player(name):
    return f'.cb-qd-bench-player[data-cb-move-player="{name}"]'


def tap_move(page: Page, player_selector: str, destination: str):
    page.locator(f'#cbQuickDefense {player_selector}').click()
    sheet = page.locator(MOVE_SHEET)
    expect(sheet).to_be_visible(timeout=10_000)
    sheet.locator(f'[data-cb-destination="{destination}"]').click()
    return sheet


def drag(page: Page, source, target):
    s, t = source.bounding_box(), target.bounding_box()
    page.mouse.move(s['x'] + s['width'] / 2, s['y'] + s['height'] / 2)
    page.mouse.down()
    page.mouse.move(t['x'] + t['width'] / 2, t['y'] + t['height'] / 2, steps=12)
    page.mouse.up()


# ------------------------------------- `live`: the named LINEUP players


PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})

INNING_1 = {pos: name for pos, (name, _) in LINEUP.items()}
INNING_2 = {**INNING_1, 'P': INNING_1['1B'], '1B': INNING_1['P']}
# The 3rd is planned only in part: who plays first and third.
INNING_3 = {'1B': INNING_1['1B'], '3B': INNING_1['3B']}
DEFAULT_PLAN = {'1': INNING_1, '2': INNING_2, '3': INNING_3}


@pytest.fixture
def live(browser, coachboard_url):
    """`live(device, plan=None)`: a started live game and a logged-in page
    for `device` -- (name, viewport, context options), e.g. PHONE."""
    made = []

    def _open(device, plan=None):
        setup = browser.new_context()
        cdn_assets.install(setup)
        api = setup.new_page()
        live_field_markers.login(api, coachboard_url)
        game_id, player_ids = create_named_live_game(api, coachboard_url, innings=plan or DEFAULT_PLAN)
        made.append((setup, api, game_id, player_ids))

        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        made[-1] += (context,)
        page = context.new_page()
        errors, writes = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: writes.append(request.url)
                if request.method != 'GET' and '/api/live-game/' in request.url else None)
        page.cb_errors, page.cb_writes = errors, writes
        live_field_markers.login(page, coachboard_url)
        page.cb_api, page.cb_game = api, game_id
        return page

    yield _open
    for setup, api, game_id, player_ids, *contexts in made:
        for context in contexts:
            context.close()
        remove_named_live_game(api, coachboard_url, game_id, player_ids)
        setup.close()


def api_url(page, base_url, path):
    return f'{base_url}/api/live-game/{page.cb_game}/{path}'


def game_state(page, base_url):
    return page.cb_api.request.get(api_url(page, base_url, 'state')).json()


def edit_live_defense(page, base_url, **changes):
    """A live defensive change: position -> player ('' leaves it open)."""
    state = game_state(page, base_url)
    alignment = {pos: name for pos, name in state['current_alignment'].items() if name}
    for pos, name in changes.items():
        if name:
            alignment[pos] = name
        else:
            alignment.pop(pos, None)
    response = page.cb_api.request.post(api_url(page, base_url, 'defense-edit'), data={
        'base_sequence': last_sequence(state), 'alignment': alignment})
    assert response.ok, response.text()[:300]


def set_next_inning(page, base_url, alignment):
    response = page.cb_api.request.post(api_url(page, base_url, 'next-inning-prep'),
                                        data={'mode': 'custom', 'alignment': alignment})
    assert response.ok, response.text()[:300]


def advance_inning(page, base_url):
    prep = page.cb_api.request.get(api_url(page, base_url, 'next-inning-prep')).json()
    response = page.cb_api.request.post(api_url(page, base_url, 'advance-inning'), data={
        'alignment': prep['confirmed']['alignment'], 'next_prep_id': prep['confirmed']['id'],
        'base_sequence': last_sequence(game_state(page, base_url))})
    assert response.ok, response.text()[:300]


# ------------------------------------ `live_field`: BASE plus RELIEVER


LIVE_FIELD_VIEWPORT = {'width': 430, 'height': 932}


@pytest.fixture
def live_field(page: Page, coachboard_url: str):
    page.set_viewport_size(LIVE_FIELD_VIEWPORT)
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


# ------------------------------------------ the Next Inning planner


NEXT_BOARD_VIEWPORT = {'width': 390, 'height': 844}
PLANNER = '#live-board-prep-v3'
PREP_URL = re.compile(r'/api/live-game/\d+/next-inning-prep$')

# Every tap must show on the board well inside one slow round trip.
IMMEDIATE_MS = 400


PLAN_NEXT_INNING = '#cb-now-next-switch [data-now-next="next"]'
END_INNING = '#liveEndInningBtn'


def open_next_inning_planner(page: Page):
    """Tap "Plan next inning" on the live screen."""
    expect(page.locator('#cb-now-next-switch')).to_be_visible(
        timeout=15_000
    )
    page.locator(PLAN_NEXT_INNING).click()


def return_to_live_field(page: Page):
    """Leave the full-screen planner the way a coach does ("Live Field").
    Nothing waits for a save: what is saving keeps saving."""
    page.locator(f'{PLANNER} [data-next-close]').click()
    expect(page.locator(PLANNER)).to_be_hidden(timeout=10_000)


def end_inning_from_live(page: Page):
    """End Inning is on the live field: go back there first if planning."""
    if page.locator(PLANNER).is_visible():
        return_to_live_field(page)
    page.locator(END_INNING).click()


def plan_undo(page: Page):
    """The planner's own Undo (Plan Undo), not the live game's."""
    page.locator(f'{PLANNER} [data-next-undo-local]').click()


def _create_next_board_game(page: Page, url: str):
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
    post_json(page, url, f'/api/live-game/{game_id}/start', start_body(page.request, url, game_id))
    return game_id


@pytest.fixture
def next_board(page: Page, coachboard_url: str, browser_name: str):
    if browser_name != 'chromium':
        pytest.skip('CDP network emulation is Chromium-only.')

    page.set_viewport_size(NEXT_BOARD_VIEWPORT)
    login(page, coachboard_url)
    game_id = _create_next_board_game(page, coachboard_url)
    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )
        open_next_inning_planner(page)
        board = page.locator(PLANNER)
        expect(spot(board, 'SS')).to_contain_text(
            'Shortstop Shawn', timeout=10_000
        )
        yield board, game_id
    finally:
        page.context.set_offline(False)
        cleanup_game(page, coachboard_url, game_id)


def spot(board, position):
    return board.locator(f'[data-next-position="{position}"]')


def bench(board, position):
    spot(board, position).click()
    board.locator('[data-next-bench-selected]').click()
    expect(spot(board, position)).to_have_attribute(
        'data-next-player', '', timeout=IMMEDIATE_MS
    )


def board_alignment(page: Page):
    return filled(page.evaluate('() => window.CBNextDefense.getAlignment()'))


def server_next(page: Page, url: str, game_id: int):
    response = page.request.get(
        f'{url}/api/live-game/{game_id}/next-inning-prep'
    )
    assert response.ok, response.text()[:300]
    return filled(response.json()['confirmed']['alignment'])


def wait_for_server(page, url, game_id, expected, timeout_s=15):
    deadline = timeout_s * 1000
    waited = 0
    while waited < deadline:
        if server_next(page, url, game_id) == expected:
            return
        page.wait_for_timeout(200)
        waited += 200
    assert server_next(page, url, game_id) == expected


def other_coach_sets(page: Page, url: str, game_id: int, alignment):
    """Another coach's device: a plain save that does not know this board."""
    post_json(
        page, url,
        f'/api/live-game/{game_id}/next-inning-prep',
        {'mode': 'custom', 'alignment': alignment},
    )


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


# ------------------------------------------------------- slow network


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
