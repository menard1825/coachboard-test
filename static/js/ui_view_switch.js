// Classic / Updated: the account menu's "Screens" choice (ui_view.py).
//
// The choice is this coach's, for this team, saved on the server so it follows
// them to every device. Switching reloads the page in the other view, so
// nothing the coach has entered may be lost on the way:
//
// - saves already queued (the Prepare Game defense, the Next Inning plan, a
//   defensive move on the live field) are waited for, and a save that fails
//   stops the switch -- the coach sees why and their edit stays on screen;
// - a form changed but not saved (Availability, a roster card...) or an open
//   window (the batting order editor...) stops the switch with the reason,
//   and nothing is reloaded.
//
// Live games always show the Updated screens; when a game goes live on this
// page, the page marks itself Updated without a reload.
(() => {
  if (window.CBViewSwitch) return;

  const body = document.body;
  const status = document.getElementById('cbViewSwitchStatus');
  const SETTLE_MS = 15000;

  const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  // --- forms changed but not saved -------------------------------------
  // A form's state is recorded the first time the coach touches it, and it
  // counts as changed only while it differs from that: a change undone by
  // hand is not "unsaved".
  const baselines = new WeakMap();

  function tracked(form) {
    return form instanceof HTMLFormElement
      && String(form.method || 'get').toLowerCase() === 'post'
      && !form.closest('[data-cb-unsaved-ignore]');
  }

  function serialize(form) {
    const parts = [];
    Array.from(form.elements).forEach((el) => {
      if (!el.name || el.disabled || el.type === 'submit' || el.type === 'button' || el.type === 'file') return;
      if (el.type === 'checkbox' || el.type === 'radio') parts.push(`${el.name}=${el.value}:${el.checked ? 1 : 0}`);
      else if (el.tagName === 'SELECT' && el.multiple) parts.push(`${el.name}=${Array.from(el.selectedOptions).map((o) => o.value).join(',')}`);
      else parts.push(`${el.name}=${el.value}`);
    });
    return parts.join('&');
  }

  document.addEventListener('focusin', (event) => {
    const form = event.target?.form || event.target?.closest?.('form');
    if (tracked(form) && !baselines.has(form)) baselines.set(form, serialize(form));
  }, true);
  // A click on a checkbox or switch can arrive without a focus event (Safari).
  document.addEventListener('pointerdown', (event) => {
    const form = event.target?.closest?.('form');
    if (tracked(form) && !baselines.has(form)) baselines.set(form, serialize(form));
  }, true);
  document.addEventListener('submit', (event) => {
    if (baselines.has(event.target)) baselines.delete(event.target);
  }, true);

  function formLabel(form) {
    const named = form.getAttribute('aria-label') || form.dataset.cbUnsavedLabel;
    if (named) return named;
    const submit = form.querySelector('[type="submit"]');
    const text = (submit?.textContent || '').trim().replace(/\s+/g, ' ');
    return text ? `"${text}"` : 'a form on this page';
  }

  function unsavedForms() {
    return Array.from(document.forms).filter((form) => (
      tracked(form) && baselines.has(form) && baselines.get(form) !== serialize(form)
    ));
  }

  // --- saves in progress -----------------------------------------------
  async function settleSaves() {
    const moves = window.CBQuickFieldMoves;
    if (moves?.whenIdle) {
      while (moves.busy?.()) {
        if (!(await moves.whenIdle())) return 'A defensive move didn’t save. Retry it, then switch.';
      }
    }

    const next = window.CBNextDefense;
    if (next?.flush) {
      try {
        await next.flush();
      } catch (_) {
        // Its own message is about ending the inning; the board already
        // shows what went wrong.
        return 'The next inning plan hasn’t saved yet. It’s still on screen; check it and your connection, then switch.';
      }
    }

    const pregame = window.CBPregameRotation;
    if (pregame?.isSaveInFlightOrQueued) {
      const began = Date.now();
      while (pregame.isSaveInFlightOrQueued()) {
        if (Date.now() - began > SETTLE_MS) return 'The defense plan is still saving. Wait a moment, then switch.';
        await sleep(100);
      }
      if (pregame.hasUnsyncedLocalState?.()) {
        return 'A change to the defense plan didn’t save. Retry the save, then switch.';
      }
    }
    return null;
  }

  // Everything that must be settled before this page may reload; null when
  // it is safe, or the reason it is not.
  async function readyToLeave() {
    const open = document.querySelector('.modal.show');
    if (open) {
      const title = open.querySelector('.modal-title')?.textContent?.trim();
      return `Finish or close ${title ? `"${title}"` : 'the open window'} first.`;
    }
    const forms = unsavedForms();
    if (forms.length) {
      return `You have changes that aren’t saved yet (${forms.map(formLabel).join(', ')}). Save or undo them, then switch.`;
    }
    return settleSaves();
  }

  function show(message) {
    if (!status) {
      window.alert(message);
      return;
    }
    status.textContent = message;
    status.hidden = !message;
  }

  // A tap on the notice dismisses it.
  status?.addEventListener('click', () => show(''));

  let switching = false;

  async function choose(view) {
    if (switching) return;
    if (view === body.dataset.cbViewChoice) return;
    switching = true;
    const buttons = Array.from(document.querySelectorAll('[data-cb-view-set]'));
    buttons.forEach((button) => { button.disabled = true; });
    try {
      show('');
      const reason = await readyToLeave();
      if (reason) {
        show(reason);
        return;
      }
      const response = await fetch('/api/account/view', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', Accept: 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({view}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status !== 'success') {
        show(data.message || 'Couldn’t change the view. Nothing changed; try again.');
        return;
      }
      // A save could have started while the preference was saving.
      const late = await readyToLeave();
      if (late) {
        body.dataset.cbViewChoice = view;
        show(`Your view is saved. ${late} Then reload to see it.`);
        return;
      }
      window.location.reload();
    } catch (error) {
      show('Couldn’t reach CoachBoard. Nothing changed; try again.');
    } finally {
      switching = false;
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest?.('[data-cb-view-set]');
    if (!button) return;
    event.preventDefault();
    // On a phone or iPad the menu is a side panel over the page: close it so
    // the coach sees what happens (a reload, or why the view didn't change).
    const panel = button.closest('.offcanvas.show');
    if (panel) window.bootstrap?.Offcanvas?.getInstance(panel)?.hide();
    choose(button.dataset.cbViewSet);
  });

  // A game that goes live on this page shows the Updated live screens.
  function markLive() {
    if (body.dataset.cbView === 'updated') return;
    body.dataset.cbView = 'updated';
    document.querySelectorAll('[data-cb-view-notice]').forEach((el) => el.remove());
  }
  document.addEventListener('coachboard:live-state', (event) => {
    const state = event.detail?.state || event.detail;
    if (state?.game?.is_live) markLive();
  });

  window.CBViewSwitch = Object.freeze({choose, readyToLeave});
})();
