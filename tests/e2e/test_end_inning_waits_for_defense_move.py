"""End Inning waits for a defensive move that is still saving.

A coach makes a live defensive move and taps End Inning while it still
says Saving…. End Inning takes the tap, waits for that move to settle --
through Quick Field's one move writer, CBQuickFieldMoves.whenIdle -- and
only then checks the field, opens Fix, or advances:

* the move saved: End Inning carries on by itself, against the saved field;
* the move failed or was refused: End Inning stops. Nothing is checked,
  no Fix picker opens for the move that did not happen, the inning does
  not advance, and the move's own status (Not saved — Retry, or why it
  was refused) stays on screen.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect  # noqa: E402

from test_live_change_pitcher_decision import (  # noqa: E402,F401 (live_field is a fixture)
    BASE,
    RELIEVER,
    filled,
    live_field,
    live_state,
    wait_for_field,
)
from test_live_move_single_writer import (  # noqa: E402,F401 (field is a fixture)
    BADGE,
    OPEN_SS,
    RETRY,
    SHEET,
    STALE,
    field,
    move,
    tap,
)


END = '#liveEndInningBtn'
GAP = '#cbRecordedInningGapModal'
NEXT_GAP = '#cbIncompleteNextModal'
DEFENSE_EDIT = re.compile(r'.*/defense-edit$')
OPEN_SS_LF = {pos: name for pos, name in BASE.items() if pos not in ('SS', 'LF')}
SWAPPED = dict(BASE, LF=BASE['RF'], RF='Left Lee')


def advances(page: Page):
    posts = []
    page.on(
        'request',
        lambda request: posts.append(request.post_data_json)
        if request.method == 'POST' and request.url.endswith('/advance-inning') else None,
    )
    return posts


def record_sheets(page: Page):
    """Every modal shown from here on, by id."""
    page.evaluate("""() => {
        window.__cbShown = [];
        document.addEventListener('show.bs.modal', event => window.__cbShown.push(event.target.id));
    }""")


def shown(page: Page):
    return page.evaluate('() => window.__cbShown')


def hold_move(page: Page):
    """Hold the next defensive save in the air; the test decides its fate."""
    held = []
    page.route(DEFENSE_EDIT, lambda route: held.append(route))
    return held


def wait_until_held(page: Page, held):
    for _ in range(50):
        if held:
            return held[0]
        page.wait_for_timeout(100)
    raise AssertionError('the defensive save never started')


def settle(page: Page, route, outcome):
    if outcome == 'saved':
        route.continue_()
    elif outcome == 'network':
        route.abort('internetdisconnected')
    else:
        route.fulfill(status=409, content_type='application/json', json={
            'status': 'error', 'code': 'stale_live_state', 'message': 'stale',
        })
    page.unroute(DEFENSE_EDIT)


def inning(page: Page, url, game_id):
    return str(live_state(page, url, game_id)['current_inning'])


def wait_for_inning(page: Page, url, game_id, expected, timeout_ms=15_000):
    waited = 0
    while waited < timeout_ms and inning(page, url, game_id) != expected:
        page.wait_for_timeout(200)
        waited += 200
    assert inning(page, url, game_id) == expected


def tap_end_inning_while_saving(page: Page, posts):
    """End Inning is taken, then waits: nothing checked, opened or sent."""
    record_sheets(page)
    page.locator(END).click()
    expect(page.locator(END)).to_be_disabled()
    expect(page.locator(END)).to_have_attribute('aria-busy', 'true')
    page.wait_for_timeout(700)
    expect(page.locator(BADGE)).to_contain_text('Saving')
    assert posts == []
    assert shown(page) == []


# ------------------------------------------------- the move is saved


@pytest.mark.parametrize('gesture', ['tap', 'drag'])
def test_end_inning_waits_for_the_move_then_carries_on(page: Page, coachboard_url, field, gesture):
    game_id, _ = field()
    posts = advances(page)
    held = hold_move(page)

    move(page, gesture, 'Left Lee', 'RF')
    route = wait_until_held(page, held)
    tap_end_inning_while_saving(page, posts)
    assert inning(page, coachboard_url, game_id) == '1'

    settle(page, route, 'saved')

    wait_for_inning(page, coachboard_url, game_id, '2')         # no second tap
    assert len(posts) == 1
    assert filled(posts[0]['alignment']) == SWAPPED             # the saved field
    assert shown(page) == []
    expect(page.locator(END)).not_to_have_attribute('aria-busy', 'true')


def test_a_move_that_fills_the_open_spot_leaves_nothing_to_fix(page: Page, coachboard_url, field):
    """SS is open; the coach is putting a bench player there when End
    Inning is tapped. Once that save lands SS is not open, so End Inning
    asks nothing about it."""
    game_id, _ = field(OPEN_SS)
    posts = advances(page)
    held = hold_move(page)

    tap(page, RELIEVER, 'SS')
    route = wait_until_held(page, held)
    tap_end_inning_while_saving(page, posts)

    settle(page, route, 'saved')

    wait_for_inning(page, coachboard_url, game_id, '2')
    assert len(posts) == 1
    assert filled(posts[0]['alignment']) == dict(OPEN_SS, SS=RELIEVER)
    assert GAP.lstrip('#') not in shown(page)
    assert NEXT_GAP.lstrip('#') not in shown(page)
    expect(page.locator(SHEET)).not_to_be_visible()


def test_a_spot_still_open_after_the_move_is_the_one_fixed(page: Page, coachboard_url, field):
    """SS and LF are open; the move in the air fills SS. End Inning then
    asks about LF -- the field as saved -- and Fix opens LF's picker."""
    game_id, _ = field(OPEN_SS_LF)
    posts = advances(page)
    held = hold_move(page)

    tap(page, RELIEVER, 'SS')
    route = wait_until_held(page, held)
    tap_end_inning_while_saving(page, posts)

    settle(page, route, 'saved')

    gap = page.locator(GAP)
    expect(gap).to_be_visible(timeout=10_000)
    expect(gap.locator('.modal-title')).to_contain_text('Left field')
    expect(gap.locator('.modal-title')).not_to_contain_text('hortstop')
    assert inning(page, coachboard_url, game_id) == '1' and posts == []

    # Fix, after the move settled, works as always.
    gap.get_by_role('button', name='Fix 1st Defense').click()
    sheet = page.locator(SHEET)
    expect(sheet.locator('.modal-title')).to_have_text('Fill LF', timeout=10_000)
    sheet.locator('[data-cb-fill-open-player]', has=page.get_by_text(re.compile(r'^(#\S+ )?Shortstop Shawn$'))).click()
    wait_for_field(page, coachboard_url, game_id, dict(OPEN_SS_LF, SS=RELIEVER, LF='Shortstop Shawn'))
    expect(page.locator(BADGE)).to_contain_text('Saved ✓', timeout=10_000)

    page.locator(END).click()
    wait_for_inning(page, coachboard_url, game_id, '2')
    assert len(posts) == 1


# --------------------------------------------- the move is not saved


@pytest.mark.parametrize('gesture', ['tap', 'drag'])
@pytest.mark.parametrize('outcome', ['network', 'stale'])
def test_end_inning_stops_when_the_move_is_not_saved(page: Page, coachboard_url, field, gesture, outcome):
    """The move was filling SS. It fails or is refused: End Inning does not
    advance, and does not open a Fix picker for SS -- the move that did
    not happen. The move's own status stays."""
    game_id, _ = field(OPEN_SS)
    posts = advances(page)
    held = hold_move(page)

    move(page, gesture, RELIEVER, 'SS')
    route = wait_until_held(page, held)
    tap_end_inning_while_saving(page, posts)

    settle(page, route, outcome)

    expected_status = 'Not saved — Retry' if outcome == 'network' else STALE
    expect(page.locator(BADGE)).to_contain_text(expected_status, timeout=10_000)
    expect(page.locator(END)).to_be_enabled(timeout=10_000)        # the coach decides next
    page.wait_for_timeout(1_000)
    assert posts == []
    assert shown(page) == []
    assert inning(page, coachboard_url, game_id) == '1'
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == OPEN_SS
    expect(page.locator(BADGE)).to_contain_text(expected_status)    # still says why


def test_retry_then_end_inning_works_normally(page: Page, coachboard_url, field):
    game_id, _ = field()
    posts = advances(page)
    page.route(DEFENSE_EDIT, lambda route: route.abort('internetdisconnected'))
    tap(page, 'Left Lee', 'RF')
    expect(page.locator(BADGE)).to_have_text('Not saved — Retry', timeout=10_000)
    page.unroute(DEFENSE_EDIT)

    page.locator(RETRY).click()
    wait_for_field(page, coachboard_url, game_id, SWAPPED)
    expect(page.locator(BADGE)).to_contain_text('Saved ✓', timeout=10_000)

    page.locator(END).click()
    wait_for_inning(page, coachboard_url, game_id, '2')
    assert len(posts) == 1 and filled(posts[0]['alignment']) == SWAPPED


# ------------------------------------------------------ one End Inning


def test_repeated_taps_make_one_end_inning(page: Page, coachboard_url, field):
    game_id, _ = field()
    posts = advances(page)
    held = hold_move(page)

    tap(page, 'Left Lee', 'RF')
    route = wait_until_held(page, held)
    page.locator(END).click()
    expect(page.locator(END)).to_be_disabled()
    # Tapped again and again -- even if something re-enabled the button.
    page.evaluate("""() => {
        const button = document.getElementById('liveEndInningBtn');
        for (let i = 0; i < 3; i += 1) { button.disabled = false; button.click(); }
    }""")
    page.wait_for_timeout(400)
    assert posts == []

    settle(page, route, 'saved')
    wait_for_inning(page, coachboard_url, game_id, '2')
    page.wait_for_timeout(1_500)
    assert len(posts) == 1
    assert inning(page, coachboard_url, game_id) == '2'


def test_end_inning_with_no_move_saving_is_unchanged(page: Page, coachboard_url, field):
    game_id, _ = field()
    record_sheets(page)
    posts = advances(page)

    page.locator(END).click()

    wait_for_inning(page, coachboard_url, game_id, '2')
    assert len(posts) == 1 and filled(posts[0]['alignment']) == BASE
    assert shown(page) == []
    assert page.evaluate("() => document.getElementById('liveEndInningBtn')?.getAttribute('aria-busy')") is None


def test_end_inning_with_an_open_spot_still_asks_about_it(page: Page, coachboard_url, field):
    """No move saving and SS genuinely open: the question and Fix are as
    before."""
    game_id, _ = field(OPEN_SS)
    posts = advances(page)

    page.locator(END).click()
    gap = page.locator(GAP)
    expect(gap).to_be_visible(timeout=10_000)
    expect(gap.locator('.modal-title')).to_contain_text('hortstop')
    gap.get_by_role('button', name='Fix 1st Defense').click()
    expect(page.locator(SHEET).locator('.modal-title')).to_have_text('Fill SS', timeout=10_000)
    assert posts == [] and inning(page, coachboard_url, game_id) == '1'
