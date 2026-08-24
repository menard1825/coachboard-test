(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const STYLE_ID = 'cb-bench-report-style';
  const MODAL_ID = 'cbBenchReportModal';
  let cardObserver = null;
  let rootObserver = null;
  let loadBusy = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #cbQuickDefense .cb-bench-report-btn {
        width:100%;
        min-height:40px;
        margin-top:8px;
        border-radius:9px;
        font-size:.72rem;
        font-weight:800;
        touch-action:manipulation;
      }
      #${MODAL_ID} .modal-content {
        border:0;
        border-radius:15px;
        overflow:hidden;
      }
      #${MODAL_ID} .cb-br-summary {
        display:flex;
        flex-wrap:wrap;
        gap:7px;
        margin-bottom:10px;
      }
      #${MODAL_ID} .cb-br-chip {
        border:1px solid #dfe4ea;
        border-radius:999px;
        background:#f8fafc;
        color:#344054;
        padding:5px 8px;
        font-size:.7rem;
        font-weight:750;
      }
      #${MODAL_ID} .cb-br-help {
        color:#667085;
        font-size:.74rem;
        line-height:1.4;
        margin-bottom:11px;
      }
      #${MODAL_ID} .cb-br-list {
        display:grid;
        gap:7px;
      }
      #${MODAL_ID} .cb-br-row {
        display:grid;
        grid-template-columns:minmax(0,1fr) auto;
        gap:4px 10px;
        align-items:center;
        border:1px solid #e1e5ea;
        border-radius:11px;
        background:#fff;
        padding:9px 10px;
      }
      #${MODAL_ID} .cb-br-row.current {
        border-color:#dfc477;
        background:#fffaf0;
      }
      #${MODAL_ID} .cb-br-player {
        min-width:0;
        color:#172033;
        font-size:.82rem;
        font-weight:820;
        overflow-wrap:anywhere;
      }
      #${MODAL_ID} .cb-br-count {
        border-radius:999px;
        background:#eef2f6;
        color:#344054;
        padding:4px 7px;
        font-size:.65rem;
        font-weight:800;
        white-space:nowrap;
      }
      #${MODAL_ID} .cb-br-row.current .cb-br-count {
        background:#fff0c7;
        color:#7a5200;
      }
      #${MODAL_ID} .cb-br-history {
        grid-column:1 / -1;
        color:#667085;
        font-size:.72rem;
        line-height:1.35;
      }
      #${MODAL_ID} .cb-br-now {
        color:#8b5c00;
        font-weight:800;
      }
      #${MODAL_ID} .cb-br-empty {
        border:1px dashed #d0d5dd;
        border-radius:11px;
        color:#667085;
        padding:16px;
        text-align:center;
        font-size:.78rem;
      }
      #${MODAL_ID} .cb-br-loading {
        min-height:150px;
        display:flex;
        align-items:center;
        justify-content:center;
        color:#667085;
        font-size:.8rem;
      }
      @media (max-width:575.98px) {
        #${MODAL_ID} .modal-dialog {
          margin:.5rem;
        }
        #${MODAL_ID} .modal-body {
          padding:12px;
        }
        #${MODAL_ID} .cb-br-row {
          padding:9px;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    let modal = document.getElementById(MODAL_ID);
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <h5 class="modal-title mb-0">Bench Report</h5>
              <div class="small text-muted">Who sat, and in which innings</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body" data-cb-bench-report-body>
            <div class="cb-br-loading">Loading bench history…</div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-outline-secondary" data-cb-bench-refresh>
              <i class="bi bi-arrow-clockwise me-1"></i>Refresh
            </button>
            <button type="button" class="btn btn-primary" data-bs-dismiss="modal">Back to Live Game</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('[data-cb-bench-refresh]')?.addEventListener('click', loadReport);
    return modal;
  }

  function inningValue(value) {
    const number = Number.parseFloat(value);
    return Number.isFinite(number) ? number : null;
  }

  function inningLabel(value) {
    const number = inningValue(value);
    if (number === null) return String(value || '—');
    return Number.isInteger(number) ? String(number) : String(number).replace(/\.0+$/, '');
  }

  function rosterName(player) {
    const name = String(player?.name || '').trim();
    const number = String(player?.number ?? '').trim();
    return number ? `#${number} ${name}` : name;
  }

  function buildReport(state) {
    const roster = Array.isArray(state?.roster) ? state.roster.filter(player => player?.name) : [];
    const currentValue = inningValue(state?.current_inning);
    const currentLabel = inningLabel(state?.current_inning || '1');
    const actual = state?.actual_rotation && typeof state.actual_rotation === 'object' ? state.actual_rotation : {};

    const completed = Object.entries(actual)
      .map(([inning, alignment]) => ({
        inning,
        value: inningValue(inning),
        alignment: alignment && typeof alignment === 'object' ? alignment : {},
      }))
      .filter(item => item.value !== null && (currentValue === null || item.value < currentValue))
      .sort((a, b) => a.value - b.value);

    const currentAssigned = new Set(Object.values(state?.current_alignment || {}).filter(Boolean));
    const history = roster.map(player => {
      const name = String(player.name).trim();
      const sat = [];
      completed.forEach(item => {
        const assigned = new Set(Object.values(item.alignment || {}).filter(Boolean));
        if (!assigned.has(name)) sat.push(inningLabel(item.inning));
      });
      const currentBench = !currentAssigned.has(name);
      return {
        player,
        name,
        display: rosterName(player),
        sat,
        currentBench,
        total: sat.length + (currentBench ? 1 : 0),
      };
    }).sort((a, b) => {
      if (a.currentBench !== b.currentBench) return a.currentBench ? -1 : 1;
      if (a.total !== b.total) return b.total - a.total;
      return a.name.localeCompare(b.name);
    });

    return { history, currentLabel, completedCount: completed.length };
  }

  function renderReport(state) {
    const modal = ensureModal();
    const body = modal.querySelector('[data-cb-bench-report-body]');
    if (!body) return;

    const report = buildReport(state);
    const benchNow = report.history.filter(row => row.currentBench).length;
    const rowsWithBench = report.history.filter(row => row.total > 0).length;

    const rows = report.history.length ? report.history.map(row => {
      const completedText = row.sat.length ? row.sat.join(', ') : 'None yet';
      const current = row.currentBench
        ? `<span class="cb-br-now"> · Inning ${esc(report.currentLabel)} now</span>`
        : '';
      const countLabel = `${row.total} ${row.total === 1 ? 'inning' : 'innings'}`;
      return `
        <div class="cb-br-row ${row.currentBench ? 'current' : ''}">
          <div class="cb-br-player">${esc(row.display)}</div>
          <div class="cb-br-count">${esc(countLabel)}</div>
          <div class="cb-br-history"><strong>Sat:</strong> ${esc(completedText)}${current}</div>
        </div>`;
    }).join('') : '<div class="cb-br-empty">No roster or live defensive history is available yet.</div>';

    body.innerHTML = `
      <div class="cb-br-summary">
        <span class="cb-br-chip">Inning ${esc(report.currentLabel)}</span>
        <span class="cb-br-chip">Bench now: ${benchNow}</span>
        <span class="cb-br-chip">Players who have sat: ${rowsWithBench}</span>
      </div>
      <div class="cb-br-help">
        This uses the <strong>actual live defense</strong>, not the planned rotation. Completed innings are listed under “Sat”; anyone currently on the bench is marked “now.”
      </div>
      <div class="cb-br-list">${rows}</div>`;
  }

  async function loadReport() {
    if (loadBusy) return;
    const modal = ensureModal();
    const body = modal.querySelector('[data-cb-bench-report-body]');
    const refresh = modal.querySelector('[data-cb-bench-refresh]');
    loadBusy = true;
    if (refresh) refresh.disabled = true;
    if (body) body.innerHTML = '<div class="cb-br-loading"><span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Loading bench history…</div>';

    try {
      const response = await fetch(`/api/live-game/${gameId}/state`, { cache: 'no-store' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.message || `Unable to load bench report (${response.status}).`);
      renderReport(data);
    } catch (error) {
      if (body) body.innerHTML = `<div class="alert alert-danger mb-0"><strong>Bench report could not be loaded.</strong><br>${esc(error.message)}</div>`;
    } finally {
      loadBusy = false;
      if (refresh) refresh.disabled = false;
    }
  }

  function openReport() {
    const modal = ensureModal();
    bootstrap.Modal.getOrCreateInstance(modal).show();
    loadReport();
  }

  function ensureButton() {
    const benchWrap = document.querySelector('#cbQuickDefense .cb-qd-bench-wrap');
    if (!benchWrap || benchWrap.querySelector('[data-cb-bench-report]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-outline-secondary cb-bench-report-btn';
    button.dataset.cbBenchReport = 'true';
    button.innerHTML = '<i class="bi bi-clipboard-data me-1"></i>Bench Report · Who sat when';
    button.addEventListener('click', openReport);
    benchWrap.appendChild(button);
  }

  function attachToQuickDefense() {
    const card = document.getElementById('cbQuickDefense');
    if (!card) return false;

    ensureButton();
    if (!cardObserver) {
      cardObserver = new MutationObserver(() => requestAnimationFrame(ensureButton));
      cardObserver.observe(card, { childList: true, subtree: true });
    }
    return true;
  }

  function start() {
    installStyles();
    if (attachToQuickDefense()) return;

    rootObserver = new MutationObserver(() => {
      if (!attachToQuickDefense()) return;
      rootObserver?.disconnect();
      rootObserver = null;
    });
    rootObserver.observe(document.body, { childList: true, subtree: true });
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, { once: true })
    : start();
})();
