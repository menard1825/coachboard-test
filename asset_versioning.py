"""The single source of truth for CoachBoard's static-asset version.

CoachBoard serves JavaScript from three places -- a Jinja ``<script src>``, a
runtime ``<script>`` injection by another module, and an ``after_app_request``
hook rewriting the response HTML. Before this module each of those versioned
its URLs differently, or not at all, so the same file could reach a browser
under several spellings and a hand-typed ``?v=20260914-...`` never changed when
the file did.

This module owns the one answer. The version is established once per
application instance (``ASSET_VERSION`` in the environment, otherwise the
process start time) and published in three forms:

* ``asset_url()`` -- for server-rendered and server-injected tags;
* the ``asset_version`` template variable -- for ``url_for(..., v=asset_version)``;
* ``window.CoachBoardAssets`` -- for every dynamic loader, via
  ``templates/_coachboard_assets.html``.

All three read the same value, so a module requested by any route resolves to
one canonical URL and one cache entry.

Deliberate trade-off: this is a whole-application version, not a per-file one.
A deployment or restart re-fetches every asset rather than only the changed
ones. That is the cost of having a single value the browser-side loaders can
also see -- an mtime cannot be computed in the browser, and per-file mtimes
were what made the URLs diverge in the first place.
"""

from flask import current_app, url_for


#: Where ``create_app`` stores the version for the life of the instance.
CONFIG_KEY = 'COACHBOARD_ASSET_VERSION'


def current_asset_version():
    """The asset version for this application instance, or ``''`` if unset."""
    try:
        return str(current_app.config.get(CONFIG_KEY) or '')
    except RuntimeError:
        # No application context (a management command, an import-time call).
        return ''


def asset_url(filename):
    """A versioned static URL, e.g. ``asset_url('js/live_game_v2.js')``.

    Falls back to an unversioned URL if no version is configured, so a missing
    version degrades to today's caching behaviour rather than a broken tag.
    """
    version = current_asset_version()
    if version:
        return url_for('static', filename=filename, v=version)
    return url_for('static', filename=filename)
