"""Pregame Plan shows one inning at a time, as a list and on a field.

Inning buttons across the top (opening on the next inning), the planned
defense next to what the game has for that inning, what changed in the plan
from the inning before, and who sits. Phones show the list first with a Field
switch; wider screens show both. It is still reference only.
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
TINY_PHONE = ('tiny-phone', {'width': 320, 'height': 640}, {'is_mobile': True, 'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
DEVICES = pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])
CARD = '#live-board-pregame-plan'

INNING_1 = {pos: name for pos, (name, _) in LINEUP.items()}
# Inning 2: the first baseman pitches and the pitcher goes to first.
INNING_2 = {**INNING_1, 'P': INNING_1['1B'], '1B': INNING_1['P']}
# Inning 3: shortstop and second base swap.
INNING_3 = {**INNING_2, 'SS': INNING_2['2B'], '2B': INNING_2['SS']}
PLAN = {'1': INNING_1, '2': INNING_2, '3': INNING_3}

#: Every marker on the plan field: where it sits, and whether each name line
#: in it (the plan's, and the game's) fits without being cut short.
MEASURE = """(field) => {
  const f = field.getBoundingClientRect();
  const markers = [...field.querySelectorAll('[data-plan-position]')].map(spot => {
    const names = [...spot.querySelectorAll('.cb-plan-spot-plan, .cb-plan-spot-game')];
    const r = spot.getBoundingClientRect();
    return {pos: spot.dataset.planPosition, tag: spot.tagName,
            box: {left: r.left, right: r.right, top: r.top, bottom: r.bottom},
            texts: names.map(n => n.innerText.trim()),
            fits: names.length > 0 && names.every(n => n.scrollWidth <= n.clientWidth + 1 && n.scrollHeight <= n.clientHeight + 1),
            px: Math.min(...names.map(n => parseFloat(getComputedStyle(n).fontSize)))};
  });
  const hit = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;
  const overlaps = [];
  markers.forEach((a, i) => markers.forEach((b, j) => { if (i < j && hit(a.box, b.box)) overlaps.push([a.pos, b.pos]); }));
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
        # Phones open on the list; the field is one tap away.
        show_field(page)
        # Shown at once, not after the next background refresh.
        expect(page.locator(f'{CARD} .cb-plan-field')).to_be_visible(timeout=1_500)
        return page

    yield _open
    for context in contexts:
        context.close()


def show_field(page):
    """The Field switch exists on phones only; wider screens show the field."""
    switch = page.locator(f'{CARD} [data-plan-view-btn="field"]')
    if switch.is_visible():
        switch.click()
        expect(switch).to_have_attribute('aria-pressed', 'true')


def show_list(page):
    switch = page.locator(f'{CARD} [data-plan-view-btn="list"]')
    if switch.is_visible():
        switch.click()
        expect(switch).to_have_attribute('aria-pressed', 'true')


def _names(page):
    """The planned name at each field position, in full (the marker itself
    shows a short form; its label and data carry the whole name)."""
    names = {pos: page.locator(f'{CARD} [data-plan-position="{pos}"]').get_attribute('data-plan-planned')
             for pos in INNING_1}
    for pos, name in names.items():
        label = page.locator(f'{CARD} [data-plan-position="{pos}"]').get_attribute('aria-label')
        assert f'plan: {name}' in label, (pos, label)
    return names


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
    expect(card.locator('.cb-plan-readonly')).to_have_text('Reference only')
    expect(card.locator('[data-plan-inning="2"]')).to_have_attribute('aria-pressed', 'true')
    expect(card.locator('.cb-plan-inning-title')).to_contain_text('2nd')
    expect(card.locator('.cb-plan-inning-title')).to_contain_text('Next inning')
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
    keys = buttons.evaluate_all('els => els.map(el => el.dataset.planInning)')
    # A button for every scheduled inning; the three planned ones say so.
    assert keys == [str(n) for n in range(1, len(keys) + 1)] and len(keys) >= 3, keys
    assert card.locator('[data-plan-inning][data-plan-has="true"]').evaluate_all(
        'els => els.map(el => el.dataset.planInning)') == ['1', '2', '3']
    expect(card.locator('[data-plan-inning="1"]')).to_contain_text('Now')

    _show(page, 3)
    assert _names(page) == INNING_3
    _show(page, 1)
    assert _names(page) == INNING_1
    expect(card.locator('.cb-plan-inning-title')).to_contain_text('On now')

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

    # Inning 2: the pitcher and first baseman swapped in the plan. That is
    # the plan against its own inning before, said in words; the markers'
    # "changed" is the game against the plan, and this game follows it.
    expect(card.locator('.cb-plan-changes')).to_have_text('Plan change from Inning 1: P, 1B')
    assert _changed(page) == []
    label = card.locator('[data-plan-position="P"]').get_attribute('aria-label')
    assert INNING_2['P'] in label and 'changed' not in label.lower(), label

    _show(page, 3)
    expect(card.locator('.cb-plan-changes')).to_have_text('Plan change from Inning 2: 2B, SS')
    assert _changed(page) == []

    _show(page, 1)
    assert _changed(page) == []
    expect(card.locator('.cb-plan-changes')).to_have_text('First inning of the plan')
    assert page.cb_errors == []


@DEVICES
def test_bench_lists_who_sits_that_inning(open_plan, device):
    page = open_plan(device)
    show_list(page)                                  # the bench is a row of the list
    bench = page.locator(f'{CARD} .cb-plan-bench')
    expect(bench).to_be_visible()
    text = bench.inner_text()
    for name in INNING_2.values():
        assert name not in text, name
    assert 'Bench' in text
    assert page.cb_errors == []


@DEVICES
def test_looking_at_the_plan_changes_nothing(open_plan, device):
    page = open_plan(device)
    for inning in (1, 3, 2):
        _show(page, inning)
    # The view switches and the filter only change what is shown.
    show_list(page)
    page.locator(f'{CARD} [data-plan-only]').click()
    page.locator(f'{CARD} [data-plan-only]').click()
    show_field(page)
    page.wait_for_timeout(600)
    assert page.cb_writes == []
    assert page.cb_errors == []


@pytest.mark.parametrize('device', [PHONE, SMALL_PHONE, TINY_PHONE], ids=lambda d: d[0])
def test_long_names_stay_whole_on_a_phone(open_plan, device):
    """Names never break inside a word ("Hollingsw-orth") or get cut short."""
    page = open_plan(device)
    field = page.locator(f'{CARD} .cb-plan-field')
    for inning in (2, 3):
        _show(page, inning)
        data = field.evaluate(MEASURE)
        assert data['outside'] == [] and data['overlaps'] == [], (inning, data)
        assert all(m['fits'] and m['px'] >= 10 for m in data['markers']), (inning, data['markers'])
        split = field.locator('.cb-plan-spot-plan, .cb-plan-spot-game').evaluate_all("""els => els.filter(el => {
          const range = document.createRange(); range.selectNodeContents(el);
          const lines = new Set([...range.getClientRects()].filter(r => r.width > 1).map(r => Math.round(r.top))).size;
          return lines > el.innerText.trim().split(/\\s+/).length;
        }).map(el => el.innerText)""")
        assert split == [], (inning, split)
    assert page.cb_errors == []
