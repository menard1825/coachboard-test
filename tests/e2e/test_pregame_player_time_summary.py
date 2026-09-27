"""Player Time / Position Summary on Prepare Game, checked against real plans.

The summary answers a coach's question before the game: has every player got
reasonable playing time, and where is each one playing? It reads the pregame
defensive plan -- each inning and any planned change during an inning -- and
nothing from a live game.
"""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip(
        'Set COACHBOARD_E2E=1 to run Playwright tests.',
        allow_module_level=True,
    )

from playwright.sync_api import Page, expect

from e2e_cleanup import delete_players_named
from test_next_inning_save_race import cleanup_game, login, post_json


DESKTOP = {'width': 1280, 'height': 900}
PHONE = {'width': 390, 'height': 844}
SUMMARY = '#pde-playing-time-summary'
EXTRA_PLAYERS = [('Bench Blake', '10'), ('Bench Bree', '11')]

BASE = {
    'P': 'Pitcher Pat', 'C': 'Catcher Cole', '1B': 'First Frank',
    '2B': 'Second Sam', '3B': 'Third Theo', 'SS': 'Shortstop Shawn',
    'LF': 'Left Lee', 'CF': 'Center Casey', 'RF': 'Right Riley',
}


def realistic_plan():
    """Four innings with two planned changes during inning 3.

    1: the starting nine; Blake and Bree sit.
    2: Blake takes RF, Riley sits.
    3: Blake starts in LF while Lee sits; during the inning (3.1) Lee comes
       back to LF, Blake sits, and Shawn takes over pitching with Pat to SS.
    4: Shawn pitches, Pat at SS, and CF is still open (not finished).
    """
    third = dict(BASE, LF='Bench Blake')
    third_change = dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat')
    fourth = dict(BASE, P='Shortstop Shawn', SS='Pitcher Pat')
    fourth.pop('CF')
    return {
        '1': BASE,
        '2': dict(BASE, RF='Bench Blake'),
        '3': third,
        '3.1': third_change,
        '4': fourth,
    }


def add_player(page: Page, url: str, name: str, number: str):
    response = page.request.post(
        f'{url}/add_player',
        form={
            'name': name, 'number': number, 'position1': '', 'position2': '',
            'position3': '', 'throws': 'Right', 'bats': 'Right', 'notes': '',
            'pitcher_role': 'Not a Pitcher', 'roster_status': 'regular',
        },
        headers={'X-Requested-With': 'XMLHttpRequest'},
        max_redirects=0,
    )
    assert response.status == 200 and response.json().get('status') == 'success', (
        response.status, response.text()[:200]
    )


@pytest.fixture
def planned_game(page: Page, coachboard_url: str):
    login(page, coachboard_url)
    names = [name for name, _ in EXTRA_PLAYERS]
    game_id = None
    try:
        for name, number in EXTRA_PLAYERS:
            add_player(page, coachboard_url, name, number)

        def create(innings):
            nonlocal game_id
            response = page.request.post(
                f'{coachboard_url}/game-day/add',
                form={
                    'game_date': (date.today() + timedelta(days=12)).isoformat(),
                    'game_start_time': '10:00',
                    'game_opponent': 'Player Time Opponent',
                    'game_location': 'Player Time Field',
                    'pitching_rule_set': 'USSSA',
                },
                max_redirects=0,
            )
            assert response.status in {302, 303}
            game_id = int(
                re.search(r'/game/(\d+)', response.headers['location']).group(1)
            )
            post_json(page, coachboard_url, '/save_rotation', {
                'title': 'Player Time Plan',
                'innings': innings,
                'associated_game_id': game_id,
            })
            return game_id

        yield create
    finally:
        if game_id is not None:
            cleanup_game(page, coachboard_url, game_id)
        assert delete_players_named(page.request, coachboard_url, names) == []


def open_prepare_game(page: Page, url: str, game_id: int, viewport):
    page.set_viewport_size(viewport)
    page.goto(f'{url}/game/{game_id}', wait_until='domcontentloaded')
    expect(page.locator(SUMMARY)).to_have_count(1, timeout=15_000)


def row(page: Page, name: str):
    return page.evaluate(
        """name => {
            const r = document.querySelector(
                `#pde-playing-time-summary [data-player-name="${CSS.escape(name)}"]`
            );
            if (!r) return null;
            const text = el => (el ? el.textContent.replace(/\\s+/g, ' ').trim() : '');
            return {
                full: Number(r.dataset.full),
                partial: Number(r.dataset.partial),
                bench: Number(r.dataset.bench),
                innings: r.dataset.innings,
                total: text(r.querySelector('.pde-time-total')),
                chips: [...r.querySelectorAll('.pde-time-chip')].map(text),
            };
        }""",
        name,
    )


def summary_text(page: Page, selector: str):
    return page.evaluate(
        """sel => {
            const el = document.querySelector(`#pde-playing-time-summary ${sel}`);
            return el ? el.textContent.replace(/\\s+/g, ' ').trim() : null;
        }""",
        selector,
    )


def select_inning(page: Page, inning: str):
    page.evaluate(
        """value => {
            const radio = [...document.querySelectorAll('input[name="inning-radio"]')]
                .find(input => input.value === value);
            radio.click();
        }""",
        inning,
    )
    expect(page.locator('input[name="inning-radio"]:checked')).to_have_value(inning)


def choose_for_spot(page: Page, position: str, button_name):
    page.locator(
        f'#pregame-defense-editor-v3 .pde-spot[data-pde-pos="{position}"]'
    ).click()
    modal = page.locator('#pde-player-modal')
    expect(modal).to_be_visible()
    modal.get_by_role('button', name=button_name).first.click()
    expect(modal).to_be_hidden()


# ---------------------------------------------------------------- the plan


@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_summary_follows_the_whole_plan(
    page: Page, coachboard_url, planned_game, viewport
):
    game_id = planned_game(realistic_plan())
    open_prepare_game(page, coachboard_url, game_id, viewport)

    # What the coach reads first. The unfinished inning 4 must not make
    # Casey "sit", and part of an inning is never a full inning.
    assert row(page, 'Center Casey')['total'] == '3 full · 0 bench'
    assert row(page, 'Bench Blake')['total'] == '1 full · 1 partial · 1 bench'

    # 1. All innings at one position.
    cole = row(page, 'Catcher Cole')
    assert (cole['full'], cole['partial'], cole['bench']) == (4, 0, 0)
    assert cole['chips'] == ['C × 4']
    assert cole['innings'] == '1 C · 2 C · 3 C · 4 C'

    # 2 + 6. Pitcher who moves to short during inning 3: on the field for
    #        all four innings, but P and SS each hold only part of inning 3.
    pat = row(page, 'Pitcher Pat')
    assert (pat['full'], pat['partial'], pat['bench']) == (4, 0, 0)
    assert pat['total'] == '4 full · 0 bench'
    assert pat['chips'] == ['P × 2 + 1 part', 'SS × 1 + 1 part']
    assert pat['innings'] == '1 P · 2 P · 3 P→SS · 4 SS'

    # 5. The planned pitching, including the change during inning 3.
    assert summary_text(page, '[data-pitching-plan]') == (
        'Pitching: Pitcher Pat: 1, 2, 3 (part) · Shortstop Shawn: 3 (part), 4'
    )
    shawn = row(page, 'Shortstop Shawn')
    assert shawn['chips'] == ['P × 1 + 1 part', 'SS × 2 + 1 part']
    assert shawn['innings'] == '1 SS · 2 SS · 3 SS→P · 4 P'

    # 3. Plays some innings and sits one.
    riley = row(page, 'Right Riley')
    assert (riley['full'], riley['partial'], riley['bench']) == (3, 0, 1)
    assert riley['chips'] == ['RF × 3', 'BN × 1']
    assert riley['innings'] == '1 RF · 2 BN · 3 RF · 4 RF'

    # 4. Bench player enters in inning 2 and leaves during inning 3.
    blake = row(page, 'Bench Blake')
    assert (blake['full'], blake['partial'], blake['bench']) == (1, 1, 1)
    assert blake['chips'] == ['LF × 1 part', 'RF × 1', 'BN × 1']
    assert blake['innings'] == '1 BN · 2 RF · 3 LF→BN · 4 –'

    # Enters during inning 3: full and partial time together.
    lee = row(page, 'Left Lee')
    assert (lee['full'], lee['partial'], lee['bench']) == (3, 1, 0)
    assert lee['total'] == '3 full · 1 partial · 0 bench'
    assert lee['chips'] == ['LF × 3 + 1 part']
    assert lee['innings'] == '1 LF · 2 LF · 3 BN→LF · 4 LF'

    # 7. No planned defensive time at all.
    bree = row(page, 'Bench Bree')
    assert (bree['full'], bree['partial'], bree['bench']) == (0, 0, 3)
    assert bree['total'] == 'No field time planned'

    # 8. Inning 4 is not finished: the open CF is nobody's time, and the
    #    players not placed in it are unassigned, not sitting.
    casey = row(page, 'Center Casey')
    assert (casey['full'], casey['partial'], casey['bench']) == (3, 0, 0)
    assert casey['innings'] == '1 CF · 2 CF · 3 CF · 4 –'
    assert summary_text(page, '.pde-playing-time-open') == (
        'Not finished: Inning 4 (CF open). '
        "Players not placed there show – and don't count as bench."
    )

    # 10. Every player's totals are their own.
    for name in ['First Frank', 'Second Sam', 'Third Theo']:
        other = row(page, name)
        assert (other['full'], other['partial'], other['bench']) == (4, 0, 0), (name, other)
        assert len(other['chips']) == 1

    # Nobody is absent: no absence warning anywhere.
    assert page.locator('[data-absent-warning], .gm-playing-time-alert').count() == 0

    # The coach can open it at this width and read it.
    toggle = page.locator(
        '.gm-playing-time-toggle:visible, .gm-phone-playing-time-toggle:visible'
    ).first
    toggle.click()
    expect(page.locator(SUMMARY)).to_be_visible()
    expect(page.locator(f'{SUMMARY} [data-pitching-plan]')).to_be_visible()
    expect(
        page.locator(f'{SUMMARY} [data-player-name="Bench Blake"] .pde-time-innings')
    ).to_be_visible()


# ----------------------------------------------------------------- updates


def test_summary_updates_as_the_plan_changes(
    page: Page, coachboard_url, planned_game
):
    game_id = planned_game({'1': BASE, '2': dict(BASE, RF='Bench Blake')})
    open_prepare_game(page, coachboard_url, game_id, DESKTOP)
    assert row(page, 'Bench Bree')['total'] == 'No field time planned'

    # A bench player comes onto the field in inning 1.
    choose_for_spot(page, 'LF', re.compile('Bench Bree'))
    expect(page.locator(f'{SUMMARY} [data-player-name="Bench Bree"]')).to_have_attribute(
        'data-innings', '1 LF · 2 BN'
    )
    assert (row(page, 'Left Lee')['full'], row(page, 'Left Lee')['bench']) == (1, 1)

    # A new planned pitcher for inning 2.
    select_inning(page, '2')
    choose_for_spot(page, 'P', re.compile('Right Riley'))
    expect(page.locator(f'{SUMMARY} [data-pitching-plan]')).to_have_text(
        'Pitching: Pitcher Pat: 1 · Right Riley: 2'
    )
    expect(page.locator(f'{SUMMARY} [data-player-name="Pitcher Pat"]')).to_have_attribute(
        'data-innings', '1 P · 2 BN'
    )

    # Copying inning 2 to the later (empty) innings adds them to the plan.
    page.locator('#gmCopyDefenseBtn').click()
    page.locator('#gmApplyDefenseRemainingBtn').click()
    riley = page.locator(f'{SUMMARY} [data-player-name="Right Riley"]')
    expect(riley).to_have_attribute('data-full', '6', timeout=10_000)
    expect(riley).to_have_attribute(
        'data-innings', '1 RF · 2 P · 3 P · 4 P · 5 P · 6 P'
    )
    expect(page.locator(f'{SUMMARY} .pde-playing-time-head')).to_contain_text(
        '6 planned innings'
    )


# ---------------------------------------------------------- absent players


def mark_absent(page: Page, url: str, game_id: int, names):
    roster = page.request.get(f'{url}/api/roster').json()
    ids = [str(player['id']) for player in roster if player['name'] in names]
    assert len(ids) == len(names)
    response = page.request.post(
        f'{url}/game/{game_id}/update_absences',
        data='&'.join(f'absent_players={player_id}' for player_id in ids),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        max_redirects=0,
    )
    assert response.status in {302, 303}
    saved = page.request.get(f'{url}/api/game_data/{game_id}').json()
    assert sorted(map(str, saved['absent_player_ids'])) == sorted(ids)


@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_absent_players_still_in_the_plan_are_flagged(
    page: Page, coachboard_url, planned_game, viewport
):
    """Riley and Blake are out today but still planned; Bree is out and unused."""
    game_id = planned_game({
        '1': BASE,
        '2': dict(BASE, P='Bench Blake', SS='Pitcher Pat', RF='Shortstop Shawn',
                  LF='Right Riley', CF='Left Lee', **{'2B': 'Center Casey'}),
        '3': dict(BASE, RF='Second Sam', **{'2B': 'Right Riley'}),
    })
    mark_absent(
        page, coachboard_url, game_id,
        ['Right Riley', 'Bench Blake', 'Bench Bree'],
    )
    open_prepare_game(page, coachboard_url, game_id, viewport)

    warnings = page.locator('[data-absent-warning]')
    expect(warnings).to_have_count(2)
    # Roster order. 9. An absent planned pitcher is named as pitching.
    expect(warnings).to_have_text([
        '⚠ Bench Blake is marked absent but is still in the plan: '
        'pitching in the 2nd.',
        '⚠ Right Riley is marked absent but is still in the plan: '
        'RF in the 1st, LF in the 2nd, 2B in the 3rd.',
    ])
    # Absent and unused: no noise, and absent players get no time row.
    assert page.locator('[data-absent-warning]:has-text("Bench Bree")').count() == 0
    for name in ['Right Riley', 'Bench Blake', 'Bench Bree']:
        assert row(page, name) is None

    # Seen while the summary is still collapsed, on its toggle.
    alert = page.locator('.gm-playing-time-alert:visible')
    expect(alert).to_have_text('⚠ 2 absent players are still in the plan')

    # Nothing was changed for the coach.
    rotation = page.evaluate('() => window.CBPregameRotation.getRotation().innings')
    assert rotation['1']['RF'] == 'Right Riley'
    assert rotation['2']['P'] == 'Bench Blake'
