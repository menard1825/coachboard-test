"""Serve CoachBoard's four CDN dependencies from local copies in browser tests.

base.html loads Bootstrap's CSS and JS bundle, Bootstrap Icons, Sortable and
socket.io from public CDNs. A browser test that depends on real rendering
cannot depend on those being reachable:

* Bootstrap's stylesheet is render blocking and supplies the
  ``.tab-pane { display: none }`` rule every visibility assertion rests on;
* ``main.js`` constructs ``new bootstrap.Modal(...)`` during init, so without
  the JS bundle its initializer throws before it renders anything -- which
  would make the legacy-fallback test pass for the wrong reason.

Point ``COACHBOARD_CDN_DIR`` at a directory holding the five files below (the
versions base.html pins), or drop them in ``tests/e2e/vendor/``. Tests that
need them skip, with this explanation, when neither is present: a silent pass
would be worse than a skip.
"""

import os
from pathlib import Path

import pytest


#: CDN path (no scheme, no query) -> (local filename, served content type).
CDN_ASSETS = {
    'cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css':
        ('bootstrap.min.css', 'text/css'),
    'cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css':
        ('bootstrap-icons.min.css', 'text/css'),
    'cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js':
        ('bootstrap.bundle.min.js', 'application/javascript'),
    'cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js':
        ('Sortable.min.js', 'application/javascript'),
    'cdn.socket.io/4.7.5/socket.io.min.js':
        ('socket.io.min.js', 'application/javascript'),
}


def vendor_dir():
    configured = os.environ.get('COACHBOARD_CDN_DIR')
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / 'vendor'


def missing_assets():
    directory = vendor_dir()
    return [name for name, _ in CDN_ASSETS.values()
            if not (directory / name).is_file()]


def require_vendored_assets():
    missing = missing_assets()
    if missing:
        pytest.skip(
            'Vendored CDN assets are required for this test and were not '
            f'found in {vendor_dir()}: {", ".join(sorted(missing))}. '
            'Set COACHBOARD_CDN_DIR to a directory holding them.'
        )


def install(context, *, api_delay_ms=0, blocked=()):
    """Route CoachBoard's CDN and, optionally, slow or block local requests.

    ``api_delay_ms`` delays every ``/api/**`` request, which is what makes the
    renderer race observable: with instant APIs the legacy and modern
    dashboards finish within a few tens of milliseconds of each other.
    ``blocked`` aborts matching local paths, used to take home_dashboard.js
    away and prove the legacy fallback still works.
    """
    import time

    directory = vendor_dir()

    def serve_cdn(route, request):
        key = request.url.split('://', 1)[1].split('?')[0]
        entry = CDN_ASSETS.get(key)
        if not entry:
            return route.abort()
        filename, content_type = entry
        route.fulfill(status=200, content_type=content_type,
                      body=(directory / filename).read_bytes())

    context.route('https://cdn.jsdelivr.net/**', serve_cdn)
    context.route('https://cdn.socket.io/**', serve_cdn)

    for fragment in blocked:
        context.route(f'**{fragment}**', lambda route: route.abort())

    if api_delay_ms:
        def slow(route):
            time.sleep(api_delay_ms / 1000.0)
            route.continue_()
        context.route('**/api/**', slow)
