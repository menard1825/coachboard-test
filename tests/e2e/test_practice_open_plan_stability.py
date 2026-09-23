"""An open practice plan stays open, and in place, when Practice refreshes.

Every practice change -- ticking a setup task inside the plan, or any change
made by another coach -- emits `data_updated`, and main.js refreshes the
visible Practice tab by rebuilding the plan list. The rebuild used to render
every plan collapsed: the plan the coach was working in closed, the page lost
its height, and the scroll position fell back to the top. On phones, where the
coach scrolls well down inside a long plan, that read as the page jumping.
"""

import os
import uuid

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
VIEWPORTS = pytest.mark.parametrize('viewport', [PHONE, DESKTOP], ids=['phone', 'desktop'])
TOLERANCE_PX = 80

#: The page's scroller: main.container-fluid on phones, the window on desktop.
SCROLL = """() => {
  const main = document.querySelector('main.container-fluid');
  const inner = main && main.scrollHeight > main.clientHeight + 5
    && getComputedStyle(main).overflowY !== 'visible';
  return inner ? main.scrollTop : window.scrollY;
}"""
PLANS_FETCHED = "performance.getEntriesByType('resource').filter(e => e.name.includes('/api/practice_plans')).length"


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
        page.cb_phone = mobile
        return page

    yield _make
    for context in contexts:
        context.close()


def _open_plan(page, base_url):
    page.goto(f'{base_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')
    page.goto(f'{base_url}/')
    page.wait_for_load_state('load')
    if page.cb_phone:
        page.locator('#cb-global-mobile-nav [data-cb-mobile-section="practice_plan"]').tap()
    else:
        page.locator('.coach-primary-nav [data-cb-section="practice_plan"]').click()
    expect(page.locator('#practicePlanAccordion .cb-practice-plan').first).to_be_visible(timeout=15_000)
    plan = page.locator('#practicePlanAccordion .cb-practice-plan').first
    plan.locator('.cb-practice-plan-button').click()
    expect(plan.locator('.accordion-collapse')).to_be_visible()
    page.wait_for_timeout(600)
    return plan


def _bring_to_middle(page, locator):
    """Scroll the page's own scroller so the element sits mid-screen."""
    page.evaluate(
        """el => {
          const main = document.querySelector('main.container-fluid');
          const inner = main && main.scrollHeight > main.clientHeight + 5
            && getComputedStyle(main).overflowY !== 'visible';
          const offset = el.getBoundingClientRect().top - innerHeight / 2;
          if (inner) main.scrollTop += offset; else scrollBy(0, offset);
        }""", locator.element_handle())
    page.wait_for_timeout(500)


def _tap(page, locator):
    box = locator.bounding_box()
    assert box and 60 < box['y'] < page.viewport_size['height'] - 90, box
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    if page.cb_phone:
        page.touchscreen.tap(x, y)
    else:
        page.mouse.click(x, y)


def _wait_for_practice_refresh(page, before):
    page.wait_for_function(f'{PLANS_FETCHED} > {before}', timeout=15_000)
    page.wait_for_timeout(800)


def _assert_in_place(page, plan, scroll_before):
    assert plan.locator('.accordion-collapse.show').count() == 1, 'the open plan collapsed'
    scroll_after = page.evaluate(SCROLL)
    assert abs(scroll_after - scroll_before) <= TOLERANCE_PX, (
        f'the page moved from {scroll_before}px to {scroll_after}px')


@VIEWPORTS
def test_ticking_a_setup_task_keeps_the_plan_open_and_in_place(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    plan = _open_plan(page, coachboard_url)
    task = plan.locator('.task-checkbox').first
    _bring_to_middle(page, task)
    scroll_before = page.evaluate(SCROLL)
    # Desktop pages are shorter; what matters there is that the plan stays open.
    assert scroll_before > (300 if page.cb_phone else 100), f'the plan is not scrolled into ({scroll_before}px)'
    was_checked = task.is_checked()
    fetched = page.evaluate(PLANS_FETCHED)

    _tap(page, task)
    _wait_for_practice_refresh(page, fetched)

    _assert_in_place(page, plan, scroll_before)
    assert plan.locator('.task-checkbox').first.is_checked() is (not was_checked)
    assert page.cb_errors == []


@VIEWPORTS
def test_another_coachs_change_keeps_the_plan_and_open_editor_in_place(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    plan = _open_plan(page, coachboard_url)
    plan.get_by_role('button', name='Edit plan details').click()
    editor = plan.locator('.practice-plan-details-form')
    expect(editor).to_be_visible()
    page.wait_for_timeout(500)
    _bring_to_middle(page, plan.locator('input[name="task_text"]'))
    scroll_before = page.evaluate(SCROLL)
    assert scroll_before > (300 if page.cb_phone else 100), scroll_before
    fetched = page.evaluate(PLANS_FETCHED)

    response = page.request.post(f'{coachboard_url}/add_note/team_notes',
                                 form={'note_text': f'Another device {uuid.uuid4().hex[:4]}'})
    assert response.status in (200, 302)
    _wait_for_practice_refresh(page, fetched)

    _assert_in_place(page, plan, scroll_before)
    expect(plan.locator('.practice-plan-details-form')).to_be_visible()
    assert page.cb_errors == []


@VIEWPORTS
def test_plan_actions_still_work_after_a_refresh(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    plan = _open_plan(page, coachboard_url)
    fetched = page.evaluate(PLANS_FETCHED)
    response = page.request.post(f'{coachboard_url}/add_note/team_notes',
                                 form={'note_text': f'Refresh {uuid.uuid4().hex[:4]}'})
    assert response.status in (200, 302)
    _wait_for_practice_refresh(page, fetched)

    plan.get_by_role('button', name='Edit plan details').click()
    expect(plan.locator('.practice-plan-details-form')).to_be_visible()
    plan.get_by_role('button', name='Reuse on another date').click()
    expect(page.locator('#reusePracticeModal')).to_be_visible()
    assert page.cb_errors == []
