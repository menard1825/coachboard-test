"""Clicking the team logo must not flash the legacy dashboard.

From /pitching the logo navigates to Home. Two renderers write
#overview-content-container there -- the legacy main.js::renderOverview() and
the modern home_dashboard.js -- and before the ownership guard in main.js
whichever finished its API calls first decided what the coach saw. Measured on
the parent commit with 150 ms of API latency, the legacy "Next Game" dashboard
sat on screen for roughly 2.4 seconds before the modern Home replaced it.

The latency case is the discriminator. With instant local APIs the two
renderers land within a few tens of milliseconds of each other, so a test that
only runs fast can pass on an unfixed build by luck.

The fallback test is the other half of the contract: when home_dashboard.js
cannot be fetched at all, the legacy renderer must still produce Home. That is
why the guard keys off the modern dashboard's own DOM markers rather than the
page path or the presence of its script tag.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.',
                allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

#: Samples #overview-content-container and reduces it to one of a few named
#: states, so a timeline reads as a sequence rather than as raw HTML.
TIMELINE_PROBE = r"""
(() => {
  const P = window.__cbFlash = {rows: [], paints: []};
  try {
    new PerformanceObserver((list) => list.getEntries().forEach((entry) =>
      P.paints.push({name: entry.name, t: Math.round(entry.startTime)})))
      .observe({type: 'paint', buffered: true});
  } catch (_) {}

  const signature = (el) => {
    if (!el) return 'ABSENT';
    if (el.querySelector('.cb-home-dashboard')) return 'MODERN';
    if (el.querySelector('.cb-home-loading')) return 'MODERN_LOADING';
    const html = el.innerHTML;
    if (!html.trim()) return 'EMPTY';
    if (/Loading Overview/i.test(html)) return 'SERVER_SPINNER';
    if (/Loading overview data/i.test(html)) return 'LEGACY_EMPTY';
    // The legacy dashboard's own card headers, with no modern marker present.
    if (/Next Game/.test(html)
        && (/Pitcher Availability/.test(html) || /Recent Coaches Log/.test(html))) {
      return 'LEGACY';
    }
    return 'OTHER';
  };

  const tick = () => {
    const root = document.getElementById('mainTabContent');
    const active = root
      ? Array.from(root.querySelectorAll(':scope > .tab-pane.active')).map((p) => p.id)
      : [];
    P.rows.push({
      t: Math.round(performance.now()),
      hash: location.hash,
      state: signature(document.getElementById('overview-content-container')),
      active,
      gamesClass: document.getElementById('games')?.className ?? null,
    });
  };
  const interval = setInterval(tick, 20);
  setTimeout(() => clearInterval(interval), 20000);
  tick();
})();
"""


def _login(page, base_url):
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')


def _timeline(probe):
    """Collapse consecutive identical states into an ordered sequence."""
    states = []
    for row in probe['rows']:
        if not states or states[-1][0] != row['state']:
            states.append((row['state'], row['t']))
    return states


def _home_via_logo(browser_context, base_url, *, api_delay_ms=0, blocked=(),
                   settle_ms=6000):
    cdn_assets.require_vendored_assets()
    cdn_assets.install(browser_context, api_delay_ms=api_delay_ms, blocked=blocked)
    browser_context.add_init_script(TIMELINE_PROBE)

    page = browser_context.new_page()
    documents = []
    page.on('response', lambda response: documents.append(
        {'url': response.url, 'status': response.status,
         'redirected': bool(response.request.redirected_from)})
        if response.request.resource_type == 'document' else None)

    _login(page, base_url)
    page.goto(f'{base_url}/pitching')
    page.wait_for_load_state('load')
    page.wait_for_timeout(500)

    documents.clear()
    page.click('.navbar-brand', no_wait_after=True)
    page.wait_for_timeout(settle_ms)

    return page, documents, page.evaluate('window.__cbFlash')


@pytest.fixture
def context(browser):
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
    yield ctx
    ctx.close()


# --- 1. normal logo navigation --------------------------------------------

def test_logo_navigates_to_home_in_one_document_request(context, coachboard_url):
    page, documents, probe = _home_via_logo(context, coachboard_url)

    assert len(documents) == 1, documents
    assert documents[0]['status'] == 200
    assert documents[0]['redirected'] is False

    url = re.match(r'^[^?#]*', page.url.replace(coachboard_url, '')).group(0)
    assert url in ('/', ''), page.url
    assert page.evaluate('location.hash') == '#overview'

    assert all('games' not in row['active'] for row in probe['rows']), (
        'the legacy #games pane became active'
    )
    assert probe['rows'][-1]['active'] == ['overview']
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_have_count(1)


# --- 2. no legacy flash once the modern owner has claimed the container ----

def test_legacy_overview_never_appears_after_the_modern_owner_claims(
        context, coachboard_url):
    _, _, probe = _home_via_logo(context, coachboard_url)
    states = _timeline(probe)

    claimed = next((index for index, (state, _) in enumerate(states)
                    if state in ('MODERN_LOADING', 'MODERN')), None)
    assert claimed is not None, f'the modern dashboard never claimed: {states}'
    after = [state for state, _ in states[claimed:]]
    assert 'LEGACY' not in after, f'legacy content after the modern claim: {states}'
    assert states[-1][0] == 'MODERN', states


# --- 3. the latency discriminator -----------------------------------------

def test_no_legacy_flash_under_api_latency(context, coachboard_url):
    """The case that failed for ~2.4 s before the guard."""
    _, _, probe = _home_via_logo(context, coachboard_url,
                                 api_delay_ms=150, settle_ms=12000)
    states = _timeline(probe)
    names = [state for state, _ in states]

    assert 'LEGACY' not in names, f'legacy dashboard rendered: {states}'
    assert 'MODERN_LOADING' in names, states
    assert names[-1] == 'MODERN', states
    assert names.index('MODERN_LOADING') < names.index('MODERN'), states


# --- 4. the legacy renderer is still a working fallback -------------------

def test_legacy_overview_still_renders_when_home_dashboard_is_blocked(
        context, coachboard_url):
    _, _, probe = _home_via_logo(context, coachboard_url,
                                 blocked=('/static/js/home_dashboard.js',),
                                 settle_ms=8000)
    states = _timeline(probe)
    names = [state for state, _ in states]

    assert 'MODERN' not in names and 'MODERN_LOADING' not in names, states
    assert names[-1] in ('LEGACY', 'LEGACY_EMPTY'), (
        f'Home was left without any dashboard when home_dashboard.js was '
        f'blocked: {states}'
    )


# --- 5. an already-rendered modern dashboard survives a re-render ---------

def test_modern_dashboard_survives_a_later_render_all(context, coachboard_url):
    """socket 'data_updated' re-runs fetchData() then renderAll()."""
    page, _, _ = _home_via_logo(context, coachboard_url)
    dashboard = page.locator('#overview-content-container .cb-home-dashboard')
    expect(dashboard).to_have_count(1)
    before = dashboard.inner_html()

    response = page.request.post(
        f'{coachboard_url}/add_game',
        form={'game_date': '2030-07-04', 'game_opponent': 'Re-render Rivals',
              'game_start_time': '10:00', 'game_location': 'Test Field',
              'game_notes': ''},
    )
    assert response.status in (200, 302), response.status

    page.wait_for_timeout(4000)

    expect(dashboard).to_have_count(1)
    assert dashboard.inner_html() == before, (
        'a later renderAll() changed the modern dashboard'
    )
    assert page.locator(
        '#overview-content-container:has-text("Pitcher Availability")'
    ).count() == 0
