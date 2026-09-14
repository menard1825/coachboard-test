import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    identity = page.get_by_label('Username or email')
    if identity.count() == 0:
        page.goto(f'{coachboard_url}/logout')
        identity = page.get_by_label('Username or email')
    identity.fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$'))


def test_coach_notes_workspace_is_mobile_readable(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    page.goto(f'{coachboard_url}/#collaboration', wait_until='domcontentloaded')

    workspace = page.locator('#collaboration')
    expect(workspace).to_be_visible()

    pseudo_title = workspace.evaluate("el => getComputedStyle(el, '::before').content")
    assert 'Coach Notes' in pseudo_title

    panels = workspace.locator(':scope > .row > .col-md-6 > .card')
    expect(panels).to_have_count(2)
    expect(panels.nth(0).get_by_role('heading', name='Team Notes')).to_be_visible()
    expect(panels.nth(1).get_by_role('heading', name='Player Notes')).to_be_visible()

    team_textarea = panels.nth(0).locator('textarea[name="note_text"]')
    player_select = panels.nth(1).locator('#collab-player-select')
    player_textarea = panels.nth(1).locator('textarea[name="note_text"]')
    expect(team_textarea).to_be_visible()
    expect(player_select).to_be_visible()
    expect(player_textarea).to_be_visible()

    team_font = float(team_textarea.evaluate("el => parseFloat(getComputedStyle(el).fontSize)"))
    player_font = float(player_textarea.evaluate("el => parseFloat(getComputedStyle(el).fontSize)"))
    select_font = float(player_select.evaluate("el => parseFloat(getComputedStyle(el).fontSize)"))
    assert team_font >= 16
    assert player_font >= 16
    assert select_font >= 16

    add_buttons = workspace.locator('form .btn-primary')
    expect(add_buttons).to_have_count(2)
    widths = add_buttons.evaluate_all(
        "items => items.map(el => ({button: el.getBoundingClientRect().width, form: el.closest('form').getBoundingClientRect().width, height: el.getBoundingClientRect().height}))"
    )
    assert all(item['button'] >= item['form'] - 24 for item in widths)
    assert all(item['height'] >= 44 for item in widths)

    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2')
