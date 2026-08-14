(() => {
  'use strict';
  if (window.location.pathname !== '/') return;

  const PRESET_PREFIX = 'DEFENSE PRESET — ';
  let practiceModal = null;
  let practiceBusy = false;
  let mutationTimer = null;

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
      #rotations .defense-preset-home{border:1px solid #dce5dc;border-radius:13px;background:#f8fbf8;margin-bottom:14px;overflow:hidden}#rotations .dph-head{padding:11px 13px;border-bottom:1px solid #e3e9e3;display:flex;justify-content:space-between;gap:10px;align-items:center}#rotations .dph-head strong{font-size:.82rem;color:#172033}#rotations .dph-head span{font-size:.65rem;color:#667085}#rotations .dph-list{display:flex;flex-wrap:wrap;gap:7px;padding:11px 13px}#rotations .dph-chip{border:1px solid #d6ded6;background:#fff;border-radius:999px;padding:6px 9px;font-size:.7rem;font-weight:750;color:#344054}
      .practice-reuse-btn{white-space:nowrap}.reuse-practice-note{font-size:.68rem;color:#667085;margin-top:6px}
      #reusePracticeModal .modal-content{border:0;border-radius:16px;overflow:hidden}#reusePracticeModal .form-control{min-height:46px}
      @media(max-width:575.98px){#player_development .season-dev-summary{align-items:flex-start}.practice-plan-details-form .reuse-practice-btn{width:100%;order:-1}#rotations .dph-list{padding:9px 10px}}
    `;
    document.head.appendChild(style);
  }

  async function loadRotations() {
    try {
      const response = await fetch('/api/rotations', {cache:'no-store'});
      if (!response.ok) return [];
      return await response.json();
    } catch (_) {
      return [];
    }
  }

  async function separateDefensePresets() {
    const tab = document.getElementById('rotations');
    const accordion = document.getElementById('rotationsAccordion');
    if (!tab || !accordion) return;

    const rotations = await loadRotations();
    const presets = rotations.filter(item => String(item.title || '').startsWith(PRESET_PREFIX));
    const normalIds = new Set(rotations.filter(item => !String(item.title || '').startsWith(PRESET_PREFIX)).map(item => String(item.id)));

    // main.js still owns the editable whole-game template list. Remove defense
    // preset rows from that list so the two concepts are not mixed together.
    accordion.querySelectorAll('[data-rotation-id]').forEach(item => {
      if (!normalIds.has(String(item.dataset.rotationId))) item.remove();
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
      <div class="dph-head"><div><strong>Defense Presets</strong><span class="d-block">Single-inning defenses saved from Game Management</span></div><span>${presets.length} saved</span></div>
      <div class="dph-list">${presets.length ? presets.map(item => `<span class="dph-chip">${esc(String(item.title).slice(PRESET_PREFIX.length).trim())}</span>`).join('') : '<span class="text-muted small">No defense presets saved yet.</span>'}</div>`;

    const header = accordion.closest('.card')?.querySelector('.card-header h5');
    if (header) header.textContent = 'Full-Game Rotation Templates';
  }

  function ensurePracticeModal() {
    let modal = document.getElementById('reusePracticeModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'reusePracticeModal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered"><div class="modal-content">
        <div class="modal-header"><div><h5 class="modal-title mb-0">Reuse Practice Plan</h5><div class="small text-muted">Copy the drills and emphasis to a fresh practice date.</div></div><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
        <div class="modal-body">
          <input type="hidden" id="reuse-practice-plan-id">
          <label class="form-label fw-semibold" for="reuse-practice-date">New practice date</label>
          <input type="date" class="form-control" id="reuse-practice-date" required>
          <div class="form-check form-switch mt-3"><input class="form-check-input" type="checkbox" id="reuse-practice-tasks" checked><label class="form-check-label" for="reuse-practice-tasks">Copy task list</label></div>
          <div class="reuse-practice-note">Copied tasks restart as pending. Attendance is never copied.</div>
        </div>
        <div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button><button type="button" class="btn btn-primary" id="reuse-practice-confirm">Create New Practice</button></div>
      </div></div>`;
    document.body.appendChild(modal);
    document.getElementById('reuse-practice-confirm').addEventListener('click', clonePractice);
    return modal;
  }

  function nextDateFrom(sourceDate) {
    const base = sourceDate ? new Date(`${sourceDate}T12:00:00`) : new Date();
    if (Number.isNaN(base.getTime())) return '';
    base.setDate(base.getDate() + 7);
    const y = base.getFullYear();
    const m = String(base.getMonth() + 1).padStart(2, '0');
    const d = String(base.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  function openReuse(planId, sourceDate) {
    const modal = ensurePracticeModal();
    document.getElementById('reuse-practice-plan-id').value = planId;
    document.getElementById('reuse-practice-date').value = nextDateFrom(sourceDate);
    document.getElementById('reuse-practice-tasks').checked = true;
    practiceModal = bootstrap.Modal.getOrCreateInstance(modal);
    practiceModal.show();
  }

  async function clonePractice() {
    if (practiceBusy) return;
    const planId = document.getElementById('reuse-practice-plan-id').value;
    const planDate = document.getElementById('reuse-practice-date').value;
    const copyTasks = document.getElementById('reuse-practice-tasks').checked;
    if (!planId || !planDate) return;

    practiceBusy = true;
    const button = document.getElementById('reuse-practice-confirm');
    button.disabled = true;
    button.textContent = 'Creating…';
    try {
      const response = await fetch(`/clone_practice_plan/${planId}`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({plan_date:planDate, copy_tasks:copyTasks}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to reuse practice plan.');
      practiceModal?.hide();
      window.location.assign(`/#plan-${data.new_plan_id}`);
      window.location.reload();
    } catch (error) {
      alert(error.message || 'Unable to reuse practice plan.');
    } finally {
      practiceBusy = false;
      button.disabled = false;
      button.textContent = 'Create New Practice';
    }
  }

  function enhancePracticePlans() {
    const accordion = document.getElementById('practicePlanAccordion');
    if (!accordion) return;
    accordion.querySelectorAll('.accordion-collapse[id^="plan-"]').forEach(collapse => {
      const planId = collapse.id.replace('plan-', '');
      const form = collapse.querySelector('.practice-plan-details-form');
      if (!form || form.querySelector('.practice-reuse-btn')) return;
      const actionRow = [...form.querySelectorAll('.d-flex.justify-content-end')].pop();
      if (!actionRow) return;
      const dateValue = form.querySelector('input[name="plan_date"]')?.value || '';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-sm btn-outline-primary practice-reuse-btn';
      button.textContent = 'Reuse Plan';
      button.addEventListener('click', () => openReuse(planId, dateValue));
      actionRow.prepend(button);
    });
  }

  async function enhanceDevelopment() {
    const pane = document.getElementById('player_development');
    const list = document.getElementById('dev-player-list');
    if (!pane || !list) return;
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
      enhancePracticePlans();
      separateDefensePresets();
      enhanceDevelopment();
    }, 100);
  }

  function init() {
    installStyles();
    ensurePracticeModal();
    scheduleEnhance();
    const targets = [document.getElementById('practicePlanAccordion'), document.getElementById('rotationsAccordion'), document.getElementById('dev-player-list')].filter(Boolean);
    targets.forEach(target => new MutationObserver(scheduleEnhance).observe(target, {childList:true, subtree:true}));
    document.addEventListener('shown.bs.tab', scheduleEnhance);
  }

  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', init, {once:true}) : init();
})();
