"""Guardrail: a dynamically loaded module must change URL when the file changes.

A browser caches by URL. If a module is loaded as
``/static/js/foo.js?v=20260819-1`` and that literal is typed into the source,
then editing ``foo.js`` does not change its URL, and a coach who opened the app
last week keeps running last week's copy against this week's backend. That is
the quiet failure mode behind "the fix is deployed but the coach still sees the
old behaviour".

CoachBoard now has exactly one answer. ``asset_versioning.py`` establishes the
application asset version, ``templates/_coachboard_assets.html`` publishes it
to the browser as ``window.CoachBoardAssets``, and all four loading
mechanisms -- a template ``<script src>``, a runtime ``<script>`` injection, a
``document.write`` during parse, and a server-side HTML rewrite -- build their
URLs from it.

``KNOWN_STALE_LOAD_SITES`` is empty. It previously held 23 entries: 13 load
sites with a hand-typed date and 10 with no version at all. Those were
corrected rather than excused, so the ratchet below now enforces the contract
outright, and any regression fails immediately.
"""

import pytest

from guardrail_js_support import (
    TEMPLATE_DIR,
    FROZEN,
    UNVERSIONED,
    VERSIONED,
    all_load_sites,
    dynamic_load_sites,
    injected_load_sites,
    template_load_sites,
)


#: Load sites permitted not to re-fetch when their module changes.
#:
#: Empty, and it should stay that way. Each entry would be ``(loader, module,
#: status)``. The two tests below enforce it in both directions, so adding an
#: entry here to silence a failure is visible in review rather than silent.
KNOWN_STALE_LOAD_SITES = frozenset()


def _violations():
    return {
        (site['loader'], site['module'], site['status'])
        for site in all_load_sites()
        if site['status'] != VERSIONED
    }


def _describe(entries):
    return sorted(f'{loader} -> {module} [{status}]' for loader, module, status in entries)


# --------------------------------------------------------------------------
# The scan itself must be working
# --------------------------------------------------------------------------

def test_the_loader_inventory_finds_all_three_mechanisms():
    """Guard against a vacuous pass from a scanner that stopped finding anything."""
    assert template_load_sites(), 'no template <script src> load sites found'
    assert injected_load_sites(), 'no server-injected load sites found'
    assert dynamic_load_sites(), 'no runtime <script> injections found'


def test_the_known_good_mechanisms_are_still_recognised_as_versioned():
    """``css_version`` and ``_versioned_static`` must both count as versioned.

    If this fails, the scanner has stopped understanding the *correct* pattern
    and every assertion below is noise.
    """
    assert all(site['status'] == VERSIONED for site in injected_load_sites()), (
        '_versioned_static injections are no longer classified as versioned'
    )
    versioned_templates = [
        site for site in template_load_sites() if site['status'] == VERSIONED
    ]
    assert versioned_templates, 'no template load site is versioned by css_version'


# --------------------------------------------------------------------------
# The ratchet
# --------------------------------------------------------------------------

def test_no_new_stale_load_sites():
    """A newly added load site must version its URL."""
    new = _violations() - KNOWN_STALE_LOAD_SITES

    assert not new, (
        'these load sites will be served from a stale browser cache after the '
        'module changes. Version the URL at the load site (see '
        'navigation_v2.js versionedHelperSrc, or _versioned_static in '
        'blueprints/live_game_ui.py):\n  ' + '\n  '.join(_describe(new))
    )


def test_cache_busting_baseline_has_no_stale_entries():
    """A fixed load site must be removed from the baseline.

    This is what makes the guardrail tighten on its own: every fix in the next
    slice forces the baseline to shrink, and once it is empty the test above
    enforces the contract strictly with no further edits here.
    """
    fixed = KNOWN_STALE_LOAD_SITES - _violations()

    assert not fixed, (
        'these load sites now version correctly -- delete them from '
        'KNOWN_STALE_LOAD_SITES:\n  ' + '\n  '.join(_describe(fixed))
    )


def test_every_load_site_is_versioned():
    """The contract, now enforced outright.

    Held as a baselined xfail while 23 load sites carried hand-typed or absent
    versions. Those were corrected in fix/asset-cache-busting-20260921 rather
    than excused, so the baseline above is empty and this is a plain assertion.
    """
    assert not _violations()


# --------------------------------------------------------------------------
# The mechanism must actually reach every page
# --------------------------------------------------------------------------

def test_every_page_shell_publishes_the_asset_version():
    """A shell that forgets the partial breaks every loader on its pages.

    ``window.CoachBoardAssets`` is defined by templates/_coachboard_assets.html
    and consumed by every dynamic loader. A new page shell that does not
    include it would leave those loaders calling into an undefined object, so
    this is checked rather than assumed. Shells are templates that extend
    nothing and load scripts of their own.
    """
    missing = []

    for path in sorted(TEMPLATE_DIR.glob('*.html')):
        source = path.read_text()
        if '{% extends' in source:
            continue
        if '<script' not in source:
            continue  # a macro or fragment, not a page shell
        if '_coachboard_assets.html' in source:
            continue
        if 'CoachBoardAssets' in source:
            continue  # this file *is* the partial
        missing.append(path.name)

    assert not missing, (
        'these page shells load scripts but do not include '
        f"_coachboard_assets.html, so window.CoachBoardAssets is undefined on "
        f'their pages: {missing}'
    )


def test_the_asset_partial_defines_the_helper_once():
    """One owner, as documented in asset_versioning.py."""
    partial = (TEMPLATE_DIR / '_coachboard_assets.html').read_text()

    assert 'window.CoachBoardAssets' in partial
    assert 'coachboard-asset-version' in partial

    definitions = [
        path.name
        for path in TEMPLATE_DIR.glob('*.html')
        if 'window.CoachBoardAssets =' in path.read_text()
    ]
    assert definitions == ['_coachboard_assets.html'], (
        f'the asset helper is defined in more than one place: {definitions}'
    )
