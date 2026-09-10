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
        modes = page.locator('#cb-test2-pregame-modes')
        expect(modes).to_be_visible(timeout=15_000)
        modes.get_by_role('button', name='Full Plan').click()
        expect(modes.get_by_role('button', name='Full Plan')).to_have_class(re.compile(r'\bactive\b'))

        # The phone redesign intentionally hides these four prep cards below
        # 768px. At the exact iPad boundary and above, the tablet layout retains them.
        prep_cards = page.locator('#pregame-checklist-container > .row.g-3.mb-4')
        expect(prep_cards).to_be_visible(timeout=15_000)

        start_button = page.locator('#startLiveGameBtnAction')
        expect(start_button).to_be_visible(timeout=15_000)
        phone_slot_start = readiness.locator(
            'xpath=following-sibling::*[1]//button[@id="startLiveGameBtnAction"]'
        )
        expect(phone_slot_start).to_have_count(0)

        inning_labels = page.locator('#inning-btn-group label.btn')
        expect(inning_labels).to_have_count(6, timeout=15_000)
        inning_bounds = inning_labels.evaluate_all(
            """items => items.map(item => {
                const r = item.getBoundingClientRect();
                return {left:r.left, right:r.right, viewport:innerWidth};
            })"""
        )
        assert all(item['left'] >= -1 and item['right'] <= item['viewport'] + 1 for item in inning_bounds)

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

        # Game Management defense layout:
        # landscape iPad keeps innings reachable, shows Rotation Table
        # immediately after Set Defense, and demotes Player Time.
        if orientation == 'landscape':
            inning_picker = page.locator(
                '#rotation-card-container '
                '.gm-coach-inning-picker'
            )

            expect(inning_picker).to_be_visible()

            sticky = inning_picker.evaluate(
                """el => ({
                    position:getComputedStyle(el).position,
                    top:getComputedStyle(el).top,
                })"""
            )

            assert sticky['position'] == 'sticky'
            assert sticky['top'] == '56px'

            # Prove the picker is no longer trapped inside the short
            # planner-controls wrapper. CSS alone is not enough:
            # sticky elements stop sticking at their containing
            # block's bottom.
            assert inning_picker.evaluate(
                "el => el.parentElement?.id"
            ) == 'rotation-board'

            # The outer rotation card must not create an overflow
            # boundary around the sticky picker.
            rotation_card = page.locator(
                '#rotation-card-container > .card'
            )

            assert rotation_card.evaluate(
                "el => getComputedStyle(el).overflow"
            ) == 'visible'

            field_document_top = field.evaluate(
                """el => (
                    el.getBoundingClientRect().top +
                    window.scrollY
                )"""
            )

            page.evaluate(
                "y => window.scrollTo(0, y)",
                field_document_top + 120,
            )

            page.wait_for_timeout(150)

            first_sticky_box = inning_picker.bounding_box()
            assert first_sticky_box is not None
            assert 54 <= first_sticky_box['y'] <= 60

            # Scroll substantially farther through the field. The
            # inning row must still remain pinned instead of moving
            # away after one frame.
            page.evaluate(
                "window.scrollBy(0, 220)"
            )

            page.wait_for_timeout(150)

            second_sticky_box = inning_picker.bounding_box()
            assert second_sticky_box is not None
            assert 54 <= second_sticky_box['y'] <= 60

            assert abs(
                second_sticky_box['y'] -
                first_sticky_box['y']
            ) <= 2

            rotation_table = page.locator(
                '#rotationMatrixCollapse'
            )

            expect(
                rotation_table
            ).to_be_visible(timeout=15_000)

            expect(
                rotation_table
            ).to_have_class(
                re.compile(r'\bshow\b')
            )

            player_time = page.locator(
                '#gm-playing-time-report'
            )

            expect(
                player_time
            ).to_be_visible(timeout=15_000)

            player_time_collapse = page.locator(
                '#gmPlayingTimeCollapse'
            )

            expect(
                player_time_collapse
            ).to_be_hidden()

            bench_summary = page.locator(
                '#benchReportDesktopCollapse'
            )

            expect(
                bench_summary
            ).to_be_hidden()

            order = page.evaluate(
                """() => {
                    const panel = document.getElementById(
                        'pregame-defense-editor-v3'
                    );
                    const rotationCollapse = document.getElementById(
                        'rotationMatrixCollapse'
                    );
                    const rotation = rotationCollapse?.closest(
                        '.d-none.d-lg-block'
                    ) || rotationCollapse?.closest('.card');
                    const playerTime = document.getElementById(
                        'gm-playing-time-report'
                    );
                    const benchCollapse = document.getElementById(
                        'benchReportDesktopCollapse'
                    );
                    const bench = benchCollapse?.closest(
                        '.d-none.d-lg-block'
                    ) || benchCollapse?.closest('.card');

                    const before = (a, b) => Boolean(
                        a &&
                        b &&
                        (
                            a.compareDocumentPosition(b) &
                            Node.DOCUMENT_POSITION_FOLLOWING
                        )
                    );

                    return {
                        panelBeforeRotation:before(panel, rotation),
                        rotationBeforePlayerTime:before(
                            rotation,
                            playerTime
                        ),
                        playerTimeBeforeBench:before(
                            playerTime,
                            bench
                        ),
                    };
                }"""
            )

            assert order == {
                'panelBeforeRotation': True,
                'rotationBeforePlayerTime': True,
                'playerTimeBeforeBench': True,
            }

            # James's player-time information is still available.
            player_time.locator(
                '.gm-playing-time-toggle'
            ).click()

            expect(
                player_time_collapse
            ).to_be_visible()

            expect(
                player_time_collapse.locator(
                    '.pde-time-row'
                )
            ).not_to_have_count(0)

        else:
            # Portrait tablet keeps the established compact planner
            # presentation; this landscape change must not remove the
            # original player-time information.
            expect(
                page.locator('#gm-playing-time-report')
            ).to_have_count(0)

            expect(
                defense.locator(
                    '#pde-playing-time-summary'
                )
            ).to_be_visible()

        pitching = page.locator('#pitcher-availability-card')
        expect(pitching).to_be_visible(timeout=15_000)
        pitcher_cards = pitching.locator('.gpa-card')
        expect(pitcher_cards).not_to_have_count(0)
        expect(pitcher_cards.first.locator('.gpa-metrics')).to_be_visible()
        expect(pitcher_cards.first.locator('.gm-pitch-card-more')).to_be_hidden()

        assert page.evaluate(
            'document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2'
        )
    finally:
        page.request.post(
            f'{coachboard_url}/game-day/{game_id}/delete',
            headers={'Accept': 'application/json'},
        )


def test_phone_landscape_keeps_innings_sticky_while_scrolling(
    page: Page,
    coachboard_url: str,
):
    """Keep inning controls reachable on a wide phone in landscape."""
    page.set_viewport_size(
        {
            'width': 955,
            'height': 440,
        }
    )

    login(page, coachboard_url)

    opponent = 'iPhone Landscape Prep UX Opponent'

    created = page.request.post(
        f'{coachboard_url}/game-day/add',
        form={
            'game_date': '2030-01-17',
            'game_start_time': '14:00',
            'game_opponent': opponent,
            'game_location': 'Phone Landscape Test Field',
            'game_notes': (
                'Disposable phone landscape pregame UX test'
            ),
        },
    )

    assert created.ok

    games = page.request.get(
        f'{coachboard_url}/api/games'
    ).json()

    game = next(
        item
        for item in games
        if item.get('opponent') == opponent
    )

    game_id = int(game['id'])

    try:
        page.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        modes = page.locator(
            '#cb-test2-pregame-modes'
        )

        expect(
            modes
        ).to_be_visible(timeout=15_000)

        modes.get_by_role(
            'button',
            name='Full Plan',
        ).click()

        defense = page.locator(
            '#pregame-defense-editor-v3'
        )

        expect(
            defense
        ).to_be_visible(timeout=15_000)

        inning_labels = page.locator(
            '#inning-btn-group label.btn'
        )

        expect(
            inning_labels
        ).to_have_count(
            6,
            timeout=15_000,
        )

        inning_picker = page.locator(
            '#rotation-card-container '
            '.gm-coach-inning-picker'
        )

        expect(
            inning_picker
        ).to_be_visible()

        sticky = inning_picker.evaluate(
            """el => ({
                position:getComputedStyle(el).position,
                top:getComputedStyle(el).top,
            })"""
        )

        assert sticky['position'] == 'sticky'
        assert sticky['top'] == '0px'

        assert inning_picker.evaluate(
            "el => el.parentElement?.id"
        ) == 'rotation-board'

        rotation_card = page.locator(
            '#rotation-card-container > .card'
        )

        assert rotation_card.evaluate(
            "el => getComputedStyle(el).overflow"
        ) == 'visible'

        # Below 992px CoachBoard intentionally makes <main> the
        # vertical scrollport while html/body stay fixed.
        scroller = page.locator(
            'main.container-fluid'
        )

        expect(
            scroller
        ).to_be_visible()

        assert scroller.evaluate(
            "el => getComputedStyle(el).overflowY"
        ) in {'auto', 'scroll'}

        field = defense.locator(
            '.pde-field'
        )

        expect(
            field
        ).to_be_visible()

        target_scroll = field.evaluate(
            """el => {
                const scroller =
                    document.querySelector('main.container-fluid');

                const fieldBox =
                    el.getBoundingClientRect();

                const scrollBox =
                    scroller.getBoundingClientRect();

                return (
                    scroller.scrollTop +
                    fieldBox.top -
                    scrollBox.top +
                    120
                );
            }"""
        )

        scroller.evaluate(
            "(el, top) => { el.scrollTop = top; }",
            target_scroll,
        )

        page.wait_for_timeout(150)

        assert scroller.evaluate(
            "el => el.scrollTop"
        ) > 0

        # The browser window itself should remain stationary in the
        # mobile layout.
        assert page.evaluate(
            "window.scrollY"
        ) == 0

        scroll_box = scroller.bounding_box()
        first_box = inning_picker.bounding_box()

        assert scroll_box is not None
        assert first_box is not None

        # The picker lives inside rotation-board/card-body, so a small
        # intentional inset from the mobile scrollport is allowed.
        # What matters is that the inset stays fixed while scrolling.
        first_offset = (
            first_box['y'] -
            scroll_box['y']
        )

        assert 0 <= first_offset <= 20

        # Continue farther through the field. The inning selector
        # must remain pinned at the same visible offset.
        scroller.evaluate(
            "el => { el.scrollTop += 140; }"
        )

        page.wait_for_timeout(150)

        second_box = inning_picker.bounding_box()

        assert second_box is not None

        second_offset = (
            second_box['y'] -
            scroll_box['y']
        )

        assert 0 <= second_offset <= 20

        assert abs(
            second_offset -
            first_offset
        ) <= 2

        assert abs(
            second_box['y'] -
            first_box['y']
        ) <= 2

        # And prove the coach can change innings without scrolling
        # back to the top.
        inning_labels.nth(1).click()

        expect(
            page.locator(
                'input[name="inning-radio"][value="2"]'
            )
        ).to_be_checked()

        expect(
            defense.locator(
                '.pde-inning strong'
            )
        ).to_have_text(
            '2',
            timeout=10_000,
        )

        after_switch = inning_picker.bounding_box()

        assert after_switch is not None

        after_switch_offset = (
            after_switch['y'] -
            scroll_box['y']
        )

        assert 0 <= after_switch_offset <= 20

        assert abs(
            after_switch_offset -
            first_offset
        ) <= 2

        assert page.evaluate(
            """
            document.documentElement.scrollWidth
            <= document.documentElement.clientWidth + 2
            """
        )

    finally:
        page.request.post(
            f'{coachboard_url}/game-day/{game_id}/delete',
            headers={'Accept': 'application/json'},
        )
