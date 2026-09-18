/**
 * CoachBoardDrag -- one gesture manager, many registered surfaces.
 *
 * WHY A SINGLETON, NOT ONE CONTROLLER PER BOARD
 *
 * The live boards are disjoint sibling elements, so per-root listeners
 * would never see each other's events. That is not the problem. The
 * problem is the rules that need a view of the *whole* pointer stream:
 *
 *   - "a second pointer cancels the drag" -- the cancelling pointerdown
 *     usually lands outside the armed root (the other card, the header,
 *     page background). A root-scoped listener is blind to it, and the
 *     result is an armed drag running underneath a pinch-zoom.
 *   - pointer capture retargets every later event for that pointer to
 *     the capturing root, so once armed, no second instance could
 *     coordinate even if it wanted to.
 *
 * So: one document-level owner, one armed gesture at a time.
 *
 * OWNERSHIP BOUNDARY
 *
 * This file owns gesture mechanics only -- activation, capture, ghost,
 * cancellation, click suppression, and hit-testing. It knows nothing
 * about players, positions, data attributes or saving. Each board keeps
 * its own movement and save semantics behind resolveSource/onDrop,
 * which is what lets On the Field refuse to drag the pitcher while Next
 * Inning deliberately allows it.
 *
 * INVARIANT: the manager never retains an element it borrowed from a
 * surface. Gesture state is plain data; a live element is obtained by
 * asking the surface -- findSource() during a drag, root() for capture
 * release and click suppression -- and dropped again within the same
 * event turn. That is what makes a rerender mid-drag survivable rather
 * than a stale-node crash.
 *
 * The one element held across turns is the drag ghost, which the
 * manager creates, owns, and is the only code able to remove. It is not
 * borrowed from anyone and cannot go stale under a rerender.
 * debugActive().borrowedElements exists to keep that line honest: it
 * counts elements in gesture state that are NOT the ghost, and is
 * asserted to be 0 while a drag is armed.
 */
(() => {
  'use strict';

  if (window.CoachBoardDrag && window.CoachBoardDrag.version === 1) return;

  const VERSION = 1;

  // Touch/pen arms on a deliberate hold. An ordinary swipe travels well
  // past the drift tolerance long before the timer fires, so it never
  // arms and the browser scrolls it natively.
  const LONG_PRESS_MS = 350;
  const DRIFT_TOLERANCE_PX = 10;

  // Mouse arms immediately on movement -- unchanged from both boards'
  // previous behavior.
  const MOUSE_THRESHOLD_PX = 8;

  const CLICK_SUPPRESSION_MS = 700;
  const GHOST_CLASS = 'cb-drag-ghost';
  const OVER_CLASS = 'cb-drag-over';
  const STYLE_ID = 'cb-drag-controller-styles';

  const surfaces = [];
  const suppressedSelectors = new Set();
  let installed = false;
  let active = null;
  let suppressClickUntil = 0;
  let suppressSurface = null;

  /* ------------------------------------------------------------ styles */

  function styleSheet() {
    let style = document.getElementById(STYLE_ID);
    if (!style) {
      style = document.createElement('style');
      style.id = STYLE_ID;
      style.textContent = `
        .${GHOST_CLASS}{
          position:fixed;z-index:8000;pointer-events:none;
          transform:translate(-50%,-50%) scale(1.04);
          max-width:170px;padding:8px 10px;
          border:2px solid #102a66;border-radius:10px;
          background:#fff;color:#172033;
          font-size:.7rem;font-weight:850;text-align:center;
          box-shadow:0 12px 28px rgba(16,24,40,.24);
        }
      `;
      document.head.appendChild(style);
    }
    return style;
  }

  /**
   * A long press on a phone races the OS: iOS raises its text-selection
   * callout at roughly half a second, so arming at 350ms gets in first
   * -- but only if the callout and selection are suppressed outright.
   * Without this a coach holding a player gets a selection bubble over
   * the drag.
   */
  function suppressNativeGestures(sourceSelector) {
    if (suppressedSelectors.has(sourceSelector)) return;
    suppressedSelectors.add(sourceSelector);
    styleSheet().textContent += `
      ${sourceSelector}{
        -webkit-touch-callout:none;
        -webkit-user-select:none;
        user-select:none;
        -webkit-tap-highlight-color:transparent;
      }
    `;
  }

  /* ----------------------------------------------------------- helpers */

  function surfaceFor(node) {
    if (!node) return null;
    for (const surface of surfaces) {
      const root = surface.root();
      if (root && root.contains(node)) return surface;
    }
    return null;
  }

  function clearHighlight() {
    document
      .querySelectorAll(`.${OVER_CLASS}`)
      .forEach(element => element.classList.remove(OVER_CLASS));
  }

  function highlight(surface, clientX, clientY) {
    clearHighlight();
    const element = document.elementFromPoint(clientX, clientY);
    const target = element && element.closest
      ? element.closest(surface.targetSelector)
      : null;
    if (target) target.classList.add(OVER_CLASS);
  }

  function dropTarget(surface, clientX, clientY) {
    const element = document.elementFromPoint(clientX, clientY);
    const node = element && element.closest
      ? element.closest(surface.targetSelector)
      : null;
    if (!node) return null;
    try {
      return surface.resolveTarget(node) || null;
    } catch (_) {
      return null;
    }
  }

  function suppressClicks(surface) {
    suppressClickUntil = Date.now() + CLICK_SUPPRESSION_MS;
    // Keep the surface, not its root element. Holding the element would
    // retain it across event turns -- the one thing this manager must
    // never do -- and it silently stops matching the moment a board
    // swaps its card node, letting a stray post-drop click through.
    suppressSurface = surface;
  }

  /* ------------------------------------------------- the one teardown */

  /**
   * Every exit runs through here: drop, cancel, pointercancel, stale
   * DOM, second pointer, abandoned drag. One place to remove the ghost
   * means a new exit path cannot leak one.
   */
  function teardown() {
    if (!active) return;
    window.clearTimeout(active.armTimer);
    if (active.ghost) active.ghost.remove();
    try {
      const root = active.surface.root();
      if (root && root.hasPointerCapture?.(active.pointerId)) {
        root.releasePointerCapture(active.pointerId);
      }
    } catch (_) {
      /* nothing holds the capture; nothing to release */
    }
    clearHighlight();
    active = null;
  }

  /* ------------------------------------------------------- activation */

  function arm() {
    if (!active || active.armed) return;
    active.armed = true;
    window.clearTimeout(active.armTimer);

    const ghost = document.createElement('div');
    ghost.className = `${GHOST_CLASS} ${GHOST_CLASS}--${active.surface.id}`;
    ghost.textContent = active.source.label || active.source.key || '';
    ghost.style.left = `${active.x}px`;
    ghost.style.top = `${active.y}px`;
    document.body.appendChild(ghost);
    active.ghost = ghost;

    // Capture on the card, never on the source element: the source is
    // exactly what a rerender destroys, and losing the capture target
    // silently drops pointerup and strands the gesture.
    //
    // The element is not kept. teardown() re-resolves root() and
    // releases only if that current root still holds the capture -- if
    // the board swapped its card, the capture went with the detached
    // node and there is nothing to release.
    const root = active.surface.root();
    if (root && root.setPointerCapture) {
      try {
        root.setPointerCapture(active.pointerId);
      } catch (_) {
        /* capture is an optimisation, not a requirement */
      }
    }

    suppressClicks(active.surface);
  }

  /* ---------------------------------------------------------- handlers */

  function onPointerDown(event) {
    // A second pointer means pinch or a stray finger, never a drag.
    if (active && event.pointerId !== active.pointerId) {
      teardown();
      return;
    }
    if (active) teardown();
    if (event.isPrimary === false) return;
    if (event.button !== undefined && event.button !== 0) return;

    const surface = surfaceFor(event.target);
    if (!surface) return;

    try {
      if (!surface.canStart()) return;
    } catch (_) {
      return;
    }

    const node = event.target.closest
      ? event.target.closest(surface.sourceSelector)
      : null;
    if (!node) return;

    let source = null;
    try {
      source = surface.resolveSource(node);
    } catch (_) {
      source = null;
    }
    if (!source) return;

    active = {
      surface,
      source,
      pointerId: event.pointerId,
      pointerType: event.pointerType,
      startX: event.clientX,
      startY: event.clientY,
      x: event.clientX,
      y: event.clientY,
      armed: false,
      ghost: null,
      armTimer: 0,
    };

    if (event.pointerType !== 'mouse') {
      // Deliberately does not preventDefault: until the hold completes
      // this is an ordinary touch, and the browser must be free to
      // scroll or pinch with it.
      active.armTimer = window.setTimeout(arm, LONG_PRESS_MS);
    }
  }

  function onPointerMove(event) {
    if (!active || event.pointerId !== active.pointerId) return;

    active.x = event.clientX;
    active.y = event.clientY;

    const distance = Math.hypot(
      event.clientX - active.startX,
      event.clientY - active.startY
    );

    if (!active.armed) {
      if (active.pointerType === 'mouse') {
        if (distance < MOUSE_THRESHOLD_PX) return;
        arm();
      } else {
        // Drift past the tolerance before the hold completes means the
        // coach is scrolling, not picking a player up. Abandon the arm
        // and leave the gesture to the browser.
        if (distance > DRIFT_TOLERANCE_PX) teardown();
        return;
      }
    }

    if (!active) return;

    // Self-healing stale check: the board answers whether its own
    // source is still on screen, so the manager never learns a
    // selector or a data attribute.
    let stillThere = null;
    try {
      stillThere = active.surface.findSource(active.source);
    } catch (_) {
      stillThere = null;
    }
    if (!stillThere) {
      teardown();
      return;
    }

    event.preventDefault();
    if (active.ghost) {
      active.ghost.style.left = `${event.clientX}px`;
      active.ghost.style.top = `${event.clientY}px`;
    }
    highlight(active.surface, event.clientX, event.clientY);
  }

  /**
   * Armed-only scroll suppression. This, not touch-action and not
   * pointermove, is the mechanism that stops the page scrolling under
   * an armed drag.
   *
   * touch-action alone cannot do the job: the browser latches it when
   * the gesture starts, so flipping it after the hold completes is
   * ignored. preventDefault on a non-passive touchmove does stop an
   * in-progress scroll -- and gating it on `armed` is what keeps an
   * unarmed swipe scrolling natively.
   *
   * It must stay on document. Pointer capture retargets *Pointer*
   * events to the capturing element; it does not retarget *Touch*
   * events, which keep firing at the original touch target. Moving
   * this listener onto a surface root would therefore silently stop it
   * seeing the touchmoves of a captured gesture -- and with it, the
   * only thing holding the scroll back.
   */
  function onTouchMove(event) {
    if (active && active.armed) event.preventDefault();
  }

  function onPointerUp(event) {
    if (!active || event.pointerId !== active.pointerId) return;

    const {surface, source, armed} = active;
    const x = event.clientX;
    const y = event.clientY;

    if (!armed) {
      teardown();
      return;
    }

    const target = dropTarget(surface, x, y);
    teardown();

    event.preventDefault();
    event.stopPropagation();
    suppressClicks(surface);

    if (!target) return;
    try {
      surface.onDrop(source, target);
    } catch (_) {
      /* board-owned; a failed save is the board's to report */
    }
  }

  function onPointerCancel(event) {
    if (active && event.pointerId !== active.pointerId) return;
    teardown();
  }

  function onClick(event) {
    if (Date.now() >= suppressClickUntil) return;
    if (!suppressSurface || !event.target.closest) return;
    const root = suppressSurface.root();
    if (!root || !root.contains(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
  }

  // One table, used to add and remove the same set. removeEventListener
  // only matches on type + listener + capture, so the options must be
  // declared once rather than repeated at both call sites.
  const DOCUMENT_LISTENERS = [
    ['pointerdown', onPointerDown, {capture: true, passive: true}],
    ['pointermove', onPointerMove, {capture: true, passive: false}],
    ['pointerup', onPointerUp, {capture: true, passive: false}],
    ['pointercancel', onPointerCancel, {capture: true, passive: true}],
    ['touchmove', onTouchMove, {capture: true, passive: false}],
    ['click', onClick, {capture: true}],
  ];

  function install() {
    if (installed) return;
    installed = true;
    DOCUMENT_LISTENERS.forEach(([type, handler, options]) => {
      document.addEventListener(type, handler, options);
    });
  }

  function uninstall() {
    if (!installed) return;
    installed = false;
    DOCUMENT_LISTENERS.forEach(([type, handler, options]) => {
      document.removeEventListener(type, handler, {capture: options.capture});
    });
    suppressSurface = null;
    suppressClickUntil = 0;
  }

  /* ------------------------------------------------------------- API */

  function registerSurface(config) {
    styleSheet();
    if (config.sourceSelector) suppressNativeGestures(config.sourceSelector);
    surfaces.push(config);
    install();

    return {
      /** The board's explicit pre-rerender cancel. */
      cancel() {
        if (active && active.surface === config) teardown();
      },
      isDragging() {
        return Boolean(active && active.surface === config && active.armed);
      },
      unregister() {
        const index = surfaces.indexOf(config);
        if (index >= 0) surfaces.splice(index, 1);
        if (active && active.surface === config) teardown();
        if (suppressSurface === config) suppressSurface = null;
        // The listener set exists to serve surfaces; with none left it
        // is pure overhead on every pointer event on the page.
        if (!surfaces.length) uninstall();
      },
    };
  }

  window.CoachBoardDrag = {
    version: VERSION,
    registerSurface,
    surfaceIds: () => surfaces.map(surface => surface.id),
    listenersInstalled: () => installed,
    /** Drop every surface and unwind the listener set. */
    unregisterAll() {
      teardown();
      surfaces.length = 0;
      uninstall();
    },
    // Read-only view of the current gesture, for diagnostics and tests.
    debugActive: () => (active
      ? {
          surfaceId: active.surface.id,
          armed: active.armed,
          pointerType: active.pointerType,
          // Elements held in gesture state other than the ghost the
          // manager owns. The invariant says this is always 0.
          borrowedElements: Object.entries(active)
            .filter(([key, value]) => key !== 'ghost' && value instanceof Element)
            .map(([key]) => key),
        }
      : null),
    longPressMs: LONG_PRESS_MS,
    driftTolerancePx: DRIFT_TOLERANCE_PX,
  };
})();
