"""Bench Report projects only the innings the game is scheduled for.

In the last scheduled inning the Next Inning defense still exists (End
Inning can start an extra inning), and the report used to project it:
"Projected to sit: 7" in a 6-inning game (walkthrough F5). It now stops at
the scheduled length. An extra inning counts once it is actually played:
the players sitting in it show as sitting now, with nothing projected past it.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from live_fixtures import (  # noqa: E402,F401 (live is a fixture)
    INNING_1,
    PHONE,
    advance_inning as _advance,
    api_url as _api,
    game_state as _state,
    live,
)


def _open_report(page, coachboard_url):
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)
    page.locator('[data-cb-bench-report]').click()
    report = page.locator('#cbBenchReportModal')
    expect(report.locator('[data-cb-br-sitting]')).to_be_visible(timeout=10_000)
    return report


def test_no_projection_past_the_scheduled_innings(live, coachboard_url):
    page = live(PHONE, plan={str(i): INNING_1 for i in range(1, 7)})
    scheduled = int(page.cb_api.request.get(_api(page, coachboard_url, 'next-inning-prep')).json()['regulation_innings'])
    for _ in range(scheduled - 1):
        _advance(page, coachboard_url)
    assert str(_state(page, coachboard_url)['current_inning']) == str(scheduled)
    extra = scheduled + 1

    report = _open_report(page, coachboard_url)
    expect(report.locator('.cb-br-plan')).to_have_count(0)                  # no "Projected to sit"
    expect(report.get_by_text('Projected innings ahead')).to_have_count(0)
    expect(report.locator('[data-cb-br-unprojected]')).to_have_count(0)
    expect(report.locator('[data-cb-br-basis]')).to_have_text(
        f'The {scheduled}th is the last scheduled inning: no innings ahead to project.')
    expect(report.locator('.cb-br-count').first).not_to_contain_text('projected')
    report.locator('[data-bs-dismiss="modal"]').first.click()

    # Extra innings still happen, and count once played.
    _advance(page, coachboard_url)
    assert str(_state(page, coachboard_url)['current_inning']) == str(extra)
    report = _open_report(page, coachboard_url)
    expect(report.locator('.cb-br-chip').first).to_have_text(f'Inning {extra}')
    expect(report.locator('.cb-br-plan')).to_have_count(0)
    expect(report.locator('[data-cb-br-basis]')).to_have_text(
        f'The {extra}th is an extra inning: no innings ahead to project.')
    assert page.cb_errors == []
