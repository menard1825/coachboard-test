"""Browser proof that every CoachBoard asset is requested under one URL.

The static guardrails in ``tests/test_js_cache_busting_contract.py`` read the
source. This reads the network: it records every request a real browser makes
while loading a page and checks what actually went over the wire, which is the
only place the four loading mechanisms -- template tag, runtime injection,
``document.write`` during parse, and server-side HTML rewrite -- can be
observed together.

The E2E harness pins ``ASSET_VERSION=e2e`` (tests/e2e/conftest.py), so every
CoachBoard asset must arrive as ``...?v=e2e``.
"""

import os
import re
from collections import defaultdict

import pytest


pytestmark = pytest.mark.e2e

if os.environ.get('COACHBOARD_E2E') != '1':
    pytest.skip('Set COACHBOARD_E2E=1 to run Playwright tests.', allow_module_level=True)

from playwright.sync_api import Page, expect


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'

EXPECTED_VERSION = 'e2e'

#: Modules the audit found reachable under competing URLs. Named explicitly so
#: a regression on any one of them is reported by name rather than buried.
PREVIOUSLY_DUPLICATED = (
    'live_game_pitcher_change_complete.js',
    'live_game_clock_controls.js',
    'live_game_inning_clarity.js',
    'client_timezone.js',
)

STATIC_ASSET = re.compile(r'/static/(?P<path>[^?]+)(?P<query>\?.*)?$')

#: Assets this mechanism versions: the code CoachBoard ships.
CODE_ASSET = re.compile(r'\.(?:js|css)$')

#: Known exception, deliberately not fixed in this slice.
#:
#: static/css/main.css references background-image: url('/static/diamond.jpg').
#: The stylesheet is versioned, so a rule change reaches returning browsers,
#: but the image URL inside it is not, so replacing the image would not. Fixing
#: that properly needs the URL rewritten at build or render time, which is more
#: machinery than an asset-versioning slice should introduce. Recorded here so
#: it is a decision rather than an oversight.
UNVERSIONED_MEDIA = ('/static/diamond.jpg',)


def login(page: Page, coachboard_url: str):
    page.goto(f'{coachboard_url}/login')
    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(
        re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$')
    )


def record_static_requests(page: Page):
    """Collect every /static/ URL the browser requests."""
    seen = []
    page.on('request', lambda request: seen.append(request.url))
    return seen


def settle(page: Page):
    """Give chain-loaded modules time to inject their own script tags."""
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1500)
    page.wait_for_load_state('networkidle')


def coachboard_assets(urls):
    """``{asset path: {full query strings seen}}`` for CoachBoard's own files.

    Uploaded team logos are content rather than shipped code, and are left out.
    """
    by_asset = defaultdict(set)
    for url in urls:
        match = STATIC_ASSET.search(url)
        if not match or match.group('path').startswith('uploads/'):
            continue
        by_asset[match.group('path')].add(match.group('query') or '')
    return by_asset


def test_the_only_unversioned_asset_is_the_known_css_background(
    page: Page, coachboard_url: str
):
    """Pin the one documented exception so it cannot quietly grow.

    If another unversioned media asset appears, this fails and the choice gets
    made deliberately rather than by default.
    """
    login(page, coachboard_url)

    requests = record_static_requests(page)
    page.goto(f'{coachboard_url}/game/1')
    settle(page)

    unversioned = {
        STATIC_ASSET.search(url).group('path')
        for url in requests
        if STATIC_ASSET.search(url)
        and f'?v={EXPECTED_VERSION}' not in url
        and not STATIC_ASSET.search(url).group('path').startswith('uploads/')
    }

    assert unversioned <= {path.removeprefix('/static/') for path in UNVERSIONED_MEDIA}, (
        'new unversioned assets appeared: '
        f'{sorted(unversioned - {p.removeprefix("/static/") for p in UNVERSIONED_MEDIA})}'
    )


def test_the_asset_helper_is_published_to_the_browser(page: Page, coachboard_url: str):
    login(page, coachboard_url)

    version = page.evaluate('() => window.CoachBoardAssets && window.CoachBoardAssets.version')
    assert version == EXPECTED_VERSION, (
        f'window.CoachBoardAssets.version is {version!r}; the page is not '
        'publishing the application asset version'
    )

    built = page.evaluate(
        "() => window.CoachBoardAssets.url('/static/js/live_game_v2.js')"
    )
    assert built == f'/static/js/live_game_v2.js?v={EXPECTED_VERSION}'


@pytest.mark.parametrize('path', ['/', '/game/1'])
def test_every_requested_asset_carries_the_canonical_version(
    page: Page, coachboard_url: str, path: str
):
    """No CoachBoard asset may be fetched without the current version."""
    login(page, coachboard_url)

    requests = record_static_requests(page)
    page.goto(f'{coachboard_url}{path}')
    settle(page)

    unversioned = sorted({
        url for url in requests
        if STATIC_ASSET.search(url)
        and CODE_ASSET.search(STATIC_ASSET.search(url).group('path'))
        and f'?v={EXPECTED_VERSION}' not in url
    })

    assert not unversioned, (
        f'{path} requested these assets without the canonical version:\n  '
        + '\n  '.join(unversioned)
    )


@pytest.mark.parametrize('path', ['/', '/game/1'])
def test_no_asset_is_requested_under_two_urls(
    page: Page, coachboard_url: str, path: str
):
    """One file, one URL, one cache entry, one download."""
    login(page, coachboard_url)

    requests = record_static_requests(page)
    page.goto(f'{coachboard_url}{path}')
    settle(page)

    duplicated = {
        asset: sorted(queries)
        for asset, queries in coachboard_assets(requests).items()
        if len(queries) > 1
    }

    assert not duplicated, (
        f'{path} requested these assets under more than one URL, so the '
        f'browser downloaded each spelling separately: {duplicated}'
    )


def test_the_previously_duplicated_modules_now_have_one_url(
    page: Page, coachboard_url: str
):
    """The four modules the audit named, each proved loaded and each with one URL.

    The recording deliberately starts on /login, before signing in, and then
    visits the live-game page. That single pass exercises both page shells --
    auth_base.html and base.html each load client_timezone.js -- as well as the
    template tag, the runtime injections and the server-side rewrite that the
    other three arrive through. Every one of the four is then required to have
    been observed: a module that silently stopped loading would otherwise make
    this assertion vacuous.
    """
    requests = record_static_requests(page)

    # The auth shell, recorded before signing in.
    page.goto(f'{coachboard_url}/login')
    settle(page)

    page.get_by_label('Username or email').fill(TEST_USERNAME)
    page.locator('#password').fill(TEST_PASSWORD)
    page.get_by_role('button', name='Sign In').click()
    expect(page).to_have_url(
        re.compile(rf'^{re.escape(coachboard_url)}/?(?:#(?:overview|games))?$')
    )

    # The application shell plus every live-game loader.
    page.goto(f'{coachboard_url}/game/1')
    settle(page)

    by_asset = coachboard_assets(requests)

    not_loaded = [
        module for module in PREVIOUSLY_DUPLICATED
        if not by_asset.get(f'js/{module}')
    ]
    assert not not_loaded, (
        'these modules were never requested, so this test would have proved '
        f'nothing about them: {not_loaded}'
    )

    wrong = {
        module: sorted(by_asset[f'js/{module}'])
        for module in PREVIOUSLY_DUPLICATED
        if by_asset[f'js/{module}'] != {f'?v={EXPECTED_VERSION}'}
    }
    assert not wrong, (
        f'expected every module to be requested only as "?v={EXPECTED_VERSION}", '
        f'but got: {wrong}'
    )
