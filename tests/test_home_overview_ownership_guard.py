"""main.js must not fight home_dashboard.js for #overview-content-container.

Two renderers write that container on Home: the legacy
``main.js::renderOverview()`` and the modern ``home_dashboard.js``. Whichever
set of API calls returned first decided what the coach saw, so under latency
the legacy "Next Game" dashboard replaced the modern Home for seconds.

The fix is one ownership guard in ``renderOverview()``. It keys off the two
markers the modern dashboard actually puts in the DOM:

* ``.cb-home-loading`` -- claimed, model still building;
* ``.cb-home-dashboard`` -- claimed and rendered.

This file pins the guard's *shape*, so a future edit cannot quietly widen it
into a page-level or script-tag-level check. Those broader signals are true
even when home_dashboard.js never executes, and the legacy renderer has to stay
alive in that case -- ``tests/e2e/test_home_dashboard_legacy_flash.py`` proves
the behaviour end to end; this file is the cheap structural half.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN_JS = ROOT / 'static' / 'js' / 'main.js'
HOME_DASHBOARD_JS = ROOT / 'static' / 'js' / 'home_dashboard.js'

#: The markers the modern dashboard puts in the container. Both must appear in
#: the guard: .cb-home-dashboard alone would let the legacy renderer overwrite
#: the modern loading state before the modern render ever lands.
OWNERSHIP_MARKERS = ('.cb-home-loading', '.cb-home-dashboard')

#: Signals that are true even when home_dashboard.js failed to execute, so a
#: guard built on them would disable the legacy fallback as well as the flash.
FORBIDDEN_SIGNALS = (
    "classList.contains('cb-home')",
    'classList.contains("cb-home")',
    'data-cb-home-dashboard',
    'script[data-cb-home-dashboard]',
)


def _render_overview_source():
    """The body of renderOverview(), by brace matching from its declaration."""
    source = MAIN_JS.read_text()
    start = source.index('function renderOverview()')
    open_brace = source.index('{', start)
    depth = 0
    for index in range(open_brace, len(source)):
        if source[index] == '{':
            depth += 1
        elif source[index] == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError('renderOverview() is not brace balanced')


@pytest.fixture(scope='module')
def render_overview():
    return _render_overview_source()


def test_render_overview_still_exists():
    """The legacy renderer is a fallback, not dead code. It must survive."""
    assert 'function renderOverview()' in MAIN_JS.read_text()


def test_guard_checks_both_ownership_markers(render_overview):
    """Mutation: delete the guard, or drop either marker from it."""
    guard = re.search(
        r'if\s*\(\s*container\s*\.\s*querySelector\(\s*([\'"])(?P<selector>[^\'"]+)\1\s*\)\s*\)'
        r'\s*(?:\{\s*)?return',
        render_overview,
    )
    assert guard, (
        'renderOverview() has no `if (container.querySelector(...)) return;` '
        'ownership guard'
    )
    selector = guard.group('selector')
    for marker in OWNERSHIP_MARKERS:
        assert marker in selector, (
            f'the ownership guard does not stand down for {marker}: {selector!r}'
        )


def test_guard_runs_before_the_container_is_written(render_overview):
    """A guard placed after the first innerHTML write would not prevent a flash."""
    guard_at = render_overview.index('cb-home-dashboard')
    writes = [match.start() for match in
              re.finditer(r'container\s*\.\s*innerHTML\s*=', render_overview)]
    assert writes, 'renderOverview() no longer writes the container at all'
    assert guard_at < min(writes), (
        'the ownership guard must come before every container write'
    )


def test_legacy_render_body_survives_the_guard(render_overview):
    """The fallback still builds the legacy dashboard after standing down."""
    for fragment in ('Next Game', 'container.innerHTML'):
        assert fragment in render_overview, (
            f'the legacy render body lost {fragment!r}'
        )
    assert render_overview.count('container.innerHTML') >= 2, (
        'renderOverview() should still have both its empty-data and its '
        'full legacy render paths'
    )


def test_existing_null_container_guard_is_kept(render_overview):
    assert 'if (!container) return;' in render_overview


def test_guard_does_not_use_broader_signals(render_overview):
    """Page/body/script-tag signals would kill the fallback, not just the flash."""
    for signal in FORBIDDEN_SIGNALS:
        assert signal not in render_overview, (
            f'renderOverview() keys its guard off {signal!r}, which is true '
            'even when home_dashboard.js never executes'
        )


def test_home_dashboard_still_publishes_both_markers():
    """The guard is only meaningful while the modern owner sets these."""
    source = HOME_DASHBOARD_JS.read_text()
    for marker in ('cb-home-loading', 'cb-home-dashboard'):
        assert marker in source, (
            f'home_dashboard.js no longer publishes {marker}, so the ownership '
            'guard in main.js can never fire'
        )


def test_home_dashboard_keeps_its_own_backstop():
    """This slice adds a guard; it does not replace the existing repair path."""
    assert 'guardAgainstLegacyOverview' in HOME_DASHBOARD_JS.read_text()
