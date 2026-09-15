import os
import re
from datetime import date, timedelta

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


def open_practice_workspace(page: Page, coachboard_url: str):
    # Use a query value so this is always a new document navigation. A hash-only
    # move from Home can legitimately keep the already-fetched practice model,
    # which is not what these tests want after creating fresh fixture data.
    page.goto(f'{coachboard_url}/?_e2e_practice=1#practice_plan', wait_until='domcontentloaded')
    expect(page.locator('#practice_plan')).to_have_class(re.compile(r'\bactive\b'), timeout=15_000)
    expect(page.locator('.cb-practice-plan')).not_to_have_count(0, timeout=15_000)


def test_practice_workspace_prioritizes_active_planning_on_desktop(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 1440, 'height': 900})
    login(page, coachboard_url)

    # Add one past plan so the visual separation between active work and history
    # is exercised as part of the real rendered practice library.
    past_date = (date.today() - timedelta(days=7)).isoformat()
    response = page.request.post(f'{coachboard_url}/add_practice_plan', form={
        'plan_date': past_date,
        'general_notes': 'Past browser practice',
        'emphasis': 'Archived practice',
        'warm_up': 'Warm-up',
        'infield_outfield': 'Defense',
        'hitting': 'Hitting',
        'pitching_catching': 'Bullpens',
    }, max_redirects=0)
    assert response.status in {302, 303}

    open_practice_workspace(page, coachboard_url)

    create_button = page.locator('#practice_plan > button[data-bs-target="#createPracticePlanForm"]')
    create_form = page.locator('#createPracticePlanForm')
    expect(create_button).to_be_visible()
    expect(create_form).to_be_hidden()
    create_button.click()
    expect(create_form).to_have_class(re.compile(r'\bshow\b'), timeout=5_000)
    expect(create_form).to_be_visible()
    create_button.click()
    expect(create_form).not_to_have_class(re.compile(r'\bshow\b'), timeout=5_000)
    expect(create_form).to_be_hidden()

    upcoming = page.locator('.cb-practice-plan.is-upcoming')
    past = page.locator('.cb-practice-plan.is-past')
    expect(upcoming).not_to_have_count(0)
    expect(past).not_to_have_count(0)

    first_past_label = past.first.evaluate(
        "el => getComputedStyle(el, '::before').content"
    )
    assert 'Past practices' in first_past_label

    upcoming.first.locator('.cb-practice-plan-button').click()
    expect(upcoming.first.locator('.cb-practice-preview')).to_be_visible()
    expect(upcoming.first.get_by_role('button', name='Reuse on another date')).to_be_visible()
    expect(upcoming.first.get_by_role('button', name='Edit plan details')).to_be_visible()


def test_practice_workspace_is_touch_friendly_on_mobile(page: Page, coachboard_url: str):
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, coachboard_url)
    open_practice_workspace(page, coachboard_url)

    create_button = page.locator('#practice_plan > button[data-bs-target="#createPracticePlanForm"]')
    expect(create_button).to_be_visible()
    button_box = create_button.bounding_box()
    assert button_box and button_box['height'] >= 44

    plan = page.locator('.cb-practice-plan.is-upcoming').first
    plan.locator('.cb-practice-plan-button').click()
    expect(plan.locator('.accordion-collapse')).to_have_class(re.compile(r'\bshow\b'))

    attendance = plan.locator('.cb-attendance-check').first
    expect(attendance).to_be_visible()
    attendance_box = attendance.bounding_box()
    assert attendance_box and attendance_box['height'] >= 40

    task = plan.locator('.task-list .list-group-item').first
    expect(task).to_be_visible()
    task_box = task.bounding_box()
    assert task_box and task_box['height'] >= 44

    assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2')