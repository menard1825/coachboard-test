"""Classic / Updated: a coach's own view, chosen in the account menu.

Runs against a second disposable server that offers the Classic view to
every coach (classic_view_url); the shared server keeps it off. Checks, on a
desktop, an iPad and a phone:

* the choice is the coach's own: another device of theirs follows it, another
  coach and their other team do not;
* switching never loses work: a form changed but not saved stops it, a save
  still in the air is waited for, and a save that fails stops it;
* a live game shows the Updated live screens whatever the coach chose.
"""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from live_field_markers import create_named_live_game, remove_named_live_game  # noqa: E402


COACH = ('playwright-coach', 'playwright-password')
ASSISTANT = ('playwright-assistant', 'playwright-assistant-password')

DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
IPAD = ('ipad-portrait', {'width': 768, 'height': 1024}, {'is_mobile': True, 'has_touch': True})
PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})


@pytest.fixture
def device(browser, classic_view_url):
    """`device(spec, who=COACH)`: a signed-in page in a fresh context (one
    "device"); each page carries `cb_errors`."""
    contexts = []

    def make(spec, who=COACH):
        cdn_assets.require_vendored_assets()
        _, viewport, extra = spec
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        page.cb_errors = []
        page.on('pageerror', lambda error: page.cb_errors.append(str(error)))
        page.goto(f'{classic_view_url}/login')
        page.get_by_label('Username or email').fill(who[0])
        page.locator('#password').fill(who[1])
        page.get_by_role('button', name='Sign In').click()
        expect(page).to_have_url(re.compile(rf'^{re.escape(classic_view_url)}/?(?:#\w+)?$'))
        return page

    yield make
    for context in contexts:
        context.close()


@pytest.fixture
def reset_views(classic_view_url, browser):
    """Every test leaves both coaches on Updated, on both teams."""
    yield
    context = browser.new_context()
    page = context.new_page()
    for who, teams in ((COACH, (1, 2)), (ASSISTANT, (1,))):
        page.goto(f'{classic_view_url}/login')
        page.get_by_label('Username or email').fill(who[0])
        page.locator('#password').fill(who[1])
        page.get_by_role('button', name='Sign In').click()
        page.wait_for_load_state()
        for team in teams:
            page.request.get(f'{classic_view_url}/switch_team/{team}')
            page.request.post(f'{classic_view_url}/api/account/view', data={'view': 'updated'})
        page.request.get(f'{classic_view_url}/logout')
    context.close()


def _view(page):
    body = page.locator('body')
    return body.get_attribute('data-cb-view'), body.get_attribute('data-cb-view-choice')


def _choose(page, view):
    """Pick a view from the account menu, as the coach would on this device."""
    if page.viewport_size['width'] >= 992:
        page.locator('#userMenuDesktop').click()
        item = page.locator(f'.dropdown-menu [data-cb-view-set="{view}"]')
    else:
        page.locator('a[href="#userOffcanvas"]').click()
        item = page.locator(f'#userOffcanvas [data-cb-view-set="{view}"]')
    expect(item).to_be_visible()
    item.click()


def _game(page, url, opponent):
    response = page.request.post(f'{url}/game-day/add', form={
        'game_date': (date.today() + timedelta(days=9)).isoformat(), 'game_start_time': '15:00',
        'game_opponent': opponent, 'game_location': 'Classic Field', 'pitching_rule_set': 'USSSA'},
        max_redirects=0)
    return int(re.search(r'/game/(\d+)', response.headers['location']).group(1))


def _delete(page, url, game_id):
    page.request.post(f'{url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})


@pytest.mark.parametrize('spec', [DESKTOP, IPAD, PHONE], ids=lambda s: s[0])
def test_the_choice_follows_the_coach_and_no_one_else(device, classic_view_url, reset_views, spec):
    coach = device(spec)
    assert _view(coach) == ('updated', 'updated')
    expect(coach.locator('[data-cb-view-notice]')).to_have_count(0)

    _choose(coach, 'classic')
    expect(coach.locator('body')).to_have_attribute('data-cb-view', 'classic', timeout=10_000)
    expect(coach.locator('[data-cb-view-notice]')).to_be_visible()
    expect(coach.locator('[data-cb-view-notice]')).to_contain_text('Live games always use the Updated screens')

    # The same coach on another device: Classic.
    other_device = device(DESKTOP if spec is not DESKTOP else PHONE)
    assert _view(other_device) == ('classic', 'classic')
    # Another coach on the same team: Updated.
    assistant = device(spec, ASSISTANT)
    assert _view(assistant) == ('updated', 'updated')
    expect(assistant.locator('[data-cb-view-notice]')).to_have_count(0)
    # The same coach on their other team: Updated, and back on this team: Classic.
    other_device.goto(f'{classic_view_url}/switch_team/2')
    assert _view(other_device) == ('updated', 'updated')
    other_device.goto(f'{classic_view_url}/switch_team/1')
    assert _view(other_device) == ('classic', 'classic')

    # And back to Updated.
    _choose(coach, 'updated')
    expect(coach.locator('body')).to_have_attribute('data-cb-view', 'updated', timeout=10_000)
    expect(coach.locator('[data-cb-view-notice]')).to_have_count(0)
    # The menu fits the screen.
    assert coach.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth + 1')
    assert coach.cb_errors == [] and assistant.cb_errors == [] and other_device.cb_errors == []


@pytest.mark.parametrize('spec', [DESKTOP, IPAD, PHONE], ids=lambda s: s[0])
def test_a_change_not_yet_saved_stops_the_switch_and_stays(device, classic_view_url, reset_views, spec):
    coach = device(spec)
    game_id = _game(coach, classic_view_url, f'Unsaved {spec[0]}')
    try:
        coach.goto(f'{classic_view_url}/game/{game_id}')
        # Open Availability (the button that opens it differs by screen size;
        # what is under test is the change made in it).
        coach.evaluate("() => bootstrap.Collapse.getOrCreateInstance(document.getElementById('availabilityCollapse')).show()")
        switch = coach.locator('#gameAvailabilityForm input[name="absent_players"]').first
        expect(switch).to_be_visible()
        switch.click()
        expect(switch).to_be_checked()
        coach.evaluate('() => { window.__sameDocument = true; }')

        _choose(coach, 'classic')
        status = coach.locator('#cbViewSwitchStatus')
        expect(status).to_be_visible(timeout=10_000)
        expect(status).to_contain_text("aren’t saved yet")
        expect(status).to_contain_text('Save Game Availability')
        # Nothing reloaded, the change is still there, and the view did not change.
        assert coach.evaluate('() => window.__sameDocument === true')
        expect(switch).to_be_checked()
        assert _view(coach) == ('updated', 'updated')
        assert _view(device(DESKTOP)) == ('updated', 'updated')

        # Undone by hand, it is no longer unsaved: the switch goes ahead.
        status.click()
        expect(status).to_be_hidden()
        switch.click()
        expect(switch).not_to_be_checked()
        _choose(coach, 'classic')
        expect(coach.locator('body')).to_have_attribute('data-cb-view', 'classic', timeout=10_000)
        assert coach.evaluate('() => window.__sameDocument === undefined')
        assert coach.cb_errors == []
    finally:
        _delete(coach, classic_view_url, game_id)


def _pick(page, position, name):
    """The Prepare Game defense editor: tap a position, choose a player."""
    page.locator(f'#pregame-defense-editor-v3 [data-pde-pos="{position}"]').click()
    modal = page.locator('#pde-player-modal')
    expect(modal).to_be_visible(timeout=10_000)
    modal.locator(f'.pde-choice[data-player="{name}"]').click()
    expect(modal).to_be_hidden(timeout=10_000)


def test_a_defense_save_in_the_air_is_waited_for_and_a_failed_one_stops_it(device, classic_view_url, reset_views):
    coach = device(DESKTOP)
    game_id = _game(coach, classic_view_url, 'Saves In The Air')
    try:
        coach.goto(f'{classic_view_url}/game/{game_id}')
        expect(coach.locator('#pregame-defense-editor-v3')).to_be_visible(timeout=15_000)

        # A save that fails: the switch stops, the edit stays on screen.
        coach.route('**/save_rotation', lambda route: route.fulfill(
            status=500, json={'status': 'error', 'message': 'Simulated outage'}))
        _pick(coach, 'SS', 'Shortstop Shawn')
        coach.evaluate('() => { window.__sameDocument = true; }')
        _choose(coach, 'classic')
        status = coach.locator('#cbViewSwitchStatus')
        expect(status).to_contain_text("defense plan didn’t save", timeout=20_000)
        assert coach.evaluate('() => window.__sameDocument === true')
        expect(coach.locator('#pregame-defense-editor-v3 [data-pde-pos="SS"] .pde-name')).to_have_text('Shortstop Shawn')
        assert _view(coach) == ('updated', 'updated')
        coach.unroute('**/save_rotation')

        # A save held in the air: the switch waits for it, then goes ahead,
        # and the edit is saved.
        held = []
        coach.route('**/save_rotation', lambda route: held.append(route))
        _pick(coach, 'SS', 'Second Sam')
        coach.wait_for_function('() => window.CBPregameRotation.isSaveInFlightOrQueued()')
        _choose(coach, 'classic')
        coach.wait_for_timeout(800)
        assert coach.evaluate('() => window.__sameDocument === true'), 'reloaded before the save landed'
        assert held, 'the save should still be in the air'
        for route in held:
            route.continue_()
        coach.unroute('**/save_rotation')
        expect(coach.locator('body')).to_have_attribute('data-cb-view', 'classic', timeout=20_000)
        saved = coach.request.get(f'{classic_view_url}/api/game_data/{game_id}').json()
        assert saved['rotation']['innings']['1']['SS'] == 'Second Sam'
        # Now on Classic Prepare Game: the same saved edit, on its diamond.
        expect(coach.locator('#pos-desktop-SS .player-tag')).to_have_text('Second Sam', timeout=15_000)
    finally:
        _delete(coach, classic_view_url, game_id)


@pytest.mark.parametrize('spec', [IPAD, PHONE], ids=lambda s: s[0])
def test_a_live_game_shows_the_updated_live_screens(device, classic_view_url, reset_views, spec):
    coach = device(spec)
    coach.request.post(f'{classic_view_url}/api/account/view', data={'view': 'classic'})
    game_id, player_ids = create_named_live_game(coach, classic_view_url)
    try:
        coach.goto(f'{classic_view_url}/game/{game_id}')
        expect(coach.locator('#cbQuickDefense')).to_be_visible(timeout=20_000)
        assert _view(coach) == ('updated', 'classic')
        expect(coach.locator('[data-cb-view-notice]')).to_have_count(0)
        # The same game before it starts would be Classic: the planning screens.
        upcoming = _game(coach, classic_view_url, 'Classic Before First Pitch')
        try:
            coach.goto(f'{classic_view_url}/game/{upcoming}')
            assert _view(coach) == ('classic', 'classic')
            expect(coach.locator('[data-cb-view-notice]')).to_be_visible()
            # When the game goes live on this page, the live modules publish
            # the new state (live_game_feedback_pass.js); the page then marks
            # itself Updated without a reload.
            coach.evaluate("""(id) => document.dispatchEvent(new CustomEvent('coachboard:live-state',
                {detail: {game_id: id, state: {game: {is_live: true}}}}))""", upcoming)
            assert _view(coach) == ('updated', 'classic')
            expect(coach.locator('[data-cb-view-notice]')).to_have_count(0)
        finally:
            _delete(coach, classic_view_url, upcoming)
        assert coach.cb_errors == []
    finally:
        remove_named_live_game(coach, classic_view_url, game_id, player_ids)


def _until(page, condition, timeout_ms=10_000):
    """Let the page run until `condition()` holds (a routed request arrived)."""
    for _ in range(timeout_ms // 50):
        if condition():
            return
        page.wait_for_timeout(50)
    raise AssertionError('timed out waiting for the request')


@pytest.mark.parametrize('spec', [DESKTOP, PHONE], ids=lambda s: s[0])
def test_work_started_while_the_choice_saves_keeps_page_and_choice_together(device, classic_view_url, reset_views, spec):
    """The view is chosen, and while the choice is on its way to the server
    the coach changes Availability. The page must not reload over that change,
    and the stored choice must match what the page shows."""
    coach = device(spec)
    game_id = _game(coach, classic_view_url, f'Race {spec[0]}')
    try:
        coach.goto(f'{classic_view_url}/game/{game_id}')
        coach.evaluate("() => bootstrap.Collapse.getOrCreateInstance(document.getElementById('availabilityCollapse')).show()")
        switch = coach.locator('#gameAvailabilityForm input[name="absent_players"]').first
        expect(switch).to_be_visible()
        coach.evaluate('() => { window.__sameDocument = true; }')

        posted, held = [], []

        def hold_first(route):
            posted.append(route.request.post_data_json['view'])
            if len(posted) == 1:
                held.append(route)
            else:
                route.continue_()
        coach.route('**/api/account/view', hold_first)

        _choose(coach, 'classic')
        _until(coach, lambda: held)
        switch.click()                       # a change made while it saves
        expect(switch).to_be_checked()
        held[0].continue_()

        status = coach.locator('#cbViewSwitchStatus')
        expect(status).to_contain_text("The view didn’t change", timeout=10_000)
        expect(status).to_contain_text('Save Game Availability')
        assert posted == ['classic', 'updated']           # put back
        assert coach.evaluate('() => window.__sameDocument === true')
        expect(switch).to_be_checked()
        assert _view(coach) == ('updated', 'updated')
        assert _view(device(DESKTOP)) == ('updated', 'updated')  # stored: Updated

        # If putting it back fails too, the page says what is stored, and the
        # menu shows it -- still no reload over the change.
        coach.unroute('**/api/account/view')
        posted.clear(); held.clear()

        def hold_then_fail(route):
            posted.append(route.request.post_data_json['view'])
            if len(posted) == 1:
                held.append(route)
            else:
                route.fulfill(status=503, json={'status': 'error', 'message': 'Simulated outage'})
        coach.route('**/api/account/view', hold_then_fail)
        status.click()
        switch.click()                       # undo, so the switch may start
        expect(switch).not_to_be_checked()
        _choose(coach, 'classic')
        _until(coach, lambda: held)
        switch.click()
        held[0].continue_()
        expect(status).to_contain_text('saved as Classic', timeout=10_000)
        assert coach.evaluate('() => window.__sameDocument === true')
        expect(switch).to_be_checked()
        assert coach.locator('body').get_attribute('data-cb-view-choice') == 'classic'
        assert coach.locator('[data-cb-view-set="classic"]').first.get_attribute('aria-pressed') == 'true'
        assert _view(device(DESKTOP)) == ('classic', 'classic')  # stored: Classic, as the menu says
        coach.unroute('**/api/account/view')
        assert coach.cb_errors == []
    finally:
        _delete(coach, classic_view_url, game_id)


IPAD_PRO_PORTRAIT = ('ipad-pro-portrait', {'width': 1032, 'height': 1376}, {'is_mobile': True, 'has_touch': True})
IPAD_PRO_LANDSCAPE = ('ipad-pro-landscape', {'width': 1376, 'height': 1032}, {'is_mobile': True, 'has_touch': True})


@pytest.mark.parametrize('spec', [IPAD_PRO_PORTRAIT, IPAD_PRO_LANDSCAPE, PHONE], ids=lambda s: s[0])
def test_classic_on_keeps_the_home_layout_and_header_fitting(device, classic_view_url, reset_views, spec):
    """With Classic chosen, Home still fits the iPad Pro (portrait and
    landscape) and a phone: the notice and the Screens menu add no width."""
    coach = device(spec)
    coach.request.post(f'{classic_view_url}/api/account/view', data={'view': 'classic'})
    coach.goto(f'{classic_view_url}/')
    coach.locator('.cb-home-dashboard .cb-home-quick').first.wait_for(timeout=20_000)
    expect(coach.locator('[data-cb-view-notice]')).to_be_visible()
    assert _view(coach) == ('classic', 'classic')
    # Against the device width, not innerWidth: mobile emulation widens the
    # layout viewport to fit overflow (see test_home_tablet_layout.MEASURE).
    fits = coach.evaluate("""(vw) => {
      const out = [...document.querySelectorAll('.cb-home-card, .cb-home-quick, [data-cb-view-notice], #userMenuDesktop, a[href="#userOffcanvas"]')]
        .filter(e => e.getClientRects().length)
        .filter(e => { const r = e.getBoundingClientRect(); return r.left < -0.5 || r.right > vw + 0.5; })
        .map(e => e.className || e.id);
      return {scroll: document.documentElement.scrollWidth, vw, out};
    }""", spec[1]['width'])
    assert fits['scroll'] <= fits['vw'] and fits['out'] == [], fits
    # The menu still offers both views, and the choice is marked.
    if spec[1]['width'] >= 992:
        coach.locator('#userMenuDesktop').click()
        expect(coach.locator('.dropdown-menu [data-cb-view-set="classic"]')).to_have_attribute('aria-pressed', 'true')
    else:
        coach.locator('a[href="#userOffcanvas"]').click()
        expect(coach.locator('#userOffcanvas [data-cb-view-set="classic"]')).to_have_attribute('aria-pressed', 'true')
    assert coach.cb_errors == []
