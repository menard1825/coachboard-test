"""Browser coverage for the richer CoachBoard season stats dashboard."""

import json
import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


STATS_PAYLOAD = {
    'status': 'success',
    'scope': {'name': 'season', 'label': 'Full Season', 'start': None, 'end': None},
    'summary': {
        'games': 4,
        'games_with_defensive_data': 4,
        'practices': 3,
        'team_attendance_pct': 96,
        'avg_available_per_game': 8.7,
        'defensive_innings_recorded': 24,
        'team_pitching_innings': '8.0',
        'team_pitching_pitches': 138,
        'pitch_history_complete': True,
    },
    'player_usage': [
        {
            'player_id': 1,
            'name': 'Pitcher Pat',
            'available_games': 4,
            'defensive_games': 4,
            'field_innings': 5,
            'bench_innings': 1,
            'bench_pct': 17,
            'position_variety': 2,
            'positions': {'P': 3, '1B': 2},
            'flags': [],
            'live_field_innings': 5,
            'legacy_field_innings': 0,
            'game_attendance_pct': 100,
            'practice_attendance_pct': 100,
        },
        {
            'player_id': 2,
            'name': 'Catcher Cole',
            'available_games': 4,
            'defensive_games': 4,
            'field_innings': 5,
            'bench_innings': 1,
            'bench_pct': 17,
            'position_variety': 2,
            'positions': {'C': 4, '3B': 1},
            'flags': ['Heavy catcher workload'],
            'live_field_innings': 5,
            'legacy_field_innings': 0,
            'game_attendance_pct': 100,
            'practice_attendance_pct': 100,
        },
        {
            'player_id': 3,
            'name': 'Utility Uma',
            'available_games': 4,
            'defensive_games': 4,
            'field_innings': 6,
            'bench_innings': 0,
            'bench_pct': 0,
            'position_variety': 3,
            'positions': {'SS': 2, '2B': 2, 'CF': 2},
            'flags': [],
            'live_field_innings': 4,
            'legacy_field_innings': 2,
            'game_attendance_pct': 100,
            'practice_attendance_pct': 67,
        },
    ],
    'attendance': [
        {'player_id': 1, 'name': 'Pitcher Pat', 'games_present': 4, 'games_total': 4, 'games_missed': 0, 'game_attendance_pct': 100, 'practices_present': 3, 'practices_total': 3, 'practices_missed': 0, 'practice_attendance_pct': 100},
        {'player_id': 2, 'name': 'Catcher Cole', 'games_present': 4, 'games_total': 4, 'games_missed': 0, 'game_attendance_pct': 100, 'practices_present': 3, 'practices_total': 3, 'practices_missed': 0, 'practice_attendance_pct': 100},
        {'player_id': 3, 'name': 'Utility Uma', 'games_present': 4, 'games_total': 4, 'games_missed': 0, 'game_attendance_pct': 100, 'practices_present': 2, 'practices_total': 3, 'practices_missed': 1, 'practice_attendance_pct': 67},
    ],
    'pitching_usage': [
        {'player_id': 1, 'name': 'Pitcher Pat', 'appearances': 3, 'starts': 2, 'relief_appearances': 1, 'total_pitches': 138, 'total_innings': '8.0', 'innings_history_complete': True, 'pitches_per_appearance': 46.0, 'innings_per_appearance': 2.67, 'pitch_share_pct': 100, 'outs_share_pct': 100},
    ],
    'insights': [
        {'level': 'info', 'title': 'Position exposure is broadening', 'detail': 'Several players have recorded innings at multiple defensive positions.'},
    ],
    'data_quality': {
        'live_games': 3,
        'legacy_games': 1,
        'live_innings': 18,
        'legacy_innings': 6,
        'note': 'Live Game history is authoritative when available. Legacy games use the saved defensive rotation as an estimate. Mid-inning substitutions count each player who appeared in that inning once.',
    },
    'raw': {
        'position_game_appearances': {
            'Pitcher Pat': {'P': 3, '1B': 1},
            'Catcher Cole': {'C': 4, '3B': 1},
            'Utility Uma': {'SS': 2, '2B': 2, 'CF': 2},
        },
        'pitching': {},
    },
}


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


def mock_stats(page: Page):
    page.route(
        re.compile(r'.*/api/stats-dashboard\?.*'),
        lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps(STATS_PAYLOAD),
        ),
    )


def open_stats(page: Page, coachboard_url: str):
    page.goto(coachboard_url)
    page.locator('#mainTabsDesktop [href="#stats"]').evaluate(
        "el => bootstrap.Tab.getOrCreateInstance(el).show()"
    )
    expect(page.locator('[data-stats-dashboard-v3]')).to_be_visible(timeout=15_000)


def test_stats_dashboard_exposes_position_innings_and_player_drilldown(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1440, 'height': 950})
    login(page, coachboard_url)
    mock_stats(page)
    open_stats(page, coachboard_url)

    dashboard = page.locator('[data-stats-dashboard-v3]')
    expect(dashboard.get_by_role('heading', name='Team Stats & Usage')).to_be_visible()
    expect(dashboard.get_by_role('heading', name='Roster Balance Snapshot')).to_be_visible()
    expect(dashboard.get_by_role('heading', name='Defensive Innings by Position')).to_be_visible()
    expect(dashboard.get_by_role('heading', name='Team Position Coverage')).to_be_visible()

    matrix = page.locator('#sv3PositionMatrix')
    expect(matrix).to_be_visible()
    for heading in ('P', 'C', '1B', '2B', '3B', 'SS', 'CF'):
        expect(matrix.locator('thead').get_by_text(heading, exact=True)).to_be_visible()

    pat_row = matrix.locator('[data-sv3-player-row="1"]')
    expect(pat_row).to_contain_text('Pitcher Pat')
    assert pat_row.locator('td[data-position="P"]').inner_text().strip() == '3'
    assert pat_row.locator('td[data-position="1B"]').inner_text().strip() == '2'
    expect(page.locator('[data-sv3-balance]')).to_contain_text('Field inning spread')
    expect(page.locator('[data-sv3-position-summary]')).to_contain_text('inning appearances')

    pat_row.get_by_role('button', name='Pitcher Pat').click()
    modal = page.locator('#statsV2PlayerModal')
    expect(modal).to_be_visible()
    expect(modal.get_by_role('heading', name='Pitcher Pat')).to_be_visible()
    detail = modal.locator('[data-sv3-position-detail]')
    expect(detail).to_contain_text('P')
    expect(detail).to_contain_text('1B')
    expect(detail).to_contain_text('3')
    expect(detail).to_contain_text('2')
    expect(modal).to_contain_text('Pitches / App')


def test_stats_dashboard_mobile_uses_player_cards_with_position_breakdown(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    mock_stats(page)
    open_stats(page, coachboard_url)

    expect(page.locator('#sv3PositionMatrix')).to_be_hidden()
    pat_card = page.locator('[data-sv3-player-card="1"]')
    expect(pat_card).to_be_visible()
    expect(pat_card).to_contain_text('Pitcher Pat')
    expect(pat_card).to_contain_text('Innings by position')
    expect(pat_card).to_contain_text('P')
    expect(pat_card).to_contain_text('1B')
    expect(pat_card).to_contain_text('3')
    expect(pat_card).to_contain_text('2')

    geometry = page.evaluate(
        """() => ({bodyWidth: document.body.scrollWidth, viewport: innerWidth})"""
    )
    assert geometry['bodyWidth'] <= geometry['viewport'] + 1

    pat_card.get_by_role('button', name='Pitcher Pat').click()
    expect(page.locator('#statsV2PlayerModal')).to_be_visible()
    expect(page.locator('#statsV2PlayerModal [data-sv3-position-detail]')).to_be_visible()
