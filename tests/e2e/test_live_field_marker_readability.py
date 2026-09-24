"""Live-field markers are readable at a glance without breaking the field.

The markers on On the Field and Next Inning carried "#22 Alexander
Montgomery" in a 61-66px box at 8.8px, with the position at 7.8px on the
grass above it. Long names broke mid-word into four or five lines, and on a
phone the shortstop's tower reached down over the pitcher.

The marker now puts position and jersey on the grass line ("SS #22") and
gives the name box only the name, so the name can be larger and still take
fewer lines. The full name always shows -- it wraps, it is never ellipsized
-- and the whole label stays on the button for screen readers.

Each check uses a realistic roster: a short (Luke), medium (Graham) and long
(Alexander Montgomery at shortstop, next to the pitcher) name, and a long
surname in centre field near the top of the field.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from live_field_markers import (  # noqa: E402
    LINEUP, MEASURE, create_named_live_game, login, open_view, remove_named_live_game,
)


PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
TABLET = ('tablet', {'width': 1024, 'height': 768}, {'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})

#: The smallest readable sizes each layout holds with the roster above, and
#: the drag target each layout already had before this change.
TARGETS = {
    'phone': {'name': 10, 'pos': 9.5, 'min_width': 61, 'min_height': 30},
    'tablet': {'name': 12, 'pos': 10, 'min_width': 56, 'min_height': 44},
    'desktop': {'name': 12, 'pos': 10, 'min_width': 56, 'min_height': 44},
}


@pytest.fixture(scope='module')
def game(browser, coachboard_url):
    context = browser.new_context()
    cdn_assets.install(context)
    page = context.new_page()
    login(page, coachboard_url)
    game_id, player_ids = create_named_live_game(page, coachboard_url)
    yield game_id
    remove_named_live_game(page, coachboard_url, game_id, player_ids)
    context.close()


@pytest.fixture
def open_page(browser, coachboard_url):
    contexts = []

    def _open(device):
        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        login(page, coachboard_url)
        return page

    yield _open
    for context in contexts:
        context.close()


def _measure(page, coachboard_url, game_id, view):
    field = open_view(page, coachboard_url, game_id, view)
    data = page.evaluate(MEASURE, field)
    assert data and len(data['markers']) == 9, data
    return field, data, {m['position']: m for m in data['markers']}


# --- fit and readability -----------------------------------------------------------

@pytest.mark.parametrize('view', ['now', 'next'], ids=['on-the-field', 'next-inning'])
@pytest.mark.parametrize('device', [PHONE, TABLET, DESKTOP], ids=lambda d: d[0])
def test_markers_are_readable_and_fit_the_field(open_page, coachboard_url, game, device, view):
    page = open_page(device)
    target = TARGETS[device[0]]
    _, data, markers = _measure(page, coachboard_url, game, view)
    # The short phone On the Field leaves the pitcher's jersey to the live
    # header directly above the field.
    pitcher_in_header = device is PHONE and view == 'now'
    if pitcher_in_header:
        name, jersey = LINEUP['P']
        expect(page.locator('#cbDugoutHeader [data-cb-pitcher]')).to_have_text(f'#{jersey} {name}')

    assert data['outside'] == [], ('markers outside the field', data['outside'])
    assert data['overlaps'] == [], ('a marker covers another marker\'s text', data['overlaps'])

    for pos, m in markers.items():
        name, jersey = LINEUP[pos]
        # Name first in the hierarchy, and big enough to read at a glance.
        assert m['namePx'] >= target['name'], (pos, m['namePx'])
        assert m['posPx'] >= target['pos'], (pos, m['posPx'])
        assert m['namePx'] >= m['posPx'], (pos, m['namePx'], m['posPx'])
        # The whole name, wrapped rather than cut off.
        assert m['label'] == name, (pos, m['label'])
        assert m['nameWraps'] and m['nameFits'], (pos, m)
        # Position and jersey stay visible, and the full label stays on the button.
        if pitcher_in_header and pos == 'P':
            assert m['posLabel'] == 'P', m['posLabel']
        else:
            assert m['posLabel'] == f'{pos} #{jersey}', (pos, m['posLabel'])
        assert name in m['accessibleName'] and f'#{jersey}' in m['accessibleName'], (pos, m['accessibleName'])
        # The drag/tap target is no smaller than it was.
        assert m['box']['width'] >= target['min_width'], (pos, m['box'])
        assert m['box']['height'] >= target['min_height'], (pos, m['box'])

    # The long name at shortstop no longer builds a four-line tower.
    assert markers['SS']['nameLines'] <= 3, markers['SS']
    assert page.cb_errors == []


def test_desktop_markers_are_not_oversized(open_page, coachboard_url, game):
    page = open_page(DESKTOP)
    _, _, markers = _measure(page, coachboard_url, game, 'now')
    assert max(m['namePx'] for m in markers.values()) <= 12.5
    assert max(m['box']['width'] for m in markers.values()) <= 112


# --- drag -----------------------------------------------------------------------------

def _drag(page, source, target, measure_ghost=False):
    s, t = source.bounding_box(), target.bounding_box()
    page.mouse.move(s['x'] + s['width'] / 2, s['y'] + s['height'] / 2)
    page.mouse.down()
    page.mouse.move((s['x'] + t['x']) / 2 + t['width'] / 2, (s['y'] + t['y']) / 2 + t['height'] / 2, steps=8)
    ghost = None
    if measure_ghost:
        ghost = page.evaluate("""() => { const g = document.querySelector('.cb-drag-ghost'); if (!g) return null;
          const r = g.getBoundingClientRect(); return {px: parseFloat(getComputedStyle(g).fontSize), text: g.innerText.trim(),
          inside: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight}; }""")
    page.mouse.move(t['x'] + t['width'] / 2, t['y'] + t['height'] / 2, steps=8)
    page.mouse.up()
    return ghost


def _alignment(page, coachboard_url, game_id):
    return page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()['current_alignment']


def _names(board, attr):
    return {pos: board.locator(f'[{attr}="{pos}"] .cb-qd-name').inner_text().strip() for pos in LINEUP}


@pytest.mark.parametrize('device', [PHONE, TABLET], ids=lambda d: d[0])
def test_on_the_field_drag_still_swaps_players(open_page, coachboard_url, game, device):
    page = open_page(device)
    field = open_view(page, coachboard_url, game, 'now')
    quick = page.locator('#cbQuickDefense')
    spot = lambda pos: quick.locator(f'[data-cb-position="{pos}"]')

    for a, b in (('SS', '2B'), ('LF', 'CF')):          # an infielder, then an outfielder
        before = _names(quick, 'data-cb-position')
        name_a, name_b = before[a], before[b]
        try:
            ghost = _drag(page, spot(a), spot(b), measure_ghost=True)
            # The ghost carries the player, readable while it follows the pointer.
            assert ghost and ghost['px'] >= 11 and ghost['inside'] and ghost['text'] == name_a, ghost
            expect(spot(b).locator('.cb-qd-name')).to_have_text(name_a, timeout=10_000)
            expect(spot(a).locator('.cb-qd-name')).to_have_text(name_b, timeout=10_000)
            expect(quick.locator('.cb-save-state')).to_contain_text('Saved', timeout=10_000)
            alignment = _alignment(page, coachboard_url, game)
            assert (alignment[a], alignment[b]) == (name_b, name_a)
            data = page.evaluate(MEASURE, field)
            assert data['outside'] == [] and data['overlaps'] == [], (data['outside'], data['overlaps'])
        finally:
            page.wait_for_timeout(750)
            if spot(a).locator('.cb-qd-name').inner_text().strip() != name_a:
                _drag(page, spot(a), spot(b))
                expect(spot(a).locator('.cb-qd-name')).to_have_text(name_a, timeout=10_000)
                expect(quick.locator('.cb-save-state')).to_contain_text('Saved', timeout=10_000)
                page.wait_for_timeout(750)
    assert page.cb_errors == []


@pytest.mark.parametrize('device', [PHONE, TABLET], ids=lambda d: d[0])
def test_next_inning_drag_still_swaps_players(open_page, coachboard_url, game, device):
    page = open_page(device)
    field = open_view(page, coachboard_url, game, 'next')
    board = page.locator('#live-board-prep-v3')
    spot = lambda pos: board.locator(f'[data-next-position="{pos}"]')
    a, b = '3B', 'SS'
    before = _names(board, 'data-next-position')
    name_a, name_b = before[a], before[b]
    try:
        _drag(page, spot(a), spot(b))
        expect(spot(b).locator('.cb-qd-name')).to_have_text(name_a, timeout=10_000)
        expect(spot(a).locator('.cb-qd-name')).to_have_text(name_b, timeout=10_000)
        data = page.evaluate(MEASURE, field)
        assert data['outside'] == [] and data['overlaps'] == [], (data['outside'], data['overlaps'])
    finally:
        page.wait_for_timeout(750)
        if spot(a).locator('.cb-qd-name').inner_text().strip() != name_a:
            _drag(page, spot(a), spot(b))
            expect(spot(a).locator('.cb-qd-name')).to_have_text(name_a, timeout=10_000)
    assert page.cb_errors == []
