(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  let dragSurface = null;
  let draft = null;
  let saveBusy = false;
  let enhanceQueued = false;
  let quickDefenseObserver = null;
  let quickDefenseOverlay = null;

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
      #cbQuickDefense .cb-qd-bench-player{touch-action:manipulation;cursor:grab}
      #cbQuickDefense .cb-qd-spot:not(.pitcher):active,
      #cbQuickDefense .cb-qd-bench-player:active{cursor:grabbing}
      #cbQuickDefense .cb-qd-spot.cb-drag-over .cb-qd-name{outline:4px solid rgba(16,42,102,.25);border-color:#102a66;background:#f4f7ff}
      #cbQuickDefense .cb-qd-bench-wrap.cb-drag-over{outline:4px solid rgba(22,107,56,.22);border-color:#5b9b70;background:#f0f8f2}
      #cbQuickDefense .cb-main-open .cb-qd-name,
      #cbQuickDefense .cb-authoritative-open .cb-qd-name{border:2px dashed #d49a22;background:#fff8e7;color:#8b5c00;font-weight:850}
      #cbQuickDefense .cb-main-draft-banner{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:9px 0 0;padding:8px 9px;border:1px solid #e4c46d;border-radius:10px;background:#fff9e9;color:#755100;font-size:.66rem;font-weight:720}
      #cbQuickDefense .cb-main-draft-banner .btn{min-height:34px;font-size:.65rem;font-weight:800;white-space:nowrap}
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

  function observeQuickDefense() {
    if (!quickDefenseObserver || !quickDefenseOverlay) return;
    quickDefenseObserver.observe(quickDefenseOverlay, {childList: true, subtree: true});
  }

  function renderDraft() {
    if (!draft) return;
    const card = document.getElementById('cbQuickDefense');
    if (!card) return;

    const resumeObserver = Boolean(quickDefenseObserver && quickDefenseOverlay);
    if (resumeObserver) quickDefenseObserver.disconnect();
    try {
      const assigned = new Set(Object.values(draft.alignment).filter(Boolean));
      card.querySelectorAll('[data-cb-position]').forEach(button => {
        const pos = String(button.dataset.cbPosition || '').toUpperCase();
        const name = draft.alignment[pos] || '';
        button.dataset.cbMovePlayer = name || 'Open';
        button.disabled = false;

        // Authoritative-open is a visual-only marker, not draft ownership.
        // A real draft render always takes over from it.
        button.classList.remove('cb-authoritative-open');
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
      const blockingMissing = missing.filter(pos => pos === 'P');
      let banner = card.querySelector('.cb-main-draft-banner');
      if (blockingMissing.length) {
        if (!banner) {
          banner = document.createElement('div');
          banner.className = 'cb-main-draft-banner';
          card.querySelector('.cb-qd-bench-wrap')?.insertAdjacentElement('afterend', banner);
        }
        const bannerHtml = `<span><strong>${esc(blockingMissing.join(', '))} open.</strong> The pitcher position must be filled before CoachBoard can save.</span><button type="button" class="btn btn-sm btn-outline-secondary" data-cb-cancel-main-draft>Cancel</button>`;
        if (banner.innerHTML !== bannerHtml) banner.innerHTML = bannerHtml;
        setSaveBadge('saving', 'Finish defense');
      } else if (banner) {
        banner.remove();
      }
    } finally {
      if (resumeObserver) observeQuickDefense();
    }
  }

  function clearDraft({restore = false} = {}) {
    if (restore && draft) {
      draft.alignment = {...draft.baseAlignment};
      renderDraft();
    }

    document.querySelector(
      '#cbQuickDefense .cb-main-draft-banner'
    )?.remove();

    // `.cb-main-open` is the cross-module signal that a local draft owns
    // #cbQuickDefense (see live_game_dugout_mode.js and
    // live_game_feedback_pass.js, which both refuse to repaint while it is
    // present). It must never outlive the draft that set it.
    document.querySelectorAll(
      '#cbQuickDefense .cb-main-open'
    ).forEach(
      element => element.classList.remove(
        'cb-main-open'
      )
    );

    draft = null;

    if (!saveBusy) {
      setSaveBadge('', 'Saved ✓');
    }
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

    // An intentionally OPEN non-pitcher position is a valid live-game
    // state and must be persisted immediately so every connected coach
    // sees the same field. P remains protected and cannot be saved OPEN.
    if (missing.includes('P')) {
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
        const saveError = new Error(
          data.message ||
          `Unable to save defense (${response.status}).`
        );

        // Preserve authoritative conflict details so the catch block can
        // repaint from the server instead of restoring a stale local draft.
        saveError.code = String(data.code || '');
        saveError.currentAlignment =
          data.current_alignment &&
          typeof data.current_alignment === 'object'
            ? {...data.current_alignment}
            : null;
        saveError.currentSequence =
          Number(data.current_sequence) || 0;

        throw saveError;
      }

      // Keep the tap-based Quick Field controller on the exact same live
      // version as drag-and-drop. Socket.IO normally broadcasts this delta too,
      // but publishing the successful response locally removes the race where a
      // coach drags a player and immediately taps the updated field.
      if (data.delta) {
        document.dispatchEvent(new CustomEvent('coachboard:live-delta', {
          detail: data.delta,
        }));
      }

      if (draft === savedDraft) {
        clearDraft();
      } else {
        document.querySelector(
          '#cbQuickDefense .cb-main-draft-banner'
        )?.remove();

        document.querySelectorAll(
          '#cbQuickDefense .cb-main-open'
        ).forEach(
          element => element.classList.remove('cb-main-open')
        );
      }

      setSaveBadge('', 'Saved ✓');
    } catch (error) {
      if (draft === savedDraft) {
        setSaveBadge('error', 'Not saved');
        window.alert(`Defense was not saved. ${error.message}`);

        if (
          error?.code === 'stale_live_state' &&
          error?.currentAlignment
        ) {
          /*
           * Another coach won the optimistic-concurrency race.
           *
           * The 409 response already contains the authoritative field.
           * Paint that immediately. Restoring savedDraft.baseAlignment here
           * would briefly show the older defense until the next socket/state
           * refresh arrives.
           *
           * Do NOT merge or retry the rejected drag automatically; the other
           * coach's change remains authoritative and the coach can retry from
           * the updated field.
           */
          savedDraft.baseAlignment = {
            ...error.currentAlignment,
          };
          savedDraft.alignment = {
            ...error.currentAlignment,
          };

          if (error.currentSequence) {
            savedDraft.baseSequence =
              error.currentSequence;
          }

          renderDraft();

          // Keep the authoritative Open look, but hand it off to a
          // visual-only class before clearDraft() strips `.cb-main-open`.
          // `.cb-main-open` must stay a pure "draft in progress" signal —
          // see clearDraft() — or the guards in live_game_dugout_mode.js
          // and live_game_feedback_pass.js will keep treating this
          // authoritative, no-longer-draft position as an active draft and
          // stop repainting #cbQuickDefense on later socket updates.
          document.querySelectorAll(
            '#cbQuickDefense .cb-main-open'
          ).forEach(element => {
            element.classList.add('cb-authoritative-open');

            // Open is a destination, never a drag source, but it must remain
            // tappable so a coach can fill the vacancy without dragging.
            element.disabled = false;
          });

          clearDraft({restore: false});
        } else {
          clearDraft({restore: true});
        }
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

    // A direct field-to-field swap needs an authoritative-state fetch before
    // the draft can be built. Do not leave the old "Saved" indicator visible
    // during that request or a coach can reasonably think the new move is
    // already persisted.
    setSaveBadge('saving', 'Saving…');

    try {
      const working = await ensureDraft();
      const source = positionForName(working.alignment, name);
      if (source === 'P') {
        setSaveBadge('', 'Saved ✓');
        clearDraft({restore: true});
        document.getElementById('liveChangePitcherBtn')?.click();
        return;
      }

      const result = applyMove(working.alignment, name, destination);
      if (!result.changed) {
        setSaveBadge('', 'Saved ✓');
        return;
      }
      renderDraft();
      await saveCompletedDraft();
    } catch (error) {
      setSaveBadge('error', 'Not saved');
      window.alert(`Defense was not changed. ${error.message}`);
      clearDraft({restore: true});
    }
  }

  /**
   * On the Field's half of the shared drag contract.
   *
   * The manager (live_game_drag_controller.js) owns every gesture
   * mechanic. What stays here is what only this board can answer:
   * who may be picked up, what a drop point means, and what a drop
   * does. The P and Open refusals below are live-game rules -- the
   * pitcher changes through Change Pitcher, and an empty position is
   * a destination, not a thing to carry -- and they deliberately do
   * not match Next Inning's.
   */
  function registerDragSurface() {
    if (dragSurface || !window.CoachBoardDrag) return;

    dragSurface = window.CoachBoardDrag.registerSurface({
      id: 'on-field',
      root: () => document.getElementById('cbQuickDefense'),
      canStart: () => !saveBusy,
      sourceSelector: '#cbQuickDefense [data-cb-move-player]',
      targetSelector: '#cbQuickDefense [data-cb-position], #cbQuickDefense .cb-qd-bench-wrap',

      resolveSource: node => {
        if (node.disabled) return null;
        const name = node.dataset.cbMovePlayer;
        if (!name || name === 'Open') return null;
        if (String(node.dataset.cbPosition || '').toUpperCase() === 'P') return null;
        return {
          kind: node.classList.contains('cb-qd-bench-player') ? 'chip' : 'marker',
          key: name,
          name,
          label: node.querySelector('.cb-qd-name, span')?.textContent?.trim() || name,
        };
      },

      // Called fresh on every move and never cached, so the manager can
      // tell a live source from one a rerender has already replaced
      // without knowing anything about how this board marks players.
      findSource: source => document.querySelector(
        `#cbQuickDefense [data-cb-move-player="${CSS.escape(source.name)}"]`
      ),

      resolveTarget: node => ({
        position: node.dataset.cbPosition
          ? String(node.dataset.cbPosition).toUpperCase()
          : 'BENCH',
      }),

      onDrop: (source, target) => handleDrop(source.name, target.position),
    });
  }

  function enhanceQuickDefense() {
    enhanceQueued = false;
    installStyles();
    const card = document.getElementById('cbQuickDefense');
    if (!card) return;
    if (draft) renderDraft();

    const helpText = 'Drag or tap players right on the field and bench. Pitcher changes stay in Change Pitcher.';
    const tipText = 'Tap a player for a quick move, or drag directly between the field and bench. CoachBoard saves a complete defense automatically.';
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

  document.addEventListener(
    'coachboard:live-state',
    event => {
      const detail = event?.detail || {};

      if (Number(detail.game_id) !== gameId) return;

      dragSurface?.cancel();

      if (String(detail.source || '') !== 'undo') return;

      clearDraft({restore: false});
    }
  );

  document.addEventListener('click', event => {
    const cancel = event.target.closest?.('[data-cb-cancel-main-draft]');
    if (cancel) {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      clearDraft({restore: true});
    }
  }, true);

  document.addEventListener('DOMContentLoaded', () => {
    installStyles();
    registerDragSurface();
    queueEnhance();
    quickDefenseOverlay = document.getElementById('live-game-overlay');
    if (quickDefenseOverlay) {
      quickDefenseObserver = new MutationObserver(() => {
        if (draft) renderDraft();
        queueEnhance();
      });
      observeQuickDefense();
    }
  });
})();