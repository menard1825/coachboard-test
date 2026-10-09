"""Prepare Game, planned the way a coach plans it: no fighting the screen.

* Saved Defense: the chosen saved defense survives the panel re-rendering
  (the coach's own taps, autosave, another device's save), and one tap on Use
  applies it through the existing confirmation, pitcher kept.
* Pitching notices: with no game rules selected, the P picker says so once,
  no reason is repeated under every player, and choosing a pitcher asks
  nothing. One inline notice sits beside the Pitching Plan. A player-specific
  concern (arm care) is shown inline under the field, and Start Game still
  asks about the rules (tests/e2e/test_start_game_pitching.py).
* Status wording agrees across the screen: a lineup holding an Out player, a
  1st inning missing only its pitcher, and a chosen starting pitcher next to
  an empty optional Pitching Plan.
* An Out player still in the plan is named once with two actions, and the
  defense picker never moves an Out player into another spot.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from test_set_defense_simplified import (  # noqa: F401 (make_page is a fixture)
    DESKTOP,
    PANEL,
    PHONE,
    _filled,
    _innings,
    _open_game,
    _saved,
    make_page,
)
from test_saved_defense_pitcher import FIELDERS, setup  # noqa: F401 (fixture)
from test_pregame_player_time_summary import mark_absent

from playwright.sync_api import expect  # noqa: E402


pytestmark = pytest.mark.e2e

IPAD = ('ipad', {'width': 820, 'height': 1180}, {'has_touch': True})
W440 = ('phone-440', {'width': 440, 'height': 956}, {'is_mobile': True, 'has_touch': True})
RULES_NOTICE = "Game rules haven't been selected. You can keep planning, but confirm the rules before starting."


def _game_without_rules(page, url, game_id):
    response = page.request.post(f'{url}/api/game-day/{game_id}/pitching-rules', data={'rule_set': ''})
    assert response.ok, response.text()
    assert response.json().get('effective') is None


def _open_saved_defense_tools(page):
    toggle = page.locator(f'{PANEL} .gm-mobile-preset-toggle')
    if toggle.is_visible():
        assert _height(toggle) >= 44
        toggle.click()
    expect(page.locator('#pde-preset')).to_be_visible(timeout=10_000)


def _height(locator):
    return locator.bounding_box()['height']


def _readiness_line(page):
    return page.locator('#coach-game-readiness-v2 .cgr-head small')


# --- 1. Saved Defense ------------------------------------------------------------------

@pytest.mark.parametrize('device', [PHONE, W440, IPAD], ids=lambda d: d[0])
def test_the_chosen_saved_defense_survives_rerenders_and_one_tap_uses_it(setup, make_page, coachboard_url, device):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'1': {'P': 'Relief Rex'}})
    name, _ = saved_defense({**FIELDERS, 'SS': 'Left Lee', 'LF': 'Shortstop Shawn'})
    coach = make_page(device)
    _open_game(coach, coachboard_url, game_id)
    _open_saved_defense_tools(coach)

    coach.locator('#pde-preset').select_option(label=name)
    use = coach.locator('#pde-use')
    expect(use).to_be_enabled()
    expect(use).to_have_text('Use for Inning 1')
    for control in (coach.locator('#pde-preset'), use, coach.locator('#pde-use-game')):
        assert _height(control) >= 44

    # Another device saves the plan; the panel re-renders under the coach.
    rotation = page.request.get(f'{coachboard_url}/api/game_data/{game_id}').json()['rotation']
    saved = page.request.post(f'{coachboard_url}/save_rotation', data={
        'id': rotation['id'], 'title': rotation['title'],
        'innings': {**_innings(page, coachboard_url, game_id), '1': {'P': 'Relief Rex', 'C': 'Catcher Cole'}},
        'associated_game_id': game_id})
    assert saved.ok and saved.json().get('status') == 'success', saved.text()
    expect(coach.locator(f'{PANEL} [data-pde-pos="C"] .pde-name')).to_have_text('Catcher Cole', timeout=15_000)
    expect(coach.locator('#pde-preset')).to_have_value(re.compile(r'^\d+$'))
    expect(coach.locator('#pde-preset option:checked')).to_have_text(name)
    expect(use).to_be_enabled()

    use.click()
    sheet = coach.locator('#pde-use-confirm')
    expect(sheet).to_be_visible(timeout=10_000)
    expect(sheet).to_contain_text('Relief Rex stays at P.')
    sheet.get_by_role('button', name='Use Saved Defense', exact=True).click()
    _saved(coach)

    assert _filled(_innings(page, coachboard_url, game_id)['1']) == {
        **FIELDERS, 'SS': 'Left Lee', 'LF': 'Shortstop Shawn', 'P': 'Relief Rex'}
    assert coach.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
    assert coach.cb_errors == []


def test_the_chosen_saved_defense_survives_a_local_edit(setup, coachboard_url):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'1': {'P': 'Relief Rex'}})
    name, _ = saved_defense(dict(FIELDERS))
    _open_game(page, coachboard_url, game_id)
    page.locator('#pde-preset').select_option(label=name)

    page.locator(f'{PANEL} [data-pde-pos="C"]').click()
    page.locator('#pde-list .pde-choice[data-player="Catcher Cole"]').click()
    _saved(page)

    expect(page.locator('#pde-preset option:checked')).to_have_text(name)
    expect(page.locator('#pde-use')).to_be_enabled()


@pytest.mark.parametrize('device', [PHONE, IPAD], ids=lambda d: d[0])
def test_use_for_this_inning_is_primary_and_whole_game_confirms_what_it_replaces(setup, make_page, coachboard_url, device):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'1': {'P': 'Relief Rex'}, '2': {'P': 'Relief Rae', 'C': 'First Frank', '1B': 'Catcher Cole'}})
    name, _ = saved_defense(dict(FIELDERS))
    coach = make_page(device)
    _open_game(coach, coachboard_url, game_id)
    _open_saved_defense_tools(coach)
    coach.locator('#pde-preset').select_option(label=name)

    use, whole = coach.locator('#pde-use'), coach.locator('#pde-use-game')
    expect(use).to_have_class(re.compile(r'\bbtn-primary\b'))
    expect(whole).to_have_class(re.compile(r'\bbtn-outline-primary\b'))
    assert use.bounding_box()['width'] > whole.bounding_box()['width']

    whole.click()
    sheet = coach.locator('#pde-use-confirm')
    expect(sheet).to_be_visible(timeout=10_000)
    expect(sheet).to_contain_text('Fielders you already planned in the 2nd inning will be replaced.')
    expect(sheet).to_contain_text('Pitchers stay as planned')
    # Cancel changes nothing.
    sheet.get_by_role('button', name='Cancel', exact=True).click()
    expect(sheet).to_be_hidden(timeout=10_000)
    assert _filled(_innings(page, coachboard_url, game_id)['2']) == {'P': 'Relief Rae', 'C': 'First Frank', '1B': 'Catcher Cole'}

    whole.click()
    expect(sheet).to_be_visible(timeout=10_000)
    sheet.get_by_role('button', name='Use Saved Defense', exact=True).click()
    _saved(coach)
    innings = _innings(page, coachboard_url, game_id)
    assert _filled(innings['1']) == {**FIELDERS, 'P': 'Relief Rex'}
    assert _filled(innings['2']) == {**FIELDERS, 'P': 'Relief Rae'}


def test_whole_game_says_when_no_other_inning_is_planned(setup, coachboard_url):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'1': {'P': 'Relief Rex'}})
    name, _ = saved_defense(dict(FIELDERS))
    _open_game(page, coachboard_url, game_id)
    page.locator('#pde-preset').select_option(label=name)
    page.locator('#pde-use-game').click()
    sheet = page.locator('#pde-use-confirm')
    expect(sheet).to_contain_text('No other inning has fielders planned yet.', timeout=10_000)
    sheet.get_by_role('button', name='Cancel', exact=True).click()


# --- 3. Ready for First Pitch ------------------------------------------------------------

@pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])
def test_a_ready_first_inning_is_ready_for_first_pitch(setup, make_page, coachboard_url, device):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': {**FIELDERS, 'P': 'Relief Rex'}})  # innings 2-6 empty, no lineup
    coach = make_page(device)
    _open_game(coach, coachboard_url, game_id)

    panel = coach.locator('#coach-game-readiness-v2')
    expect(panel.locator('.cgr-head strong')).to_have_text('Ready for First Pitch', timeout=15_000)
    expect(panel.locator('.cgr-badge')).to_have_text('READY')
    if device is PHONE:
        expect(panel.locator('.cgr-head small')).to_contain_text('1st inning ready')
    else:
        expect(panel.locator('.cgr-head small')).to_have_text(
            'Optional before first pitch: batting order and full-game defense.')
        expect(panel.locator('.cgr-item', has_text='Defense')).to_contain_text(
            '1st inning ready · full-game plan 1 of 6 innings (optional)')
    expect(coach.locator('#startLiveGameBtnAction')).to_be_enabled()


def test_without_a_starting_pitcher_it_is_not_ready(setup, coachboard_url):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': dict(FIELDERS)})
    _open_game(page, coachboard_url, game_id)
    panel = page.locator('#coach-game-readiness-v2')
    expect(panel.locator('.cgr-head strong')).to_have_text('Pregame setup', timeout=15_000)
    expect(panel.locator('.cgr-badge')).to_have_text('SETUP')
    expect(page.locator('#startLiveGameBtnAction')).to_be_disabled()


# --- 2. Pitching notices --------------------------------------------------------------------

@pytest.mark.parametrize('device', [PHONE, DESKTOP], ids=lambda d: d[0])
def test_no_game_rules_is_said_once_and_choosing_a_pitcher_asks_nothing(setup, make_page, coachboard_url, device):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': dict(FIELDERS)})
    _game_without_rules(page, coachboard_url, game_id)
    coach = make_page(device)
    _open_game(coach, coachboard_url, game_id)

    notice = coach.locator('#gm-rules-notice')
    expect(notice).to_have_count(1, timeout=15_000)
    expect(notice).to_contain_text(RULES_NOTICE)
    assert _height(notice.get_by_role('button', name='Choose rules')) >= 44

    coach.locator(f'{PANEL} [data-pde-pos="P"]').click()
    picker = coach.locator('#pde-player-modal')
    expect(picker).to_be_visible(timeout=10_000)
    expect(picker.locator('.pde-rules-notice')).to_have_count(1, timeout=10_000)
    expect(picker.locator('.pde-rules-notice')).to_have_text(RULES_NOTICE)
    coach.wait_for_timeout(500)  # the eligibility lines arrive after the list
    expect(picker.locator('.pde-eligibility')).to_have_count(0)
    expect(picker).not_to_contain_text("can't confirm")

    picker.locator('.pde-choice[data-player="Relief Rae"]').click()
    expect(picker).to_be_hidden(timeout=10_000)
    _saved(coach)
    assert _filled(_innings(page, coachboard_url, game_id)['1'])['P'] == 'Relief Rae'

    # Still one notice on the page, beside the Pitching Plan.
    expect(coach.locator('#gm-rules-notice')).to_have_count(1)
    coach.locator('#gm-rules-notice').get_by_role('button', name='Choose rules').click()
    expect(coach.locator('#game-pitch-rule-editor-v2')).to_be_visible(timeout=10_000)


def test_rules_selected_hides_the_rules_notice(setup, coachboard_url):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': dict(FIELDERS)})
    _open_game(page, coachboard_url, game_id)
    page.wait_for_timeout(6_000)  # past a readiness publish
    expect(page.locator('#gm-rules-notice')).to_have_count(0)


def test_an_arm_care_concern_is_shown_inline_without_game_rules(setup, coachboard_url):
    page, plan_game, _, _ = setup
    today = datetime.now(ZoneInfo('America/Indiana/Indianapolis')).date()
    yesterday = page.request.post(f'{coachboard_url}/game-day/add', form={
        'game_date': (today - timedelta(days=1)).isoformat(), 'game_start_time': '15:00',
        'game_opponent': 'Arm Care Yesterday', 'pitching_rule_set': 'MLB Pitch Smart'}, max_redirects=0)
    yesterday_id = int(re.search(r'/game/(\d+)', yesterday.headers['location']).group(1))
    try:
        rex = next(p['id'] for p in page.request.get(f'{coachboard_url}/api/roster').json() if p['name'] == 'Relief Rex')
        saved = page.request.post(f'{coachboard_url}/add_pitching', form={
            'game_id': str(yesterday_id), 'player_id': str(rex), 'pitches': '70',
            'innings_whole': '3', 'innings_outs': '0', 'pitcher_type': 'Starter'}, max_redirects=0)
        assert saved.status in {302, 303}
        tomorrow = page.request.post(f'{coachboard_url}/game-day/add', form={
            'game_date': (today + timedelta(days=1)).isoformat(), 'game_start_time': '15:00',
            'game_opponent': 'Arm Care Tomorrow'}, max_redirects=0)
        game_id = int(re.search(r'/game/(\d+)', tomorrow.headers['location']).group(1))
        try:
            _game_without_rules(page, coachboard_url, game_id)
            page.request.post(f'{coachboard_url}/save_rotation', data={
                'title': 'Rotation', 'innings': {'1': dict(FIELDERS)}, 'associated_game_id': game_id})
            _open_game(page, coachboard_url, game_id)
            page.locator(f'{PANEL} [data-pde-pos="P"]').click()
            rex_choice = page.locator('#pde-list .pde-choice[data-player="Relief Rex"]')
            expect(rex_choice.locator('.pde-eligibility')).to_have_text(re.compile(r'^Arm care · '), timeout=10_000)
            # Only Rex has a line; the shared reason is said once.
            expect(page.locator('#pde-list .pde-eligibility')).to_have_count(1)
            rex_choice.click()
            # No question while planning; the concern stays under the field.
            expect(page.locator('#pde-player-modal')).to_be_hidden(timeout=10_000)
            _saved(page)
            assert _filled(_innings(page, coachboard_url, game_id)['1'])['P'] == 'Relief Rex'
            expect(page.locator(f'{PANEL} .pde-pitcher-note')).to_have_text(
                re.compile(r'^Relief Rex: Arm care · .*Start Game will ask before first pitch\.$'), timeout=10_000)

            # Start Game surfaces both: the missing rules and Rex's arm care.
            page.locator('#startLiveGameBtnAction').click()
            sheet = page.locator('#cbStartGameModal')
            expect(sheet).to_be_visible(timeout=15_000)
            expect(sheet.locator('.modal-title')).to_have_text("Pitching rules aren't selected")
            expect(sheet).to_contain_text('Arm care (MLB Pitch Smart): Resting.')
            for label in ('Choose Rules', 'Choose Another Pitcher', 'Start Without Rules'):
                expect(sheet.get_by_role('button', name=label)).to_be_visible()
            sheet.get_by_role('button', name='Close').click()
            expect(sheet).to_be_hidden(timeout=10_000)
            state = page.request.get(f'{coachboard_url}/api/live-game/{game_id}/state').json()
            assert state['game']['is_live'] is False
        finally:
            page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
    finally:
        page.request.post(f'{coachboard_url}/game-day/{yesterday_id}/delete', headers={'Accept': 'application/json'})


# --- 4 and 5. Status wording, the starting pitcher, Out players --------------------------------

def test_a_missing_starter_reads_the_same_everywhere_and_opens_the_picker(setup, make_page, coachboard_url):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': dict(FIELDERS)})
    coach = make_page(PHONE)
    _open_game(coach, coachboard_url, game_id)

    expect(_readiness_line(coach)).to_contain_text('Starting pitcher needed', timeout=15_000)
    plan = coach.locator('#pitching-board-v2 .card-header')
    expect(plan.locator('h5')).to_have_text('Pitching Plan')
    expect(plan).to_contain_text('Starting pitcher not chosen yet.')

    starter = coach.locator('.cb-tap-starter').first
    expect(starter).to_be_visible(timeout=15_000)
    assert _height(starter) >= 44
    starter.click()
    picker = coach.locator('#pde-player-modal')
    expect(picker).to_be_visible(timeout=10_000)
    expect(picker.locator('.modal-title')).to_have_text('P — Choose Player')
    expect(coach.locator('input[name="inning-radio"][value="1"]')).to_be_checked()
    picker.locator('.pde-choice[data-player="Relief Rae"]').click()
    expect(picker).to_be_hidden(timeout=10_000)
    _saved(coach)

    expect(plan).to_contain_text('Starting pitcher: Relief Rae · relief plan optional', timeout=10_000)
    # One title through refreshes -- never "Today's Pitching Board" or "(Optional)".
    coach.wait_for_timeout(6_000)
    expect(plan.locator('h5')).to_have_text('Pitching Plan')


@pytest.mark.parametrize('device', [PHONE, IPAD], ids=lambda d: d[0])
def test_an_out_player_in_the_plan_is_named_once_with_a_fix(setup, make_page, coachboard_url, device):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': {**FIELDERS, 'P': 'Relief Rex'}, '2': {'LF': 'Left Lee'}})
    roster = {p['name']: p['id'] for p in page.request.get(f'{coachboard_url}/api/roster').json()}
    order = list(FIELDERS.values()) + ['Relief Rex']
    lineup = page.request.post(f'{coachboard_url}/add_lineup', data={
        'title': 'Lineup', 'associated_game_id': game_id, 'lineup_player_ids': [roster[n] for n in order]})
    assert lineup.ok
    mark_absent(page, coachboard_url, game_id, ['Left Lee'])
    coach = make_page(device)
    _open_game(coach, coachboard_url, game_id)

    if device is PHONE:  # the one-line summary is the phone layout
        expect(_readiness_line(coach)).to_contain_text('Lineup: Left Lee is Out · 1st inning: Left Lee is Out', timeout=15_000)
    expect(coach.locator('#gameBattingOrderCard .card-header')).to_contain_text('hitters · Left Lee is Out', timeout=15_000)
    status = coach.locator(f'{PANEL} .pde-status')
    expect(status).to_contain_text('Left Lee is marked Out')
    expect(status).not_to_contain_text('Defense complete')
    expect(coach.locator(f'{PANEL} [data-pde-pos="LF"]')).to_have_class(re.compile(r'\bis-out\b'))

    conflicts = coach.locator('#gm-out-conflicts')
    expect(conflicts.locator('.gm-out-item')).to_have_count(1, timeout=15_000)
    # Under Start Game: a short reason that points to the notice, not the
    # whole warning again.
    reason = coach.locator('#gm-mobile-start-reason' if device is PHONE else '#start-live-blockers')
    expect(reason).to_contain_text('1 player marked Out is in the 1st inning. Fix it below.', timeout=15_000)
    expect(reason).not_to_contain_text('Left Lee is marked Out but')
    expect(coach.locator('#startLiveGameBtnAction')).to_be_disabled()
    if device is PHONE:
        expect(reason).to_have_class(re.compile(r'\bcb-tap-out\b'))
    expect(conflicts).to_contain_text('Left Lee is marked Out but is still in the batting order and the defense (LF in the 1st and 2nd).')
    expect(conflicts).to_contain_text('Remove from plan: Left Lee comes out of the batting order and leaves LF open')
    for name in ('Mark Left Lee Playing', 'Remove from plan'):
        assert _height(conflicts.get_by_role('button', name=name)) >= 44
    assert coach.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')

    with coach.expect_navigation(timeout=20_000):
        conflicts.get_by_role('button', name='Remove from plan').click()
    data = page.request.get(f'{coachboard_url}/api/game_data/{game_id}').json()
    assert 'Left Lee' not in data['lineup']['lineup_positions']
    innings = data['rotation']['innings']
    assert 'LF' not in _filled(innings['1']) and 'LF' not in _filled(innings['2'])
    assert _filled(innings['1'])['C'] == 'Catcher Cole'  # nothing else moved
    expect(coach.locator('#gm-out-conflicts')).to_have_count(0, timeout=15_000)
    coach.wait_for_timeout(6_000)
    expect(coach.locator('#gm-out-conflicts')).to_have_count(0)


def test_mark_playing_resolves_the_conflict_without_changing_the_plan(setup, coachboard_url):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': {**FIELDERS, 'P': 'Relief Rex'}})
    mark_absent(page, coachboard_url, game_id, ['Left Lee'])
    _open_game(page, coachboard_url, game_id)

    conflicts = page.locator('#gm-out-conflicts')
    expect(conflicts).to_contain_text('Left Lee is marked Out but is still in the defense (LF in the 1st).', timeout=15_000)
    with page.expect_navigation(timeout=20_000):
        conflicts.get_by_role('button', name='Mark Left Lee Playing').click()
    assert page.request.get(f'{coachboard_url}/api/game_data/{game_id}').json()['absent_player_ids'] == []
    assert _filled(_innings(page, coachboard_url, game_id)['1'])['LF'] == 'Left Lee'
    page.wait_for_timeout(6_000)
    expect(page.locator('#gm-out-conflicts')).to_have_count(0)


def test_the_defense_picker_never_moves_an_out_player_into_another_spot(setup, coachboard_url):
    page, plan_game, _, _ = setup
    game_id = plan_game({'1': {**FIELDERS, 'P': 'Relief Rex'}})
    mark_absent(page, coachboard_url, game_id, ['Left Lee'])
    _open_game(page, coachboard_url, game_id)

    page.locator(f'{PANEL} [data-pde-pos="LF"]').click()
    picker = page.locator('#pde-player-modal')
    expect(picker).to_be_visible(timeout=10_000)
    expect(picker.locator('#pde-help')).to_have_text('Left Lee is marked Out. Choose who plays LF; Left Lee comes off the field.')
    expect(picker.locator('.pde-choice[data-clear]')).to_contain_text('Take Left Lee off the field')
    catcher = picker.locator('.pde-choice[data-player="Catcher Cole"]')
    expect(catcher).to_contain_text('Currently at C — C will become open')
    expect(picker).not_to_contain_text('swaps with Left Lee')
    catcher.click()
    _saved(page)

    first = _filled(_innings(page, coachboard_url, game_id)['1'])
    assert first['LF'] == 'Catcher Cole'
    assert 'C' not in first
    assert 'Left Lee' not in first.values()
