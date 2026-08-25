"""Browser coverage for deleting historical games from Game Day."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
PAST_OPPONENT = 'Past Delete Test Opponent'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    identity = page.get_by_label('Username or email')
    if identity.count() == 0:
        page.goto(f'{coachboard_url}/logout')
        expect(page).to_have_url(re.compile(r'/login$'))
        identity = page.get_by_label('Username or email')
    identity.fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#overview)?$'))


def test_head_coach_can_delete_past_game_from_history(page: Page, coachboard_url: str):
    # Start on desktop because the regression this test protects was caused by
    # the Past Games card clipping the dropdown below the row.
    page.set_viewport_size({'width': 1440, 'height': 900})
    login(page, coachboard_url)

    created = page.context.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': '2025-01-15',
            'game_start_time': '16:30',
            'game_opponent': PAST_OPPONENT,
            'game_location': 'History Field',
            'game_notes': 'Disposable past-game delete regression test',
        },
    )
    assert created.ok

    games_response = page.context.request.get(f'{coachboard_url}/api/games')
    assert games_response.ok
    game = next(item for item in games_response.json() if item.get('opponent') == PAST_OPPONENT)
    game_id = int(game['id'])

    # The dedicated Game Day history exposes the protected options menu and the
    # dropdown must not be clipped by the rounded Past Games container.
    page.goto(f'{coachboard_url}/game-day', wait_until='domcontentloaded')
    past_row = page.locator(f'.gd-up-row[data-game-id="{game_id}"]')
    expect(past_row).to_be_visible()
    past_row.locator('.gd-game-menu > button').click()
    desktop_delete = past_row.get_by_role('button', name='Delete Game')
    expect(desktop_delete).to_be_visible()

    overflow = past_row.evaluate(
        "row => { const list = row.closest('.gd-upcoming'); const s = getComputedStyle(list); return {x:s.overflowX, y:s.overflowY}; }"
    )
    assert overflow == {'x': 'visible', 'y': 'visible'}

    hit_test_visible = desktop_delete.evaluate(
        "el => { const r = el.getBoundingClientRect(); const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!hit && (hit === el || el.contains(hit)); }"
    )
    assert hit_test_visible is True

    # Mobile uses the same authoritative /game-day history instead of falling
    # back to the retired #games dashboard workspace.
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(f'{coachboard_url}/game-day', wait_until='domcontentloaded')
    mobile_row = page.locator(f'.gd-up-row[data-game-id="{game_id}"]')
    expect(mobile_row).to_be_visible()
    mobile_row.locator('.gd-game-menu > button').click()
    delete_button = mobile_row.get_by_role('button', name='Delete Game')
    expect(delete_button).to_be_visible()

    page.once('dialog', lambda dialog: dialog.accept())
    with page.expect_navigation(wait_until='domcontentloaded', timeout=10000):
        delete_button.click()

    games_after = page.context.request.get(f'{coachboard_url}/api/games')
    assert games_after.ok
    assert all(int(item['id']) != game_id for item in games_after.json())
