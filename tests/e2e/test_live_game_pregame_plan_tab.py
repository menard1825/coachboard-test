"""Browser coverage for the read-only Pregame Plan tab in Live Game.

The tab exists so a coach can glance back at the defense they wrote before
first pitch. Two properties matter more than the rendering itself: it must
never write anything, and moving through it must leave On the Field and Next
Inning exactly as they were -- a coach who taps Pregame mid-substitution and
taps back has to find their work still there.
"""

import json
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


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

PLAN_CARD = '#live-board-pregame-plan'
NEXT_CARD = '#live-board-prep-v3'
SWITCHER = '#cb-now-next-switch'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(
        re.compile(
            rf'^{re.escape(coachboard_url)}/?'
            rf'(?:#(?:games|overview))?$'
        )
    )


def post_json(page: Page, coachboard_url: str, path: str, data, expected_status=200):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == expected_status, (
        f'POST {path} returned {response.status}: {response.text()}'
    )
    payload = response.json()
    if expected_status < 400:
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


def inning_two_alignment():
    value = alignment()
    value['P'] = 'Second Sam'
    value['2B'] = 'Pitcher Pat'
    return value


def inning_three_alignment():
    value = alignment()
    value['RF'] = 'Left Lee'
    value['LF'] = 'Right Riley'
    return value


def create_game(page: Page, coachboard_url: str):
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=12)).isoformat(),
            'game_start_time': '16:00',
            'game_opponent': 'Pregame Plan Opponent',
            'game_location': 'Pregame Plan Field',
            'game_notes': 'Disposable Pregame Plan browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )

    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(
        page,
        coachboard_url,
        '/save_rotation',
        {
            'title': 'Pregame Plan Rotation',
            'innings': {
                '1': alignment(),
                '2': inning_two_alignment(),
                '3': inning_three_alignment(),
            },
            'associated_game_id': game_id,
        },
    )

    return game_id


def get_prep(page: Page, coachboard_url: str, game_id: int):
    response = page.request.get(
        f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep'
    )
    assert response.ok, response.text()
    return response.json()


def open_live_game(page: Page, coachboard_url: str, game_id: int):
    post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
    page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
    expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
    expect(page.locator(SWITCHER)).to_be_visible(timeout=15_000)


def cleanup_game(page: Page, coachboard_url: str, game_id: int):
    """End and delete the game this test started.

    Every test in this file puts a game live, and one live game anywhere on
    the team locks the roster for the whole session: roster.py add_player
    checks _active_live_game_for_team() before it checks X-Requested-With, so
    it answers AJAX callers with a redirect to the home page instead of JSON.
    A game left live here therefore breaks unrelated tests that add players.
    """
    state = page.request.get(
        f'{coachboard_url}/api/live-game/{game_id}/state'
    )

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


def tab(page: Page, name: str):
    return page.locator(SWITCHER).locator(f'[data-now-next="{name}"]')


def test_pregame_plan_tab_renders_every_planned_inning(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 430, 'height': 932})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_live_game(page, coachboard_url, game_id)

        expect(tab(page, 'plan')).to_have_text('Pregame Plan')
        tab(page, 'plan').click()

        plan = page.locator(PLAN_CARD)
        expect(plan).to_be_visible(timeout=10_000)
        expect(plan).to_contain_text('Pregame Defense')
        expect(plan).to_contain_text('Reference only')

        innings = plan.locator('.cb-plan-inning')
        expect(innings).to_have_count(3)
        expect(innings.nth(0)).to_contain_text('Inning 1')
        expect(innings.nth(1)).to_contain_text('Inning 2')
        expect(innings.nth(2)).to_contain_text('Inning 3')

        # The plan as written, not the live alignment: inning 2 planned
        # Second Sam on the mound and Pitcher Pat at second.
        expect(innings.nth(1)).to_contain_text('Second Sam')
        expect(innings.nth(1)).to_contain_text('Pitcher Pat')

        # The inning actually being played is called out.
        expect(innings.nth(0)).to_contain_text('On now')
        expect(innings.nth(1)).not_to_contain_text('On now')
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_pregame_plan_tab_offers_no_way_to_edit(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 430, 'height': 932})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_live_game(page, coachboard_url, game_id)
        tab(page, 'plan').click()

        plan = page.locator(PLAN_CARD)
        expect(plan).to_be_visible(timeout=10_000)

        for selector in (
            'button',
            'input',
            'select',
            'textarea',
            '[contenteditable="true"]',
            '[data-next-position]',
            '[data-next-player]',
            '[data-pde-pos]',
        ):
            expect(plan.locator(selector)).to_have_count(0)

        # The live Undo control cannot act while a reference view is open.
        expect(page.locator('#liveUndoBtn')).to_be_disabled()
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_visiting_pregame_plan_leaves_the_other_boards_untouched(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 430, 'height': 932})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_live_game(page, coachboard_url, game_id)

        # Settle the prep row first, so the comparison below is not just
        # picking up the row this endpoint creates on its own first read.
        get_prep(page, coachboard_url, game_id)

        tab(page, 'next').click()
        next_board = page.locator(NEXT_CARD)
        expect(next_board).to_be_visible(timeout=10_000)
        next_before = next_board.inner_html()

        tab(page, 'now').click()
        field_board = page.locator('#cbQuickDefense')
        expect(field_board).to_be_visible(timeout=10_000)
        field_before = field_board.inner_html()

        prep_before = get_prep(page, coachboard_url, game_id)

        tab(page, 'plan').click()
        expect(page.locator(PLAN_CARD)).to_be_visible(timeout=10_000)
        expect(field_board).to_be_hidden()
        expect(next_board).to_be_hidden()

        tab(page, 'now').click()
        expect(field_board).to_be_visible(timeout=10_000)
        assert field_board.inner_html() == field_before, (
            'On the Field changed after a visit to Pregame Plan'
        )

        tab(page, 'next').click()
        expect(next_board).to_be_visible(timeout=10_000)
        assert next_board.inner_html() == next_before, (
            'Next Inning changed after a visit to Pregame Plan'
        )

        # Viewing a reference tab must not have written anything.
        prep_after = get_prep(page, coachboard_url, game_id)
        assert prep_after['confirmed'] == prep_before['confirmed']
        assert prep_after['pregame_rotation'] == prep_before['pregame_rotation']
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_pregame_plan_tab_shows_an_empty_state_without_a_saved_plan(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 430, 'height': 932})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})

    # A live game always needs a startable inning 1, so the no-plan case is
    # reached by serving a real response with the plan emptied out rather
    # than by trying to start a game that has nothing to start with.
    def strip_plan(route):
        response = route.fetch()
        payload = response.json()
        payload['pregame_rotation'] = {}
        route.fulfill(response=response, body=json.dumps(payload))

    page.route('**/next-inning-prep', strip_plan)

    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
        expect(page.locator(SWITCHER)).to_be_visible(timeout=15_000)

        tab(page, 'plan').click()

        plan = page.locator(PLAN_CARD)
        expect(plan).to_be_visible(timeout=10_000)
        expect(plan).to_contain_text(
            'No pregame defensive plan was saved for this game.'
        )
        expect(plan.locator('.cb-plan-inning')).to_have_count(0)
    finally:
        page.unroute('**/next-inning-prep')
        cleanup_game(page, coachboard_url, game_id)


def test_three_tab_switcher_fits_a_phone_without_clipping(page: Page, coachboard_url: str):
    """A third labelled tab makes the switcher much tighter than the two it
    replaced, and "Pregame Plan" is the longest of the three. Measured in the
    real browser rather than trusting the arithmetic."""
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_live_game(page, coachboard_url, game_id)

        for name in ('now', 'next', 'plan'):
            expect(tab(page, name)).to_be_visible()

        measurements = page.locator(SWITCHER).evaluate(
            """
            (switcher) => {
                const doc = document.documentElement;
                return {
                    horizontalOverflow: doc.scrollWidth > doc.clientWidth,
                    buttons: [...switcher.querySelectorAll('[data-now-next]')].map((button) => {
                        const range = document.createRange();
                        range.selectNodeContents(button);
                        return {
                            label: button.textContent.trim(),
                            lineCount: range.getClientRects().length,
                            overflows: button.scrollWidth > button.clientWidth + 1,
                            height: Math.round(button.getBoundingClientRect().height),
                        };
                    }),
                };
            }
            """
        )

        labels = [button['label'] for button in measurements['buttons']]
        assert labels == ['On the Field', 'Next Inning', 'Pregame Plan'], labels

        for button in measurements['buttons']:
            assert button['lineCount'] == 1, (
                f"{button['label']!r} wrapped onto {button['lineCount']} lines at 390px"
            )
            assert not button['overflows'], (
                f"{button['label']!r} overflows its button at 390px"
            )
            assert button['height'] >= 42, (
                f"{button['label']!r} tap target shrank to {button['height']}px"
            )

        assert not measurements['horizontalOverflow'], (
            'the switcher pushed the page into horizontal scrolling at 390px'
        )
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_on_the_field_and_next_inning_still_work_alongside_the_new_tab(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 430, 'height': 932})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_live_game(page, coachboard_url, game_id)

        expect(page.locator(SWITCHER).locator('[data-now-next]')).to_have_count(3)

        expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=10_000)

        tab(page, 'next').click()
        next_board = page.locator(NEXT_CARD)
        expect(next_board).to_be_visible(timeout=10_000)
        expect(next_board).to_contain_text('NEXT INNING · 2')
        expect(page.locator(PLAN_CARD)).to_be_hidden()

        tab(page, 'now').click()
        expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=10_000)
        expect(next_board).to_be_hidden()
        expect(page.locator(PLAN_CARD)).to_be_hidden()
    finally:
        cleanup_game(page, coachboard_url, game_id)
