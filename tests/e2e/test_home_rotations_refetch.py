"""season_management_v2.js may refetch /api/rotations only when rotations changed.

The script separates Starting Defense presets from full-game rotation templates
on Home's Rotations tab and decorates what main.js renders. It watches three
containers -- #rotationsAccordion, #practicePlanAccordion, #dev-player-list --
plus `shown.bs.tab`, and every trigger used to refetch /api/rotations:

* main.js rendering the hidden Development and Practice lists at start-up;
* its own writes (removing preset rows, adding Edit Template and Reuse Plan
  buttons), and coachboard_ui.js adding Delete buttons beside those links.

That was 3 rotations requests per Home load with instant APIs and 5 with 150 ms
latency. The intended behaviour is one fetch at start-up plus a fetch whenever
the rotations themselves change. The two real triggers pinned here:

A. main.js re-renders the accordion with a different set of rotations -- a
   `data_updated` socket event after a template is created or deleted;
B. the coach opens the Rotations tab on desktop (`shown.bs.tab`). That is the
   only way the preset panel picks up a preset saved on another device, because
   `rotation_save` makes main.js refetch without re-rendering the accordion.

Requests are attributed to the script on the fetch's stack: main.js makes its
own legitimate /api/rotations request, which this slice does not touch.

main.js now renders the Rotations list only when the tab is first opened, so
Home itself is left with season_management_v2.js's single start-up fetch, and
the first open decorates the new list from that cached response. Tests that
act on the decorated list open the tab first.
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

ROTATIONS = '/api/rotations'
SEASON_JS = 'season_management_v2.js'
MAIN_JS = 'main.js'
PRESET_PREFIX = 'DEFENSE PRESET — '

FETCH_RECORDER = r"""
(() => {
  const native = window.fetch.bind(window);
  window.__cbApi = [];
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.includes('/api/')) {
      const frame = (new Error().stack || '').split('\n')
        .map(line => line.match(/\/static\/js\/([\w.-]+\.js)/))
        .find(Boolean);
      window.__cbApi.push({path: new URL(url, location.href).pathname,
                           by: frame ? frame[1] : '(unknown)'});
    }
    return native(input, init);
  };
})();
"""


@pytest.fixture
def make_page(browser):
    contexts = []

    def _make(viewport, *, api_delay_ms=0):
        cdn_assets.require_vendored_assets()
        mobile = viewport is PHONE
        context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        cdn_assets.install(context, api_delay_ms=api_delay_ms)
        context.add_init_script(FETCH_RECORDER)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        page.cb_delay = api_delay_ms
        return page

    yield _make
    for context in contexts:
        context.close()


def _wait_until_rotations_decorated(page):
    """The Rotations tab has been separated and decorated at least once."""
    page.wait_for_function(
        """() => {
          const panel = document.getElementById('defense-preset-home-v2');
          const items = [...document.querySelectorAll('#rotationsAccordion [data-rotation-id]')];
          return panel && items.length > 0
            && items.every(item => item.querySelector('.rotation-template-edit-btn'));
        }""",
        timeout=30_000,
    )


def _settle(page):
    # Long enough for the old self-triggered chain to finish even at 150 ms
    # latency (its last request landed ~1.5 s after the tab was decorated).
    page.wait_for_timeout(4000 if page.cb_delay else 2000)


def _open_home(page, base_url):
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')
    page.goto(f'{base_url}/')
    page.wait_for_load_state('load')
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_have_count(1, timeout=30_000)
    _settle(page)


def _open_rotations(page):
    page.evaluate("() => { location.hash = '#rotations'; }")
    expect(page.locator('#rotations')).to_be_visible(timeout=15_000)
    _wait_until_rotations_decorated(page)
    _settle(page)


def _rotation_calls(page, by=None):
    return [call['by'] for call in page.evaluate('window.__cbApi')
            if call['path'] == ROTATIONS and (by is None or call['by'] == by)]


def _assert_home_load_counts(page):
    everyone = sorted(_rotation_calls(page))
    assert _rotation_calls(page, MAIN_JS) == [], everyone
    assert len(_rotation_calls(page, SEASON_JS)) == 1, (
        f'{SEASON_JS} fetched {ROTATIONS} {len(_rotation_calls(page, SEASON_JS))} '
        f'times on one Home load; all callers: {everyone}')
    assert page.cb_errors == []

    # Opening the tab: main.js fetches and renders the list once, and the
    # season script decorates it from the response it already has. Desktop
    # opens tabs through Bootstrap, whose shown.bs.tab is the season script's
    # own refresh trigger (B above) -- one more request there, none on phones.
    phone = page.viewport_size['width'] < 992
    _open_rotations(page)
    everyone = sorted(_rotation_calls(page))
    assert _rotation_calls(page, MAIN_JS) == [MAIN_JS], everyone
    assert len(_rotation_calls(page, SEASON_JS)) == (1 if phone else 2), everyone
    _assert_rotations_ui_is_decorated(page)
    assert page.cb_errors == []


def _rotations_ui(page):
    """What the Rotations tab shows, structurally."""
    return page.evaluate(
        """(prefix) => {
          const accordion = document.getElementById('rotationsAccordion');
          const items = [...accordion.querySelectorAll('[data-rotation-id]')];
          const panel = document.getElementById('defense-preset-home-v2');
          const header = accordion.closest('.card')?.querySelector('.card-header h5');
          return {
            accordionTitles: items.map(i => i.querySelector('.accordion-button strong')?.textContent.trim()),
            presetsInAccordion: items.filter(i =>
              (i.querySelector('.accordion-button strong')?.textContent || '').startsWith(prefix)).length,
            editButtons: items.map(i => i.querySelectorAll('.rotation-template-edit-btn').length),
            presetChips: [...(panel?.querySelectorAll('.dph-chip') || [])].map(c => c.textContent.trim()),
            presetCountLabel: panel?.querySelector('.dph-head-actions span')?.textContent.trim() || null,
            header: header?.textContent.trim() || null,
            toolbar: !!accordion.closest('.card')?.querySelector('.rotation-template-toolbar'),
          };
        }""",
        PRESET_PREFIX,
    )


def _assert_rotations_ui_is_decorated(page):
    ui = _rotations_ui(page)
    assert ui['accordionTitles'], ui
    assert ui['presetsInAccordion'] == 0, f'presets were left in the full-game list: {ui}'
    assert ui['editButtons'] and all(n == 1 for n in ui['editButtons']), ui
    assert ui['presetChips'], f'the Starting Defense panel is empty: {ui}'
    assert ui['header'] == 'Full-Game Rotation Templates', ui
    assert ui['toolbar'] is True, ui
    return ui


def _create_template(page, base_url, title):
    response = page.request.post(
        f'{base_url}/save_rotation_as_template',
        data={'title': title, 'innings': {'1': {'P': 'Pitcher Pat'}}},
    )
    assert response.ok, (response.status, response.text())


# --- one Home load --------------------------------------------------------

def test_home_load_makes_one_season_rotation_fetch_desktop(make_page, coachboard_url):
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    _assert_home_load_counts(page)


def test_home_load_makes_one_season_rotation_fetch_phone(make_page, coachboard_url):
    page = make_page(PHONE)
    _open_home(page, coachboard_url)
    _assert_home_load_counts(page)


def test_home_load_count_does_not_grow_with_api_latency_desktop(make_page, coachboard_url):
    page = make_page(DESKTOP, api_delay_ms=150)
    _open_home(page, coachboard_url)
    _assert_home_load_counts(page)


def test_home_load_count_does_not_grow_with_api_latency_phone(make_page, coachboard_url):
    page = make_page(PHONE, api_delay_ms=150)
    _open_home(page, coachboard_url)
    _assert_home_load_counts(page)


# --- mutations that are not rotation changes ------------------------------

def test_main_js_rerender_without_rotation_changes_does_not_refetch(make_page, coachboard_url):
    """A real data_updated for a game while Rotations is showing: main.js
    refetches and re-renders the accordion with the same rotations. The season
    script must re-decorate from what it already has."""
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    _open_rotations(page)
    before = len(_rotation_calls(page, SEASON_JS))
    main_before = len(_rotation_calls(page, MAIN_JS))

    response = page.request.post(f'{coachboard_url}/add_game', form={
        'game_date': '2031-05-01', 'game_opponent': f'Unrelated {uuid.uuid4().hex[:6]}',
        'game_start_time': '10:00', 'game_location': 'Field', 'game_notes': ''})
    assert response.status in (200, 302)
    page.wait_for_function(f'window.__cbApi.filter(c => c.path === "{ROTATIONS}" && c.by === "{MAIN_JS}").length > {main_before}',
                           timeout=15_000)
    _wait_until_rotations_decorated(page)
    _settle(page)

    assert len(_rotation_calls(page, SEASON_JS)) == before, sorted(_rotation_calls(page))
    _assert_rotations_ui_is_decorated(page)
    assert page.cb_errors == []


def test_unrelated_watched_containers_do_not_refetch(make_page, coachboard_url):
    """#dev-player-list and #practicePlanAccordion are watched for their own
    enhancements; changing them must not fetch rotations."""
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    _open_rotations(page)
    before = len(_rotation_calls(page, SEASON_JS))
    page.evaluate("""() => {
      for (const id of ['dev-player-list', 'practicePlanAccordion']) {
        const el = document.getElementById(id);
        if (el) el.appendChild(document.createElement('div'));
      }
    }""")
    _settle(page)
    assert len(_rotation_calls(page, SEASON_JS)) == before, sorted(_rotation_calls(page))


# --- real rotation changes must still refresh -----------------------------

def test_new_template_from_another_device_refreshes_and_is_decorated(make_page, coachboard_url):
    """Trigger A: data_updated after a template is created elsewhere."""
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    _open_rotations(page)
    before = len(_rotation_calls(page, SEASON_JS))

    title = f'Sunday Rotation {uuid.uuid4().hex[:6]}'
    _create_template(page, coachboard_url, title)
    page.wait_for_function(
        """title => [...document.querySelectorAll('#rotationsAccordion .accordion-button strong')]
                     .some(s => s.textContent.trim() === title)""", arg=title, timeout=15_000)
    _wait_until_rotations_decorated(page)
    _settle(page)

    assert len(_rotation_calls(page, SEASON_JS)) == before + 1, sorted(_rotation_calls(page))
    ui = _assert_rotations_ui_is_decorated(page)
    assert title in ui['accordionTitles']
    assert page.cb_errors == []


def test_new_preset_from_another_device_lands_in_the_preset_panel(make_page, coachboard_url):
    """Trigger A for the preset branch: the new row must move out of the list."""
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    _open_rotations(page)
    before = len(_rotation_calls(page, SEASON_JS))

    name = f'Tournament {uuid.uuid4().hex[:6]}'
    _create_template(page, coachboard_url, PRESET_PREFIX + name)
    page.wait_for_function(
        """name => [...document.querySelectorAll('#defense-preset-home-v2 .dph-chip')]
                    .some(c => c.textContent.trim() === name)""", arg=name, timeout=15_000)
    _settle(page)

    assert len(_rotation_calls(page, SEASON_JS)) == before + 1, sorted(_rotation_calls(page))
    ui = _assert_rotations_ui_is_decorated(page)
    assert name in ui['presetChips']
    assert page.cb_errors == []


# --- opening Rotations after Home has been idle ----------------------------

def test_opening_rotations_on_desktop_after_idle_refreshes_once(make_page, coachboard_url):
    """Trigger B: the desktop More menu -> Defensive Templates."""
    page = make_page(DESKTOP)
    _open_home(page, coachboard_url)
    page.wait_for_timeout(3000)  # Home sitting idle
    before = len(_rotation_calls(page, SEASON_JS))

    page.locator('.navbar .dropdown-toggle', has_text='More').first.click()
    page.locator('a.dropdown-item[href$="#rotations"]').first.click()

    expect(page.locator('#rotations')).to_be_visible(timeout=15_000)
    _settle(page)
    assert len(_rotation_calls(page, SEASON_JS)) == before + 1, sorted(_rotation_calls(page))
    _assert_rotations_ui_is_decorated(page)
    assert page.cb_errors == []


def test_opening_rotations_on_phone_after_idle_shows_the_decorated_tab(make_page, coachboard_url):
    """Phones switch tabs without Bootstrap events: nothing to refetch, but the
    list main.js renders on first open must be decorated from the Home load's
    response."""
    page = make_page(PHONE)
    _open_home(page, coachboard_url)
    page.wait_for_timeout(3000)
    before = len(_rotation_calls(page, SEASON_JS))

    page.evaluate("() => { location.hash = '#more'; }")
    link = page.locator('#more a[href$="#rotations"]').first
    expect(link).to_be_visible(timeout=15_000)
    link.click()

    expect(page.locator('#rotations')).to_be_visible(timeout=15_000)
    _settle(page)
    assert len(_rotation_calls(page, SEASON_JS)) == before, sorted(_rotation_calls(page))
    _assert_rotations_ui_is_decorated(page)
    assert page.cb_errors == []
