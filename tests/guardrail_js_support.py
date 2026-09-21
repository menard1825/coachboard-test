"""Inventory of how CoachBoard's JavaScript actually gets onto a page.

CoachBoard has no build step and no script manifest. A module reaches the
browser by one of three routes:

1. a Jinja template's ``<script src>``, versioned with ``css_version``;
2. another JavaScript module injecting a ``<script>`` tag at runtime;
3. ``blueprints/live_game_ui.py`` rewriting the response HTML in an
   ``after_app_request`` hook, versioned by the file's mtime.

The result is a load *graph* that exists only implicitly, spread across
templates, JavaScript and Python. Two guardrails depend on reading it:

* cache-busting -- a module whose URL never changes is served from a stale
  browser cache forever, so a deployed fix never reaches a returning coach;
* liveness -- a module no template mentions is not therefore dead, because
  something else may chain-load or inject it.

This module builds the graph by static analysis. It is deliberately
conservative: it discovers loader functions by shape rather than by name, so a
new loader called something else is still seen.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / 'static' / 'js'
TEMPLATE_DIR = ROOT / 'templates'
BLUEPRINT_DIR = ROOT / 'blueprints'

MODULE_URL = re.compile(
    r"""/static/js/(?P<module>[A-Za-z0-9_\-]+\.js)(?P<query>\?[^'"`\s)]*)?"""
)
TEMPLATE_SCRIPT = re.compile(
    r"""url_for\(\s*['"]static['"]\s*,\s*filename\s*=\s*['"]js/(?P<module>[A-Za-z0-9_\-]+\.js)['"](?P<rest>[^)]*)\)"""
)
CONCATENATED_QUERY = re.compile(r"""\?v=[^'"`\s)]+""")
INJECTED_SCRIPT = re.compile(
    r"""_versioned_static\(\s*['"]js/(?P<module>[A-Za-z0-9_\-]+\.js)['"]\s*\)"""
)

#: Versioned by something that changes when the file changes, or at worst when
#: the application restarts. A returning browser re-fetches.
VERSIONED = 'versioned'
#: A version string typed into the source by hand. It does not change when the
#: file changes, so the browser keeps serving its cached copy.
FROZEN = 'frozen'
#: No version at all.
UNVERSIONED = 'unversioned'

TEMPLATE = 'template'
DYNAMIC = 'dynamic'
INJECTED = 'injected'

#: The canonical mechanism: templates/_coachboard_assets.html publishes the
#: application asset version, and every dynamic loader builds its URL through
#: this helper. See asset_versioning.py for the server half.
CANONICAL_ASSET_HELPER = re.compile(r'CoachBoardAssets\s*\.\s*url\s*\(')

#: Expressions that produce a version at runtime rather than from a literal.
RUNTIME_VERSION = re.compile(
    r'CoachBoardAssets|coachboard-asset-version|getmtime|asset_version|ASSET_VERSION'
)


def all_modules():
    """Every JavaScript file shipped in static/js."""
    return {path.name for path in JS_DIR.glob('*.js')}


def _function_body(source, brace_index):
    depth = 0
    for position in range(brace_index, len(source)):
        character = source[position]
        if character == '{':
            depth += 1
        elif character == '}':
            depth -= 1
            if depth == 0:
                return source[brace_index:position + 1]
    return ''


def _loader_functions(source):
    """Functions in this file that inject a ``<script>`` tag.

    Found by shape -- a body that creates an element and assigns ``.src`` --
    rather than by name, so ``loadScript``, ``loadOnce``, ``ensureClockControls``
    and anything added later are all recognised.
    """
    loaders = {}
    for match in re.finditer(r'function\s+(\w+)\s*\(([^)]*)\)\s*\{', source):
        body = _function_body(source, match.end() - 1)
        if body and 'createElement' in body and re.search(r'\.src\s*=', body):
            loaders[match.group(1)] = body
    return loaders


def _versioning_names(source):
    """Names whose call applies a runtime version to the URL they are given.

    Resolved to a fixpoint so an indirection chain is followed: in
    ``navigation_v2.js``, ``loadScript`` versions its argument only because it
    calls ``versionedHelperSrc``, which is what actually reads the version.
    """
    bodies = {}
    for match in re.finditer(r'function\s+(\w+)\s*\(([^)]*)\)\s*\{', source):
        body = _function_body(source, match.end() - 1)
        if body:
            bodies[match.group(1)] = body

    versioning = {name for name, body in bodies.items() if RUNTIME_VERSION.search(body)}

    changed = True
    while changed:
        changed = False
        for name, body in bodies.items():
            if name in versioning:
                continue
            if any(re.search(rf'\b{re.escape(other)}\s*\(', body) for other in versioning):
                versioning.add(name)
                changed = True

    return versioning


def _statement_at(source, index):
    """The statement text surrounding ``index``.

    Load sites span multiple lines here -- a src can be built from concatenated
    string literals -- so a line-based reader undercounts.
    """
    start = max(
        source.rfind(';', 0, index),
        source.rfind('{', 0, index),
        source.rfind('\n\n', 0, index),
    ) + 1
    end = source.find(';', index)
    if end == -1:
        end = len(source)
    return source[start:end + 1]


def _in_comment(source, index):
    line_start = source.rfind('\n', 0, index) + 1
    line = source[line_start:index]
    if '//' in line or line.lstrip().startswith('*'):
        return True
    open_block = source.rfind('/*', 0, index)
    if open_block == -1:
        return False
    return source.find('*/', open_block) > index


def scan_js_source(name, source):
    """Load sites performed by one JavaScript source.

    Separated from the directory walk so the scanner can be exercised against
    synthetic input, independently of what CoachBoard happens to contain.
    """
    sites = []
    loaders = _loader_functions(source)
    versioning = _versioning_names(source)
    loader_call = re.compile(
        r'\b(' + '|'.join(re.escape(loader) for loader in loaders) + r')\s*\('
    ) if loaders else None

    for match in MODULE_URL.finditer(source):
        if _in_comment(source, match.start()):
            continue

        statement = _statement_at(source, match.start())
        is_src_assignment = re.search(r'\.src\s*=', statement)
        # document.write('<script src="...">') is a fourth loading mechanism,
        # used by live_game_inning_clarity.js while the document is still
        # parsing. An earlier version of this scan missed it entirely.
        is_written_tag = re.search(r'src\s*=\s*[\'"\\]', statement)
        is_loader_call = bool(loader_call and loader_call.search(statement))
        if not (is_src_assignment or is_written_tag or is_loader_call):
            continue

        query = match.group('query') or ''
        if not query:
            # A src can be built from two concatenated string literals, putting
            # the query outside the URL match.
            concatenated = CONCATENATED_QUERY.search(statement)
            if concatenated:
                query = concatenated.group(0)

        if query:
            status = FROZEN
        elif CANONICAL_ASSET_HELPER.search(statement) or any(
            re.search(rf'\b{re.escape(helper)}\s*\(', statement)
            for helper in versioning
        ):
            status = VERSIONED
        else:
            status = UNVERSIONED

        sites.append({
            'kind': DYNAMIC,
            'loader': name,
            'module': match.group('module'),
            'query': query,
            'status': status,
            'line': source.count('\n', 0, match.start()) + 1,
        })

    return sites


def dynamic_load_sites():
    """Every runtime ``<script>`` injection performed by a JavaScript module."""
    sites = []
    for path in sorted(JS_DIR.glob('*.js')):
        sites.extend(scan_js_source(path.name, path.read_text()))
    return sites


def rendered_templates():
    """Templates the application can actually render.

    A template no view renders, and no other template extends or includes, puts
    nothing on a page -- counting its script tags would report loads that never
    happen. The audit found five such orphans at 1a06777.
    """
    python_sources = '\n'.join(
        path.read_text()
        for path in ROOT.rglob('*.py')
        if 'tests' not in path.parts
    )
    template_sources = '\n'.join(
        path.read_text() for path in TEMPLATE_DIR.glob('*.html')
    )

    rendered = set()
    for path in TEMPLATE_DIR.glob('*.html'):
        name = path.name
        if name in python_sources or f"'{name}'" in template_sources or f'"{name}"' in template_sources:
            rendered.add(name)
    return rendered


def orphan_templates():
    """Templates on disk that nothing can render."""
    return {path.name for path in TEMPLATE_DIR.glob('*.html')} - rendered_templates()


def template_load_sites():
    """Modules loaded directly by a Jinja template that can be rendered."""
    sites = []
    renderable = rendered_templates()
    for path in sorted(TEMPLATE_DIR.glob('*.html')):
        if path.name not in renderable:
            continue
        source = path.read_text()
        for match in TEMPLATE_SCRIPT.finditer(source):
            sites.append({
                'kind': TEMPLATE,
                'loader': path.name,
                'module': match.group('module'),
                'query': '',
                'status': VERSIONED if 'asset_version' in match.group('rest') else UNVERSIONED,
                'line': source.count('\n', 0, match.start()) + 1,
            })
    return sites


def injected_load_sites():
    """Modules injected into the response HTML by an after_app_request hook.

    ``_versioned_static`` versions by file mtime, which is the only mechanism in
    the codebase that changes when the file itself changes.
    """
    sites = []
    for path in sorted(BLUEPRINT_DIR.glob('*.py')):
        source = path.read_text()
        for match in INJECTED_SCRIPT.finditer(source):
            sites.append({
                'kind': INJECTED,
                'loader': path.name,
                'module': match.group('module'),
                'query': '',
                'status': VERSIONED,
                'line': source.count('\n', 0, match.start()) + 1,
            })
    return sites


def all_load_sites():
    return template_load_sites() + injected_load_sites() + dynamic_load_sites()


def load_graph():
    """``{loader: {modules it loads}}`` across all three mechanisms."""
    graph = {}
    for site in all_load_sites():
        graph.setdefault(site['loader'], set()).add(site['module'])
    return graph


def entry_modules():
    """Modules a page loads without another module asking for them."""
    return {
        site['module']
        for site in template_load_sites() + injected_load_sites()
    }


def walk(graph, entries):
    """Everything reachable from ``entries`` by following ``graph``.

    A pure function over plain data, so the traversal can be verified against a
    synthetic graph instead of against whatever CoachBoard's own load graph
    happens to look like today.
    """
    seen = set()
    queue = list(entries)
    while queue:
        node = queue.pop()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(graph.get(node, set()))
    return seen


def reachable_modules():
    """Modules reachable from a page entry point, following chain loads."""
    return walk(load_graph(), entry_modules())


def effective_url(site):
    """The URL a browser would request for this load site.

    Every canonically versioned site resolves to the same string, whichever of
    the four loading mechanisms produced it -- which is the whole point of the
    mechanism, and what makes duplicate-URL detection mean something. An
    earlier version of this helper compared (kind, status, query) instead, so
    a module loaded by a template *and* by another module always looked like
    two URLs even when both were spelled identically.
    """
    base = f"/static/js/{site['module']}"
    if site['status'] == VERSIONED:
        return f'{base}?v={{asset_version}}'
    if site['status'] == FROZEN:
        return f"{base}{site['query']}"
    return base


def select_page_load_sites(sites, shells, reachable):
    """Filter ``sites`` down to the ones that occur on one rendered page.

    Pure, so it can be exercised against a synthetic graph. Each kind of load
    site answers "is this on the page?" differently, and conflating them is a
    real source of wrong answers:

    ``template``
        On the page only if the tag is in the rendered template or the shell
        it extends. A tag in some other template is a different page.

    ``injected``
        Always included. Every server-side injection in this tree lives in a
        hook gated on ``/game/<id>``, which is the page this is used for. A
        second injector on another route would need this revisited.

    ``dynamic``
        On the page only if the *loader module* is itself reachable. Testing
        the loaded module instead is wrong: a module reachable via one loader
        would drag in load sites from unrelated loaders that the page never
        runs -- e.g. an orphan module that also loads clock controls would be
        counted against /game/<id> purely because the contract loads clock
        controls too.
    """
    selected = []
    for site in sites:
        kind = site['kind']
        if kind == TEMPLATE:
            if site['loader'] in shells:
                selected.append(site)
        elif kind == INJECTED:
            selected.append(site)
        elif site['loader'] in reachable:
            selected.append(site)
    return selected


def page_entry_modules(shells):
    """Modules a page loads before any JavaScript runs."""
    return {
        site['module']
        for site in template_load_sites() + injected_load_sites()
        if site['kind'] == INJECTED or site['loader'] in shells
    }


def page_shells(template):
    """``template`` plus the shell it extends, if any."""
    shells = {template}
    source = (TEMPLATE_DIR / template).read_text()
    match = re.search(r"""\{%\s*extends\s*['"]([^'"]+)['"]""", source)
    if match:
        shells.add(match.group(1))
    return shells


def page_load_sites(template):
    """Every load site that occurs when ``template`` is the rendered page."""
    shells = page_shells(template)
    reachable = walk(load_graph(), page_entry_modules(shells))
    return select_page_load_sites(all_load_sites(), shells, reachable)


def page_loader_files(template):
    """``{module: {loader files}}`` for one rendered page.

    Keyed by loader *file*: two sites inside one loader are that module's own
    branching (an if/else, or two mutually exclusive route blocks) and are not
    two loaders racing to put the same script on the page.
    """
    by_module = {}
    for site in page_load_sites(template):
        by_module.setdefault(site['module'], set()).add(site['loader'])
    return by_module


def modules_loaded_under_multiple_urls():
    """Modules whose load sites do not agree on a single URL.

    A browser keys its cache on the full URL, so two spellings of the same
    module are two downloads and two executions.
    """
    spellings = {}
    for site in all_load_sites():
        spellings.setdefault(site['module'], set()).add(effective_url(site))
    return {
        module: sorted(variants)
        for module, variants in spellings.items()
        if len(variants) > 1
    }
