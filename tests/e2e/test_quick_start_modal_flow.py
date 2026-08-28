"""Browser coverage for the contained Quick Start pregame workflow."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
OPPONENT = 'Quick Start Modal Opponent'


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
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def quick_step(quick, key: str):
    return quick.locator(f'[data-cb-qs-step="{key}"]')


def back_to_quick(step_modal):
    step_modal.get_by_role('button', name='Back to Quick Start').last.click()


def test_quick_start_keeps_first_pitch_setup_in_modals(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)

    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': '2030-05-10',
            'game_start_time': '09:00',
            'game_opponent': OPPONENT,
            'game_location': 'Quick Start Field',
            'game_notes': 'Disposable Quick Start modal test',
        },
    )
    assert created.ok
    games = page.request.get(f'{coachboard_url}/api/games').json()
    game = next(item for item in games if item.get('opponent') == OPPONENT)
    game_id = int(game['id'])

    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        launcher = page.locator('#cb-quick-start-launch')
        expect(launcher).to_be_visible(timeout=15_000)
        launcher.get_by_role('button', name='Open Quick Start').click()

        quick = page.locator('#cb-quick-start-modal')
        step_modal = page.locator('#cb-quick-step-modal')
        expect(quick).to_be_visible()
        expect(quick.locator('.cb-qs-progress')).to_contain_text('essentials ready')

        # Player Availability stays in a focused popup instead of scrolling the
        # coach to the full pregame page.
        quick_step(quick, 'availability').locator('[data-cb-qs-go]').click()
        expect(quick).to_be_hidden()
        expect(step_modal).to_be_visible()
        expect(step_modal.locator('[data-cb-qsm-title]')).to_have_text('Player Availability')
        expect(step_modal.locator('#gameAvailabilityForm')).to_be_visible()
        back_to_quick(step_modal)
        expect(quick).to_be_visible()

        # Batting Order uses the real lineup editor modal and returns directly to
        # Quick Start when the coach closes it.
        quick_step(quick, 'batting').locator('[data-cb-qs-go]').click()
        lineup = page.locator('#lineupEditorModal')
        expect(quick).to_be_hidden()
        expect(lineup).to_be_visible()
        lineup.get_by_role('button', name='Cancel').click()
        expect(quick).to_be_visible()

        # Starting Defense moves the actual autosaving field editor into the
        # focused popup, then restores it to the full plan afterward.
        quick_step(quick, 'defense').locator('[data-cb-qs-go]').click()
        expect(step_modal).to_be_visible()
        expect(step_modal.locator('[data-cb-qsm-title]')).to_have_text('Starting Defense')
        expect(step_modal.locator('#pregame-defense-editor-v3')).to_be_visible()
        expect(step_modal.locator('[data-pde-pos="P"]')).to_be_visible()
        back_to_quick(step_modal)
        expect(quick).to_be_visible()
        expect(page.locator('#rotation-card-container #pregame-defense-editor-v3')).to_have_count(1)

        # Starting Pitcher is a compact eligibility-first picker rather than a
        # jump into the entire pitching/defense section.
        quick_step(quick, 'starter').locator('[data-cb-qs-go]').click()
        expect(step_modal).to_be_visible()
        expect(step_modal.locator('[data-cb-qsm-title]')).to_have_text('Starting Pitcher')
        expect(step_modal.locator('.cb-qsp-player')).not_to_have_count(0, timeout=15_000)
        back_to_quick(step_modal)
        expect(quick).to_be_visible()

        # Pitching Tracking leads with Track Pitches vs Track Innings / Outs and
        # saves without leaving Quick Start.
        quick_step(quick, 'rules').locator('[data-cb-qs-go]').click()
        expect(step_modal).to_be_visible()
        expect(step_modal.locator('[data-cb-qsm-title]')).to_have_text('Pitching Tracking')
        expect(step_modal).to_contain_text('Track Pitches')
        expect(step_modal).to_contain_text('Track Innings / Outs')
        pitch_smart = step_modal.locator('[data-cb-qsr-rule="MLB Pitch Smart"]')
        expect(pitch_smart).to_be_visible()
        pitch_smart.click()
        expect(step_modal).to_be_hidden()
        expect(quick).to_be_visible(timeout=10_000)
        expect(quick_step(quick, 'rules')).to_contain_text('Track Pitches', timeout=10_000)

        # Game Clock uses the existing quick preset modal and comes back to the
        # Quick Start checklist when the coach is done.
        quick_step(quick, 'clock').locator('[data-cb-qs-go]').click()
        clock = page.locator('#cbGameClockConfigModal')
        expect(quick).to_be_hidden()
        expect(clock).to_be_visible()
        expect(clock.get_by_role('button', name='1:45')).to_be_visible()
        expect(clock.get_by_role('button', name='No Limit')).to_be_visible()
        clock.get_by_role('button', name='Done').click()
        expect(quick).to_be_visible()

        quick.get_by_role('button', name='Full Game Plan').click()
        expect(quick).to_be_hidden()
    finally:
        page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
