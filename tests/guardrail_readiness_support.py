"""Static analysis of readiness polling and the readiness event contract.

``tests/guardrail_js_support.py`` answers "how does this file reach the
browser". It deliberately cannot answer "how many timers in this page fetch the
same URL", because its comparisons are set-based over *load sites*: three
modules each owning a ``setInterval`` against
``/api/game-day/<id>/readiness`` look exactly like three ordinary modules.

That blind spot is what let readiness reach 26 requests/minute on a pregame
page. This module closes it by resolving, per file, which interval callbacks
actually reach a readiness ``fetch`` -- following the callback through the
file's own call graph, because the callback is usually a bare identifier or an
arrow that delegates (``setInterval(refresh, 5000)``,
``setInterval(() => { ... refresh(); }, 10000)``).

Everything here is exercised against synthetic sources as well as the real
tree, so a scanner that silently stops matching fails its own tests rather
than quietly reporting zero pollers.
"""

import re

from guardrail_js_support import JS_DIR, _function_body, _in_comment


READINESS_FETCH = re.compile(r'game-day/[^\s\'"`]*readiness')

FUNCTION_DECL = re.compile(r'(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*\{')
ARROW_DECL = re.compile(
    r'(?:const|let|var)\s+(\w+)\s*=\s*'
    r'(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>\s*\{'
)

CALL = re.compile(r'\b(\w+)\s*\(')
BARE_IDENTIFIER = re.compile(r'^\w+$')

CUSTOM_EVENT = re.compile(r'new\s+CustomEvent\(\s*[\'"]([^\'"]+)[\'"]')
LISTENER = re.compile(r'addEventListener\(\s*[\'"]([^\'"]+)[\'"]')


def module_source(name):
    return (JS_DIR / name).read_text()


def functions(source):
    """Named functions in one source, mapped to their brace-matched bodies.

    Covers both ``function name(...) {`` and ``const name = (...) => {``, which
    are the two shapes CoachBoard uses for anything an interval delegates to.
    """
    found = {}
    for pattern in (FUNCTION_DECL, ARROW_DECL):
        for match in pattern.finditer(source):
            if _in_comment(source, match.start()):
                continue
            body = _function_body(source, match.end() - 1)
            if body:
                found[match.group(1)] = body
    return found


def _call_args(source, open_paren):
    """Split one call's argument list at top-level commas."""
    depth = 0
    args = []
    current = []
    for position in range(open_paren, len(source)):
        character = source[position]
        if character in '([{':
            depth += 1
            if depth == 1:
                continue
        elif character in ')]}':
            depth -= 1
            if depth == 0:
                args.append(''.join(current).strip())
                return args
        if depth == 1 and character == ',':
            args.append(''.join(current).strip())
            current = []
            continue
        current.append(character)
    return args


def _fetches_readiness(body):
    """True when ``body`` names the readiness URL in live code.

    Comment-aware on purpose. The first version of this scanner was not, and
    the ownership comment added to game_setup_ux.js by this very slice made
    ``start()`` register as a readiness fetcher. A guardrail that counts
    pollers must not be steerable by prose.
    """
    return any(
        not _in_comment(body, match.start())
        for match in READINESS_FETCH.finditer(body)
    )


def readiness_fetchers(source):
    """Functions whose own body issues a readiness request."""
    return {
        name for name, body in functions(source).items()
        if _fetches_readiness(body)
    }


def _reaches_readiness(seeds, table, fetchers):
    seen = set()
    queue = list(seeds)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in fetchers:
            return True
        body = table.get(name)
        if body:
            queue.extend(CALL.findall(body))
    return False


def interval_sites(source):
    """Every ``setInterval`` call in one source, with its delay and callback."""
    sites = []
    for match in re.finditer(r'setInterval\s*\(', source):
        if _in_comment(source, match.start()):
            continue
        args = _call_args(source, match.end() - 1)
        if len(args) < 2:
            continue
        delay = args[1].strip()
        sites.append({
            'callback': args[0].strip(),
            'delay_ms': int(delay) if delay.isdigit() else None,
        })
    return sites


def readiness_intervals_in_source(source):
    """Interval sites in one source whose callback reaches a readiness fetch."""
    table = functions(source)
    fetchers = readiness_fetchers(source)
    if not fetchers:
        return []

    polling = []
    for site in interval_sites(source):
        callback = site['callback']
        if BARE_IDENTIFIER.match(callback):
            seeds = {callback}
        else:
            seeds = set(CALL.findall(callback))
        if _fetches_readiness(callback) or _reaches_readiness(seeds, table, fetchers):
            polling.append(site)
    return polling


def readiness_intervals():
    """Every periodic readiness poller shipped in static/js, by module."""
    found = {}
    for path in sorted(JS_DIR.glob('*.js')):
        sites = readiness_intervals_in_source(path.read_text())
        if sites:
            found[path.name] = sites
    return found


def dispatched_events(source):
    return set(CUSTOM_EVENT.findall(source))


def listened_events(source):
    return set(LISTENER.findall(source))


def listener_callbacks(source, event_name):
    """Callback text for every ``addEventListener('<event_name>', ...)`` call."""
    callbacks = []
    pattern = re.compile(
        r'addEventListener\(\s*[\'"]' + re.escape(event_name) + r'[\'"]\s*,'
    )
    for match in pattern.finditer(source):
        if _in_comment(source, match.start()):
            continue
        open_paren = source.index('(', match.start())
        args = _call_args(source, open_paren)
        if len(args) >= 2:
            callbacks.append(args[1])
    return callbacks


def body_without_listener_callbacks(body):
    """``body`` with every nested ``addEventListener`` callback removed.

    Needed to tell a *direct* call apart from one that only happens inside a
    handler. start() contains both ``refreshReadiness();`` on init and another
    inside its visibilitychange handler, so a plain substring test over the
    whole body cannot distinguish the two fallback paths -- it passes even
    when the init fetch is gone.
    """
    stripped = body
    for match in re.finditer(r'addEventListener\s*\(', body):
        if _in_comment(body, match.start()):
            continue
        args = _call_args(body, match.end() - 1)
        if len(args) >= 2 and args[1]:
            stripped = stripped.replace(args[1], '')
    return stripped
