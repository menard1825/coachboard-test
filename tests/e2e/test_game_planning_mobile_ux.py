"""Mobile browser coverage for the pregame coaching workflow."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
OPPONENT = 'Mobile Prep UX Opponent'


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


def test_mobile_game_planning_is_compact_and_baseball_friendly(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)

    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': '2030-01-15',
            'game_start_time': '14:00',
            'game_opponent': OPPONENT,
            'game_location': 'Test Field',
            'game_notes': 'Disposable mobile pregame UX test',
        },
    )
    assert created.ok
    games = page.request.get(f'{coachboard_url}/api/games').json()
    game = next(item for item in games if item.get('opponent') == OPPONENT)
    game_id = int(game['id'])

    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        readiness = page.locator('#coach-game-readiness-v2')
        expect(readiness).to_be_visible(timeout=15_000)
        expect(readiness).to_contain_text('Finish the defense for innings 1–6.')
        expect(readiness).not_to_contain_text('regulation inning(s)')
        expect(readiness).not_to_contain_text('setup item need attention')
        expect(readiness.get_by_role('button', name=re.compile("Who's Out"))).to_be_visible()
        expect(readiness.get_by_role('button', name=re.compile('Batting Order'))).to_be_visible()
        expect(readiness.get_by_role('button', name=re.compile('Defense'))).to_be_visible()
        expect(readiness.get_by_role('button', name=re.compile('Pitch Plan'))).to_be_visible()

        # The old four-card checklist is redundant on phones and must stay out of
        # the way. Start Live Game should sit directly below the compact status.
        expect(page.locator('#pregame-checklist-container > .row.g-3.mb-4')).to_be_hidden()
        start_after_readiness = readiness.locator('xpath=following-sibling::*[1]//button[@id="startLiveGameBtnAction"]')
        expect(start_after_readiness).to_be_visible()
        expect(start_after_readiness).to_have_text(re.compile('Start Live Game'))
        expect(page.locator('#start-live-blockers')).to_be_hidden()

        # All six regulation innings fit across the phone without being clipped.
        inning_labels = page.locator('#inning-btn-group label.btn')
        expect(inning_labels).to_have_count(6, timeout=15_000)
        inning_bounds = inning_labels.evaluate_all(
            """items => items.map(item => {
                const r = item.getBoundingClientRect();
                return {left:r.left, right:r.right, top:r.top, viewport:innerWidth};
            })"""
        )
        assert all(item['left'] >= -1 and item['right'] <= item['viewport'] + 1 for item in inning_bounds)
        assert max(item['top'] for item in inning_bounds) - min(item['top'] for item in inning_bounds) <= 3

        # The current editor is the rotation-board diamond, not the retired PDE
        # overlay. It must remain directly usable on a phone.
        expect(page.locator('#rotation-editor-title')).to_have_text('Set Defense')
        expect(page.locator('#rotation-board')).to_be_visible(timeout=15_000)
        template_select = page.locator('#rotationTemplateSelect')
        expect(template_select).to_be_attached()
        everyday = template_select.locator('option').filter(has_text='Everyday Defense')
        expect(everyday).to_have_count(1)
        template_id = everyday.get_attribute('value')
        assert template_id
        page.once('dialog', lambda dialog: dialog.accept())
        template_select.select_option(value=template_id)

        diamond = page.locator('#diamond-parent-mobile .diamond-container-interactive')
        expect(diamond).to_be_visible()
        spots = diamond.locator('.position-dropzone')
        expect(spots).to_have_count(9)
        geometry = diamond.evaluate(
            """field => {
                const outer = field.getBoundingClientRect();
                const spots = [...field.querySelectorAll('.position-dropzone')].map(spot => {
                    const r = spot.getBoundingClientRect();
                    return {left:r.left, right:r.right, top:r.top, bottom:r.bottom, width:r.width, height:r.height};
                });
                return {outer:{left:outer.left,right:outer.right,top:outer.top,bottom:outer.bottom},spots};
            }"""
        )
        assert geometry['spots']
        assert all(
            spot['left'] >= geometry['outer']['left'] - 1
            and spot['right'] <= geometry['outer']['right'] + 1
            and spot['top'] >= geometry['outer']['top'] - 1
            and spot['bottom'] <= geometry['outer']['bottom'] + 1
            for spot in geometry['spots']
        )
        assert all(spot['width'] >= 44 and spot['height'] >= 36 for spot in geometry['spots'])

        # A player's complete name is game-critical information. Applied preset
        # names may wrap, but they must not be ellipsized or clipped.
        diamond_names = diamond.locator('.player-tag')
        expect(diamond_names).not_to_have_count(0)
        samples = diamond_names.evaluate_all(
            """items => items.map(el => {
                const s = getComputedStyle(el);
                return {
                    text:(el.textContent || '').trim(),
                    textOverflow:s.textOverflow,
                    scrollWidth:el.scrollWidth,
                    clientWidth:el.clientWidth,
                    scrollHeight:el.scrollHeight,
                    clientHeight:el.clientHeight,
                };
            })"""
        )
        for sample in samples:
            assert sample['text']
            assert sample['textOverflow'] != 'ellipsis', sample
            assert sample['scrollWidth'] <= sample['clientWidth'] + 1, sample
            assert sample['scrollHeight'] <= sample['clientHeight'] + 1, sample

        # Game-planning pitching uses coach language and keeps secondary pitch
        # metrics collapsed until the coach asks for them.
        pitching = page.locator('#pitcher-availability-card')
        expect(pitching).to_be_visible(timeout=15_000)
        expect(pitching.locator(':scope > .card-header strong, :scope > .card-header h5').first).to_have_text('Who Can Pitch?')
        pitcher_cards = pitching.locator('.gpa-card')
        expect(pitcher_cards).not_to_have_count(0)
        expect(pitcher_cards.first).to_contain_text('Game eligibility')
        expect(pitcher_cards.first).not_to_contain_text('Competition eligibility')
        expect(pitcher_cards.first.locator('.gpa-metrics')).to_be_hidden()
        expect(pitcher_cards.first.locator('.gm-pitch-card-more')).to_be_visible()

        assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2')
    finally:
        page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
