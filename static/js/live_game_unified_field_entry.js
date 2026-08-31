(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  let suppressClickUntil = 0;
  let drag = null;
  let draft = null;
  let saveBusy = false;
  let enhanceQueued = false;
  let endInningBusy = false;

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function installStyles() {
    if (document.getElementById('cb-main-field-drag-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-main-field-drag-styles';
    style.textContent = `
      #cbQuickDefense .cb-qd-spot:not(.pitcher),
      #cbQuickDefense .cb-qd-bench-player{touch-action:none;cursor:grab}
      #cbQuickDefense .cb-qd-spot:not(.pitcher):active,
      #cbQuickDefense .cb-qd-bench-player:active{cursor:grabbing}
      #cbQuickDefense .cb-qd-spot.cb-main-drag-over .cb-qd-name{outline:4px solid rgba(16,42,102,.25);border-color:#102a66;background:#f4f7ff}
      #cbQuickDefense .cb-qd-bench-wrap.cb-main-drag-over{outline:4px solid rgba(22,107,56,.22);border-color:#5b9b70;background:#f0f8f2}
      #cbQuickDefense .cb-main-open .cb-qd-name{border:2px dashed #d49a22;background:#fff8e7;color:#8b5c00;font-weight:850}
      #cbQuickDefense .cb-main-draft-banner{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:9px 0 0;padding:8px 9px;border:1px solid #e4c46d;border-radius:10px;background:#fff9e9;color:#755100;font-size:.66rem;font-weight:720}
      #cbQuickDefense .cb-main-draft-banner .btn{min-height:34px;font-size:.65rem;font-weight:800;white-space:nowrap}
      .cb-main-drag-ghost{position:fixed;z-index:8000;pointer-events:none;transform:translate(-50%,-50%) scale(1.04);max-width:160px;border:2px solid #102a66;background:#fff;color:#172033;border-radius:10px;padding:8px 10px;font-size:.7rem;font-weight:850;text-align:center;box-shadow:0 12px 28px rgba(16,24,40,.24)}
    `;
    document.head.appendChild(style);
  }

  function positionForName(alignment, name) {
    return Object.entries(alignment || {}).find(([, value]) => value === name)?.[0] || 'BENCH';
  }

  function fieldPositions() {
    return [...document.querySelectorAll('#cbQuickDefense [data-cb-position]')]
      .map(button => String(button.dataset.cbPosition || '').toUpperCase())
      .filter(Boolean);
  }

  function currentSequence(state) {
    return (state?.rotation_events || []).reduce((max, event) => {
      if (event?.reverted) return max;
      return Math.max(max, Number(event?.sequence) || 0);
    }, 0);
  }

  async function loadAuthoritativeState() {
    const response = await fetch(`/api/live-game/${gameId}/state`, {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data?.game?.is_live) {
      throw new Error(data?.message || 'Live Game state is unavailable.');
    }
    return data;
  }

  async function loadNextInningPrep() {
    const response = await fetch(`/api/live-game/${gameId}/next-inning-prep`, {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data?.status === 'error') {
      throw new Error(data?.message || 'Next-inning defense is unavailable.');
    }
    return data;
  }

  async function advanceLockedNextInning() {
    const prep = await loadNextInningPrep();
    const confirmed = prep?.confirmed;
    if (!confirmed?.alignment || String(confirmed.inning || '') !== String(prep.next_inning || '')) {
      return null;
    }

    const liveState = await loadAuthoritativeState();
    if (String(liveState.current_inning || liveState.game?.live_current_inning || '1') !== String(prep.current_inning || '1')) {
      throw new Error('Another coach already moved the game forward. The live field has been refreshed.');
    }

    const response = await fetch(`/api/live-game/${gameId}/advance-inning`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        alignment: confirmed.alignment,
        base_sequence: currentSequence(liveState),
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data?.status === 'error') {
      throw new Error(data?.message || `Unable to start Inning ${prep.next_inning}.`);
    }
    return {nextInning: String(prep.next_inning), delta: data.delta || null};
  }

  function lockedNextInningIsVisible() {
    const ready = document.querySelector('#live-board-prep-v3 .nxd-status.ready');
    if (!ready) return false;
    const badge = ready.querySelector('.nxd-badge');
    return /LOCKED IN/i.test(String(badge?.textContent || ready.textContent || ''));
  }

  function openNextDefenseEditor() {
    const change = document.querySelector('#live-board-prep-v3 [data-bp-action="adjust"]');
    if (change && !change.disabled) change.click();
  }

  function interceptLockedEndInning(event) {
    const button = event.target.closest?.('#liveEndInningBtn');
    if (!button || !lockedNextInningIsVisible()) return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    if (endInningBusy || button.disabled) return;
    endInningBusy = true;
    button.disabled = true;

    advanceLockedNextInning()
      .then(result => {
        if (!result) {
          endInningBusy = false;
          if (button.isConnected) button.disabled = false;
          openNextDefenseEditor();
          return;
        }

        clearDraft({restore: true});
        setSaveBadge('', `Inning ${result.nextInning} started`);
        endInningBusy = false;
        window.setTimeout(() => {
          if (button.isConnected) button.disabled = false;
        }, 900);
      })
      .catch(error => {
        endInningBusy = false;
        if (button.isConnected) button.disabled = false;
        window.alert(`CoachBoard could not start the locked-in next inning. ${error.message}`);
        openNextDefenseEditor();
      });
  }

  async function ensureDraft() {
    if (draft) return draft;
    const state = await loadAuthoritativeState();
    draft = {
      baseAlignment: {...(state.current_alignment || {})},
      alignment: {...(state.current_alignment || {})},
      roster: [...(state.roster || [])],
      baseSequence: currentSequence(state),
    };
    return draft;
  }

  function rosterLabel(name, roster = draft?.roster || []) {
    const player = roster.find(item => item.name === name);
    const number = String(player?.number ?? '').trim();
    return number ? `#${number} ${name}` : name;
  }

  function setSaveBadge(mode, message) {
    const badge = document.querySelector('#cbQuickDefense .cb-save-state');
    if (!badge) return;
    badge.classList.remove('saving', 'error');
    if (mode) badge.classList.add(mode);
    const text = badge.querySelector('span');
    if (text && text.textContent !== message) text.textContent = message;
  }

  function renderDraft() {
    if (!draft) return;
    const card = document.getElementById('cbQuickDefense');
    if (!card) return;

    const assigned = new Set(Object.values(draft.alignment).filter(Boolean));
    card.querySelectorAll('[data-cb-position]').forEach(button => {
      const pos = String(button.dataset.cbPosition || '').toUpperCase();
      const name = draft.alignment[pos] || '';
      button.dataset.cbMovePlayer = name || 'Open';
      button.disabled = false;
      button.classList.toggle('cb-main-open', !name);
      const label = button.querySelector('.cb-qd-name');
      const desiredLabel = name ? rosterLabel(name) : 'Open — choose player';
      if (label && label.textContent !== desiredLabel) label.textContent = desiredLabel;
    });

    const benchPlayers = draft.roster.filter(player => !assigned.has(player.name));
    const benchHost = card.querySelector('.cb-qd-bench');
    if (benchHost) {
      const benchHtml = benchPlayers.length
        ? benchPlayers.map(player => {
            const number = String(player.number ?? '').trim();
            const label = number ? `#${number} ${player.name}` : player.name;
            return `<button type="button" class="cb-qd-bench-player" data-cb-move-player="${esc(player.name)}"><span>${esc(label)}</span><span class="cb-bench-note">Bench now</span></button>`;
          }).join('')
        : '<span class="small text-muted">No players are on the bench.</span>';
      if (benchHost.innerHTML !== benchHtml) benchHost.innerHTML = benchHtml;
    }

    const benchTitle = card.querySelector('.cb-qd-bench-head strong');
    const benchTitleText = `Bench now · ${benchPlayers.length}`;
    if (benchTitle && benchTitle.textContent !== benchTitleText) benchTitle.textContent = benchTitleText;

    const missing = fieldPositions().filter(pos => !draft.alignment[pos]);
    let banner = card.querySelector('.cb-main-draft-banner');
    if (missing.length) {
      if (!banner) {
        banner = document.createElement('div');
        banner.className = 'cb-main-draft-banner';
        card.querySelector('.cb-qd-bench-wrap')?.insertAdjacentElement('afterend', banner);
      }
      const bannerHtml = `<span><strong>${esc(missing.join(', '))} open.</strong> Keep dragging players until every position is filled; CoachBoard will save automatically.</span><button type="button" class="btn btn-sm btn-outline-secondary" data-cb-cancel-main-draft>Cancel</button>`;
      if (banner.innerHTML !== bannerHtml) banner.innerHTML = bannerHtml;
      setSaveBadge('saving', 'Finish defense');
    } else if (banner) {
      banner.remove();
    }
  }

  function clearDraft({restore = false} = {}) {
    if (restore && draft) {
      draft.alignment = {...draft.baseAlignment};
      renderDraft();
    }
    document.querySelector('#cbQuickDefense .cb-main-draft-banner')?.remove();
    document.querySelectorAll('#cbQuickDefense .cb-main-open').forEach(el => el.classList.remove('cb-main-open'));
    draft = null;
    if (!saveBusy) setSaveBadge('', 'Saved ✓');
  }

  function applyMove(alignment, name, destination) {
    const source = positionForName(alignment, name);
    if (source === 'P' || destination === 'P') return {pitcher: true, changed: false};
    if (source === destination || (source === 'BENCH' && destination === 'BENCH')) {
      return {pitcher: false, changed: false};
    }

    if (destination === 'BENCH') {
      if (source !== 'BENCH') delete alignment[source];
      return {pitcher: false, changed: true};
    }

    const occupant = alignment[destination] || null;
    if (source !== 'BENCH') delete alignment[source];
    alignment[destination] = name;
    if (occupant && occupant !== name && source !== 'BENCH') alignment[source] = occupant;
    return {pitcher: false, changed: true};
  }

  async function saveCompletedDraft() {
    if (!draft || saveBusy) return;
    const missing = fieldPositions().filter(pos => !draft.alignment[pos]);
    if (missing.length) {
      renderDraft();
      return;
    }

    const comparableBefore = JSON.stringify(draft.baseAlignment);
    const comparableAfter = JSON.stringify(draft.alignment);
    if (comparableBefore === comparableAfter) {
      clearDraft({restore: true});
      return;
    }

    saveBusy = true;
    setSaveBadge('saving', 'Saving…');
    const savedDraft = draft;
    try {
      const response = await fetch(`/api/live-game/${gameId}/defense-edit`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          alignment: savedDraft.alignment,
          base_sequence: savedDraft.baseSequence,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') {
        throw new Error(data.message || `Unable to save defense (${response.status}).`);
      }

      if (draft === savedDraft) draft = null;
      document.querySelector('#cbQuickDefense .cb-main-draft-banner')?.remove();
      setSaveBadge('', 'Saved ✓');
    } catch (error) {
      if (draft === savedDraft) {
        setSaveBadge('error', 'Not saved');
        window.alert(`Defense was not saved. ${error.message}`);
        clearDraft({restore: true});
      }
    } finally {
      saveBusy = false;
    }
  }

  async function handleDrop(name, destination) {
    if (!name || name === 'Open' || !destination) return;
    if (destination === 'P') {
      clearDraft({restore: true});
      document.getElementById('liveChangePitcherBtn')?.click();
      return;
    }

    try {
      const working = await ensureDraft();
      const source = positionForName(working.alignment, name);
      if (source === 'P') {
        clearDraft({restore: true});
        document.getElementById('liveChangePitcherBtn')?.click();
        return;
      }

      const result = applyMove(working.alignment, name, destination);
      if (!result.changed) return;
      renderDraft();
      await saveCompletedDraft();
    } catch (error) {
      setSaveBadge('error', 'Not saved');
      window.alert(`Defense was not changed. ${error.message}`);
      clearDraft({restore: true});
    }
  }

  function dragSourceFromEvent(event) {
    const source = event.target.closest?.('#cbQuickDefense [data-cb-move-player]');
    if (!source || source.disabled) return null;
    const name = source.dataset.cbMovePlayer;
    if (!name || name === 'Open') return null;
    const pos = String(source.dataset.cbPosition || '').toUpperCase();
    if (pos === 'P') return null;
    return source;
  }

  function dropDestination(clientX, clientY) {
    const element = document.elementFromPoint(clientX, clientY);
    const spot = element?.closest?.('#cbQuickDefense [data-cb-position]');
    if (spot) return String(spot.dataset.cbPosition || '').toUpperCase();
    if (element?.closest?.('#cbQuickDefense .cb-qd-bench-wrap')) return 'BENCH';
    return null;
  }

  function clearDropHighlight() {
    document.querySelectorAll('#cbQuickDefense .cb-main-drag-over').forEach(el => el.classList.remove('cb-main-drag-over'));
  }

  function highlightDropTarget(clientX, clientY) {
    clearDropHighlight();
    const element = document.elementFromPoint(clientX, clientY);
    const target = element?.closest?.('#cbQuickDefense [data-cb-position], #cbQuickDefense .cb-qd-bench-wrap');
    target?.classList.add('cb-main-drag-over');
  }

  function beginDrag(event) {
    if (saveBusy || (event.button !== undefined && event.button !== 0)) return;
    const source = dragSourceFromEvent(event);
    if (!source) return;
    drag = {
      pointerId: event.pointerId,
      source,
      name: source.dataset.cbMovePlayer,
      startX: event.clientX,
      startY: event.clientY,
      active: false,
      ghost: null,
    };
  }

  function moveDrag(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    if (!drag.active && distance < 8) return;

    if (!drag.active) {
      drag.active = true;
      suppressClickUntil = Date.now() + 700;
      const ghost = document.createElement('div');
      ghost.className = 'cb-main-drag-ghost';
      ghost.textContent = drag.source.querySelector('.cb-qd-name, span')?.textContent?.trim() || drag.name;
      document.body.appendChild(ghost);
      drag.ghost = ghost;
    }

    event.preventDefault();
    if (drag.ghost) {
      drag.ghost.style.left = `${event.clientX}px`;
      drag.ghost.style.top = `${event.clientY}px`;
    }
    highlightDropTarget(event.clientX, event.clientY);
  }

  function finishDrag(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const completed = drag;
    drag = null;
    clearDropHighlight();
    completed.ghost?.remove();
    if (!completed.active) return;

    event.preventDefault();
    event.stopPropagation();
    suppressClickUntil = Date.now() + 700;
    const destination = dropDestination(event.clientX, event.clientY);
    if (destination) handleDrop(completed.name, destination);
  }

  function cancelDrag() {
    clearDropHighlight();
    drag?.ghost?.remove();
    drag = null;
  }

  function selectPlayerWhenEditorOpens(name) {
    let timeoutId = null;
    const onShown = event => {
      if (event.target?.id !== 'cb-live-field-editor') return;
      document.removeEventListener('shown.bs.modal', onShown);
      if (timeoutId) window.clearTimeout(timeoutId);
      window.requestAnimationFrame(() => {
        const player = [...document.querySelectorAll('#cb-live-field-editor [data-cb-editor-player]')]
          .find(button => button.dataset.cbEditorPlayer === name);
        player?.click();
      });
    };

    document.addEventListener('shown.bs.modal', onShown);
    timeoutId = window.setTimeout(() => {
      document.removeEventListener('shown.bs.modal', onShown);
    }, 5000);
  }

  function enhanceQuickDefense() {
    enhanceQueued = false;
    installStyles();
    const card = document.getElementById('cbQuickDefense');
    if (!card) return;
    if (draft) renderDraft();
    const helpText = 'Drag players right on the field or bench. Tap a fielder for the full editor. Pitcher changes stay in Change Pitcher.';
    const tipText = 'Drag a bench player onto a field spot for a substitution, or drag fielders to swap. If you drag a fielder to Bench, fill the open spot and CoachBoard saves the completed defense.';
    const help = card.querySelector('.cb-qd-help');
    if (help && help.textContent !== helpText) help.textContent = helpText;
    const tip = card.querySelector('.cb-qd-tip');
    if (tip && tip.textContent !== tipText) tip.textContent = tipText;
  }

  function queueEnhance() {
    if (enhanceQueued) return;
    enhanceQueued = true;
    window.requestAnimationFrame(enhanceQuickDefense);
  }

  // End Inning is owned by the full-field live editor controller. This module
  // only owns Quick Defense drag/tap behavior.

  document.addEventListener('pointerdown', beginDrag, {capture: true, passive: true});
  document.addEventListener('pointermove', moveDrag, {capture: true, passive: false});
  document.addEventListener('pointerup', finishDrag, {capture: true, passive: false});
  document.addEventListener('pointercancel', cancelDrag, {capture: true, passive: true});

  document.addEventListener('click', event => {
    const cancel = event.target.closest?.('[data-cb-cancel-main-draft]');
    if (cancel) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      clearDraft({restore: true});
      return;
    }

    if (Date.now() < suppressClickUntil && event.target.closest?.('#cbQuickDefense')) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      return;
    }

    const fielder = event.target.closest?.(
      '#cbQuickDefense [data-cb-move-player][data-cb-position]'
    );
    if (!fielder || fielder.disabled) return;

    const position = String(fielder.dataset.cbPosition || '').toUpperCase();
    if (!position || position === 'P') return;

    const defenseButton = document.getElementById('liveDefensiveChangeBtn');
    if (!defenseButton || defenseButton.disabled) return;

    const name = fielder.dataset.cbMovePlayer;
    if (!name || name === 'Open') {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    selectPlayerWhenEditorOpens(name);
    defenseButton.click();
  }, true);

  document.addEventListener('DOMContentLoaded', () => {
    installStyles();
    queueEnhance();
    const overlay = document.getElementById('live-game-overlay');
    if (overlay) {
      new MutationObserver(() => {
        // A staged defense is the visible source of truth until every position
        // is filled and the bulk edit is saved. Reassert it in the same
        // mutation cycle so socket/server rerenders cannot flash or replace the
        // draft bench/field between the coach's first and second drag.
        if (draft) renderDraft();
        queueEnhance();
      }).observe(overlay, {childList: true, subtree: true});
    }
  });
})();