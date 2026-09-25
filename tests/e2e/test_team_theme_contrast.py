"""Team colors theme the app readably, keep Delete distinct, and leak no navy.

Each test sets the team's color through Team Settings, as a coach would, and
restores the seeded navy afterwards (the server is shared by the session).
"""

import os
import re

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import expect  # noqa: E402

import cdn_assets  # noqa: E402
from team_theme import LIGHT_SURFACE, primary_text_color  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
DESKTOP = {'width': 1440, 'height': 900}
PHONE = {'width': 390, 'height': 844}
SEEDED = '#102A66'
WHITE_FG = 'rgb(255, 255, 255)'
DARK_FG = 'rgb(23, 32, 51)'          # --cb-ink
DANGER = 'rgb(180, 35, 24)'          # --cb-danger

#: team color -> the foreground expected on it
TEAM_COLORS = {
    'navy': ('#102A66', WHITE_FG),
    'red': ('#B91C1C', WHITE_FG),
    'green': ('#15803D', WHITE_FG),
    'gold': ('#C9A227', DARK_FG),
    'yellow': ('#FFD600', DARK_FG),
    'white': ('#FFFFFF', DARK_FG),
}

CONTRAST = """([fg, bg]) => {
  const parse = c => c.match(/[\\d.]+/g).slice(0, 3).map(Number);
  const lum = rgb => { const [r, g, b] = rgb.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const [a, b] = [lum(parse(fg)), lum(parse(bg))].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}"""


def _rgb(hex_color):
    h = hex_color.lstrip('#')
    return 'rgb({}, {}, {})'.format(*(int(h[i:i + 2], 16) for i in (0, 2, 4)))


@pytest.fixture
def make_page(browser, coachboard_url):
    contexts = []

    def _make(viewport=DESKTOP, color=None):
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
        if color:
            _set_team_color(page, coachboard_url, color)
        return page

    yield _make
    if contexts:
        _set_team_color(contexts[0].pages[0], coachboard_url, SEEDED)
    for context in contexts:
        context.close()


def _set_team_color(page, base_url, color):
    response = page.request.post(f'{base_url}/admin/settings/update',
                                 form={'primary_color': color}, max_redirects=0)
    assert response.status == 302, response.status


def _style(locator, prop):
    return locator.evaluate(f'(el, p) => getComputedStyle(el).getPropertyValue(p)', prop)


def _contrast(page, fg, bg):
    return page.evaluate(CONTRAST, [fg, bg])


# --- A/B: readable foreground on the team color ----------------------------

@pytest.mark.parametrize('name', list(TEAM_COLORS))
@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_header_and_main_buttons_use_a_readable_foreground(make_page, coachboard_url, name, viewport):
    color, foreground = TEAM_COLORS[name]
    page = make_page(viewport, color)
    page.goto(f'{coachboard_url}/')
    expect(page.locator('#overview-content-container .cb-home-dashboard')).to_be_visible(timeout=15_000)

    navbar = page.locator('nav.navbar').first
    assert _style(navbar, 'background-color') == _rgb(color)
    brand = page.locator('.navbar-brand-text').first
    assert _style(brand, 'color') == foreground
    assert _contrast(page, _style(brand, 'color'), _rgb(color)) >= 4.5

    if viewport is DESKTOP:
        link = page.locator('.coach-primary-nav .cb-nav-link').first
        link_color = _style(link, 'color')
        # Nav links are the foreground at reduced opacity, never white on a light team.
        assert _contrast(page, link_color, _rgb(color)) >= 3, (name, link_color)

    button = page.locator('#overview-content-container .btn-primary').first
    expect(button).to_be_visible()
    assert _style(button, 'background-color') == _rgb(color)
    assert _style(button, 'color') == foreground
    assert page.cb_errors == []


# --- C: destructive stays danger, apart from red branding --------------------

def _open_practice_delete(page, base_url):
    page.goto(f'{base_url}/')
    page.evaluate("() => { location.hash = '#practice_plan'; }")
    plan = page.locator('#practicePlanAccordion .cb-practice-plan').first
    expect(plan).to_be_visible(timeout=15_000)
    plan.locator('.cb-practice-plan-button').click()
    plan.get_by_role('button', name='Edit plan details').click()
    delete = plan.get_by_role('button', name='Delete plan')
    expect(delete).to_be_visible()
    return plan, delete


@pytest.mark.parametrize('name', ['navy', 'red'])
def test_delete_controls_keep_the_danger_color(make_page, coachboard_url, name):
    color, _ = TEAM_COLORS[name]
    page = make_page(DESKTOP, color)
    plan, delete = _open_practice_delete(page, coachboard_url)
    assert _style(delete, 'color') == DANGER
    save = plan.get_by_role('button', name='Save plan details')
    assert _style(save, 'background-color') == _rgb(color)

    delete.click()
    confirm = page.locator('#confirmDeleteModal .btn-danger').first
    expect(confirm).to_be_visible()
    confirm_bg = _style(confirm, 'background-color')
    confirm_fg = _style(confirm, 'color')
    if name == 'red':
        # A solid red Delete would look exactly like the team's main buttons.
        assert confirm_bg != _rgb(color), 'Delete looks like a red team primary button'
        assert confirm_fg == DANGER
    else:
        assert confirm_bg == DANGER
    assert page.cb_errors == []


def test_legacy_outline_danger_rule_does_not_follow_the_team_color(make_page, coachboard_url):
    """main.css styled .btn-outline-danger with the team color; before
    coachboard_ui.js marks <body> that rule is the one that applies."""
    page = make_page(DESKTOP, TEAM_COLORS['green'][0])
    page.goto(f'{coachboard_url}/')
    color = page.evaluate("""() => {
      document.body.classList.remove('cb-ui');
      const b = Object.assign(document.createElement('button'), {className: 'btn btn-outline-danger', textContent: 'Delete'});
      document.body.appendChild(b);
      return getComputedStyle(b).color;
    }""")
    assert color == DANGER


# --- D: no hard-coded navy where the team color belongs -----------------------

NAVY_OUTSIDE_FALLBACK = re.compile(r'#102a66|rgba?\(\s*16\s*,\s*42\s*,\s*102', re.I)
FALLBACK = re.compile(r'var\(--[\w-]+\s*,\s*(var\(--[\w-]+\s*,\s*)?#102a66\s*\)+', re.I)


def _navy_leaks(page):
    css = page.evaluate("() => [...document.querySelectorAll('style')].map(s => s.textContent).join('\\n')")
    return NAVY_OUTSIDE_FALLBACK.findall(FALLBACK.sub('', css))


def test_game_day_primary_action_follows_the_team_color(make_page, coachboard_url):
    color, foreground = TEAM_COLORS['green']
    page = make_page(DESKTOP, color)
    page.goto(f'{coachboard_url}/game-day')
    button = page.locator('.gd-primary').first
    expect(button).to_be_visible(timeout=15_000)
    assert _style(button, 'background-color') == _rgb(color)
    assert _style(button, 'color') == foreground
    assert _navy_leaks(page) == []


def test_white_team_game_day_action_is_not_forced_to_navy(make_page, coachboard_url):
    color, foreground = TEAM_COLORS['white']
    page = make_page(PHONE, color)
    page.goto(f'{coachboard_url}/game-day')
    button = page.locator('.gd-primary').first
    expect(button).to_be_visible(timeout=15_000)
    page.wait_for_timeout(800)
    assert _style(button, 'background-color') != _rgb('#102A66')
    assert _style(button, 'color') == foreground
    assert page.cb_errors == []


def test_live_game_page_styles_leak_no_navy(make_page, coachboard_url):
    page = make_page(DESKTOP, TEAM_COLORS['green'][0])
    page.goto(f'{coachboard_url}/game-day')
    href = page.locator('a[href^="/game/"]').first.get_attribute('href')
    page.goto(f'{coachboard_url}{href}')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1500)
    assert _navy_leaks(page) == []


# --- E: the team color as text on light surfaces ------------------------------

#: The element's text or border color and the background behind it, both
#: resolved to rgb() by painting them on a canvas: computed colors can come
#: back as color(srgb ...) with alpha when the CSS uses color-mix().
RESOLVED = """([el, prop]) => {
  const ctx = Object.assign(document.createElement('canvas'), {width: 1, height: 1}).getContext('2d');
  const paint = colors => {
    ctx.clearRect(0, 0, 1, 1);
    for (const c of colors) { ctx.fillStyle = c; ctx.fillRect(0, 0, 1, 1); }
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return `rgb(${r}, ${g}, ${b})`;
  };
  const layers = [];
  for (let n = el; n; n = n.parentElement) layers.unshift(getComputedStyle(n).backgroundColor);
  const background = paint(['#fff', ...layers]);
  return [paint([background, getComputedStyle(el).getPropertyValue(prop)]), background];
}"""


def _on_its_background(page, locator, prop='color'):
    """(contrast, color) of the element's text or border against what is behind it."""
    color, background = page.evaluate(RESOLVED, [locator.element_handle(), prop])
    return _contrast(page, color, background), color


def _open_game(page, base_url):
    page.goto(f'{base_url}/game-day')
    href = page.locator('a[href^="/game/"]').first.get_attribute('href')
    page.goto(f'{base_url}{href}')
    page.wait_for_load_state('load')


def _team_colored_controls(page, base_url, viewport):
    """The controls reported as disappearing on a white team, by page."""
    page.goto(f'{base_url}/')
    link = page.locator('#overview-content-container .cb-home-text-link').first
    expect(link).to_be_visible(timeout=15_000)
    yield 'View Practice Plan link', link, ('color',)
    if viewport is PHONE:
        yield 'active phone nav', page.locator('#cb-global-mobile-nav .nav-link.active').first, ('color', 'border-top-color')

    _open_game(page, base_url)
    # Set Who's Out and Edit Lineup are hidden while the game is in pregame
    # planning; check the team-colored outline buttons the page is showing.
    # The selected inning is a filled button, not an outline one; it has its
    # own test below.
    outlines = page.locator(
        '.game-workspace-v2 .btn-outline-primary:not(.btn-check:checked + *):visible, #pde-apply:visible')
    expect(outlines.first).to_be_visible(timeout=15_000)
    page.wait_for_timeout(500)
    for index in range(min(outlines.count(), 4)):
        control = outlines.nth(index)
        yield control.inner_text().strip(), control, ('color', 'border-top-color')


@pytest.mark.parametrize('name', ['white', 'gold', 'yellow'])
@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_light_team_color_text_and_outlines_stay_readable(make_page, coachboard_url, name, viewport):
    color, _ = TEAM_COLORS[name]
    page = make_page(viewport, color)
    unreadable = []
    for control, locator, props in _team_colored_controls(page, coachboard_url, viewport):
        text, text_color = _on_its_background(page, locator)
        if text < 4.5:
            unreadable.append((control, 'text', text_color, round(text, 2)))
        if 'border-top-color' in props:
            edge, edge_color = _on_its_background(page, locator, 'border-top-color')
            # Outlines are a lighter tint of the text color, at 3:1 like any UI edge.
            if edge < 3:
                unreadable.append((control, 'edge', edge_color, round(edge, 2)))
    assert unreadable == []
    assert page.cb_errors == []


@pytest.mark.parametrize('name', ['navy', 'green', 'red'])
def test_dark_team_colors_are_used_as_is_for_text(make_page, coachboard_url, name):
    color, _ = TEAM_COLORS[name]
    assert primary_text_color(color) == color.lower()
    page = make_page(PHONE, color)
    changed = [(control, _style(locator, 'color'))
               for control, locator, _ in _team_colored_controls(page, coachboard_url, PHONE)
               if _style(locator, 'color') != _rgb(color)]
    assert changed == []


@pytest.mark.parametrize('name', list(TEAM_COLORS))
def test_outlined_team_controls_have_a_3_to_1_edge(make_page, coachboard_url, name):
    color, _ = TEAM_COLORS[name]
    page = make_page(DESKTOP, color)
    edges = {}
    for control, locator, props in _team_colored_controls(page, coachboard_url, DESKTOP):
        if 'border-top-color' in props:
            inside, edge = _on_its_background(page, locator, 'border-top-color')
            # The edge also meets the page background some buttons sit on.
            outside = _contrast(page, edge, _rgb(LIGHT_SURFACE))
            edges[control] = round(min(inside, outside), 2)
    assert edges and min(edges.values()) >= 3, edges


# --- Team Settings -----------------------------------------------------------------

def _pick(page, color):
    page.evaluate("""color => {
      const input = document.getElementById('primary_color');
      input.value = color;
      input.dispatchEvent(new Event('input', {bubbles: true}));
    }""", color)
    page.wait_for_timeout(700)


def test_team_settings_previews_the_foreground_and_warns(make_page, coachboard_url):
    page = make_page(DESKTOP, SEEDED)
    page.goto(f'{coachboard_url}/admin/settings')
    page.locator('a[href="#appearance-settings"], button[data-bs-target="#appearance-settings"]').first.click()
    preview = page.locator('#teamColorPreview')
    warning = page.locator('#teamColorWarning')
    expect(preview).to_be_visible()
    expect(warning).to_be_hidden()
    assert _style(preview, 'color') == WHITE_FG

    text_sample = page.locator('#teamColorTextPreview')
    expect(text_sample).to_be_visible()
    assert _style(text_sample, 'color') == _rgb(SEEDED)

    _pick(page, '#ffd600')
    expect(warning).to_be_visible()
    assert _style(preview, 'color') == DARK_FG
    assert _style(page.locator('.navbar-brand-text').first, 'color') == DARK_FG
    darker = primary_text_color('#ffd600')
    assert _style(text_sample, 'color') == _rgb(darker)
    expect(warning).to_contain_text(darker)

    _pick(page, '#102a66')
    expect(warning).to_be_hidden()
    assert _style(preview, 'color') == WHITE_FG
    assert _style(text_sample, 'color') == _rgb(SEEDED)
    assert page.cb_errors == []


# --- the selected inning in Set Defense ------------------------------------------

SELECTED_INNING = '#inning-btn-group .btn-check:checked + label'
UNSELECTED_INNING = '#inning-btn-group .btn-check:not(:checked) + label'

#: What is painted at the element (its own background over everything behind
#: it) and what is painted just behind it (its parent's stack).
FILLS = """el => {
  const ctx = Object.assign(document.createElement('canvas'), {width: 1, height: 1}).getContext('2d');
  const paint = els => {
    ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 1, 1);
    for (const n of els) { ctx.fillStyle = getComputedStyle(n).backgroundColor; ctx.fillRect(0, 0, 1, 1); }
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return `rgb(${r}, ${g}, ${b})`;
  };
  const stack = []; for (let n = el; n; n = n.parentElement) stack.unshift(n);
  return {fill: paint(stack), behind: paint(stack.slice(0, -1)), text: getComputedStyle(el).color};
}"""


@pytest.mark.parametrize('name', ['white', 'gold', 'yellow', 'navy', 'red'])
@pytest.mark.parametrize('viewport', [DESKTOP, PHONE], ids=['desktop', 'phone'])
def test_selected_inning_stands_out_for_any_team_color(make_page, coachboard_url, name, viewport):
    color, _ = TEAM_COLORS[name]
    page = make_page(viewport, color)
    _open_game(page, coachboard_url)
    selected = page.locator(SELECTED_INNING).first
    other = page.locator(UNSELECTED_INNING).first
    expect(selected).to_be_visible(timeout=15_000)
    page.wait_for_timeout(500)

    chosen = selected.evaluate(FILLS)
    plain = other.evaluate(FILLS)
    # The number on the selected inning is readable on its fill ...
    assert _contrast(page, chosen['text'], chosen['fill']) >= 4.5, (name, chosen)
    # ... and the selected inning stands apart from the card and from the
    # innings that are not selected, like any UI control at 3:1.
    assert _contrast(page, chosen['fill'], chosen['behind']) >= 3, (name, chosen)
    assert _contrast(page, chosen['fill'], plain['fill']) >= 3, (name, chosen, plain)

    if name in ('navy', 'red'):
        # Dark team colors are used as they are.
        assert chosen['fill'] == _rgb(color), (name, chosen)
        assert chosen['text'] == WHITE_FG, (name, chosen)
    assert page.cb_errors == []
