(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  let state = null;
  let before = null;
  let draft = null;
  let incoming = null;
  let oldPitcher = '';
  let incomingPosition = null;
  let requiredPositions = [];
  let busy = false;

  function positions() {
    return Number(state?.outfielder_count) === 4
      ? ['P','C','1B','2B','3B','SS','LF','LCF','RCF','RF']
      : ['P','C','1B','2B','3B','SS','LF','CF','RF'];
  }

  function installStyles() {
    if ($('pitcher-change-complete-styles')) return;
    const style = document.createElement('style');
    style.id = 'pitcher-change-complete-styles';
    style.textContent = `
      #live-pitcher-finish-v3 .modal-content{border:0;border-radius:16px;overflow:hidden}
      #live-pitcher-finish-v3 .modal-header{padding:16px 18px 12px;border-bottom:1px solid #eceff3}
      #live-pitcher-finish-v3 .pitch-summary{background:#f6f8fb;border:1px solid #e2e7ee;border-radius:12px;padding:12px;margin-bottom:14px}
      #live-pitcher-finish-v3 .pitch-row{display:grid;grid-template-columns:48px minmax(0,1fr);gap:10px;align-items:center;margin-bottom:9px}
      #live-pitcher-finish-v3 .pitch-pos{width:44px;height:34px;border-radius:8px;background:#eef1f5;color:#344054;display:flex;align-items:center;justify-content:center;font-size:.74rem;font-weight:800}
      #live-pitcher-finish-v3 .pitch-row.pitcher .pitch-pos{background:#172033;color:#fff}
      #live-pitcher-finish-v3 .pitch-row .form-select,#live-pitcher-finish-v3 .pitch-row .form-control{min-height:48px;border-radius:10px;font-weight:650}
      #live-pitcher-finish-v3 .pitch-bench{display:flex;flex-wrap:wrap;gap:6px}
      #live-pitcher-finish-v3 .pitch-bench span{border:1px solid #dfe3e8;background:#f8f9fb;border-radius:999px;padding:5px 9px;font-size:.74rem;color:#475467}
      #live-pitcher-finish-v3 .pitch-warning{color:#a32929;font-size:.8rem;font-weight:650}
      #live-pitcher-finish-v3 .pitch-footer{position:sticky;bottom:0;background:rgba(255,255,255,.98);border-top:1px solid #e7eaf0;padding:12px 16px;margin:14px -16px -16px;display:flex;gap:8px;align-items:center}
      #live-pitcher-finish-v3 .pitch-footer .btn{min-height:46px;border-radius:10px;font-weight:700}
      @media(max-width:575.98px){#live-pitcher-finish-v3 .modal-dialog{margin:.5rem}#live-pitcher-finish-v3 .modal-header{padding:14px 14px 10px}#live-pitcher-finish-v3 .modal-body{padding:14px}#live-pitcher-finish-v3 .pitch-footer{margin:14px -14px -14px;padding:11px 14px}}
      @media(min-width:576px){#live-pitcher-finish-v3 .modal-dialog{max-width:720px;width:calc(100% - 40px);margin:1.75rem auto}}
    `;
    document.head.appendChild(style);
  }

  function toast(message, kind='success') {
    let host = $('pitcher-change-toast-v3');
    if (!host) {
      host = document.createElement('div');
      host.id = 'pitcher-change-toast-v3';
      host.className = 'toast-container position-fixed top-0 end-0 p-3';
      host.style.zIndex = '4000';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    host.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el,{delay:3000});
    el.addEventListener('hidden.bs.toast',()=>el.remove(),{once:true});
    instance.show();
  }

  async function loadState() {
    const response = await fetch(`/api/live-game/${gameId}/state`,{cache:'no-store'});
    const data = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(data.message || `Unable to load live game state (${response.status}).`);
    return data;
  }

  function ensureModal() {
    let modal = $('live-pitcher-finish-v3');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'live-pitcher-finish-v3';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('data-bs-backdrop','static');
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Finish Pitching Change</h5><div class="small text-muted">Confirm the whole defense before saving.</div></div><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body" id="pitch-finish-body-v3"></div></div></div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function missing() {
    return requiredPositions.filter(pos => !draft?.[pos]);
  }

  function bench() {
    const assigned = new Set(Object.values(draft || {}).filter(Boolean));
    return (state?.roster || []).map(p=>p.name).filter(name=>!assigned.has(name));
  }

  function render() {
    const body = $('pitch-finish-body-v3');
    if (!body || !state || !draft || !incoming) return;

    const fieldPositions = positions();
    const roster = [...(state.roster || [])].sort((a,b)=>a.name.localeCompare(b.name));
    const holes = missing();
    const benchNames = bench();

    let summary = `<strong>${esc(incoming.name)}</strong> will pitch.`;
    if (incomingPosition && oldPitcher) {
      summary = `<strong>${esc(incoming.name)}</strong> moves from <strong>${esc(incomingPosition)}</strong> to <strong>P</strong>. <strong>${esc(oldPitcher)}</strong> is automatically placed at ${esc(incomingPosition)} so you do not leave a hole. Adjust anything below if needed.`;
    } else if (oldPitcher) {
      summary = `<strong>${esc(incoming.name)}</strong> comes in from the bench to pitch. <strong>${esc(oldPitcher)}</strong> is headed to the bench unless you assign him to another position below.`;
    }

    const rows = fieldPositions.map(pos => {
      if (pos === 'P') {
        return `<div class="pitch-row pitcher"><div class="pitch-pos">P</div><div class="form-control bg-light d-flex justify-content-between align-items-center"><strong>${esc(incoming.name)}</strong><span class="badge text-bg-dark">Locked</span></div></div>`;
      }
      const selected = draft[pos] || '';
      const options = ['<option value="">Open position</option>'].concat(
        roster.filter(p=>p.name!==incoming.name).map(p=>`<option value="${esc(p.name)}" ${p.name===selected?'selected':''}>${esc(p.name)}</option>`)
      ).join('');
      return `<div class="pitch-row"><div class="pitch-pos">${esc(pos)}</div><select class="form-select pitch-select-v3" data-pos="${esc(pos)}">${options}</select></div>`;
    }).join('');

    body.innerHTML = `<div class="pitch-summary">${summary}</div><div class="small text-uppercase text-muted fw-bold mb-2">Defense after change</div>${rows}<div class="small text-uppercase text-muted fw-bold mt-3 mb-2">Bench after change</div><div class="pitch-bench">${benchNames.length?benchNames.map(name=>`<span>${esc(name)}</span>`).join(''):'<span>No players on bench</span>'}</div><div class="pitch-footer"><div class="me-auto">${holes.length?`<div class="pitch-warning">Fill ${esc(holes.join(', '))} before saving.</div>`:'<div class="small text-muted">One Undo restores the entire previous defense.</div>'}</div><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button><button type="button" class="btn btn-dark" id="save-pitch-finish-v3" ${holes.length?'disabled':''}>Save Pitching Change</button></div>`;

    body.querySelectorAll('.pitch-select-v3').forEach(select=>{
      select.addEventListener('change',()=>{
        const pos = select.dataset.pos;
        const oldName = draft[pos] || '';
        const newName = select.value || '';
        if (oldName === newName) return;

        if (newName) {
          const other = fieldPositions.find(otherPos=>otherPos!==pos && otherPos!=='P' && draft[otherPos]===newName);
          if (other) draft[other] = oldName;
        }
        draft[pos] = newName;
        render();
      });
    });

    $('save-pitch-finish-v3')?.addEventListener('click',save);
  }

  async function save() {
    if (busy || !incoming || !draft) return;
    const holes = missing();
    if (holes.length) return toast(`Fill ${holes.join(', ')} before saving.`,'danger');

    busy = true;
    const button = $('save-pitch-finish-v3');
    if (button) { button.disabled = true; button.textContent = 'Saving...'; }

    try {
      const response = await fetch(`/api/live-game/${gameId}/complete-pitcher-change`,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({new_pitcher_id:Number(incoming.id),alignment:draft})
      });
      const data = await response.json().catch(()=>({}));
      if (!response.ok || data.status==='error') throw new Error(data.message || `Unable to save pitching change (${response.status}).`);
      bootstrap.Modal.getOrCreateInstance($('live-pitcher-finish-v3')).hide();
      toast(`${incoming.name} → P • Full defense saved & synced`);
    } catch (err) {
      toast(err.message,'danger');
      if (button) { button.disabled = false; button.textContent = 'Save Pitching Change'; }
    } finally {
      busy = false;
    }
  }

  async function openWizard(playerId) {
    try {
      state = await loadState();
      if (!state?.game?.is_live) throw new Error('This game is not live.');
      incoming = (state.roster || []).find(p=>Number(p.id)===Number(playerId));
      if (!incoming) throw new Error('Incoming pitcher is not available for this game.');

      const fieldPositions = positions();
      before = {...(state.current_alignment || {})};
      oldPitcher = before.P || '';
      incomingPosition = fieldPositions.find(pos=>pos!=='P' && before[pos]===incoming.name) || null;
      requiredPositions = fieldPositions.filter(pos=>Boolean(before[pos]));

      draft = {};
      fieldPositions.forEach(pos=>{ if (before[pos]) draft[pos] = before[pos]; });
      if (incomingPosition) delete draft[incomingPosition];
      draft.P = incoming.name;
      if (incomingPosition && oldPitcher) draft[incomingPosition] = oldPitcher;

      ensureModal();
      render();
      bootstrap.Modal.getOrCreateInstance($('live-pitcher-finish-v3')).show();
    } catch (err) {
      toast(err.message,'danger');
    }
  }

  function intercept(event) {
    const choice = event.target.closest?.('.pitcher-choice-v2');
    if (!choice || choice.disabled) return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    const playerId = Number(choice.dataset.playerId);
    if (!Number.isFinite(playerId)) return;

    const picker = $('live-pitcher-picker-v2');
    if (picker?.classList.contains('show')) {
      const modal = bootstrap.Modal.getOrCreateInstance(picker);
      picker.addEventListener('hidden.bs.modal',()=>openWizard(playerId),{once:true});
      modal.hide();
    } else {
      openWizard(playerId);
    }
  }

  installStyles();
  document.addEventListener('click',intercept,true);
})();
