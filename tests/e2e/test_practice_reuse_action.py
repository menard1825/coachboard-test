"""An open practice plan offers one reuse action, and it works.

The Practice tab's own "Reuse on another date" button opens the reuse modal
from index.html. season_management_v2.js used to add a second "Reuse Plan"
button inside "Edit plan details"; its handler expected a different modal's
fields, so every click threw "Cannot set properties of null" and did nothing.
"""

import os
import re
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
DESKTOP = {'width': 1440, 'height': 900}
PHONE = {'width': 390, 'height': 844}
VIEWPORTS = pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
REUSE = re.compile(r'reuse', re.I)


@pytest.fixture
def make_page(browser):
    contexts = []

    def _make(viewport):
        cdn_assets.require_vendored_assets()
        mobile = viewport is PHONE
        context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.cb_errors = errors
        return page

    yield _make
    for context in contexts:
        context.close()


def _open_plan(page, base_url):
    """Practice -> the first plan -> Edit plan details. Returns the open plan."""
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')
    page.goto(f'{base_url}/')
    page.wait_for_load_state('load')
    page.evaluate("() => { location.hash = '#practice_plan'; }")
    expect(page.locator('#practice_plan')).to_be_visible(timeout=15_000)

    plan = page.locator('#practicePlanAccordion .cb-practice-plan').first
    plan.locator('.cb-practice-plan-button').click()
    body = plan.locator('.accordion-collapse')
    expect(body).to_be_visible()
    body.get_by_role('button', name='Edit plan details').click()
    expect(body.locator('.practice-plan-details-form')).to_be_visible()
    # Give the page's enhancers time to decorate the open plan.
    page.wait_for_timeout(800)
    return plan


def _reuse_controls(plan):
    return plan.get_by_role('button', name=REUSE)


@VIEWPORTS
def test_an_open_plan_offers_exactly_one_reuse_action(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    plan = _open_plan(page, coachboard_url)
    controls = _reuse_controls(plan)
    labels = [text.strip() for text in controls.all_inner_texts()]
    assert labels == ['Reuse on another date'], labels
    expect(controls.first).to_be_visible()
    assert page.cb_errors == []


@VIEWPORTS
def test_every_reuse_control_opens_the_reuse_dialog(make_page, coachboard_url, viewport):
    """Whatever reuse controls the plan offers, each must work."""
    page = make_page(viewport)
    plan = _open_plan(page, coachboard_url)
    modal = page.locator('#reusePracticeModal')
    for index in range(_reuse_controls(plan).count()):
        control = _reuse_controls(plan).nth(index)
        label = control.inner_text().strip()
        control.scroll_into_view_if_needed()
        control.click()
        page.wait_for_timeout(500)
        assert page.cb_errors == [], f'"{label}" threw: {page.cb_errors}'
        expect(modal, f'"{label}" did not open the reuse dialog').to_be_visible()
        modal.get_by_role('button', name='Cancel').click()
        expect(modal).to_be_hidden()


@VIEWPORTS
def test_reuse_on_another_date_prefills_the_plan_and_next_week(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    plan = _open_plan(page, coachboard_url)
    title = plan.locator('.cb-practice-title strong').inner_text().strip()
    plan_date = plan.locator('input[name="plan_date"]').input_value()

    plan.get_by_role('button', name='Reuse on another date').click()
    modal = page.locator('#reusePracticeModal')
    expect(modal).to_be_visible()
    expect(modal.locator('#reusePracticeName')).to_have_text(title)
    expected = (date.fromisoformat(plan_date) + timedelta(days=7)).isoformat()
    expect(modal.locator('#reusePracticeDate')).to_have_value(expected)
    expect(modal.get_by_role('button', name='Create Copy')).to_be_visible()
    assert page.cb_errors == []


@VIEWPORTS
def test_edit_plan_details_is_unchanged(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    plan = _open_plan(page, coachboard_url)
    form = plan.locator('.practice-plan-details-form')
    expect(form.locator('input[name="plan_date"]')).to_be_visible()
    expect(form.get_by_role('button', name='Save plan details')).to_be_visible()
    expect(form.get_by_role('button', name='Delete plan')).to_be_visible()
    assert page.cb_errors == []
