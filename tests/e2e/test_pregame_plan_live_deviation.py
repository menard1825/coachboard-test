"""Pregame Plan shows where the game has gone its own way from the plan.

"Plan change from Inning 1: ..." is a change inside the original plan. Next to
the plan, a second column shows the defense the game is really using for that
inning, under a plain heading:

* "On the field now" -- the inning being played;
* "Next inning" -- what End Inning would put out (the carried-forward field
  or the coach's own Next Inning edit);
* "How the 1st ended" -- an inning already played.

Rows where the two differ are marked; a row is "Changed" when the plan named
someone and a different player is there. It compares alignments, so it states
what is, never a story of how it happened ("came in", "moved", "switched").

The field shows both names on each marker (the plan's in violet), there is one
bench row, and the plan stays read-only. End Inning stays available on this
tab like on the others.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from live_field_markers import LINEUP, create_named_live_game, login, remove_named_live_game  # noqa: E402
from test_pregame_plan_field_view import MEASURE, show_field, show_list  # noqa: E402


PHONE = ('phone', {'width': 390, 'height': 844}, {'is_mobile': True, 'has_touch': True})
DESKTOP = ('desktop', {'width': 1440, 'height': 900}, {})
DEVICES = pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])
CARD = '#live-board-pregame-plan'
ORDER = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF']

INNING_1 = {pos: name for pos, (name, _) in LINEUP.items()}
INNING_2 = {**INNING_1, 'P': INNING_1['1B'], '1B': INNING_1['P']}
INNING_3 = {**INNING_2, 'SS': INNING_2['2B'], '2B': INNING_2['SS']}
PLAN = {'1': INNING_1, '2': INNING_2, '3': INNING_3}
RELIEVER = 'Pitcher Pat'            # on the bench in this plan


@pytest.fixture
def live(browser, coachboard_url):
    made = []

    def _open(device):
        setup = browser.new_context()
        cdn_assets.install(setup)
        api = setup.new_page()
        login(api, coachboard_url)
        game_id, player_ids = create_named_live_game(api, coachboard_url, innings=PLAN)
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


def _state(page, base_url):
    return page.cb_api.request.get(f'{base_url}/api/live-game/{page.cb_game}/state').json()


def _sequence(state):
    return max([int(e.get('sequence') or 0) for e in state.get('rotation_events') or [] if not e.get('reverted')] or [0])


def _change_pitcher(page, base_url, name):
    state = _state(page, base_url)
    player_id = next(p['id'] for p in page.cb_api.request.get(f'{base_url}/api/roster').json() if p['name'] == name)
    alignment = {**{pos: v for pos, v in state['current_alignment'].items() if v}, 'P': name}
    response = page.cb_api.request.post(f'{base_url}/api/live-game/{page.cb_game}/complete-pitcher-change', data={
        'base_sequence': _sequence(state), 'fast': True, 'new_pitcher_id': int(player_id), 'alignment': alignment})
    assert response.ok, response.text()[:300]


def _swap(page, base_url, a, b):
    state = _state(page, base_url)
    current = {pos: v for pos, v in state['current_alignment'].items() if v}
    alignment = {**current, a: current[b], b: current[a]}
    response = page.cb_api.request.post(f'{base_url}/api/live-game/{page.cb_game}/defense-edit', data={
        'base_sequence': _sequence(state), 'alignment': alignment})
    assert response.ok, response.text()[:300]


def _open_plan(page, base_url, inning):
    page.goto(f'{base_url}/game/{page.cb_game}')
    page.locator('#cbQuickDefense').wait_for(state='visible', timeout=20_000)
    page.locator('#cb-now-next-switch [data-now-next="plan"]').click()
    button = page.locator(f'{CARD} [data-plan-inning="{inning}"]')
    button.click()
    expect(button).to_have_attribute('aria-pressed', 'true')
    return page.locator(CARD)


NARRATIVE = ('came in', 'moved', 'switched', 'swapped')


def _comparison(card):
    """The game column's heading and every row that differs from the plan, as
    (position, planned, in the game) -- checked for plain, factual wording."""
    listing = card.locator('.cb-plan-list')
    heading = listing.locator('.cb-plan-colhead .cb-plan-game').text_content().strip()
    rows = listing.locator('[data-plan-row][data-plan-live-differs="true"]').evaluate_all(
        'els => els.map(el => [el.dataset.planRow, el.dataset.planPlanned, el.dataset.planActual])')
    text = listing.text_content()
    assert not any(verb in text for verb in NARRATIVE), text
    return heading, [tuple(row) for row in rows]


def _differing_rows(card):
    return card.locator('.cb-plan-list [data-plan-row][data-plan-live-differs="true"]')


def _advance(page, base_url):
    prep = page.cb_api.request.get(f'{base_url}/api/live-game/{page.cb_game}/next-inning-prep').json()
    response = page.cb_api.request.post(f'{base_url}/api/live-game/{page.cb_game}/advance-inning', data={
        'alignment': prep['confirmed']['alignment'], 'next_prep_id': prep['confirmed']['id'],
        'base_sequence': _sequence(_state(page, base_url))})
    assert response.ok, response.text()[:300]


def _differs(card):
    marked = card.locator('[data-plan-position][data-plan-live-differs="true"]').evaluate_all(
        'els => els.map(el => el.dataset.planPosition)')
    return sorted(marked, key=ORDER.index)


@DEVICES
def test_mid_inning_pitcher_change_shows_on_the_inning_being_played(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    card = _open_plan(page, coachboard_url, 1)

    expect(_differing_rows(card)).to_have_count(1, timeout=10_000)
    assert _comparison(card) == ('On the field now', [('P', INNING_1['P'], RELIEVER)])
    assert _differs(card) == ['P']
    # The plan column, and the field's plan line, still show what was planned.
    for pos, name in INNING_1.items():
        expect(card.locator(f'[data-plan-row="{pos}"]')).to_have_attribute('data-plan-planned', name)
        expect(card.locator(f'[data-plan-position="{pos}"]')).to_have_attribute('data-plan-planned', name)
    expect(card.locator('[data-plan-row="P"] .cb-plan-planned')).to_contain_text(INNING_1['P'])
    expect(card.locator('[data-plan-row="P"] .cb-plan-game')).to_contain_text(RELIEVER)
    expect(card.locator('[data-plan-row="P"] .cb-plan-game')).to_contain_text('Changed')
    # One bench row: the plan's bench, and who sits now -- the starter, out
    # of the game, sits; the reliever does not.
    show_list(page)
    expect(card.locator('.cb-plan-bench')).to_have_count(1)
    game_bench = card.locator('.cb-plan-bench .cb-plan-game').inner_text()
    assert INNING_1['P'] in game_bench and RELIEVER not in game_bench, game_bench
    assert RELIEVER in card.locator('[data-plan-position="P"]').get_attribute('aria-label')
    expect(card.locator('[data-plan-inning="1"]')).to_have_attribute('data-plan-live-differs', 'true')
    # A changed row is highlighted, quietly: amber, nothing red about it.
    changed_bg = card.locator('[data-plan-row="P"]').evaluate('el => getComputedStyle(el).backgroundColor')
    plain_bg = card.locator('[data-plan-row="C"]').evaluate('el => getComputedStyle(el).backgroundColor')
    assert changed_bg != plain_bg, (changed_bg, plain_bg)
    r, g, b = (int(v) for v in changed_bg[changed_bg.index('(') + 1:changed_bg.index(')')].split(',')[:3])
    assert not (r > g + 60 and r > b + 60), changed_bg
    # The plan's names never share the game's color.
    plan_color = card.locator('[data-plan-row="P"] .cb-plan-planned .cb-plan-nm').evaluate('el => getComputedStyle(el).color')
    game_color = card.locator('[data-plan-row="P"] .cb-plan-game .cb-plan-nm').evaluate('el => getComputedStyle(el).color')
    assert plan_color != game_color, (plan_color, game_color)
    # On the field, a changed marker looks different from an unchanged one.
    show_field(page)
    look = 'el => { const s = getComputedStyle(el); return [s.borderColor, s.borderWidth]; }'
    assert card.locator('[data-plan-position="P"]').evaluate(look) != card.locator('[data-plan-position="C"]').evaluate(look)
    texts = card.locator('[data-plan-position="P"] .cb-plan-spot-plan, [data-plan-position="P"] .cb-plan-spot-game').all_inner_texts()
    assert texts == [_short(INNING_1['P']), _short(RELIEVER)], texts
    assert page.cb_errors == []


def _short(name):
    first, *rest = name.split()
    return f'{first} {rest[-1][0]}.' if rest else first


@DEVICES
def test_several_live_changes_are_all_listed(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    _swap(page, coachboard_url, 'LF', 'RF')
    card = _open_plan(page, coachboard_url, 1)
    expect(_differing_rows(card)).to_have_count(3, timeout=10_000)
    assert _comparison(card) == ('On the field now', [
        ('P', INNING_1['P'], RELIEVER),
        ('LF', INNING_1['LF'], INNING_1['RF']),
        ('RF', INNING_1['RF'], INNING_1['LF']),
    ])
    assert _differs(card) == ['P', 'LF', 'RF']
    assert page.cb_errors == []


@DEVICES
def test_no_message_while_the_game_follows_the_plan(live, coachboard_url, device):
    page = live(device)
    card = _open_plan(page, coachboard_url, 1)
    page.wait_for_timeout(1_500)
    expect(_differing_rows(card)).to_have_count(0)
    expect(card.locator('.cb-plan-chip[data-kind="match"]')).to_have_text('Matches the plan')
    assert _differs(card) == []
    card.locator('[data-plan-inning="2"]').click()                 # next inning follows its plan too
    page.wait_for_timeout(500)
    expect(_differing_rows(card)).to_have_count(0)
    expect(card.locator('.cb-plan-chip[data-kind="match"]')).to_have_text('Matches the plan')
    expect(card.locator('.cb-plan-changes')).to_have_text('Plan change from Inning 1: P, 1B')
    assert page.cb_errors == []


@DEVICES
def test_next_inning_compares_what_end_inning_would_put_out(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    card = _open_plan(page, coachboard_url, 2)
    # The live field carries forward, so End Inning would not put out the plan.
    prep = page.cb_api.request.get(f'{coachboard_url}/api/live-game/{page.cb_game}/next-inning-prep').json()
    carried = prep['confirmed']['alignment']
    assert carried['P'] == RELIEVER
    expected = [pos for pos in ORDER if (INNING_2.get(pos) or '') != (carried.get(pos) or '')]
    assert expected == ['P', '1B']
    expect(_differing_rows(card)).to_have_count(2, timeout=10_000)
    assert _comparison(card) == ('Next inning', [
        ('P', INNING_2['P'], RELIEVER),
        ('1B', INNING_2['1B'], carried['1B']),
    ])
    assert _differs(card) == expected
    assert page.cb_errors == []


@DEVICES
def test_a_manual_next_inning_edit_is_compared_with_the_plan(live, coachboard_url, device):
    page = live(device)
    edited = {**INNING_2, 'LF': INNING_2['RF'], 'RF': INNING_2['LF']}
    response = page.cb_api.request.post(f'{coachboard_url}/api/live-game/{page.cb_game}/next-inning-prep',
                                        data={'mode': 'custom', 'alignment': edited})
    assert response.ok, response.text()[:200]
    card = _open_plan(page, coachboard_url, 2)
    expect(_differing_rows(card)).to_have_count(2, timeout=10_000)
    assert _comparison(card) == ('Next inning', [
        ('LF', INNING_2['LF'], INNING_2['RF']),
        ('RF', INNING_2['RF'], INNING_2['LF']),
    ])
    assert _differs(card) == ['LF', 'RF']
    # Inning 1 is still being played exactly as planned.
    card.locator('[data-plan-inning="1"]').click()
    expect(_differing_rows(card)).to_have_count(0)
    expect(card.locator('.cb-plan-chip[data-kind="match"]')).to_have_text('Matches the plan')
    assert page.cb_errors == []


@DEVICES
def test_a_finished_inning_shows_how_it_finished(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    _advance(page, coachboard_url)                     # the relief pitcher carries into the 2nd
    card = _open_plan(page, coachboard_url, 1)
    expect(_differing_rows(card)).to_have_count(1, timeout=10_000)
    assert _comparison(card) == ('How the 1st ended', [('P', INNING_1['P'], RELIEVER)])

    card.locator('[data-plan-inning="2"]').click()     # now being played
    expect(card.locator('.cb-plan-colhead .cb-plan-game')).to_have_text('On the field now')
    heading, rows = _comparison(card)
    assert heading == 'On the field now'
    assert ('P', INNING_2['P'], RELIEVER) in rows
    assert page.cb_errors == []


@DEVICES
def test_end_inning_stays_available_on_the_pregame_plan(live, coachboard_url, device):
    page = live(device)
    _open_plan(page, coachboard_url, 2)
    end_inning = page.locator('#liveEndInningBtn')
    expect(end_inning).to_be_visible()
    expect(end_inning).to_contain_text('End 1st → Start 2nd')
    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    expect(end_inning).to_be_visible()
    assert page.cb_errors == []


def test_long_names_fit_on_a_small_phone(live, coachboard_url):
    page = live(('small-phone', {'width': 360, 'height': 740}, {'is_mobile': True, 'has_touch': True}))
    state = _state(page, coachboard_url)
    current = {pos: name for pos, name in state['current_alignment'].items() if name}
    long_name = 'Benjamin Hollingsworth'
    player_id = next(p['id'] for p in page.cb_api.request.get(f'{coachboard_url}/api/roster').json()
                     if p['name'] == long_name)
    response = page.cb_api.request.post(
        f'{coachboard_url}/api/live-game/{page.cb_game}/complete-pitcher-change',
        data={'base_sequence': _sequence(state), 'fast': True, 'new_pitcher_id': int(player_id),
              'alignment': {**current, 'P': long_name, 'CF': current['P']}})
    assert response.ok, response.text()[:200]
    _swap(page, coachboard_url, 'SS', '2B')
    for inning in (1, 2):
        card = _open_plan(page, coachboard_url, inning)
        expect(_differing_rows(card)).to_have_count(5 if inning == 2 else 4, timeout=10_000)
        listing = card.locator('.cb-plan-list')
        assert listing.evaluate('el => el.scrollWidth <= el.clientWidth + 1'), inning
        assert listing.bounding_box()['x'] + listing.bounding_box()['width'] <= card.bounding_box()['x'] + card.bounding_box()['width'] + 1
        show_field(page)
        data = card.locator('.cb-plan-field').evaluate(MEASURE)
        assert data['outside'] == [] and data['overlaps'] == [], (inning, data)
        assert all(m['fits'] for m in data['markers']), (inning, data['markers'])
    assert page.cb_errors == []


@DEVICES
def test_the_plan_stays_read_only(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    card = _open_plan(page, coachboard_url, 1)
    expect(_differing_rows(card).first).to_be_visible(timeout=10_000)
    for inning in (2, 3, 1):
        card.locator(f'[data-plan-inning="{inning}"]').click()
    show_field(page)
    card.locator('[data-plan-position="P"]').click()
    page.wait_for_timeout(800)
    # Every button only chooses what to look at, or opens the Next Inning tab.
    assert card.locator('button').count() == card.locator(
        'button[data-plan-inning], button[data-plan-view-btn], button[data-plan-only], button[data-plan-edit-next]').count()
    assert page.cb_writes == []
    assert _state(page, coachboard_url)['current_alignment']['P'] == RELIEVER
    assert page.cb_errors == []
