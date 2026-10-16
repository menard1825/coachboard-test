"""The Bench Report's words: completed, now and scheduled, never confused.

Each player's line keeps three things apart -- innings already sat, the
inning being played, and innings the plan has them sitting -- and always
names innings by ordinal ("3rd inning"), so an inning number is never read
as a count of innings. "Sitting next inning" appears only when the upcoming
inning's defense is set and benches the player. Neutral coaching language
throughout: information, not a score.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from live_fixtures import INNING_2, advance_inning, live, set_next_inning  # noqa: E402,F401 (live is a fixture)


DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})

# CBBenchReport.describe(row, report) with exactly the inputs given.
DESCRIBE = """([row, report]) => window.CBBenchReport.describe(
  {sat: [], currentBench: false, plannedSat: [], ...row},
  {currentLabel: '2', futurePlanned: [], ...report})"""

UPCOMING_3RD = [{'inning': '3', 'upcoming': True}]          # the 3rd's defense is set
LATER_ONLY = [{'inning': '4', 'upcoming': False}]            # the 3rd isn't set; the 4th is

CASES = [
    # (what it checks, row, report, expected)
    ('singular, now, sitting next inning',
     {'sat': ['1'], 'currentBench': True, 'plannedSat': ['3']}, {'futurePlanned': UPCOMING_3RD},
     {'count': '1 inning sat · On bench now · Sitting next inning',
      'sat': 'Sat: 1st inning · On bench now (2nd inning)',
      'plan': 'Scheduled to sit: 3rd inning'}),
    ('plural completed innings',
     {'sat': ['1', '2']}, {'currentLabel': '3'},
     {'count': '2 innings sat', 'sat': 'Sat: 1st and 2nd innings', 'plan': ''}),
    ('an inning number is not a count: sat only the 3rd',
     {'sat': ['3']}, {'currentLabel': '4'},
     {'count': '1 inning sat', 'sat': 'Sat: 3rd inning', 'plan': ''}),
    ('next inning plus a later one',
     {'plannedSat': ['3', '5']}, {'futurePlanned': UPCOMING_3RD + [{'inning': '5', 'upcoming': False}]},
     {'count': 'No innings sat · Sitting next inning · 1 later inning scheduled',
      'sat': 'Sat: None', 'plan': 'Scheduled to sit: 3rd and 5th innings'}),
    ('several later innings, not the next one',
     {'sat': ['1'], 'plannedSat': ['4', '5', '6']}, {'futurePlanned': UPCOMING_3RD},
     {'count': '1 inning sat · 3 later innings scheduled',
      'sat': 'Sat: 1st inning', 'plan': 'Scheduled to sit: 4th, 5th and 6th innings'}),
    ('next inning not fully planned: never "Sitting next inning"',
     {'currentBench': True, 'plannedSat': ['4']}, {'futurePlanned': LATER_ONLY},
     {'count': 'No innings sat · On bench now · 1 later inning scheduled',
      'sat': 'Sat: None · On bench now (2nd inning)', 'plan': 'Scheduled to sit: 4th inning'}),
    ('playing the next inning, nothing else scheduled',
     {'sat': ['1'], 'currentBench': True}, {'futurePlanned': UPCOMING_3RD},
     {'count': '1 inning sat · On bench now', 'sat': 'Sat: 1st inning · On bench now (2nd inning)', 'plan': ''}),
    ('nothing at all',
     {}, {},
     {'count': 'No innings sat', 'sat': 'Sat: None', 'plan': ''}),
    ('extra innings use the right ordinals',
     {'sat': ['11', '12', '13'], 'currentBench': True}, {'currentLabel': '21'},
     {'count': '3 innings sat · On bench now', 'sat': 'Sat: 11th, 12th and 13th innings · On bench now (21st inning)',
      'plan': ''}),
]


def test_each_players_words(live, coachboard_url):
    page = live(DESKTOP)
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.wait_for_function('() => window.CBBenchReport && window.CBBenchReport.describe')
    for what, row, report, expected in CASES:
        assert page.evaluate(DESCRIBE, [row, report]) == expected, what
    assert page.cb_errors == []


def test_the_report_in_a_live_game(live, coachboard_url):
    """In the 2nd, with the 3rd fully planned: Catcher Cole moves into LF and
    the player he replaces sits the 3rd. Center Casey sat the 1st, sits now
    and sits the 3rd."""
    page = live(DESKTOP)
    advance_inning(page, coachboard_url)
    replaced = INNING_2['LF']
    set_next_inning(page, coachboard_url, {**INNING_2, 'LF': 'Catcher Cole'})
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('[data-cb-bench-report]').click()
    report = page.locator('#cbBenchReportModal')
    expect(report.locator('[data-cb-br-sitting]')).to_be_visible(timeout=10_000)

    def row(name):
        return report.locator(f'[data-cb-br-player="{name}"]')

    expect(row('Center Casey').locator('.cb-br-count')).to_have_text('1 inning sat · On bench now · Sitting next inning')
    expect(row('Center Casey').locator('.cb-br-history')).to_have_text('Sat: 1st inning · On bench now (2nd inning)')
    expect(row('Center Casey').locator('.cb-br-plan')).to_have_text('Scheduled to sit: 3rd inning')

    expect(row('Catcher Cole').locator('.cb-br-count')).to_have_text('1 inning sat · On bench now')
    expect(row('Catcher Cole').locator('.cb-br-plan')).to_have_count(0)

    expect(row(replaced).locator('.cb-br-count')).to_have_text('No innings sat · Sitting next inning')
    expect(row(replaced).locator('.cb-br-history')).to_have_text('Sat: None')
    expect(row(replaced).locator('.cb-br-plan')).to_have_text('Scheduled to sit: 3rd inning')
    assert page.cb_errors == []
