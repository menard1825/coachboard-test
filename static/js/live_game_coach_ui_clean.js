(() => {
  'use strict';

  const gameMatch = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!gameMatch) return;

  const gameId = Number(gameMatch[1]);
  const $ = (id) => document.getElementById(id);
  let enhanced = false;
  let defenseView = 'list';
  let bulkState = null;
  let bulkOriginal = null;
  let bulkDraft = null;

  function addStyles() {
    if ($('coach-live-polish-styles')) return;
    const style = document.createElement('style');
    style.id = 'coach-live-polish-styles';
    style.textContent = `
      #live-game-overlay.coach-live-polished { background:#f4f6f8 !important; padding:12px !important; }
      #live-game-overlay.coach-live-polished > :not(.coach-live-shell):not(.modal) { display:none !important; }
      .coach-live-shell { max-width:980px; margin:0 auto; }
      .coach-live-head { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:10px; }
      .coach-inning-pill { background:#111827; color:#fff; border-radius:14px; min-width:92px; padding:8px 12px; text-align:center; }
      .coach-inning-pill small { display:block; font-size:.68rem; opacity:.75; font-weight:800; letter-spacing:.05em; }
      .coach-inning-pill strong { display:block; font-size:1.6rem; line-height:1; }
      .coach-card { background:#fff; border:1px solid #e5e7eb; border-radius:16px; box-shadow:0 2px 8px rgba(15,23,42,.06); padding:12px; margin-bottom:10px; }
      .coach-label { font-size:.73rem; color:#6b7280; text-transform:uppercase; letter-spacing:.05em; font-weight:800; }
      .coach-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
      .coach-actions .btn { min-height:72px; border-radius:14px !important; font-weight:800; }
      .coach-actions .btn i { display:block; font-size:1.3rem; margin-bottom:2px; }
      #liveSetDefenseBtnCoach { grid-column:1 / -1; }
      .coach-defense-row { display:grid; grid-template-columns:46px 1fr; gap:10px; align-items:center; padding:9px 0; border-bottom:1px solid #eef0f2; }
      .coach-pos { display:flex; align-items:center; justify-content:center; width:42px; height:32px; border-radius:8px; background:#111827; color:#fff; font-weight:800; font-size:.76rem; }
      .coach-player-name { font-weight:750; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .coach-player-name.empty { color:#9ca3af; font-weight:600; }
      .coach-bench { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
      .coach-bench span { border:1px solid #d1d5db; background:#fff; border-radius:999px; padding:6px 10px; font-size:.78rem; font-weight:700; }
      .coach-view-toggle .btn { font-size:.75rem; font-weight:700; }
      .coach-field-grid { background:linear-gradient(#e9f7e8,#f7f4df); border:1px solid #d9e4d5; border-radius:14px; padding:10px 6px; margin-top:9px; }
      .coach-field-row { display:flex; justify-content:center; gap:6px; margin:7px 0; }
      .coach-field-spot { flex:1; min-width:0; max-width:145px; text-align:center; background:rgba(255,255,255,.93); border:1px solid rgba(0,0,0,.08); border-radius:9px; padding:6px 4px; }
      .coach-field-spot strong { display:block; color:#6b7280; font-size:.65rem; }
      .coach-field-spot span { display:block; font-weight:800; font-size:.74rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      #rotation-board.coach-live-board-hidden { display:none !important; }
      #live-defense-v2 .modal-dialog, #live-pitcher-picker-v2 .modal-dialog, #live-defense-destination-v2 .modal-dialog, #live-pitcher-destination-v2 .modal-dialog { margin:.55rem; }
      #live-defense-v2 .list-group-item, #live-pitcher-picker-v2 .pitcher-choice-v2 { border:1px solid #e1e5ea !important; border-radius:12px !important; margin-bottom:8px; padding:13px !important; }
      #live-defense-destination-v2 .btn, #live-pitcher-destination-v2 .btn { min-height:68px; border-radius:12px; font-weight:800; }
      #live-defense-v2 .modal-title::after { content:' - Pick a player, then a destination'; font-size:.72rem; font-weight:400; color:#6b7280; }
      .bulk-defense-row { display:grid; grid-template-columns:52px 1fr; gap:10px; align-items:center; margin-bottom:8px; }
      .bulk-defense-row .form-select { min-height:48px; font-weight:650; }
      .bulk-defense-source .btn { border-radius:999px; font-size:.78rem; }
      .bulk-defense-bench { display:flex; flex-wrap:wrap; gap:6px; }
      .bulk-defense-bench span { border:1px solid #d1d5db; border-radius:999px; padding:6px 10px; font-size:.78rem; background:#fff; }
      .bulk-pending { position:sticky; bottom:0; background:rgba(255,255,255,.97); border-top:1px solid #e5e7eb; margin:12px -16px -16px; padding:12px 16px; z-index:2; }
      @media (min-width:768px) { .coach-actions { grid-template-columns:repeat(5,1fr); } #liveSetDefenseBtnCoach { grid-column:auto; } }
    `;
    document.head.appendChild(style);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[ch]));
  }

  function positionsFromOutfieldCount(count) {
    return Number(count) === 4 ? ['P','C','1B','2B','3B','SS','LF','LCF','RCF','RF'] : ['P','C','1B','2B','3B','SS','LF','CF','RF'];
  }

  function positionsFromDom() {
    return $('pos-mobile-LCF') || $('pos-desktop-LCF') ? ['P','C','1B','2B','3B','SS','LF','LCF','RCF','RF'] : ['P','C','1B','2B','3B','SS','LF','CF','RF'];
  }

  function currentMode() { return window.matchMedia('(min-width: 992px)').matches ? 'desktop' : 'mobile'; }

  function posName(pos, mode) {
    const tag = $(`pos-${mode}-${pos}`)?.querySelector('.player-tag');
    return tag?.dataset?.playerName || tag?.textContent?.trim() || '';
  }

  function currentDefense() {
    const mode = currentMode();
    const result = {};
    positionsFromDom().forEach(pos => { result[pos] = posName(pos, mode); });
    return result;
  }

  function benchNames() {
    const host = currentMode() === 'desktop' ? $('bench-list-desktop') : $('bench-list-mobile');
    if (!host) return [];
    return [...host.querySelectorAll('.player-tag, .badge')].map(el => el.dataset?.playerName || el.textContent.trim()).filter(name => name && !/No one on bench/i.test(name));
  }

  function listMarkup() {
    const defense = currentDefense();
    const rows = positionsFromDom().map(pos => `<div class="coach-defense-row"><div class="coach-pos">${esc(pos)}</div><div class="coach-player-name ${defense[pos] ? '' : 'empty'}">${esc(defense[pos] || 'Open')}</div></div>`).join('');
    const bench = benchNames();
    return `${rows}<div class="coach-label mt-3">Bench</div><div class="coach-bench">${bench.length ? bench.map(name => `<span>${esc(name)}</span>`).join('') : '<span>No players on bench</span>'}</div>`;
  }

  function spot(pos, defense) { return `<div class="coach-field-spot"><strong>${esc(pos)}</strong><span>${esc(defense[pos] || 'Open')}</span></div>`; }

  function fieldMarkup() {
    const defense = currentDefense();
    const out = positionsFromDom().includes('LCF') ? ['LF','LCF','RCF','RF'] : ['LF','CF','RF'];
    return `<div class="coach-field-grid"><div class="coach-field-row">${out.map(pos => spot(pos, defense)).join('')}</div><div class="coach-field-row">${['3B','SS','2B','1B'].map(pos => spot(pos, defense)).join('')}</div><div class="coach-field-row">${spot('P', defense)}</div><div class="coach-field-row">${spot('C', defense)}</div></div><div class="small text-muted text-center mt-2">Display only - use Quick Change or Set New Defense to move players.</div>`;
  }

  function refreshDefense() {
    const host = $('coach-current-defense');
    if (!host) return;
    host.innerHTML = defenseView === 'list' ? listMarkup() : fieldMarkup();
    document.querySelectorAll('[data-coach-defense-view]').forEach(btn => {
      const active = btn.dataset.coachDefenseView === defenseView;
      btn.classList.toggle('btn-dark', active);
      btn.classList.toggle('btn-outline-dark', !active);
    });
  }

  function toast(message, kind = 'success') {
    let container = $('coach-live-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'coach-live-toast-container';
      container.className = 'toast-container position-fixed top-0 end-0 p-3';
      container.style.zIndex = '3000';
      document.body.appendChild(container);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    container.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el, { delay:2600 });
    el.addEventListener('hidden.bs.toast', () => el.remove(), { once:true });
    instance.show();
  }

  async function fetchLiveState() {
    const response = await fetch(`/api/live-game/${gameId}/state`, { cache:'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || `Unable to load game state (${response.status}).`);
    return data;
  }

  function enhance() {
    const overlay = $('live-game-overlay');
    if (!overlay || overlay.classList.contains('d-none') || enhanced) return;
    addStyles();
    overlay.classList.add('coach-live-polished');
    const inning = $('live-inning-display');
    const pitcherCard = $('live-current-pitcher')?.closest('.card');
    const endGame = $('liveEndGameBtn')?.closest('.d-grid') || $('liveEndGameBtn');
    const actionButtons = ['liveChangePitcherBtn','liveDefensiveChangeBtn','liveEndInningBtn','liveUndoBtn'].map(id => $(id)).filter(Boolean);
    const shell = document.createElement('div');
    shell.className = 'coach-live-shell';
    shell.innerHTML = `<div class="coach-live-head"><div><div class="coach-label">Live Dugout</div><div class="small text-muted">Actual game state - saved for every coach</div></div><div class="coach-inning-pill"><small>INNING</small><strong id="coach-inning-copy">${esc(inning?.textContent || '1')}</strong></div></div><div id="coach-pitcher-slot"></div><div class="coach-actions" id="coach-action-slot"></div><div class="coach-card"><div class="d-flex align-items-center justify-content-between gap-2"><div><div class="coach-label">Current Defense</div><div class="small text-muted">List view is fastest in the dugout</div></div><div class="btn-group coach-view-toggle"><button class="btn btn-dark" data-coach-defense-view="list"><i class="bi bi-list-ul"></i> List</button><button class="btn btn-outline-dark" data-coach-defense-view="field"><i class="bi bi-diamond"></i> Field</button></div></div><div id="coach-current-defense" class="mt-2"></div></div><div id="coach-existing-extra"></div>`;
    overlay.appendChild(shell);
    const sync = $('live-sync-status-v2');
    if (sync) shell.querySelector('.coach-live-head > div:first-child').prepend(sync);
    if (pitcherCard) { pitcherCard.classList.add('coach-card'); pitcherCard.classList.remove('border-primary'); shell.querySelector('#coach-pitcher-slot').appendChild(pitcherCard); }
    const quickChange = $('liveDefensiveChangeBtn');
    if (quickChange) { quickChange.innerHTML = '<i class="bi bi-arrow-left-right"></i><span class="fw-bold">Quick Change</span>'; quickChange.title = 'Move or swap one defensive player'; }
    actionButtons.forEach(btn => shell.querySelector('#coach-action-slot').appendChild(btn));
    const setDefense = document.createElement('button');
    setDefense.type = 'button';
    setDefense.id = 'liveSetDefenseBtnCoach';
    setDefense.className = 'btn btn-warning text-dark w-100 shadow-sm';
    setDefense.innerHTML = '<i class="bi bi-people-fill"></i><span class="fw-bold">Set New Defense</span><span class="d-block small fw-normal">Make several changes at once</span>';
    setDefense.addEventListener('click', openBulkDefense);
    shell.querySelector('#coach-action-slot').insertBefore(setDefense, $('liveEndInningBtn') || null);
    const extra = shell.querySelector('#coach-existing-extra');
    const upNext = $('live-up-next-v2');
    if (upNext) extra.appendChild(upNext);
    if (endGame) extra.appendChild(endGame);
    $('rotation-board')?.classList.add('coach-live-board-hidden');
    if ($('rotation-editor-title')) $('rotation-editor-title').textContent = 'Live Dugout';
    shell.addEventListener('click', event => { const view = event.target.closest('[data-coach-defense-view]'); if (!view) return; defenseView = view.dataset.coachDefenseView; refreshDefense(); });
    enhanced = true;
    refreshDefense();
  }

  function ensureBulkModal() {
    let modal = $('live-bulk-defense-coach');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'live-bulk-defense-coach';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('data-bs-backdrop', 'static');
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Set New Defense</h5><div class="small text-muted">Make all the changes, then save once.</div></div><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body" id="bulk-defense-body"></div></div></div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function inningNumber(value) { const n = Number.parseFloat(value); return Number.isFinite(n) ? n : null; }

  function previousInningKey(state) {
    const current = inningNumber(state.current_inning);
    if (current === null) return null;
    const keys = Object.keys(state.actual_rotation || {}).map(key => ({ key, value:inningNumber(key) })).filter(x => x.value !== null && x.value < current).sort((a,b) => b.value - a.value);
    return keys[0]?.key || null;
  }

  function cleanAlignment(source, state) {
    const cleaned = {};
    positionsFromOutfieldCount(state.outfielder_count).forEach(pos => { cleaned[pos] = source?.[pos] || ''; });
    cleaned.P = state.current_alignment?.P || '';
    return cleaned;
  }

  function changedCount(a, b, positions) { return positions.filter(pos => pos !== 'P' && (a?.[pos] || '') !== (b?.[pos] || '')).length; }

  function bulkBenchNames() {
    const assigned = new Set(Object.values(bulkDraft || {}).filter(Boolean));
    return (bulkState?.roster || []).map(p => p.name).filter(name => !assigned.has(name));
  }

  function setBulkSource(source) {
    if (!bulkState) return;
    const currentInning = String(bulkState.current_inning || '1');
    if (source === 'current') bulkDraft = cleanAlignment(bulkState.current_alignment || {}, bulkState);
    if (source === 'planned') bulkDraft = cleanAlignment(bulkState.rotation?.innings?.[currentInning] || {}, bulkState);
    if (source === 'previous') { const key = previousInningKey(bulkState); bulkDraft = cleanAlignment(key ? bulkState.actual_rotation?.[key] || {} : bulkState.current_alignment || {}, bulkState); }
    renderBulkDefense(source);
  }

  function renderBulkDefense(activeSource = 'current') {
    const body = $('bulk-defense-body');
    if (!body || !bulkState || !bulkDraft) return;
    const positions = positionsFromOutfieldCount(bulkState.outfielder_count);
    const currentInning = String(bulkState.current_inning || '1');
    const previousKey = previousInningKey(bulkState);
    const plannedExists = Boolean(bulkState.rotation?.innings?.[currentInning]);
    const roster = [...(bulkState.roster || [])].sort((a,b) => a.name.localeCompare(b.name));
    const currentPitcher = bulkState.current_alignment?.P || 'None';
    const changed = changedCount(bulkDraft, bulkOriginal, positions);
    const bench = bulkBenchNames();
    const sourceButton = (source, label, enabled = true) => `<button type="button" class="btn ${activeSource === source ? 'btn-dark' : 'btn-outline-secondary'}" data-bulk-source="${source}" ${enabled ? '' : 'disabled'}>${esc(label)}</button>`;
    const rows = positions.map(pos => {
      if (pos === 'P') return `<div class="bulk-defense-row"><div class="coach-pos">P</div><div class="form-control bg-light d-flex justify-content-between align-items-center" style="min-height:48px"><strong>${esc(currentPitcher)}</strong><span class="badge text-bg-secondary">Locked</span></div></div>`;
      const selected = bulkDraft[pos] || '';
      const options = ['<option value="">Open / Bench current player</option>'].concat(roster.filter(player => player.name !== currentPitcher).map(player => `<option value="${esc(player.name)}" ${player.name === selected ? 'selected' : ''}>${esc(player.name)}</option>`)).join('');
      return `<div class="bulk-defense-row"><div class="coach-pos">${esc(pos)}</div><select class="form-select bulk-defense-select" data-pos="${esc(pos)}">${options}</select></div>`;
    }).join('');
    body.innerHTML = `<div class="alert alert-info py-2 small mb-3"><strong>Pitcher stays ${esc(currentPitcher)}.</strong> Use Change Pitcher if P is changing. Everything else below saves as one defensive event.</div><div class="coach-label mb-2">Start from</div><div class="d-flex flex-wrap gap-2 bulk-defense-source mb-3">${sourceButton('current','Current Defense')}${sourceButton('planned',`Planned Inning ${currentInning}`,plannedExists)}${sourceButton('previous',previousKey ? `Previous Inning ${previousKey}` : 'Previous Inning',Boolean(previousKey))}</div>${rows}<div class="coach-label mt-3 mb-2">Bench after changes</div><div class="bulk-defense-bench">${bench.length ? bench.map(name => `<span>${esc(name)}</span>`).join('') : '<span>No players on bench</span>'}</div><div class="bulk-pending d-flex align-items-center gap-2"><div class="me-auto"><strong>${changed}</strong> ${changed === 1 ? 'change' : 'changes'} pending<div class="small text-muted">One Undo will reverse the whole set.</div></div><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button><button type="button" class="btn btn-success fw-bold" id="applyBulkDefenseBtn" ${changed ? '' : 'disabled'}>Apply ${changed || ''} ${changed === 1 ? 'Change' : 'Changes'}</button></div>`;
    body.querySelectorAll('[data-bulk-source]').forEach(btn => btn.addEventListener('click', () => setBulkSource(btn.dataset.bulkSource)));
    body.querySelectorAll('.bulk-defense-select').forEach(select => select.addEventListener('change', () => {
      const pos = select.dataset.pos;
      const oldName = bulkDraft[pos] || '';
      const newName = select.value || '';
      if (oldName === newName) return;
      if (newName) { const otherPos = positions.find(other => other !== pos && other !== 'P' && bulkDraft[other] === newName); if (otherPos) bulkDraft[otherPos] = oldName; }
      bulkDraft[pos] = newName;
      renderBulkDefense(activeSource);
    }));
    $('applyBulkDefenseBtn')?.addEventListener('click', applyBulkDefense);
  }

  async function openBulkDefense() {
    try {
      bulkState = await fetchLiveState();
      if (!bulkState.game?.is_live) throw new Error('This game is not live.');
      bulkOriginal = cleanAlignment(bulkState.current_alignment || {}, bulkState);
      bulkDraft = cleanAlignment(bulkState.current_alignment || {}, bulkState);
      ensureBulkModal();
      renderBulkDefense('current');
      bootstrap.Modal.getOrCreateInstance($('live-bulk-defense-coach')).show();
    } catch (err) { toast(err.message, 'danger'); }
  }

  async function applyBulkDefense() {
    const btn = $('applyBulkDefenseBtn');
    if (!btn || !bulkState || !bulkDraft) return;
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = 'Saving...';
    try {
      const response = await fetch(`/api/live-game/${gameId}/set-defense`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ alignment:bulkDraft }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || `Unable to save defense (${response.status}).`);
      bootstrap.Modal.getOrCreateInstance($('live-bulk-defense-coach')).hide();
      const count = changedCount(bulkDraft, bulkOriginal, positionsFromOutfieldCount(bulkState.outfielder_count));
      toast(`Saved ${count} defensive ${count === 1 ? 'change' : 'changes'} as one event.`);
      setTimeout(refreshDefense, 250);
    } catch (err) { btn.disabled = false; btn.textContent = originalText; toast(err.message, 'danger'); }
  }

  function polishLiveModals() {
    document.querySelectorAll('#live-defense-v2 .list-group-item').forEach(item => {
      if (item.querySelector('strong')?.textContent?.trim() === 'P') { item.setAttribute('disabled','disabled'); item.classList.add('opacity-50'); item.title = 'Use Change Pitcher to replace the pitcher.'; }
    });
    document.querySelectorAll('#live-defense-destination-v2 [data-destination="P"]').forEach(btn => {
      btn.setAttribute('disabled','disabled'); btn.classList.add('opacity-50');
      if (!btn.querySelector('.coach-use-pitcher-note')) btn.insertAdjacentHTML('beforeend','<div class="small coach-use-pitcher-note">Use Change Pitcher</div>');
    });
    document.querySelectorAll('#live-pitcher-picker-v2 .pitcher-choice-v2').forEach(btn => {
      if (/Pitch Count Incomplete|Eligibility unknown/i.test(btn.textContent || '')) { btn.setAttribute('disabled','disabled'); btn.classList.add('opacity-50'); }
    });
  }

  function keepExistingExtrasInShell() {
    const extra = $('coach-existing-extra');
    if (!extra) return;
    const upNext = $('live-up-next-v2');
    if (upNext && !extra.contains(upNext)) extra.prepend(upNext);
    const endGame = $('liveEndGameBtn')?.closest('.d-grid') || $('liveEndGameBtn');
    if (endGame && !extra.contains(endGame)) extra.appendChild(endGame);
  }

  function tick() {
    const overlay = $('live-game-overlay');
    if (overlay && !overlay.classList.contains('d-none')) {
      enhance();
      if (enhanced) {
        if ($('coach-inning-copy') && $('live-inning-display')) $('coach-inning-copy').textContent = $('live-inning-display').textContent;
        keepExistingExtrasInShell();
        refreshDefense();
        polishLiveModals();
      }
    } else if (enhanced) {
      $('rotation-board')?.classList.remove('coach-live-board-hidden');
      if ($('rotation-editor-title')) $('rotation-editor-title').textContent = 'Defensive Rotation';
    }
  }

  document.addEventListener('DOMContentLoaded', () => { addStyles(); tick(); setInterval(tick, 800); });
})();
