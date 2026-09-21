"""Shared helpers for the guardrail test slice.

These tests exist to pin down *current* structural facts about CoachBoard so a
later cleanup slice cannot silently regress them. Nothing here changes
application behaviour, and nothing here should be imported by application code.

The two jobs of this module:

1. Build a throwaway application the same way the existing unit tests do, so a
   test can read the real ``app.url_map``.
2. Discover, rather than restate, the endpoint-name strings that the security
   guard and the ``before_app_request`` interceptors compare against. Copying
   those names into a test would defeat the point: the test would keep passing
   after a rename because the test was renamed alongside the code.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

#: Directories excluded from the application-source scan.
#:
#: ``tests`` and ``migrations`` are not request-handling code; the rest are
#: environment or build artefacts that may appear in a working checkout and are
#: not part of CoachBoard.
EXCLUDED_DIRS = frozenset({
    'tests',
    'migrations',
    '__pycache__',
    '.git',
    '.venv',
    'venv',
    'env',
    'node_modules',
    'site-packages',
    'vendor',
    'build',
    'dist',
    '.tox',
    '.mypy_cache',
    '.pytest_cache',
})


def build_app(monkeypatch):
    """Create an isolated in-memory application, mirroring the existing tests."""
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app


def endpoint_names(app):
    """Every endpoint name Flask can actually dispatch."""
    return {rule.endpoint for rule in app.url_map.iter_rules()}


# --------------------------------------------------------------------------
# Static discovery of endpoint-name literals
# --------------------------------------------------------------------------

def application_sources():
    """Every Python file that can take part in handling a request.

    Scanned recursively rather than from a hand-listed set of directories, so
    a hook added in a new package is covered without editing this helper.
    """
    for path in sorted(ROOT.rglob('*.py')):
        if EXCLUDED_DIRS & set(path.relative_to(ROOT).parts):
            continue
        yield path


def _is_request_endpoint(node):
    """True for the expression ``request.endpoint``."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == 'endpoint'
        and isinstance(node.value, ast.Name)
        and node.value.id == 'request'
    )


def _unwrap(node):
    """Peel the idioms used to normalise ``request.endpoint``.

    Handles ``request.endpoint or ''`` and ``str(request.endpoint or '')``.
    """
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return _unwrap(node.values[0])
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'str'
        and node.args
    ):
        return _unwrap(node.args[0])
    return node


class _EndpointLiteralVisitor(ast.NodeVisitor):
    """Collect endpoint-name literals compared against ``request.endpoint``.

    ``exact`` holds names used with ``==``, ``!=`` or ``in {...}``; each of
    those must name a real endpoint.

    ``prefixes`` holds the arguments to ``.startswith(...)``; each of those must
    match at least one real endpoint, which is the strongest assertion that
    still permits a blueprint to grow new routes.
    """

    def __init__(self):
        self.exact = set()
        self.prefixes = set()
        # Local names bound to request.endpoint, e.g.
        # `endpoint = request.endpoint or ''`.
        #
        # Scoped per function: an unrelated local called `endpoint` in a
        # different function must not be mistaken for the real thing, or the
        # scan invents endpoint names that were never guarded.
        self._aliases = set()

    def _visit_scope(self, node):
        outer = self._aliases
        self._aliases = set(())
        self.generic_visit(node)
        self._aliases = outer

    visit_FunctionDef = _visit_scope
    visit_AsyncFunctionDef = _visit_scope
    visit_Lambda = _visit_scope

    def _endpoint_expr(self, node):
        node = _unwrap(node)
        if _is_request_endpoint(node):
            return True
        return isinstance(node, ast.Name) and node.id in self._aliases

    def visit_Assign(self, node):
        if self._endpoint_expr(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._aliases.add(target.id)
        self.generic_visit(node)

    def visit_Compare(self, node):
        if self._endpoint_expr(node.left):
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)):
                    self._collect(comparator)
                elif isinstance(op, (ast.In, ast.NotIn)):
                    if isinstance(comparator, (ast.Set, ast.List, ast.Tuple)):
                        for element in comparator.elts:
                            self._collect(element)
                    # `endpoint in SOME_NAMED_SET` is covered by importing that
                    # set directly in the test, which is more precise than
                    # trying to resolve the name statically.
        self.generic_visit(node)

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == 'startswith'
            and self._endpoint_expr(node.func.value)
        ):
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    self.prefixes.add(argument.value)
        self.generic_visit(node)

    def _collect(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            self.exact.add(node.value)


def scan_source(source, filename='<source>'):
    """Endpoint-name literals compared against ``request.endpoint`` in ``source``.

    Exposed separately from the file walk so the scanner can be exercised
    against synthetic input, without depending on what the application happens
    to contain today.
    """
    visitor = _EndpointLiteralVisitor()
    visitor.visit(ast.parse(source, filename=filename))
    return visitor.exact, visitor.prefixes


def discover_endpoint_comparisons():
    """Scan the application for endpoint-name comparisons.

    Returns ``(exact, prefixes)`` where each value maps the literal to the set
    of source files that use it, so a failure message can name the file.
    """
    exact = {}
    prefixes = {}

    for path in application_sources():
        found_exact, found_prefixes = scan_source(path.read_text(), str(path))
        relative = path.relative_to(ROOT).as_posix()
        for name in found_exact:
            exact.setdefault(name, set()).add(relative)
        for prefix in found_prefixes:
            prefixes.setdefault(prefix, set()).add(relative)

    return exact, prefixes

