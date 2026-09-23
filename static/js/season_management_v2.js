(() => {
  'use strict';
  if (window.location.pathname !== '/') return;

  const PRESET_PREFIX = 'DEFENSE PRESET — ';
  let mutationTimer = null;

  // /api/rotations is fetched when the rotations themselves may have changed,
  // not on every mutation of a watched container. Those containers also change
  // when main.js renders unrelated lists and when this script (or
  // coachboard_ui.js) decorates the Rotations tab, and each of those used to
  // cost another request -- 3 per Home load, 5 on a slow connection.
  let rotationsCache = null;
  let rotationsRequest = null;
  let refreshRotationsOnNextPass = false;
  // Rotation data is fetched only once the Rotations tab has been shown; the
  // Practice and Development enhancements need none and run regardless.
  // Before that the rotation work is dormant. After it: `rotationsRequest`
  // while a fetch is out, `rotationsCache` once one succeeded; neither means
  // the last fetch failed and the next pass tries again.
  let rotationsInitialized = false;
  const separatedItems = new WeakSet();
  let separatedState = null;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if (document.getElementById('season-management-v2-styles')) return;
    const style = document.createElement('style');
    style.id = 'season-management-v2-styles';
    style.textContent = `
      #player_development .season-dev-summary{display:flex;justify-content:space-between;gap:12px;align-items:center;border:1px solid #e2e6eb;background:#fff;border-radius:12px;padding:10px 12px;margin-bottom:12px}
      #player_development .season-dev-summary strong{font-size:.82rem;color:#172033}#player_development .season-dev-summary span{font-size:.68rem;color:#667085}
      #dev-player-list{display:grid;gap:7px}#dev-player-list .list-group-item{border:1px solid #e2e6eb!important;border-radius:10px!important;margin:0!important;padding:10px 11px}#dev-player-list .list-group-item.active{background:#f1f5fb;color:#172033;border-color:#9eb3d3!important}#dev-player-list .list-group-item.active small{color:#475467!important}
      #player-dev-content>.card,#player-dev-content>.list-group,#player-dev-content>div{border-radius:12px}
      #rotations .defense-preset-home{border:1px solid #dce5dc;border-radius:13px;background:#f8fbf8;margin-bottom:14px;overflow:hidden}#rotations .dph-head{padding:11px 13px;border-bottom:1px solid #e3e9e3;display:flex;justify-content:space-between;gap:10px;align-items:center}#rotations .dph-head strong{font-size:.82rem;color:#172033}#rotations .dph-head span{font-size:.65rem;color:#667085}#rotations .dph-head-actions{display:flex;align-items:center;gap:8px}#rotations .dph-head-actions .btn{border-radius:8px;font-weight:750;white-space:nowrap}#rotations .dph-list{display:flex;flex-wrap:wrap;gap:7px;padding:11px 13px}#rotations .dph-chip{display:inline-flex;align-items:center;gap:5px;border:1px solid #d6ded6;background:#fff;border-radius:999px;padding:6px 9px;font-size:.7rem;font-weight:750;color:#344054;text-decoration:none}#rotations .dph-chip:hover{border-color:#9eae9e;background:#f3f8f3;color:#172033}
      #rotations .rotation-template-card-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}#rotations .rotation-template-toolbar{display:flex;align-items:center;gap:7px}#rotations .rotation-template-toolbar .btn{border-radius:8px;font-weight:750;white-space:nowrap}#rotations .rotation-template-edit-btn{font-weight:750}
      #reusePracticeModal .modal-content{border:0;border-radius:16px;overflow:hidden}#reusePracticeModal .form-control{min-height:46px}
      @media(max-width:575.98px){#player_development .season-dev-summary{align-items:flex-start}.practice-plan-details-form .reuse-practice-btn{width:100%;order:-1}#rotations .dph-head{align-items:flex-start;flex-direction:column}#rotations .dph-head-actions{width:100%;justify-content:space-between}#rotations .dph-head-actions .btn{min-height:40px}#rotations .dph-list{padding:9px 10px}#rotations .rotation-template-toolbar{width:100%}#rotations .rotation-template-toolbar .btn{width:100%;min-height:42px}}
    `;
    document.head.appendChild(style);
  }

  async function loadRotations() {
    try {
      const response = await fetch('/api/rotations', {cache:'no-store'});
      if (!response.ok) return null;
      return await response.json();
    } catch (_) {
      return null;
    }
  }

  function requestRotations() {
    rotationsRequest = rotationsRequest || loadRotations().finally(() => { rotationsRequest = null; });
    return rotationsRequest;
  }

  // The rotations main.js rendered, in the terms that decide the separation:
  // which rotations, under which titles (the preset prefix is in the title).
  function renderedRotationsKey(accordion) {
    return [...accordion.querySelectorAll('[data-rotation-id]')]
      .map(item => `${item.dataset.rotationId}\u0001${item.querySelector('.accordion-button strong')?.textContent ?? ''}`)
      .sort().join('\u0002');
  }

  function fetchedRotationsKey(rotations) {
    return rotations.filter(item => !item.associated_game_id)
      .map(item => `${item.id}\u0001${item.title ?? ''}`)
      .sort().join('\u0002');
  }

  // The accordion as this script last left it. Decorations inside the rows
  // (its own Edit buttons, coachboard_ui.js's Delete buttons) do not change
  // it; main.js re-rendering the list does, because that creates new rows.
  function accordionState(accordion) {
    const items = [...accordion.querySelectorAll('[data-rotation-id]')];
    return items.map(item => item.dataset.rotationId).join(',') + '|'
      + (items.length ? '' : accordion.textContent.trim());
  }

  function accordionUnchanged(accordion) {
    return accordionState(accordion) === separatedState
      && [...accordion.querySelectorAll('[data-rotation-id]')].every(item => separatedItems.has(item));
  }

  async function separateDefensePresets() {
    const tab = document.getElementById('rotations');
    const accordion = document.getElementById('rotationsAccordion');
    if (!tab || !accordion || !rotationsInitialized) return;

    const forceRefresh = refreshRotationsOnNextPass;
    refreshRotationsOnNextPass = false;
    if (!forceRefresh && rotationsCache && accordionUnchanged(accordion)) return;

    let rotations = rotationsCache;
    if (forceRefresh || !rotations || renderedRotationsKey(accordion) !== fetchedRotationsKey(rotations)) {
      const fetched = await requestRotations();
      if (fetched) rotationsCache = fetched;
      rotations = fetched || [];
    }
    const presets = rotations.filter(item => !item.associated_game_id && String(item.title || '').startsWith(PRESET_PREFIX));
    const normalIds = new Set(rotations.filter(item => !item.associated_game_id && !String(item.title || '').startsWith(PRESET_PREFIX)).map(item => String(item.id)));

    accordion.querySelectorAll('[data-rotation-id]').forEach(item => {
      const rotationId = String(item.dataset.rotationId);
      if (!normalIds.has(rotationId)) {
        item.remove();
        return;
      }
      const actions = item.querySelector('.accordion-body .d-flex.justify-content-end');
      if (actions && !actions.querySelector('.rotation-template-edit-btn')) {
        const edit = document.createElement('a');
        edit.className = 'btn btn-sm btn-outline-primary me-2 rotation-template-edit-btn';
        edit.href = `/rotation-template/${encodeURIComponent(rotationId)}`;
        edit.textContent = 'Edit Template';
        actions.prepend(edit);
      }
    });

    let panel = document.getElementById('defense-preset-home-v2');
    if (!panel) {
      panel = document.createElement('section');
      panel.id = 'defense-preset-home-v2';
      panel.className = 'defense-preset-home';
      const mainCard = accordion.closest('.card');
      if (mainCard) mainCard.insertAdjacentElement('beforebegin', panel);
      else tab.prepend(panel);
    }
    panel.innerHTML = `
      <div class="dph-head">
        <div><strong>Starting Defense Templates</strong><span class="d-block">Set the regular defense once; pitcher may stay open for Game Day</span></div>
        <div class="dph-head-actions"><span>${presets.length} saved</span><a class="btn btn-sm btn-primary" href="/starting-defense-template/new"><i class="bi bi-plus-lg me-1"></i>New Starting Defense</a></div>
      </div>
      <div class="dph-list">${presets.length ? presets.map(item => `<a class="dph-chip" href="/starting-defense-template/${encodeURIComponent(item.id)}"><i class="bi bi-pencil"></i>${esc(String(item.title).slice(PRESET_PREFIX.length).trim())}</a>`).join('') : '<span class="text-muted small">No starting defense templates saved yet.</span>'}</div>`;

    const mainCard = accordion.closest('.card');
    const cardHeader = mainCard?.querySelector('.card-header');
    const header = cardHeader?.querySelector('h5');
    if (header) header.textContent = 'Full-Game Rotation Templates';
    if (cardHeader) {
      cardHeader.classList.add('rotation-template-card-head');
      let toolbar = cardHeader.querySelector('.rotation-template-toolbar');
      if (!toolbar) {
        toolbar = document.createElement('div');
        toolbar.className = 'rotation-template-toolbar';
        toolbar.innerHTML = '<a class="btn btn-sm btn-primary" href="/rotation-template/new"><i class="bi bi-plus-lg me-1"></i>New Rotation Template</a>';
        cardHeader.appendChild(toolbar);
      }
    }

    accordion.querySelectorAll('[data-rotation-id]').forEach(item => separatedItems.add(item));
    separatedState = accordionState(accordion);
  }

  async function enhanceDevelopment() {
    const pane = document.getElementById('player_development');
    const list = document.getElementById('dev-player-list');
    if (!pane || !list) return;
    if (pane.querySelector(':scope > .cb-workspace-head')) {
      document.getElementById('season-dev-summary-v2')?.remove();
      return;
    }
    let summary = document.getElementById('season-dev-summary-v2');
    if (!summary) {
      summary = document.createElement('div');
      summary.id = 'season-dev-summary-v2';
      summary.className = 'season-dev-summary';
      const row = pane.querySelector(':scope > .row');
      if (row) row.insertAdjacentElement('beforebegin', summary);
      else pane.prepend(summary);
    }
    try {
      const response = await fetch('/api/player_development', {cache:'no-store'});
      const data = response.ok ? await response.json() : {};
      const players = Object.keys(data || {});
      const activePlayers = players.filter(name => (data[name] || []).some(item => item.status === 'active'));
      const activeGoals = players.reduce((total, name) => total + (data[name] || []).filter(item => item.status === 'active').length, 0);
      summary.innerHTML = `<div><strong>Player Development</strong><span class="d-block">Open a player to see goals, notes, and progress in one place.</span></div><div class="text-end"><strong>${activeGoals} active goal${activeGoals === 1 ? '' : 's'}</strong><span class="d-block">${activePlayers.length} player${activePlayers.length === 1 ? '' : 's'} with active focus</span></div>`;
    } catch (_) {
      summary.innerHTML = '<div><strong>Player Development</strong><span class="d-block">Open a player to see goals, notes, and progress.</span></div>';
    }
  }

  function scheduleEnhance() {
    clearTimeout(mutationTimer);
    mutationTimer = setTimeout(() => {
      separateDefensePresets();
      enhanceDevelopment();
    }, 100);
  }

  // Initialising goes through the same debounced pass as every other
  // trigger, so a first desktop showing -- which is also a shown.bs.tab asking
  // for a refresh -- makes one request, not two.
  function rotationsBecameActive() {
    rotationsInitialized = true;
    scheduleEnhance();
  }

  function watchRotationsPane() {
    const pane = document.getElementById('rotations');
    if (!pane) return;
    // One showing per batch of class changes: adding "active show" at once can
    // report two records that both start from an inactive pane.
    new MutationObserver(records => {
      if (pane.classList.contains('active') && !/\bactive\b/.test(records[0].oldValue || '')) rotationsBecameActive();
    }).observe(pane, {attributes:true, attributeFilter:['class'], attributeOldValue:true});
    if (pane.classList.contains('active')) rotationsBecameActive();
  }

  function init() {
    installStyles();
    scheduleEnhance();
    const targets = [document.getElementById('practicePlanAccordion'), document.getElementById('rotationsAccordion'), document.getElementById('dev-player-list')].filter(Boolean);
    targets.forEach(target => new MutationObserver(scheduleEnhance).observe(target, {childList:true, subtree:true}));
    watchRotationsPane();
    document.addEventListener('shown.bs.tab', event => {
      // Opening Rotations is the one refresh the accordion observer cannot see:
      // a preset saved on another device only appears here when asked for.
      if (event.target?.getAttribute?.('href') === '#rotations') refreshRotationsOnNextPass = true;
      scheduleEnhance();
    });
  }

  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', init, {once:true}) : init();
})();
