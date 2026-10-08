"""Undo plan edit undoes this coach's own last plan change -- never another's.

Two coaches on one game: the head coach (A, this page) and the assistant
(B, a second signed-in browser). Undo used to take back whoever saved last:
B, having received A's save, could undo it. Now the server refuses that
(next_prep_not_yours) and every read says whether this coach may undo, so:

* A's own save: Undo on, and it works -- after a reload too;
* B's save, received live or on opening the game: A's Undo is off;
* a screen that missed B's save, or an Undo that crosses it in flight: the
  server refuses, the board shows B's plan, and A reads
  "That plan was changed by another coach. Nothing was undone.";
* A's own save still in the air: Undo waits for it, then undoes it.
"""

import json
import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from live_fixtures import PHONE, api_url as _api, live  # noqa: E402,F401 (live is a fixture)


ASSISTANT = ('playwright-assistant', 'playwright-assistant-password')
PLANNER = '#live-board-prep-v3'
PLAN_BUTTON = '#cb-now-next-switch [data-now-next="next"]'
UNDO = f'{PLANNER} [data-next-undo-local]'
NOTICE = f'{PLANNER} [data-next-notice]'
NOT_YOURS = 'That plan was changed by another coach. Nothing was undone.'


def _filled(alignment):
    return {pos: name for pos, name in (alignment or {}).items() if name}


def _prep(request, url, page):
    response = request.get(_api(page, url, 'next-inning-prep'))
    assert response.ok, response.text()[:300]
    return response.json()['confirmed']


def _save(request, url, page, **changes):
    """A Next Inning save through the API, as the session behind `request`."""
    confirmed = _prep(request, url, page)
    alignment = dict(confirmed['alignment'], **changes)
    data = request.get(_api(page, url, 'next-inning-prep')).json()
    response = request.post(_api(page, url, 'next-inning-prep'), data={
        'mode': 'custom', 'alignment': alignment,
        'base_alignment': confirmed['alignment'], 'inning': data['next_inning']})
    assert response.ok, response.text()[:300]
    return response.json()['confirmed']


def _swap(confirmed, a, b):
    return {a: confirmed['alignment'][b], b: confirmed['alignment'][a]}


@pytest.fixture
def assistant(browser, coachboard_url):
    """Coach B: the team's assistant coach, signed in on another browser."""
    contexts = []

    def _open(page_a):
        context = browser.new_context(viewport=PHONE[1], **PHONE[2])
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        page.goto(f'{coachboard_url}/login')
        page.get_by_label('Username or email').fill(ASSISTANT[0])
        page.locator('#password').fill(ASSISTANT[1])
        page.get_by_role('button', name='Sign In').click()
        page.wait_for_load_state('load')
        page.cb_game = page_a.cb_game
        return page

    yield _open
    for context in contexts:
        context.close()


def _open_planner(page, url):
    page.goto(f'{url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(600)
    page.locator(PLAN_BUTTON).click()
    expect(page.locator(PLANNER)).to_be_visible()


def _tap_swap(page, a, b):
    planner = page.locator(PLANNER)
    planner.locator(f'[data-next-position="{a}"]').click()
    planner.locator(f'[data-next-position="{b}"]').click()


def test_own_change_can_be_undone_and_survives_a_reload(live, coachboard_url):
    page = live(PHONE)
    _open_planner(page, coachboard_url)
    before = _filled(_prep(page.cb_api.request, coachboard_url, page)['alignment'])
    expect(page.locator(UNDO)).to_be_disabled()

    _tap_swap(page, 'LF', 'RF')
    expect(page.locator(UNDO)).to_be_enabled(timeout=5_000)
    page.reload()
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.locator(PLAN_BUTTON).click()
    expect(page.locator(UNDO)).to_be_enabled(timeout=5_000)           # from the server, not memory
    page.locator(UNDO).click()
    expect(page.locator(UNDO)).to_be_disabled(timeout=5_000)
    expect(page.locator(f'{PLANNER} [data-next-undo-note]')).to_contain_text('Undid your last change')
    assert _filled(_prep(page.cb_api.request, coachboard_url, page)['alignment']) == before
    assert page.cb_errors == []


def test_another_coachs_save_cannot_be_undone(live, assistant, coachboard_url):
    page = live(PHONE)
    _open_planner(page, coachboard_url)
    _tap_swap(page, 'LF', 'RF')                                          # A's save
    expect(page.locator(UNDO)).to_be_enabled(timeout=5_000)
    saved = _filled(_prep(page.cb_api.request, coachboard_url, page)['alignment'])

    other = assistant(page)
    _open_planner(other, coachboard_url)                                 # B opens after A saved
    expect(other.locator(f'{PLANNER} [data-next-position="LF"]')).to_have_attribute(
        'data-next-player', saved['LF'])
    expect(other.locator(UNDO)).to_be_disabled()
    other.wait_for_timeout(1_000)
    expect(other.locator(UNDO)).to_be_disabled()                         # polls keep it off
    assert page.cb_errors == []


def test_ownership_updates_live_when_another_coach_saves(live, assistant, coachboard_url):
    page = live(PHONE)
    _open_planner(page, coachboard_url)
    _tap_swap(page, 'LF', 'RF')                                          # A's save
    expect(page.locator(UNDO)).to_be_enabled(timeout=5_000)

    other = assistant(page)
    confirmed = _prep(other.request, coachboard_url, page)
    theirs = _save(other.request, coachboard_url, page, **_swap(confirmed, '2B', 'SS'))

    # A, planner open, receives B's plan: the board follows, Undo turns off.
    expect(page.locator(f'{PLANNER} [data-next-position="2B"]')).to_have_attribute(
        'data-next-player', theirs['alignment']['2B'], timeout=10_000)
    expect(page.locator(UNDO)).to_be_disabled()
    assert page.cb_errors == []


def test_a_stale_screen_is_refused_and_told_why(live, assistant, coachboard_url):
    page = live(PHONE)
    _open_planner(page, coachboard_url)
    _tap_swap(page, 'LF', 'RF')                                          # A's save
    expect(page.locator(UNDO)).to_be_enabled(timeout=5_000)
    expect(page.locator(f'{PLANNER} [data-next-save-state]')).to_contain_text('✓', timeout=5_000)

    # A's screen hears nothing more (reads are held) while B saves.
    held, holding = [], {'on': True}

    def hold_reads(route):
        if holding['on'] and route.request.method == 'GET':
            held.append(route)
        else:
            route.continue_()

    page.route(re.compile(r'.*/next-inning-prep$'), hold_reads)
    other = assistant(page)
    confirmed = _prep(other.request, coachboard_url, page)
    theirs = _save(other.request, coachboard_url, page, **_swap(confirmed, '2B', 'SS'))
    expect(page.locator(UNDO)).to_be_enabled()                           # A has not seen it

    with page.expect_response(lambda r: r.url.endswith('/next-inning-prep')
                              and r.request.method == 'POST') as answer:
        page.locator(UNDO).click()
    assert answer.value.status == 409
    assert answer.value.json()['code'] == 'next_prep_not_yours'
    holding['on'] = False
    for route in held:
        route.continue_()

    expect(page.locator(NOTICE)).to_have_text(NOT_YOURS, timeout=10_000)
    expect(page.locator(f'{PLANNER} [data-next-position="2B"]')).to_have_attribute(
        'data-next-player', theirs['alignment']['2B'], timeout=10_000)
    expect(page.locator(UNDO)).to_be_disabled()
    expect(page.locator(f'{PLANNER} [data-next-undo-note]')).to_have_count(0)
    assert _filled(_prep(page.cb_api.request, coachboard_url, page)['alignment']) == _filled(theirs['alignment'])
    assert page.cb_errors == []


def test_an_undo_crossing_another_coachs_save_does_not_overwrite_it(live, assistant, coachboard_url):
    page = live(PHONE)
    _open_planner(page, coachboard_url)
    _tap_swap(page, 'LF', 'RF')
    expect(page.locator(UNDO)).to_be_enabled(timeout=5_000)
    expect(page.locator(f'{PLANNER} [data-next-save-state]')).to_contain_text('✓', timeout=5_000)

    other = assistant(page)
    held = []

    def hold_undo(route):
        body = route.request.post_data_json if route.request.method == 'POST' else None
        if isinstance(body, dict) and body.get('mode') == 'undo' and not held:
            held.append(route)
        else:
            route.continue_()

    page.route(re.compile(r'.*/next-inning-prep$'), hold_undo)
    page.locator(UNDO).click()                                           # A's Undo is in the air ...
    page.wait_for_timeout(300)
    assert len(held) == 1
    confirmed = _prep(other.request, coachboard_url, page)
    theirs = _save(other.request, coachboard_url, page, **_swap(confirmed, '2B', 'SS'))  # ... B saves
    held[0].continue_()

    expect(page.locator(NOTICE)).to_have_text(NOT_YOURS, timeout=10_000)
    assert _filled(_prep(page.cb_api.request, coachboard_url, page)['alignment']) == _filled(theirs['alignment'])
    expect(page.locator(f'{PLANNER} [data-next-position="2B"]')).to_have_attribute(
        'data-next-player', theirs['alignment']['2B'], timeout=10_000)
    expect(page.locator(UNDO)).to_be_disabled()
    assert page.cb_errors == []


def test_undo_waits_for_own_save_in_flight_then_undoes_it(live, coachboard_url):
    page = live(PHONE)
    _open_planner(page, coachboard_url)
    before = _filled(_prep(page.cb_api.request, coachboard_url, page)['alignment'])
    cdp = page.context.new_cdp_session(page)
    cdp.send('Network.enable')
    cdp.send('Network.emulateNetworkConditions', {
        'offline': False, 'latency': 700, 'downloadThroughput': -1, 'uploadThroughput': -1})

    _tap_swap(page, 'LF', 'RF')
    expect(page.locator(f'{PLANNER} [data-next-save-state]')).to_contain_text('Saving')
    expect(page.locator(UNDO)).to_be_enabled()                           # own change in the air
    page.locator(UNDO).click()
    expect(page.locator(f'{PLANNER} [data-next-undo-note]')).to_contain_text(
        'Undid your last change', timeout=15_000)
    expect(page.locator(UNDO)).to_be_disabled()
    assert _filled(_prep(page.cb_api.request, coachboard_url, page)['alignment']) == before
    assert page.cb_errors == []


def test_rapid_edits_then_one_undo_keeps_one_step(live, coachboard_url):
    page = live(PHONE)
    _open_planner(page, coachboard_url)
    posts = []
    page.on('request', lambda r: posts.append(json.loads(r.post_data or '{}').get('mode'))
            if r.method == 'POST' and r.url.endswith('/next-inning-prep') else None)

    _tap_swap(page, 'LF', 'RF')
    _tap_swap(page, '2B', 'SS')
    expect(page.locator(f'{PLANNER} [data-next-save-state]')).to_contain_text('✓', timeout=10_000)
    expect(page.locator(UNDO)).to_be_enabled()
    confirmed = _prep(page.cb_api.request, coachboard_url, page)
    previous = _filled(confirmed['previous']['alignment'])               # before the last save

    page.locator(UNDO).click()
    # Off at once (an Undo is under way) -- done only when the server has
    # confirmed it and the board says what came back.
    expect(page.locator(UNDO)).to_be_disabled(timeout=5_000)
    expect(page.locator(f'{PLANNER} [data-next-undo-note]')).to_contain_text(
        'Undid your last change', timeout=10_000)
    expect(page.locator(UNDO)).to_be_disabled()
    assert _filled(_prep(page.cb_api.request, coachboard_url, page)['alignment']) == previous
    assert posts.count('undo') == 1
    assert page.cb_errors == []
