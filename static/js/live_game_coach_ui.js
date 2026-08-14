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
  let lastDefenseSignature = '';

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function addStyles() {
    if ($('coach-live-polish-styles')) return;
    const style = document.createElement('style');
    style.id = 'coach-live-polish-styles';
    style.textContent = `
      .coach-game-header { gap:14px; align-items:flex-start !important; padding:2px 0 8px; }
      .coach-game-header h3 { font-size:clamp(1.55rem,4.2vw,2rem); line-height:1.12; letter-spacing:-.02em; }
      .coach-game-meta { display:flex; flex-wrap:wrap; align-items:center; gap:6px 10px; margin-top:7px; color:#667085 !important; font-size:.94rem; }
      .coach-game-meta .meta-divider { color:#c2c8d0; }
      .coach-game-meta .meta-location { flex-basis:auto; }
      .coach-game-header-actions { display:flex; gap:6px; flex-shrink:0; }
      .coach-game-header-actions .btn { border-radius:9px; font-weight:650; }

      #live-game-overlay.coach-live-polished { background:#f5f6f8 !important; padding:10px !important; }
      #live-game-overlay.coach-live-polished > :not(.coach-live-shell):not(.modal) { display:none !important; }
      .coach-live-shell { max-width:980px; margin:0 auto; }
      .coach-live-head { display:flex; justify-content:space-between; align-items:flex-start; gap:14px; margin-bottom:10px; }
      .coach-live-kicker { font-size:.68rem; color:#667085; text-transform:uppercase; letter-spacing:.11em; font-weight:800; }
      .coach-live-context { margin-top:2px; color:#344054; font-size:.9rem; font-weight:650; }
      .coach-live-subcontext { color:#8a94a3; font-size:.76rem; margin-top:1px; }
      .coach-inning-pill { background:#172033; color:#fff; border-radius:10px; min-width:74px; padding:8px 10px; text-align:center; box-shadow:0 1px 2px rgba(16,24,40,.12); }
      .coach-inning-pill small { display:block; font-size:.58rem; opacity:.7; font-weight:750; letter-spacing:.1em; }
      .coach-inning-pill strong { display:block; font-size:1.45rem; line-height:1.05; margin-top:2px; }
      .coach-card { background:#fff; border:1px solid #e4e7ec; border-radius:13px; box-shadow:0 1px 3px rgba(16,24,40,.06); padding:12px; margin-bottom:10px; }
      .coach-label { font-size:.66rem; color:#667085; text-transform:uppercase; letter-spacing:.09em; font-weight:800; }
      .coach-help { color:#98a2b3; font-size:.76rem; margin-top:1px; }

      .coach-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
      .coach-actions .btn { min-height:58px; border-radius:11px !important; padding:8px 10px; box-shadow:none !important; text-align:left; display:flex !important; flex-direction:column; justify-content:center; align-items:flex-start !important; line-height:1.1; }
      .coach-actions .btn i { display:none !important; }
      .coach-action-title { display:block; font-weight:780; font-size:.94rem; }
      .coach-action-note { display:block; margin-top:4px; font-size:.67rem; font-weight:550; opacity:.68; }
      .coach-action-primary { background:var(--primary-color,#102a66) !important; border-color:var(--primary-color,#102a66) !important; color:#fff !important; }
      .coach-action-secondary { background:#fff !important; border:1px solid #cfd5dd !important; color:#273142 !important; }
      .coach-action-end { background:#202733 !important; border-color:#202733 !important; color:#fff !important; }
      .coach-action-undo { background:#fff !important; border:1px solid #d6dae1 !important; color:#5f6b7a !important; }
      #liveSetDefenseBtnCoach { grid-column:1 / -1; border:1px solid var(--primary-color,#102a66) !important; background:#f7f9fc !important; color:var(--primary-color,#102a66) !important; }

      .coach-defense-row { display:grid; grid-template-columns:42px minmax(0,1fr); gap:9px; align-items:center; padding:8px 0; border-bottom:1px solid #f0f1f3; }
      .coach-defense-row:last-child { border-bottom:0; }
      .coach-pos { display:flex; align-items:center; justify-content:center; width:38px; height:28px; border-radius:7px; background:#eef1f5; color:#344054; font-weight:800; font-size:.7rem; }
      .coach-player-name { font-weight:700; color:#1d2939; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .coach-player-name.empty { color:#98a2b3; font-weight:600; }
      .coach-bench { display:flex; flex-wrap:wrap; gap:6px; margin-top:7px; }
      .coach-bench span { border:1px solid #e0e4e9; background:#f8f9fb; color:#475467; border-radius:999px; padding:5px 9px; font-size:.72rem; font-weight:650; }

      .coach-view-toggle { padding:2px; border:1px solid #d9dde4; background:#f4f5f7; border-radius:9px; }
      .coach-view-toggle .btn { border:0 !important; border-radius:7px !important; padding:6px 11px; min-height:0; font-size:.72rem; font-weight:750; box-shadow:none !important; }
      .coach-view-toggle .btn-dark { background:#fff !important; color:#1d2939 !important; box-shadow:0 1px 2px rgba(16,24,40,.08) !important; }
      .coach-view-toggle .btn-outline-dark { background:transparent !important; color:#7b8492 !important; }

      .coach-field { position:relative; width:100%; aspect-ratio:1.08 / 1; max-height:520px; margin-top:10px; overflow:hidden; border:1px solid #dfe5de; border-radius:14px; background:linear-gradient(180deg,#edf5ec 0%,#f7f6ed 100%); }
      .coach-field-infield { position:absolute; width:37%; aspect-ratio:1; left:31.5%; top:38%; border:1px solid rgba(143,126,91,.34); background:rgba(232,220,186,.28); transform:rotate(45deg); border-radius:3px; }
      .coach-field-arc { position:absolute; left:12%; right:12%; top:8%; height:60%; border:1px solid rgba(93,132,92,.20); border-bottom:0; border-radius:50% 50% 0 0; }
      .coach-field-spot { position:absolute; transform:translate(-50%,-50%); text-align:center; min-width:70px; max-width:112px; }
      .coach-field-spot strong { display:block; color:#7b8492; font-size:.58rem; line-height:1; letter-spacing:.06em; margin-bottom:3px; }
      .coach-field-spot span { display:block; padding:5px 7px; border-radius:8px; border:1px solid rgba(208,213,221,.9); background:rgba(255,255,255,.92); color:#1d2939; font-weight:750; font-size:.68rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; box-shadow:0 1px 2px rgba(16,24,40,.05); }
      .coach-field-help { text-align:center; color:#98a2b3; font-size:.7rem; margin-top:7px; }

      #rotation-board.coach-live-board-hidden { display:none !important; }
      #live-defense-v2 .modal-dialog, #live-pitcher-picker-v2 .modal-dialog, #live-defense-destination-v2 .modal-dialog, #live-pitcher-destination-v2 .modal-dialog { margin:.55rem; }
      #live-defense-v2 .list-group-item, #live-pitcher-picker-v2 .pitcher-choice-v2 { border:1px solid #e4e7ec !important; border-radius:10px !important; margin-bottom:7px; padding:12px !important; }
      #live-defense-destination-v2 .btn, #live-pitcher-destination-v2 .btn { min-height:60px; border-radius:10px; font-weight:750; }
      #live-defense-v2 .modal-title::after { content:' - choose a player, then a position'; font-size:.7rem; font-weight:400; color:#7b8492; }

      .bulk-defense-row { display:grid; grid-template-columns:46px 1fr; gap:9px; align-items:center; margin-bottom:8px; }
      .bulk-defense-row .form-select { min-height:46px; font-weight:650; border-radius:9px; }
      .bulk-defense-source .btn { border-radius:999px; font-size:.73rem; }
      .bulk-defense-bench { display:flex; flex-wrap:wrap; gap:6px; }
      .bulk-defense-bench span { border:1px solid #dfe3e8; border-radius:999px; padding:5px 9px; font-size:.72rem; background:#f8f9fb; }
      .bulk-pending { position:sticky; bottom:0; background:rgba(255,255,255,.97); border-top:1px solid #e5e7eb; margin:12px -16px -16px; padding:12px 16px; z-index:2; }

      @media (max-width:575.98px) {
        .coach-game-header { display:block !important; }
        .coach-game-header-actions { margin-top:10px; }
        .coach-game-header-actions .btn { flex:1; }
        .coach-game-meta .meta-location { flex-basis:100%; }
        #live-game-overlay.coach-live-polished { padding:8px !important; }
        .coach-card { border-radius:12px; padding:11px; }
        .coach-field-spot { min-width:58px; max-width:82px; }
        .coach-field-spot span { font-size:.62rem; padding:4px 5px; }
      }
      @media (min-width:768px) {
        .coach-actions { grid-template-columns:repeat(5,1fr); }
        #liveSetDefenseBtnCoach { grid-column:auto; }
      }
    `;
    document.head.appendChild(style);
  }

  function parseTime(value) {
    const match = String(value || '').match(/^(\d{1,2}):(\d{2})/);
    if (!match) return '';
    let hour = Number(match[1]);
    const minute = match[2];
    if (!Number.isFinite(hour)) return '';
    const suffix = hour >= 12 ? 'PM' : 'AM';
    hour %= 12;
    if (!hour) hour = 12;
    return `${hour}:${minute} ${suffix}`;
  }

  function formatGameHeader() {
    const pregame = $('pregame-checklist-container');
    if (!pregame) return;
    const header = pregame.firstElementChild;
    if (!header) return;
    header.classList.add('coach-game-header');

    const title = header.querySelector('h3');
    if (title) title.id = 'coach-game-title';

    const meta = header.querySelector('p.text-muted');
    if (meta) {
      const dateValue = $('game_date')?.value || '';
      const timeValue = $('game_start_time')?.value || '';
      const locationValue = $('game_location')?.value || '';
      let dateLabel = '';
      const parts = dateValue.match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (parts) {
        const localDate = new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]));
        if (!Number.isNaN(localDate.getTime())) {
          dateLabel = new Intl.DateTimeFormat('en-US', { weekday:'short', month:'short', day:'numeric' }).format(localDate);
        }
      }
      if (!dateLabel) dateLabel = dateValue;
      const timeLabel = parseTime(timeValue);
      const bits = [];
      if (dateLabel) bits.push(`<span class="meta-date">${esc(dateLabel)}</span>`);
      if (timeLabel) bits.push(`<span class="meta-divider">•</span><span class="meta-time">${esc(timeLabel)}</span>`);
      if (locationValue) bits.push(`<span class="meta-divider">•</span><span class="meta-location">${esc(locationValue)}</span>`);
      meta.className = 'coach-game-meta';
      meta.innerHTML = bits.join('');
      meta.id = 'coach-game-meta';
    }

    const actionWrap = header.lastElementChild;
    if (actionWrap && actionWrap !== header.firstElementChild) {
      actionWrap.classList.add('coach-game-header-actions');
      actionWrap.querySelectorAll('.btn i').forEach(icon => icon.remove());
      actionWrap.querySelectorAll('.btn').forEach(btn => btn.classList.remove('ms-1'));
    }
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

  function listMarkup(defense, bench) {
    const rows = positionsFromDom().map(pos => `<div class="coach-defense-row"><div class="coach-pos">${esc(pos)}</div><div class="coach-player-name ${defense[pos] ? '' : 'empty'}">${esc(defense[pos] || 'Open')}</div></div>`).join('');
    return `${rows}<div class="coach-label mt-3">Bench</div><div class="coach-bench">${bench.length ? bench.map(name => `<span>${esc(name)}</span>`).join('') : '<span>No players on bench</span>'}</div>`;
  }

  function fieldSpot(pos, defense, left, top) {
    return `<div class="coach-field-spot" style="left:${left}%;top:${top}%"><strong>${esc(pos)}</strong><span>${esc(defense[pos] || 'Open')}</span></div>`;
  }

  function fieldMarkup(defense) {
    const fourOutfielders = positionsFromDom().includes('LCF');
    const outfield = fourOutfielders ? [['LF',9,20],['LCF',36,11],['RCF',64,11],['RF',91,20]] : [['LF',13,19],['CF',50,9],['RF',87,19]];
    const spots = [...outfield,['3B',16,55],['SS',36,41],['2B',64,41],['1B',84,55],['P',50,61],['C',50,86]];
    return `<div class="coach-field"><div class="coach-field-arc"></div><div class="coach-field-infield"></div>${spots.map(([pos,left,top]) => fieldSpot(pos, defense, left, top)).join('')}</div><div class="coach-field-help">Reference view only. Use Quick Change or Set New Defense to move players.</div>`;
  }

  function refreshDefense(force = false) {
    const host = $('coach-current-defense');
    if (!host) return;
    const defense = currentDefense();
    const bench = benchNames();
    const signature = JSON.stringify({ defense, bench, defenseView });
    if (!force && signature === lastDefenseSignature) return;
    lastDefenseSignature = signature;
    host.innerHTML = defenseView === 'list' ? listMarkup(defense, bench) : fieldMarkup(defense);
    document.querySelectorAll('[data-coach-defense-view]').forEach(btn => {
      const active = btn.dataset.coachDefenseView === defenseView;
      btn.classList.toggle('btn-dark', active);
      btn.classList.toggle('btn-outline-dark', !active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
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

  function setActionContent(button, title, note, className) {
    if (!button) return;
    button.className = `btn w-100 ${className}`;
    button.innerHTML = `<span class="coach-action-title">${esc(title)}</span><span class="coach-action-note">${esc(note)}</span>`;
  }

  function gameContextText() {
    const title = $('coach-game-title')?.textContent?.trim() || '';
    const vsIndex = title.toLowerCase().indexOf(' vs ');
    return vsIndex >= 0 ? title.slice(vsIndex + 1) : title;
  }

  function enhance() {
    const overlay = $('live-game-overlay');
    if (!overlay || overlay.classList.contains('d-none') || enhanced) return;
    addStyles();
    overlay.classList.add('coach-live-polished');

    const inning = $('live-inning-display');
    const pitcherCard = $('live-current-pitcher')?.closest('.card');
    const endGame = $('liveEndGameBtn')?.closest('.d-grid') || $('liveEndGameBtn');
    const changePitcher = $('liveChangePitcherBtn');
    const quickChange = $('liveDefensiveChangeBtn');
    const endInning = $('liveEndInningBtn');
    const undo = $('liveUndoBtn');

    const shell = document.createElement('div');
    shell.className = 'coach-live-shell';
    const formattedMeta = $('coach-game-meta')?.textContent?.replace(/\s+/g, ' ').trim() || '';
    shell.innerHTML = `<div class="coach-live-head"><div><div class="coach-live-kicker">Live Dugout</div><div class="coach-live-context">${esc(gameContextText())}</div><div class="coach-live-subcontext">${esc(formattedMeta)}</div></div><div class="coach-inning-pill"><small>INNING</small><strong id="coach-inning-copy">${esc(inning?.textContent || '1')}</strong></div></div><div id="coach-pitcher-slot"></div><div class="coach-actions" id="coach-action-slot"></div><div class="coach-card"><div class="d-flex align-items-center justify-content-between gap-2"><div><div class="coach-label">Current Defense</div><div class="coach-help">List is quickest for in-game checks</div></div><div class="btn-group coach-view-toggle" role="group" aria-label="Defense view"><button class="btn btn-dark" data-coach-defense-view="list" aria-pressed="true">List</button><button class="btn btn-outline-dark" data-coach-defense-view="field" aria-pressed="false">Field</button></div></div><div id="coach-current-defense" class="mt-2"></div></div><div id="coach-existing-extra"></div>`;
    overlay.appendChild(shell);

    const sync = $('live-sync-status-v2');
    if (sync) {
      sync.classList.add('mb-1');
      shell.querySelector('.coach-live-head > div:first-child').prepend(sync);
    }
    if (pitcherCard) {
      pitcherCard.classList.add('coach-card');
      pitcherCard.classList.remove('border-primary');
      pitcherCard.querySelectorAll('i').forEach(icon => icon.remove());
      shell.querySelector('#coach-pitcher-slot').appendChild(pitcherCard);
    }

    setActionContent(changePitcher, 'Change Pitcher', 'Mound change', 'coach-action-primary');
    setActionContent(quickChange, 'Quick Change', 'Move one player', 'coach-action-secondary');
    setActionContent(endInning, 'End Inning', 'Load next plan', 'coach-action-end');
    setActionContent(undo, 'Undo', 'Revert last change', 'coach-action-undo');

    const actionSlot = shell.querySelector('#coach-action-slot');
    [changePitcher, quickChange].filter(Boolean).forEach(btn => actionSlot.appendChild(btn));
    const setDefense = document.createElement('button');
    setDefense.type = 'button';
    setDefense.id = 'liveSetDefenseBtnCoach';
    setDefense.className = 'btn w-100 coach-action-secondary';
    setDefense.innerHTML = '<span class="coach-action-title">Set New Defense</span><span class="coach-action-note">Change several players at once</span>';
    setDefense.addEventListener('click', openBulkDefense);
    actionSlot.appendChild(setDefense);
    [endInning, undo].filter(Boolean).forEach(btn => actionSlot.appendChild(btn));

    const extra = shell.querySelector('#coach-existing-extra');
    const upNext = $('live-up-next-v2');
    if (upNext) extra.appendChild(upNext);
    if (endGame) {
      const endButton = $('liveEndGameBtn');
      if (endButton) {
        endButton.classList.remove('btn-outline-danger');
        endButton.classList.add('btn-link','text-danger','text-decoration-none','px-0','small');
        endButton.innerHTML = 'End Game & Enter Final Pitch Counts';
      }
      extra.appendChild(endGame);
    }

    $('rotation-board')?.classList.add('coach-live-board-hidden');
    if ($('rotation-editor-title')) $('rotation-editor-title').textContent = 'Live Dugout';
    shell.addEventListener('click', event => {
      const view = event.target.closest('[data-coach-defense-view]');
      if (!view) return;
      defenseView = view.dataset.coachDefenseView;
      refreshDefense(true);
    });
    enhanced = true;
    refreshDefense(true);
  }

  function ensureBulkModal() {
    let modal = $('live-bulk-defense-coach');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'live-bulk-defense-coach';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('data-bs-backdrop','static');
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Set New Defense</h5><div class="small text-muted">Make all position changes, then apply once.</div></div><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body" id="bulk-defense-body"></div></div></div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function inningNumber(value) {
    const n = Number.parseFloat(value);
    return Number.isFinite(n) ? n : null;
  }

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

  function changedCount(a, b, positions) {
    return positions.filter(pos => pos !== 'P' && (a?.[pos] || '') !== (b?.[pos] || '')).length;
  }

  function bulkBenchNames() {
    const assigned = new Set(Object.values(bulkDraft || {}).filter(Boolean));
    return (bulkState?.roster || []).map(p => p.name).filter(name => !assigned.has(name));
  }

  function setBulkSource(source) {
    if (!bulkState) return;
    const currentInning = String(bulkState.current_inning || '1');
    if (source === 'current') bulkDraft = cleanAlignment(bulkState.current_alignment || {}, bulkState);
    if (source === 'planned') bulkDraft = cleanAlignment(bulkState.rotation?.innings?.[currentInning] || {}, bulkState);
    if (source === 'previous') {
      const key = previousInningKey(bulkState);
      bulkDraft = cleanAlignment(key ? bulkState.actual_rotation?.[key] || {} : bulkState.current_alignment || {}, bulkState);
    }
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
    const sourceButton = (source,label,enabled=true) => `<button type="button" class="btn ${activeSource === source ? 'btn-dark' : 'btn-outline-secondary'}" data-bulk-source="${source}" ${enabled ? '' : 'disabled'}>${esc(label)}</button>`;
    const rows = positions.map(pos => {
      if (pos === 'P') return `<div class="bulk-defense-row"><div class="coach-pos">P</div><div class="form-control bg-light d-flex justify-content-between align-items-center" style="min-height:46px"><strong>${esc(currentPitcher)}</strong><span class="badge text-bg-secondary">Pitcher locked</span></div></div>`;
      const selected = bulkDraft[pos] || '';
      const options = ['<option value="">Open / Bench current player</option>'].concat(roster.filter(player => player.name !== currentPitcher).map(player => `<option value="${esc(player.name)}" ${player.name === selected ? 'selected' : ''}>${esc(player.name)}</option>`)).join('');
      return `<div class="bulk-defense-row"><div class="coach-pos">${esc(pos)}</div><select class="form-select bulk-defense-select" data-pos="${esc(pos)}">${options}</select></div>`;
    }).join('');
    body.innerHTML = `<div class="small text-muted mb-3"><strong class="text-dark">Pitcher stays ${esc(currentPitcher)}.</strong> Use Change Pitcher for the mound.</div><div class="coach-label mb-2">Start from</div><div class="d-flex flex-wrap gap-2 bulk-defense-source mb-3">${sourceButton('current','Current Defense')}${sourceButton('planned',`Planned Inning ${currentInning}`,plannedExists)}${sourceButton('previous',previousKey ? `Previous Inning ${previousKey}` : 'Previous Inning',Boolean(previousKey))}</div>${rows}<div class="coach-label mt-3 mb-2">Bench after changes</div><div class="bulk-defense-bench">${bench.length ? bench.map(name => `<span>${esc(name)}</span>`).join('') : '<span>No players on bench</span>'}</div><div class="bulk-pending d-flex align-items-center gap-2"><div class="me-auto"><strong>${changed}</strong> ${changed === 1 ? 'change' : 'changes'} pending<div class="small text-muted">One Undo reverses the whole set.</div></div><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button><button type="button" class="btn btn-dark fw-bold" id="applyBulkDefenseBtn" ${changed ? '' : 'disabled'}>Apply ${changed || ''} ${changed === 1 ? 'Change' : 'Changes'}</button></div>`;
    body.querySelectorAll('[data-bulk-source]').forEach(btn => btn.addEventListener('click', () => setBulkSource(btn.dataset.bulkSource)));
    body.querySelectorAll('.bulk-defense-select').forEach(select => select.addEventListener('change', () => {
      const pos = select.dataset.pos;
      const oldName = bulkDraft[pos] || '';
      const newName = select.value || '';
      if (oldName === newName) return;
      if (newName) {
        const otherPos = positions.find(other => other !== pos && other !== 'P' && bulkDraft[other] === newName);
        if (otherPos) bulkDraft[otherPos] = oldName;
      }
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
    } catch (err) {
      toast(err.message,'danger');
    }
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
      lastDefenseSignature = '';
      setTimeout(() => refreshDefense(true),250);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = originalText;
      toast(err.message,'danger');
    }
  }

  function polishLiveModals() {
    document.querySelectorAll('#live-defense-v2 .list-group-item').forEach(item => {
      if (item.querySelector('strong')?.textContent?.trim() === 'P') {
        item.setAttribute('disabled','disabled');
        item.classList.add('opacity-50');
        item.title = 'Use Change Pitcher to replace the pitcher.';
      }
    });
    document.querySelectorAll('#live-defense-destination-v2 [data-destination="P"]').forEach(btn => {
      btn.setAttribute('disabled','disabled');
      btn.classList.add('opacity-50');
      if (!btn.querySelector('.coach-use-pitcher-note')) btn.insertAdjacentHTML('beforeend','<div class="small coach-use-pitcher-note">Use Change Pitcher</div>');
    });
    document.querySelectorAll('#live-pitcher-picker-v2 .pitcher-choice-v2').forEach(btn => {
      if (/Pitch Count Incomplete|Eligibility unknown/i.test(btn.textContent || '')) {
        btn.setAttribute('disabled','disabled');
        btn.classList.add('opacity-50');
      }
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

  document.addEventListener('DOMContentLoaded', () => {
    addStyles();
    formatGameHeader();
    tick();
    setInterval(tick,900);
  });
})();
