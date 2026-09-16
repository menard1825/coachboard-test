"""Dugout Mode shows connection health in exactly one place.

live_game_v2 owns the authoritative sync state and writes it into
#live-sync-status-v2. live_game_connection_status used to *also* place that
badge directly beneath #cbDugoutHeader and force it visible, so the live
surface carried two competing status presentations and burned a row of
vertical space saying the same thing twice.

The badge now stays in the DOM purely as a state carrier -- the header reads
its text -- and #cbDugoutHeader is the only thing that renders it. These
tests pin both halves: one visible presenter, and no loss of the reconnecting
or not-synced states that the badge used to be the only home for.
"""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

BADGE = '#live-sync-status-v2'
HEADER = '#cbDugoutHeader'
HEADER_LABEL = '#cbDugoutHeader [data-cb-live-label]'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(
        re.compile(
            rf'^{re.escape(coachboard_url)}/?'
            rf'(?:#(?:games|overview))?$'
        )
    )


def post_json(page: Page, coachboard_url: str, path: str, data, expected_status=200):
    response = page.request.post(f'{coachboard_url}{path}', data=data)
    assert response.status == expected_status, (
        f'POST {path} returned {response.status}: {response.text()}'
    )
    payload = response.json()
    if expected_status < 400:
        assert payload.get('status') == 'success', payload
    return payload


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
            'game_date': (date.today() + timedelta(days=13)).isoformat(),
            'game_start_time': '16:00',
            'game_opponent': 'Status Ownership Opponent',
            'game_location': 'Status Ownership Field',
            'game_notes': 'Disposable status ownership browser test',
            'pitching_rule_set': 'USSSA',
        },
        max_redirects=0,
    )

    assert response.status in {302, 303}
    match = re.search(r'/game/(\d+)', response.headers.get('location') or '')
    assert match
    game_id = int(match.group(1))

    post_json(
        page,
        coachboard_url,
        '/save_rotation',
        {
            'title': 'Status Ownership Rotation',
            'innings': {'1': alignment(), '2': alignment()},
            'associated_game_id': game_id,
        },
    )

    return game_id


def cleanup_game(page: Page, coachboard_url: str, game_id: int):
    """A live game left behind locks the roster for later tests."""
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


def open_dugout(page: Page, coachboard_url: str, game_id: int):
    post_json(page, coachboard_url, f'/api/live-game/{game_id}/start', {})
    page.goto(f'{coachboard_url}/game/{game_id}', wait_until='domcontentloaded')
    expect(page.locator('#live-game-overlay')).to_be_visible(timeout=15_000)
    expect(page.locator(HEADER)).to_be_visible(timeout=15_000)
    expect(page.locator('body')).to_have_class(re.compile(r'\bcb-dugout\b'), timeout=15_000)


def set_sync(page: Page, mode: str):
    """Write the badge exactly the way live_game_v2.setSyncStatus does.

    The header re-renders from a requestAnimationFrame loop, so callers can
    simply assert on the header afterwards.
    """
    markup = {
        'synced': '<span class="badge rounded-pill text-bg-success px-3 py-2">● LIVE • SYNCED</span>',
        'reconnecting': '<span class="badge rounded-pill text-bg-warning px-3 py-2">⚠ RECONNECTING…</span>',
        'offline': '<span class="badge rounded-pill text-bg-danger px-3 py-2">⚠ NOT SYNCED</span>',
    }[mode]

    page.evaluate(
        """
        (html) => {
            const badge = document.getElementById('live-sync-status-v2');
            if (!badge) throw new Error('sync badge is missing from the DOM');
            badge.innerHTML = html;
        }
        """,
        markup,
    )


def visible_status_presenters(page: Page):
    """Every visible element inside the live overlay that announces sync state.

    Counts only leaf-ish nodes so a container is not double counted with the
    text node it wraps.
    """
    return page.evaluate(
        """
        () => {
            const overlay = document.getElementById('live-game-overlay');
            if (!overlay) return [];
            const pattern = /synced|reconnecting/i;
            return [...overlay.querySelectorAll('*')]
                .filter((el) => {
                    if (!pattern.test(el.textContent || '')) return false;
                    if ([...el.children].some((c) => pattern.test(c.textContent || ''))) return false;
                    const cs = getComputedStyle(el);
                    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                })
                .map((el) => ({
                    text: (el.textContent || '').trim(),
                    id: el.id || null,
                    inHeader: Boolean(el.closest('#cbDugoutHeader')),
                }));
        }
        """
    )


def test_dugout_header_is_the_only_visible_sync_status(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_dugout(page, coachboard_url, game_id)
        set_sync(page, 'synced')

        expect(page.locator(HEADER_LABEL)).to_have_text('Live · Synced', timeout=10_000)

        # The badge is still present for the header to read, but invisible.
        expect(page.locator(BADGE)).to_have_count(1)
        expect(page.locator(BADGE)).to_be_hidden()

        presenters = visible_status_presenters(page)
        assert len(presenters) == 1, (
            f'expected exactly one visible sync presenter, got {presenters}'
        )
        assert presenters[0]['inHeader'], (
            f'the only visible sync presenter should be the dugout header, got {presenters[0]}'
        )
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_reconnecting_is_explicit_in_the_header(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_dugout(page, coachboard_url, game_id)
        set_sync(page, 'reconnecting')

        expect(page.locator(HEADER_LABEL)).to_have_text('Reconnecting…', timeout=10_000)
        expect(page.locator(HEADER)).to_have_attribute('data-cb-sync', 'reconnecting')

        presenters = visible_status_presenters(page)
        assert len(presenters) == 1, presenters
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_not_synced_is_explicit_in_the_header(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_dugout(page, coachboard_url, game_id)
        set_sync(page, 'offline')

        expect(page.locator(HEADER_LABEL)).to_have_text('Not Synced', timeout=10_000)
        expect(page.locator(HEADER)).to_have_attribute('data-cb-sync', 'offline')

        presenters = visible_status_presenters(page)
        assert len(presenters) == 1, presenters
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_paused_does_not_conceal_a_failed_connection(page: Page, coachboard_url: str):
    """The old label collapsed to plain "Paused", which hid a dead connection.
    Pause has its own affordances; it must not take over the health label."""
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_dugout(page, coachboard_url, game_id)
        set_sync(page, 'offline')
        page.evaluate("() => document.body.classList.add('cb-clock-paused')")

        expect(page.locator(HEADER_LABEL)).to_have_text('Not Synced', timeout=10_000)
        expect(page.locator(HEADER)).to_have_attribute('data-cb-sync', 'offline')

        # Pause remains legible through its own treatment rather than the
        # health label: a paused clock still reads "Paused · ...".
        expect(
            page.locator('#cbDugoutHeader [data-cb-clock-label]')
        ).to_contain_text('Paused', timeout=10_000)
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_absent_state_carrier_reads_as_reconnecting_not_healthy(page: Page, coachboard_url: str):
    """Before live_game_v2 has reported anything there is no badge at all.
    Showing "Live · Synced" then would be claiming a healthy connection the
    app has no evidence for, so the header degrades to Reconnecting instead."""
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_dugout(page, coachboard_url, game_id)
        set_sync(page, 'synced')
        expect(page.locator(HEADER_LABEL)).to_have_text('Live · Synced', timeout=10_000)

        page.evaluate(
            "() => document.getElementById('live-sync-status-v2')?.remove()"
        )

        expect(page.locator(HEADER_LABEL)).to_have_text('Reconnecting…', timeout=10_000)
        expect(page.locator(HEADER)).to_have_attribute('data-cb-sync', 'reconnecting')
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_not_synced_is_never_read_as_healthy(page: Page, coachboard_url: str):
    """"NOT SYNCED" contains the substring "SYNCED"; a naive match would call
    a dead connection healthy."""
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_dugout(page, coachboard_url, game_id)

        for raw in ('⚠ NOT SYNCED', 'NOT SYNCED', 'not synced'):
            page.evaluate(
                """
                (text) => {
                    const badge = document.getElementById('live-sync-status-v2');
                    badge.innerHTML = '<span class="badge">' + text + '</span>';
                }
                """,
                raw,
            )
            expect(page.locator(HEADER_LABEL)).to_have_text('Not Synced', timeout=10_000)
            expect(page.locator(HEADER)).to_have_attribute('data-cb-sync', 'offline')
    finally:
        cleanup_game(page, coachboard_url, game_id)


def test_health_recovers_back_to_synced(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1024, 'height': 768})
    login(page, coachboard_url)
    game_id = create_game(page, coachboard_url)

    try:
        open_dugout(page, coachboard_url, game_id)

        set_sync(page, 'offline')
        expect(page.locator(HEADER_LABEL)).to_have_text('Not Synced', timeout=10_000)

        set_sync(page, 'synced')
        expect(page.locator(HEADER_LABEL)).to_have_text('Live · Synced', timeout=10_000)
        expect(page.locator(HEADER)).to_have_attribute('data-cb-sync', 'synced')
    finally:
        cleanup_game(page, coachboard_url, game_id)
