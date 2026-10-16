"""Home fits every phone, tablet and desktop width, portrait and landscape.

An iPad Pro 13 is 1032px wide in portrait and 1376px in landscape. Home must
never be wider than the screen: every card fits inside it, the navigation
links and the account menu stay whole, and only a long team name or instance
label gives way (with an ellipsis). Tablets (768-1199px) stack Next Game over
Team Alerts and use two columns below.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

import cdn_assets  # noqa: E402
from live_field_markers import login  # noqa: E402


ICON_FONTS = 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/**'

# (width, height): phones, iPads (mini/Air/Pro 11, Pro 13) in both orientations, desktops.
SIZES = [
    (390, 844), (430, 932),
    (768, 1024), (1024, 768), (1024, 1366), (1366, 1024),
    (1032, 1376), (1376, 1032),
    (1280, 800), (1440, 900),
]

# `vw` is the device width the context was opened with. Not window.innerWidth:
# with mobile emulation (phones, iPads) Chrome widens the layout viewport to
# fit overflowing content, so innerWidth grows with the very overflow being
# looked for.
MEASURE = r"""async (vw) => {
  await document.fonts.ready;
  const shown = el => el && el.getClientRects().length > 0;
  const box = el => { const r = el.getBoundingClientRect(); return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width}; };
  const outside = el => { const r = el.getBoundingClientRect(); return r.left < -0.5 || r.right > vw + 0.5; };
  const cards = [...document.querySelectorAll('.cb-home-dashboard .cb-home-card, .cb-home-dashboard .cb-home-quick')].filter(shown);
  const nav = [...document.querySelectorAll('.coach-primary-nav .cb-nav-link, .coach-primary-nav .cb-nav-more')].filter(shown);
  const account = [...document.querySelectorAll('#userMenuDesktop, a[href="#userOffcanvas"]')].find(shown);
  const grid = sel => { const el = document.querySelector(sel); return el ? getComputedStyle(el).gridTemplateColumns.split(' ').length : 0; };
  return {
    vw,
    scrollWidth: document.documentElement.scrollWidth,
    cards: cards.length,
    cardsOutside: cards.filter(outside).map(c => c.querySelector('.cb-home-eyebrow, strong')?.textContent.trim()),
    navOutside: nav.filter(outside).map(l => l.textContent.trim()),
    navClipped: nav.filter(l => l.scrollWidth > l.clientWidth + 1).map(l => l.textContent.trim()),
    account: account ? box(account) : null,
    nextGame: box(document.querySelector('.cb-home-grid-top > :first-child')),
    alerts: box(document.querySelector('.cb-home-grid-top > :nth-child(2)')),
    columns: {top: grid('.cb-home-grid-top'), three: grid('.cb-home-grid-three'), quick: grid('.cb-home-quick-grid')},
  };
}"""

# A team name and an instance label far longer than any real one.
LONG_NAMES = r"""() => {
  document.querySelector('.navbar-brand-text').textContent = 'Southern Indiana Bulls 10U Gold Elite Travel Prospects';
  const brand = document.querySelector('.navbar-brand');
  if (!brand.querySelector('[data-coachboard-instance-label]')) {
    const label = document.createElement('span');
    label.className = 'badge rounded-pill text-bg-warning text-dark border border-dark ms-2';
    label.setAttribute('data-coachboard-instance-label', '');
    label.innerHTML = '<i class="bi bi-cone-striped me-1"></i>CoachBoard Sandbox - Disposable Test Data';
    brand.appendChild(label);
  }
}"""


def _serve_icon_fonts(context):
    fonts = cdn_assets.vendor_dir() / 'fonts'

    def fulfill(route, request):
        path = fonts / request.url.split('/')[-1].split('?')[0]
        if not path.is_file():
            return route.abort()
        route.fulfill(status=200, body=path.read_bytes(),
                      content_type='font/woff2' if path.suffix == '.woff2' else 'font/woff')

    context.route(ICON_FONTS, fulfill)


@pytest.fixture
def home(browser, coachboard_url):
    contexts = []

    def open_home(size):
        cdn_assets.require_vendored_assets()
        width, height = size
        tablet_or_phone = width < 1100 or height > width
        context = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=2,
                                      is_mobile=tablet_or_phone, has_touch=tablet_or_phone)
        contexts.append(context)
        cdn_assets.install(context)
        _serve_icon_fonts(context)
        page = context.new_page()
        login(page, coachboard_url)
        page.goto(f'{coachboard_url}/')
        page.locator('.cb-home-dashboard .cb-home-quick').first.wait_for(timeout=20_000)
        return page

    yield open_home
    for context in contexts:
        context.close()


def _assert_fits(m):
    assert m['scrollWidth'] <= m['vw'], m
    assert m['cards'] >= 9 and m['cardsOutside'] == [], m
    assert m['navOutside'] == [] and m['navClipped'] == [], m
    assert m['account'] and m['account']['left'] >= 0 and m['account']['right'] <= m['vw'] + 0.5, m


@pytest.mark.parametrize('size', SIZES, ids=lambda s: f'{s[0]}x{s[1]}')
def test_home_fits_the_screen(home, size):
    page = home(size)
    m = page.evaluate(MEASURE, page.viewport_size['width'])
    _assert_fits(m)

    width = size[0]
    if 768 <= width < 1200:
        # Tablet: Next Game full width, Team Alerts beneath it, then two columns.
        assert m['columns'] == {'top': 1, 'three': 2, 'quick': 2}, m
        assert m['alerts']['top'] >= m['nextGame']['bottom'], m
        assert abs(m['alerts']['width'] - m['nextGame']['width']) < 1, m
    elif width >= 1200:
        # Desktop: unchanged -- Team Alerts beside Next Game, three and four columns.
        assert m['columns'] == {'top': 2, 'three': 3, 'quick': 4}, m
        assert m['alerts']['left'] >= m['nextGame']['right'], m
    else:
        assert m['columns']['top'] == 1 and m['columns']['three'] == 1, m


@pytest.mark.parametrize('size', [(1032, 1376), (1376, 1032), (1024, 768), (1280, 800), (1366, 1024)],
                         ids=lambda s: f'{s[0]}x{s[1]}')
def test_a_long_team_name_and_label_give_way_not_the_page(home, size):
    page = home(size)
    page.evaluate(LONG_NAMES)
    m = page.evaluate(MEASURE, page.viewport_size['width'])
    _assert_fits(m)
    brand = page.evaluate("""() => {
      const text = document.querySelector('.navbar-brand-text');
      return {truncated: text.scrollWidth > text.clientWidth, title: text.title};
    }""")
    assert brand['truncated'], brand
    # Every navigation link is still there and tappable.
    page.locator('.coach-primary-nav .cb-nav-more').click()
    assert page.locator('.coach-primary-nav .dropdown-menu.show').is_visible()
