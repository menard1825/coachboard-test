"""Guardrail: a dynamically loaded module must change URL when the file changes.

A browser caches by URL. If a module is loaded as
``/static/js/foo.js?v=20260819-1`` and that literal is typed into the source,
then editing ``foo.js`` does not change its URL, and a coach who opened the app
last week keeps running last week's copy against this week's backend. That is
the quiet failure mode behind "the fix is deployed but the coach still sees the
old behaviour".

CoachBoard already solves this correctly in two places:

* templates pass ``v=css_version``;
* ``blueprints/live_game_ui.py`` injects scripts through ``_versioned_static``,
  which versions by file mtime -- the only mechanism here that changes when the
  file itself changes.

Thirteen other load sites hardcode a date, and ten version nothing at
all -- 23 in total.

These tests do not fail the suite for the existing violations. They baseline
them, and the baseline is enforced in *both* directions: a new violation fails,
and a violation that gets fixed without being removed from the baseline also
fails. That is what lets the guardrail tighten by itself as the next slice
fixes each site, and go fully strict the moment the baseline is empty.
"""

import pytest

from guardrail_js_support import (
    FROZEN,
    UNVERSIONED,
    VERSIONED,
    all_load_sites,
    dynamic_load_sites,
    injected_load_sites,
    template_load_sites,
)


#: Load sites that do not re-fetch when their module changes, as of
#: 1a067777472d8fb5f3c62ca0bb024b621c6f4005.
#:
#: Each entry is ``(loader, module, status)``. Remove an entry when its load
#: site is fixed -- the tests below will tell you if you forget. When this set
#: is empty the contract is enforced strictly with no further edits.
KNOWN_STALE_LOAD_SITES = frozenset({
    # Hand-typed version strings, frozen at the date someone last thought
    # about them.
    ('coachboard_ui.js', 'fair_play_assistant.js', FROZEN),
    ('coachboard_ui.js', 'home_dashboard.js', FROZEN),
    ('coachboard_ui.js', 'pitching_preferences.js', FROZEN),
    ('gameday_pitching_steppers.js', 'live_game_dugout_mode.js', FROZEN),
    ('live_game_contract.js', 'live_game_clock_controls.js', FROZEN),
    ('live_game_inning_clarity.js', 'live_game_feedback_pass.js', FROZEN),
    ('live_game_sync_status.js', 'live_game_bench_report.js', FROZEN),
    ('live_game_v2.js', 'live_game_pitcher_change_complete.js', FROZEN),
    ('navigation_v2.js', 'live_game_sync_status.js', FROZEN),
    ('pitching_dashboard_v3.js', 'pitching_dugout_mobile.js', FROZEN),
    ('pitching_dashboard_v3.js', 'pitching_scan_compact.js', FROZEN),
    ('touch_reorder_guard.js', 'getting_started_home.js', FROZEN),
    ('touch_reorder_guard.js', 'mobile_game_day_fields.js', FROZEN),

    # No version at all -- cached until the browser decides otherwise.
    ('auth_base.html', 'client_timezone.js', UNVERSIONED),
    ('game_correction.html', 'postgame_correction.js', UNVERSIONED),
    ('gameday_pitching_steppers.js', 'live_game_clock_controls.js', UNVERSIONED),
    ('gameday_pitching_steppers.js', 'live_game_command_center.js', UNVERSIONED),
    ('gameday_pitching_steppers.js', 'live_game_connection_status.js', UNVERSIONED),
    ('gameday_pitching_steppers.js', 'pregame_quick_start.js', UNVERSIONED),
    ('gameday_pitching_steppers.js', 'pregame_quick_start_modals.js', UNVERSIONED),
    ('gameday_pitching_steppers.js', 'pregame_starting_defense_scope.js', UNVERSIONED),
    ('live_game_field_realism.js', 'live_game_pitcher_change_complete.js', UNVERSIONED),
    ('live_game_sync_status.js', 'live_game_inning_clarity.js', UNVERSIONED),
})


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


@pytest.mark.xfail(
    strict=True,
    reason=(
        'Known defect at 1a06777: 23 load sites do not re-fetch when their '
        'module changes. Scheduled for the cache-busting slice. When that '
        'lands, empty KNOWN_STALE_LOAD_SITES and delete this xfail marker.'
    ),
)
def test_every_load_site_is_versioned():
    """The contract this suite is aiming at, recorded as a visible defect.

    ``strict=True`` means that if this ever passes while the marker is still
    here, the suite fails -- so the marker cannot outlive the defect.
    """
    assert not _violations()
