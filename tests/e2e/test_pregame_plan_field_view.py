"""Pregame Plan shows one planned inning at a time, on the field.

The tab used to list every inning as a block of nine same-looking tiles with
the position in tiny grey type, which was slow to read mid-game. It now uses
the same field as On the Field and Next Inning: inning buttons across the top
(opening on the next inning), the planned defense on the field, what changed
from the inning before, and who sits. It is still reference only.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from live_field_markers import LINEUP, create_named_live_game, login, remove_named_live_game  # noqa: E402


PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
SMALL_PHONE = ('small-phone', {'width': 360, 'height': 740}, {'is_mobile': True, 'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
DEVICES = pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])
CARD = '#live-board-pregame-plan'

INNING_1 = {pos: name for pos, (name, _) in LINEUP.items()}
# Inning 2: the first baseman pitches and the pitcher goes to first.
INNING_2 = {**INNING_1, 'P': INNING_1['1B'], '1B': INNING_1['P']}
# Inning 3: shortstop and second base swap.
INNING_3 = {**INNING_2, 'SS': INNING_2['2B'], '2B': INNING_2['SS']}
PLAN = {'1': INNING_1, '2': INNING_2, '3': INNING_3}

#: Every marker on the plan field: where it sits and whether its name fits.
MEASURE = """(field) => {
  const f = field.getBoundingClientRect();
  const markers = [...field.querySelectorAll('[data-plan-position]')].map(spot => {
    const name = spot.querySelector('.cb-qd-name');
    const r = spot.getBoundingClientRect(), n = name.getBoundingClientRect();
    return {pos: spot.dataset.planPosition, tag: spot.tagName,
            box: {left: r.left, right: r.right, top: r.top, bottom: r.bottom},
            name: {left: n.left, right: n.right, top: n.top, bottom: n.bottom},
            fits: name.scrollWidth <= name.clientWidth + 1 && name.scrollHeight <= name.clientHeight + 1,
            px: parseFloat(getComputedStyle(name).fontSize)};
  });
  const hit = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;
  const overlaps = [];
  markers.forEach((a, i) => markers.forEach((b, j) => { if (i < j && hit(a.name, b.name)) overlaps.push([a.pos, b.pos]); }));
  const outside = markers.filter(m => m.box.left < f.left - 1 || m.box.right > f.right + 1 || m.box.top < f.top - 1 || m.box.bottom > f.bottom + 1).map(m => m.pos);
  return {markers, overlaps, outside};
}"""


@pytest.fixture(scope='module')
def game(browser, coachboard_url):
    context = browser.new_context()
    cdn_assets.install(context)
    page = context.new_page()
    login(page, coachboard_url)
    game_id, player_ids = create_named_live_game(page, coachboard_url, innings=PLAN)
    yield game_id
    remove_named_live_game(page, coachboard_url, game_id, player_ids)
    context.close()


@pytest.fixture
def open_plan(browser, coachboard_url, game):
    contexts = []

    def _open(device):
        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        errors, writes = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: writes.append(request.url)
                if request.method != 'GET' and '/api/live-game/' in request.url else None)
        page.cb_errors, page.cb_writes = errors, writes
        login(page, coachboard_url)
        page.goto(f'{coachboard_url}/game/{game}')
        page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
        page.locator('#cb-now-next-switch [data-now-next="plan"]').click()
        # Shown at once, not after the next background refresh.
        expect(page.locator(f'{CARD} .cb-plan-field')).to_be_visible(timeout=1_500)
        return page

    yield _open
    for context in contexts:
        context.close()


def _names(page):
    return {pos: page.locator(f'{CARD} [data-plan-position="{pos}"] .cb-qd-name').inner_text().strip()
            for pos in INNING_1}


def _show(page, inning):
    page.locator(f'{CARD} [data-plan-inning="{inning}"]').click()
    expect(page.locator(f'{CARD} [data-plan-inning="{inning}"]')).to_have_attribute('aria-pressed', 'true')


def _changed(page):
    return sorted(page.locator(f'{CARD} [data-plan-position][data-plan-changed="true"]').evaluate_all(
        'els => els.map(el => el.dataset.planPosition)'))


@DEVICES
def test_plan_opens_on_the_next_inning_as_a_field(open_plan, device):
    page = open_plan(device)
    card = page.locator(CARD)
    expect(card.locator('.cb-plan-title')).to_have_text('Pregame Card · 2nd')
    expect(card.locator('.cb-plan-sub')).to_have_text('Reference · not what goes out')
    expect(card.locator('[data-plan-inning="2"]')).to_have_attribute('aria-pressed', 'true')
    expect(card.locator('.cb-plan-inning-title')).to_contain_text('Inning 2')
    expect(card.locator('.cb-plan-inning-title')).to_contain_text('On deck')
    assert _names(page) == INNING_2

    data = card.locator('.cb-plan-field').evaluate(MEASURE)
    assert len(data['markers']) == 9
    assert data['outside'] == [] and data['overlaps'] == [], data
    for marker in data['markers']:
        assert marker['tag'] != 'BUTTON', marker            # reference only: nothing to tap on the field
        assert marker['fits'] and marker['px'] >= 10, marker
    assert page.cb_errors == []


@DEVICES
def test_every_planned_inning_is_one_tap_away(open_plan, device):
    page = open_plan(device)
    card = page.locator(CARD)
    buttons = card.locator('[data-plan-inning]')
    assert buttons.evaluate_all('els => els.map(el => el.dataset.planInning)') == ['1', '2', '3']
    expect(card.locator('[data-plan-inning="1"]')).to_contain_text('Now')

    _show(page, 3)
    assert _names(page) == INNING_3
    _show(page, 1)
    assert _names(page) == INNING_1
    expect(card.locator('.cb-plan-inning-title')).to_contain_text('Being played')

    # The inning chosen stays chosen through the background refreshes.
    _show(page, 3)
    page.wait_for_timeout(4_500)
    expect(card.locator('[data-plan-inning="3"]')).to_have_attribute('aria-pressed', 'true')
    assert _names(page) == INNING_3
    assert page.cb_errors == []


@DEVICES
def test_changes_from_the_inning_before_are_marked(open_plan, device):
    page = open_plan(device)
    card = page.locator(CARD)

    # Inning 2: the pitcher and first baseman swapped.
    assert _changed(page) == ['1B', 'P']
    expect(card.locator('.cb-plan-changes')).to_have_text('Changed from Inning 1: P, 1B')
    label = card.locator('[data-plan-position="P"]').get_attribute('aria-label')
    assert INNING_2['P'] in label and 'changed' in label.lower(), label
    # A changed marker looks different from an unchanged one.
    look = 'el => getComputedStyle(el.querySelector(".cb-qd-name")).boxShadow + getComputedStyle(el.querySelector(".cb-qd-name")).borderColor'
    assert card.locator('[data-plan-position="P"]').evaluate(look) != card.locator('[data-plan-position="C"]').evaluate(look)

    _show(page, 3)
    assert _changed(page) == ['2B', 'SS']
    expect(card.locator('.cb-plan-changes')).to_have_text('Changed from Inning 2: 2B, SS')

    _show(page, 1)
    assert _changed(page) == []
    expect(card.locator('.cb-plan-changes')).to_have_text('First inning of the plan')
    assert page.cb_errors == []


@DEVICES
def test_bench_lists_who_sits_that_inning(open_plan, device):
    page = open_plan(device)
    bench = page.locator(f'{CARD} .cb-plan-bench')
    expect(bench).to_be_visible()
    text = bench.inner_text()
    for name in INNING_2.values():
        assert name not in text, name
    assert 'Card bench' in text
    assert page.cb_errors == []


@DEVICES
def test_looking_at_the_plan_changes_nothing(open_plan, device):
    page = open_plan(device)
    for inning in (1, 3, 2):
        _show(page, inning)
    page.wait_for_timeout(600)
    assert page.cb_writes == []
    assert page.cb_errors == []


@pytest.mark.parametrize('device', [PHONE, SMALL_PHONE], ids=lambda d: d[0])
def test_long_names_stay_whole_on_a_phone(open_plan, device):
    """Names wrap between words, never inside one ("Hollingsw-orth")."""
    page = open_plan(device)
    field = page.locator(f'{CARD} .cb-plan-field')
    for inning in (2, 3):
        _show(page, inning)
        data = field.evaluate(MEASURE)
        assert data['outside'] == [] and data['overlaps'] == [], (inning, data)
        split = field.locator('.cb-qd-name').evaluate_all("""els => els.filter(el => {
          const range = document.createRange(); range.selectNodeContents(el);
          const lines = new Set([...range.getClientRects()].filter(r => r.width > 1).map(r => Math.round(r.top))).size;
          return lines > el.innerText.trim().split(/\\s+/).length;
        }).map(el => el.innerText)""")
        assert split == [], (inning, split)
    assert page.cb_errors == []
