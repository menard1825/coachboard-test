"""Pregame Plan notes where the game has gone its own way from the plan.

"Changed from Inning 1: ..." (amber) is a change inside the original plan.
A quiet team-colored note compares the plan for an inning with the defense
the game is really using, in plain baseball terms:

* "In-game adjustments" -- the inning being played, against the field now;
* "Heading into the 2nd" -- the next inning, against what End Inning would
  put out (the carried-forward field or the coach's own Next Inning edit);
* "How the 1st finished" -- an inning already played.

The note states what is ("Pat pitching instead of Ames"), never a story of
how it happened ("came in", "moved", "switched"): it compares alignments and
does not know the order moves were made in. The plan itself stays read-only.
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


def _note(card):
    """The note's heading and lines, checked for plain, factual wording."""
    note = card.locator('.cb-plan-live')
    expect(note).to_be_visible(timeout=10_000)
    heading = note.locator('strong').inner_text().strip()
    lines = [line.strip() for line in note.locator('li').all_inner_texts()]
    for line in lines:
        assert not any(verb in line for verb in NARRATIVE), line
    return heading, lines


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

    expect(card.locator('.cb-plan-live li')).to_have_count(1, timeout=10_000)
    assert _note(card) == ('In-game adjustments', [f'{RELIEVER} pitching instead of {INNING_1["P"]}'])
    assert _differs(card) == ['P']
    assert RELIEVER in card.locator('[data-plan-position="P"]').get_attribute('aria-label')
    # The plan itself still shows what was planned.
    expect(card.locator('[data-plan-position="P"] .cb-qd-name')).to_have_text(INNING_1['P'])
    expect(card.locator('[data-plan-inning="1"]')).to_have_attribute('data-plan-live-differs', 'true')
    # A quiet team-colored note: the same color as the position outline, and
    # nothing red about it.
    note_rule = card.locator('.cb-plan-live').evaluate('el => getComputedStyle(el).borderLeftColor')
    outline = card.locator('[data-plan-position="P"] .cb-qd-name').evaluate('el => getComputedStyle(el).outlineColor')
    assert note_rule == outline, (note_rule, outline)
    r, g, b = (int(v) for v in note_rule[note_rule.index('(') + 1:note_rule.index(')')].split(',')[:3])
    assert not (r > g + 60 and r > b + 60), note_rule
    # A live deviation looks different from a change inside the plan.
    _show = lambda n: card.locator(f'[data-plan-inning="{n}"]').click()
    look = 'el => { const s = getComputedStyle(el.querySelector(".cb-qd-name")); return [s.outlineStyle, s.outlineColor, s.boxShadow]; }'
    live_look = card.locator('[data-plan-position="P"]').evaluate(look)
    _show(3)
    planned_look = card.locator('[data-plan-position="SS"]').evaluate(look)   # changed from Inning 2, no live data
    assert live_look != planned_look, (live_look, planned_look)
    assert page.cb_errors == []


@DEVICES
def test_several_live_changes_are_all_listed(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    _swap(page, coachboard_url, 'LF', 'RF')
    card = _open_plan(page, coachboard_url, 1)
    expect(card.locator('.cb-plan-live li')).to_have_count(3, timeout=10_000)
    assert _note(card) == ('In-game adjustments', [
        f'{RELIEVER} pitching instead of {INNING_1["P"]}',
        f'{INNING_1["RF"]} in LF instead of {INNING_1["LF"]}',
        f'{INNING_1["LF"]} in RF instead of {INNING_1["RF"]}',
    ])
    assert _differs(card) == ['P', 'LF', 'RF']
    assert page.cb_errors == []


@DEVICES
def test_no_message_while_the_game_follows_the_plan(live, coachboard_url, device):
    page = live(device)
    card = _open_plan(page, coachboard_url, 1)
    page.wait_for_timeout(1_500)
    expect(card.locator('.cb-plan-live')).to_have_count(0)
    assert _differs(card) == []
    card.locator('[data-plan-inning="2"]').click()                 # next inning follows its plan too
    page.wait_for_timeout(500)
    expect(card.locator('.cb-plan-live')).to_have_count(0)
    expect(card.locator('.cb-plan-changes')).to_have_text('Changed from Inning 1: P, 1B')
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
    expect(card.locator('.cb-plan-live li')).to_have_count(2, timeout=10_000)
    # Both players are already in those spots now, so they "stay".
    assert _note(card) == ('Heading into the 2nd', [
        f'{RELIEVER} stays on the mound (plan: {INNING_2["P"]})',
        f'{carried["1B"]} stays at 1B (plan: {INNING_2["1B"]})',
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
    expect(card.locator('.cb-plan-live li')).to_have_count(2, timeout=10_000)
    # Neither player is in that spot now, so no "stays".
    assert _note(card) == ('Heading into the 2nd', [
        f'{INNING_2["RF"]} in LF (plan: {INNING_2["LF"]})',
        f'{INNING_2["LF"]} in RF (plan: {INNING_2["RF"]})',
    ])
    assert _differs(card) == ['LF', 'RF']
    # Inning 1 is still being played exactly as planned.
    card.locator('[data-plan-inning="1"]').click()
    expect(card.locator('.cb-plan-live')).to_have_count(0)
    assert page.cb_errors == []


@DEVICES
def test_a_finished_inning_shows_how_it_finished(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    _advance(page, coachboard_url)                     # the relief pitcher carries into the 2nd
    card = _open_plan(page, coachboard_url, 1)
    expect(card.locator('.cb-plan-live li')).to_have_count(1, timeout=10_000)
    assert _note(card) == ('How the 1st finished', [f'{RELIEVER} pitching instead of {INNING_1["P"]}'])

    card.locator('[data-plan-inning="2"]').click()     # now being played
    heading, lines = _note(card)
    assert heading == 'In-game adjustments'
    assert f'{RELIEVER} pitching instead of {INNING_2["P"]}' in lines
    assert page.cb_errors == []


@DEVICES
def test_the_plan_stays_read_only(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    card = _open_plan(page, coachboard_url, 1)
    expect(card.locator('.cb-plan-live')).to_be_visible(timeout=10_000)
    for inning in (2, 3, 1):
        card.locator(f'[data-plan-inning="{inning}"]').click()
    card.locator('[data-plan-position="P"]').click()
    page.wait_for_timeout(800)
    assert card.locator('button').count() == card.locator('button[data-plan-inning]').count()
    assert page.cb_writes == []
    assert _state(page, coachboard_url)['current_alignment']['P'] == RELIEVER
    assert page.cb_errors == []
