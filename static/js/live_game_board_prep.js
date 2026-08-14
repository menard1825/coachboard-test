(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const PRESET_PREFIX = 'DEFENSE PRESET — ';
  const STYLE_ID = 'pregame-defense-editor-styles-v2';
  let state = null;
  let currentInning = '1';
  let busy = false;
  let refreshTimer = null;

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function positions() {
    return Number(state?.outfielder_count) === 4
      ? ['P','C','1B','2B','3B','SS','LF','LCF','RCF','RF']
      : ['P','C','1B','2B','3B','SS','LF','CF','RF'];
  }

  function presentRoster() {
    const absent = new Set((state?.absent_player_ids || []).map(Number));
    return (state?.roster || []).filter(player => !absent.has(Number(player.id)));
  }

  function currentAlignment() {
    if (!state?.rotation) return {};
    if (!state.rotation.innings || typeof state.rotation.innings !== 'object') state.rotation.innings = {};
    if (!state.rotation.innings[currentInning]) state.rotation.innings[currentInning] = {};
    return state.rotation.innings[currentInning];
  }

  function presetName(template) {
    const title = String(template?.title || '');
    return title.startsWith(PRESET_PREFIX) ? title.slice(PRESET_PREFIX.length).trim() : null;
  }

  function presets() {
    return (state?.rotation_templates || [])
      .filter(template => presetName(template))
      .sort((a,b) => presetName(a).localeCompare(presetName(b)));
  }

  function installStyles() {
    if ($(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #pregame-defense-editor-v2{border:1px solid #dfe4ea;border-radius:16px;background:#fff;box-shadow:0 1px 4px rgba(16,24,40,.06);overflow:hidden;margin-bottom:18px}
      #pregame-defense-editor-v2 .pde-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;padding:15px 16px 12px;border-bottom:1px solid #edf0f3}
      #pregame-defense-editor-v2 .pde-kicker{font-size:.66rem;text-transform:uppercase;letter-spacing:.1em;font-weight:850;color:#667085}
      #pregame-defense-editor-v2 .pde-title{font-size:1.05rem;font-weight:850;color:#172033;margin-top:2px}
      #pregame-defense-editor-v2 .pde-help{font-size:.74rem;color:#7b8492;margin-top:2px}
      #pregame-defense-editor-v2 .pde-inning{background:#172033;color:#fff;border-radius:10px;min-width:70px;text-align:center;padding:7px 10px;flex:0 0 auto}
      #pregame-defense-editor-v2 .pde-inning small{display:block;font-size:.54rem;letter-spacing:.08em;font-weight:800;opacity:.7}
      #pregame-defense-editor-v2 .pde-inning strong{display:block;font-size:1.45rem;line-height:1.05;margin-top:2px}
      #pregame-defense-editor-v2 .pde-body{padding:14px 16px 16px}
      #pregame-defense-editor-v2 .pde-tools{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px;align-items:center;margin-bottom:14px}
      #pregame-defense-editor-v2 .pde-tools .form-select,#pregame-defense-editor-v2 .pde-tools .btn{min-height:42px;border-radius:9px}
      #pregame-defense-editor-v2 .pde-field{border:1px solid #dce5d9;border-radius:14px;padding:12px;background:linear-gradient(180deg,#edf7ea 0%,#f6f7e9 72%,#f4eadb 100%)}
      #pregame-defense-editor-v2 .pde-row{display:grid;gap:7px;margin-bottom:7px}
      #pregame-defense-editor-v2 .pde-row.of3{grid-template-columns:repeat(3,minmax(0,1fr))}
      #pregame-defense-editor-v2 .pde-row.of4{grid-template-columns:repeat(4,minmax(0,1fr))}
      #pregame-defense-editor-v2 .pde-row.if{grid-template-columns:repeat(4,minmax(0,1fr))}
      #pregame-defense-editor-v2 .pde-row.battery{grid-template-columns:repeat(2,minmax(0,1fr));max-width:58%;margin:0 auto 7px}
      #pregame-defense-editor-v2 .pde-slot{min-width:0;border:1px solid #d9dfe4;background:rgba(255,255,255,.95);border-radius:10px;padding:8px 6px;text-align:center;cursor:pointer;transition:transform .08s ease,border-color .08s ease,box-shadow .08s ease}
      #pregame-defense-editor-v2 .pde-slot:hover{border-color:#8ca3bd;box-shadow:0 2px 6px rgba(16,24,40,.08);transform:translateY(-1px)}
      #pregame-defense-editor-v2 .pde-slot.open{border-style:dashed;border-color:#d99a9a;background:#fffafa}
      #pregame-defense-editor-v2 .pde-pos{display:block;font-size:.58rem;font-weight:900;color:#667085;letter-spacing:.06em;line-height:1;margin-bottom:4px}
      #pregame-defense-editor-v2 .pde-name{display:block;font-size:.74rem;font-weight:800;color:#172033;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #pregame-defense-editor-v2 .pde-slot.open .pde-name{color:#a63d3d}
      #pregame-defense-editor-v2 .pde-bench{border-top:1px solid #dce2dc;margin-top:10px;padding-top:10px}
      #pregame-defense-editor-v2 .pde-label{font-size:.62rem;text-transform:uppercase;letter-spacing:.08em;font-weight:850;color:#667085;margin-bottom:6px}
      #pregame-defense-editor-v2 .pde-bench-list{display:flex;gap:5px;flex-wrap:wrap}
      #pregame-defense-editor-v2 .pde-bench-list span{font-size:.66rem;font-weight:650;color:#475467;border:1px solid #dde2e7;background:#fff;border-radius:999px;padding:5px 8px}
      #pregame-defense-editor-v2 .pde-status{font-size:.72rem;color:#667085;margin-top:9px;text-align:center}
      #pregame-defense-editor-v2 .pde-status strong{color:#172033}
      #pregame-defense-editor-v2 .pde-open-warning{color:#a63d3d;font-weight:750}
      #pregame-defense-player-modal-v2 .modal-content,#pregame-defense-preset-modal-v2 .modal-content{border:0;border-radius:16px;overflow:hidden}
      #pregame-defense-player-modal-v2 .pde-choice{padding:12px 14px}
      #pregame-defense-player-modal-v2 .pde-choice small{display:block;color:#667085;margin-top:2px}
      #pregame-defense-player-modal-v2 .pde-choice.current{background:#f2f7ff}
      #pregame-defense-editor-v2 + .row.d-none.d-lg-flex{display:none !important}
      #rotation-board.pde-explicit-active #diamond-parent-mobile{display:none !important}
      #rotation-board.pde-explicit-active #diamond-parent-mobile + h5,
      #rotation-board.pde-explicit-active #diamond-parent-mobile + h5 + ul,
      #rotation-board.pde-explicit-active #diamond-parent-mobile + h5 + ul + hr,
      #rotation-board.pde-explicit-active #diamond-parent-mobile + h5 + ul + hr + h5,
      #rotation-board.pde-explicit-active #summary-mobile{display:none !important}
      @media(max-width:575.98px){
        #pregame-defense-editor-v2 .pde-head{padding:12px 12px 10px}
        #pregame-defense-editor-v2 .pde-body{padding:11px 12px 13px}
        #pregame-defense-editor-v2 .pde-tools{grid-template-columns:1fr 1fr}
        #pregame-defense-editor-v2 .pde-tools .pde-preset-select{grid-column:1/-1}
        #pregame-defense-editor-v2 .pde-slot{padding:7px 4px}
        #pregame-defense-editor-v2 .pde-name{font-size:.66rem}
        #pregame-defense-editor-v2 .pde-row.battery{max-width:72%}
      }
      @media(min-width:576px) and (max-width:1024px){
        #pregame-defense-editor-v2 .pde-name{font-size:.78rem}
        #pregame-defense-editor-v2 .pde-field{padding:14px}
      }
    `;
    document.head.appendChild(style);
  }

  function toast(message, kind='success') {
    let host = $('pregame-defense-toast-v2');
    if (!host) {
      host = document.createElement('div');
      host.id = 'pregame-defense-toast-v2';
      host.className = 'toast-container position-fixed top-0 end-0 p-3';
      host.style.zIndex = '5000';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    host.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el,{delay:3200});
    el.addEventListener('hidden.bs.toast',()=>el.remove(),{once:true});
    instance.show();
  }

  function ensureRotation() {
    if (!state.rotation) {
      state.rotation = {
        id:null,
        title:`Rotation for vs ${state.game?.opponent || 'Opponent'}`,
        innings:{'1':{}},
        associated_game_id:gameId,
      };
    }
    if (!state.rotation.innings || typeof state.rotation.innings !== 'object') state.rotation.innings = {'1':{}};
    if (!Object.keys(state.rotation.innings).length) state.rotation.innings['1'] = {};
    if (!state.rotation.innings[currentInning]) state.rotation.innings[currentInning] = {};
  }

  async function refreshState({render=true}={}) {
    try {
      const response = await fetch(`/api/game_data/${gameId}`,{cache:'no-store'});
      if (!response.ok) throw new Error(`Unable to load defense (${response.status}).`);
      const fresh = await response.json();
      const previousInning = currentInning;
      state = fresh;
      if (state.rotation && typeof state.rotation.innings === 'string') {
        try { state.rotation.innings = JSON.parse(state.rotation.innings); }
        catch (_) { state.rotation.innings = {'1':{}}; }
      }
      ensureRotation();
      const innings = Object.keys(state.rotation.innings).sort((a,b)=>parseFloat(a)-parseFloat(b));
      currentInning = innings.includes(previousInning) ? previousInning : (innings[0] || '1');
      filterWholeGameTemplateDropdown();
      if (render) renderEditor();
    } catch (err) {
      console.error('Pregame defense editor:',err);
    }
  }

  function filterWholeGameTemplateDropdown() {
    const select = $('rotationTemplateSelect');
    if (!select || !state) return;
    const presetIds = new Set(presets().map(p=>String(p.id)));
    [...select.options].forEach(option => {
      if (presetIds.has(String(option.value))) option.remove();
    });
  }

  function fieldSlot(pos, alignment) {
    const name = alignment[pos] || '';
    return `<button type="button" class="pde-slot ${name ? '' : 'open'}" data-pde-pos="${esc(pos)}"><span class="pde-pos">${esc(pos)}</span><span class="pde-name">${esc(name || 'OPEN')}</span></button>`;
  }

  function renderEditor() {
    const board = $('rotation-board');
    if (!board || !state) return;

    const existing = $('pregame-defense-editor-v2');
    if (state.game?.is_live) {
      existing?.remove();
      board.classList.remove('pde-explicit-active');
      return;
    }

    board.classList.add('pde-explicit-active');
    ensureRotation();
    disableLegacyDragging();

    let panel = existing;
    if (!panel) {
      panel = document.createElement('section');
      panel.id = 'pregame-defense-editor-v2';
      const toolbar = board.querySelector(':scope > .mb-3.planner-controls');
      if (toolbar) toolbar.insertAdjacentElement('afterend',panel);
      else board.prepend(panel);
    }

    const alignment = currentAlignment();
    const four = Number(state.outfielder_count) === 4;
    const outfield = four
      ? `<div class="pde-row of4">${['LF','LCF','RCF','RF'].map(pos=>fieldSlot(pos,alignment)).join('')}</div>`
      : `<div class="pde-row of3">${['LF','CF','RF'].map(pos=>fieldSlot(pos,alignment)).join('')}</div>`;
    const infield = `<div class="pde-row if">${['3B','SS','2B','1B'].map(pos=>fieldSlot(pos,alignment)).join('')}</div>`;
    const battery = `<div class="pde-row battery">${['P','C'].map(pos=>fieldSlot(pos,alignment)).join('')}</div>`;
    const assigned = new Set(Object.values(alignment).filter(Boolean));
    const bench = presentRoster().filter(player=>!assigned.has(player.name));
    const open = positions().filter(pos=>!alignment[pos]);
    const savedPresets = presets();

    panel.innerHTML = `
      <div class="pde-head">
        <div><div class="pde-kicker">Pregame Defense</div><div class="pde-title">Set Inning ${esc(currentInning)}</div><div class="pde-help">Tap a position and choose the player. Nothing auto-swaps or bounces back.</div></div>
        <div class="pde-inning"><small>INNING</small><strong>${esc(currentInning)}</strong></div>
      </div>
      <div class="pde-body">
        <div class="pde-tools">
          <select class="form-select pde-preset-select" id="pde-preset-select-v2"><option value="">Defense Preset…</option>${savedPresets.map(p=>`<option value="${p.id}">${esc(presetName(p))}</option>`).join('')}</select>
          <button type="button" class="btn btn-outline-primary" id="pde-apply-preset-v2" disabled>Apply to Inning ${esc(currentInning)}</button>
          <button type="button" class="btn btn-outline-secondary" id="pde-save-preset-v2">Save This Inning</button>
        </div>
        <div class="pde-field">${outfield}${infield}${battery}<div class="pde-bench"><div class="pde-label">Bench — Inning ${esc(currentInning)}</div><div class="pde-bench-list">${bench.length?bench.map(p=>`<span>${esc(p.name)}</span>`).join(''):'<span>None</span>'}</div></div></div>
        <div class="pde-status">${open.length?`<span class="pde-open-warning">Open: ${esc(open.join(', '))}</span>`:'<strong>Defense complete</strong>'} • Changes save automatically to this inning only.</div>
      </div>`;

    panel.querySelectorAll('[data-pde-pos]').forEach(button=>button.addEventListener('click',()=>openPlayerPicker(button.dataset.pdePos)));
    const presetSelect = $('pde-preset-select-v2');
    const applyButton = $('pde-apply-preset-v2');
    presetSelect?.addEventListener('change',()=>{ if (applyButton) applyButton.disabled = !presetSelect.value; });
    applyButton?.addEventListener('click',applyPreset);
    $('pde-save-preset-v2')?.addEventListener('click',openSavePresetModal);
  }

  function ensurePlayerModal() {
    let modal = $('pregame-defense-player-modal-v2');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'pregame-defense-player-modal-v2';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Choose Player</h5><div class="small text-muted" id="pde-player-modal-help-v2"></div></div><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body p-0"><div class="list-group list-group-flush" id="pde-player-list-v2"></div></div></div></div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function playerPosition(name,alignment) {
    return Object.entries(alignment).find(([,player])=>player===name)?.[0] || null;
  }

  function openPlayerPicker(targetPos) {
    const modal = ensurePlayerModal();
    const alignment = currentAlignment();
    const occupant = alignment[targetPos] || '';
    modal.querySelector('.modal-title').textContent = `${targetPos} — Choose Player`;
    $('pde-player-modal-help-v2').textContent = occupant ? `Currently ${occupant}. Choosing someone else sends ${occupant} to the bench unless you place him elsewhere.` : 'Open position. Choose who should play here.';

    const roster = presentRoster().map(player=>({player,pos:playerPosition(player.name,alignment)}));
    roster.sort((a,b)=>{
      if (a.player.name===occupant) return -1;
      if (b.player.name===occupant) return 1;
      if (!a.pos && b.pos) return -1;
      if (!b.pos && a.pos) return 1;
      return a.player.name.localeCompare(b.player.name);
    });

    const list = $('pde-player-list-v2');
    list.innerHTML = `${occupant?`<button type="button" class="list-group-item list-group-item-action pde-choice text-danger" data-pde-clear="1"><strong>Move ${esc(occupant)} to Bench</strong><small>Leave ${esc(targetPos)} open.</small></button>`:''}${roster.map(({player,pos})=>{
      let detail = 'On bench this inning';
      if (pos===targetPos) detail = `Currently at ${targetPos}`;
      else if (pos) detail = `Currently at ${pos} — ${pos} will become open`;
      return `<button type="button" class="list-group-item list-group-item-action pde-choice ${pos===targetPos?'current':''}" data-pde-player="${esc(player.name)}"><strong>${esc(player.name)}</strong><small>${esc(detail)}</small></button>`;
    }).join('')}`;

    list.onclick = async (event) => {
      const choice = event.target.closest('.pde-choice');
      if (!choice || busy) return;
      const draft = {...currentAlignment()};
      let message = '';
      if (choice.dataset.pdeClear) {
        const old = draft[targetPos];
        delete draft[targetPos];
        message = `${old} moved to bench. ${targetPos} is open.`;
      } else {
        const selected = choice.dataset.pdePlayer;
        const source = playerPosition(selected,draft);
        const displaced = draft[targetPos];
        if (source && source!==targetPos) delete draft[source];
        draft[targetPos] = selected;
        if (source && source!==targetPos) message = `${selected}: ${source} → ${targetPos}. ${source} is now open.`;
        else if (displaced && displaced!==selected) message = `${selected} → ${targetPos}. ${displaced} is now on the bench.`;
        else message = `${selected} set at ${targetPos}.`;
      }
      state.rotation.innings[currentInning] = draft;
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      renderEditor();
      try { await saveRotation(); toast(message); }
      catch (err) { toast(err.message,'danger'); await refreshState(); }
    };
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  async function saveRotation() {
    if (busy) return;
    busy = true;
    try {
      ensureRotation();
      const response = await fetch('/save_rotation',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          id:state.rotation.id,
          title:state.rotation.title || `Rotation for vs ${state.game?.opponent || 'Opponent'}`,
          innings:state.rotation.innings,
          associated_game_id:gameId,
        }),
      });
      const result = await response.json().catch(()=>({}));
      if (!response.ok || result.status==='error') throw new Error(result.message || 'Unable to save defense.');
      if (result.new_id) state.rotation.id = result.new_id;
    } finally {
      busy = false;
    }
  }

  async function applyPreset() {
    const select = $('pde-preset-select-v2');
    if (!select?.value || busy) return;
    const preset = presets().find(item=>String(item.id)===String(select.value));
    if (!preset) return;
    const name = presetName(preset);
    if (!confirm(`Apply “${name}” to Inning ${currentInning}? Only this inning will be replaced.`)) return;

    const source = preset.innings?.['1'] || Object.values(preset.innings || {})[0] || {};
    const present = new Set(presentRoster().map(player=>player.name));
    const draft = {};
    const unavailable = [];
    positions().forEach(pos=>{
      const player = source[pos];
      if (!player) return;
      if (present.has(player)) draft[pos] = player;
      else unavailable.push(player);
    });
    state.rotation.innings[currentInning] = draft;
    renderEditor();
    try {
      await saveRotation();
      if (unavailable.length) toast(`Preset applied. Open spots remain because ${[...new Set(unavailable)].join(', ')} is unavailable.`,'warning');
      else toast(`${name} applied to Inning ${currentInning}.`);
    } catch (err) {
      toast(err.message,'danger');
      await refreshState();
    }
  }

  function ensurePresetModal() {
    let modal = $('pregame-defense-preset-modal-v2');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'pregame-defense-preset-modal-v2';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Save Defense Preset</h5><div class="small text-muted">Save this inning's defense so it can be dropped into any one inning later.</div></div><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><label class="form-label fw-semibold" for="pde-preset-name-v2">Preset name</label><input id="pde-preset-name-v2" class="form-control form-control-lg" maxlength="60" placeholder="e.g. #1 Defense"><div class="form-text">This is separate from your full-game Pool/Bracket rotation templates.</div><div class="d-grid mt-3"><button type="button" class="btn btn-primary btn-lg" id="pde-confirm-save-preset-v2">Save Defense Preset</button></div></div></div></div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function openSavePresetModal() {
    const open = positions().filter(pos=>!currentAlignment()[pos]);
    if (open.length) return toast(`Fill ${open.join(', ')} before saving a defense preset.`,'warning');
    const modal = ensurePresetModal();
    const input = $('pde-preset-name-v2');
    input.value = '';
    $('pde-confirm-save-preset-v2').onclick = savePreset;
    bootstrap.Modal.getOrCreateInstance(modal).show();
    setTimeout(()=>input.focus(),250);
  }

  async function savePreset() {
    if (busy) return;
    const input = $('pde-preset-name-v2');
    const name = input.value.trim();
    if (!name) { input.classList.add('is-invalid'); return; }
    input.classList.remove('is-invalid');
    const duplicate = presets().some(item=>presetName(item).toLowerCase()===name.toLowerCase());
    if (duplicate) return toast(`A defense preset named “${name}” already exists.`,'warning');

    busy = true;
    const button = $('pde-confirm-save-preset-v2');
    if (button) { button.disabled=true; button.textContent='Saving…'; }
    try {
      const response = await fetch('/save_rotation_as_template',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({title:PRESET_PREFIX+name,innings:{'1':{...currentAlignment()}}}),
      });
      const result = await response.json().catch(()=>({}));
      if (!response.ok || result.status==='error') throw new Error(result.message || 'Unable to save defense preset.');
      if (result.new_template) state.rotation_templates.push(result.new_template);
      bootstrap.Modal.getOrCreateInstance($('pregame-defense-preset-modal-v2')).hide();
      filterWholeGameTemplateDropdown();
      renderEditor();
      toast(`${name} saved as a one-inning defense preset.`);
    } catch (err) {
      toast(err.message,'danger');
    } finally {
      busy=false;
      if (button) { button.disabled=false; button.textContent='Save Defense Preset'; }
    }
  }

  function disableLegacyDragging() {
    if (state?.game?.is_live) return;
    const legacyDesktop = $('diamond-parent-desktop')?.closest('.row');
    if (legacyDesktop) legacyDesktop.style.setProperty('display','none','important');
    const mobileParent = $('diamond-parent-mobile');
    const mobileSection = mobileParent?.closest('.d-lg-none');
    if (mobileSection) mobileSection.style.setProperty('display','none','important');
    if (window.Sortable?.get) {
      document.querySelectorAll('#bench-list-desktop, #diamond-parent-desktop .position-dropzone').forEach(el=>{
        try { window.Sortable.get(el)?.destroy(); } catch (_) {}
      });
    }
  }

  function syncInningFromLegacy(event) {
    const radio = event.target.closest?.('input[name="inning-radio"]');
    if (!radio || !state || state.game?.is_live) return;
    currentInning = radio.value;
    ensureRotation();
    renderEditor();
  }

  function scheduleRefresh(delay=2400) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(()=>refreshState(),delay);
  }

  function wireLegacySync() {
    document.addEventListener('change',syncInningFromLegacy,true);
    ['addInningBtn','addSubInningBtn','removeInningBtn','pasteToSelectedBtn','clearInningBtn','copyPreviousInningBtn'].forEach(id=>{
      $(id)?.addEventListener('click',()=>scheduleRefresh(),false);
    });
    $('rotationTemplateSelect')?.addEventListener('change',()=>scheduleRefresh(),false);

    const matrix = $('rotation-matrix-container');
    if (matrix) {
      const observer = new MutationObserver(()=>{
        disableLegacyDragging();
        filterWholeGameTemplateDropdown();
      });
      observer.observe(matrix,{childList:true,subtree:true});
    }
    setInterval(disableLegacyDragging,1200);
  }

  async function init() {
    installStyles();
    await refreshState();
    wireLegacySync();
    disableLegacyDragging();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',()=>setTimeout(init,0),{once:true});
  else setTimeout(init,0);
})();
