"""Real browser touch input for Playwright tests, via CDP.

Playwright's `page.touchscreen` only exposes `tap()`. It cannot express a
long-press, a drag, a drift, or multi-touch -- and `page.mouse` is useless
for this contract because it reports `pointerType: 'mouse'`, which is
exactly the branch the touch rules do not take.

`Input.dispatchTouchEvent` injects at the browser input pipeline, so the
compositor scrolls for real. That is the whole point: a test that asserts
"an ordinary swipe still scrolls" is only meaningful if the swipe is
capable of scrolling. Synthetic PointerEvents dispatched from page script
cannot scroll and cannot be prevented from scrolling, so they can never
prove that assertion either way.

Chromium only. Callers must skip on other engines.
"""


class TouchDriver:
    """Drives CDP touch input, tracking active points across events.

    CDP models touch as a state diff: every event carries the full set of
    currently-active points, and Chrome synthesises the individual
    press/move/release events from the change. So callers never assemble
    point lists themselves -- they move fingers by id and this class
    re-sends the whole set.
    """

    def __init__(self, page):
        self._page = page
        self._session = page.context.new_cdp_session(page)
        self._points = {}

    # -- plumbing ---------------------------------------------------

    def _payload(self):
        return [
            {'x': float(x), 'y': float(y), 'id': float(pid)}
            for pid, (x, y) in sorted(self._points.items())
        ]

    def _send(self, event_type):
        self._session.send(
            'Input.dispatchTouchEvent',
            {'type': event_type, 'touchPoints': self._payload(), 'modifiers': 0},
        )

    # -- gestures ---------------------------------------------------

    def down(self, x, y, finger=0):
        self._points[finger] = (x, y)
        self._send('touchStart')
        return self

    def move_to(self, x, y, finger=0, steps=1, pause_ms=0):
        """Move one finger, optionally interpolated.

        `steps` matters: a single 120px jump is not a swipe as far as the
        compositor is concerned, and will not scroll. Real swipes arrive
        as a stream of small deltas.
        """
        start_x, start_y = self._points[finger]
        for step in range(1, steps + 1):
            self._points[finger] = (
                start_x + (x - start_x) * step / steps,
                start_y + (y - start_y) * step / steps,
            )
            self._send('touchMove')
            if pause_ms:
                self._page.wait_for_timeout(pause_ms)
        return self

    def up(self, finger=0):
        self._points.pop(finger, None)
        self._send('touchEnd')
        return self

    def cancel(self):
        self._points.clear()
        self._send('touchCancel')
        return self

    def hold(self, ms):
        self._page.wait_for_timeout(ms)
        return self


def centre(locator):
    """Viewport centre of an element, scrolled into view first.

    Both CDP touch and page.mouse take viewport coordinates, so an
    element sitting below the fold yields a point that lands on whatever
    happens to be there instead. Flash banners accumulate across tests
    and push the boards down, which makes that a real failure mode --
    and one that reads as "the drag broke" rather than "the coordinates
    were off the screen". The bounds assertion makes it say so.
    """
    box = locator.bounding_box()
    assert box, f'no bounding box for {locator}'
    x = box['x'] + box['width'] / 2
    y = box['y'] + box['height'] / 2
    size = locator.page.viewport_size
    if size:
        assert 0 <= x <= size['width'] and 0 <= y <= size['height'], (
            f'{locator} centre ({x:.0f},{y:.0f}) is outside the '
            f"{size['width']}x{size['height']} viewport"
        )

    occluder = locator.page.evaluate(
        """([x, y]) => {
            const el = document.elementFromPoint(x, y);
            return el ? (el.tagName + '.' + (el.className || '')).slice(0, 120) : 'none';
        }""",
        [x, y],
    )
    assert reachable(locator), (
        f'{locator} centre ({x:.0f},{y:.0f}) is covered by {occluder}'
    )
    return x, y


def reachable(locator):
    """Does a tap at this element's centre actually land on it?

    The live boards sit under a sticky header. Scrolling can park a
    marker beneath it: the node is still present and still has a box,
    but a touch at its centre hits the header instead. The gesture then
    starts on nothing -- which looks exactly like "the drag never
    armed", with the source apparently right there. This is what made
    one On the Field test fail intermittently.
    """
    box = locator.bounding_box()
    if not box:
        return False
    x = box['x'] + box['width'] / 2
    y = box['y'] + box['height'] / 2
    size = locator.page.viewport_size
    if size and not (0 <= x <= size['width'] and 0 <= y <= size['height']):
        return False
    return locator.page.evaluate(
        """([node, x, y]) => {
            const el = document.elementFromPoint(x, y);
            return Boolean(el && (node.contains(el) || el.contains(node)));
        }""",
        [locator.element_handle(), x, y],
    )


def settle(locator, tries=20, pause_ms=100):
    """Wait until an element's box stops moving.

    Both boards re-render after their first state fetch, which shifts
    the markers. A coordinate measured before that lands on whatever
    moved into its place -- the gesture then starts on nothing and
    silently does nothing, which reads as "the drag never armed". Under
    full-suite load this was roughly one run in four.
    """
    page = locator.page
    previous = None
    for _ in range(tries):
        box = locator.bounding_box()
        if box and previous and all(
            abs(box[k] - previous[k]) < 0.5 for k in ('x', 'y', 'width', 'height')
        ):
            return box
        previous = box
        page.wait_for_timeout(pause_ms)
    return previous


def centres(*locators):
    """Centres of several elements, measured once everything has settled.

    Calling centre() twice is unsound: the second call can scroll the
    page and silently invalidate the first result, so the gesture then
    starts from a stale point and quietly does nothing. Worse, measuring
    a drop target mid-gesture scrolls *during* the drag. Scroll
    everything into view first, let layout settle, measure last.
    """
    for locator in locators:
        locator.scroll_into_view_if_needed()
    for locator in locators:
        settle(locator)
    # Clear the sticky header before measuring anything. Scrolling one
    # element out from under it can push another off-screen, so nudge
    # until every point is both on-screen and actually reachable, then
    # take all the measurements together.
    for _ in range(12):
        blocked = [loc for loc in locators if not reachable(loc)]
        if not blocked:
            break
        locators[0].page.mouse.wheel(0, -60)
        locators[0].page.wait_for_timeout(60)
    return [centre(locator) for locator in locators]


# -- observers ------------------------------------------------------

GHOST_SELECTOR = '[class*="drag-ghost"]'
DRAG_OVER_SELECTOR = '[class*="drag-over"]'

_GHOST_COUNTER = """
() => {
  window.__cbGhostCreations = 0;
  const seen = new WeakSet();
  const scan = () => {
    document.querySelectorAll('%s').forEach(node => {
      if (seen.has(node)) return;
      seen.add(node);
      window.__cbGhostCreations += 1;
    });
  };
  window.__cbGhostObserver?.disconnect();
  window.__cbGhostObserver = new MutationObserver(scan);
  window.__cbGhostObserver.observe(document.body, {childList: true, subtree: true});
  scan();
}
""" % GHOST_SELECTOR


def watch_ghosts(page):
    """Count ghost elements *created*, not currently present.

    Asserting `count == 0` after a gesture cannot tell "never created"
    apart from "created and torn down" -- and those are opposite bugs.
    An accidental drag that cleans up after itself still moved a player.
    """
    page.evaluate(_GHOST_COUNTER)


def ghost_creations(page):
    return page.evaluate('() => window.__cbGhostCreations ?? -1')


OVERLAY_SELECTOR = '#live-game-overlay'

_MAKE_SCROLLABLE = """
(selector) => {
  const overlay = document.querySelector(selector);
  if (!overlay) return {ok: false, reason: 'overlay not found'};

  let spacer = document.getElementById('cbTestScrollSpacer');
  if (!spacer) {
    spacer = document.createElement('div');
    spacer.id = 'cbTestScrollSpacer';
    spacer.setAttribute('aria-hidden', 'true');
    // Inline !important, because the boot-reveal stylesheet hides
    // children of the overlay it does not recognise. A plainly styled
    // spacer lands in the DOM, renders at zero height, and leaves the
    // test quietly asserting against whatever scroll the environment
    // happened to have.
    [
      ['display', 'block'], ['visibility', 'visible'], ['opacity', '1'],
      ['height', '1200px'], ['min-height', '1200px'],
      ['pointer-events', 'none'],
    ].forEach(([property, value]) => {
      spacer.style.setProperty(property, value, 'important');
    });
    overlay.appendChild(spacer);
  }

  overlay.scrollTop = 0;
  const maxScroll = overlay.scrollHeight - overlay.clientHeight;
  return {
    ok: maxScroll > 0 && spacer.getBoundingClientRect().height > 0,
    maxScroll,
    spacerHeight: spacer.getBoundingClientRect().height,
  };
}
"""


def make_overlay_scrollable(page):
    """Give the live overlay a deterministic scroll opportunity.

    At 390x844 the real app leaves nothing on the page able to scroll:
    body and html are pinned to the viewport and #live-game-overlay is a
    fixed-height scroller whose content fits exactly, so maxScroll is 0.
    A swipe test on that page asserts something physically impossible --
    and window.scrollY is the wrong thing to watch regardless, since the
    app deliberately does its scrolling inside the overlay.

    So the test manufactures the surface and verifies it exists before
    swiping, instead of depending on what the environment renders.
    """
    return page.evaluate(_MAKE_SCROLLABLE, OVERLAY_SELECTOR)


def overlay_scroll_top(page):
    return page.evaluate(
        '(selector) => document.querySelector(selector)?.scrollTop ?? -1',
        OVERLAY_SELECTOR,
    )
