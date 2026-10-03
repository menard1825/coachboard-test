"""Next Inning without repeated questions or a jumping board.

End Inning (live_game_contract.js):

* "Start 2nd with CF Open" is remembered for exactly the inning and
  defense started, like "Continue to 3rd": when that inning ends with the
  same defense, "Center field is empty at the end of the 2nd" is not asked.
  A different defense, or a different set of open spots, asks again.
* Short-handed -- every player here is already on the field, so the open
  spot cannot be filled -- starts the inning without asking. A player on
  the bench means the spot could be filled, so it asks: "2nd inning defense
  has CF open", with "Finish 2nd Inning Defense" and "Start 2nd with CF
  Open" as two real choices. An open P
  is never accepted.

The Next Inning board (live_game_board_prep_v2.js): tapping a player changes
one header line ("Moving #6 Shortstop Shawn — tap a spot or Bench") and the
highlights; the field does not move. The Bench is a destination; tapping
the moving player again cancels.
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect

from test_next_inning_save_queue import (  # noqa: F401 (next_board is a fixture)
    CARD,
    IMMEDIATE_MS,
    board_alignment,
    filled,
    live_state,
    next_board,
    record_prep_posts,
    server_next,
    spot,
    wait_for_server,
)
from test_saved_defense_pitcher import setup  # noqa: F401 (fixture)
from test_set_defense_simplified import _open_game, make_page  # noqa: F401 (fixture)


FULL = {'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam',
        '3B': 'Third Theo', 'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey',
        'RF': 'Right Riley'}
NO_CF = {pos: n for pos, n in FULL.items() if pos != 'CF'}
START = '#startLiveGameBtnAction'
RECORDED = '#cbRecordedInningGapModal'
INCOMPLETE = '#cbIncompleteNextModal'


# --- End Inning ----------------------------------------------------------------------------------

def _mark_out(page: Page, url: str, game_id: int, names):
    """Out at first pitch, before Start Game (locked once live)."""
    roster = page.request.get(f'{url}/api/roster').json()
    ids = [str(p['id']) for p in roster if p['name'] in names]
    assert len(ids) == len(names), roster
    response = page.request.post(
        f'{url}/game/{game_id}/update_absences',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        data='&'.join(f'absent_players={i}' for i in ids),
        max_redirects=0,
    )
    assert response.status in {200, 302, 303}, response.text()[:300]


def _start(setup, url, plan, out=()):
    """Start Game in the browser, the way a coach does ("Start with CF Open"
    when the 1st has CF open)."""
    page, plan_game, _, _ = setup
    game_id = plan_game(plan)
    if out:
        _mark_out(page, url, game_id, out)
    _open_game(page, url, game_id)
    expect(page.locator(START)).to_be_enabled(timeout=15_000)
    page.locator(START).click()
    if not plan['1'].get('CF'):
        page.locator('#cbStartGameModal').get_by_role('button', name='Start with CF Open', exact=True).click()
    page.wait_for_function(
        f"async () => (await (await fetch('/api/live-game/{game_id}/state')).json()).game.is_live",
        timeout=15_000,
    )
    if not plan['1'].get('CF'):
        # Start writes its "Start with CF Open" acknowledgement once its
        # request returns, which can be after the server already says live.
        page.wait_for_function(
            f"() => (sessionStorage.getItem('coachboard:record-acks:v1:{game_id}') || '[]') !== '[]'",
            timeout=15_000,
        )
    page.reload(wait_until='domcontentloaded')
    expect(page.locator('#liveEndInningBtn')).to_be_visible(timeout=15_000)
    return page, game_id


def _watch_questions(page: Page):
    """Every End Inning question shown on this page, in order."""
    page.evaluate("""() => {
      window.__cbAsked = [];
      document.addEventListener('shown.bs.modal', event => {
        window.__cbAsked.push(event.target.id);
      });
    }""")


def _asked(page: Page):
    return page.evaluate('() => window.__cbAsked')


def _inning(page: Page, url, game_id):
    return str(live_state(page, url, game_id)['current_inning'])


def _end_inning_to(page: Page, inning: str):
    page.locator('#liveEndInningBtn').click()
    expect(page.locator('#live-inning-display')).to_have_text(inning, timeout=20_000)
    page.wait_for_timeout(800)            # the next inning's board settles


def _sequence(state):
    return max([int(e.get('sequence') or 0) for e in state.get('rotation_events', [])
                if not e.get('reverted')] or [0])


def _set_field(page: Page, url, game_id, alignment):
    state = live_state(page, url, game_id)
    response = page.request.post(
        f'{url}/api/live-game/{game_id}/defense-edit',
        data={'alignment': alignment, 'base_sequence': _sequence(state)},
    )
    assert response.ok, response.text()[:300]


def _expect_two_real_choices(modal, finish, start):
    """Both answers look and act like actions: neither is disabled or faded."""
    # Fixing is the prominent action; starting with the gap is deliberate.
    for name, style in ((finish, 'btn-primary'), (start, 'btn-outline-primary')):
        button = modal.get_by_role('button', name=name, exact=True)
        expect(button).to_be_visible()
        expect(button).to_be_enabled()
        expect(button).to_have_class(re.compile(rf'\b{style}\b'))
        looks = button.evaluate("""el => {
          const s = getComputedStyle(el);
          return {opacity: s.opacity, pointer: s.pointerEvents, disabled: el.matches(':disabled, .disabled')};
        }""")
        assert looks == {'opacity': '1', 'pointer': 'auto', 'disabled': False}, (name, looks)
    expect(modal.get_by_role('button', name='Start Inning Anyway')).to_have_count(0)


def _expect_coach_words(modal):
    """Coach words only: no record keeping, no app name."""
    text = modal.inner_text()
    for word in ('record', 'open position', 'Keep as Recorded', 'CoachBoard'):
        assert word.lower() not in text.lower(), (word, text)


def _start_the_2nd_anyway(setup, url):
    """1st full; the 2nd planned with CF open (Center Casey and the relievers
    on the bench, so End Inning asks); the 3rd planned full."""
    page, game_id = _start(setup, url, {'1': FULL, '2': NO_CF, '3': FULL})
    _watch_questions(page)
    page.locator('#liveEndInningBtn').click()
    incomplete = page.locator(INCOMPLETE)
    expect(incomplete.locator('.modal-title')).to_have_text('2nd inning defense has CF open', timeout=15_000)
    expect(incomplete).to_contain_text('CF is open, and players are available on the bench.')
    _expect_two_real_choices(incomplete, 'Finish 2nd Inning Defense', 'Start 2nd with CF Open')
    incomplete.get_by_role('button', name='Start 2nd with CF Open').click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    assert filled(live_state(page, url, game_id)['current_alignment']) == NO_CF
    page.wait_for_timeout(800)
    return page, game_id


def test_starting_the_2nd_with_cf_open_is_not_asked_again_when_it_ends(setup, coachboard_url):
    page, game_id = _start_the_2nd_anyway(setup, coachboard_url)
    assert server_next(page, coachboard_url, game_id) == FULL

    _end_inning_to(page, '3')
    assert _asked(page) == ['cbIncompleteNextModal']        # never the 2nd's record
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == FULL


def test_the_acknowledgement_survives_a_reload(setup, coachboard_url):
    page, game_id = _start_the_2nd_anyway(setup, coachboard_url)
    page.reload(wait_until='domcontentloaded')
    expect(page.locator('#liveEndInningBtn')).to_be_visible(timeout=15_000)
    _watch_questions(page)
    _end_inning_to(page, '3')
    assert _asked(page) == []


def test_a_changed_defense_with_the_same_open_spot_asks_again(setup, coachboard_url):
    page, game_id = _start_the_2nd_anyway(setup, coachboard_url)
    _set_field(page, coachboard_url, game_id, dict(NO_CF, SS='Second Sam', **{'2B': 'Shortstop Shawn'}))

    page.locator('#liveEndInningBtn').click()
    recorded = page.locator(RECORDED)
    expect(recorded.locator('.modal-title')).to_have_text(
        'Center field is empty at the end of the 2nd', timeout=15_000
    )
    expect(recorded.locator('.modal-body')).to_have_text(
        "Nobody was in CF when the 2nd ended. Go back and fix the 2nd if that's wrong, or continue to the 3rd and leave the 2nd as saved."
    )
    _expect_coach_words(recorded)
    # Fix is the solid navy action; Continue a navy outline, clearly available.
    expect(recorded.get_by_role('button', name='Fix 2nd Defense', exact=True)).to_have_class(
        re.compile(r'\bbtn-primary\b'))
    go_on = recorded.get_by_role('button', name='Continue to 3rd', exact=True)
    expect(go_on).to_be_enabled()
    expect(go_on).to_have_class(re.compile(r'\bbtn-outline-primary\b'))
    assert go_on.evaluate('el => getComputedStyle(el).opacity') == '1'
    recorded.get_by_role('button', name='Fix 2nd Defense', exact=True).click()
    expect(recorded).to_be_hidden()
    assert _inning(page, coachboard_url, game_id) == '2'


def test_a_different_open_set_asks_again(setup, coachboard_url):
    page, game_id = _start_the_2nd_anyway(setup, coachboard_url)
    _set_field(page, coachboard_url, game_id, {p: n for p, n in NO_CF.items() if p != 'LF'})

    page.locator('#liveEndInningBtn').click()
    recorded = page.locator(RECORDED)
    expect(recorded).to_contain_text(
        'Nobody was in LF or CF when the 2nd ended.', timeout=15_000
    )
    expect(recorded.locator('.modal-title')).to_have_text(
        'Left field and center field are empty at the end of the 2nd'
    )
    recorded.get_by_role('button', name='Fix 2nd Defense').click()
    assert _inning(page, coachboard_url, game_id) == '2'


def test_three_empty_spots_read_naturally_and_continue_goes_on(setup, coachboard_url):
    page, game_id = _start_the_2nd_anyway(setup, coachboard_url)
    third = {p: n for p, n in NO_CF.items() if p not in ('LF', 'RF')}
    _set_field(page, coachboard_url, game_id, third)

    page.locator('#liveEndInningBtn').click()
    recorded = page.locator(RECORDED)
    expect(recorded.locator('.modal-title')).to_have_text(
        'Left field, center field, and right field are empty at the end of the 2nd', timeout=15_000
    )
    expect(recorded.locator('.modal-body')).to_have_text(
        "Nobody was in LF, CF, or RF when the 2nd ended. Go back and fix the 2nd if that's wrong, or continue to the 3rd and leave the 2nd as saved."
    )
    _expect_coach_words(recorded)

    # Continue keeps the 2nd as saved. The 3rd is planned full, but the
    # changed field was carried forward instead, so End Inning asks before
    # that plan is skipped; keeping the field leaves the same spots open.
    recorded.get_by_role('button', name='Continue to 3rd', exact=True).click()
    skipped = page.locator('#cbSkippedPlanModal')
    expect(skipped.locator('.modal-title')).to_have_text('Use the 3rd-inning plan?', timeout=15_000)
    skipped.get_by_role('button', name='Keep this defense', exact=True).click()
    incomplete = page.locator(INCOMPLETE)
    expect(incomplete.locator('.modal-title')).to_have_text(
        '3rd inning defense has open positions', timeout=15_000
    )
    assert str(live_state(page, coachboard_url, game_id)['current_inning']) == '2'
    incomplete.get_by_role('button', name='Start 3rd with LF, CF, and RF Open', exact=True).click()
    expect(page.locator('#live-inning-display')).to_have_text('3', timeout=20_000)
    events = sorted(live_state(page, coachboard_url, game_id)['rotation_events'], key=lambda e: e['sequence'])
    ended = [e for e in events if e['event_type'] == 'End Inning' and not e.get('reverted')]
    assert filled(ended[-1]['before_alignment']) == third


SHORT = ('Center Casey', 'Relief Rex', 'Relief Rae')      # eight players here


def test_short_handed_with_nobody_on_the_bench_starts_without_asking(setup, coachboard_url):
    page, game_id = _start(setup, coachboard_url, {'1': NO_CF, '2': NO_CF, '3': NO_CF}, out=SHORT)
    _watch_questions(page)

    # The board still says CF is open.
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    expect(page.locator('#cbNextOpenWarning')).to_have_text('⚠ Next inning: CF is open', timeout=10_000)

    _end_inning_to(page, '2')
    _end_inning_to(page, '3')                 # nor the 2nd's record afterwards
    assert _asked(page) == []
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == NO_CF


def test_a_player_on_the_bench_still_asks(setup, coachboard_url):
    # Center Casey is here but planned on the bench: CF could be filled.
    page, game_id = _start(setup, coachboard_url, {'1': NO_CF, '2': NO_CF},
                           out=('Relief Rex', 'Relief Rae'))
    page.locator('#liveEndInningBtn').click()
    incomplete = page.locator(INCOMPLETE)
    expect(incomplete).to_contain_text('CF is open, and players are available on the bench.', timeout=15_000)
    incomplete.get_by_role('button', name='Finish 2nd Inning Defense').click()
    expect(incomplete).to_be_hidden()
    assert _inning(page, coachboard_url, game_id) == '1'


def test_several_open_spots_are_named_and_the_start_is_remembered(
    page: Page, coachboard_url, next_board
):
    """CF and RF open with both players on the bench: one question naming
    both. Starting with them open is remembered for that defense, so when
    the 2nd ends only the 3rd's plan is asked about, never the 2nd's record."""
    board, game_id = next_board
    for pos in ('CF', 'RF'):
        spot(board, pos).click()
        board.get_by_role('button', name=re.compile(r'^Bench #\d+ ')).click()
        expect(spot(board, pos)).to_have_attribute('data-next-player', '', timeout=IMMEDIATE_MS)
    plan = {p: n for p, n in FULL.items() if p not in ('CF', 'RF')}
    wait_for_server(page, coachboard_url, game_id, plan)
    _watch_questions(page)

    page.locator('#liveEndInningBtn').click()
    incomplete = page.locator(INCOMPLETE)
    expect(incomplete.locator('.modal-title')).to_have_text(
        '2nd inning defense has open positions', timeout=15_000
    )
    expect(incomplete).to_contain_text('CF and RF are open, and players are available on the bench.')
    _expect_two_real_choices(incomplete, 'Finish 2nd Inning Defense', 'Start 2nd with CF and RF Open')
    incomplete.get_by_role('button', name='Start 2nd with CF and RF Open').click()
    expect(page.locator('#live-inning-display')).to_have_text('2', timeout=20_000)
    assert filled(live_state(page, coachboard_url, game_id)['current_alignment']) == plan
    page.wait_for_timeout(800)

    # The 3rd's plan is the same open defense: asked about; the 2nd's
    # record (the defense just started on purpose) is not.
    page.locator('#liveEndInningBtn').click()
    expect(incomplete.locator('.modal-title')).to_have_text(
        '3rd inning defense has open positions', timeout=15_000
    )
    incomplete.get_by_role('button', name='Finish 3rd Inning Defense').click()
    expect(incomplete).to_be_hidden()
    assert _asked(page) == ['cbIncompleteNextModal', 'cbIncompleteNextModal']
    assert _inning(page, coachboard_url, game_id) == '2'


def test_finish_defense_returns_to_next_inning_planning(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    spot(board, 'RF').click()
    board.get_by_role('button', name='Bench #9 Right Riley', exact=True).click()
    wait_for_server(page, coachboard_url, game_id, {p: n for p, n in FULL.items() if p != 'RF'})

    # Ending from On the Field: Finish brings the coach to the 2nd's plan.
    page.locator('#cb-now-next-switch [data-now-next="now"]').click()
    expect(board).to_be_hidden()
    page.locator('#liveEndInningBtn').click()
    incomplete = page.locator(INCOMPLETE)
    expect(incomplete.locator('.modal-title')).to_have_text('2nd inning defense has RF open', timeout=15_000)
    _expect_two_real_choices(incomplete, 'Finish 2nd Inning Defense', 'Start 2nd with RF Open')
    incomplete.get_by_role('button', name='Finish 2nd Inning Defense').click()
    expect(incomplete).to_be_hidden()
    expect(board).to_be_visible(timeout=10_000)
    expect(spot(board, 'RF')).to_have_attribute('data-next-player', '')
    page.wait_for_timeout(500)
    assert _inning(page, coachboard_url, game_id) == '1'


def test_an_open_p_is_never_accepted_even_short_handed(setup, coachboard_url):
    page, game_id = _start(setup, coachboard_url, {'1': NO_CF, '2': NO_CF}, out=SHORT)
    _watch_questions(page)
    # Everyone here is on the field, but nobody is pitching the 2nd.
    current = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep').json()
    no_p = dict({p: n for p, n in NO_CF.items() if p != 'P'}, CF='Pitcher Pat')
    response = page.request.post(f'{coachboard_url}/api/live-game/{game_id}/next-inning-prep', data={
        'mode': 'custom', 'alignment': no_p,
        'base_alignment': current['confirmed']['alignment'], 'inning': str(current['next_inning']),
    })
    assert response.ok, response.text()[:300]
    page.locator('#cb-now-next-switch [data-now-next="next"]').click()
    expect(spot(page.locator(CARD), 'P')).to_have_attribute('data-next-player', '', timeout=10_000)

    page.locator('#liveEndInningBtn').click()
    # One message -- the board's own line -- and focus on the P spot
    # (test_end_inning_needs_pitcher.py); no question is asked.
    expect(spot(page.locator(CARD), 'P')).to_be_focused(timeout=15_000)
    expect(page.locator(f'{CARD} #cb-next-needs-pitcher')).to_have_text('Set a pitcher for the next inning.')
    expect(page.locator(f'{CARD} .cb-next-error')).to_have_count(0)
    page.wait_for_timeout(500)
    assert _asked(page) == []
    assert _inning(page, coachboard_url, game_id) == '1'


# --- The board -----------------------------------------------------------------------------------

def _boxes(page: Page):
    return page.evaluate(f"""() => {{
      const card = document.querySelector('{CARD}');
      const top = el => el ? Math.round(el.getBoundingClientRect().top * 10) / 10 : null;
      return {{
        field: top(card.querySelector('.cb-next-field')),
        bench: top(card.querySelector('.cb-next-bench')),
        tools: top(card.querySelector('.cb-next-tools')),
        endInning: top(document.getElementById('liveEndInningBtn')),
      }};
    }}""")


def _classes(board, pos):
    return spot(board, pos).get_attribute('class') or ''


@pytest.mark.parametrize('size', [(390, 844), (768, 1024), (1024, 768)],
                         ids=lambda s: f'{s[0]}x{s[1]}')
def test_tapping_a_fielder_does_not_move_the_field(page: Page, next_board, size):
    board, _ = next_board
    page.set_viewport_size({'width': size[0], 'height': size[1]})
    page.wait_for_timeout(300)
    page.evaluate('() => window.scrollTo(0, 0)')
    before = _boxes(page)
    spot(board, 'SS').click()
    expect(board.locator('[data-next-hint]')).to_contain_text('Moving', timeout=IMMEDIATE_MS)
    assert _boxes(page) == before

    spot(board, 'SS').click()                 # and cancelling doesn't either
    expect(board.locator('[data-next-hint]')).not_to_contain_text('Moving')
    assert _boxes(page) == before


def test_the_moving_player_and_every_destination_are_marked(page: Page, next_board):
    board, _ = next_board
    spot(board, 'SS').click()

    hint = board.locator('[data-next-hint]')
    expect(hint).to_have_text('Moving #6 Shortstop Shawn — tap a spot or Bench')
    assert 'cb-next-selected' in _classes(board, 'SS')
    for pos in ('P', 'C', '1B', '2B', '3B', 'LF', 'CF', 'RF'):
        assert 'cb-next-destination' in _classes(board, pos), pos
        assert 'cb-next-selected' not in _classes(board, pos), pos
    bench = board.locator('.cb-next-bench')
    expect(bench).to_have_class(re.compile(r'\bdestination-active\b'))
    expect(bench.get_by_role('button', name='Bench #6 Shortstop Shawn', exact=True)).to_be_visible()

    text = board.inner_text()
    for gone in ('STEP 2', 'CHOOSE DESTINATION', 'TO BENCH', 'TAP HERE'):
        assert gone not in text.upper(), gone

    # The selected marker reads differently from a destination.
    selected_bg = spot(board, 'SS').locator('.cb-qd-name').evaluate('el => getComputedStyle(el).backgroundColor')
    target_bg = spot(board, '2B').locator('.cb-qd-name').evaluate('el => getComputedStyle(el).backgroundColor')
    assert selected_bg != target_bg


def test_tapping_the_moving_player_again_cancels(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    posts = record_prep_posts(page)
    before = board_alignment(page)

    spot(board, 'SS').click()
    spot(board, 'SS').click()
    hint = board.locator('[data-next-hint]')
    expect(hint).not_to_contain_text('Moving', timeout=IMMEDIATE_MS)
    expect(board.locator('.cb-next-selected')).to_have_count(0)
    expect(board.locator('.cb-next-destination')).to_have_count(0)
    expect(board.locator('.cb-next-bench.destination-active')).to_have_count(0)

    # A bench player too.
    spot(board, 'LF').click()
    board.get_by_role('button', name='Bench #7 Left Lee', exact=True).click()
    expect(spot(board, 'LF')).to_have_attribute('data-next-player', '', timeout=IMMEDIATE_MS)
    wait_for_server(page, coachboard_url, game_id, {p: n for p, n in before.items() if p != 'LF'})
    sent = len(posts)
    chip = board.locator('[data-next-bench-player="Left Lee"]')
    chip.click()
    expect(hint).to_have_text('Moving #7 Left Lee — tap a spot')
    expect(chip).to_have_class(re.compile(r'\bselected\b'))
    chip.click()
    expect(hint).not_to_contain_text('Moving', timeout=IMMEDIATE_MS)
    expect(board.locator('.cb-next-bench-player.selected')).to_have_count(0)
    page.wait_for_timeout(600)
    assert len(posts) == sent                 # cancelling saved nothing


def test_the_bench_is_a_destination(page: Page, coachboard_url, next_board):
    board, game_id = next_board
    want = dict(board_alignment(page))

    # Tap a fielder, then the explicit "Bench #6 Shortstop Shawn".
    spot(board, 'SS').click()
    board.get_by_role('button', name='Bench #6 Shortstop Shawn', exact=True).click()
    want.pop('SS')
    expect(spot(board, 'SS')).to_have_attribute('data-next-player', '', timeout=IMMEDIATE_MS)
    expect(board.locator('[data-next-bench-player="Shortstop Shawn"]')).to_be_visible()
    expect(board.locator('[data-next-hint]')).not_to_contain_text('Moving')

    # The Bench's empty space is the same destination.
    spot(board, 'LF').click()
    box = board.locator('.cb-next-bench').bounding_box()
    page.mouse.click(box['x'] + box['width'] - 6, box['y'] + box['height'] - 6)
    want.pop('LF')
    expect(spot(board, 'LF')).to_have_attribute('data-next-player', '', timeout=IMMEDIATE_MS)

    # Keyboard: the Bench target is a real button.
    spot(board, 'RF').click()
    board.get_by_role('button', name='Bench #9 Right Riley', exact=True).focus()
    page.keyboard.press('Enter')
    want.pop('RF')
    expect(spot(board, 'RF')).to_have_attribute('data-next-player', '', timeout=IMMEDIATE_MS)
    wait_for_server(page, coachboard_url, game_id, want)
    assert board_alignment(page) == want


def test_a_bench_chip_selects_its_own_player_and_benches_nobody(page: Page, coachboard_url, next_board):
    """Moving Shortstop Shawn, the coach taps Left Lee's bench chip: Shawn is
    not benched. The selection switches to Lee; nothing changes or saves."""
    board, game_id = next_board
    spot(board, 'LF').click()
    board.get_by_role('button', name='Bench #7 Left Lee', exact=True).click()
    want = {p: n for p, n in board_alignment(page).items()}
    wait_for_server(page, coachboard_url, game_id, want)
    posts = record_prep_posts(page)

    spot(board, 'SS').click()
    lee = board.locator('[data-next-bench-player="Left Lee"]')
    lee.click()

    hint = board.locator('[data-next-hint]')
    expect(hint).to_have_text('Moving #7 Left Lee — tap a spot', timeout=IMMEDIATE_MS)
    expect(lee).to_have_class(re.compile(r'\bselected\b'))
    expect(spot(board, 'SS')).to_have_attribute('data-next-player', 'Shortstop Shawn')
    assert 'cb-next-selected' not in _classes(board, 'SS')
    expect(board.locator('.cb-next-bench.destination-active')).to_have_count(0)
    expect(board.locator('[data-next-bench-selected]')).to_have_count(0)
    page.wait_for_timeout(600)
    assert board_alignment(page) == want
    assert posts == []                        # no baseball change, nothing saved

    # From there it is an ordinary bench-player move: Lee to the open LF.
    spot(board, 'LF').click()
    expect(spot(board, 'LF')).to_have_attribute('data-next-player', 'Left Lee', timeout=IMMEDIATE_MS)
    wait_for_server(page, coachboard_url, game_id, dict(want, LF='Left Lee'))
