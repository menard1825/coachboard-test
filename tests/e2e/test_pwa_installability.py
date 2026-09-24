"""Chromium treats CoachBoard as an installable app.

Asks Chromium itself, through the DevTools protocol, for the parsed manifest
and for any reason it would refuse to install the app -- on the login page a
new coach lands on and on a signed-in page. CoachBoard has no service worker
and must not need one to be installable.
"""

import os

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

import cdn_assets  # noqa: E402


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
PHONE = {'viewport': {'width': 390, 'height': 844}, 'is_mobile': True, 'has_touch': True}


@pytest.fixture
def page(browser):
    cdn_assets.require_vendored_assets()
    context = browser.new_context(**PHONE)
    cdn_assets.install(context)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.cb_errors = errors
    yield page
    context.close()


def _check(page, coachboard_url):
    cdp = page.context.new_cdp_session(page)
    manifest = cdp.send('Page.getAppManifest')
    assert manifest['url'] == f'{coachboard_url}/manifest.json'
    assert manifest['errors'] == [], manifest['errors']
    # Nothing stands in the way of Chromium's install prompt ...
    assert cdp.send('Page.getInstallabilityErrors')['installabilityErrors'] == []
    # ... and it installs as one app, whichever page the coach installs from.
    app = manifest['manifest']
    root = f'{coachboard_url}/'
    assert (app['id'], app['startUrl'], app['scope']) == (root, root, root)
    assert (app['name'], app['display']) == ('CoachBoard', 'kStandalone')
    assert (app['themeColor'], app['backgroundColor']) == ('rgba(23,32,51,1)', 'rgba(243,245,248,1)')
    # The icons load in the browser at the sizes the manifest declares.
    parsed = page.evaluate("""async (url) => {
      const manifest = await (await fetch(url)).json();
      const icons = [];
      for (const icon of manifest.icons) {
        const image = new Image(); image.src = icon.src; await image.decode();
        icons.push({sizes: icon.sizes, purpose: icon.purpose, loaded: `${image.naturalWidth}x${image.naturalHeight}`});
      }
      return {name: manifest.name, short_name: manifest.short_name, display: manifest.display, icons};
    }""", manifest['url'])
    assert (parsed['name'], parsed['short_name'], parsed['display']) == ('CoachBoard', 'CoachBoard', 'standalone')
    assert all(icon['loaded'] == icon['sizes'] for icon in parsed['icons']), parsed['icons']
    assert {icon['purpose'] for icon in parsed['icons']} == {'any', 'maskable'}
    # No service worker is needed for any of this, and none is registered.
    assert page.evaluate('async () => (await navigator.serviceWorker.getRegistrations()).length') == 0
    assert page.cb_errors == []


def test_login_page_is_installable_without_a_service_worker(page, coachboard_url):
    page.goto(f'{coachboard_url}/login')
    page.wait_for_load_state('load')
    _check(page, coachboard_url)


def test_signed_in_page_is_installable_without_a_service_worker(page, coachboard_url):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    page.wait_for_load_state('load')
    page.goto(f'{coachboard_url}/')
    page.wait_for_load_state('load')
    _check(page, coachboard_url)
