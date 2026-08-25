"""iPad browser coverage for the pregame coaching workflow."""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


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


@pytest.mark.parametrize(
    ('orientation', 'width', 'height'),
    [
        pytest.param('portrait', 768, 1024, id='ipad-portrait-768x1024'),
        pytest.param('landscape', 1024, 768, id='ipad-landscape-1024x768'),
    ],
)
def test_ipad_game_planning_keeps_tablet_layout(
    page: Page,
    coachboard_url: str,
    orientation: str,
    width: int,
    height: int,
):
    """Protect the tablet layout from phone-only Game Planning rules."""
    page.set_viewport_size({'width': width, 'height': height})
    login(page, coachboard_url)

    opponent = f'iPad {orientation.title()} Prep UX Opponent'
    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': '2030-01-16',
            'game_start_time': '14:00',
            'game_opponent': opponent,
            'game_location': 'Tablet Test Field',
            'game_notes': f'Disposable iPad {orientation} pregame UX test',
        },
    )
    assert created.ok
    games = page.request.get(f'{coachboard_url}/api/games').json()
    game = next(item for item in games if item.get('opponent') == opponent)
    game_id = int(game['id'])

    try:
        page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')

        readiness = page.locator('#coach-game-readiness-v2')
        expect(readiness).to_be_visible(timeout=15_000)

        # The phone redesign intentionally hides these four prep cards below
        # 768px. At the exact iPad boundary and above, the tablet layout retains them.
        prep_cards = page.locator('#pregame-checklist-container > .row.g-3.mb-4')
        expect(prep_cards).to_be_visible(timeout=15_000)

        # Start Live Game remains available, but should not be relocated into
        # the phone-only slot immediately after the compact readiness panel.
        start_button = page.locator('#startLiveGameBtnAction')
        expect(start_button).to_be_visible(timeout=15_000)
        phone_slot_start = readiness.locator(
            'xpath=following-sibling::*[1]//button[@id="startLiveGameBtnAction"]'
        )
        expect(phone_slot_start).to_have_count(0)

        # All regulation inning controls stay inside the viewport.
        inning_labels = page.locator('#inning-btn-group label.btn')
        expect(inning_labels).to_have_count(6, timeout=15_000)
        inning_bounds = inning_labels.evaluate_all(
            """items => items.map(item => {
                const r = item.getBoundingClientRect();
                return {left:r.left, right:r.right, viewport:innerWidth};
            })"""
        )
        assert all(item['left'] >= -1 and item['right'] <= item['viewport'] + 1 for item in inning_bounds)

        # Use the visible defense editor and the same preset workflow a coach taps.
        expect(page.locator('#rotation-editor-title')).to_have_text('Set Defense')
        defense = page.locator('#pregame-defense-editor-v3')
        expect(defense).to_be_visible(timeout=15_000)
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
                    return {left:r.left, right:r.right, top:r.top, bottom:r.bottom};
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

        names = field.locator('.pde-name')
        expect(names).not_to_have_count(0)
        samples = names.evaluate_all(
            """items => items.map(el => ({
                text:(el.textContent || '').trim(),
                whiteSpace:getComputedStyle(el).whiteSpace,
                overflow:getComputedStyle(el).overflow,
                textOverflow:getComputedStyle(el).textOverflow,
                scrollWidth:el.scrollWidth,
                clientWidth:el.clientWidth,
                scrollHeight:el.scrollHeight,
                clientHeight:el.clientHeight,
            }))"""
        )
        for sample in samples:
            if sample['text'] == 'OPEN':
                continue
            assert sample['whiteSpace'] == 'normal', sample
            assert sample['overflow'] == 'visible', sample
            assert sample['textOverflow'] == 'clip', sample
            assert sample['scrollWidth'] <= sample['clientWidth'] + 1, sample
            assert sample['scrollHeight'] <= sample['clientHeight'] + 1, sample

        # Pitching details are only collapsed into a phone toggle below the
        # tablet breakpoint. iPad keeps the richer at-a-glance card.
        pitching = page.locator('#pitcher-availability-card')
        expect(pitching).to_be_visible(timeout=15_000)
        pitcher_cards = pitching.locator('.gpa-card')
        expect(pitcher_cards).not_to_have_count(0)
        expect(pitcher_cards.first.locator('.gpa-metrics')).to_be_visible()
        expect(pitcher_cards.first.locator('.gm-pitch-card-more')).to_be_hidden()

        # Nothing on Game Planning may make the entire iPad page scroll sideways.
        assert page.evaluate(
            'document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2'
        )
    finally:
        page.request.post(
            f'{coachboard_url}/game-day/{game_id}/delete',
            headers={'Accept': 'application/json'},
        )
