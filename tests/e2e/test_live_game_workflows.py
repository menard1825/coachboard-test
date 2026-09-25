"""Game Day, planning, Live Game, clock, postgame, and safety coverage."""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect

from e2e_cleanup import release_game


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
ASSISTANT_USERNAME = 'playwright-assistant'
ASSISTANT_PASSWORD = 'playwright-assistant-password'


def login(
    page: Page,
    coachboard_url: str,
    username=TEST_USERNAME,
    password=TEST_PASSWORD,
):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(username)
    page.locator('#password').fill(password)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:games|overview))?$'))


def post_json(page: Page, coachboard_url: str, path: str, data, expected_status=200):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == expected_status, f'POST {path} returned {response.status}: {response.text()}'
    payload = response.json()
    if expected_status < 400:
        assert payload.get('status') == 'success', f'POST {path} failed: {payload}'
    return payload


def get_json(page: Page, coachboard_url: str, path: str, expected_status=200):
    response = page.request.get(f'{coachboard_url}{path}')
    assert response.status == expected_status, f'GET {path} returned {response.status}: {response.text()}'
    return response.json()


def delete_json(page: Page, coachboard_url: str, path: str, expected_status=200):
    response = page.request.fetch(f'{coachboard_url}{path}', method='DELETE')
    assert response.status == expected_status, f'DELETE {path} returned {response.status}: {response.text()}'
    return response.json()


def post_form(page: Page, coachboard_url: str, path: str, form):
    response = page.request.post(f'{coachboard_url}{path}', form=form, max_redirects=0)
    assert response.status in {302, 303}, f'POST {path} returned {response.status}: {response.text()}'
    return response


def assert_player_names_are_fully_visible(locator):
    """Player labels may wrap, but they may never be ellipsized or clipped."""
    expect(locator).not_to_have_count(0)
    samples = locator.evaluate_all(
        """items => items.map(el => {
            const s = getComputedStyle(el);
            const before = getComputedStyle(el, '::before');
            return {
                text: (el.textContent || '').trim(),
                whiteSpace: s.whiteSpace,
                overflow: s.overflow,
                textOverflow: s.textOverflow,
                scrollWidth: el.scrollWidth,
                clientWidth: el.clientWidth,
                scrollHeight: el.scrollHeight,
                clientHeight: el.clientHeight,
                hasNumber: el.hasAttribute('data-cb-number'),
                numberDisplay: before.display,
            };
        })"""
    )
    for sample in samples:
        if not sample['text'] or sample['text'].lower() in {'open', 'tbd'}:
            continue
        assert sample['whiteSpace'] == 'normal', sample
        assert sample['overflow'] == 'visible', sample
        assert sample['textOverflow'] == 'clip', sample
        assert sample['scrollWidth'] <= sample['clientWidth'] + 1, sample
        assert sample['scrollHeight'] <= sample['clientHeight'] + 1, sample
        if sample['hasNumber']:
            assert sample['numberDisplay'] == 'block', sample


def alignment(pitcher='Pitcher Pat'):
    return {
        'P': pitcher,
        'C': 'Catcher Cole',
        '1B': 'First Frank',
        '2B': 'Second Sam',
        '3B': 'Third Theo',
        'SS': 'Shortstop Shawn',
        'LF': 'Left Lee',
        'CF': 'Center Casey',
        'RF': 'Right Riley',
    }


def active_sequence(state):
    return max(
        (
            int(event.get('sequence') or 0)
            for event in state.get('rotation_events', [])
            if not event.get('reverted')
        ),
        default=0,
    )


def create_game_with_plan(page: Page, coachboard_url: str):
    game_date = (date.today() + timedelta(days=5)).isoformat()
    response = post_form(page, coachboard_url, '/game-day/add', {
        'game_date': game_date,
        'game_start_time': '10:30',
        'game_opponent': 'Automation Live Opponent',
        'game_location': 'Automation Field',
        'game_notes': 'Created for the app-wide Playwright suite',
        'pitching_rule_set': 'USSSA',
    })
    location = response.headers.get('location') or ''
    match = re.search(r'/game/(\d+)', location)
    assert match, f'New game redirect did not include a game id: {location}'
    game_id = int(match.group(1))

    lineup = post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Automation Game Lineup',
        'lineup_data': [
            'Pitcher Pat', 'Catcher Cole', 'First Frank', 'Second Sam',
            'Third Theo', 'Shortstop Shawn', 'Left Lee', 'Center Casey', 'Right Riley',
        ],
        'associated_game_id': game_id,
    })
    rotation = post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Automation Game Rotation',
        'innings': {'1': alignment(), '2': alignment()},
        'associated_game_id': game_id,
    })
    return game_id, lineup['new_id'], rotation['new_id']


def test_game_day_planning_live_game_and_postgame_lifecycle(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id, _, _ = create_game_with_plan(page, coachboard_url)
    try:
        page_errors = []
        page.on('pageerror', lambda error: page_errors.append(str(error)))

        rules = get_json(page, coachboard_url, f'/api/game-day/{game_id}/pitching-rules')
        assert rules['override'] == 'USSSA' and rules['source'] == 'game'
        rules = post_json(page, coachboard_url, f'/api/game-day/{game_id}/pitching-rules', {
            'rule_set': 'MLB Pitch Smart',
        })
        assert rules['override'] == 'MLB Pitch Smart'

        post_form(page, coachboard_url, f'/game-day/{game_id}/notes', {
            'game_notes': 'Automation notes updated and persisted',
        })
        game_data = get_json(page, coachboard_url, f'/api/game_data/{game_id}')
        assert game_data['game']['game_notes'] == 'Automation notes updated and persisted'
        assert game_data['lineup']['title'] == 'Automation Game Lineup'
        assert game_data['rotation']['title'] == 'Automation Game Rotation'

        post_form(page, coachboard_url, f'/game/{game_id}/update_absences', {
            'absent_players': '9',
        })
        assert get_json(page, coachboard_url, f'/api/game_data/{game_id}')['absent_player_ids'] == [9]
        post_form(page, coachboard_url, f'/game/{game_id}/update_absences', {})

        post_json(page, coachboard_url, f'/api/live-game/{game_id}/pitching-plan', {
            'player_id': 2,
            'role': 'First Relief',
            'expected_innings': '2',
            'coach_note': 'Attack the zone',
            'situational_note': 'Use after starter',
        })
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/pitching-profile/2', {
            'traits': ['Command / Strike Thrower'],
        })

        pregame_state = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
        assert pregame_state['game']['is_live'] is False

        page.goto(f'{coachboard_url}/game/{game_id}')
        start_button = page.locator('#startLiveGameBtnAction')
        expect(start_button).to_be_visible()
        start_button.click()
        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
        expect(page.locator('#live-inning-display')).to_have_text('1')

        state = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
        assert state['game']['is_live'] is True
        assert state['current_alignment']['P'] == 'Pitcher Pat'

        # NEXT exists immediately and is automatically seeded from
        # the Inning 2 pregame defense.
        switcher = page.locator('#cb-now-next-switch')
        expect(switcher).to_be_visible(timeout=15_000)

        switcher.locator('[data-now-next="next"]').click()

        next_board = page.locator('#live-board-prep-v3')
        expect(next_board).to_be_visible(timeout=15_000)
        expect(next_board.locator('.cb-next-title')).to_have_text('2nd Inning Defense')
        expect(next_board.locator('.cb-next-sub')).to_have_text('Pregame plan for the 2nd')

        viewports = (
            {'width': 390, 'height': 844},
            {'width': 820, 'height': 1180},
            {'width': 1180, 'height': 820},
            {'width': 1440, 'height': 900},
        )

        for viewport in viewports:
            page.set_viewport_size(viewport)
            page.wait_for_timeout(180)

            expect(next_board).to_be_visible()

            next_field_names = next_board.locator(
                '.cb-next-spot .cb-qd-name'
            )

            assert_player_names_are_fully_visible(
                next_field_names
            )

            assert page.evaluate(
                'document.documentElement.scrollWidth '
                '<= document.documentElement.clientWidth + 2'
            )

        clock = get_json(page, coachboard_url, f'/api/live-game/{game_id}/clock')
        assert clock['clock']['is_live'] is True
        assert clock['clock']['started_at_utc']
        restarted = post_json(page, coachboard_url, f'/api/live-game/{game_id}/clock', {
            'action': 'restart',
            'time_limit_minutes': 90,
        })
        assert restarted['clock']['time_limit_minutes'] == 90

        live_state = get_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/state',
        )

        changed = post_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/defensive-change',
            {
                'player_id': 4,
                'destination_position': 'SS',
                'base_sequence': active_sequence(live_state),
            },
        )
        assert changed['state']['current_alignment']['SS'] == 'Second Sam'

        restored = post_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/set-defense',
            {
                'alignment': alignment(),
                'base_sequence': active_sequence(changed['state']),
            },
        )
        assert restored['state']['current_alignment']['SS'] == 'Shortstop Shawn'

        pitching_change = alignment('Second Sam')
        pitching_change['2B'] = 'Pitcher Pat'

        completed = post_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/complete-pitcher-change',
            {
                'new_pitcher_id': 4,
                'alignment': pitching_change,
                'base_sequence': active_sequence(restored['state']),
            },
        )
        assert completed['state']['current_alignment']['P'] == 'Second Sam'

        prep = post_json(page, coachboard_url, f'/api/live-game/{game_id}/next-inning-prep', {
            'mode': 'current',
        })
        assert prep['confirmed']['alignment']['P'] == 'Second Sam'
        saved_prep = get_json(page, coachboard_url, f'/api/live-game/{game_id}/next-inning-prep')
        assert saved_prep['confirmed']['source'] == 'current'
        cleared_prep = delete_json(page, coachboard_url, f'/api/live-game/{game_id}/next-inning-prep')
        assert cleared_prep['confirmed'] is None
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/next-inning-prep', {
            'mode': 'current',
        })

        before_advance = get_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/state',
        )

        inning = post_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/advance-inning',
            {
                'alignment': before_advance['current_alignment'],
                'base_sequence': active_sequence(before_advance),
            },
        )
        assert inning['delta']['current_inning'] == '2'

        after_advance = get_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/state',
        )

        undone = post_json(
            page,
            coachboard_url,
            f'/api/live-game/{game_id}/undo',
            {
                'base_sequence': active_sequence(after_advance),
            },
        )
        assert undone['state']['current_inning'] == '1'

        # Socket state broadcasts used to call a removed renderBenchReport() helper.
        page.wait_for_timeout(500)
        assert not [error for error in page_errors if 'renderBenchReport' in error], page_errors

        finalized = post_json(page, coachboard_url, f'/api/live-game/{game_id}/end-with-pitching', {
            'defer_pitching': True,
            'end_reason': 'manual',
            'current_inning_played': True,
        })
        assert finalized['state']['game']['is_live'] is False

        delete_json(page, coachboard_url, f'/api/live-game/{game_id}/pitching-plan/2')

        # The real Live Game page automatically routes a completed game to its
        # report once the state changes from live to ended. Do not issue a second
        # page.goto() to the same URL here; that races the app's navigation and
        # Chromium can abort one of the two requests with net::ERR_ABORTED.
        expect(page).to_have_url(
            re.compile(
                rf'^{re.escape(coachboard_url)}/game-day/{game_id}/report$'
            ),
            timeout=5_000,
        )

        expect(page.get_by_role(
            'heading',
            name=re.compile(r'Automation Live Opponent'),
        )).to_be_visible()
        expect(page.locator('body')).to_contain_text('Automation notes updated and persisted')

        deleted = post_json(page, coachboard_url, f'/game-day/{game_id}/delete', {})
        assert 'Automation Live Opponent' in deleted['message']
        assert get_json(page, coachboard_url, f'/api/game_data/{game_id}', expected_status=404)['error']
    finally:
        release_game(page.request, coachboard_url, game_id)


def test_secondary_coach_uses_live_state_for_postgame_transition(
    browser,
    coachboard_url: str,
):
    primary_context = browser.new_context()
    assistant_context = browser.new_context()
    primary = game_id = None

    try:
        primary = primary_context.new_page()
        assistant = assistant_context.new_page()

        login(primary, coachboard_url)
        login(
            assistant,
            coachboard_url,
            username=ASSISTANT_USERNAME,
            password=ASSISTANT_PASSWORD,
        )

        game_id, _, _ = create_game_with_plan(
            primary,
            coachboard_url,
        )

        primary.goto(f'{coachboard_url}/game/{game_id}')

        start_button = primary.locator(
            '#startLiveGameBtnAction'
        )
        expect(start_button).to_be_visible()
        start_button.click()

        expect(
            primary.locator('#live-game-overlay')
        ).to_be_visible(timeout=15_000)

        # The assistant coach joins the same active Live Game and must observe
        # a live state before the other coach ends it.
        assistant.goto(f'{coachboard_url}/game/{game_id}')

        expect(
            assistant.locator('#live-game-overlay')
        ).to_be_visible(timeout=15_000)

        # Once the assistant has observed the live game, block future HTTP
        # state polls. The postgame transition below must therefore come from
        # the Socket.IO -> applyState -> coachboard:live-state path, not from
        # the 5-second polling fallback.
        assistant.route(
            f'**/api/live-game/{game_id}/state',
            lambda route: route.abort(),
        )

        finalized = post_json(
            primary,
            coachboard_url,
            f'/api/live-game/{game_id}/end-with-pitching',
            {
                'defer_pitching': True,
                'end_reason': 'manual',
                'current_inning_played': True,
            },
        )

        assert finalized['state']['game']['is_live'] is False

        expect(assistant).to_have_url(
            re.compile(
                rf'^{re.escape(coachboard_url)}'
                rf'/game-day/{game_id}/report$'
            ),
            timeout=2_500,
        )

    finally:
        if game_id:
            release_game(primary.request, coachboard_url, game_id)
        assistant_context.close()
        primary_context.close()


def test_live_game_validation_legacy_client_and_cross_site_safety(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    game_id, _, _ = create_game_with_plan(page, coachboard_url)

    inactive = page.request.post(f'{coachboard_url}/api/live-game/{game_id}/set-defense', data={
        'alignment': alignment(),
    })
    assert inactive.status == 409
    assert inactive.json()['message'] == 'Game is not live.'

    invalid_pitcher = page.request.post(f'{coachboard_url}/api/live-game/{game_id}/change-pitcher', data={
        'new_pitcher_id': 99999,
    })
    assert invalid_pitcher.status == 409

    legacy_routes = (
        '/toggle_live_game',
        '/save_rotation_event',
        '/undo_rotation_event',
        '/save_pitching_plan',
        '/delete_pitching_plan',
        '/save_final_pitch_counts',
    )
    for path in legacy_routes:
        response = page.request.post(f'{coachboard_url}{path}', data={'game_id': game_id})
        assert response.status == 410, f'{path} should require a refreshed client'

    cross_site = page.request.post(
        f'{coachboard_url}/api/live-game/{game_id}/start',
        data={},
        headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'},
    )
    assert cross_site.status == 403
    assert cross_site.json()['message'] == 'Cross-site request blocked.'

    destructive_get = page.request.get(
        f'{coachboard_url}/delete_game/{game_id}',
        headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'},
    )
    assert destructive_get.status == 403

    post_json(page, coachboard_url, f'/game-day/{game_id}/delete', {})
