"""Browser coverage for shared mid-inning defensive reps in the Game Report."""

import json
import os

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)


def test_game_report_counts_only_full_inning_sits(page: Page, coachboard_url: str):
    initial = {
        'P': 'Pat',
        'C': 'Cole',
        '1B': 'Graham',
        '2B': 'Sam',
        '3B': 'Theo',
        'SS': 'Shawn',
        'LF': 'Lee',
        'CF': 'Casey',
        'RF': 'Riley',
    }
    after = {**initial, '1B': 'Jack'}
    roster_names = ['Pat', 'Cole', 'Graham', 'Sam', 'Theo', 'Shawn', 'Lee', 'Casey', 'Riley', 'Jack', 'Ben']
    state = {
        'roster': [{'id': index + 1, 'name': name, 'number': ''} for index, name in enumerate(roster_names)],
        'rotation': {'innings': {'1': initial}},
        'actual_rotation': {'1': after},
        'rotation_events': [
            {
                'inning': '1',
                'sequence': 1,
                'event_type': 'Defensive Change',
                'before_alignment': initial,
                'after_alignment': after,
                'reverted': False,
            },
            {
                'inning': '1',
                'sequence': 2,
                'event_type': 'Defensive Change',
                'before_alignment': after,
                'after_alignment': initial,
                'reverted': True,
            },
        ],
    }

    page.route(
        '**/api/live-game/42/state',
        lambda route: route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps(state),
        ),
    )
    page.goto(f'{coachboard_url}/login')
    page.set_content(
        '''
        <div class="agr-shell" data-game-id="42">
          <table><tbody id="agr-bench-body"></tbody></table>
          <div class="agr-inning" data-inning="1" data-reliable="1">
            <div class="agr-pos" data-pos="P"><b>P</b><span>Pat</span></div>
            <div class="agr-pos" data-pos="C"><b>C</b><span>Cole</span></div>
            <div class="agr-pos" data-pos="1B"><b>1B</b><span>Jack</span></div>
            <div class="agr-pos" data-pos="2B"><b>2B</b><span>Sam</span></div>
            <div class="agr-pos" data-pos="3B"><b>3B</b><span>Theo</span></div>
            <div class="agr-pos" data-pos="SS"><b>SS</b><span>Shawn</span></div>
            <div class="agr-pos" data-pos="LF"><b>LF</b><span>Lee</span></div>
            <div class="agr-pos" data-pos="CF"><b>CF</b><span>Casey</span></div>
            <div class="agr-pos" data-pos="RF"><b>RF</b><span>Riley</span></div>
            <div class="agr-bench" data-role="bench"><strong>Bench:</strong> Graham, Ben</div>
          </div>
          <section id="agr-game-changes-card" hidden>
            <div id="agr-game-changes"></div>
          </section>
        </div>
        '''
    )
    page.add_script_tag(url=f'{coachboard_url}/static/js/game_report_shared_defense.js')

    expect(page.locator('.agr-pos[data-pos="1B"] span')).to_have_text('Graham / Jack')

    bench = page.locator('[data-role="bench"]')
    expect(bench).to_contain_text('Ben')
    expect(bench).not_to_contain_text('Graham')
    expect(bench).not_to_contain_text('Jack')

    graham_row = page.locator('#agr-bench-body tr').filter(has_text='Graham')
    jack_row = page.locator('#agr-bench-body tr').filter(has_text='Jack')
    ben_row = page.locator('#agr-bench-body tr').filter(has_text='Ben')
    expect(graham_row.locator('td').nth(1)).to_have_text('0')
    expect(jack_row.locator('td').nth(1)).to_have_text('0')
    expect(ben_row.locator('td').nth(1)).to_have_text('1')
    expect(ben_row.locator('td').nth(2)).to_have_text('1')

    changes = page.locator('#agr-game-changes-card')
    expect(changes).to_be_visible()
    expect(changes).to_contain_text('Inning 1 · Defensive Change')
    expect(changes).to_contain_text('Jack: BENCH → 1B')
    expect(changes).to_contain_text('Graham: 1B → BENCH')
    expect(changes).not_to_contain_text('reverted')
