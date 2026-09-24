"""Secondary text stays readable on a phone outdoors.

CoachBoard is compact on purpose, but helper copy, meta lines, timestamps and
short actions had drifted down to 9-10px, often in a faint grey (#7b8492,
#8a94a3) that reads at about 3:1 on white. The floor is now:

* meaningful secondary text: --cb-text-xs (12px) in at least the muted grey;
* short uppercase kickers, labels and status pills: --cb-text-2xs (11px).

Each case below is real text a coach reads, measured as rendered at 390px:
its size, its contrast against what is actually painted behind it, and that
the larger text is not cut off by its container.
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


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
PHONE = {'width': 390, 'height': 844}
DESKTOP = {'width': 1440, 'height': 900}
TEXT_FLOOR_PX = 12
LABEL_PX = (10.5, 11.5)
AA = 4.5

#: Font size, rendered contrast and clipping of the first visible match.
MEASURE = """(el) => {
  const ctx = Object.assign(document.createElement('canvas'), {width: 1, height: 1}).getContext('2d');
  const paint = colors => {
    ctx.clearRect(0, 0, 1, 1);
    for (const c of colors) { ctx.fillStyle = c; ctx.fillRect(0, 0, 1, 1); }
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return [r, g, b];
  };
  const lum = rgb => { const [r, g, b] = rgb.map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * r + .7152 * g + .0722 * b; };
  const layers = [];
  for (let n = el; n; n = n.parentElement) layers.unshift(getComputedStyle(n).backgroundColor);
  const bg = paint(['#fff', ...layers]);
  const cs = getComputedStyle(el);
  const fg = paint([`rgb(${bg.join(',')})`, cs.color]);
  const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a);
  // Clipped: the text box runs past an ancestor that hides overflow.
  const box = el.getBoundingClientRect();
  let clipped = cs.overflow !== 'visible' && el.scrollWidth > el.clientWidth + 1;
  for (let n = el.parentElement; n && !clipped; n = n.parentElement) {
    const ov = getComputedStyle(n);
    if (ov.overflowX === 'visible' && ov.overflowY === 'visible') continue;
    if (n === document.body || n === document.documentElement) break;
    const r = n.getBoundingClientRect();
    if (ov.overflowX === 'hidden' && (box.left < r.left - 1 || box.right > r.right + 1)) clipped = true;
    if (ov.overflowY === 'hidden' && (box.top < r.top - 1 || box.bottom > r.bottom + 1)) clipped = true;
  }
  return {px: parseFloat(cs.fontSize), contrast: (hi + .05) / (lo + .05), clipped, text: el.innerText.trim().slice(0, 40)};
}"""


def _login(page, base_url):
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')


@pytest.fixture
def make_page(browser, coachboard_url):
    contexts = []

    def _make(viewport=PHONE):
        cdn_assets.require_vendored_assets()
        mobile = viewport is PHONE
        context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        _login(page, coachboard_url)
        return page

    yield _make
    for context in contexts:
        context.close()


def _measure(page, selector):
    target = page.locator(selector).locator('visible=true').first
    expect(target).to_be_visible(timeout=15_000)
    return target.evaluate(MEASURE)


def _open_practice_plan(page):
    plan = page.locator('#practicePlanAccordion .cb-practice-plan').first
    expect(plan).to_be_visible(timeout=15_000)
    plan.locator('.cb-practice-plan-button').click()
    expect(plan.locator('.accordion-collapse')).to_be_visible()


# --- meaningful secondary text: 12px and readable contrast ---------------------------

#: (page, selector, what a coach reads there)
SECONDARY_TEXT = [
    ('/#overview', '.cb-home-status small', 'readiness explanation on the next-game card'),
    ('/#overview', '.cb-home-text-link', 'View Practice Plan / Open Pitching links'),
    ('/#overview', '.cb-home-attention-row small', 'what an attention item needs'),
    ('/#roster', '.cb-roster-submetric .cb-roster-metric-copy', 'roster pitcher count'),
    ('/#practice_plan', '.cb-practice-meta span', 'practice attendance summary'),
    ('/#practice_plan', '#practice_plan .task-list .form-check-label .small', 'who added a setup task'),
    ('/#rotations', '#rotations .dph-head span', 'Starting Defense explanation'),
    ('/#collaboration', '#team-notes-container .card-body > small', 'note author and time'),
    ('/game-day', '.gd-alerts div', 'setup items still to finish'),
    ('/game/1', '.cgr-head small', 'pregame setup summary'),
    ('/game/1', '#pitcher-availability-card .gpa-summary', 'pitcher availability summary'),
    ('/pitching', '.cb-pitcher-last', 'last game outing'),
    ('/#stats', '.sv2-kpi span', 'stat card explanation'),
]


@pytest.mark.parametrize('path,selector,what', SECONDARY_TEXT, ids=[c[2] for c in SECONDARY_TEXT])
def test_secondary_text_is_readable_on_a_phone(make_page, coachboard_url, path, selector, what):
    page = make_page(PHONE)
    page.goto(f'{coachboard_url}{path}')
    if path == '/#practice_plan' and '.task-list' in selector:
        _open_practice_plan(page)
    page.wait_for_timeout(600)
    m = _measure(page, selector)
    assert m['px'] >= TEXT_FLOOR_PX, (what, m)
    assert m['contrast'] >= AA, (what, m)
    assert not m['clipped'], (what, m)
    assert page.cb_errors == []


# --- live game ----------------------------------------------------------------------

def _alignment():
    return {'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam',
            '3B': 'Third Theo', 'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey',
            'RF': 'Right Riley'}


@pytest.fixture
def live_game(make_page, coachboard_url):
    page = make_page(PHONE)
    response = page.request.post(f'{coachboard_url}/game-day/add', form={
        'game_date': (date.today() + timedelta(days=12)).isoformat(), 'game_start_time': '15:00',
        'game_opponent': 'Readability Live', 'game_location': 'Readability Field',
        'pitching_rule_set': 'USSSA',
    }, max_redirects=0)
    game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
    roster = page.request.get(f'{coachboard_url}/api/roster').json()
    page.request.post(f'{coachboard_url}/add_lineup', data={
        'title': 'Readability Lineup', 'lineup_player_ids': [int(p['id']) for p in roster],
        'associated_game_id': game_id})
    page.request.post(f'{coachboard_url}/save_rotation', data={
        'title': 'Readability Rotation', 'innings': {'1': _alignment(), '2': _alignment()},
        'associated_game_id': game_id})
    assert page.request.post(f'{coachboard_url}/api/live-game/{game_id}/start', data={}).ok
    page.goto(f'{coachboard_url}/game/{game_id}')
    expect(page.locator('#cbQuickDefense')).to_be_visible(timeout=20_000)
    page.wait_for_timeout(800)
    yield page
    page.request.post(f'{coachboard_url}/api/live-game/{game_id}/end-with-pitching', data={
        'defer_pitching': True, 'end_reason': 'manual', 'current_inning_played': True})
    page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})


def test_live_game_help_text_is_readable_on_a_phone(live_game):
    page = live_game
    for selector in ('#cbQuickDefense .cb-qd-help', '.cb-qd-bench-head span'):
        m = _measure(page, selector)
        assert m['px'] >= TEXT_FLOOR_PX, (selector, m)
        assert m['contrast'] >= AA, (selector, m)
        assert not m['clipped'], (selector, m)
    assert page.cb_errors == []


# --- compact labels may stay one step smaller ----------------------------------------

COMPACT_LABELS = [
    ('/#roster', 'body.cb-ui .cb-kicker', 'COACHBOARD kicker'),
    ('/game-day', '.gd-ready-label', 'Game Day readiness label'),
    ('/game-day', '.gd-status', 'Game Day status pill'),
    ('/game/1', '#pitcher-availability-card .gpa-label', 'pitcher card label'),
]


@pytest.mark.parametrize('path,selector,what', COMPACT_LABELS, ids=[c[2] for c in COMPACT_LABELS])
def test_compact_labels_stay_compact_but_legible(make_page, coachboard_url, path, selector, what):
    page = make_page(PHONE)
    page.goto(f'{coachboard_url}{path}')
    page.wait_for_timeout(600)
    m = _measure(page, selector)
    low, high = LABEL_PX
    # Not blown up to body-text size, not shrunk below legibility.
    assert low <= m['px'] <= high, (what, m)
    assert m['contrast'] >= AA, (what, m)
    assert page.cb_errors == []


# --- desktop keeps the same floor -------------------------------------------------------

@pytest.mark.parametrize('path,selector', [
    ('/#overview', '.cb-home-status small'),
    ('/game-day', '.gd-alerts div'),
    ('/game/1', '.cgr-head small'),
])
def test_desktop_secondary_text_keeps_the_floor(make_page, coachboard_url, path, selector):
    page = make_page(DESKTOP)
    page.goto(f'{coachboard_url}{path}')
    page.wait_for_timeout(600)
    m = _measure(page, selector)
    assert m['px'] >= TEXT_FLOOR_PX and m['contrast'] >= AA and not m['clipped'], (selector, m)
