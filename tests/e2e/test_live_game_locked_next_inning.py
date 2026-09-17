"""Browser coverage for the Live Game NOW/NEXT first slice."""

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


def post_json(
    page: Page,
    coachboard_url: str,
    path: str,
    data,
    expected_status=200,
):
    response = page.request.post(
        f'{coachboard_url}{path}',
        data=data,
    )

    assert response.status == expected_status, (
        f'POST {path} returned '
        f'{response.status}: {response.text()}'
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

    # Planned pitcher is intentionally different from Inning 1.
    value['P'] = 'Second Sam'
    value['2B'] = 'Pitcher Pat'

    return value


def create_game(page: Page, coachboard_url: str):
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date':
                (date.today() + timedelta(days=11)).isoformat(),
            'game_start_time': '16:00',
            'game_opponent': 'NOW NEXT Opponent',
            'game_location': 'NOW NEXT Test Field',
            'game_notes': 'Disposable NOW NEXT browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )

    assert response.status in {302, 303}

    match = re.search(
        r'/game/(\d+)',
        response.headers.get('location') or '',
    )

    assert match
    game_id = int(match.group(1))

    post_json(
        page,
        coachboard_url,
        '/save_rotation',
        {
            'title': 'NOW NEXT Rotation',
            'innings': {
                '1': alignment(),
                '2': inning_two_alignment(),
                '3': alignment(),
            },
            'associated_game_id': game_id,
        },
    )

    return game_id



def drag(page: Page, source, target):
    source_box = source.bounding_box()
    target_box = target.bounding_box()

    assert source_box and target_box

    page.mouse.move(
        source_box['x'] + source_box['width'] / 2,
        source_box['y'] + source_box['height'] / 2,
    )
    page.mouse.down()
    page.mouse.move(
        target_box['x'] + target_box['width'] / 2,
        target_box['y'] + target_box['height'] / 2,
        steps=12,
    )
    page.mouse.up()

def get_prep(page: Page, coachboard_url: str, game_id: int):
    response = page.request.get(
        f'{coachboard_url}/api/live-game/'
        f'{game_id}/next-inning-prep'
    )

    assert response.ok, response.text()
    return response.json()


def nonblank(alignment_value):
    return {
        key: value
        for key, value in alignment_value.items()
        if value
    }



def test_next_inning_supports_drag_and_drop(
    page: Page,
    coachboard_url: str,
):
    page.set_viewport_size(
        {
            'width': 430,
            'height': 932,
        }
    )

    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        post_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/start',
            {},
        )

        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        switcher = page.locator('#cb-now-next-switch')

        expect(
            switcher
        ).to_be_visible(
            timeout=15_000
        )

        switcher.locator(
            '[data-now-next="next"]'
        ).click()

        next_board = page.locator(
            '#live-board-prep-v3'
        )

        expect(
            next_board
        ).to_be_visible(
            timeout=10_000
        )

        catcher = next_board.locator(
            '[data-next-position="C"]'
        )

        first_base = next_board.locator(
            '[data-next-position="1B"]'
        )

        expect(catcher).to_contain_text('Catcher Cole')
        expect(first_base).to_contain_text('First Frank')

        # Dragging must perform the same authoritative NEXT move as
        # the existing tap-source / tap-destination workflow.
        drag(
            page,
            catcher,
            first_base,
        )

        expect(
            first_base
        ).to_contain_text(
            'Catcher Cole',
            timeout=10_000,
        )

        expect(
            catcher
        ).to_contain_text(
            'First Frank',
            timeout=10_000,
        )

        save_chip = next_board.locator(
            '.cb-next-save'
        )

        expect(
            save_chip
        ).to_have_class(
            re.compile(r'\bsaved\b'),
            timeout=10_000,
        )

        expect(
            save_chip
        ).to_contain_text(
            'Catcher Cole',
            timeout=10_000,
        )

        expect(
            save_chip
        ).to_contain_text(
            '→ 1B',
            timeout=10_000,
        )

        prep = get_prep(
            page,
            coachboard_url,
            game_id,
        )

        assert (
            prep['confirmed']['alignment']['1B']
            == 'Catcher Cole'
        )

        assert (
            prep['confirmed']['alignment']['C']
            == 'First Frank'
        )

    finally:
        state_response = page.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
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
            f'{coachboard_url}/game-day/{game_id}/delete',
            headers={'Accept': 'application/json'},
        )


def test_now_next_first_slice(
    page: Page,
    coachboard_url: str,
):
    page.set_viewport_size(
        {
            'width': 430,
            'height': 932,
        }
    )

    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        started = post_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/start',
            {},
        )

        assert (
            started['state']['current_alignment']['P']
            == 'Pitcher Pat'
        )

        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        expect(
            page.locator('#live-game-overlay')
        ).to_be_visible(
            timeout=15_000
        )

        switcher = page.locator(
            '#cb-now-next-switch'
        )

        expect(
            switcher
        ).to_be_visible(
            timeout=15_000
        )

        # Live Game must not load the pitch-count workload UI.
        expect(
            page.locator(
                'script[src*="live_game_pitching_workload.js"]'
            )
        ).to_have_count(0)

        switcher.locator(
            '[data-now-next="next"]'
        ).click()

        next_board = page.locator(
            '#live-board-prep-v3'
        )

        expect(
            next_board
        ).to_be_visible(
            timeout=10_000
        )

        expect(
            next_board.locator(
                '[data-next-position="P"]'
            )
        ).to_contain_text(
            'Second Sam'
        )

        expect(
            next_board.locator(
                '[data-next-position="2B"]'
            )
        ).to_contain_text(
            'Pitcher Pat'
        )

        prep = get_prep(
            page,
            coachboard_url,
            game_id,
        )

        assert (
            prep['confirmed']['source']
            == 'planned'
        )

        assert (
            prep['confirmed']['alignment']['P']
            == 'Second Sam'
        )

        # Use Current Defense is the optional one-tap shortcut.
        next_board.get_by_role(
            'button',
            name='Use current defense',
        ).click()

        expect(
            next_board.locator(
                '.cb-next-save'
            )
        ).to_contain_text(
            'Current defense copied',
            timeout=10_000,
        )

        prep = get_prep(
            page,
            coachboard_url,
            game_id,
        )

        assert (
            prep['confirmed']['alignment']['P']
            == 'Pitcher Pat'
        )

        # Undo restores the NEXT plan that existed before the copy.
        expect(
            next_board.get_by_role(
                'button',
                name='Undo NEXT change',
            )
        ).to_have_count(0)

        undo = page.locator(
            '#liveUndoBtn'
        )

        expect(
            undo
        ).to_be_visible()

        expect(
            undo
        ).to_be_enabled()

        undo.click()

        expect(
            next_board.locator(
                '.cb-next-save'
            )
        ).to_contain_text(
            'NEXT restored',
            timeout=10_000,
        )

        prep = get_prep(
            page,
            coachboard_url,
            game_id,
        )

        assert (
            prep['confirmed']['alignment']['P']
            == 'Second Sam'
        )

        assert (
            prep['confirmed']['alignment']['2B']
            == 'Pitcher Pat'
        )

        # Two ordinary non-pitcher swaps on NEXT.
        next_board.locator(
            '[data-next-position="C"]'
        ).click()

        next_board.locator(
            '[data-next-position="1B"]'
        ).click()

        expect(
            next_board.locator(
                '.cb-next-save'
            )
        ).to_contain_text(
            '→ 1B',
            timeout=10_000,
        )

        next_board.locator(
            '[data-next-position="3B"]'
        ).click()

        next_board.locator(
            '[data-next-position="SS"]'
        ).click()

        expect(
            next_board.locator(
                '.cb-next-save'
            )
        ).to_contain_text(
            '→ SS',
            timeout=10_000,
        )

        prep = get_prep(
            page,
            coachboard_url,
            game_id,
        )

        assert (
            prep['confirmed']['alignment']['C']
            == 'First Frank'
        )

        assert (
            prep['confirmed']['alignment']['1B']
            == 'Catcher Cole'
        )

        assert (
            prep['confirmed']['alignment']['3B']
            == 'Shortstop Shawn'
        )

        assert (
            prep['confirmed']['alignment']['SS']
            == 'Third Theo'
        )

        # OPEN non-pitcher spots are allowed.
        next_board.locator(
            '[data-next-position="RF"]'
        ).click()

        next_board.locator(
            '[data-next-bench-selected]'
        ).click()

        expect(
            next_board.locator(
                '[data-next-position="RF"]'
            )
        ).to_contain_text(
            'OPEN',
            timeout=10_000,
        )

        expect(
            next_board.locator(
                '.cb-next-warnings'
            )
        ).to_contain_text(
            'RF is open'
        )

        prep = get_prep(
            page,
            coachboard_url,
            game_id,
        )

        assert (
            prep['confirmed']['alignment']['RF']
            == ''
        )

        # P is the one NEXT position that may not be empty
        # when End Inning is pressed.
        next_board.locator(
            '[data-next-position="P"]'
        ).click()

        next_board.locator(
            '[data-next-bench-selected]'
        ).click()

        expect(
            next_board.locator(
                '[data-next-position="P"]'
            )
        ).to_contain_text(
            'OPEN',
            timeout=10_000,
        )

        expect(
            next_board.locator(
                '.cb-next-warnings'
            )
        ).to_contain_text(
            'Set a pitcher for the next inning'
        )

        page.locator(
            '#liveEndInningBtn'
        ).click()

        expect(
            page.locator(
                '#live-inning-display'
            )
        ).to_have_text(
            '1'
        )

        expect(
            next_board.locator(
                '.cb-next-error'
            )
        ).to_contain_text(
            'Set a pitcher for the next inning',
            timeout=10_000,
        )

        # Restore the pitcher, leaving RF intentionally OPEN.
        undo = page.locator(
            '#liveUndoBtn'
        )

        expect(
            undo
        ).to_be_visible()

        expect(
            undo
        ).to_be_enabled()

        undo.click()

        expect(
            next_board.locator(
                '[data-next-position="P"]'
            )
        ).to_contain_text(
            'Second Sam',
            timeout=10_000,
        )

        ready_prep = get_prep(
            page,
            coachboard_url,
            game_id,
        )

        expected_now = nonblank(
            ready_prep['confirmed']['alignment']
        )

        assert 'RF' not in expected_now
        assert expected_now['P'] == 'Second Sam'

        # One tap. No huddle. NEXT becomes NOW.
        page.locator(
            '#liveEndInningBtn'
        ).click()

        expect(
            page.locator(
                '#cb-test2-huddle-modal'
            )
        ).to_have_count(0)

        expect(
            page.locator(
                '#live-inning-display'
            )
        ).to_have_text(
            '2',
            timeout=10_000,
        )

        state = page.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/state'
        ).json()

        assert state['current_inning'] == '2'
        assert state['current_alignment'] == expected_now

        # Inning 3 NEXT is immediately seeded from the plan.
        prep_three = get_prep(
            page,
            coachboard_url,
            game_id,
        )

        assert prep_three['current_inning'] == '2'
        assert prep_three['next_inning'] == '3'

        assert (
            prep_three['confirmed']['source']
            == 'planned'
        )

        assert (
            nonblank(
                prep_three['confirmed']['alignment']
            )
            == alignment()
        )

        # End Game is not a pitch-entry workflow.
        end_game = page.locator(
            '#liveEndGameBtn'
        )

        expect(
            end_game
        ).to_be_visible()

        assert (
            'Pitch'
            not in end_game.inner_text()
        )

        assert (
            page.locator(
                '#liveFinalCountsModal.show'
            ).count()
            == 0
        )

        dialogs = []

        def accept_end_game(dialog):
            dialogs.append(dialog.message)
            dialog.accept()

        page.once(
            'dialog',
            accept_end_game,
        )

        end_game.click()

        expect(
            page
        ).to_have_url(
            re.compile(
                rf'^{re.escape(coachboard_url)}'
                rf'/game-day/{game_id}/report$'
            ),
            timeout=10_000,
        )

        assert dialogs
        assert (
            'paste GameChanger pitching stats later'
            in dialogs[0]
        )

    finally:
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
