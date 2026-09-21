"""Guardrail: the implicit JavaScript load graph.

CoachBoard has no script manifest. A module reaches the browser by a template
``<script src>``, by another module injecting a ``<script>`` tag, or by
``blueprints/live_game_ui.py`` rewriting the response HTML. Most modules arrive
by the second route, several links deep.

That makes "nothing references this file, so it is dead" a dangerous
inference -- during the audit a first pass suggested 36 of the 63 files were
unreferenced, and every one of them turned out to be chain-loaded. These tests
make the graph explicit so a future cleanup slice can tell a genuinely
unreachable file from a dynamically reached one, instead of guessing.
"""

import pytest

from guardrail_js_support import (
    FROZEN,
    UNVERSIONED,
    VERSIONED,
    all_load_sites,
    all_modules,
    entry_modules,
    modules_loaded_under_multiple_urls,
    orphan_templates,
    reachable_modules,
    scan_js_source,
    walk,
)


#: Modules permitted to be loaded under more than one URL.
#:
#: Empty. It previously held four modules -- client_timezone.js,
#: live_game_inning_clarity.js, live_game_clock_controls.js and
#: live_game_pitcher_change_complete.js, the last reachable under three
#: spellings. A single asset version across all four loading mechanisms means
#: every loader now produces the same URL for a given module.
KNOWN_MULTI_URL_MODULES = frozenset()

#: Templates on disk that no view renders and no template includes.
KNOWN_ORPHAN_TEMPLATES = frozenset({
    '_stats_contentold.html',
    'create_initial_team.html',
    'development_hub.html',
    'game_management_v2.html',
    'stats.html',
})


# --------------------------------------------------------------------------
# Scanner self-tests
#
# These run against synthetic source and synthetic graphs. They prove the
# traversal follows chain loads correctly without asserting anything about how
# deeply CoachBoard's own modules happen to be chained today -- that depth is
# current debt, not a property worth preserving.
# --------------------------------------------------------------------------

def test_walk_follows_a_chain_of_loads():
    graph = {
        'page.html': {'a.js'},
        'a.js': {'b.js'},
        'b.js': {'c.js'},
    }

    assert walk(graph, {'page.html'}) == {'page.html', 'a.js', 'b.js', 'c.js'}


def test_walk_terminates_on_a_cycle():
    graph = {'a.js': {'b.js'}, 'b.js': {'a.js'}}

    assert walk(graph, {'a.js'}) == {'a.js', 'b.js'}


def test_walk_does_not_invent_unreachable_nodes():
    graph = {'page.html': {'a.js'}, 'orphan.js': {'b.js'}}

    assert walk(graph, {'page.html'}) == {'page.html', 'a.js'}


def test_walk_of_a_flat_graph_is_just_its_entries():
    """A codebase with no chain loading at all is a valid shape.

    If the cleanup slices flatten CoachBoard's loading, the traversal must stay
    correct rather than expecting depth.
    """
    graph = {'page.html': {'a.js', 'b.js'}}

    assert walk(graph, {'page.html'}) == {'page.html', 'a.js', 'b.js'}
    assert walk({}, {'a.js'}) == {'a.js'}


def test_scanner_reads_a_direct_src_assignment():
    sites = scan_js_source('probe.js', """
      var s = document.createElement('script');
      s.src = '/static/js/target.js';
      document.head.appendChild(s);
    """)

    assert [(site['module'], site['status']) for site in sites] == [
        ('target.js', UNVERSIONED)
    ]


def test_scanner_reads_a_hand_typed_version_as_frozen():
    sites = scan_js_source('probe.js', """
      var s = document.createElement('script');
      s.src = '/static/js/target.js?v=20260101-1';
    """)

    assert [(site['module'], site['status']) for site in sites] == [
        ('target.js', FROZEN)
    ]


def test_scanner_reads_a_concatenated_version_as_frozen():
    """A src built from two string literals still carries a frozen version."""
    sites = scan_js_source('probe.js', """
      var s = document.createElement('script');
      s.src =
          '/static/js/target.js' +
          '?v=hand-written';
    """)

    assert [(site['module'], site['status']) for site in sites] == [
        ('target.js', FROZEN)
    ]


def test_scanner_recognises_the_canonical_asset_helper():
    """A URL built through window.CoachBoardAssets.url() counts as versioned.

    This is the one sanctioned mechanism: the version comes from the server via
    templates/_coachboard_assets.html, so the URL changes when the deployment
    does and is identical across every loader.
    """
    sites = scan_js_source('probe.js', """
      var s = document.createElement('script');
      s.src = window.CoachBoardAssets.url('/static/js/target.js');
      document.head.appendChild(s);
    """)

    assert [(site['module'], site['status']) for site in sites] == [
        ('target.js', VERSIONED)
    ]


def test_scanner_follows_a_local_wrapper_around_the_helper():
    """Loaders that route their src through a local function still count.

    Resolved to a fixpoint, so an indirection chain is followed: ``load``
    versions only because it calls ``wrap``, which calls the canonical helper.
    """
    sites = scan_js_source('probe.js', """
      function wrap(src) {
        return window.CoachBoardAssets.url(src);
      }

      function load(src) {
        var s = document.createElement('script');
        s.src = wrap(src);
        document.head.appendChild(s);
      }

      load('/static/js/target.js');
    """)

    assert [(site['module'], site['status']) for site in sites] == [
        ('target.js', VERSIONED)
    ]


def test_scanner_reads_a_script_written_during_parse():
    """document.write is a fourth loading mechanism and must not be invisible.

    live_game_inning_clarity.js uses it while the document is still parsing. An
    earlier version of this scan matched only ``.src =`` and loader calls, so
    it missed that load site entirely -- and with it, one of the competing URLs
    for live_game_feedback_pass.js.
    """
    sites = scan_js_source('probe.js', """
      document.write(
        '<script src="' +
        window.CoachBoardAssets.url('/static/js/target.js') +
        '" data-x="1"></' + 'script>'
      );
    """)

    assert [(site['module'], site['status']) for site in sites] == [
        ('target.js', VERSIONED)
    ]


def test_scanner_reads_an_unversioned_written_tag_as_unversioned():
    sites = scan_js_source('probe.js', """
      document.write('<script src="/static/js/target.js"></' + 'script>');
    """)

    assert [(site['module'], site['status']) for site in sites] == [
        ('target.js', UNVERSIONED)
    ]


def test_scanner_ignores_a_module_named_only_in_a_comment():
    """Comments mention modules constantly in this codebase."""
    sites = scan_js_source('probe.js', """
      // see /static/js/mentioned.js for the other half of this
      /* also /static/js/blocky.js */
      var s = document.createElement('script');
      s.src = '/static/js/real.js';
    """)

    assert [site['module'] for site in sites] == ['real.js']


def test_scanner_finds_a_loader_whatever_it_is_called():
    """Loaders are matched by shape, not by a known name.

    CoachBoard has fifteen of them under fifteen different names.
    """
    sites = scan_js_source('probe.js', """
      function someUnusualName(src, key) {
        var s = document.createElement('script');
        s.src = src;
        s.dataset.key = key;
        document.head.appendChild(s);
      }

      someUnusualName('/static/js/target.js', 'k');
    """)

    assert [site['module'] for site in sites] == ['target.js']


# --------------------------------------------------------------------------
# The production scan must not be silently empty
# --------------------------------------------------------------------------

def test_the_production_scan_finds_load_sites():
    """Guard against a vacuous pass from a scanner that stopped finding anything.

    This asserts the scan works, not that CoachBoard keeps any particular
    loading mechanism.
    """
    assert all_load_sites(), 'no load sites found at all; the scan is broken'
    assert entry_modules(), 'no page loads any JavaScript directly'


# --------------------------------------------------------------------------
# Reachability
# --------------------------------------------------------------------------

def test_every_shipped_module_is_reachable():
    """No file in static/js is dead.

    A failure here means either a genuinely orphaned file was added, or a new
    loading mechanism exists that this scan does not understand. Check the
    second possibility before deleting anything -- that is exactly the mistake
    this guardrail exists to prevent.
    """
    unreachable = all_modules() - reachable_modules()

    assert not unreachable, (
        'these modules are not reachable from any page entry point. Before '
        'concluding they are dead, confirm no new loader mechanism was added '
        f'(templates, JS chain loads, server-side injection): {sorted(unreachable)}'
    )


def test_no_load_site_points_at_a_missing_module():
    """A loader must not reference a file that is not shipped."""
    shipped = all_modules()
    missing = sorted({
        f"{site['loader']}:{site['line']} -> {site['module']}"
        for site in all_load_sites()
        if site['module'] not in shipped
    })

    assert not missing, f'load sites reference files that do not exist: {missing}'


# --------------------------------------------------------------------------
# Duplicate loading
# --------------------------------------------------------------------------

def test_no_new_module_is_loaded_under_multiple_urls():
    """Two spellings of one module are two downloads and two executions."""
    new = set(modules_loaded_under_multiple_urls()) - KNOWN_MULTI_URL_MODULES

    assert not new, (
        'these modules are loaded under more than one URL, so a browser '
        'downloads and executes each spelling separately. Unless the module '
        'guards itself, that means two copies of its state: '
        f'{sorted(new)}'
    )


def test_multi_url_baseline_has_no_stale_entries():
    """A module that now loads under one URL must leave the baseline."""
    fixed = KNOWN_MULTI_URL_MODULES - set(modules_loaded_under_multiple_urls())

    assert not fixed, (
        'these modules now load under a single URL -- delete them from '
        f'KNOWN_MULTI_URL_MODULES: {sorted(fixed)}'
    )


def test_every_module_is_loaded_under_exactly_one_url():
    """One module, one URL, one cache entry, one execution.

    Held as a baselined xfail while four modules had competing spellings.
    """
    assert not modules_loaded_under_multiple_urls()


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------

def test_no_new_orphan_templates():
    """A template nothing renders cannot put anything on a page."""
    new = orphan_templates() - KNOWN_ORPHAN_TEMPLATES

    assert not new, (
        'these templates are not rendered by any view and not included or '
        f'extended by any template: {sorted(new)}'
    )


def test_orphan_template_baseline_has_no_stale_entries():
    """Deleting a known orphan must also shrink the baseline."""
    gone = KNOWN_ORPHAN_TEMPLATES - orphan_templates()

    assert not gone, (
        'these templates are no longer orphaned (deleted, or newly rendered) '
        f'-- remove them from KNOWN_ORPHAN_TEMPLATES: {sorted(gone)}'
    )
