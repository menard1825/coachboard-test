"""Undo belongs in the dark Dugout header, not in a row of its own.

live_game_command_center.js used to park #liveUndoBtn inside .coach-live-head,
which live_game_dugout_mode.js hides in Dugout Mode. The only way the button
stayed reachable was gameday_pitching_steppers.js re-showing that head with a
higher-specificity rule -- so a 46px row plus margin sat between the dark
header and the On the Field / Next Inning / Pregame Plan tabs carrying nothing
but one circular control. On a 1024x768 tablet that row is the difference
between End Inning being on screen and being below the fold.
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


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

HEADER = '#cbDugoutHeader'
UNDO = '#liveUndoBtn'


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
            'game_date': (date.today() + timedelta(days=9)).isoformat(),
            'game_start_time': '13:00',
            'game_opponent': opponent,
            'game_location': 'Header Undo Field',
            'game_notes': 'Disposable header-undo browser test',
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
        'title': 'Header Undo Lineup',
        'lineup_player_ids': [int(player['id']) for player in roster],
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Header Undo Rotation',
        'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
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
    expect(page.locator(HEADER)).to_be_visible(timeout=15_000)
    expect(page.locator('#cb-now-next-switch')).to_be_visible(timeout=15_000)


def test_undo_sits_in_the_dark_header_and_costs_no_row(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Header Undo Placement')

    try:
        open_live_game(page, coachboard_url, game_id)

        undo = page.locator(UNDO)

        # Exactly one Undo, and it is the header's.
        expect(undo).to_have_count(1)
        expect(undo).to_be_visible()
        expect(page.locator(f'{HEADER} {UNDO}')).to_have_count(1)

        # The row that existed only to hold it is gone again.
        head = page.locator('.coach-live-head')
        if head.count():
            expect(head.first).to_be_hidden()

        # ...and nothing sits between the dark header and the tabs.
        gap = page.evaluate(
            """() => {
              const header = document.querySelector('#cbDugoutHeader');
              const tabs = document.querySelector('#cb-now-next-switch');
              return Math.round(
                tabs.getBoundingClientRect().top
                - header.getBoundingClientRect().bottom
              );
            }"""
        )
        assert 0 <= gap <= 24, (
            f'{gap}px between the dark header and the tabs; a control row '
            f'would put roughly 54px there'
        )
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_header_undo_keeps_its_label_and_a_tappable_target(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Header Undo Affordance')

    try:
        open_live_game(page, coachboard_url, game_id)

        undo = page.locator(UNDO)
        expect(undo).to_have_attribute('aria-label', 'Undo last change')
        expect(undo).to_have_attribute(
            'title', 'Undo the last live-game change'
        )

        # The old icon was a circular arrow, which reads as refresh. The
        # control now says what it does.
        expect(undo).to_contain_text('Undo')
        assert page.evaluate(
            """() => !!document.querySelector(
                 '#liveUndoBtn i.bi-arrow-counterclockwise'
               )"""
        ) is False, 'Undo is still using the refresh-looking circular arrow'

        box = undo.bounding_box()
        assert box and box['width'] >= 40 and box['height'] >= 40, (
            f'Undo touch target collapsed to {box}'
        )
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_phone_header_still_shows_undo_without_a_row(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Header Undo Phone')

    try:
        open_live_game(page, coachboard_url, game_id)

        undo = page.locator(UNDO)
        expect(undo).to_have_count(1)
        expect(undo).to_be_visible()
        expect(page.locator(f'{HEADER} {UNDO}')).to_have_count(1)

        box = undo.bounding_box()
        assert box and box['width'] >= 40 and box['height'] >= 40, (
            f'phone Undo touch target collapsed to {box}'
        )

        # The header is the widest thing on a phone; adding a control to it
        # must not push the page sideways.
        assert page.evaluate(
            'document.documentElement.scrollWidth'
            ' <= document.documentElement.clientWidth + 2'
        )

        # Reproduce the real-device case that exposed the old seven-column
        # phone layout: a long paused elapsed clock beside a numbered,
        # two-word pitcher name.
        page.evaluate(
            '''() => {
              document.querySelector('[data-cb-clock-label]').textContent =
                'Paused · Elapsed';
              document.querySelector('[data-cb-clock-time]').textContent =
                '51:54:05';
              document.querySelector('[data-cb-pitcher]').textContent =
                '#7 Jack Fordice';
            }'''
        )
        page.wait_for_timeout(50)

        geometry = page.evaluate(
            '''() => {
              const time = document
                .querySelector('[data-cb-clock-time]')
                .getBoundingClientRect();
              const pitcher = document
                .querySelector('.cb-dh-pitcher')
                .getBoundingClientRect();
              const name = document
                .querySelector('[data-cb-pitcher]')
                .getBoundingClientRect();
              const undo = document
                .querySelector('#cbDugoutHeader #liveUndoBtn')
                .getBoundingClientRect();

              return {
                timeRight: time.right,
                pitcherLeft: pitcher.left,
                nameRight: name.right,
                undoLeft: undo.left,
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
              };
            }'''
        )

        assert geometry['timeRight'] <= geometry['pitcherLeft'] + 1, (
            f'clock overlaps pitcher on phone: {geometry}'
        )
        assert geometry['nameRight'] <= geometry['undoLeft'] + 1, (
            f'pitcher overlaps Undo on phone: {geometry}'
        )
        assert geometry['scrollWidth'] <= geometry['clientWidth'] + 2, (
            f'long header content pushes page sideways: {geometry}'
        )
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_header_undo_still_undoes_and_still_disables(page: Page, coachboard_url: str):
    """Moving the element must not change what it does.

    The /undo handler in live_game_v2 is delegated from document, and
    live_game_board_prep_v2 toggles `disabled` by id, so both should survive
    the reparent -- this proves it rather than assuming it.
    """
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Header Undo Behaviour')

    try:
        open_live_game(page, coachboard_url, game_id)

        before = page.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        ).json()['current_alignment']

        # A real defensive change through Quick Field: LF and RF swap. This
        # needs nothing but the nine fielders, so it does not depend on what
        # else is on the shared test roster.
        page.locator('#cbQuickDefense [data-cb-position="LF"]').click()
        modal = page.locator('#cbQuickMoveModal')
        expect(modal).to_be_visible(timeout=10_000)
        modal.locator('[data-cb-destination="RF"]').click()
        expect(modal).to_be_hidden(timeout=15_000)

        expect(
            page.locator('#cbQuickDefense [data-cb-position="RF"]')
        ).to_contain_text('Left Lee', timeout=15_000)

        undo = page.locator(UNDO)
        expect(undo).to_be_enabled()
        undo.click()

        expect(
            page.locator('#cbQuickDefense [data-cb-position="LF"]')
        ).to_contain_text('Left Lee', timeout=15_000)

        after = page.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        ).json()['current_alignment']
        assert after == before, (
            f'undo did not restore the alignment: {before} -> {after}'
        )

        # Pregame Plan is reference only, so the header Undo has to go dead
        # there exactly as it did in its old home.
        page.locator('#cb-now-next-switch [data-now-next="plan"]').click()
        expect(page.locator('#live-board-pregame-plan')).to_be_visible(
            timeout=10_000
        )
        expect(undo).to_be_disabled()

        page.locator('#cb-now-next-switch [data-now-next="now"]').click()
        expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=10_000)
        expect(undo).to_be_enabled()
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_portrait_tablet_header_stays_one_row(page: Page, coachboard_url: str):
    """Adding a control to .cb-dh-main must not wrap the header.

    live_game_sync_status.js compacts the header between 576px and 899.98px by
    hiding .cb-dh-live and pinning an explicit grid-template-columns. That
    column count has to account for the Undo slot: leaving it at the old width
    puts six items in five columns, the header wraps onto a second row, and a
    768x1024 iPad loses ~46px off the top of the live workspace -- the exact
    mistake this guards.
    """
    page.set_viewport_size({'width': 768, 'height': 1024})
    login(page, coachboard_url)
    game_id = create_live_game(page, coachboard_url, 'Header Undo Portrait')

    try:
        open_live_game(page, coachboard_url, game_id)

        undo = page.locator(UNDO)
        expect(undo).to_have_count(1)
        expect(undo).to_be_visible()
        expect(page.locator(f'{HEADER} {UNDO}')).to_have_count(1)

        # Ask the grid how many rows it actually resolved to. Comparing item
        # tops does not work here: .cb-dh-main centres items of differing
        # heights, so a single row legitimately yields several distinct tops.
        rows = page.evaluate(
            """() => {
              const main = document.querySelector('#cbDugoutHeader .cb-dh-main');
              const tracks = getComputedStyle(main).gridTemplateRows;
              return {
                rowTracks: tracks,
                rowCount: tracks.trim().split(/\s+/).filter(Boolean).length,
                headerHeight: Math.round(
                  document.querySelector('#cbDugoutHeader')
                    .getBoundingClientRect().height
                ),
              };
            }"""
        )

        assert rows['rowCount'] == 1, (
            f"header wrapped onto {rows['rowCount']} rows "
            f"(grid-template-rows: {rows['rowTracks']}); the grid is short "
            f"a column"
        )

        # A wrapped header roughly doubles: ~61px becomes ~107px.
        assert rows['headerHeight'] <= 80, (
            f"header is {rows['headerHeight']}px tall at 768x1024; "
            f"a single row is about 61px"
        )

        assert page.evaluate(
            'document.documentElement.scrollWidth'
            ' <= document.documentElement.clientWidth + 2'
        )
    finally:
        cleanup_game(page, coachboard_url, game_id)
