"""Browser coverage for recovering a Live Game that was ended by mistake."""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:games|overview))?$'))


def post_json(page: Page, coachboard_url: str, path: str, data):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == 200, f'POST {path} returned {response.status}: {response.text()}'
    payload = response.json()
    assert payload.get('status') == 'success', payload
    return payload


def get_json(page: Page, coachboard_url: str, path: str):
    response = page.request.get(f'{coachboard_url}{path}')
    assert response.status == 200, f'GET {path} returned {response.status}: {response.text()}'
    return response.json()


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


def create_game(page: Page, coachboard_url: str):
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=9)).isoformat(),
            'game_start_time': '15:00',
            'game_opponent': 'Resume Live Game Opponent',
            'game_location': 'Resume Test Field',
            'game_notes': 'Disposable accidental-end recovery test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(page, coachboard_url, '/add_lineup', {
        'title': 'Resume Test Lineup',
        'lineup_data': list(alignment().values()),
        'associated_game_id': game_id,
    })
    post_json(page, coachboard_url, '/save_rotation', {
        'title': 'Resume Test Rotation',
        'innings': {'1': alignment(), '2': alignment(), '3': alignment()},
        'associated_game_id': game_id,
    })
    return game_id


def active_sequence(state):
    return max(
        (int(event.get('sequence') or 0) for event in state.get('rotation_events', []) if not event.get('reverted')),
        default=0,
    )


def test_ended_game_can_resume_same_inning_clock_and_history_then_end_again(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        started = post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
        assert started['state']['game']['is_live'] is True

        advanced = post_json(page, coachboard_url, f'/api/live-game/{game_id}/end-inning', {})
        assert advanced['state']['current_inning'] == '2'

        ended = post_json(page, coachboard_url, f'/api/live-game/{game_id}/end-with-pitching', {
            'defer_pitching': True,
            'end_reason': 'manual',
            'current_inning_played': True,
        })
        assert ended['state']['game']['is_live'] is False
        ended_clock = get_json(page, coachboard_url, f'/api/live-game/{game_id}/clock')['clock']
        assert ended_clock['is_live'] is False
        assert ended_clock['end_reason'] == 'manual'
        assert ended_clock['ended_at_utc']

        ended_state = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
        end_markers = [event for event in ended_state['rotation_events'] if event['event_type'] == 'End Game']
        assert len(end_markers) == 1
        assert end_markers[0]['reverted'] is False
        assert ended_state['current_inning'] == '2'

        page.goto(f'{coachboard_url}/game-day/{game_id}/report', wait_until='domcontentloaded')
        expect(page.get_by_text('Game Report', exact=True)).to_be_visible()
        resume_button = page.get_by_role('button', name='Resume Live Game')
        expect(resume_button).to_be_visible()
        resume_button.click()

        expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/game/{game_id}/?$'), timeout=15_000)
        expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
        expect(page.locator('#cbDugoutHeader')).to_be_visible(timeout=15_000)
        expect(page.locator('#live-inning-display')).to_have_text('2')

        resumed_state = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
        assert resumed_state['game']['is_live'] is True
        assert resumed_state['current_inning'] == '2'
        assert resumed_state['current_alignment'] == alignment()

        resumed_markers = [event for event in resumed_state['rotation_events'] if event['event_type'] == 'End Game']
        assert len(resumed_markers) == 1
        assert resumed_markers[0]['reverted'] is True
        resume_markers = [
            event for event in resumed_state['rotation_events']
            if event['event_type'] == 'Resume Game' and not event['reverted']
        ]
        assert len(resume_markers) == 1
        assert resume_markers[0]['inning'] == '2'
        assert resume_markers[0]['before_alignment'] == alignment()
        assert resume_markers[0]['after_alignment'] == alignment()

        resumed_clock = get_json(page, coachboard_url, f'/api/live-game/{game_id}/clock')['clock']
        assert resumed_clock['is_live'] is True
        assert resumed_clock['is_paused'] is False
        assert resumed_clock['ended_at_utc'] is None
        assert resumed_clock['end_reason'] is None
        assert resumed_clock['last_played_inning'] == '2'

        # The resumed sequence must support the same stale-write protected bulk
        # defense save used by the direct-drag and full field editors.
        changed_alignment = dict(resumed_state['current_alignment'])
        changed_alignment['SS'], changed_alignment['2B'] = changed_alignment['2B'], changed_alignment['SS']
        post_json(page, coachboard_url, f'/api/live-game/{game_id}/defense-edit', {
            'alignment': changed_alignment,
            'base_sequence': active_sequence(resumed_state),
        })
        changed_state = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
        assert changed_state['current_alignment']['SS'] == 'Second Sam'
        assert changed_state['current_alignment']['2B'] == 'Shortstop Shawn'
        assert any(
            event['event_type'] == 'Bulk Defensive Change' and not event['reverted']
            for event in changed_state['rotation_events']
        )

        # A later legitimate End Game creates a new active marker. The accidental
        # end remains in history as reverted instead of being erased.
        ended_again = post_json(page, coachboard_url, f'/api/live-game/{game_id}/end-with-pitching', {
            'defer_pitching': True,
            'end_reason': 'manual',
            'current_inning_played': True,
        })
        assert ended_again['state']['game']['is_live'] is False

        final_state = get_json(page, coachboard_url, f'/api/live-game/{game_id}/state')
        final_markers = [event for event in final_state['rotation_events'] if event['event_type'] == 'End Game']
        assert len(final_markers) == 2
        assert sum(1 for event in final_markers if event['reverted']) == 1
        assert sum(1 for event in final_markers if not event['reverted']) == 1
        assert final_state['current_inning'] == '2'
    finally:
        state_response = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
        if state_response.ok and state_response.json().get('game', {}).get('is_live'):
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
