"""The live Pregame Card never looks like the defense that is out there.

The tab is the card: "Pregame Card · 2nd", "Reference · not what goes out",
a CARD stamp on the field, and no End Inning while it is open. Where the game
has gone its own way, the marker shows both -- "Plan: Ames" and "Now: Pat"
(or "Next:", or "Finished:") -- so a coach never reads a planned name as
the player on the field. The card's bench is "Card bench"; the live or next
bench is shown beside it when it differs. Until CoachBoard knows what End
Inning would send, the card says it is checking instead of looking like a
match.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

from test_pregame_plan_live_deviation import (  # noqa: E402,F401
    CARD, DESKTOP, INNING_1, INNING_2, PHONE, RELIEVER, _advance, _change_pitcher, _open_plan, _swap, live,
)
from test_pregame_plan_field_view import MEASURE  # noqa: E402


DEVICES = pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])


def short(name):
    """Two-line markers use surnames; the note keeps full names."""
    return name.split()[-1]


SMALL_PHONE = ('small-phone', {'width': 360, 'height': 740}, {'is_mobile': True, 'has_touch': True})


def _marker(card, pos):
    spot = card.locator(f'[data-plan-position="{pos}"]')
    return spot.locator('.cb-plan-card-name'), spot.locator('.cb-plan-effective')


def _plain_markers(card, alignment, skip=()):
    """Positions that match show just the card's name -- nothing more."""
    for pos, name in alignment.items():
        if pos in skip:
            continue
        spot = card.locator(f'[data-plan-position="{pos}"]')
        expect(spot.locator('.cb-qd-name')).to_have_text(name)
        expect(spot.locator('.cb-plan-effective')).to_have_count(0)


def _benches(card):
    return card.locator('[data-plan-bench]').evaluate_all('els => els.map(el => el.dataset.planBench)')


@DEVICES
def test_the_card_reads_as_a_card(live, coachboard_url, device):
    page = live(device)
    card = _open_plan(page, coachboard_url, 2)
    expect(card.locator('.cb-plan-title')).to_have_text('Pregame Card · 2nd')
    expect(card.locator('.cb-plan-sub')).to_have_text('Reference · not what goes out')
    expect(card.locator('.cb-plan-field .cb-plan-stamp')).to_have_text('CARD')
    expect(card.locator('.cb-plan-inning-title')).to_contain_text('On deck')
    assert 'next inning' not in card.inner_text().lower()
    expect(card.locator('.cb-plan-matches')).to_have_text('End Inning would send the card as written.', timeout=10_000)
    assert _benches(card) == ['Card bench']
    assert page.cb_errors == []


@DEVICES
def test_inning_being_played_shows_plan_and_now_on_the_marker(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    card = _open_plan(page, coachboard_url, 1)
    planned, effective = _marker(card, 'P')
    expect(effective).to_have_text(f'Now: {short(RELIEVER)}', timeout=10_000)
    expect(planned).to_have_text(f'Plan: {short(INNING_1["P"])}')
    _plain_markers(card, INNING_1, skip=('P',))

    # Card bench keeps the plan; the live bench is who really sits now.
    assert _benches(card) == ['Card bench', 'Live bench']
    card_bench = card.locator('[data-plan-bench="Card bench"]').inner_text()
    live_bench = card.locator('[data-plan-bench="Live bench"]').inner_text()
    assert RELIEVER in card_bench and INNING_1['P'] not in card_bench
    assert INNING_1['P'] in live_bench and RELIEVER not in live_bench
    assert page.cb_errors == []


@DEVICES
def test_next_inning_shows_plan_and_next_on_the_marker(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    card = _open_plan(page, coachboard_url, 2)
    planned, effective = _marker(card, 'P')
    expect(effective).to_have_text(f'Next: {short(RELIEVER)}', timeout=10_000)
    expect(planned).to_have_text(f'Plan: {short(INNING_2["P"])}')
    expect(card.locator('.cb-plan-live strong')).to_have_text('Heading into the 2nd')
    assert _benches(card) == ['Card bench', 'Next bench']
    assert 'next inning' not in card.inner_text().lower()
    assert page.cb_errors == []


@DEVICES
def test_finished_inning_shows_plan_and_finished(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    _advance(page, coachboard_url)
    card = _open_plan(page, coachboard_url, 1)
    planned, effective = _marker(card, 'P')
    expect(effective).to_have_text(f'Finished: {short(RELIEVER)}', timeout=10_000)
    expect(planned).to_have_text(f'Plan: {short(INNING_1["P"])}')
    expect(card.locator('.cb-plan-inning-title')).to_contain_text('Finished')
    assert _benches(card) == ['Card bench']            # the bench then is not known reliably
    assert page.cb_errors == []


@DEVICES
def test_end_inning_is_hidden_on_the_card_and_back_elsewhere(live, coachboard_url, device):
    page = live(device)
    end_inning = page.locator('#liveEndInningBtn')
    _open_plan(page, coachboard_url, 2)
    expect(end_inning).to_be_hidden()
    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    expect(end_inning).to_be_visible()
    page.locator('#cb-now-next-switch [data-now-next="plan"]').click()
    expect(end_inning).to_be_hidden()
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    expect(end_inning).to_be_visible()
    expect(end_inning).to_contain_text('End 1st → Start 2nd')
    assert page.cb_errors == []


def _hold_next_inning_reads(page):
    held, state = [], {'hold': False}

    def handle(route):
        if state['hold'] and route.request.method == 'GET':
            held.append(route)
        else:
            route.continue_()

    page.route('**/next-inning-prep', handle)
    return held, state


def _release(held):
    while held:
        held.pop(0).continue_()


@DEVICES
def test_unknown_next_inning_never_looks_like_a_match(live, coachboard_url, device):
    page = live(device)
    held, state = _hold_next_inning_reads(page)

    # Before anything has loaded: a loading card, not a blank or a guess.
    state['hold'] = True
    page.goto(f'{coachboard_url}/game/{page.cb_game}')
    page.locator('#cb-now-next-switch [data-now-next="plan"]').click(timeout=20_000)
    expect(page.locator(f'{CARD} .cb-plan-checking')).to_have_text('Loading the pregame card…')
    expect(page.locator(f'{CARD} [data-plan-position]')).to_have_count(0)
    state['hold'] = False
    _release(held)
    card = page.locator(CARD)
    expect(card.locator('.cb-plan-matches')).to_have_text('End Inning would send the card as written.', timeout=10_000)

    # A live change: until the next-inning data is read again, it is checking.
    state['hold'] = True
    _change_pitcher(page, coachboard_url, RELIEVER)
    expect(card.locator('.cb-plan-checking')).to_have_text('Checking what End Inning would send…', timeout=10_000)
    expect(card.locator('.cb-plan-matches')).to_have_count(0)
    expect(card.locator('[data-plan-live-differs="true"]')).to_have_count(0)
    state['hold'] = False
    _release(held)
    planned, effective = _marker(card, 'P')
    expect(effective).to_have_text(f'Next: {short(RELIEVER)}', timeout=10_000)
    expect(card.locator('.cb-plan-checking')).to_have_count(0)
    assert page.cb_errors == []


def test_long_names_fit_at_360px(live, coachboard_url):
    page = live(SMALL_PHONE)
    state = page.cb_api.request.get(f'{coachboard_url}/api/live-game/{page.cb_game}/state').json()
    current = {pos: name for pos, name in state['current_alignment'].items() if name}
    roster = page.cb_api.request.get(f'{coachboard_url}/api/roster').json()
    long_name = 'Benjamin Hollingsworth'
    player_id = next(p['id'] for p in roster if p['name'] == long_name)
    events = [int(e.get('sequence') or 0) for e in state.get('rotation_events') or [] if not e.get('reverted')]
    response = page.cb_api.request.post(
        f'{coachboard_url}/api/live-game/{page.cb_game}/complete-pitcher-change',
        data={'base_sequence': max(events or [0]), 'fast': True, 'new_pitcher_id': int(player_id),
              'alignment': {**current, 'P': long_name, 'CF': current['P']}})
    assert response.ok, response.text()[:200]
    _swap(page, coachboard_url, 'SS', '2B')

    for inning in (1, 2):
        card = _open_plan(page, coachboard_url, inning)
        expect(card.locator('.cb-plan-effective').first).to_be_visible(timeout=10_000)
        data = card.locator('.cb-plan-field').evaluate(MEASURE)
        assert data['outside'] == [] and data['overlaps'] == [], (inning, data)
        assert all(m['fits'] for m in data['markers']), (inning, data['markers'])
    assert page.cb_errors == []


@DEVICES
def test_the_card_stays_read_only(live, coachboard_url, device):
    page = live(device)
    _change_pitcher(page, coachboard_url, RELIEVER)
    card = _open_plan(page, coachboard_url, 1)
    expect(card.locator('.cb-plan-effective').first).to_be_visible(timeout=10_000)
    for inning in (2, 3, 1):
        card.locator(f'[data-plan-inning="{inning}"]').click()
    card.locator('[data-plan-position="P"]').click()
    page.wait_for_timeout(600)
    assert card.locator('button').count() == card.locator('button[data-plan-inning]').count()
    assert card.locator('input, select, textarea, [contenteditable="true"]').count() == 0
    assert page.cb_writes == []
    assert page.cb_errors == []
