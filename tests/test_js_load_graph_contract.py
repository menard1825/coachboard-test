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
    DYNAMIC,
    FROZEN,
    INJECTED,
    TEMPLATE,
    UNVERSIONED,
    VERSIONED,
    all_load_sites,
    all_modules,
    entry_modules,
    modules_loaded_under_multiple_urls,
    orphan_templates,
    page_load_sites,
    page_loader_files,
    select_page_load_sites,
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
#:
#: Empty. It previously held five, all deleted in the dead-code slice after
#: proving nothing rendered, extended, included or imported them, and that the
#: one dynamic render_template() call site can only receive login.html,
#: register.html or forgot_password.html.
KNOWN_ORPHAN_TEMPLATES = frozenset()


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


# --------------------------------------------------------------------------
# Duplicate executable script loading
#
# modules_loaded_under_multiple_urls() compares the *set of URLs* a module is
# requested under. Once every loader produces the same canonical URL that set
# has one entry, so it cannot see two loaders putting the same script on one
# page -- which is how live_game_clock_controls.js kept two <script> tags and
# ran two five-second /clock pollers.
#
# This counts loader *files* within a single rendered page's graph, so:
#   - two loaders in mutually exclusive templates are not flagged
#     (client_timezone.js in auth_base.html vs base.html);
#   - two sites inside one loader are not flagged, being that module's own
#     branching (live_game_inning_clarity.js's document.write / createElement
#     if/else, or navigation_v2.js's per-route blocks).
# --------------------------------------------------------------------------

LIVE_GAME_TEMPLATE = 'game_management.html'

#: Modules on /game/<id> loaded by more than one loader file, each verified in
#: a real browser and each safe for a specific, named reason. An entry here is
#: a statement that the duplicate cannot execute twice -- not a licence to add
#: another loader.
KNOWN_MULTI_LOADER_MODULES = {
    # Three loaders, two <script> tags in the browser. The module opens with
    # `if (window.CBPitcherChangeComplete?.version === 6) return;`, so the
    # second tag is a no-op. Only the download is duplicated.
    'live_game_pitcher_change_complete.js',
    # Two loaders whose dedupe markers agree: game_management.html tags it
    # data-live-inning-clarity="true" and live_game_sync_status.js checks for
    # exactly that attribute before loading, so only one tag is created.
    # Verified: one <script> tag in the browser.
    'live_game_inning_clarity.js',
}


def test_clock_controls_has_exactly_one_load_site():
    """The regression this slice fixed, pinned by name.

    live_game_contract.js::ensureClockControls() is the canonical loader.
    gameday_pitching_steppers.js used to load it as well, with a different
    dedupe marker, so the module got two <script> tags, executed twice, and
    ran two five-second /clock pollers.

    Deliberately stricter than the file-level check below: this module's
    correct architecture is one load site, one script tag, one execution, so
    the assertion counts actual load *sites*. Two calls inside one loader file
    would be just as wrong here, and a set of loader filenames would hide
    that.
    """
    sites = [
        site for site in page_load_sites(LIVE_GAME_TEMPLATE)
        if site['module'] == 'live_game_clock_controls.js'
    ]

    assert sites, 'live_game_clock_controls.js is no longer loaded at all'
    assert len(sites) == 1, (
        'live_game_clock_controls.js must have exactly one load site; it self '
        'guards against nothing, so every extra tag is another set of timers '
        'and listeners. Found: '
        + repr([f"{s['loader']}:{s['line']}" for s in sites])
    )
    assert sites[0]['loader'] == 'live_game_contract.js', (
        'the canonical loader is live_game_contract.js::ensureClockControls(); '
        f"found {sites[0]['loader']}:{sites[0]['line']}"
    )


def test_no_new_module_has_two_loaders_on_the_live_page():
    """Two loader files for one module need a reason, recorded in the baseline.

    Whether a second loader actually produces a second <script> tag depends on
    whether the two agree on a dedupe marker -- this tree contains examples
    both ways. So this does not claim a duplicate tag; it requires that any
    such pair has been looked at and justified.
    """
    multi = {
        module: sorted(loaders)
        for module, loaders in page_loader_files(LIVE_GAME_TEMPLATE).items()
        if len(loaders) > 1 and module not in KNOWN_MULTI_LOADER_MODULES
    }

    assert not multi, (
        'these modules are loaded by more than one loader on /game/<id>. '
        'Whether that produces a second <script> tag and a second execution '
        'depends on whether the loaders share a dedupe marker and whether the '
        'module self-guards, so each pair needs review and, if safe, an entry '
        'in KNOWN_MULTI_LOADER_MODULES recording why: ' + repr(multi)
    )


def test_multi_loader_baseline_has_no_stale_entries():
    """A module reduced to one loader must leave the baseline."""
    current = {
        module for module, loaders in page_loader_files(LIVE_GAME_TEMPLATE).items()
        if len(loaders) > 1
    }
    stale = KNOWN_MULTI_LOADER_MODULES - current

    assert not stale, (
        'these modules now have a single loader -- remove them from '
        f'KNOWN_MULTI_LOADER_MODULES: {sorted(stale)}'
    )


def test_the_page_scoped_scan_is_not_vacuous():
    """Guard against a scan that silently stopped finding the page's modules."""
    modules = page_loader_files(LIVE_GAME_TEMPLATE)

    assert len(modules) > 30, (
        f'only {len(modules)} modules found on /game/<id>; the page-scoped '
        'walk is probably broken'
    )
    assert 'live_game_v2.js' in modules
    assert 'live_game_contract.js' in modules


def test_a_dynamic_load_from_an_unreachable_loader_is_not_counted():
    """A load site belongs to a page only if its *loader* runs on that page.

    Models::

        game.html --template--> contract.js --dynamic--> clock.js
        orphan.js --dynamic--> clock.js          (orphan.js loads nowhere)

    clock.js is reachable, via contract.js. An earlier version of the filter
    asked whether the *loaded module* was reachable, so it counted the
    orphan.js site too and reported clock.js as having two loaders on a page
    that never runs orphan.js.
    """
    sites = [
        {'kind': TEMPLATE, 'loader': 'game.html', 'module': 'contract.js', 'line': 1},
        {'kind': DYNAMIC, 'loader': 'contract.js', 'module': 'clock.js', 'line': 2},
        {'kind': DYNAMIC, 'loader': 'orphan.js', 'module': 'clock.js', 'line': 3},
    ]
    graph = {'game.html': {'contract.js'}, 'contract.js': {'clock.js'},
             'orphan.js': {'clock.js'}}
    shells = {'game.html'}
    reachable = walk(graph, {'contract.js'})

    assert 'clock.js' in reachable, 'the fixture must make clock.js reachable'
    assert 'orphan.js' not in reachable, 'orphan.js must be unreachable'

    selected = select_page_load_sites(sites, shells, reachable)
    loaders = sorted(site['loader'] for site in selected if site['module'] == 'clock.js')

    assert loaders == ['contract.js'], (
        f'expected only the reachable loader to count for clock.js; got {loaders}'
    )


def test_a_template_site_from_another_template_is_not_counted():
    """Two templates loading one module are two pages, not two loaders."""
    sites = [
        {'kind': TEMPLATE, 'loader': 'game.html', 'module': 'shared.js', 'line': 1},
        {'kind': TEMPLATE, 'loader': 'other.html', 'module': 'shared.js', 'line': 1},
    ]
    selected = select_page_load_sites(sites, {'game.html'}, {'shared.js'})

    assert [site['loader'] for site in selected] == ['game.html']


def test_a_dynamic_load_from_a_reachable_loader_is_counted():
    """The inverse, so the filter is not simply dropping dynamic sites."""
    sites = [
        {'kind': DYNAMIC, 'loader': 'contract.js', 'module': 'clock.js', 'line': 2},
    ]
    selected = select_page_load_sites(sites, {'game.html'}, {'contract.js', 'clock.js'})

    assert len(selected) == 1


def test_injected_sites_are_counted():
    """Server injections are all /game/<id>-gated, as proved in this slice."""
    sites = [
        {'kind': INJECTED, 'loader': 'live_game_ui.py', 'module': 'x.js', 'line': 1},
    ]

    assert len(select_page_load_sites(sites, set(), set())) == 1
