"""Locked Test 2 iPhone + iPad stress pass across live-game race conditions."""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Browser, Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


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


def planned_two():
    value = alignment()
    value['SS'], value['2B'] = value['2B'], value['SS']
    return value


def create_game(page: Page, coachboard_url: str, opponent: str, *, complete=True, include_inning_two=True):
    response = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': (date.today() + timedelta(days=14)).isoformat(),
            'game_start_time': '12:30',
            'game_opponent': opponent,
            'game_location': 'Test 2 Stress Field',
            'game_notes': 'Disposable Test 2 stress game',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )
    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    if complete:
        innings = {'1': alignment()}
        if include_inning_two:
            innings['2'] = planned_two()
        rotation = page.request.post(
            f'{coachboard_url}/save_rotation',
            data={
                'title': f'{opponent} Stress Rotation',
                'innings': innings,
                'associated_game_id': game_id,
            },
        )
        assert rotation.status == 200, rotation.text()
        assert rotation.json().get('status') == 'success', rotation.json()
    return game_id


def current_sequence(state):
    return max(
        [0] + [
            int(event.get('sequence') or 0)
            for event in state.get('rotation_events', [])
            if not event.get('reverted')
        ]
    )


def cleanup_game(page: Page, coachboard_url: str, game_id: int):
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


def test_test2_iphone_ipad_multi_client_stress(browser: Browser, coachboard_url: str):
    phone_context = browser.new_context(viewport={'width': 390, 'height': 844})
    ipad_context = browser.new_context(viewport={'width': 768, 'height': 1024})
    phone = phone_context.new_page()
    ipad = ipad_context.new_page()
    game_id = None
    incomplete_id = None

    try:
        login(phone, coachboard_url)
        login(ipad, coachboard_url)
        game_id = create_game(phone, coachboard_url, 'Test 2 Multi Client Opponent')

        phone.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        ipad.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        # Empty batting order must remain optional on both clients.
        phone_ready = phone.request.get(f'{coachboard_url}/api/game-day/{game_id}/readiness').json()
        ipad_ready = ipad.request.get(f'{coachboard_url}/api/game-day/{game_id}/readiness').json()
        for ready in (phone_ready, ipad_ready):
            assert ready['readiness']['lineup_ready'] is False
            assert ready['ready'] is True, ready
            assert ready['missing'] == []

        # Client A starts. Client B must converge to the same live transition without reloading.
        phone.locator('#startLiveGameBtnAction').click()
        expect(phone.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        expect(ipad.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        expect(phone.locator('#live-inning-display')).to_have_text('1')
        expect(ipad.locator('#live-inning-display')).to_have_text('1')

        # Planned-but-not-locked Inning 2: End Inning opens a huddle, not an editor,
        # and the planned defense is an explicit choice before Start Inning is enabled.
        prep = phone.request.get(f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep').json()
        assert prep['confirmed'] is None
        assert prep['planned_alignment']
        phone.locator('#liveEndInningBtn').click()
        huddle = phone.locator('#cb-test2-huddle-modal')
        expect(huddle).to_be_visible(timeout=10_000)
        expect(huddle.locator('[data-cb-t2-choice="planned"]')).to_be_visible()
        expect(huddle.locator('[data-cb-t2-start-inning]')).to_be_disabled()
        expect(phone.locator('#cb-live-field-editor')).to_have_count(0)
        huddle.get_by_role('button', name='Back to game').click()
        expect(huddle).not_to_be_visible(timeout=10_000)

        # Move -> Undo -> End Inning quickly. The huddle must win the click and the
        # game must stay coherent while Undo and next-inning preparation settle.
        quick = phone.locator('#cbQuickDefense')
        quick.locator('[data-cb-position="SS"]').click()
        move = phone.locator('#cbQuickMoveModal')
        expect(move).to_be_visible(timeout=10_000)
        move.locator('[data-cb-destination="2B"]').click()
        expect(move).not_to_be_visible(timeout=10_000)
        expect(quick.locator('.cb-save-state')).to_contain_text('Saved', timeout=10_000)
        phone.locator('#liveUndoBtn').click()
        phone.locator('#liveEndInningBtn').click()
        expect(huddle).to_be_visible(timeout=10_000)
        expect(phone.locator('#cb-live-field-editor')).to_have_count(0)
        huddle.get_by_role('button', name='Back to game').click()

        # Navigate away while a defensive bulk save is in flight. keepalive keeps
        # the write eligible to finish while the page leaves; returning must show
        # one authoritative defense, never a half-rendered local draft.
        state = phone.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        inflight = dict(state['current_alignment'])
        inflight['1B'], inflight['3B'] = inflight['3B'], inflight['1B']
        phone.evaluate(
            """({gameId, alignment, baseSequence}) => {
                fetch(`/api/live-game/${gameId}/defense-edit`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({alignment, base_sequence: baseSequence}),
                    keepalive: true,
                });
                window.location.assign('/game-day');
            }""",
            {
                'gameId': game_id,
                'alignment': inflight,
                'baseSequence': current_sequence(state),
            },
        )
        expect(phone).to_have_url(re.compile(r'/game-day$'), timeout=10_000)
        phone.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(phone.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        authoritative = phone.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert authoritative['current_alignment'] in (state['current_alignment'], inflight)
        expect(phone.locator('#cbQuickDefense .cb-main-draft-banner')).to_have_count(0)

        # Both sessions still see the same authoritative inning and live state.
        phone_state = phone.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        ipad_state = ipad.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert phone_state['game']['is_live'] is True
        assert ipad_state['game']['is_live'] is True
        assert phone_state['current_inning'] == ipad_state['current_inning'] == '1'
        assert phone_state['current_alignment'] == ipad_state['current_alignment']

        # Direct /start must reject an incomplete game using the same server contract.
        incomplete_id = create_game(phone, coachboard_url, 'Test 2 Incomplete Opponent', complete=False)
        rejected = phone.request.post(f'{coachboard_url}/api/live-game/{incomplete_id}/start', data={})
        assert rejected.status == 409, rejected.text()
        payload = rejected.json()
        assert payload['ready'] is False
        assert 'Finish the Inning 1 defense.' in payload['missing']
        incomplete_state = phone.request.get(f'{coachboard_url}/api/live-game/{incomplete_id}/state').json()
        assert incomplete_state['game']['is_live'] is False
    finally:
        if game_id is not None:
            cleanup_game(phone, coachboard_url, game_id)
        if incomplete_id is not None:
            cleanup_game(phone, coachboard_url, incomplete_id)
        phone_context.close()
        ipad_context.close()