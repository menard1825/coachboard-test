(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const STYLE_ID = 'cb-live-dugout-workflow-style';
  const nativeFetch = window.fetch.bind(window);
  let rootObserver = null;
  let started = false;

  const setText = (el, value) => {
    if (el && el.textContent !== value) el.textContent = value;
  };
  const setHtml = (el, value) => {
    if (el && el.innerHTML !== value) el.innerHTML = value;
  };

  if (typeof window.io === 'function' && !window.io.__cbSocketExposed) {
    const originalIo = window.io;
    const exposedIo = function(...args) {
      const socket = originalIo.apply(this, args);
      window.__cbLiveGameSocket = socket;
      return socket;
    };
    Object.keys(originalIo).forEach(key => { try { exposedIo[key] = originalIo[key]; } catch (_) {} });
    exposedIo.__cbSocketExposed = true;
    exposedIo.__cbOriginal = originalIo;
    window.io = exposedIo;
  }

  async function bridgeDefensiveChange(input, init = {}) {
    const url = typeof input === 'string' ? input : input?.url;
    const method = String(init?.method || (typeof input !== 'string' ? input?.method : '') || 'GET').toUpperCase();
    let pathname = '';
    try { pathname = new URL(url, window.location.href).pathname; } catch (_) {}
    if (method !== 'POST' || pathname !== `/api/live-game/${gameId}/defensive-change`) return nativeFetch(input, init);

    let requested = {};
    try { requested = JSON.parse(init.body || '{}'); } catch (_) { return nativeFetch(input, init); }
    const playerId = Number(requested.player_id);
    const destination = String(requested.destination_position || 'BENCH').toUpperCase();
    if (!Number.isFinite(playerId) || destination === 'P') return nativeFetch(input, init);

    const stateResponse = await nativeFetch(`/api/live-game/${gameId}/state`, {cache:'no-store'});
    if (!stateResponse.ok) return nativeFetch(input, init);
    const current = await stateResponse.json();
    const player = (current.roster || []).find(item => Number(item.id) === playerId);
    if (!player) return nativeFetch(input, init);

    const after = {...(current.current_alignment || {})};
    const source = Object.entries(after).find(([, name]) => name === player.name)?.[0] || '';
    if (destination === 'BENCH') {
      if (source) delete after[source];
      return nativeFetch(input, init);
    }

    const occupant = after[destination] || '';
    if (source) delete after[source];
    after[destination] = player.name;
    if (occupant && occupant !== player.name && source) after[source] = occupant;

    const editResponse = await nativeFetch(`/api/live-game/${gameId}/defense-edit`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({alignment:after}),
    });
    if (!editResponse.ok) return editResponse;
    const editData = await editResponse.clone().json().catch(() => ({}));
    const delta = editData.delta || {};
    const syntheticState = {
      ...current,
      current_inning: String(delta.current_inning || current.current_inning || '1'),
      current_alignment: {...(delta.current_alignment || after)},
      current_pitcher: delta.current_pitcher || (delta.current_alignment || after).P || current.current_pitcher,
      bench: Array.isArray(delta.bench) ? delta.bench : current.bench,
      rotation_events: delta.event ? [...(current.rotation_events || []), delta.event] : (current.rotation_events || []),
    };
    return new Response(JSON.stringify({status:'success', state:syntheticState, delta}), {
      status:200,
      headers:{'Content-Type':'application/json'},
    });
  }

  window.fetch = bridgeDefensiveChange;

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      body.cb-dugout #liveSetDefenseBtnCoach,body.cb-dugout [data-cb-full-defense]{display:none!important}
      body.cb-dugout #cbQuickDefense .cb-qd-actions{display:none!important}
      body.cb-dugout #cbQuickDefense .cb-bench-note{display:none!important}
      body.cb-dugout #coach-action-slot.coach-actions{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important}
      body.cb-dugout #liveChangePitcherBtn,body.cb-dugout #liveEndInningBtn{min-height:62px!important}
      body.cb-dugout #liveUndoBtn{grid-column:1/-1!important;width:auto!important;min-height:28px!important;justify-self:center!important;border:0!important;background:transparent!important;color:#667085!important;padding:3px 10px!important;box-shadow:none!important}
      body.cb-dugout #liveUndoBtn .coach-action-title{font-size:.74rem!important;text-decoration:underline;text-underline-offset:2px}
      body.cb-dugout #liveUndoBtn .coach-action-note{display:none!important}
      body.cb-dugout #liveChangePitcherBtn .coach-action-note,body.cb-dugout #liveEndInningBtn .coach-action-note{font-size:0!important;opacity:.78!important}
      body.cb-dugout #liveChangePitcherBtn .coach-action-note::after{content:'This inning';font-size:.67rem}
      body.cb-dugout #liveEndInningBtn .coach-action-note::after{content:'Send next defense out';font-size:.67rem}
      body.cb-dugout #cbQuickDefense .cb-qd-bench{display:flex!important;visibility:visible!important}
      @media(max-width:575.98px){html body.cb-dugout #cbQuickDefense .cb-qd-head{padding:8px 9px 7px!important}html body.cb-dugout #cbQuickDefense .cb-qd-title{font-size:.9rem!important}html body.cb-dugout #cbQuickDefense .cb-qd-help{font-size:.64rem!important}html body.cb-dugout #cbQuickDefense .cb-qd-body{padding:6px 7px 8px!important}html body.cb-dugout #cbQuickDefense .cb-qd-field{min-height:0!important;max-height:228px!important;aspect-ratio:1.58/1!important}html body.cb-dugout #cbQuickDefense .cb-qd-spot{width:61px!important}html body.cb-dugout #cbQuickDefense .cb-qd-name{font-size:.55rem!important;padding:3px 4px!important}html body.cb-dugout #cbQuickDefense .cb-qd-bench-wrap{margin-top:6px!important;padding:7px!important}html body.cb-dugout #cbQuickDefense .cb-qd-bench-player{padding:6px 7px!important;font-size:.66rem!important}body.cb-dugout #coach-action-slot.coach-actions{position:sticky;bottom:0;z-index:1030;background:#eef1f4;padding:7px 0 calc(7px + env(safe-area-inset-bottom));margin-bottom:8px!important}body.cb-dugout #liveChangePitcherBtn,body.cb-dugout #liveEndInningBtn{min-height:56px!important}}
      @media(orientation:landscape) and (max-height:599.98px){html body.cb-dugout #cbQuickDefense .cb-qd-field{max-height:205px!important;width:min(62vw,480px)!important}}
    `;
    document.head.appendChild(style);
  }

  function removeBulkDefense() {
    document.getElementById('liveSetDefenseBtnCoach')?.remove();
    document.getElementById('live-bulk-defense-coach')?.remove();
    document.querySelectorAll('[data-cb-full-defense]').forEach(button => button.remove());
  }

  function patchStaticCopy() {
    removeBulkDefense();
    const card = document.getElementById('cbQuickDefense');
    if (card) {
      setText(card.querySelector('.cb-qd-kicker'), 'ON THE FIELD');
      setText(card.querySelector('.cb-qd-title'), 'Defense Now');
      setText(card.querySelector('.cb-qd-help'), 'Tap a fielder or bench player to make one sub.');
      const benchTitle = card.querySelector('.cb-qd-bench-head strong');
      if (benchTitle && /^Bench now/i.test(benchTitle.textContent || '')) setText(benchTitle, benchTitle.textContent.replace(/^Bench now/i, 'On the Bench'));
    }
    setText(document.querySelector('.cb-end-zone small'), 'After the last out');
  }

  function patchMenu() {
    const modal = document.getElementById('cbCoachBoardNavModal');
    if (!modal) return;
    setText(modal.querySelector('.modal-header .small.text-muted'), 'Game stays live.');
    setHtml(modal.querySelector('.cb-nav-safe'), '<strong>Game stays live.</strong> Clock stays as-is.');
  }

  function retrySuppressedEditorSave(event) {
    const save = event.target.closest?.('#cb-live-field-editor [data-cb-editor-save]');
    if (!save || save.disabled) return;
    window.setTimeout(() => {
      const modal = document.getElementById('cb-live-field-editor');
      const currentSave = modal?.querySelector('[data-cb-editor-save]');
      if (!modal?.classList.contains('show') || !currentSave || currentSave.disabled) return;
      currentSave.click();
    }, 400);
  }

  function pushStateIntoUnifiedController(current) {
    const events = Array.isArray(current?.rotation_events) ? current.rotation_events : [];
    const sequence = events.reduce((max, item) => item?.reverted ? max : Math.max(max, Number(item?.sequence) || 0), 0);
    const delta = {
      game_id: gameId,
      current_inning: String(current?.current_inning || current?.game?.live_current_inning || '1'),
      current_alignment: {...(current?.current_alignment || {})},
      current_pitcher: current?.current_pitcher || current?.current_alignment?.P || null,
      bench: Array.isArray(current?.bench) ? current.bench : [],
      sequence,
    };
    const socket = window.__cbLiveGameSocket;
    const listeners = typeof socket?.listeners === 'function' ? socket.listeners('live_game_delta') : [];
    if (listeners?.length) {
      listeners.forEach(listener => listener(delta));
      return true;
    }
    if (typeof socket?.emitEvent === 'function') {
      socket.emitEvent(['live_game_delta', delta]);
      return true;
    }
    return false;
  }

  async function refreshUnifiedStateAndReplay(button) {
    const response = await nativeFetch(`/api/live-game/${gameId}/state`, {cache:'no-store'});
    if (!response.ok) throw new Error('Unable to refresh live game state.');
    const current = await response.json();
    pushStateIntoUnifiedController(current);
    button.dataset.cbUnifiedReplay = '1';
    button.click();
  }

  function guaranteeUnifiedEndInning(event) {
    const button = event.target.closest?.('#liveEndInningBtn');
    if (!button || button.disabled) return;
    if (button.dataset.cbUnifiedReplay === '1') {
      delete button.dataset.cbUnifiedReplay;
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation?.();
    refreshUnifiedStateAndReplay(button).catch(() => {});
  }

  function loadUnifiedFeedbackPass() {
    if ([...document.scripts].some(node => /\/static\/js\/live_game_feedback_pass\.js(?:\?|$)/.test(node.src || ''))) return;
    const script = document.createElement('script');
    script.src = '/static/js/live_game_feedback_pass.js?v=20260831-5';
    script.dataset.cbLiveFeedbackPass = 'true';
    document.body.appendChild(script);
  }

  function start() {
    if (started) return;
    if (!document.body) {
      document.addEventListener('DOMContentLoaded', start, {once:true});
      return;
    }
    started = true;
    installStyles();
    document.getElementById('cbCurrentInningStrip')?.remove();
    patchStaticCopy();

    // Register the authoritative End Inning refresh guard before loading the
    // unified editor. This guarantees an immediate post-start click refreshes
    // server state before the editor is allowed to consume the replay.
    document.addEventListener('click', guaranteeUnifiedEndInning, true);
    document.addEventListener('click', retrySuppressedEditorSave, true);
    document.addEventListener('click', event => {
      if (event.target.closest?.('[data-cb-menu], #cbCoachBoardNavBtn')) window.setTimeout(patchMenu, 0);
    }, true);
    loadUnifiedFeedbackPass();

    if (!document.getElementById('cbQuickDefense')) {
      rootObserver = new MutationObserver(() => {
        if (!document.getElementById('cbQuickDefense')) return;
        patchStaticCopy();
        rootObserver?.disconnect();
        rootObserver = null;
      });
      rootObserver.observe(document.body, {childList:true, subtree:true});
    }
  }

  start();
})();