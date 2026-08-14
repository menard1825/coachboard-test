(() => {
  'use strict';

  const gameMatch = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!gameMatch) return;

  const gameId = Number(gameMatch[1]);
  let wizardBusy = false;
  let wizardState = null;
  let wizardDraft = null;
  let wizardBefore = null;
  let wizardIncoming = null;
  let wizardOldPitcher = null;
  let wizardIncomingPosition = null;
  let wizardRequiredPositions = [];

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function positionsFor(state) {
    return Number(state?.outfielder_count) === 4
      ? ['P','C','1B','2B','3B','SS','LF','LCF','RCF','RF']
      : ['P','C','1B','2B','3B','SS','LF','CF','RF'];
  }

  async function fetchState() {
    const response = await fetch(`/api/live-game/${gameId}/state`, { cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || `Unable to load live game state (${response.status}).`);
    return data;
  }

  function toast(message, kind = 'success') {
    let container = $('pitcher-change-toast-v3');
    if (!container) {
      container = document.createElement('div');
      container.id = 'pitcher-change-toast-v3';
      container.className = 'toast-container position-fixed top-0 end-0 p-3';
      container.style.zIndex = '4000';
      document.body.appendChild(container);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    container.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el, { delay: 3000 });
    el.addEventListener('hidden.bs.toast', () => el.remove(), { once: true });
    instance.show();
  }

  function installStyles() {
    if ($('pitcher-change-complete-styles')) return;
    const style = document.createElement('style');
    style.id = 'pitcher-change-complete-styles';
    style.textContent = `
      #live-pitcher-finish-v3 .modal-content { border:0; border-radius:16px; overflow:hidden; }
      #live-pitcher-finish-v3 .modal-header { padding:16px 18px 12px; border-bottom:1px solid #eceff3; }
      #live-pitcher-finish-v3 .pitch-finish-summary { background:#f6f8fb; border:1px solid #e2e7ee; border-radius:12px; padding:12px; margin-bottom:14px; }
      #live-pitcher-finish-v3 .pitch-finish-summary strong { color:#172033; }
      #live-pitcher-finish-v3 .pitch-finish-row { display:grid; grid-template-columns:48px minmax(0,1fr); gap:10px; align-items:center; margin-bottom:9px; }
      #live-pitcher-finish-v3 .pitch-finish-pos { width:44px; height:34px; border-radius:8px; background:#eef1f5; color:#344054; display:flex; align-items:center; justify-content:center; font-size:.74rem; font-weight:800; }
      #live-pitcher-finish-v3 .pitch-finish-row.pitcher .pitch-finish-pos { background:#172033; color:#fff; }
      #live-pitcher-finish-v3 .pitch-finish-row .form-select,
      #live-pitcher-finish-v3 .pitch-finish-row .form-control { min-height:48px; border-radius:10px; font-weight:650; }
      #live-pitcher-finish-v3 .pitch-finish-bench { display:flex; flex-wrap:wrap; gap:6px; }
      #live-pitcher-finish-v3 .pitch-finish-bench span { border:1px solid #dfe3e8; background:#f8f9fb; border-radius:999px; padding:5px 9px; font-size:.74rem; color:#475467; }
      #live-pitcher-finish-v3 .pitch-finish-warning { color:#a32929; font-size:.8rem; font-weight:650; }
      #live-pitcher-finish-v3 .pitch-finish-footer { position:sticky; bottom:0; background:rgba(255,255,255,.98); border-top:1px solid #e7eaf0; padding:12px 16px; margin:14px -16px -16px; display:flex; gap:8px; align-items:center; }
      #live-pitcher-finish-v3 .pitch-finish-footer .btn { min-height:46px; border-radius:10px; font-weight:700; }
      @media (max-width:575.98px) {
        #live-pitcher-finish-v3 .modal-dialog { margin:.5rem; }
        #live-pitcher-finish-v3 .modal-header { padding:14px 14px 10px; }
        #live-pitcher-finish-v3 .modal-body { padding:14px; }
        #live-pitcher-finish-v3 .pitch-finish-footer { margin:14px -14px -14px; padding:11px 14px; }
      }
      @media (min-width:576px) {
        #live-pitcher-finish-v3 .modal-dialog { max-width:720px; width:calc(100% - 40px); margin:1.75rem auto; }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    let modal = $('live-pitcher-finish-v3');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'live-pitcher-finish-v3';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('data-bs-backdrop', 'static');
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <h5 class="modal-title mb-0">Finish Pitching Change</h5>
              <div class="small text-muted">Make sure every defensive position is covered before saving.</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body" id="pitch-finish-body-v3"></div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function assignedNames() {
    return new Set(Object.values(wizardDraft || {}).filter(Boolean));
  }

  function benchNames() {
    const assigned = assignedNames();
    return (wizardState?.roster || []).map(player => player.name).filter(name => !assigned.has(name));
  }

  function missingRequired() {
    return wizardRequiredPositions.filter(pos => !wizardDraft?.[pos]);
  }

  function renderWizard() {
    const body = $('pitch-finish-body-v3');
    if (!body || !wizardState || !wizardDraft || !wizardIncoming) return;

    const positions = positionsFor(wizardState);
    const roster = [...(wizardState.roster || [])].sort((a,b) => a.name.localeCompare(b.name));
    const missing = missingRequired();
    const bench = benchNames();

    let summary;
    if (wizardIncomingPosition && wizardOldPitcher) {
      summary = `<strong>${esc(wizardIncoming.name)}</strong> moves from <strong>${esc(wizardIncomingPosition)}</strong> to <strong>P</strong>. ` +
        `<strong>${esc(wizardOldPitcher)}</strong> is set to ${esc(wizardIncomingPosition)} so the defense stays complete. Change anything below if you want a different setup.`;
    } else if (wizardOldPitcher) {
      summary = `<strong>${esc(wizardIncoming.name)}</strong> comes in from the bench to pitch. <strong>${esc(wizardOldPitcher)}</strong> is currently headed to the bench. Assign him below if he is staying in the field.`;
    } else {
      summary = `<strong>${esc(wizardIncoming.name)}</strong> will pitch. Finish the defensive alignment below.`;
    }

    const rows = positions.map(pos => {
      if (pos === 'P') {
        return `<div class="pitch-finish-row pitcher"><div class="pitch-finish-pos">P</div><div class="form-control bg-light d-flex align-items-center justify-content-between"><strong>${esc(wizardIncoming.name)}</strong><span class="badge text-bg-dark">Locked</span></div></div>`;
      }
      const selected = wizardDraft[pos] || '';
      const options = ['<option value="">Open position</option>'].concat(
        roster.filter(player => player.name !== wizardIncoming.name).map(player =>
          `<option value="${esc(player.name)}" ${player.name === selected ? 'selected' : ''}>${esc(player.name)}</option>`
        )
      ).join('');
      return `<div class="pitch-finish-row"><div class="pitch-finish-pos">${esc(pos)}</div><select class="form-select pitch-finish-select-v3" data-pos="${esc(pos)}">${options}</select></div>`;
    }).join('');

    body.innerHTML = `
      <div class="pitch-finish-summary">${summary}</div>
      <div class="small text-uppercase text-muted fw-bold mb-2">Defense after the pitching change</div>
      ${rows}
      <div class="small text-uppercase text-muted fw-bold mt-3 mb-2">Bench after change</div>
      <div class="pitch-finish-bench">${bench.length ? bench.map(name => `<span>${esc(name)}</span>`).join('') : '<span>No players on bench</span>'}</div>
      <div class="pitch-finish-footer">
        <div class="me-auto">${missing.length ? `<div class="pitch-finish-warning">Fill ${esc(missing.join(', '))} before saving.</div>` : '<div class="small text-muted">One Undo will restore the entire previous defense.</div>'}</div>
        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
        <button type="button" class="btn btn-dark" id="save-pitch-finish-v3" ${missing.length ? 'disabled' : ''}>Save Pitching Change</button>
      </div>`;

    body.querySelectorAll('.pitch-finish-select-v3').forEach(select => {
      select.addEventListener('change', () => {
        const pos = select.dataset.pos;
        const oldName = wizardDraft[pos] || '';
        const newName = select.value || '';
        if (oldName === newName) return;

        if (newName) {
          const otherPos = positions.find(other => other !== pos && other !== 'P' && wizardDraft[other] === newName);
          if (otherPos) wizardDraft[otherPos] = oldName;
        }
        wizardDraft[pos] = newName;
        renderWizard();
      });
    });

    $('save-pitch-finish-v3')?.addEventListener('click', saveWizard);
  }

  async function saveWizard() {
    if (wizardBusy || !wizardIncoming || !wizardDraft) return;
    const missing = missingRequired();
    if (missing.length) {
      toast(`Fill ${missing.join(', ')} before saving.`, 'danger');
      return;
    }

    const button = $('save-pitch-finish-v3');
    wizardBusy = true;
    if (button) {
      button.disabled = true;
      button.textContent = 'Saving...';
    }

    try {
      const response = await fetch(`/api/live-game/${gameId}/complete-pitcher-change`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          new_pitcher_id: Number(wizardIncoming.id),
          alignment: wizardDraft,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || `Unable to save pitching change (${response.status}).`);

      bootstrap.Modal.getOrCreateInstance($('live-pitcher-finish-v3')).hide();
      const movedFrom = wizardIncomingPosition ? ` from ${wizardIncomingPosition}` : '';
      toast(`${wizardIncoming.name} → P${movedFrom} • Defense saved & synced`);
    } catch (err) {
      toast(err.message, 'danger');
      if (button) {
        button.disabled = false;
        button.textContent = 'Save Pitching Change';
      }
    } finally {
      wizardBusy = false;
    }
  }

  async function openWizard(newPitcherId) {
    try {
      wizardState = await fetchState();
      if (!wizardState?.game?.is_live) throw new Error('This game is not live.');

      wizardIncoming = (wizardState.roster || []).find(player => Number(player.id) === Number(newPitcherId));
      if (!wizardIncoming) throw new Error('Incoming pitcher is not available for this game.');

      const positions = positionsFor(wizardState);
      wizardBefore = { ...(wizardState.current_alignment || {}) };
      wizardOldPitcher = wizardBefore.P || '';
      wizardIncomingPosition = positions.find(pos => pos !== 'P' && wizardBefore[pos] === wizardIncoming.name) || null;
      wizardRequiredPositions = positions.filter(pos => Boolean(wizardBefore[pos]));

      wizardDraft = {};
      positions.forEach(pos => {
        if (wizardBefore[pos]) wizardDraft[pos] = wizardBefore[pos];
      });

      if (wizardIncomingPosition) delete wizardDraft[wizardIncomingPosition];
      wizardDraft.P = wizardIncoming.name;

      // Baseball-friendly default: if the incoming pitcher came from the field,
      // move the outgoing pitcher into the vacated position. The coach can then
      // alter any position before saving.
      if (wizardIncomingPosition && wizardOldPitcher) {
        wizardDraft[wizardIncomingPosition] = wizardOldPitcher;
      }

      ensureModal();
      renderWizard();
      bootstrap.Modal.getOrCreateInstance($('live-pitcher-finish-v3')).show();
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  function interceptPitcherChoice(event) {
    const choice = event.target.closest?.('.pitcher-choice-v2');
    if (!choice || choice.disabled) return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    const newPitcherId = Number(choice.dataset.playerId);
    if (!Number.isFinite(newPitcherId)) return;

    const picker = $('live-pitcher-picker-v2');
    if (picker?.classList.contains('show')) {
      const instance = bootstrap.Modal.getOrCreateInstance(picker);
      picker.addEventListener('hidden.bs.modal', () => openWizard(newPitcherId), { once: true });
      instance.hide();
    } else {
      openWizard(newPitcherId);
    }
  }

  document.addEventListener('DOMContentLoaded', installStyles);
  document.addEventListener('click', interceptPitcherChoice, true);
})();
