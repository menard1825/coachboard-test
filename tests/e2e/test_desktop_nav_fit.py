"""The desktop header fits on one line at every desktop width.

Development and Practice join the header at 1200px, where the compact
992-1199px rules stop applying. Before this was fixed, widths up to about
1360px wrapped Game Day onto two lines, pushed the account menu past the right
edge and gave every page a horizontal scrollbar.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

import cdn_assets
from live_field_markers import login


ICON_FONTS = 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/**'

HEADER = r"""async () => {
  await document.fonts.ready;
  const visible = el => el && el.getClientRects().length > 0;
  const oneLine = el => [...el.childNodes].every(node => {
    if (node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) return true;
    const range = document.createRange();
    range.selectNodeContents(node);
    const tops = [...range.getClientRects()].filter(r => r.width > 1).map(r => Math.round(r.top));
    return new Set(tops).size <= 1;
  });
  const links = [...document.querySelectorAll('.coach-primary-nav .cb-nav-link, .coach-primary-nav .cb-nav-more')]
    .filter(visible);
  const account = document.querySelector('#userMenuDesktop');
  const box = visible(account) ? account.getBoundingClientRect() : null;
  return {
    viewport: document.documentElement.clientWidth,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    labels: links.map(link => link.textContent.trim()),
    wrapped: links.filter(link => !oneLine(link)).map(link => link.textContent.trim()),
    account: box && {left: box.left, right: box.right, clipped: account.scrollWidth > account.clientWidth,
                     text: account.innerText.trim()},
    iconFont: document.fonts.check('16px "bootstrap-icons"'),
  };
}"""


def _serve_icon_fonts(context):
    """Real glyph widths matter here; serve the icon font when it is vendored."""
    fonts = cdn_assets.vendor_dir() / 'fonts'

    def fulfill(route, request):
        name = request.url.split('/')[-1].split('?')[0]
        path = fonts / name
        if not path.is_file():
            return route.abort()
        route.fulfill(status=200, body=path.read_bytes(),
                      content_type='font/woff2' if name.endswith('.woff2') else 'font/woff')

    context.route(ICON_FONTS, fulfill)


def _header(browser, coachboard_url, width, path='/game-day'):
    cdn_assets.require_vendored_assets()
    context = browser.new_context(viewport={'width': width, 'height': 900})
    try:
        cdn_assets.install(context)
        _serve_icon_fonts(context)
        page = context.new_page()
        login(page, coachboard_url)
        page.goto(f'{coachboard_url}{path}')
        page.wait_for_load_state('load')
        header = page.evaluate(HEADER)
        if (cdn_assets.vendor_dir() / 'fonts').is_dir():
            assert header['iconFont'], 'the vendored icon font did not load'
        return header
    finally:
        context.close()


@pytest.mark.parametrize('width', [1200, 1280, 1360, 1366, 1440])
def test_desktop_header_fits_on_one_line(browser, coachboard_url, width):
    header = _header(browser, coachboard_url, width)

    assert header['overflow'] == 0, header
    assert header['labels'] == ['Home', 'Game Day', 'Roster', 'Development', 'Practice', 'Pitching', 'More']
    assert header['wrapped'] == [], header
    account = header['account']
    assert account and account['left'] >= 0 and account['right'] <= header['viewport'], header
    assert not account['clipped'], header


def test_only_the_tight_range_drops_the_greeting_words(browser, coachboard_url):
    assert _header(browser, coachboard_url, 1280)['account']['text'] == 'Playwright Coach'
    assert _header(browser, coachboard_url, 1366)['account']['text'] == 'Welcome, Playwright Coach!'


@pytest.mark.parametrize('width', [1024, 1180])
def test_tablet_landscape_header_is_unchanged(browser, coachboard_url, width):
    header = _header(browser, coachboard_url, width)

    assert header['overflow'] == 0, header
    assert header['labels'] == ['Home', 'Game Day', 'Roster', 'Pitching', 'More']
    assert header['wrapped'] == [], header
    assert header['account']['right'] - header['account']['left'] <= 48, header
