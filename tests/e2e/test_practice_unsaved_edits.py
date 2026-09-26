"""A Practice refresh never wipes what a coach has typed but not saved.

Every practice change -- and every other coach's change anywhere -- emits
`data_updated`, and main.js refreshes the visible Practice tab by rebuilding
the plan list. The rebuild used to throw away anything typed into an open
plan's editor, attendance or setup-task box. Unsaved values are now carried
over; untouched fields still take the refreshed values.
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
PLANS_FETCHED = "performance.getEntriesByType('resource').filter(e => e.name.includes('/api/practice_plans')).length"


@pytest.fixture
def practice(browser, coachboard_url):
    """Logged-in pages plus practice plans this test owns (deleted afterwards)."""
    contexts, plan_ids = [], []

    def open_page(viewport=DESKTOP):
        cdn_assets.require_vendored_assets()
        mobile = viewport is PHONE
        context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
        cdn_assets.install(context)
        contexts.append(context)
        page = context.new_page()
        page.cb_errors = []
        page.on('pageerror', lambda error: page.cb_errors.append(str(error)))
        page.goto(f'{coachboard_url}/login')
        page.get_by_label('Username or email').fill(TEST_USERNAME)
        page.locator('#password').fill(TEST_PASSWORD)
        page.get_by_role('button', name='Sign In').click()
        page.wait_for_load_state('load')
        return page

    api = open_page()

    def new_plan(title, date, **fields):
        response = api.request.post(f'{coachboard_url}/add_practice_plan', form={
            'plan_date': date, 'general_notes': title, **fields})
        assert response.status in (200, 302)
        plans = api.request.get(f'{coachboard_url}/api/practice_plans').json()
        plan_id = next(p['id'] for p in plans if p['general_notes'] == title)
        plan_ids.append(plan_id)
        return plan_id

    yield open_page, new_plan, api
    for plan_id in plan_ids:
        api.request.get(f'{coachboard_url}/delete_practice_plan/{plan_id}')
    for context in contexts:
        context.close()


def show_practice(page, base_url):
    page.goto(f'{base_url}/#practice_plan')
    page.wait_for_load_state('load')
    expect(page.locator('#practicePlanAccordion .cb-practice-plan').first).to_be_visible(timeout=15_000)


def open_editor(page, plan_id):
    plan = page.locator(f'#plan-{plan_id}').locator('xpath=..')
    if not page.locator(f'#plan-{plan_id}').is_visible():
        page.locator(f'[data-bs-target="#plan-{plan_id}"]').first.click()
        expect(page.locator(f'#plan-{plan_id}')).to_be_visible()
    page.locator(f'#plan-{plan_id} [data-bs-target="#edit-plan-{plan_id}"]').click()
    editor = page.locator(f'#edit-plan-{plan_id} form')
    expect(editor).to_be_visible()
    page.wait_for_timeout(400)
    return plan, editor


def refresh_from_elsewhere(page, api, base_url, times=1):
    """Another coach's change: emits data_updated and rebuilds the plan list."""
    for _ in range(times):
        before = page.evaluate(PLANS_FETCHED)
        response = api.request.post(f'{base_url}/add_note/team_notes',
                                    form={'note_text': f'Elsewhere {uuid.uuid4().hex[:6]}'})
        assert response.status in (200, 302)
        page.wait_for_function(f'{PLANS_FETCHED} > {before}', timeout=15_000)
        page.wait_for_timeout(600)


def field(page, plan_id, name):
    return page.locator(f'#plan-{plan_id} [name="{name}"]')


def test_typed_text_in_every_practice_field_survives_a_refresh(practice, coachboard_url):
    open_page, new_plan, api = practice
    plan_a = new_plan(f'Plan A {uuid.uuid4().hex[:4]}', '2031-05-01', emphasis='Saved priorities A')
    plan_b = new_plan(f'Plan B {uuid.uuid4().hex[:4]}', '2031-05-02', emphasis='Saved priorities B')
    page = open_page()
    show_practice(page, coachboard_url)

    # Unsaved work in plan B's editor ...
    open_editor(page, plan_b)
    field(page, plan_b, 'hitting').fill('B: soft toss, front toss')
    # ... and in every kind of field in plan A.
    open_editor(page, plan_a)
    typed_a = {
        'general_notes': 'A: renamed but unsaved',
        'warm_up': 'A: band work, long toss',
        'task_text': 'A: bring the L-screen',
    }
    for name, text in typed_a.items():
        field(page, plan_a, name).fill(text)
    absent = page.locator(f'#plan-{plan_a} input[name="absent_players"]').first
    absent_was = absent.is_checked()
    absent.set_checked(not absent_was)
    # The coach is mid-sentence in Top priorities, caret in the middle.
    emphasis = field(page, plan_a, 'emphasis')
    emphasis.fill('A: first-step quickness')
    emphasis.focus()
    emphasis.evaluate('el => el.setSelectionRange(8, 8)')

    refresh_from_elsewhere(page, api, coachboard_url)

    for name, text in typed_a.items():
        expect(field(page, plan_a, name)).to_have_value(text)
    expect(field(page, plan_a, 'emphasis')).to_have_value('A: first-step quickness')
    assert page.locator(f'#plan-{plan_a} input[name="absent_players"]').first.is_checked() is (not absent_was)
    expect(field(page, plan_b, 'hitting')).to_have_value('B: soft toss, front toss')
    # Nothing leaked between the two plans.
    expect(field(page, plan_b, 'emphasis')).to_have_value('Saved priorities B')
    expect(field(page, plan_b, 'warm_up')).to_have_value('')
    # Focus and caret stay where the coach was typing.
    focus = page.evaluate("""() => {
      const el = document.activeElement;
      return {name: el?.name, plan: el?.form?.getAttribute('action'), start: el?.selectionStart, end: el?.selectionEnd};
    }""")
    assert focus == {'name': 'emphasis', 'plan': f'/edit_practice_plan/{plan_a}', 'start': 8, 'end': 8}, focus
    # Typing carries on from the caret.
    page.keyboard.type('+')
    expect(field(page, plan_a, 'emphasis')).to_have_value('A: first+-step quickness')
    assert page.cb_errors == []


def test_untouched_fields_still_take_remote_changes(practice, coachboard_url):
    open_page, new_plan, api = practice
    title = f'Remote Plan {uuid.uuid4().hex[:4]}'
    plan = new_plan(title, '2031-05-03', emphasis='Old priorities', hitting='Old hitting')
    page = open_page()
    show_practice(page, coachboard_url)
    open_editor(page, plan)
    field(page, plan, 'warm_up').fill('Local warm-up, not saved')

    # Another coach saves new hitting and priorities for this plan.
    response = api.request.post(f'{coachboard_url}/edit_practice_plan/{plan}', form={
        'plan_date': '2031-05-03', 'general_notes': title, 'emphasis': 'New priorities',
        'warm_up': '', 'infield_outfield': '', 'hitting': 'New hitting', 'pitching_catching': ''})
    assert response.status in (200, 302)
    page.wait_for_timeout(1500)

    expect(field(page, plan, 'hitting')).to_have_value('New hitting')
    expect(field(page, plan, 'emphasis')).to_have_value('New priorities')
    expect(field(page, plan, 'warm_up')).to_have_value('Local warm-up, not saved')


def test_after_saving_later_updates_behave_normally(practice, coachboard_url):
    open_page, new_plan, api = practice
    title = f'Save Plan {uuid.uuid4().hex[:4]}'
    plan = new_plan(title, '2031-05-04')
    page = open_page()
    show_practice(page, coachboard_url)
    open_editor(page, plan)
    field(page, plan, 'hitting').fill('Saved hitting')
    with page.expect_navigation():
        page.locator(f'#edit-plan-{plan} button[type="submit"]').click()
    show_practice(page, coachboard_url)
    saved = next(p for p in api.request.get(f'{coachboard_url}/api/practice_plans').json() if p['id'] == plan)
    assert saved['hitting'] == 'Saved hitting'

    # Saved now, so a later remote change to that field shows up.
    open_editor(page, plan)
    expect(field(page, plan, 'hitting')).to_have_value('Saved hitting')
    response = api.request.post(f'{coachboard_url}/edit_practice_plan/{plan}', form={
        'plan_date': '2031-05-04', 'general_notes': title, 'emphasis': '', 'warm_up': '',
        'infield_outfield': '', 'hitting': 'Changed by another coach', 'pitching_catching': ''})
    assert response.status in (200, 302)
    expect(field(page, plan, 'hitting')).to_have_value('Changed by another coach', timeout=10_000)


def test_repeated_refreshes_keep_one_copy_and_the_typed_text(practice, coachboard_url):
    open_page, new_plan, api = practice
    plan = new_plan(f'Repeat Plan {uuid.uuid4().hex[:4]}', '2031-05-05')
    page = open_page(PHONE)
    show_practice(page, coachboard_url)
    plans_before = page.locator('#practicePlanAccordion .cb-practice-plan').count()
    open_editor(page, plan)
    field(page, plan, 'pitching_catching').fill('Bullpens: 25 pitches each')

    refresh_from_elsewhere(page, api, coachboard_url, times=3)

    expect(field(page, plan, 'pitching_catching')).to_have_value('Bullpens: 25 pitches each')
    assert page.locator('#practicePlanAccordion .cb-practice-plan').count() == plans_before
    assert page.locator(f'#edit-plan-{plan} form').count() == 1
    # Buttons in the rebuilt list still work exactly once.
    page.locator(f'#plan-{plan} .reuse-practice-btn').click()
    expect(page.locator('#reusePracticeModal')).to_be_visible()
    assert page.locator('.modal-backdrop').count() == 1
    assert page.cb_errors == []
