"""Small UI polish: one Coach Notes header, one Add Game, centered phone buttons.

* Coach Notes carried a CSS-drawn title and subtitle on top of the standard
  CoachBoard tab intro, so the page read "Coach Notes / COACHBOARD / Coach
  Notes" with two subtitles.
* Game Day offered Add Game twice -- in the page header and again beside the
  Schedule heading -- both opening the same modal.
* On phones the Defensive Templates buttons are given a 40-42px minimum height
  as flex items, which lays them out as blocks with the label at the top.
"""

import datetime
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
VIEWPORTS = pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])


@pytest.fixture
def make_page(browser, coachboard_url):
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
        page.goto(f'{coachboard_url}/login')
        page.get_by_label('Username or email').fill(TEST_USERNAME)
        page.locator('#password').fill(TEST_PASSWORD)
        page.get_by_role('button', name='Sign In').click()
        page.wait_for_load_state('load')
        return page

    yield _make
    for context in contexts:
        context.close()


# --- Coach Notes ---------------------------------------------------------------

#: Every piece of text the pane renders, including CSS generated content.
RENDERED_TEXT = """pane => {
  const out = [];
  const shown = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  for (const el of [pane, ...pane.querySelectorAll('*')]) {
    if (!shown(el)) continue;
    for (const pseudo of ['::before', '::after']) {
      const content = getComputedStyle(el, pseudo).content;
      if (content && content !== 'none' && content !== 'normal' && content !== '""') {
        out.push(content.replace(/^"|"$/g, ''));
      }
    }
    for (const node of el.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) out.push(node.textContent.trim());
    }
  }
  return out;
}"""


@VIEWPORTS
def test_coach_notes_has_one_page_header(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    page.goto(f'{coachboard_url}/#collaboration')
    pane = page.locator('#collaboration')
    expect(pane.locator('#team-notes-container')).to_be_visible(timeout=15_000)
    page.wait_for_timeout(500)

    texts = pane.evaluate(RENDERED_TEXT)
    assert texts.count('Coach Notes') == 1, texts[:8]

    # The one header left is the standard CoachBoard tab intro.
    intro = pane.locator(':scope > .cb-tab-intro')
    expect(intro).to_be_visible()
    expect(intro.locator('h1')).to_have_text('Coach Notes')
    expect(intro.locator('.cb-kicker')).to_have_text('CoachBoard')
    # ...and it sits above the notes, not below another title.
    intro_top = intro.bounding_box()['y']
    first_card = pane.locator('.card').first.bounding_box()['y']
    assert intro_top < first_card
    assert page.cb_errors == []


# --- Game Day: Add Game ----------------------------------------------------------

def _visible_add_game(page):
    return page.locator('button:visible, a:visible').filter(has_text='Add Game')


@VIEWPORTS
def test_game_day_offers_one_add_game_action(make_page, coachboard_url, viewport):
    page = make_page(viewport)
    page.goto(f'{coachboard_url}/game-day')
    expect(page.locator('.gd-schedule-head')).to_be_attached(timeout=15_000)
    page.wait_for_timeout(500)

    add = _visible_add_game(page)
    assert add.count() == 1, [add.nth(i).evaluate('e => e.outerHTML.slice(0, 120)') for i in range(add.count())]
    # The one kept is the header's primary action, visible without scrolling.
    assert add.evaluate('e => !!e.closest(".gd-hero")')
    box = add.bounding_box()
    assert box['y'] + box['height'] <= page.viewport_size['height']

    # The Schedule section still has its heading.
    expect(page.locator('.gd-schedule-head .gd-section-title')).to_have_text('Schedule')

    add.click()
    modal = page.locator('#game-day-add-modal')
    expect(modal).to_be_visible()
    assert page.locator('#gd-add-date').input_value()
    expect(page.locator('#gd-add-opponent')).to_be_visible()
    assert page.cb_errors == []


def test_game_day_with_upcoming_games_still_offers_one_add_game(make_page, coachboard_url):
    """With games coming up the Schedule heading is built from that section,
    a separate path from the empty schedule the seed data shows."""
    page = make_page(DESKTOP)
    page.goto(f'{coachboard_url}/game-day')
    add = _visible_add_game(page)
    expect(add).to_have_count(1, timeout=15_000)

    # Schedule a game through the kept Add Game workflow.
    opponent = f'Polish {uuid.uuid4().hex[:6]}'
    add.click()
    expect(page.locator('#game-day-add-modal')).to_be_visible()
    page.locator('#gd-add-date').fill((datetime.date.today() + datetime.timedelta(days=21)).isoformat())
    page.locator('#gd-add-opponent').fill(opponent)
    page.locator('#game-day-add-modal [type=submit]').click()
    # Saving opens the new game.
    page.wait_for_url('**/game/*', timeout=15_000)
    game_id = page.url.rstrip('/').rsplit('/', 1)[1]
    try:
        page.goto(f'{coachboard_url}/game-day')
        expect(page.locator('.gd-up-row').filter(has_text=opponent)).to_be_visible(timeout=15_000)
        page.wait_for_timeout(500)
        expect(page.locator('.gd-schedule-head .gd-section-title')).to_have_text('Schedule')
        assert _visible_add_game(page).count() == 1
        assert page.cb_errors == []
    finally:
        response = page.request.post(f'{coachboard_url}/game-day/{game_id}/delete',
                                     headers={'Accept': 'application/json'})
        assert response.ok, response.status


@pytest.fixture(scope='module')
def empty_team_coach(browser, coachboard_url):
    """A head coach on a brand-new team with no games, removed afterwards."""
    tag = uuid.uuid4().hex[:6]
    team_name, username, password = f'Empty Team {tag}', f'empty-coach-{tag}', 'EmptyCoach123!'
    context = browser.new_context()
    cdn_assets.install(context)
    admin = context.new_page()
    admin.goto(f'{coachboard_url}/login')
    admin.get_by_label('Username or email').fill(TEST_USERNAME)
    admin.locator('#password').fill(TEST_PASSWORD)
    admin.get_by_role('button', name='Sign In').click()
    admin.wait_for_load_state('load')
    admin.request.post(f'{coachboard_url}/admin/create_team', form={'team_name': team_name})
    admin.goto(f'{coachboard_url}/admin/teams')
    team_item = admin.locator('li.list-group-item').filter(has_text=team_name)
    code = team_item.locator('small').first.inner_text().strip()
    team_id = team_item.locator('button[data-bs-target^="#deleteTeamModal-"]').get_attribute('data-bs-target').rsplit('-', 1)[1]

    register = browser.new_context()
    response = register.request.post(f'{coachboard_url}/register', form={
        'username': username, 'email': f'{username}@example.test', 'full_name': 'Empty Team Coach',
        'password': password, 'registration_code': code,
    })
    registered = response.status == 200 and team_name in response.text()
    register.close()
    assert registered

    yield username, password

    admin.request.post(f'{coachboard_url}/admin/delete_user/{username}')
    admin.request.get(f'{coachboard_url}/admin/delete_team/{team_id}')
    context.close()


@VIEWPORTS
def test_game_day_with_no_games_offers_one_add_game(browser, coachboard_url, empty_team_coach, viewport):
    username, password = empty_team_coach
    mobile = viewport is PHONE
    context = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile)
    cdn_assets.install(context)
    try:
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'{coachboard_url}/login')
        page.get_by_label('Username or email').fill(username)
        page.locator('#password').fill(password)
        page.get_by_role('button', name='Sign In').click()
        page.wait_for_load_state('load')
        page.goto(f'{coachboard_url}/game-day')

        empty = page.locator('.gd-empty')
        expect(empty).to_be_visible(timeout=15_000)
        expect(empty).to_contain_text('No games are scheduled.')
        page.wait_for_timeout(500)

        add = _visible_add_game(page)
        assert add.count() == 1, [add.nth(i).evaluate('e => e.outerHTML.slice(0, 120)') for i in range(add.count())]
        assert add.evaluate('e => !!e.closest(".gd-hero")')

        add.click()
        expect(page.locator('#game-day-add-modal')).to_be_visible()
        assert page.locator('#gd-add-date').input_value()
        assert errors == []
    finally:
        context.close()


# --- Phone button labels ------------------------------------------------------------

#: Space above and below the button's label, from its layout boxes.
LABEL_GAPS = """el => {
  const box = el.getBoundingClientRect();
  const range = document.createRange();
  range.selectNodeContents(el);
  const lines = [...range.getClientRects()].filter(r => r.height > 0);
  const top = Math.min(...lines.map(r => r.top));
  const bottom = Math.max(...lines.map(r => r.bottom));
  return {above: top - box.top, below: box.bottom - bottom, height: box.height, width: box.width};
}"""

TEMPLATE_BUTTONS = {
    'New Starting Defense': '/starting-defense-template/new',
    'New Rotation Template': '/rotation-template/new',
}


def _template_button(page, coachboard_url, name):
    page.goto(f'{coachboard_url}/#rotations')
    button = page.locator('#rotations a.btn').filter(has_text=name).first
    expect(button).to_be_visible(timeout=15_000)
    page.wait_for_timeout(400)
    return button


@pytest.mark.parametrize('name', list(TEMPLATE_BUTTONS))
def test_phone_template_buttons_center_their_label(make_page, coachboard_url, name):
    page = make_page(PHONE)
    button = _template_button(page, coachboard_url, name)
    gaps = button.evaluate(LABEL_GAPS)
    assert abs(gaps['above'] - gaps['below']) <= 2, gaps
    # Still a comfortable tap target.
    assert gaps['height'] >= 40 and gaps['width'] >= 120, gaps

    button.scroll_into_view_if_needed()
    box = button.bounding_box()
    page.touchscreen.tap(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    page.wait_for_url(f'**{TEMPLATE_BUTTONS[name]}', timeout=15_000)
    assert page.cb_errors == []


@pytest.mark.parametrize('name', list(TEMPLATE_BUTTONS))
def test_desktop_template_buttons_keep_their_size(make_page, coachboard_url, name):
    page = make_page(DESKTOP)
    gaps = _template_button(page, coachboard_url, name).evaluate(LABEL_GAPS)
    assert abs(gaps['above'] - gaps['below']) <= 2, gaps
    assert gaps['height'] < 36, gaps   # the compact btn-sm, no phone minimum
