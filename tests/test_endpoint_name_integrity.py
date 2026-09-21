"""Guardrail: every endpoint name the security layer matches on must exist.

CoachBoard attaches authorization and workflow rules to endpoints by *name*:
``security_guard`` holds sets of endpoint-name strings, and eleven blueprints
install ``before_app_request`` hooks that branch on ``request.endpoint``.

Nothing enforces that those strings still refer to real endpoints. Renaming a
view function is enough to silently drop its restriction -- no import error, no
404, no log line, just a guard that stops matching. These tests close that gap.

They deliberately *discover* the names instead of restating them, so they keep
biting after a rename.
"""

import pytest

from guardrail_support import (
    application_sources,
    build_app,
    discover_endpoint_comparisons,
    endpoint_names,
    scan_source,
)


REQUIRED_SECURITY_SETS = (
    'LEGACY_LIVE_MUTATIONS',
    'DESTRUCTIVE_GET_ENDPOINTS',
    'ASSISTANT_HEAD_COACH_ONLY_ENDPOINTS',
)


def _looks_like_endpoint(value):
    """``blueprint.view_function`` -- the shape Flask uses for a named endpoint."""
    if not isinstance(value, str) or value.count('.') != 1:
        return False
    blueprint, view = value.split('.')
    return blueprint.isidentifier() and view.isidentifier()


def _endpoint_collections(module):
    """Every module-level constant that holds endpoint names.

    Discovering these keeps the guardrail honest as the security layer grows: a
    fourth set added next year is covered without touching this test.
    """
    found = {}
    for name in dir(module):
        if not name.isupper():
            continue
        value = getattr(module, name)
        if isinstance(value, dict):
            candidates = list(value.keys())
        elif isinstance(value, (set, frozenset, list, tuple)):
            candidates = list(value)
        else:
            continue
        if candidates and all(_looks_like_endpoint(item) for item in candidates):
            found[name] = set(candidates)
    return found


@pytest.fixture(name='app')
def _app(monkeypatch):
    return build_app(monkeypatch)


def test_security_guard_sets_are_discoverable():
    """The discovery helper must actually find the sets we care about.

    Without this, a typo in the helper would turn every assertion below into a
    vacuous pass over an empty collection.
    """
    from blueprints import security_guard

    discovered = _endpoint_collections(security_guard)

    missing = [name for name in REQUIRED_SECURITY_SETS if name not in discovered]
    assert not missing, (
        'guardrail helper stopped recognising these security constants as '
        f'endpoint-name collections: {missing}. Discovered: {sorted(discovered)}'
    )
    for name in REQUIRED_SECURITY_SETS:
        assert discovered[name], f'{name} is empty; the guardrail would be vacuous'


def test_every_security_endpoint_name_exists(app):
    """Each endpoint named by the security layer must be dispatchable."""
    from blueprints import security_guard

    known = endpoint_names(app)
    collections = _endpoint_collections(security_guard)

    broken = {
        name: sorted(names - known)
        for name, names in collections.items()
        if names - known
    }

    assert not broken, (
        'blueprints/security_guard.py names endpoints that do not exist in the '
        f'URL map -- their guard no longer applies to anything: {broken}'
    )


def test_every_intercepted_endpoint_name_exists(app):
    """Each ``request.endpoint == '...'`` comparison must name a real endpoint.

    This covers the ``before_app_request`` interceptors, which carry the same
    rename hazard as the security sets but are scattered across eleven files.
    """
    known = endpoint_names(app)
    exact, _ = discover_endpoint_comparisons()

    assert exact, 'guardrail found no endpoint comparisons at all; the scan is broken'

    broken = {
        name: sorted(sources)
        for name, sources in exact.items()
        if name not in known
    }

    assert not broken, (
        'these endpoint names are compared against request.endpoint but do not '
        f'exist in the URL map, so the interceptor is dead: {broken}'
    )


def test_every_intercepted_endpoint_prefix_matches_something(app):
    """Each ``endpoint.startswith('x.')`` guard must still cover real endpoints."""
    known = endpoint_names(app)
    _, prefixes = discover_endpoint_comparisons()

    assert prefixes, 'guardrail found no prefix guards; the scan is broken'

    broken = {
        prefix: sorted(sources)
        for prefix, sources in prefixes.items()
        if not any(name.startswith(prefix) for name in known)
    }

    assert not broken, (
        'these endpoint prefixes are guarded but match no endpoint in the URL '
        f'map: {broken}'
    )


def test_destructive_get_endpoints_covers_every_get_reachable_deletion(app):
    """A destructive route reachable by GET must be in the cross-site guard set.

    The audit found the set complete at 1a06777. This pins that, so a new
    delete-by-link route cannot be added without either joining the set or
    failing here.
    """
    from blueprints.security_guard import DESTRUCTIVE_GET_ENDPOINTS

    destructive_words = ('delete', 'remove', 'purge', 'wipe')
    uncovered = []

    for rule in app.url_map.iter_rules():
        if 'GET' not in (rule.methods or set()):
            continue
        view_name = rule.endpoint.rsplit('.', 1)[-1]
        if not any(word in view_name for word in destructive_words):
            continue
        if rule.endpoint in DESTRUCTIVE_GET_ENDPOINTS:
            continue
        uncovered.append(rule.endpoint)

    assert not uncovered, (
        'these endpoints delete data and are reachable by GET but are not in '
        f'DESTRUCTIVE_GET_ENDPOINTS: {sorted(uncovered)}'
    )


# --------------------------------------------------------------------------
# Scanner self-tests
#
# These run against synthetic source rather than the application, so they keep
# describing what the scanner promises no matter how CoachBoard changes.
# --------------------------------------------------------------------------

def test_scanner_reads_a_direct_comparison():
    exact, prefixes = scan_source(
        """
def guard():
    if request.endpoint == 'roster.delete_player':
        return None
"""
    )
    assert exact == {'roster.delete_player'}
    assert prefixes == set()


def test_scanner_follows_an_alias_within_one_function():
    exact, _ = scan_source(
        """
def guard():
    endpoint = request.endpoint or ''
    if endpoint in {'admin.delete_team', 'admin.create_team'}:
        return None
"""
    )
    assert exact == {'admin.delete_team', 'admin.create_team'}


def test_scanner_reads_prefix_guards():
    _, prefixes = scan_source(
        """
def guard():
    endpoint = str(request.endpoint or '')
    return endpoint.startswith('live_game_api.')
"""
    )
    assert prefixes == {'live_game_api.'}


def test_an_alias_does_not_leak_between_functions():
    """An unrelated local named ``endpoint`` is not ``request.endpoint``.

    Without per-function scoping the scanner would carry the alias from the
    first function into the second and invent 'not.an.endpoint' as a guarded
    name -- which would then fail the URL-map assertions for a guard that does
    not exist.
    """
    exact, _ = scan_source(
        """
def guarded():
    endpoint = request.endpoint or ''
    if endpoint == 'roster.delete_player':
        return None


def unrelated(row):
    endpoint = row.some_other_value
    if endpoint == 'not.an.endpoint':
        return None
"""
    )

    assert exact == {'roster.delete_player'}, (
        f'alias tracking leaked between functions: {sorted(exact)}'
    )


def test_an_alias_does_not_leak_out_of_a_nested_function():
    exact, _ = scan_source(
        """
def outer():
    def inner():
        endpoint = request.endpoint
        return endpoint == 'auth.register'

    endpoint = 'a plain string'
    if endpoint == 'not.an.endpoint':
        return None
    return inner
"""
    )

    assert exact == {'auth.register'}, (
        f'alias tracking leaked out of a nested function: {sorted(exact)}'
    )


def test_source_discovery_covers_the_application_and_excludes_the_rest():
    scanned = {path.name for path in application_sources()}
    parts = {part for path in application_sources() for part in path.parts}

    assert 'app.py' in scanned, 'the application factory is not being scanned'
    assert 'security_guard.py' in scanned, 'blueprints are not being scanned'
    assert 'utils.py' in scanned, 'root helper modules are not being scanned'

    assert 'tests' not in parts, 'the scan is reading the test suite'
    assert 'migrations' not in parts, 'the scan is reading Alembic migrations'
    assert '__pycache__' not in parts, 'the scan is reading build artefacts'
