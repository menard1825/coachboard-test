"""Plan Next Inning is a workspace of its own, not a sheet over the live game.

On a real 1344x865 tablet the planner floated over the live screen, which
stayed visible, undimmed and tappable around it: coach-live-polish-styles
hides every child of #live-game-overlay but the live shell and dialogs, so
the planner's backdrop never rendered, and a tap above the planner opened
the live field's Move Player. Now:

* the planner covers the screen at every size, under a sticky bar with the
  way back (Live Field), the inning, the save state and Undo;
* the live screen behind it is inert -- no tap, click or Tab reaches it --
  and does not scroll; only the planner scrolls;
* wider than tall from 700px, or from 1000px, it is two columns: the field
  sized by the height, the bench and tools beside it; otherwise one column;
* focus goes into the planner when it opens and back to the Plan button
  when it closes; Escape closes it unless a dialog is open;
* dialogs opened from the planner are above it and usable.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_reference import PHONE, _api, live  # noqa: E402,F401 (live is a fixture)


TOUCH = {'is_mobile': True, 'has_touch': True}
SMALL_PHONE = ('small-phone', {'width': 320, 'height': 700}, TOUCH)
TABLET_PORTRAIT = ('tablet-portrait', {'width': 820, 'height': 1180}, TOUCH)
TABLET_LANDSCAPE = ('tablet-landscape', {'width': 1180, 'height': 820}, TOUCH)
ANDROID_LANDSCAPE = ('android-landscape', {'width': 1280, 'height': 800}, TOUCH)
REPORTED_TABLET = ('reported-tablet', {'width': 1344, 'height': 865}, TOUCH)
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})

PLANNER = '#live-board-prep-v3'
PLAN_BUTTON = '#cb-now-next-switch [data-now-next="next"]'
BACK = f'{PLANNER} [data-next-close]'
UNDO = f'{PLANNER} [data-next-undo-local]'
PICKER = '#cbNextOpenPositionPicker'

ids = lambda device: device[0]  # noqa: E731


def _open_planner(page, url):
    page.goto(f'{url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)
    page.locator(PLAN_BUTTON).click()
    expect(page.locator(PLANNER)).to_be_visible()
    page.wait_for_timeout(300)


def _box(page, selector):
    return page.locator(selector).bounding_box()


# Every point of the screen belongs to the planner.
HITS_OUTSIDE = """() => {
  const planner = document.querySelector('#live-board-prep-v3');
  const outside = new Set();
  for (let x = 4; x < innerWidth; x += innerWidth / 16)
    for (let y = 4; y < innerHeight; y += innerHeight / 16) {
      const hit = document.elementFromPoint(x, y);
      if (hit && !planner.contains(hit)) outside.add(hit.id || hit.tagName);
    }
  return [...outside];
}"""

LIVE_CONTROLS = ['#cbQuickDefense [data-cb-move-player]', '#cbQuickDefense .cb-qd-bench-player',
                 '#liveEndInningBtn', '#liveChangePitcherBtn', '#liveUndoBtn', PLAN_BUTTON]

INERT = """selectors => Object.fromEntries(selectors.map(sel => {
  const el = document.querySelector(sel);
  return [sel, el ? Boolean(el.closest('[inert]')) : 'missing'];
}))"""

SCROLL = """() => [document.getElementById('live-game-overlay').scrollTop,
                  document.scrollingElement.scrollTop, scrollY]"""


@pytest.mark.parametrize('device', [SMALL_PHONE, PHONE, TABLET_PORTRAIT, REPORTED_TABLET, DESKTOP], ids=ids)
def test_the_planner_is_a_full_screen_workspace(live, coachboard_url, device):
    page = live(device)
    _open_planner(page, coachboard_url)
    viewport = page.viewport_size
    planner = _box(page, PLANNER)
    assert planner['x'] == 0 and planner['y'] == 0
    assert planner['width'] >= viewport['width'] - 1 and planner['height'] >= viewport['height'] - 1

    # The bar: the way back, the inning, the save state and Undo, together.
    bar = _box(page, f'{PLANNER} .cb-next-bar')
    expect(page.locator(f'{PLANNER} .cb-next-bar .cb-next-title')).to_have_text('2nd Inning Defense')
    expect(page.locator(f'{PLANNER} .cb-next-bar [data-next-save-state]')).to_be_visible()
    for control in (BACK, UNDO):
        box = _box(page, control)
        assert box['height'] >= 44 and box['width'] >= 44, (control, box)
        assert bar['y'] <= box['y'] and box['y'] + box['height'] <= bar['y'] + bar['height'] + 1
    assert page.cb_errors == []


@pytest.mark.parametrize('device', [PHONE, TABLET_PORTRAIT, REPORTED_TABLET, DESKTOP], ids=ids)
def test_the_live_screen_is_inert_while_planning(live, coachboard_url, device):
    page = live(device)
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.wait_for_timeout(800)
    # Where a live player is, before the planner opens.
    marker = _box(page, '#cbQuickDefense [data-cb-position="CF"]')
    page.locator(PLAN_BUTTON).click()
    expect(page.locator(PLANNER)).to_be_visible()
    page.wait_for_timeout(300)

    assert page.evaluate(HITS_OUTSIDE) == []
    assert all(value is True for value in page.evaluate(INERT, LIVE_CONTROLS).values())
    # A tap where the live CF was reaches the planner, not the live field.
    page.mouse.click(marker['x'] + marker['width'] / 2, marker['y'] + marker['height'] / 2)
    page.wait_for_timeout(400)
    expect(page.locator('#cbQuickMoveModal')).to_have_count(0)
    # Tab never leaves the planner for the live screen.
    for _ in range(30):
        page.keyboard.press('Tab')
        assert page.evaluate("""() => { const a = document.activeElement;
            return !a || a === document.body || Boolean(a.closest('#live-board-prep-v3')); }""")

    page.locator(BACK).click()
    expect(page.locator(PLANNER)).to_be_hidden()
    assert not any(value is True for value in page.evaluate(INERT, LIVE_CONTROLS).values())
    page.locator('#cbQuickDefense [data-cb-position="CF"]').click()
    expect(page.locator('#cbQuickMoveModal')).to_be_visible()
    assert page.cb_errors == []


def test_only_the_planner_scrolls(live, coachboard_url):
    from test_live_game_shared_drag_contract import TouchDriver, centres

    page = live(SMALL_PHONE)
    _open_planner(page, coachboard_url)
    before = page.evaluate(SCROLL)
    planner = page.locator(PLANNER)
    assert planner.evaluate('el => el.scrollHeight > el.clientHeight')

    # A swipe that starts on a player scrolls the planner, not the page.
    (x, y), = centres(page.locator(f'{PLANNER} [data-next-position="SS"]'))
    TouchDriver(page).down(x, y).move_to(x, y - 160, steps=16, pause_ms=6).up()
    page.wait_for_timeout(400)
    assert planner.evaluate('el => el.scrollTop') > 0
    assert page.evaluate(SCROLL) == before

    # Scrolling past the planner's end does not carry on into the live page.
    page.mouse.move(x, y)
    page.mouse.wheel(0, 3000)
    page.wait_for_timeout(400)
    assert page.evaluate(SCROLL) == before
    assert page.cb_errors == []


@pytest.mark.parametrize('device', [TABLET_LANDSCAPE, ANDROID_LANDSCAPE, REPORTED_TABLET], ids=ids)
def test_tablet_landscape_is_two_columns(live, coachboard_url, device):
    page = live(device)
    _open_planner(page, coachboard_url)
    viewport = page.viewport_size
    field = _box(page, f'{PLANNER} .cb-next-field')
    bench = _box(page, f'{PLANNER} .cb-next-bench')
    tools = _box(page, f'{PLANNER} .cb-next-tools')

    # Field on the left (about 55-60% of the screen), bench and tools beside it.
    assert 0.5 <= field['width'] / viewport['width'] <= 0.62, field
    assert bench['x'] >= field['x'] + field['width']
    assert tools['x'] == bench['x']
    # All of it on screen at once.
    for box in (field, bench, tools):
        assert box['y'] + box['height'] <= viewport['height'], box
    assert page.cb_errors == []


def test_tablet_portrait_is_one_column(live, coachboard_url):
    page = live(TABLET_PORTRAIT)
    _open_planner(page, coachboard_url)
    field = _box(page, f'{PLANNER} .cb-next-field')
    bench = _box(page, f'{PLANNER} .cb-next-bench')
    assert bench['y'] >= field['y'] + field['height']
    assert field['width'] >= 0.9 * page.viewport_size['width']
    assert bench['y'] + bench['height'] <= page.viewport_size['height']


@pytest.mark.parametrize('device', [PHONE, REPORTED_TABLET], ids=ids)
def test_focus_goes_in_and_comes_back(live, coachboard_url, device):
    page = live(device)
    _open_planner(page, coachboard_url)
    expect(page.locator(BACK)).to_be_focused()

    page.locator(BACK).click()
    expect(page.locator(PLANNER)).to_be_hidden()
    expect(page.locator(PLAN_BUTTON)).to_be_focused()

    page.locator(PLAN_BUTTON).click()
    expect(page.locator(BACK)).to_be_focused()
    page.keyboard.press('Escape')
    expect(page.locator(PLANNER)).to_be_hidden()
    expect(page.locator(PLAN_BUTTON)).to_be_focused()

    # A redraw (a plan save, here an edit and its Undo) keeps focus inside.
    page.locator(PLAN_BUTTON).click()
    planner = page.locator(PLANNER)
    planner.locator('[data-next-position="LF"]').click()
    planner.locator('[data-next-position="RF"]').click()
    expect(page.locator(UNDO)).to_be_enabled(timeout=5_000)
    page.locator(UNDO).click()
    expect(page.locator(UNDO)).to_be_disabled(timeout=5_000)
    assert page.evaluate("() => Boolean(document.activeElement?.closest('#live-board-prep-v3'))")
    assert page.cb_errors == []


@pytest.mark.parametrize('device', [PHONE, REPORTED_TABLET], ids=ids)
def test_a_dialog_from_the_planner_is_above_it_and_usable(live, coachboard_url, device):
    page = live(device)
    prep = page.cb_api.request.get(_api(page, coachboard_url, 'next-inning-prep')).json()
    response = page.cb_api.request.post(_api(page, coachboard_url, 'next-inning-prep'), data={
        'mode': 'custom', 'alignment': dict(prep['confirmed']['alignment'], CF=''),
        'base_alignment': prep['confirmed']['alignment'], 'inning': prep['next_inning']})
    assert response.ok, response.text()[:300]
    _open_planner(page, coachboard_url)
    planner = page.locator(PLANNER)
    picker = page.locator(PICKER)

    planner.locator('[data-next-position="CF"]').click()
    expect(picker).to_be_visible()
    page.wait_for_timeout(500)                       # fully shown
    choice = picker.locator('.modal-body button').first
    on_top = page.evaluate("""sel => { const el = document.querySelector(sel); const r = el.getBoundingClientRect();
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return hit === el || el.contains(hit); }""", f'{PICKER} .modal-body button')
    assert on_top

    # Escape belongs to the dialog: it closes, the planner stays.
    page.keyboard.press('Escape')
    expect(picker).to_be_hidden()
    expect(planner).to_be_visible()

    planner.locator('[data-next-position="CF"]').click()
    expect(picker).to_be_visible()
    page.wait_for_timeout(500)
    name = choice.inner_text().split('\n')[0].lstrip('#0123456789 ').strip()
    choice.click()
    expect(planner.locator('[data-next-position="CF"]')).to_have_attribute('data-next-player', name, timeout=5_000)
    expect(planner).to_be_visible()
    assert page.cb_errors == []
