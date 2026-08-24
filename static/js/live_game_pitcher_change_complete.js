(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const MODAL_ID = 'live-pitcher-finish-v3';
  let state = null;
  let incoming = null;
  let before = null;
  let oldPitcher = '';
  let incomingPosition = null;
  let busy = false;

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if ($('pitcher-change-simple-styles')) return;
    const style = document.createElement('style');
    style.id = 'pitcher-change-simple-styles';
    style.textContent = `
      #${MODAL_ID} .modal-content{border:0;border-radius:15px;overflow:hidden}
      #${MODAL_ID} .pc-summary{border:1px solid #dfe4ea;background:#f8fafc;border-radius:10px;padding:10px 11px;margin-bottom:12px;color:#344054;font-size:.8rem}
      #${MODAL_ID} .pc-actions{display:grid;gap:9px}
      #${MODAL_ID} .pc-action{min-height:58px;border-radius:11px;font-weight:850;text-align:left;padding:9px 11px}
      #${MODAL_ID} .pc-action small{display:block;margin-top:2px;font-size:.67rem;font-weight:550;opacity:.78}
      #${MODAL_ID} .pc-replacements{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}
      #${MODAL_ID} .pc-replacements .btn{min-height:48px;border-radius:9px;font-weight:750}
      #${MODAL_ID} .pc-label{font-size:.65rem;text-transform:uppercase;letter-spacing:.08em;font-weight:850;color:#667085;margin:12px 0 6px}
      @media(max-width:575.98px){#${MODAL_ID} .modal-dialog{margin:.5rem}}
    `;
    document.head.appendChild(style);
  }

  function toast(message, kind='success') {
    let host = $('pitcher-change-toast-v3');
    if (!host) {
      host = document.createElement('div');
      host.id = 'pitcher-change-toast-v3';
      host.className = 'toast-container position-fixed top-0 end-0 p-3';
      host.style.zIndex = '5000';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    host.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el,{delay:2400});
    el.addEventListener('hidden.bs.toast',()=>el.remove(),{once:true});
    instance.show();
  }

  async function loadState() {
    const response = await fetch(`/api/live-game/${gameId}/state`,{cache:'no-store'});
    const data = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(data.message || `Unable to load game (${response.status}).`);
    return data;
  }

  function ensureModal() {
    let modal = $(MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Pitching Change</h5><div class="small text-muted">Who’s coming in, and where does the old pitcher go?</div></div><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body" data-pc-body></div></div></div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function benchPlayers() {
    const assigned = new Set(Object.values(before || {}).filter(Boolean));
    return (state?.roster || []).filter(player => !assigned.has(player.name) && player.name !== incoming?.name);
  }

  function baseDraft() {
    const draft = {...(before || {})};
    if (incomingPosition) delete draft[incomingPosition];
    draft.P = incoming.name;
    return draft;
  }

  function render() {
    const modal = ensureModal();
    const body = modal.querySelector('[data-pc-body]');
    if (!body || !incoming) return;

    const oldName = oldPitcher || 'Current pitcher';
    let actions = '';

    if (incomingPosition && oldPitcher) {
      actions = `
        <div class="pc-actions">
          <button type="button" class="btn btn-primary pc-action" data-pc-swap>
            ${esc(oldPitcher)} → ${esc(incomingPosition)}
            <small>Straight swap. Everyone else stays put.</small>
          </button>
          <button type="button" class="btn btn-outline-secondary pc-action" data-pc-bench-old>
            ${esc(oldPitcher)} → Bench
            <small>Choose who fills ${esc(incomingPosition)}.</small>
          </button>
        </div>
        <div data-pc-replacement-wrap class="d-none">
          <div class="pc-label">Who takes ${esc(incomingPosition)}?</div>
          <div class="pc-replacements">${benchPlayers().map(player => `<button type="button" class="btn btn-outline-primary" data-pc-replacement="${esc(player.name)}">${esc(player.name)}</button>`).join('') || '<div class="small text-muted">No bench player is available.</div>'}</div>
        </div>`;
    } else {
      actions = `
        <div class="pc-actions">
          <button type="button" class="btn btn-primary pc-action" data-pc-bench-old>
            ${oldPitcher ? `${esc(oldPitcher)} → Bench` : 'Make Pitching Change'}
            <small>Everyone else stays put.</small>
          </button>
        </div>`;
    }

    body.innerHTML = `<div class="pc-summary"><strong>${esc(incoming.name)}</strong> → P<br><span class="text-muted">Where does ${esc(oldName)} go?</span></div>${actions}`;

    body.querySelector('[data-pc-swap]')?.addEventListener('click', () => {
      const draft = baseDraft();
      draft[incomingPosition] = oldPitcher;
      save(draft, `${incoming.name} in at P · ${oldPitcher} to ${incomingPosition}`);
    });

    body.querySelector('[data-pc-bench-old]')?.addEventListener('click', () => {
      if (incomingPosition && oldPitcher) {
        body.querySelector('[data-pc-replacement-wrap]')?.classList.remove('d-none');
        return;
      }
      save(baseDraft(), `${incoming.name} in at P`);
    });

    body.querySelectorAll('[data-pc-replacement]').forEach(button => {
      button.addEventListener('click', () => {
        const draft = baseDraft();
        draft[incomingPosition] = button.dataset.pcReplacement;
        save(draft, `${incoming.name} in at P · ${button.dataset.pcReplacement} to ${incomingPosition}`);
      });
    });
  }

  async function save(alignment, successMessage) {
    if (busy) return;
    busy = true;
    const modal = ensureModal();
    modal.querySelectorAll('button').forEach(button => { if (!button.classList.contains('btn-close')) button.disabled = true; });
    try {
      const response = await fetch(`/api/live-game/${gameId}/complete-pitcher-change`,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({new_pitcher_id:Number(incoming.id), alignment})
      });
      const data = await response.json().catch(()=>({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || `Unable to change pitcher (${response.status}).`);
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      toast(successMessage);
    } catch (err) {
      toast(err.message,'danger');
      modal.querySelectorAll('button').forEach(button => { button.disabled = false; });
    } finally {
      busy = false;
    }
  }

  async function open(playerId) {
    try {
      state = await loadState();
      if (!state?.game?.is_live) throw new Error('Game is not live.');
      incoming = (state.roster || []).find(player => Number(player.id) === Number(playerId));
      if (!incoming) throw new Error('Pitcher is not available.');
      before = {...(state.current_alignment || {})};
      oldPitcher = before.P || '';
      incomingPosition = Object.entries(before).find(([pos,name]) => pos !== 'P' && name === incoming.name)?.[0] || null;
      render();
      bootstrap.Modal.getOrCreateInstance(ensureModal()).show();
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
      const instance = bootstrap.Modal.getOrCreateInstance(picker);
      picker.addEventListener('hidden.bs.modal',()=>open(playerId),{once:true});
      instance.hide();
    } else {
      open(playerId);
    }
  }

  installStyles();
  document.addEventListener('click',intercept,true);
})();