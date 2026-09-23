"""One failed legacy dataset must not take the visible Home page with it.

main.js loads 13 datasets for the legacy tabs at start-up. It used to await
them with Promise.all, so a single failed request -- /api/signs, say, for a
tab the coach is not even looking at -- rejected the whole load, and init()'s
catch replaced #mainTabContent with "Could not load app data". That removed
every pane, including #overview-content-container and the modern Home
dashboard inside it, and init() returned before binding listeners, rendering
or opening its socket.

Now each dataset fails on its own: its tab gets a small notice, the other tabs
render normally, and Home is untouched. /api/lineups is included because its
renderers call .filter/.find on the data directly, so it proves the fallback
has the shape the renderer expects, not merely "something".

/api/overview_data is also fetched by home_dashboard.js, which owns Home's own
error handling (getJson() falls back on failure). That case is here to prove
the change does not interfere with it.
"""

import os
import re
import uuid

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
DESKTOP = {'width': 1440, 'height': 900}
PHONE = {'width': 390, 'height': 844}

#: endpoint -> the tab pane whose data it is
HIDDEN = {
    '/api/signs': 'signs',
    '/api/stats': 'stats',
    '/api/scouting_list': 'scouting_list',
    '/api/lineups': 'lineups',
}
LOAD_ERROR_KEY = {'signs': 'signs', 'stats': 'stats', 'scouting_list': 'scouting_list', 'lineups': 'lineups'}


@pytest.fixture
def make_page(browser):
    contexts = []

    def _make(viewport, failing=()):
        cdn_assets.require_vendored_assets()
        mobile = viewport is PHONE
        context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        page.cb_failing = set()
        for path in failing:
            _fail(page, path)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        return page

    yield _make
    for context in contexts:
        context.close()


def _fail(page, path):
    page.cb_failing.add(path)
    page.route(f'**{path}', lambda route: route.fulfill(
        status=500, content_type='application/json', body='{"status": "error"}'))


def _recover(page, path):
    page.cb_failing.discard(path)
    page.unroute(f'**{path}')


def _open_home(page, base_url):
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')
    page.goto(f'{base_url}/')
    page.wait_for_load_state('load')
    page.wait_for_timeout(2500)


def _assert_home_intact(page):
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_be_visible(timeout=15_000)
    assert page.locator('#mainTabContent > .alert-danger').count() == 0, (
        page.locator('#mainTabContent > .alert-danger').inner_text())
    assert page.locator('#mainTabContent > .tab-pane').count() == 13
    assert page.cb_errors == [], page.cb_errors


def _assert_unrelated_tabs_rendered(page):
    """Data from requests that succeeded still reaches its tabs."""
    expect(page.locator('#roster-cards-container .save-player-btn')).not_to_have_count(0, timeout=15_000)
    expect(page.locator('#rotationsAccordion [data-rotation-id]')).not_to_have_count(0, timeout=15_000)
    expect(page.locator('#practicePlanAccordion .accordion-item')).not_to_have_count(0, timeout=15_000)


def _open_tab(page, pane_id):
    page.evaluate('id => { location.hash = "#" + id; }', pane_id)
    expect(page.locator(f'#{pane_id}')).to_be_visible(timeout=15_000)


def _notice(page, pane_id, key):
    return page.locator(f'#{pane_id} > [data-cb-load-error="{key}"]')


# --- healthy baseline -----------------------------------------------------

def test_healthy_home_has_no_load_notices(make_page, coachboard_url):
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    _assert_home_intact(page)
    _assert_unrelated_tabs_rendered(page)
    assert page.locator('[data-cb-load-error]').count() == 0


# --- one hidden dataset fails ---------------------------------------------

@pytest.mark.parametrize('path', sorted(HIDDEN))
def test_one_hidden_failure_leaves_home_intact(make_page, coachboard_url, path):
    page = make_page(DESKTOP, failing=[path])
    _open_home(page, coachboard_url)

    _assert_home_intact(page)
    _assert_unrelated_tabs_rendered(page)

    pane = HIDDEN[path]
    _open_tab(page, pane)
    expect(_notice(page, pane, LOAD_ERROR_KEY[pane])).to_be_visible()
    assert page.locator('[data-cb-load-error]').count() == 1
    assert page.locator('#mainTabContent > .tab-pane').count() == 13
    assert page.cb_errors == []


def test_one_hidden_failure_still_navigates_to_other_tabs(make_page, coachboard_url):
    page = make_page(DESKTOP, failing=['/api/signs'])
    _open_home(page, coachboard_url)
    _assert_home_intact(page)

    page.locator('.coach-primary-nav [data-cb-section="roster"]').click()
    expect(page.locator('#roster')).to_be_visible(timeout=15_000)
    expect(page.locator('#roster-cards-container .save-player-btn')).not_to_have_count(0)
    _open_tab(page, 'rotations')
    expect(page.locator('#rotationsAccordion .rotation-template-edit-btn')).not_to_have_count(0, timeout=15_000)
    assert page.cb_errors == []


def test_one_hidden_failure_on_phone(make_page, coachboard_url):
    page = make_page(PHONE, failing=['/api/signs'])
    _open_home(page, coachboard_url)
    _assert_home_intact(page)
    _assert_unrelated_tabs_rendered(page)
    _open_tab(page, 'signs')
    expect(_notice(page, 'signs', 'signs')).to_be_visible()
    assert page.cb_errors == []


# --- two hidden datasets fail at once -------------------------------------

def test_two_hidden_failures_leave_home_and_other_tabs_intact(make_page, coachboard_url):
    page = make_page(DESKTOP, failing=['/api/signs', '/api/stats'])
    _open_home(page, coachboard_url)

    _assert_home_intact(page)
    _assert_unrelated_tabs_rendered(page)
    for pane in ('signs', 'stats'):
        _open_tab(page, pane)
        expect(_notice(page, pane, pane)).to_be_visible()
    assert page.locator('[data-cb-load-error]').count() == 2

    page.locator('.coach-primary-nav [data-cb-section="roster"]').click()
    expect(page.locator('#roster')).to_be_visible(timeout=15_000)
    _open_tab(page, 'practice_plan')
    expect(page.locator('#practicePlanAccordion .accordion-item')).not_to_have_count(0)
    assert page.cb_errors == []


# --- a Home-owned dataset fails -------------------------------------------

def test_home_owned_failure_stays_with_home_dashboard(make_page, coachboard_url):
    """/api/overview_data belongs to Home. home_dashboard.js handles its own
    failure; main.js must neither wipe Home nor add a notice inside it."""
    page = make_page(DESKTOP, failing=['/api/overview_data'])
    _open_home(page, coachboard_url)

    _assert_home_intact(page)
    assert page.locator('#overview [data-cb-load-error]').count() == 0
    _assert_unrelated_tabs_rendered(page)


# --- a later refresh after a failure --------------------------------------

def _trigger_data_updated(page, base_url):
    """A real server change: every open main.js refetches and re-renders."""
    before = page.evaluate("performance.getEntriesByType('resource').filter(e => e.name.includes('/api/signs')).length")
    response = page.request.post(f'{base_url}/add_game', form={
        'game_date': '2031-06-01', 'game_opponent': f'Refresh {uuid.uuid4().hex[:6]}',
        'game_start_time': '10:00', 'game_location': 'Field', 'game_notes': ''})
    assert response.status in (200, 302)
    page.wait_for_function(
        f"performance.getEntriesByType('resource').filter(e => e.name.includes('/api/signs')).length > {before}",
        timeout=15_000)
    page.wait_for_timeout(1500)


def test_data_update_after_a_failure_does_not_throw(make_page, coachboard_url):
    page = make_page(DESKTOP, failing=['/api/signs'])
    _open_home(page, coachboard_url)
    _assert_home_intact(page)

    _trigger_data_updated(page, coachboard_url)   # signs still failing
    _assert_home_intact(page)
    _assert_unrelated_tabs_rendered(page)
    assert _notice(page, 'signs', 'signs').count() == 1

    _recover(page, '/api/signs')
    _trigger_data_updated(page, coachboard_url)   # signs back
    _assert_home_intact(page)
    assert page.locator('[data-cb-load-error]').count() == 0
    assert page.cb_errors == []
