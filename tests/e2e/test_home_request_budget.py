"""Home's API request budget.

Measured from one click on the team logo (from /pitching) to a settled Home.
The Home audit found 17 of 28 desktop requests served hidden tabs or were
duplicates; each slice lowers these ceilings in the same commit that earns
the reduction.

Ceilings are per endpoint, so a change that trades one request for a new one
still fails. main.js now loads a legacy tab's datasets only when that tab is
opened, so none of its thirteen start-up requests remain on Home: the
endpoints below are home_dashboard.js's own plus the enhancer scripts'
(roster_pitching_traits.js, season_management_v2.js, getting_started_home.js,
client_timezone.js's heartbeat, and on phones mobile_game_day_fields.js).
An endpoint that only a legacy tab needs -- /api/signs, say -- appearing here
fails as "outside the baseline".
"""

import os
import re
from collections import Counter

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

import cdn_assets  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

#: endpoint -> maximum requests per Home load. Measured on the lazy-loading
#: change, three runs per viewport at 0 ms and 150 ms API latency, identical
#: every time. History: 10eed5d measured 28 desktop / 30 phone; pageshow,
#: rotations and lazy legacy tabs brought it to 13 / 14.
DESKTOP_BASELINE = {
    '/api/session_data': 1,                   # home_dashboard.js
    '/api/roster': 1,                         # home_dashboard.js
    '/api/rotations': 1,                      # season_management_v2.js
    '/api/games': 1,                          # home_dashboard.js
    '/api/practice_plans': 1,                 # home_dashboard.js
    '/api/overview_data': 1,                  # home_dashboard.js
    '/api/roster-pitching-profiles': 1,
    '/api/getting-started': 1,
    '/api/pitching-preferences/settings': 1,
    '/api/pitching-preferences/arm-care-summary': 1,
    '/api/game-day/<id>/readiness': 1,
    '/api/game-day/<id>/pitching-rules': 1,
    '/api/coach-usage/heartbeat': 1,
}
#: Phones also load mobile_game_day_fields.js, which fetches /api/games once more.
PHONE_BASELINE = dict(DESKTOP_BASELINE, **{'/api/games': 2})

#: The measured totals the ceilings above add up from. Printed with the result.
MEASURED_TOTAL = {'desktop': 13, 'phone': 14}


def _normalise(url):
    path = re.sub(r'^https?://[^/]+', '', url).split('?')[0]
    return re.sub(r'^/api/game-day/\d+/', '/api/game-day/<id>/', path)


def _home_requests(browser, base_url, *, phone):
    cdn_assets.require_vendored_assets()
    viewport = {'width': 390, 'height': 844} if phone else {'width': 1440, 'height': 900}
    context = browser.new_context(viewport=viewport, is_mobile=phone, has_touch=phone)
    try:
        cdn_assets.install(context)
        page = context.new_page()
        page.goto(f'{base_url}/login')
        page.get_by_label('Username or email').fill(TEST_USERNAME)
        page.locator('#password').fill(TEST_PASSWORD)
        page.get_by_role('button', name='Sign In').click()
        page.wait_for_load_state('load')
        page.goto(f'{base_url}/pitching')
        page.wait_for_load_state('load')
        page.wait_for_timeout(800)

        seen = []
        page.on('request', lambda request: seen.append(_normalise(request.url))
                if '/api/' in request.url else None)
        page.click('.navbar-brand')
        page.wait_for_load_state('load')
        page.locator('#overview-content-container .cb-home-dashboard').wait_for(timeout=15_000)
        page.wait_for_timeout(4000)
        return Counter(seen)
    finally:
        context.close()


def _check(counts, baseline, label):
    print(f'\n[{label}] {sum(counts.values())} API requests, {len(counts)} distinct '
          f'(measured baseline {MEASURED_TOTAL[label]}):')
    for endpoint, n in sorted(counts.items()):
        print(f'   {n}x {endpoint}')

    unexpected = sorted(set(counts) - set(baseline))
    assert not unexpected, f'{label}: Home made requests outside its recorded baseline: {unexpected}'
    over = {endpoint: (n, baseline[endpoint]) for endpoint, n in counts.items() if n > baseline[endpoint]}
    assert not over, f'{label}: endpoints over their ceiling (measured, ceiling): {over}'
    assert sum(counts.values()) <= sum(baseline.values())


def test_home_request_budget_desktop(browser, coachboard_url):
    _check(_home_requests(browser, coachboard_url, phone=False), DESKTOP_BASELINE, 'desktop')


def test_home_request_budget_phone(browser, coachboard_url):
    _check(_home_requests(browser, coachboard_url, phone=True), PHONE_BASELINE, 'phone')
