(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const MODAL_ID = 'cbBenchReportModal';
  let cardObserver = null;
  let rootObserver = null;
  let loadBusy = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if (document.getElementById('cb-bench-report-style')) return;
    const style = document.createElement('style');
    style.id = 'cb-bench-report-style';
    style.textContent = `
      #cbQuickDefense .cb-bench-report-btn{width:100%;min-height:40px;margin-top:8px;border-radius:9px;font-size:.72rem;font-weight:800;touch-action:manipulation}
      #${MODAL_ID} .modal-content{border:0;border-radius:15px;overflow:hidden}
      #${MODAL_ID} .cb-br-summary{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:10px}
      #${MODAL_ID} .cb-br-chip{border:1px solid #dfe4ea;border-radius:999px;background:#f8fafc;color:#344054;padding:5px 8px;font-size:.7rem;font-weight:750}
      #${MODAL_ID} .cb-br-list{display:grid;gap:7px}
      #${MODAL_ID} .cb-br-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 10px;align-items:center;border:1px solid #e1e5ea;border-radius:11px;background:#fff;padding:9px 10px}
      #${MODAL_ID} .cb-br-row.current{border-color:#dfc477;background:#fffaf0}
      #${MODAL_ID} .cb-br-player{min-width:0;color:#172033;font-size:.82rem;font-weight:820;overflow-wrap:anywhere}
      #${MODAL_ID} .cb-br-count{border-radius:999px;background:#eef2f6;color:#344054;padding:4px 7px;font-size:.65rem;font-weight:800;white-space:nowrap}
      #${MODAL_ID} .cb-br-row.current .cb-br-count{background:#fff0c7;color:#7a5200}
      #${MODAL_ID} .cb-br-history{grid-column:1/-1;color:#667085;font-size:.72rem;line-height:1.35}
      #${MODAL_ID} .cb-br-now{color:#8b5c00;font-weight:800}
      #${MODAL_ID} .cb-br-plan{grid-column:1/-1;color:#526176;font-size:.7rem;line-height:1.35}
      #${MODAL_ID} .cb-br-plan strong{color:#294a84}
      #${MODAL_ID} .cb-br-basis{margin:-2px 0 8px;color:#526176;font-size:.7rem;line-height:1.35}
      #${MODAL_ID} .cb-br-unprojected{margin:0 0 10px;border:1px solid #f1d38a;border-radius:9px;background:#fff8e6;color:#5b4300;padding:7px 9px;font-size:.72rem;line-height:1.35}
      #${MODAL_ID} .cb-br-empty{border:1px dashed #d0d5dd;border-radius:11px;color:#667085;padding:16px;text-align:center;font-size:.78rem}
      #${MODAL_ID} .cb-br-loading{min-height:140px;display:flex;align-items:center;justify-content:center;color:#667085;font-size:.8rem}
      @media(max-width:575.98px){#${MODAL_ID} .modal-dialog{margin:.5rem}#${MODAL_ID} .modal-body{padding:12px}#${MODAL_ID} .cb-br-count{font-size:.61rem}}
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
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header">
            <div><h5 class="modal-title mb-0">Bench Report</h5><div class="small text-muted">Actual + projected bench innings</div></div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body" data-cb-bench-report-body><div class="cb-br-loading">Loading…</div></div>
          <div class="modal-footer">
            <button type="button" class="btn btn-outline-secondary" data-cb-bench-refresh>Refresh</button>
            <button type="button" class="btn btn-primary" data-bs-dismiss="modal">Back to Game</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('[data-cb-bench-refresh]')?.addEventListener('click',loadReport);
    return modal;
  }

  function inningValue(value) {
    const number = Number.parseFloat(value);
    return Number.isFinite(number) ? number : null;
  }

  function inningLabel(value) {
    const number = inningValue(value);
    if (number === null) return String(value || '—');
    return Number.isInteger(number) ? String(number) : String(number).replace(/\.0+$/,'');
  }

  function rosterName(player) {
    const name = String(player?.name || '').trim();
    const number = String(player?.number ?? '').trim();
    return number ? `#${number} ${name}` : name;
  }

  function parseInnings(value) {
    if (value && typeof value === 'object') return value;
    if (typeof value !== 'string') return {};
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function requiredFieldPositions(state) {
    return Number(state?.outfielder_count) === 4
      ? ['C','1B','2B','3B','SS','LF','LCF','RCF','RF']
      : ['C','1B','2B','3B','SS','LF','CF','RF'];
  }

  function hasCompletePlannedDefense(alignment, state) {
    if (!alignment || typeof alignment !== 'object') return false;
    // A planned defense may intentionally leave P open. Do not treat an empty
    // Quick Start inning slot as a plan that has the whole roster sitting.
    return requiredFieldPositions(state).every(position => String(alignment[position] || '').trim());
  }

  function ordinal(value) {
    const number = inningValue(value);
    if (number === null || !Number.isInteger(number)) return inningLabel(value);
    const teen = number % 100 >= 11 && number % 100 <= 13;
    return `${number}${teen ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[number % 10] || 'th')}`;
  }

  function openFieldPositions(alignment, state) {
    return requiredFieldPositions(state).filter(position => !String((alignment || {})[position] || '').trim());
  }

  /*
   * Innings ahead, each with the defense it will use: the upcoming inning as
   * it will actually start (the Next Inning defense -- carried forward, the
   * plan, or the coach's edit), later innings from the pregame plan. An
   * inning that can't be projected -- a position open, or no plan at all --
   * is named instead of being left out silently.
   */
  function inningsAhead(state, prep) {
    const currentValue = inningValue(state?.current_inning);
    const plannedInnings = parseInnings(state?.rotation?.innings);
    const nextKey = String(prep?.next_inning || '');
    const upcoming = prep?.confirmed?.alignment || null;
    const keys = new Set(Object.keys(plannedInnings));
    if (nextKey && upcoming) keys.add(nextKey);
    // Every regulation inning ahead, planned or not.
    const regulation = Number(state?.regulation_innings) || 0;
    for (let inning = 1; inning <= regulation; inning += 1) keys.add(String(inning));

    const projected = [];
    const unprojected = [];
    [...keys]
      .map(inning => ({inning, value: inningValue(inning)}))
      .filter(item => item.value !== null && Number.isInteger(item.value) &&
        (currentValue === null || item.value > currentValue))
      .sort((a, b) => a.value - b.value)
      .forEach(({inning}) => {
        const isNext = inning === nextKey && upcoming;
        const alignment = isNext ? upcoming : (plannedInnings[inning] || {});
        const named = Object.values(alignment).some(name => String(name || '').trim());
        if (!named) {
          unprojected.push({inning, reason: 'not planned'});
        } else if (!hasCompletePlannedDefense(alignment, state)) {
          const open = openFieldPositions(alignment, state);
          unprojected.push({inning, reason: `${open.join(', ')} open`});
        } else {
          projected.push({inning, value: inningValue(inning), alignment, upcoming: Boolean(isNext)});
        }
      });
    return {projected, unprojected};
  }

  function buildReport(state, prep = null) {
    const roster = Array.isArray(state?.roster) ? state.roster.filter(player => player?.name) : [];
    const currentValue = inningValue(state?.current_inning);
    const currentLabel = inningLabel(state?.current_inning || '1');
    const actual = state?.actual_rotation && typeof state.actual_rotation === 'object' ? state.actual_rotation : {};
    const completed = Object.entries(actual)
      .map(([inning,alignment]) => ({inning,value:inningValue(inning),alignment:alignment || {}}))
      .filter(item => item.value !== null && (currentValue === null || item.value < currentValue))
      .sort((a,b)=>a.value-b.value);

    const {projected: futurePlanned, unprojected} = inningsAhead(state, prep);

    const currentAssigned = new Set(
      Object.values(state?.current_alignment || {})
        .map(value => String(value ?? '').trim())
        .filter(Boolean)
    );
    const history = roster.map(player => {
      const name = String(player.name).trim();
      const sat = [];
      completed.forEach(item => {
        const assigned = Object.values(item.alignment || {})
          .map(value => String(value ?? '').trim());
        if (!assigned.includes(name)) {
          sat.push(inningLabel(item.inning));
        }
      });
      const currentBench = !currentAssigned.has(name);
      const plannedSat = futurePlanned
        .filter(item => {
          const assigned = Object.values(item.alignment || {})
            .map(value => String(value ?? '').trim());
          return !assigned.includes(name);
        })
        .map(item => inningLabel(item.inning));
      const total = sat.length + (currentBench ? 1 : 0);
      return {player,name,display:rosterName(player),sat,currentBench,plannedSat,total};
    }).sort((a,b) => {
      if (a.currentBench !== b.currentBench) return a.currentBench ? -1 : 1;
      if (a.total !== b.total) return b.total - a.total;
      if (a.plannedSat.length !== b.plannedSat.length) return b.plannedSat.length - a.plannedSat.length;
      return a.name.localeCompare(b.name);
    });
    return {history,currentLabel,futurePlanned,unprojected,nextLabel: ordinal(prep?.next_inning),
      upcomingKnown: Boolean(prep?.confirmed?.alignment)};
  }

  function countLabel(row) {
    const actual = row.total;
    const planned = row.plannedSat.length;
    if (actual && planned) return `${actual} so far · ${planned} planned`;
    if (actual) return `${actual} ${actual === 1 ? 'inning' : 'innings'}`;
    if (planned) return `${planned} planned`;
    return '0 innings';
  }

  function renderReport(state, prep = null) {
    const modal = ensureModal();
    const body = modal.querySelector('[data-cb-bench-report-body]');
    if (!body) return;
    const report = buildReport(state, prep);
    const onBench = report.history.filter(row => row.currentBench).length;
    const rows = report.history.length ? report.history.map(row => {
      const completedText = row.sat.length ? row.sat.join(', ') : 'None';
      const current = row.currentBench ? `<span class="cb-br-now"> · Inning ${esc(report.currentLabel)} now</span>` : '';
      const planned = row.plannedSat.length
        ? `<div class="cb-br-plan"><strong>Projected to sit:</strong> ${esc(row.plannedSat.join(', '))}</div>`
        : '';
      return `<div class="cb-br-row ${row.currentBench ? 'current' : ''}"><div class="cb-br-player">${esc(row.display)}</div><div class="cb-br-count">${esc(countLabel(row))}</div><div class="cb-br-history"><strong>Sat:</strong> ${esc(completedText)}${current}</div>${planned}</div>`;
    }).join('') : '<div class="cb-br-empty">No bench history yet.</div>';
    const planChip = report.futurePlanned.length
      ? `<span class="cb-br-chip">Projected innings ahead: ${report.futurePlanned.length}</span>`
      : '';
    // Where the projections come from, and what they leave out.
    const basis = report.upcomingKnown
      ? `Projections use the ${report.nextLabel}-inning defense as it will start, then the pregame plan.`
      : "Projections use the pregame plan; the next inning's defense couldn't be read.";
    const missing = report.unprojected.length
      ? `<div class="cb-br-unprojected" data-cb-br-unprojected><strong>Not projected:</strong> ${
          esc(report.unprojected.map(item => `${ordinal(item.inning)} (${item.reason})`).join(', '))
        }. Sits for ${report.unprojected.length === 1 ? 'that inning aren' : 'those innings aren'}'t counted.</div>`
      : '';
    body.innerHTML = `<div class="cb-br-summary"><span class="cb-br-chip">Inning ${esc(report.currentLabel)}</span><span class="cb-br-chip">On bench: ${onBench}</span>${planChip}</div><div class="cb-br-basis" data-cb-br-basis>${esc(basis)}</div>${missing}<div class="cb-br-list">${rows}</div>`;
  }

  async function loadReport() {
    if (loadBusy) return;
    const modal = ensureModal();
    const body = modal.querySelector('[data-cb-bench-report-body]');
    const refresh = modal.querySelector('[data-cb-bench-refresh]');
    loadBusy = true;
    if (refresh) refresh.disabled = true;
    if (body) body.innerHTML = '<div class="cb-br-loading">Loading…</div>';
    try {
      const [response, prep] = await Promise.all([
        fetch(`/api/live-game/${gameId}/state`,{cache:'no-store'}),
        // The defense the next inning will actually start with.
        fetch(`/api/live-game/${gameId}/next-inning-prep`,{cache:'no-store'})
          .then(r => (r.ok ? r.json() : null))
          .catch(() => null),
      ]);
      const data = await response.json().catch(()=>({}));
      if (!response.ok) throw new Error(data.message || `Unable to load bench report (${response.status}).`);
      renderReport(data, prep?.status === 'success' ? prep : null);
    } catch (err) {
      if (body) body.innerHTML = `<div class="alert alert-danger mb-0">${esc(err.message)}</div>`;
    } finally {
      loadBusy = false;
      if (refresh) refresh.disabled = false;
    }
  }

  function openReport() {
    bootstrap.Modal.getOrCreateInstance(ensureModal()).show();
    loadReport();
  }

  function ensureButton() {
    const benchWrap = document.querySelector('#cbQuickDefense .cb-qd-bench-wrap');
    if (!benchWrap || benchWrap.querySelector('[data-cb-bench-report]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-outline-secondary cb-bench-report-btn';
    button.dataset.cbBenchReport = 'true';
    button.innerHTML = '<i class="bi bi-clipboard-data me-1"></i>Bench Report';
    button.addEventListener('click',openReport);
    benchWrap.appendChild(button);
  }

  function attach() {
    const card = document.getElementById('cbQuickDefense');
    if (!card) return false;
    ensureButton();
    if (!cardObserver) {
      cardObserver = new MutationObserver(() => requestAnimationFrame(ensureButton));
      cardObserver.observe(card,{childList:true,subtree:true});
    }
    return true;
  }

  function start() {
    installStyles();
    if (attach()) return;
    rootObserver = new MutationObserver(() => {
      if (!attach()) return;
      rootObserver?.disconnect();
      rootObserver = null;
    });
    rootObserver.observe(document.body,{childList:true,subtree:true});
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded',start,{once:true})
    : start();
})();