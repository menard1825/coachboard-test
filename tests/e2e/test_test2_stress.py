"""Locked Test 2 iPhone + iPad stress pass across live-game race conditions."""

import json
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
        'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
        '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
        'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
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
            'game_start_time': '12:30', 'game_opponent': opponent,
            'game_location': 'Test 2 Stress Field', 'game_notes': 'Disposable Test 2 stress game',
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
                'title': f'{opponent} Stress Rotation', 'innings': innings,
                'associated_game_id': game_id,
            },
        )
        assert rotation.status == 200, rotation.text()
        assert rotation.json().get('status') == 'success', rotation.json()
    return game_id


def current_sequence(state):
    return max([0] + [int(event.get('sequence') or 0) for event in state.get('rotation_events', []) if not event.get('reverted')])


def cleanup_game(page: Page, coachboard_url: str, game_id: int):
    state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state')
    if state.ok and state.json().get('game', {}).get('is_live'):
        page.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/end-with-pitching',
            data={'defer_pitching': True, 'end_reason': 'manual', 'current_inning_played': True},
        )
    page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})


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

        phone_ready = phone.request.get(f'{coachboard_url}/api/game-day/{game_id}/readiness').json()
        ipad_ready = ipad.request.get(f'{coachboard_url}/api/game-day/{game_id}/readiness').json()
        for ready in (phone_ready, ipad_ready):
            assert ready['readiness']['lineup_ready'] is False
            assert ready['ready'] is True, ready
            assert ready['missing'] == []

        # Both browsers must be attached to the game room before testing the
        # cross-client start transition. This tests synchronization rather than
        # racing page boot against the first server broadcast.
        expect(phone.locator('#live-sync-status-v2')).to_contain_text('SYNCED', timeout=10_000)
        expect(ipad.locator('#live-sync-status-v2')).to_contain_text('SYNCED', timeout=10_000)
        ipad.wait_for_timeout(500)

        phone_start = phone.locator('#gm-mobile-start-game')
        expect(phone_start).to_be_visible(timeout=15_000)
        phone_start.click()
        expect(phone.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        expect(ipad.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        expect(phone.locator('#live-inning-display')).to_have_text('1')
        expect(ipad.locator('#live-inning-display')).to_have_text('1')

        # NEXT is automatically seeded when Live Game starts.
        #
        # With an Inning 2 pregame defense available, the automatic NEXT
        # draft should already contain that planned defense. The coach can
        # edit it immediately; no separate lock/confirm step is required.
        prep = phone.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep'
        ).json()

        assert prep['planned_alignment']
        assert prep['confirmed'] is not None
        assert prep['confirmed']['inning'] == '2'
        assert prep['confirmed']['source'] == 'planned'
        assert prep['confirmed']['alignment']

        # End Inning now applies the prepared NEXT defense directly.
        # There is no separate huddle / Start Inning confirmation.
        next_alignment = dict(prep['confirmed']['alignment'])

        phone.locator('#liveEndInningBtn').click()

        expect(
            phone.locator('#live-inning-display')
        ).to_have_text(
            '2',
            timeout=15_000,
        )

        expect(
            ipad.locator('#live-inning-display')
        ).to_have_text(
            '2',
            timeout=15_000,
        )

        expect(
            phone.locator('#cb-test2-huddle-modal')
        ).to_have_count(0)

        expect(
            phone.locator('#cb-live-field-editor')
        ).to_have_count(0)

        phone_after_advance = phone.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        ).json()

        ipad_after_advance = ipad.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        ).json()

        assert phone_after_advance['current_inning'] == '2'
        assert ipad_after_advance['current_inning'] == '2'
        assert phone_after_advance['current_alignment'] == next_alignment
        assert ipad_after_advance['current_alignment'] == next_alignment

        quick = phone.locator('#cbQuickDefense')
        quick.locator('[data-cb-position="SS"]').click()
        move = phone.locator('#cbQuickMoveModal')
        expect(move).to_be_visible(timeout=10_000)
        move.locator('[data-cb-destination="2B"]').click()
        expect(move).not_to_be_visible(timeout=10_000)
        expect(quick.locator('.cb-save-state')).to_contain_text('Saved', timeout=10_000)
        phone.locator('#liveUndoBtn').click()

        # Undo must restore the authoritative Inning 2 alignment without
        # invoking any retired huddle/editor workflow.
        expect(
            phone.locator('#live-inning-display')
        ).to_have_text(
            '2',
            timeout=10_000,
        )

        expect(
            phone.locator('#cb-test2-huddle-modal')
        ).to_have_count(0)

        expect(
            phone.locator('#cb-live-field-editor')
        ).to_have_count(0)

        state = phone.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        inflight = dict(state['current_alignment'])
        inflight['1B'], inflight['3B'] = inflight['3B'], inflight['1B']
        phone.evaluate(
            """({gameId, alignment, baseSequence}) => {
                fetch(`/api/live-game/${gameId}/defense-edit`, {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({alignment, base_sequence: baseSequence}), keepalive: true,
                });
                window.location.assign('/game-day');
            }""",
            {'gameId': game_id, 'alignment': inflight, 'baseSequence': current_sequence(state)},
        )
        expect(phone).to_have_url(re.compile(r'/game-day$'), timeout=10_000)
        phone.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
        expect(phone.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)
        authoritative = phone.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert authoritative['current_alignment'] in (state['current_alignment'], inflight)
        expect(phone.locator('#cbQuickDefense .cb-main-draft-banner')).to_have_count(0)

        phone_state = phone.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        ipad_state = ipad.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
        assert phone_state['game']['is_live'] is True
        assert ipad_state['game']['is_live'] is True
        assert phone_state['current_inning'] == ipad_state['current_inning'] == '2'
        assert phone_state['current_alignment'] == ipad_state['current_alignment']

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



def test_test2_offline_quick_field_recovers_authoritative_state(
    browser: Browser,
    coachboard_url: str,
):
    coach_a_context = browser.new_context(
        viewport={'width': 390, 'height': 844}
    )
    coach_b_context = browser.new_context(
        viewport={'width': 390, 'height': 844}
    )

    coach_a = coach_a_context.new_page()
    coach_b = coach_b_context.new_page()
    game_id = None

    try:
        login(coach_a, coachboard_url)
        login(coach_b, coachboard_url)

        game_id = create_game(
            coach_a,
            coachboard_url,
            'Test 2 Offline Recovery Opponent',
            include_inning_two=False,
        )

        coach_a.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        coach_b.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        expect(
            coach_a.locator('#live-sync-status-v2')
        ).to_contain_text(
            'SYNCED',
            timeout=10_000,
        )

        expect(
            coach_b.locator('#live-sync-status-v2')
        ).to_contain_text(
            'SYNCED',
            timeout=10_000,
        )

        coach_a_start = coach_a.locator(
            '#gm-mobile-start-game'
        )
        expect(
            coach_a_start
        ).to_be_visible(timeout=15_000)
        coach_a_start.click()

        quick_a = coach_a.locator('#cbQuickDefense')
        quick_b = coach_b.locator('#cbQuickDefense')

        expect(quick_a).to_be_visible(timeout=15_000)
        expect(quick_b).to_be_visible(timeout=15_000)

        # Open the Quick Field move sheet while Coach B still has
        # network. Chromium's context-level offline emulation can race
        # Playwright locator auto-waiting if we try to open the sheet
        # only after networking has been disabled.
        quick_b.locator(
            '[data-cb-position="SS"]'
        ).click()

        move_b = coach_b.locator('#cbQuickMoveModal')

        expect(move_b).to_be_visible(timeout=10_000)

        expect(
            move_b.locator(
                '[data-cb-destination="2B"]'
            )
        ).to_be_visible(timeout=10_000)

        # Coach B now loses all network.
        #
        # Chromium's offline transition is asynchronous enough that a
        # request fired immediately after set_offline(True) can sometimes
        # escape before the browser has actually entered offline mode.
        # That made this stress test nondeterministic on otherwise
        # unchanged builds.
        failed_defense_edits = []

        coach_b.on(
            'requestfailed',
            lambda request: (
                failed_defense_edits.append(request.url)
                if (
                    f'/api/live-game/{game_id}/defense-edit'
                    in request.url
                )
                else None
            ),
        )

        coach_b_context.set_offline(True)

        for _ in range(50):
            if coach_b.evaluate(
                'navigator.onLine === false'
            ):
                break

            coach_b.wait_for_timeout(100)

        assert coach_b.evaluate(
            'navigator.onLine === false'
        ), (
            'Chromium never entered offline mode '
            'before the defensive write.'
        )

        # Trigger the already-rendered destination button directly in
        # the page. The application still executes its normal
        # /defense-edit fetch, which must fail because the browser is
        # offline. This avoids making Playwright itself auto-wait for a
        # locator after Chromium networking has been disabled.
        coach_b.evaluate(
            """() => {
                const button = document.querySelector(
                    '#cbQuickMoveModal [data-cb-destination="2B"]'
                );

                if (!button) {
                    throw new Error(
                        'Offline test destination button disappeared.'
                    );
                }

                button.click();
            }"""
        )

        # Do not assert the UI error until we have independently proved
        # that the defensive write really reached Chromium's failed-
        # request path. This keeps the test from racing offline emulation.
        for _ in range(50):
            if failed_defense_edits:
                break

            coach_b.wait_for_timeout(100)

        assert failed_defense_edits, (
            'Expected the offline /defense-edit request to fail, '
            'but Chromium reported no failed defensive write.'
        )

        expect(
            quick_b.locator('.cb-save-state')
        ).to_contain_text(
            'Not saved',
            timeout=10_000,
        )

        # While B is offline, Coach A changes the actual live field.
        quick_a.locator(
            '[data-cb-position="1B"]'
        ).click()

        move_a = coach_a.locator('#cbQuickMoveModal')

        expect(move_a).to_be_visible(timeout=10_000)

        move_a.locator(
            '[data-cb-destination="3B"]'
        ).click()

        expect(move_a).not_to_be_visible(timeout=10_000)

        expect(
            quick_a.locator('.cb-save-state')
        ).to_contain_text(
            'Saved',
            timeout=10_000,
        )

        authoritative = coach_a.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        ).json()

        assert (
            authoritative['current_alignment']['1B']
            == 'Third Theo'
        )
        assert (
            authoritative['current_alignment']['3B']
            == 'First Frank'
        )

        # Prove recovery happens in-place, without a browser reload.
        coach_b.evaluate(
            "window.__cbOfflineRecoveryStayedOnPage = 'yes'"
        )

        coach_b_context.set_offline(False)

        expect(
            coach_b.locator('#live-sync-status-v2')
        ).to_contain_text(
            'SYNCED',
            timeout=15_000,
        )

        expect(move_b).not_to_be_visible(timeout=15_000)

        expect(
            quick_b.locator('.cb-save-state')
        ).to_contain_text(
            'Reconnected',
            timeout=15_000,
        )

        expect(
            quick_b.locator('[data-cb-position="1B"]')
        ).to_contain_text(
            'Third Theo',
            timeout=15_000,
        )

        expect(
            quick_b.locator('[data-cb-position="3B"]')
        ).to_contain_text(
            'First Frank',
            timeout=15_000,
        )

        # The offline SS -> 2B attempt never reached the server.
        expect(
            quick_b.locator('[data-cb-position="SS"]')
        ).to_contain_text(
            'Shortstop Shawn',
            timeout=15_000,
        )

        expect(
            quick_b.locator('[data-cb-position="2B"]')
        ).to_contain_text(
            'Second Sam',
            timeout=15_000,
        )

        assert (
            coach_b.evaluate(
                'window.__cbOfflineRecoveryStayedOnPage'
            )
            == 'yes'
        )

        recovered = coach_b.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        ).json()

        assert (
            recovered['current_alignment']
            == authoritative['current_alignment']
        )

        assert recovered['current_inning'] == '1'

    finally:
        try:
            coach_b_context.set_offline(False)
        except Exception:
            pass

        if game_id is not None:
            cleanup_game(
                coach_a,
                coachboard_url,
                game_id,
            )

        coach_a_context.close()
        coach_b_context.close()


def test_test2_drag_survives_remote_live_redraw(
    browser: Browser,
    coachboard_url: str,
):
    """
    Concurrent Quick Field regression.

    A coach begins dragging SS while another coach saves a real live
    defensive change.

    Either concurrency outcome is valid:

    * the drag rebases on current state and saves, preserving both changes; or
    * optimistic concurrency rejects the drag with stale_live_state.

    What must never happen is for the phone to visually roll the field back
    to the older alignment after it has already rendered the newer remote
    defense.
    """
    phone_context = browser.new_context(
        viewport={'width': 390, 'height': 844}
    )
    ipad_context = browser.new_context(
        viewport={'width': 768, 'height': 1024}
    )

    phone = phone_context.new_page()
    ipad = ipad_context.new_page()

    game_id = None
    mouse_down = False
    dialogs = []

    phone.on(
        'dialog',
        lambda dialog: (
            dialogs.append(dialog.message),
            dialog.dismiss(),
        ),
    )

    try:
        login(phone, coachboard_url)
        login(ipad, coachboard_url)

        game_id = create_game(
            phone,
            coachboard_url,
            'Test 2 Drag Redraw Race Opponent',
        )

        started = phone.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/start',
            data={},
        )

        assert started.status == 200, started.text()
        assert started.json().get('status') == 'success'

        phone.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        ipad.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        phone_quick = phone.locator('#cbQuickDefense')
        ipad_quick = ipad.locator('#cbQuickDefense')

        expect(phone_quick).to_be_visible(timeout=15_000)
        expect(ipad_quick).to_be_visible(timeout=15_000)

        expect(
            phone.locator('#live-sync-status-v2')
        ).to_contain_text(
            'SYNCED',
            timeout=10_000,
        )

        expect(
            ipad.locator('#live-sync-status-v2')
        ).to_contain_text(
            'SYNCED',
            timeout=10_000,
        )

        source = phone_quick.locator(
            '[data-cb-position="SS"]'
        )

        expect(source).to_contain_text(
            'Shortstop Shawn'
        )

        expect(source).to_be_visible(
            timeout=10_000,
        )

        source.scroll_into_view_if_needed()

        source_box = None

        for _ in range(20):
            source_box = source.bounding_box()

            if source_box is not None:
                break

            phone.wait_for_timeout(50)

        assert source_box is not None

        source_x = (
            source_box['x'] +
            source_box['width'] / 2
        )
        source_y = (
            source_box['y'] +
            source_box['height'] / 2
        )

        phone.evaluate(
            """
            () => {
                const source = document.querySelector(
                    '#cbQuickDefense [data-cb-position="SS"]'
                );
                source.dataset.cbRaceToken = 'held-before-redraw';
            }
            """
        )

        phone.mouse.move(
            source_x,
            source_y,
        )

        phone.mouse.down()
        mouse_down = True

        # Stay below the 8px drag threshold.
        phone.mouse.move(
            source_x + 4,
            source_y,
        )

        remote_before_response = ipad.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        )

        assert remote_before_response.status == 200

        remote_before = remote_before_response.json()

        original_alignment = dict(
            remote_before['current_alignment']
        )

        remote_alignment = dict(
            original_alignment
        )

        remote_alignment['1B'], remote_alignment['3B'] = (
            remote_alignment['3B'],
            remote_alignment['1B'],
        )

        remote_write = ipad.request.post(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/defense-edit',
            data={
                'alignment': remote_alignment,
                'base_sequence': current_sequence(
                    remote_before
                ),
            },
        )

        assert remote_write.status == 200, (
            remote_write.text()
        )

        remote_payload = remote_write.json()

        assert (
            remote_payload.get('status')
            == 'success'
        ), remote_payload

        # The phone has definitely rendered the newer remote defense.
        expect(
            phone_quick.locator(
                '[data-cb-position="1B"]'
            )
        ).to_contain_text(
            remote_alignment['1B'],
            timeout=10_000,
        )

        expect(
            phone_quick.locator(
                '[data-cb-position="3B"]'
            )
        ).to_contain_text(
            remote_alignment['3B'],
            timeout=10_000,
        )

        # Prove the redraw replaced the element that received pointerdown.
        assert (
            phone_quick.locator(
                '[data-cb-position="SS"]'
            ).get_attribute(
                'data-cb-race-token'
            )
            is None
        )

        destination = phone_quick.locator(
            '[data-cb-position="2B"]'
        )

        expect(destination).to_be_visible(
            timeout=10_000,
        )

        destination_box = None

        for _ in range(20):
            destination_box = destination.bounding_box()

            if destination_box is not None:
                break

            phone.wait_for_timeout(50)

        assert destination_box is not None

        destination_x = (
            destination_box['x'] +
            destination_box['width'] / 2
        )
        destination_y = (
            destination_box['y'] +
            destination_box['height'] / 2
        )

        # Start an rAF sampler BEFORE pointerup. From this moment forward,
        # 1B/3B must never revert to the pre-iPad alignment.
        phone.evaluate(
            """
            () => {
                const read = position => (
                    document.querySelector(
                        `#cbQuickDefense `
                        + `[data-cb-position="${position}"]`
                    )?.dataset?.cbMovePlayer || null
                );

                window.__cbConcurrencySamples = [];

                const started = performance.now();

                const sample = () => {
                    window.__cbConcurrencySamples.push({
                        elapsed: performance.now() - started,
                        oneB: read('1B'),
                        twoB: read('2B'),
                        threeB: read('3B'),
                        ss: read('SS'),
                    });

                    if (performance.now() - started < 1500) {
                        requestAnimationFrame(sample);
                    }
                };

                sample();
            }
            """
        )

        phone.mouse.move(
            destination_x,
            destination_y,
        )

        endpoint = (
            f'/api/live-game/{game_id}/defense-edit'
        )

        with phone.expect_response(
            lambda response: (
                endpoint in response.url
                and response.request.method == 'POST'
            ),
            timeout=10_000,
        ) as save_response_info:
            phone.mouse.up()
            mouse_down = False

        save_response = save_response_info.value
        save_payload = save_response.json()

        # Allow the sampler to span the full stale-error recovery window.
        phone.wait_for_timeout(1700)

        samples = phone.evaluate(
            "() => window.__cbConcurrencySamples || []"
        )

        assert samples

        stale_visual_samples = [
            sample
            for sample in samples
            if (
                sample.get('oneB')
                == original_alignment['1B']
                and sample.get('threeB')
                == original_alignment['3B']
            )
        ]

        assert not stale_visual_samples, (
            'Quick Field visually rolled back to the stale '
            'pre-remote defense after already showing the '
            'newer coach change. Samples: '
            f'{stale_visual_samples[:10]}'
        )

        final_state_response = phone.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        )

        assert final_state_response.status == 200

        final_state = final_state_response.json()

        if save_response.status == 200:
            assert save_payload.get('status') == 'success'

            # Remote 1B/3B edit and local SS/2B drag both survived.
            assert (
                final_state['current_alignment']['1B']
                == remote_alignment['1B']
            )
            assert (
                final_state['current_alignment']['3B']
                == remote_alignment['3B']
            )
            assert (
                final_state['current_alignment']['2B']
                == 'Shortstop Shawn'
            )
            assert (
                final_state['current_alignment']['SS']
                == 'Second Sam'
            )

            expect(
                phone_quick.locator('.cb-save-state')
            ).to_contain_text(
                'Saved',
                timeout=10_000,
            )

        else:
            # First accepted coach wins. The rejected drag must not be
            # automatically merged/retried over newer authoritative state.
            assert save_response.status == 409
            assert (
                save_payload.get('code')
                == 'stale_live_state'
            )

            authoritative = dict(
                save_payload['current_alignment']
            )

            assert (
                authoritative
                == remote_alignment
            )

            assert (
                final_state['current_alignment']
                == remote_alignment
            )

            assert dialogs
            assert any(
                'not saved' in message.lower()
                for message in dialogs
            )

            # The visible field must already be the authoritative winner.
            for position in ('1B', '2B', '3B', 'SS'):
                assert (
                    phone_quick.locator(
                        f'[data-cb-position="{position}"]'
                    ).get_attribute(
                        'data-cb-move-player'
                    )
                    == remote_alignment[position]
                )

    finally:
        if mouse_down:
            try:
                phone.mouse.up()
            except Exception:
                pass

        if game_id is not None:
            cleanup_game(
                phone,
                coachboard_url,
                game_id,
            )

        phone_context.close()
        ipad_context.close()


def test_test2_end_inning_uses_latest_remote_next_prep(
    browser: Browser,
    coachboard_url: str,
):
    """
    Regression probe for multi-coach NEXT ownership.

    Deliberately keep the phone's local NEXT board stale while another
    coach changes the server-side NEXT prep. End Inning must perform its
    authoritative GET and advance using the newest server prep, not the
    stale in-memory phone draft.
    """
    phone_context = browser.new_context(
        viewport={'width': 390, 'height': 844}
    )
    ipad_context = browser.new_context(
        viewport={'width': 768, 'height': 1024}
    )

    phone = phone_context.new_page()
    ipad = ipad_context.new_page()

    game_id = None
    stale_route = None

    try:
        login(phone, coachboard_url)
        login(ipad, coachboard_url)

        game_id = create_game(
            phone,
            coachboard_url,
            'Test 2 Latest NEXT Opponent',
        )

        started = phone.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/start',
            data={},
        )

        assert started.status == 200, started.text()
        assert started.json().get('status') == 'success'

        phone.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        ipad.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        expect(
            phone.locator('#cbQuickDefense')
        ).to_be_visible(
            timeout=15_000,
        )

        expect(
            ipad.locator('#cbQuickDefense')
        ).to_be_visible(
            timeout=15_000,
        )

        phone.locator(
            '[data-now-next="next"]'
        ).click()

        next_board = phone.locator(
            '#live-board-prep-v3'
        )

        expect(next_board).to_be_visible(
            timeout=10_000,
        )

        stale_prep = phone.request.get(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/next-inning-prep'
        ).json()

        assert stale_prep['confirmed']
        stale_alignment = dict(
            stale_prep['confirmed']['alignment']
        )

        # Disconnect the phone's socket and freeze periodic NEXT GETs
        # at the old response. This deliberately creates the situation
        # Claude was concerned about: the visible phone copy is stale.
        phone.evaluate(
            """
            () => {
                window.__cbLiveGameSocket?.disconnect?.();
            }
            """
        )

        stale_route = (
            f'**/api/live-game/'
            f'{game_id}/next-inning-prep'
        )

        phone.route(
            stale_route,
            lambda route: route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps(stale_prep),
            ),
        )

        remote_alignment = dict(
            stale_alignment
        )

        remote_alignment['C'], remote_alignment['1B'] = (
            remote_alignment['1B'],
            remote_alignment['C'],
        )

        remote_save = ipad.request.post(
            f'{coachboard_url}/api/live-game/'
            f'{game_id}/next-inning-prep',
            data={
                'mode': 'custom',
                'alignment': remote_alignment,
            },
        )

        assert remote_save.status == 200, (
            remote_save.text()
        )

        remote_payload = remote_save.json()

        assert (
            remote_payload.get('status')
            == 'success'
        ), remote_payload

        assert (
            remote_payload['confirmed']['alignment']
            == remote_alignment
        )

        phone.wait_for_timeout(500)

        # The phone really is still displaying/holding the old NEXT.
        local_alignment = phone.evaluate(
            """
            () => (
                window.CBNextDefense?.getAlignment?.()
                || null
            )
            """
        )

        assert local_alignment == stale_alignment
        assert local_alignment != remote_alignment

        # Release the artificial stale GET before End Inning.
        # live_game_contract.js must now fetch the authoritative server
        # prep and use that rather than CBNextDefense.getAlignment().
        phone.unroute(stale_route)
        stale_route = None

        phone.locator(
            '#liveEndInningBtn'
        ).click()

        expect(
            phone.locator(
                '#live-inning-display'
            )
        ).to_have_text(
            '2',
            timeout=15_000,
        )

        final_state = phone.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        ).json()

        assert final_state['current_inning'] == '2'

        assert (
            final_state['current_alignment']
            == remote_alignment
        )

        # Specifically prove the remote coach's NEXT swap won.
        assert (
            final_state['current_alignment']['C']
            == stale_alignment['1B']
        )

        assert (
            final_state['current_alignment']['1B']
            == stale_alignment['C']
        )

    finally:
        if stale_route is not None:
            try:
                phone.unroute(stale_route)
            except Exception:
                pass

        if game_id is not None:
            cleanup_game(
                phone,
                coachboard_url,
                game_id,
            )

        phone_context.close()
        ipad_context.close()


def test_test2_stale_recovery_authoritative_open_does_not_freeze_quick_field(
    browser: Browser,
    coachboard_url: str,
):
    """
    Regression for the `.cb-main-open` / authoritative-open interaction.

    When a drag loses the optimistic-concurrency race and the authoritative
    alignment the server returns has a genuinely open position, Quick Field
    may keep showing that position as open. It must NOT reuse `.cb-main-open`
    to do it: live_game_dugout_mode.js and live_game_feedback_pass.js both
    treat the presence of `.cb-main-open` anywhere in #cbQuickDefense as "a
    local draft owns this DOM, do not repaint" and will otherwise stay
    frozen indefinitely, since draft is null and nothing else clears it.

    This proves the open marker survives as a visual-only class and that a
    later real remote defensive change still repaints the phone normally.
    """
    phone_context = browser.new_context(
        viewport={'width': 390, 'height': 844}
    )
    ipad_context = browser.new_context(
        viewport={'width': 768, 'height': 1024}
    )

    phone = phone_context.new_page()
    ipad = ipad_context.new_page()

    game_id = None
    stale_route = None
    mouse_down = False
    dialogs = []

    phone.on(
        'dialog',
        lambda dialog: (
            dialogs.append(dialog.message),
            dialog.dismiss(),
        ),
    )

    try:
        login(phone, coachboard_url)
        login(ipad, coachboard_url)

        game_id = create_game(
            phone,
            coachboard_url,
            'Test 2 Authoritative Open Opponent',
        )

        started = phone.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/start',
            data={},
        )

        assert started.status == 200, started.text()
        assert started.json().get('status') == 'success'

        phone.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        ipad.goto(
            f'{coachboard_url}/game/{game_id}',
            wait_until='domcontentloaded',
        )

        phone_quick = phone.locator('#cbQuickDefense')

        expect(phone_quick).to_be_visible(timeout=15_000)
        expect(ipad.locator('#cbQuickDefense')).to_be_visible(timeout=15_000)

        expect(
            phone.locator('#live-sync-status-v2')
        ).to_contain_text('SYNCED', timeout=10_000)

        expect(
            ipad.locator('#live-sync-status-v2')
        ).to_contain_text('SYNCED', timeout=10_000)

        before_response = phone.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        )
        assert before_response.status == 200
        before = before_response.json()

        # Simulate a rejected save whose authoritative alignment leaves
        # 1B genuinely open (e.g. an ejected/absent fielder not yet
        # replaced), which is exactly the case the preserveOpen fix targets.
        authoritative_open = dict(before['current_alignment'])
        authoritative_open['1B'] = ''

        stale_route = f'**/api/live-game/{game_id}/defense-edit'

        def stale_drag_response(route):
            if route.request.method != 'POST':
                route.continue_()
                return
            route.fulfill(
                status=409,
                content_type='application/json',
                body=json.dumps({
                    'status': 'error',
                    'code': 'stale_live_state',
                    'message': (
                        'Another coach changed the live game first. '
                        'Review the updated field before saving.'
                    ),
                    'current_sequence': current_sequence(before) + 1,
                    'current_inning': before.get('current_inning') or '1',
                    'current_alignment': authoritative_open,
                }),
            )

        phone.route(stale_route, stale_drag_response)

        source = phone_quick.locator('[data-cb-position="SS"]')
        destination = phone_quick.locator('[data-cb-position="2B"]')

        expect(source).to_be_visible(timeout=10_000)
        expect(destination).to_be_visible(timeout=10_000)

        source.scroll_into_view_if_needed()

        source_box = None
        destination_box = None
        for _ in range(20):
            source_box = source.bounding_box()
            destination_box = destination.bounding_box()
            if source_box is not None and destination_box is not None:
                break
            phone.wait_for_timeout(50)

        assert source_box is not None
        assert destination_box is not None

        source_x = source_box['x'] + source_box['width'] / 2
        source_y = source_box['y'] + source_box['height'] / 2
        destination_x = destination_box['x'] + destination_box['width'] / 2
        destination_y = destination_box['y'] + destination_box['height'] / 2

        phone.mouse.move(source_x, source_y)
        phone.mouse.down()
        mouse_down = True
        phone.mouse.move(destination_x, destination_y, steps=4)

        endpoint = f'/api/live-game/{game_id}/defense-edit'
        with phone.expect_response(
            lambda response: (
                endpoint in response.url
                and response.request.method == 'POST'
            ),
            timeout=10_000,
        ) as response_info:
            phone.mouse.up()
            mouse_down = False

        stale_response = response_info.value
        assert stale_response.status == 409
        assert stale_response.json().get('code') == 'stale_live_state'

        phone.unroute(stale_route)
        stale_route = None

        open_spot = phone_quick.locator('[data-cb-position="1B"]')

        expect(open_spot).to_contain_text(
            'Open — choose player', timeout=10_000,
        )

        # An authoritative Open position is now intentionally actionable:
        # the coach can tap it and choose a bench player. It must remain
        # visually authoritative without becoming a frozen local draft.
        expect(open_spot).to_be_enabled()

        assert open_spot.evaluate(
            "el => el.classList.contains('cb-authoritative-open')"
        )
        assert not open_spot.evaluate(
            "el => el.classList.contains('cb-main-open')"
        )

        expect(
            phone_quick.locator('.cb-main-draft-banner')
        ).to_have_count(0)

        assert dialogs
        assert any('not saved' in message.lower() for message in dialogs)

        # This is the regression assertion: a real remote defensive change
        # must still repaint the phone's Quick Field normally. Before the
        # fix, the lingering `.cb-main-open` from the stale-recovery path
        # made live_game_dugout_mode.js's and live_game_feedback_pass.js's
        # "a draft owns this DOM" guards refuse to repaint forever.
        remote_state_response = ipad.request.get(
            f'{coachboard_url}/api/live-game/{game_id}/state'
        )
        assert remote_state_response.status == 200
        remote_state = remote_state_response.json()

        remote_alignment = dict(remote_state['current_alignment'])
        remote_alignment['3B'], remote_alignment['C'] = (
            remote_alignment['C'],
            remote_alignment['3B'],
        )

        remote_write = ipad.request.post(
            f'{coachboard_url}/api/live-game/{game_id}/defense-edit',
            data={
                'alignment': remote_alignment,
                'base_sequence': current_sequence(remote_state),
            },
        )

        assert remote_write.status == 200, remote_write.text()
        assert remote_write.json().get('status') == 'success'

        expect(
            phone_quick.locator('[data-cb-position="3B"]')
        ).to_contain_text(remote_alignment['3B'], timeout=10_000)

        expect(
            phone_quick.locator('[data-cb-position="C"]')
        ).to_contain_text(remote_alignment['C'], timeout=10_000)

    finally:
        if mouse_down:
            try:
                phone.mouse.up()
            except Exception:
                pass

        if stale_route is not None:
            try:
                phone.unroute(stale_route)
            except Exception:
                pass

        if game_id is not None:
            cleanup_game(phone, coachboard_url, game_id)

        phone_context.close()
        ipad_context.close()
