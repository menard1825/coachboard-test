"""A Saved Defense sets fielders. It never decides the pitcher.

"This inning" and "Whole game" follow one rule:

* every target inning keeps exactly the P it already has (filled, open, or
  marked Out -- the absent-in-plan warning covers that);
* a P stored in an older saved defense is ignored, and new saved defenses
  do not store one;
* a saved fielder who is pitching that inning, or marked Out, leaves that
  position Open, and the confirmation sheet says why -- never a duplicate;
* Cancel changes nothing.
"""

import re
import uuid
from datetime import date, timedelta

import pytest

from test_set_defense_simplified import (  # noqa: F401 (make_page is a fixture)
    DESKTOP,
    DEVICES,
    PANEL,
    _choose_inning,
    _filled,
    _innings,
    _open_game,
    _saved,
    _saved_defense_tools,
    make_page,
)
from test_pregame_player_time_summary import add_player, mark_absent
from e2e_cleanup import delete_players_named

from playwright.sync_api import expect  # noqa: E402


pytestmark = pytest.mark.e2e

PREFIX = 'DEFENSE PRESET — '
FIELDERS = {'C': 'Catcher Cole', '1B': 'First Frank', '2B': 'Second Sam', '3B': 'Third Theo',
            'SS': 'Shortstop Shawn', 'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley'}
# The saved defense moves two fielders so it is visibly applied.
SAVED = {**FIELDERS, 'SS': 'Left Lee', 'LF': 'Shortstop Shawn'}
SHEET = '#pde-use-confirm'
EXTRA_PLAYERS = [('Relief Rex', '21'), ('Relief Rae', '22')]


@pytest.fixture
def setup(make_page, coachboard_url):
    page = make_page(DESKTOP)
    games, defenses = [], []

    def plan_game(innings):
        response = page.request.post(f'{coachboard_url}/game-day/add', form={
            'game_date': (date.today() + timedelta(days=14)).isoformat(), 'game_start_time': '15:00',
            'game_opponent': f'Saved P {uuid.uuid4().hex[:5]}', 'game_location': 'Plan Field',
            'pitching_rule_set': 'USSSA'}, max_redirects=0)
        game_id = int(re.search(r'/game/(\d+)', response.headers['location']).group(1))
        games.append(game_id)
        plan = {str(i): {} for i in range(1, 7)}
        plan.update({key: dict(value) for key, value in innings.items()})
        saved = page.request.post(f'{coachboard_url}/save_rotation', data={
            'title': 'Rotation', 'innings': plan, 'associated_game_id': game_id})
        assert saved.ok and saved.json().get('status') == 'success', saved.text()
        return game_id

    def saved_defense(alignment):
        name = f'Fielders {uuid.uuid4().hex[:5]}'
        response = page.request.post(f'{coachboard_url}/api/starting-defense-template/save',
                                     data={'title': name, 'innings': {'1': alignment}})
        assert response.ok, response.text()
        defenses.append(response.json()['id'])
        return name, response.json()

    def legacy_defense(alignment):
        """A saved defense stored before saved defenses dropped P."""
        name = f'Legacy {uuid.uuid4().hex[:5]}'
        response = page.request.post(f'{coachboard_url}/save_rotation', data={
            'title': PREFIX + name, 'innings': {'1': alignment}, 'associated_game_id': None})
        assert response.ok and response.json().get('status') == 'success', response.text()
        defenses.append(response.json()['new_id'])
        return name

    try:
        for player_name, number in EXTRA_PLAYERS:
            add_player(page, coachboard_url, player_name, number)
        yield page, plan_game, saved_defense, legacy_defense
    finally:
        for game_id in games:
            # A test may have started the game; a live game can't be deleted.
            page.request.post(f'{coachboard_url}/api/live-game/{game_id}/end-with-pitching',
                              data={'defer_pitching': True})
            page.request.post(f'{coachboard_url}/game-day/{game_id}/delete', headers={'Accept': 'application/json'})
        for defense_id in defenses:
            page.request.get(f'{coachboard_url}/delete_rotation/{defense_id}', max_redirects=0)
        assert delete_players_named(page.request, coachboard_url, [n for n, _ in EXTRA_PLAYERS]) == []


def _open_use(page, name, scope):
    tools = _saved_defense_tools(page)
    tools.locator('#pde-preset').select_option(label=name)
    page.locator('#pde-use').click()
    page.locator('#pde-use-inning' if scope == 'This inning' else '#pde-use-game').click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible(timeout=10_000)
    return sheet


def _answer(page, answer):
    sheet = page.locator(SHEET)
    sheet.get_by_role('button', name=answer, exact=True).click()
    expect(sheet).to_be_hidden(timeout=10_000)


def _assert_no_duplicates(innings):
    for key, defense in innings.items():
        names = [name for name in _filled(defense).values()]
        assert len(names) == len(set(names)), (key, defense)


def test_this_inning_keeps_the_planned_pitcher(setup, coachboard_url):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'2': {**FIELDERS, 'P': 'Relief Rex'}})
    name, _ = saved_defense(SAVED)
    _open_game(page, coachboard_url, game_id)
    _choose_inning(page, 2)

    sheet = _open_use(page, name, 'This inning')
    expect(sheet.locator('.modal-title')).to_have_text(f'Use “{name}” for the 2nd inning?')
    expect(sheet).to_contain_text('Fielders in the 2nd inning will be replaced.')
    expect(sheet).to_contain_text('Relief Rex stays at P.')
    _answer(page, 'Use Saved Defense')
    _saved(page)

    innings = _innings(page, coachboard_url, game_id)
    assert _filled(innings['2']) == {**SAVED, 'P': 'Relief Rex'}
    assert _filled(innings['1']) == {} and _filled(innings['3']) == {}
    _assert_no_duplicates(innings)


def test_this_inning_leaves_an_open_pitcher_open(setup, coachboard_url):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'1': {**FIELDERS, 'P': 'Pitcher Pat'}})
    name, _ = saved_defense(SAVED)
    _open_game(page, coachboard_url, game_id)
    _choose_inning(page, 4)

    sheet = _open_use(page, name, 'This inning')
    expect(sheet).to_contain_text('No pitcher is planned yet. Saved defenses never set the pitcher.')
    _answer(page, 'Use Saved Defense')
    _saved(page)

    innings = _innings(page, coachboard_url, game_id)
    assert _filled(innings['4']) == SAVED
    assert 'P' not in _filled(innings['4'])
    # A later inning shows its open P as still to be chosen.
    expect(page.locator(f'{PANEL} [data-pde-pos="P"] .pde-name')).to_have_text(re.compile('PITCHER TBD'))


def test_whole_game_keeps_each_innings_pitcher(setup, coachboard_url):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({
        '1': {**FIELDERS, 'P': 'Pitcher Pat'},
        '2': {**FIELDERS, 'P': 'Pitcher Pat'},
        '3': {**FIELDERS, 'P': 'Relief Rex'},
    })
    name, _ = saved_defense(SAVED)
    _open_game(page, coachboard_url, game_id)

    sheet = _open_use(page, name, 'Whole game')
    expect(sheet.locator('.modal-title')).to_have_text(f'Use “{name}” for innings 1–6?')
    expect(sheet).to_contain_text(
        'Pitchers stay as planned: Pitcher Pat (1st–2nd) · Relief Rex (3rd) · no pitcher yet (4th–6th).'
    )
    _answer(page, 'Use Saved Defense')
    _saved(page)

    innings = _innings(page, coachboard_url, game_id)
    assert _filled(innings['1']) == {**SAVED, 'P': 'Pitcher Pat'}
    assert _filled(innings['2']) == {**SAVED, 'P': 'Pitcher Pat'}
    assert _filled(innings['3']) == {**SAVED, 'P': 'Relief Rex'}
    for key in ('4', '5', '6'):
        assert _filled(innings[key]) == SAVED, (key, innings[key])
    _assert_no_duplicates(innings)


def test_a_different_pitcher_in_an_old_saved_defense_is_not_used(setup, coachboard_url):
    page, plan_game, _, legacy_defense = setup
    game_id = plan_game({'1': {**FIELDERS, 'P': 'Pitcher Pat'}})
    name = legacy_defense({**SAVED, 'P': 'Relief Rae'})
    _open_game(page, coachboard_url, game_id)

    sheet = _open_use(page, name, 'This inning')
    expect(sheet).to_contain_text('Pitcher Pat stays at P.')
    expect(sheet).to_contain_text(
        f'“{name}” was saved with Relief Rae at P. Saved defenses set fielders only, '
        "so Relief Rae isn't placed by it."
    )
    _answer(page, 'Use Saved Defense')
    _saved(page)

    innings = _innings(page, coachboard_url, game_id)
    assert _filled(innings['1']) == {**SAVED, 'P': 'Pitcher Pat'}
    assert 'Relief Rae' not in _filled(innings['1']).values()


def test_an_old_saved_defense_never_fills_an_open_pitcher(setup, coachboard_url):
    page, plan_game, _, legacy_defense = setup
    game_id = plan_game({'1': dict(FIELDERS)})
    name = legacy_defense({**SAVED, 'P': 'Relief Rae'})
    _open_game(page, coachboard_url, game_id)

    _open_use(page, name, 'Whole game')
    _answer(page, 'Use Saved Defense')
    _saved(page)

    innings = _innings(page, coachboard_url, game_id)
    for key in map(str, range(1, 7)):
        assert _filled(innings[key]) == SAVED, (key, innings[key])


@DEVICES
def test_planned_pitcher_at_a_saved_position_leaves_it_open(setup, make_page, coachboard_url, device):
    _, plan_game, saved_defense, _ = setup
    # Shawn pitches the 1st-3rd; the saved defense has him at SS.
    game_id = plan_game({
        '1': {**FIELDERS, 'SS': 'Relief Rex', 'P': 'Shortstop Shawn'},
        '2': {**FIELDERS, 'SS': 'Relief Rex', 'P': 'Shortstop Shawn'},
        '3': {**FIELDERS, 'SS': 'Relief Rex', 'P': 'Shortstop Shawn'},
        '4': {**FIELDERS, 'P': 'Pitcher Pat'},
    })
    name, _ = saved_defense(dict(FIELDERS))
    page = make_page(device)
    _open_game(page, coachboard_url, game_id)

    sheet = _open_use(page, name, 'Whole game')
    expect(sheet).to_contain_text('SS is left Open in the 1st–3rd: Shortstop Shawn is pitching.')
    _answer(page, 'Use Saved Defense')
    _saved(page)

    innings = _innings(page, coachboard_url, game_id)
    without_ss = {pos: name for pos, name in FIELDERS.items() if pos != 'SS'}
    for key in ('1', '2', '3'):
        assert _filled(innings[key]) == {**without_ss, 'P': 'Shortstop Shawn'}, (key, innings[key])
    assert _filled(innings['4']) == {**FIELDERS, 'P': 'Pitcher Pat'}
    for key in ('5', '6'):
        assert _filled(innings[key]) == FIELDERS, (key, innings[key])
    _assert_no_duplicates(innings)
    expect(page.locator(f'{PANEL} [data-pde-pos="SS"] .pde-name')).to_have_text('OPEN')


def test_this_inning_conflict_names_the_position_and_pitcher(setup, coachboard_url):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'1': {**FIELDERS, 'SS': 'Relief Rex', 'P': 'Shortstop Shawn'}})
    name, _ = saved_defense(dict(FIELDERS))
    _open_game(page, coachboard_url, game_id)

    sheet = _open_use(page, name, 'This inning')
    expect(sheet).to_contain_text('Shortstop Shawn stays at P.')
    expect(sheet).to_contain_text('SS is left Open: Shortstop Shawn is pitching.')
    _answer(page, 'Use Saved Defense')
    _saved(page)

    innings = _innings(page, coachboard_url, game_id)
    assert innings['1'].get('P') == 'Shortstop Shawn'
    assert not innings['1'].get('SS')
    _assert_no_duplicates(innings)


def test_a_planned_pitcher_marked_out_is_kept_and_flagged(setup, coachboard_url):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'1': {**FIELDERS, 'P': 'Relief Rex'}})
    mark_absent(page, coachboard_url, game_id, ['Relief Rex'])
    name, _ = saved_defense(SAVED)
    _open_game(page, coachboard_url, game_id)

    sheet = _open_use(page, name, 'This inning')
    expect(sheet).to_contain_text('Relief Rex stays at P.')
    _answer(page, 'Use Saved Defense')
    _saved(page)

    innings = _innings(page, coachboard_url, game_id)
    assert _filled(innings['1']) == {**SAVED, 'P': 'Relief Rex'}
    # The existing absent-in-plan warning, not the saved defense, handles it.
    expect(page.locator('[data-absent-warning]')).to_have_text(
        '⚠ Relief Rex is marked absent but is still in the plan: pitching in the 1st.'
    )


def test_an_unavailable_saved_fielder_leaves_the_position_open(setup, coachboard_url):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'1': {**FIELDERS, 'P': 'Pitcher Pat'}})
    mark_absent(page, coachboard_url, game_id, ['Center Casey'])
    name, _ = saved_defense(SAVED)
    _open_game(page, coachboard_url, game_id)

    sheet = _open_use(page, name, 'This inning')
    expect(sheet).to_contain_text('CF is left Open: Center Casey is marked Out for this game.')
    _answer(page, 'Use Saved Defense')
    _saved(page)

    innings = _innings(page, coachboard_url, game_id)
    expected = {pos: name for pos, name in SAVED.items() if pos != 'CF'}
    assert _filled(innings['1']) == {**expected, 'P': 'Pitcher Pat'}


def test_cancel_changes_nothing(setup, coachboard_url):
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'2': {**FIELDERS, 'P': 'Relief Rex'}})
    name, _ = saved_defense(SAVED)
    _open_game(page, coachboard_url, game_id)
    _choose_inning(page, 2)
    before = _innings(page, coachboard_url, game_id)

    _open_use(page, name, 'This inning')
    _answer(page, 'Cancel')
    page.wait_for_timeout(600)

    status = page.locator(f'{PANEL} #pde-save-status')
    expect(status).not_to_contain_text('Saving')
    expect(status).not_to_contain_text('Saved')
    canonical = page.evaluate('() => window.CBPregameRotation.getRotation().innings')
    assert _filled(canonical['2']) == {**FIELDERS, 'P': 'Relief Rex'}
    assert _innings(page, coachboard_url, game_id) == before
    expect(page.locator(f'{PANEL} [data-pde-pos="SS"] .pde-name')).to_have_text('Shortstop Shawn')


def test_new_saved_defenses_do_not_store_the_pitcher(setup, coachboard_url):
    page, plan_game, saved_defense, _ = setup
    # An older client sending P: the server keeps the fielders only.
    _, saved = saved_defense({**SAVED, 'P': 'Pitcher Pat'})
    assert saved['rotation']['innings'] == {'1': SAVED}

    # Save this defense from Prepare Game with a pitcher on the field.
    game_id = plan_game({'1': {**FIELDERS, 'P': 'Pitcher Pat'}})
    _open_game(page, coachboard_url, game_id)
    tools = _saved_defense_tools(page)
    tools.get_by_role('button', name='Save this defense', exact=True).click()
    modal = page.locator('#pde-preset-modal')
    expect(modal).to_contain_text("Saved defenses set fielders only. The pitcher isn't saved")
    name = f'Fielders {uuid.uuid4().hex[:5]}'
    modal.locator('#pde-name').fill(name)
    with page.expect_response(lambda r: r.url.endswith('/api/starting-defense-template/save')) as saving:
        modal.locator('#pde-confirm').click()
    created = saving.value.json()
    defense_id = created['rotation']['id']
    page.request.get(f'{coachboard_url}/delete_rotation/{defense_id}', max_redirects=0)
    assert created['rotation']['innings'] == {'1': FIELDERS}


@pytest.mark.parametrize('answer', ['Use Saved Defense', 'Cancel'])
def test_a_tap_while_the_sheet_is_still_opening_counts(setup, coachboard_url, answer):
    """Bootstrap ignores hide() mid-transition; the answer must still count."""
    page, plan_game, saved_defense, _ = setup
    game_id = plan_game({'1': {**FIELDERS, 'P': 'Pitcher Pat'}})
    name, _ = saved_defense(SAVED)
    _open_game(page, coachboard_url, game_id)
    before = _innings(page, coachboard_url, game_id)

    # Tap the answer the moment the sheet starts to open, before it is shown.
    page.evaluate(
        """answer => document.addEventListener('show.bs.modal', event => {
            if (event.target.id !== 'pde-use-confirm') return;
            const button = [...event.target.querySelectorAll('button')]
              .find(item => item.textContent.trim() === answer);
            setTimeout(() => button.click(), 0);
        }, {once: true})""",
        answer,
    )
    tools = _saved_defense_tools(page)
    tools.locator('#pde-preset').select_option(label=name)
    page.locator('#pde-use').click()
    page.locator('#pde-use-inning').click()

    expect(page.locator(SHEET)).to_be_hidden(timeout=10_000)
    if answer == 'Cancel':
        page.wait_for_timeout(600)
        assert _innings(page, coachboard_url, game_id) == before
    else:
        _saved(page)
        assert _filled(_innings(page, coachboard_url, game_id)['1']) == {**SAVED, 'P': 'Pitcher Pat'}
