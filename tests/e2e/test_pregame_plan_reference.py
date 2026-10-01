"""Pregame Plan as a between-innings reference: plan against the game.

What a coach reads on this tab, and the data each piece must come from:

* "Matches the plan" only when every position matches, empty ones included;
  a partial plan says how many positions it names, marks the rest "Not in
  plan", and lists no bench of its own ("Bench not specified").
* An empty position the game knows about is "Empty"; a played inning with no
  saved record is "No record" -- never an empty-position warning.
* "Only changes" is unavailable when there is nothing to compare.
* The next inning is this board's own Next Inning defense, edits not yet
  saved included; a compact preview says "Same defense as the 1st" or lists
  what changes, and "Edit next inning" opens the Next Inning tab.
* One inning button per scheduled inning of the game.
* Phones: the list first, the field a tap away; iPad: both together.
"""

import json
import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from live_field_markers import LINEUP, create_named_live_game, login, remove_named_live_game  # noqa: E402
from test_pregame_plan_field_view import show_field, show_list  # noqa: E402


PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
DEVICES = pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])
CARD = '#live-board-pregame-plan'
NEXT_CARD = '#live-board-prep-v3'

INNING_1 = {pos: name for pos, (name, _) in LINEUP.items()}
INNING_2 = {**INNING_1, 'P': INNING_1['1B'], '1B': INNING_1['P']}
# The 3rd is planned only in part: who plays first and third.
INNING_3 = {'1B': INNING_1['1B'], '3B': INNING_1['3B']}
PLAN = {'1': INNING_1, '2': INNING_2, '3': INNING_3}


@pytest.fixture
def live(browser, coachboard_url):
    made = []

    def _open(device, plan=None):
        setup = browser.new_context()
        cdn_assets.install(setup)
        api = setup.new_page()
        login(api, coachboard_url)
        game_id, player_ids = create_named_live_game(api, coachboard_url, innings=plan or PLAN)
        made.append((setup, api, game_id, player_ids))

        cdn_assets.require_vendored_assets()
        _, viewport, extra = device
        context = browser.new_context(viewport=viewport, **extra)
        cdn_assets.install(context)
        made[-1] += (context,)
        page = context.new_page()
        errors, writes = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: writes.append(request.url)
                if request.method != 'GET' and '/api/live-game/' in request.url else None)
        page.cb_errors, page.cb_writes = errors, writes
        login(page, coachboard_url)
        page.cb_api, page.cb_game = api, game_id
        return page

    yield _open
    for setup, api, game_id, player_ids, *contexts in made:
        for context in contexts:
            context.close()
        remove_named_live_game(api, coachboard_url, game_id, player_ids)
        setup.close()


def _api(page, base_url, path):
    return f'{base_url}/api/live-game/{page.cb_game}/{path}'


def _state(page, base_url):
    return page.cb_api.request.get(_api(page, base_url, 'state')).json()


def _sequence(state):
    return max([int(e.get('sequence') or 0) for e in state.get('rotation_events') or [] if not e.get('reverted')] or [0])


def _field_edit(page, base_url, **changes):
    """A live defensive change: position -> player ('' leaves it open)."""
    state = _state(page, base_url)
    alignment = {pos: name for pos, name in state['current_alignment'].items() if name}
    for pos, name in changes.items():
        if name:
            alignment[pos] = name
        else:
            alignment.pop(pos, None)
    response = page.cb_api.request.post(_api(page, base_url, 'defense-edit'), data={
        'base_sequence': _sequence(state), 'alignment': alignment})
    assert response.ok, response.text()[:300]


def _set_next(page, base_url, alignment):
    response = page.cb_api.request.post(_api(page, base_url, 'next-inning-prep'),
                                        data={'mode': 'custom', 'alignment': alignment})
    assert response.ok, response.text()[:300]


def _advance(page, base_url):
    prep = page.cb_api.request.get(_api(page, base_url, 'next-inning-prep')).json()
    response = page.cb_api.request.post(_api(page, base_url, 'advance-inning'), data={
        'alignment': prep['confirmed']['alignment'], 'next_prep_id': prep['confirmed']['id'],
        'base_sequence': _sequence(_state(page, base_url))})
    assert response.ok, response.text()[:300]


def _open_plan(page, base_url, inning=None):
    page.goto(f'{base_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.locator('#cb-now-next-switch [data-now-next="plan"]').click()
    card = page.locator(CARD)
    expect(card).to_be_visible(timeout=10_000)
    if inning is not None:
        _show(page, inning)
    return card


def _show(page, inning):
    button = page.locator(f'{CARD} [data-plan-inning="{inning}"]')
    button.click()
    expect(button).to_have_attribute('aria-pressed', 'true')


def _chips(card):
    return card.locator('.cb-plan-chip').evaluate_all('els => els.map(el => [el.dataset.kind, el.innerText.trim()])')


def _states(card):
    return card.locator('.cb-plan-list [data-plan-row]:not([data-plan-row="bench"])').evaluate_all(
        'els => Object.fromEntries(els.map(el => [el.dataset.planRow, el.dataset.planState]))')


# Matching ----------------------------------------------------------------------------------

@DEVICES
def test_matching_needs_every_position_including_empty_ones(live, coachboard_url, device):
    page = live(device)
    card = _open_plan(page, coachboard_url, 1)
    expect(card.locator('.cb-plan-chip[data-kind="match"]')).to_have_text('Matches the plan')

    # Left field opened up: one position no longer matches, so no match.
    _field_edit(page, coachboard_url, LF='')
    expect(card.locator('[data-plan-row="LF"]')).to_have_attribute('data-plan-state', 'empty', timeout=10_000)
    expect(card.locator('.cb-plan-chip[data-kind="match"]')).to_have_count(0)
    assert ['empty', 'Empty: LF'] in _chips(card)
    expect(card.locator('[data-plan-row="LF"] .cb-plan-game')).to_have_text('Empty')
    expect(card.locator('[data-plan-row="LF"]')).to_have_attribute('data-plan-live-differs', 'true')
    # Not "Changed": the plan named someone and nobody is there.
    expect(card.locator('[data-plan-row="LF"]')).to_have_attribute('data-plan-changed', 'false')
    expect(card.locator('[data-plan-inning="1"]')).to_have_attribute('data-plan-live-differs', 'true')

    # The next inning likewise: a planned player missing is a difference.
    _show(page, 2)
    _set_next(page, coachboard_url, {**INNING_2, 'RF': ''})
    expect(card.locator('[data-plan-row="RF"]')).to_have_attribute('data-plan-state', 'empty', timeout=10_000)
    expect(card.locator('[data-plan-row="RF"]')).to_have_attribute('data-plan-live-differs', 'true')
    expect(card.locator('.cb-plan-chip[data-kind="match"]')).to_have_count(0)
    assert page.cb_errors == []


def test_a_plan_with_an_open_position_matches_the_same_open_field(live, coachboard_url):
    page = live(DESKTOP, plan={'1': INNING_1, '2': {**INNING_2, 'RF': ''}})
    _set_next(page, coachboard_url, {**INNING_2, 'RF': ''})
    card = _open_plan(page, coachboard_url, 2)
    expect(card.locator('[data-plan-row="RF"]')).to_have_attribute('data-plan-state', 'empty', timeout=10_000)
    expect(card.locator('[data-plan-row="RF"] .cb-plan-planned')).to_have_text('Not in plan')
    expect(card.locator('[data-plan-row="RF"]')).to_have_attribute('data-plan-live-differs', 'false')
    chips = _chips(card)
    assert ['match', 'Matches the plan'] in chips and ['empty', 'Empty: RF'] in chips, chips
    assert ['plan', 'Plan: 8 of 9 positions'] in chips, chips
    expect(card.locator('[data-plan-inning="2"]')).to_have_attribute('data-plan-live-differs', 'false')
    assert page.cb_errors == []


# Partial plans -----------------------------------------------------------------------------

def test_a_partial_plan_names_what_it_has_and_specifies_no_bench(live, coachboard_url):
    page = live(DESKTOP)
    card = _open_plan(page, coachboard_url, 3)                       # a later inning, planned in part
    expect(card.locator('.cb-plan-inning-title')).to_contain_text('3rd')
    chips = _chips(card)
    assert ['plan', 'Plan: 2 of 9 positions'] in chips, chips
    assert not any(kind in ('match', 'changed', 'empty') for kind, _ in chips), chips
    for pos in INNING_1:
        planned = card.locator(f'[data-plan-row="{pos}"] .cb-plan-planned')
        if pos in INNING_3:
            expect(planned).to_contain_text(INNING_3[pos])
        else:
            expect(planned).to_have_text('Not in plan')
    expect(card.locator('.cb-plan-bench .cb-plan-planned')).to_have_text('Bench not specified')
    # A later inning has no game side: nothing to compare.
    expect(card.locator('.cb-plan-list.single')).to_have_count(1)
    expect(card.locator('[data-plan-only]')).to_be_disabled()
    expect(card.locator('.cb-plan-emp')).to_have_count(0)
    # The plan against its inning before only speaks for the positions it
    # names: first base differs from the 2nd's plan; third base does not, and
    # the positions it leaves out are not called changes.
    expect(card.locator('.cb-plan-changes')).to_have_text('Plan change from Inning 2: 1B')

    # A complete plan lists who it leaves out: here players, not anyone absent.
    _show(page, 2)
    bench = card.locator('.cb-plan-bench .cb-plan-planned').inner_text()
    assert bench not in ('', 'Bench not specified'), bench
    for name in INNING_2.values():
        assert name not in bench, (name, bench)
    roster = {player['name'] for player in page.cb_api.request.get(_api(page, coachboard_url, 'next-inning-prep')).json()['roster']}
    for label in bench.split(', '):
        assert label.split(' ', 1)[1] in roster, (label, roster)
    assert page.cb_errors == []


# Missing records ---------------------------------------------------------------------------

@DEVICES
def test_a_played_inning_with_no_record_is_never_called_empty(live, coachboard_url, device):
    page = live(device)
    _advance(page, coachboard_url)

    # An older game: the 1st inning has no saved record at all.
    def drop_record(route):
        response = route.fetch()
        payload = response.json()
        payload.get('actual_rotation', {}).pop('1', None)
        route.fulfill(response=response, body=json.dumps(payload))

    page.route('**/next-inning-prep', drop_record)
    card = _open_plan(page, coachboard_url, 1)
    expect(card.locator('.cb-plan-colhead .cb-plan-planned')).to_have_text('Pregame plan')
    expect(card.locator('.cb-plan-note')).to_have_text('No record of how the 1st ended. Showing the pregame plan only.')
    assert set(_states(card).values()) == {'norec'}, _states(card)
    chips = _chips(card)
    assert ['norec', 'No record for this inning'] in chips, chips
    assert not any(kind in ('empty', 'match', 'changed') for kind, _ in chips), chips
    expect(card.locator('.cb-plan-list .cb-plan-emp')).to_have_count(0)
    expect(card.locator('[data-plan-only]')).to_be_disabled()
    expect(card.locator('[data-plan-inning="1"]')).to_have_attribute('data-plan-live-differs', 'false')
    show_field(page)
    expect(card.locator('.cb-plan-field .cb-plan-norec').first).to_have_text('No record')
    expect(card.locator('.cb-plan-field .cb-plan-emp')).to_have_count(0)

    # The same inning with its record: how it ended, compared with the plan.
    page.unroute('**/next-inning-prep')
    card = _open_plan(page, coachboard_url, 1)
    expect(card.locator('.cb-plan-colhead .cb-plan-game')).to_have_text('How the 1st ended')
    assert set(_states(card).values()) == {'name'}, _states(card)
    expect(card.locator('.cb-plan-chip[data-kind="match"]')).to_have_text('Matches the plan')
    assert page.cb_errors == []


# Only changes ------------------------------------------------------------------------------

def test_only_changes_lists_the_differences_and_needs_a_comparison(live, coachboard_url):
    page = live(PHONE)
    _field_edit(page, coachboard_url, LF=INNING_1['RF'], RF=INNING_1['LF'])
    card = _open_plan(page, coachboard_url, 1)
    only = card.locator('[data-plan-only]')
    expect(only).to_be_enabled()
    only.click()
    expect(only).to_have_attribute('aria-pressed', 'true')
    rows = card.locator('.cb-plan-list [data-plan-row]:not([data-plan-row="bench"])')
    assert rows.evaluate_all('els => els.map(el => el.dataset.planRow)') == ['LF', 'RF']
    only.click()
    expect(rows).to_have_count(9)

    # Nothing to compare: a later inning (no game side yet), or one with
    # neither a plan nor a defense yet.
    _show(page, '3')
    expect(only).to_be_disabled()
    expect(rows).to_have_count(9)
    _show(page, '5')
    expect(only).to_be_disabled()
    expect(card.locator('.cb-plan-listwrap .cb-plan-note')).to_have_text(
        'No pregame plan and no defense set yet for the 5th.')
    assert page.cb_writes == []
    assert page.cb_errors == []


# The next inning ---------------------------------------------------------------------------

@DEVICES
def test_the_next_inning_preview_follows_the_next_inning_board(live, coachboard_url, device):
    page = live(device, plan={'1': INNING_1, '2': INNING_1})
    card = _open_plan(page, coachboard_url)
    preview = card.locator('.cb-plan-next')
    expect(preview).to_have_attribute('data-plan-next', 'same')
    expect(preview).to_contain_text('Next inning · 2nd')
    expect(preview.locator('[data-plan-next-summary]')).to_have_text('Same defense as the 1st')

    # Saved elsewhere: the preview lists what changes from the field now.
    _set_next(page, coachboard_url, {**INNING_1, 'LF': INNING_1['RF'], 'RF': INNING_1['LF']})
    expect(preview).to_have_attribute('data-plan-next', 'changed', timeout=10_000)
    expect(preview.locator('[data-plan-next-summary]')).to_have_text(
        'Changes saved for the 2nd · 2 changes from the field now')
    assert preview.locator('[data-plan-next-pos]').evaluate_all(
        'els => els.map(el => el.dataset.planNextPos)') == ['LF', 'RF']
    expect(preview.locator('[data-plan-next-pos="LF"]')).to_contain_text(INNING_1['RF'])

    # "Edit next inning" opens the Next Inning tab; looking changes nothing.
    preview.locator('[data-plan-edit-next]').click()
    expect(page.locator(NEXT_CARD)).to_be_visible()
    expect(card).to_be_hidden()
    expect(page.locator('#cb-now-next-switch [data-now-next="next"]')).to_have_attribute('aria-pressed', 'true')
    assert page.cb_writes == []
    assert page.cb_errors == []


def test_an_edit_still_saving_shows_in_the_next_inning_column(live, coachboard_url):
    """The next inning is the board's own defense -- not the last saved copy."""
    page = live(PHONE)
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)

    # Hold the save, so the board has the edit and the server does not yet.
    held = []
    page.route('**/next-inning-prep', lambda route: held.append(route)
               if route.request.method == 'POST' else route.continue_())
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    board = page.locator(NEXT_CARD)
    expect(board).to_be_visible(timeout=10_000)
    board.locator('[data-next-position="RF"]').click()
    board.locator('[data-next-bench-selected]').click()
    expect(board.locator('[data-next-position="RF"]')).to_have_attribute('data-next-player', '', timeout=2_000)

    page.locator('#cb-now-next-switch [data-now-next="plan"]').click()
    card = page.locator(CARD)
    expect(card.locator('.cb-plan-colhead .cb-plan-game')).to_have_text('Next inning')
    expect(card.locator('[data-plan-row="RF"]')).to_have_attribute('data-plan-state', 'empty')
    expect(card.locator('[data-plan-row="RF"] .cb-plan-game')).to_have_text('Empty')
    expect(card.locator('.cb-plan-next [data-plan-next-pos="RF"]')).to_contain_text('Empty')
    assert held, 'the edit was not sent'
    for route in held:
        route.continue_()
    page.unroute('**/next-inning-prep')
    assert page.cb_errors == []


def test_no_preview_after_the_last_scheduled_inning(live, coachboard_url):
    page = live(DESKTOP)
    scheduled = page.cb_api.request.get(_api(page, coachboard_url, 'next-inning-prep')).json()['regulation_innings']

    def last_inning(route):
        response = route.fetch()
        payload = response.json()
        payload['current_inning'] = str(scheduled)
        payload['next_inning'] = str(scheduled + 1)
        route.fulfill(response=response, body=json.dumps(payload))

    page.route('**/next-inning-prep', last_inning)
    card = _open_plan(page, coachboard_url)
    expect(card.locator('[data-plan-inning]')).to_have_count(scheduled)
    expect(card.locator('.cb-plan-next')).to_have_attribute('data-plan-next', 'none')
    expect(card.locator('[data-plan-edit-next]')).to_have_count(0)
    page.unroute('**/next-inning-prep')
    assert page.cb_errors == []


# Layout ------------------------------------------------------------------------------------

LAYOUT = """() => {
  const card = document.getElementById('live-board-pregame-plan');
  const box = el => { if (!el || !el.getClientRects().length) return null; const r = el.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom}; };
  const list = box(card.querySelector('.cb-plan-list'));
  const field = box(card.querySelector('.cb-plan-field'));
  const names = [...card.querySelectorAll('.cb-plan-list .cb-plan-nm')].filter(el => el.getClientRects().length);
  return {
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    card: box(card), list, field,
    viewport: window.innerWidth,
    clippedNames: names.filter(el => el.scrollWidth > el.clientWidth + 1).map(el => el.innerText),
    smallestName: Math.min(...names.map(el => parseFloat(getComputedStyle(el).fontSize))),
    shortButtons: [...card.querySelectorAll('button')].filter(el => el.getClientRects().length && el.getBoundingClientRect().height < 44).map(el => el.innerText.trim()),
  };
}"""


@pytest.mark.parametrize('size', [(320, 640), (360, 740), (375, 667), (440, 956),
                                  (768, 1024), (820, 1180), (1024, 768), (1180, 820)],
                         ids=lambda s: f'{s[0]}x{s[1]}')
def test_layout_reads_at_every_size(live, coachboard_url, size):
    width, height = size
    phone = width < 744
    device = ('size', {'width': width, 'height': height},
              {'is_mobile': True, 'has_touch': True} if phone else {})
    page = live(device)
    _field_edit(page, coachboard_url, LF=INNING_1['RF'], RF=INNING_1['LF'])
    card = _open_plan(page, coachboard_url, 1)
    data = page.evaluate(LAYOUT)
    assert data['overflow'] <= 0, data
    assert data['card']['l'] >= 0 and data['card']['r'] <= width + 1, data
    assert data['clippedNames'] == [] and data['smallestName'] >= 15, data
    assert data['shortButtons'] == [], data
    if phone:
        # The list first; the field is a tap away, one view at a time.
        assert data['list'] and data['field'] is None, data
        show_field(page)
        data = page.evaluate(LAYOUT)
        assert data['field'] and data['list'] is None, data
        show_list(page)
    else:
        # Both together; side by side when there is room for both.
        assert data['list'] and data['field'], data
        expect(card.locator('[data-plan-view-btn="field"]')).to_be_hidden()
        side_by_side = data['field']['l'] >= data['list']['r'] - 1
        stacked = data['field']['t'] >= data['list']['b'] - 1
        assert side_by_side or stacked, data
        assert side_by_side, ('iPad and wider show list and field together', data)
    assert page.cb_errors == []
