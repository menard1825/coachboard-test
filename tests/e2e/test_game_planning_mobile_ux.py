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
        expect(readiness).not_to_contain_text('Finish the defense for innings 1–6.')
        expect(readiness).not_to_contain_text('regulation inning(s)')
        expect(readiness).not_to_contain_text('setup item need attention')
        expect(readiness.get_by_role('button', name=re.compile('Player Availability'))).to_be_visible()
        expect(readiness.get_by_role('button', name=re.compile('Defense'))).to_be_visible()
        expect(readiness.get_by_role('button', name=re.compile('Game Clock'))).to_be_visible()

        modes = page.locator('#cb-test2-pregame-modes')
        expect(modes).to_be_visible(timeout=15_000)
        first_pitch = modes.get_by_role('button', name='First Pitch')
        full_plan = modes.get_by_role('button', name='Full Plan')
        expect(first_pitch).to_have_class(re.compile(r'\bactive\b'))
        expect(page.locator('#cb-quick-start-launch')).to_have_count(0)
        expect(page.locator('#cb-quick-start-modal')).to_have_count(0)
        expect(readiness.get_by_role('button', name=re.compile('Batting Order'))).to_be_hidden()

        # Full Plan intentionally reveals the optional whole-game planning tools.
        full_plan.click()
        expect(full_plan).to_have_class(re.compile(r'\bactive\b'))
        expect(readiness.get_by_role('button', name=re.compile('Batting Order'))).to_be_visible()

        # The normal Start Game action stays available as a sticky footer action.
        start = page.locator('#startLiveGameBtnAction')
        expect(start).to_be_visible()
        expect(start).to_have_text(re.compile('START GAME'))
        start_style = start.evaluate(
            """button => ({position:getComputedStyle(button).position,bottom:button.getBoundingClientRect().bottom,viewport:innerHeight})"""
        )
        assert start_style['position'] == 'fixed'
        assert start_style['bottom'] <= start_style['viewport'] + 1
        assert start_style['bottom'] >= start_style['viewport'] - 90
        expect(page.locator('#start-live-blockers')).to_be_hidden()

        rules = page.locator('#game-pitching-rules-v2')
        expect(rules).to_be_visible(timeout=15_000)
        expect(rules.locator('.gpr-label').first).to_have_text('Game Tracking')
        expect(rules.locator('.gpr-rule')).to_have_text(re.compile(r'Track Pitches|Track Innings / Outs|Track Pitching|Choose tracking'))

        # Full Plan exposes all regulation innings on the phone without clipping.
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

        expect(page.locator('#rotation-editor-title')).to_have_text('Set Defense')
        defense = page.locator('#pregame-defense-editor-v3')
        expect(defense).to_be_visible(timeout=15_000)
        expect(defense.locator('.pde-title')).to_have_text('Set Defense — Inning 1')
        expect(defense.locator('.pde-kicker')).to_have_text('Defense Setup')
        canonical_label = defense.locator('.cb-starting-defense-label')
        expect(canonical_label).to_have_count(1)
        expect(canonical_label).to_have_text('Starting Defense Preset (Optional)')
        expect(defense.locator('.gm-preset-help')).to_be_hidden()
        expect(defense.locator('#pde-apply')).to_have_text('Apply to Inning 1')
        expect(defense.locator('#pde-apply-game')).to_have_text('Apply to Entire Game')
        expect(defense.locator('.cb-starting-defense-help')).to_contain_text('Pitchers stay as assigned')

        preset_layout = defense.locator('.pde-tools').evaluate(
            """tools => {
                const wrap = tools.querySelector('.gm-preset-wrap').getBoundingClientRect();
                const select = tools.querySelector('#pde-preset').getBoundingClientRect();
                const game = tools.querySelector('#pde-apply-game').getBoundingClientRect();
                const apply = tools.querySelector('#pde-apply').getBoundingClientRect();
                return {
                    display:getComputedStyle(tools).display,
                    wrap:{left:wrap.left,right:wrap.right,top:wrap.top,bottom:wrap.bottom},
                    select:{left:select.left,right:select.right,top:select.top,bottom:select.bottom},
                    game:{left:game.left,right:game.right,top:game.top,bottom:game.bottom},
                    apply:{left:apply.left,right:apply.right,top:apply.top},
                };
            }"""
        )
        assert preset_layout['display'] == 'grid'
        assert abs(preset_layout['game']['top'] - preset_layout['select']['top']) <= 4
        assert preset_layout['apply']['top'] >= max(preset_layout['wrap']['bottom'], preset_layout['game']['bottom']) - 1
        assert abs(preset_layout['apply']['left'] - min(preset_layout['wrap']['left'], preset_layout['game']['left'])) <= 2
        assert abs(preset_layout['apply']['right'] - max(preset_layout['wrap']['right'], preset_layout['game']['right'])) <= 2

        defense_options = page.get_by_role('button', name=re.compile('Defense Options'))
        defense_options.click()
        expect(page.locator('#gmFullGamePlanHeader')).to_contain_text('Full-game defense plan · all innings')
        rotation_template = page.locator('#rotationTemplateSelect')
        expect(rotation_template).to_be_visible()
        expect(rotation_template.locator('option').first).to_have_text('Load full-game defense plan (all innings)…')
        defense_options.click()

        preset = defense.locator('#pde-preset')
        expect(preset).to_be_visible()
        everyday = preset.locator('option').filter(has_text='Everyday Defense')
        expect(everyday).to_have_count(1)
        preset_id = everyday.get_attribute('value')
        assert preset_id
        preset.select_option(value=preset_id)
        page.once('dialog', lambda dialog: dialog.accept())
        defense.locator('#pde-apply').click()
        expect(defense.locator('[data-pde-pos="SS"] .pde-name')).to_have_text('Shortstop Shawn')
        expect(defense.locator('[data-pde-pos="P"] .pde-name')).to_have_text('OPEN')

        field = defense.locator('.pde-field')
        expect(field).to_be_visible()
        spots = field.locator('.pde-spot')
        expect(spots).to_have_count(9)
        geometry = field.evaluate(
            """field => {
                const outer = field.getBoundingClientRect();
                const spots = [...field.querySelectorAll('.pde-spot')].map(spot => {
                    const r = spot.getBoundingClientRect();
                    return {left:r.left, right:r.right, top:r.top, bottom:r.bottom, width:r.width, height:r.height};
                });
                return {outer:{left:outer.left,right:outer.right,top:outer.top,bottom:outer.bottom,height:outer.height},spots};
            }"""
        )
        assert geometry['outer']['height'] <= 270
        assert geometry['spots']
        assert all(
            spot['left'] >= geometry['outer']['left'] - 1
            and spot['right'] <= geometry['outer']['right'] + 1
            and spot['top'] >= geometry['outer']['top'] - 1
            and spot['bottom'] <= geometry['outer']['bottom'] + 1
            for spot in geometry['spots']
        )
        assert all(spot['width'] >= 44 and spot['height'] >= 36 for spot in geometry['spots'])

        diamond_names = field.locator('.pde-name')
        expect(diamond_names).not_to_have_count(0)
        samples = diamond_names.evaluate_all(
            """items => items.map(el => {
                const s = getComputedStyle(el);
                return {
                    text:(el.textContent || '').trim(), whiteSpace:s.whiteSpace,
                    overflow:s.overflow, textOverflow:s.textOverflow,
                    fontSize:parseFloat(s.fontSize), scrollWidth:el.scrollWidth,
                    clientWidth:el.clientWidth, scrollHeight:el.scrollHeight,
                    clientHeight:el.clientHeight,
                };
            })"""
        )
        for sample in samples:
            if sample['text'] == 'OPEN':
                continue
            assert sample['whiteSpace'] == 'normal', sample
            assert sample['overflow'] == 'visible', sample
            assert sample['textOverflow'] == 'clip', sample
            assert sample['fontSize'] >= 8.0, sample
            assert sample['scrollWidth'] <= sample['clientWidth'] + 1, sample
            assert sample['scrollHeight'] <= sample['clientHeight'] + 1, sample

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
