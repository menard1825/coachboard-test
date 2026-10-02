/*
 * Focus around the live game's dialogs (Change Pitcher, Fill / Move on the
 * field, Who plays ... next inning, and the rest), following Bootstrap's own
 * modal lifecycle rather than replacing it.
 *
 * Bootstrap 5.3 hides a dialog by setting aria-hidden="true" on it
 * (_hideModal) without first moving focus out, so the button the coach just
 * tapped -- or the dialog itself after Escape -- is still focused inside an
 * aria-hidden element, which the browser reports and assistive technology
 * mishandles. And it returns focus to the opener only for data-bs-toggle
 * triggers; these dialogs are all opened from script, so focus fell back to
 * the page.
 *
 *   show.bs.modal    remember the control that opened the dialog (or the one
 *                    just tapped -- a tapped button often never takes focus
 *                    on a phone), with a way to find it again if the board
 *                    redraws it;
 *   hide.bs.modal    unless the hide was cancelled, move focus out of the
 *                    dialog before Bootstrap marks it aria-hidden;
 *   hidden.bs.modal  return focus to that control, or its redrawn copy. When
 *                    another dialog is open (one dialog leading to the next),
 *                    that dialog owns focus: it inherits where to return to.
 */
(function () {
  'use strict';

  if (window.__cbModalFocus) return;
  window.__cbModalFocus = true;

  const openers = new WeakMap();
  const KEYS = ['data-cb-position', 'data-next-position', 'data-now-next', 'data-plan-inning', 'data-next-player'];
  let tapped = null;

  // How to find the same control again after the board redraws it.
  function selectorFor(element) {
    if (!element || element === document.body) return '';
    if (element.id) return `#${CSS.escape(element.id)}`;
    const key = KEYS.find(name => element.hasAttribute(name));
    return key ? `[${key}="${CSS.escape(element.getAttribute(key))}"]` : '';
  }

  function record(element) {
    return element ? {element, selector: selectorFor(element)} : null;
  }

  function usable(element) {
    return Boolean(
      element &&
      element.isConnected &&
      !element.disabled &&
      element.getClientRects().length &&
      !element.closest('[aria-hidden="true"], [inert], .modal:not(.show)')
    );
  }

  function resolve(saved) {
    if (!saved) return null;
    if (usable(saved.element)) return saved.element;
    const again = saved.selector ? document.querySelector(saved.selector) : null;
    return usable(again) ? again : null;
  }

  // The control a tap landed on, for openers that never took focus.
  document.addEventListener('pointerdown', event => {
    const control = event.target.closest?.('button, a[href], [role="button"], [tabindex], input, select');
    tapped = control ? {element: control, at: Date.now()} : null;
  }, true);

  document.addEventListener('show.bs.modal', event => {
    const modal = event.target;
    if (!(modal instanceof Element) || !modal.classList.contains('modal')) return;

    const active = document.activeElement;
    let opener = event.relatedTarget || null;
    if (!opener && active && active !== document.body && !modal.contains(active)) opener = active;
    if (!opener && tapped && Date.now() - tapped.at < 1500 && !modal.contains(tapped.element)) opener = tapped.element;

    // Opened from inside another dialog: return where that one would have.
    const from = opener?.closest?.('.modal');
    const saved = from && from !== modal && openers.get(from) ? openers.get(from) : record(opener);
    if (saved) openers.set(modal, saved);
  });

  document.addEventListener('hide.bs.modal', event => {
    const modal = event.target;
    if (event.defaultPrevented || !(modal instanceof Element)) return;
    // Out of the dialog before Bootstrap sets aria-hidden on it.
    if (modal.contains(document.activeElement)) document.activeElement.blur();
  });

  document.addEventListener('hidden.bs.modal', event => {
    const modal = event.target;
    if (!(modal instanceof Element)) return;
    const saved = openers.get(modal);
    openers.delete(modal);

    // One dialog led to the next: that one owns focus, and returns it later.
    const open = document.querySelector('.modal.show');
    if (open) {
      if (saved && !openers.has(open)) openers.set(open, saved);
      return;
    }

    const target = resolve(saved);
    if (target && document.activeElement !== target) target.focus({preventScroll: true});
  });
})();
