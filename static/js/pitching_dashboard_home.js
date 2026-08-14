(() => {
  'use strict';

  if (window.location.pathname !== '/') return;

  const $ = (selector, root = document) => root.querySelector(selector);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  let summaryRendering = false;
  let summaryTimer = null;

  function installStyles() {
    if ($('#pitching-home-v2-styles')) return;
    const style = document.createElement('style');
    style.id = 'pitching-home-v2-styles';
    style.textContent = `
      #pitching .ph-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}
      #pitching .ph-card{border:1px solid #e1e5ea;border-radius:12px;background:#fff;padding:11px 12px;min-width:0}
      #pitching .ph-name{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:9px}
      #pitching .ph-name strong{font-size:.9rem;color:#172033;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #pitching .ph-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}
      #pitching .ph-metric{background:#f7f8fa;border-radius:8px;padding:7px 8px;min-width:0}
      #pitching .ph-label{display:block;font-size:.55rem;text-transform:uppercase;letter-spacing:.07em;font-weight:850;color:#667085;margin-bottom:2px}
      #pitching .ph-value{display:block;font-size:.77rem;font-weight:800;color:#1d2939;white-space:normal}
      #pitching .ph-detail{font-size:.65rem;color:#7b8492;margin-top:7px}
      #pitching .ph-entry-help{font-size:.72rem;color:#667085;margin-top:4px}
      #pitching .ph-game-fields{display:contents}
      #pitching .ph-hidden{display:none!important}
      #pitching .ph-form-card .card-header{background:#fff}
      #pitching .ph-form-card .form-control,#pitching .ph-form-card .form-select{min-height:42px}
      #editPitchingOutingModal .ph-hidden{display:none!important}
      @media (max-width:575.98px){
        #pitching .ph-grid{grid-template-columns:1fr}
        #pitching .ph-metrics{grid-template-columns:1fr 1fr}
        #pitching .ph-metric:last-child{grid-column:1/-1}
      }
      @media (min-width:576px) and (orientation:portrait){
        #pitching .ph-grid{grid-template-columns:1fr 1fr}
      }
      @media (min-width:768px) and (orientation:landscape){
        #pitching .ph-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
      }
    `;
    document.head.appendChild(style);
  }

  function statusBadge(summary) {
    const status = String(summary?.status || 'Verify Data');
    if (status === 'Available') return '<span class="badge text-bg-success">Available</span>';
    if (status === 'Same-Day Game Restriction') return '<span class="badge text-bg-warning">No 2nd Game</span>';
    if (['Pitch Count Incomplete', 'Innings Incomplete'].includes(status)) return '<span class="badge text-bg-warning">Verify Data</span>';
    if (/target/i.test(status)) return `<span class="badge text-bg-warning">${esc(status)}</span>`;
    return `<span class="badge text-bg-danger">${esc(status)}</span>`;
  }

  function formatOfficial(summary) {
    if (summary?.rule_type === 'innings') {
      const today = summary.daily_innings ?? '—';
      return `${esc(today)} IP`;
    }
    const today = summary?.official_daily_pitches;
    const max = summary?.max_daily;
    if (today == null) return '—';
    return max != null ? `${esc(today)} / ${esc(max)}` : String(today);
  }

  function formatWorkload(summary) {
    const value = summary?.workload_daily_pitches;
    return value == null ? '—' : `${esc(value)} pitches`;
  }

  function formatNext(summary) {
    const value = summary?.next_available;
    if (!value || value === 'N/A') return 'Today';
    return esc(value);
  }

  async function renderSummary() {
    const container = $('#pitch-count-summary-container');
    if (!container || summaryRendering) return;
    summaryRendering = true;
    try {
      const [pitchResponse, rosterResponse] = await Promise.all([
        fetch('/api/pitching_data', {cache: 'no-store'}),
        fetch('/api/roster', {cache: 'no-store'}),
      ]);
      if (!pitchResponse.ok || !rosterResponse.ok) return;
      const pitchData = await pitchResponse.json();
      const roster = await rosterResponse.json();
      const summary = pitchData.pitch_count_summary || {};
      const outings = pitchData.pitching || [];
      const usedIds = new Set(outings.map((outing) => Number(outing.player_id)).filter(Number.isFinite));
      const pitchers = roster
        .filter((player) => player.pitcher_role !== 'Not a Pitcher' || usedIds.has(Number(player.id)))
        .sort((a, b) => String(a.name).localeCompare(String(b.name)));

      const cards = pitchers.map((player) => {
        const data = summary[player.name] || {};
        const detail = data.status_detail ? `<div class="ph-detail">${esc(data.status_detail)}</div>` : '';
        const officialLabel = data.rule_type === 'innings' ? 'Official Innings' : 'Official Pitches';
        const nextLabel = data.status === 'Available' ? 'Next' : 'Eligible';
        return `
          <article class="ph-card">
            <div class="ph-name"><strong>${esc(player.name)}</strong>${statusBadge(data)}</div>
            <div class="ph-metrics">
              <div class="ph-metric"><span class="ph-label">${officialLabel}</span><span class="ph-value">${formatOfficial(data)}</span></div>
              <div class="ph-metric"><span class="ph-label">Throwing Workload</span><span class="ph-value">${formatWorkload(data)}</span></div>
              <div class="ph-metric"><span class="ph-label">${nextLabel}</span><span class="ph-value">${formatNext(data)}</span></div>
            </div>
            ${detail}
          </article>`;
      }).join('');

      container.innerHTML = `<div data-pitching-dashboard-fixed="1" class="ph-grid">${cards || '<div class="text-muted p-3">No pitchers or outings recorded yet.</div>'}</div>`;
      const header = container.closest('.card')?.querySelector('.card-header');
      const title = header?.querySelector('h5');
      if (title) title.textContent = 'Pitching Dashboard';
      if (header && !header.querySelector('.ph-header-help')) {
        const help = document.createElement('div');
        help.className = 'small text-muted ph-header-help';
        help.textContent = 'Official game-rule status is separate from practice and lesson workload.';
        title?.insertAdjacentElement('afterend', help);
      }
    } catch (error) {
      console.error('Pitching dashboard refresh failed:', error);
    } finally {
      summaryRendering = false;
    }
  }

  function scheduleSummary() {
    clearTimeout(summaryTimer);
    summaryTimer = setTimeout(() => {
      const container = $('#pitch-count-summary-container');
      if (container && !container.querySelector('[data-pitching-dashboard-fixed="1"]')) renderSummary();
    }, 40);
  }

  async function rebuildAddForm() {
    const pitchingTab = $('#mainTabContent #pitching');
    if (!pitchingTab) return;
    const form = $('form[action$="/add_pitching"]', pitchingTab);
    if (!form || form.dataset.pitchingV2 === '1') return;

    let roster = [];
    try {
      const response = await fetch('/api/roster', {cache: 'no-store'});
      if (response.ok) roster = await response.json();
    } catch (_) {}

    const today = new Date();
    const localDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    form.dataset.pitchingV2 = '1';
    form.closest('.card')?.classList.add('ph-form-card');
    const cardTitle = form.closest('.card')?.querySelector('.card-header h5');
    if (cardTitle) cardTitle.textContent = 'Record Throwing';

    form.innerHTML = `
      <div class="row g-3">
        <div class="col-6">
          <label for="pitch_date" class="form-label">Date</label>
          <input type="date" id="pitch_date" name="pitch_date" class="form-control" value="${localDate}" required>
        </div>
        <div class="col-6">
          <label for="pitching-log-pitcher-select" class="form-label">Pitcher</label>
          <select name="player_id" id="pitching-log-pitcher-select" class="form-select" required>
            <option value="">Select pitcher…</option>
            ${roster.sort((a, b) => String(a.name).localeCompare(String(b.name))).map((player) => `<option value="${player.id}">${esc(player.name)}</option>`).join('')}
          </select>
        </div>
        <div class="col-6">
          <label for="outing_type" class="form-label">Session Type</label>
          <select name="outing_type" id="outing_type" class="form-select">
            <option value="Game">Game</option>
            <option value="Practice">Practice / Bullpen</option>
            <option value="External/Lesson">Pitching Lesson / External</option>
          </select>
        </div>
        <div class="col-6">
          <label for="pitches" class="form-label">Pitch Count</label>
          <input type="number" min="0" step="1" inputmode="numeric" id="pitches" name="pitches" class="form-control" required>
        </div>
        <div class="col-12">
          <label for="opponent" class="form-label" id="ph-context-label">Opponent</label>
          <input type="text" id="opponent" name="opponent" class="form-control" placeholder="Opponent" required>
          <div class="ph-entry-help" id="ph-context-help">Required for game outings.</div>
        </div>
        <div class="col-7 ph-game-only">
          <label for="innings_whole" class="form-label">Full Innings</label>
          <input type="number" min="0" step="1" inputmode="numeric" id="innings_whole" name="innings_whole" class="form-control" placeholder="2" required>
        </div>
        <div class="col-5 ph-game-only">
          <label for="innings_outs" class="form-label">Extra Outs</label>
          <select id="innings_outs" name="innings_outs" class="form-select">
            <option value="0">0</option><option value="1">1</option><option value="2">2</option>
          </select>
        </div>
        <div class="col-12 ph-game-only">
          <label for="pitcher_type" class="form-label">Role</label>
          <select name="pitcher_type" id="pitcher_type" class="form-select">
            <option value="Starter">Starter</option><option value="Reliever">Reliever</option>
          </select>
          <div class="ph-entry-help">Game only. Example: 2 full innings + 1 out = 2.1 IP.</div>
        </div>
      </div>
      <button type="submit" class="btn btn-primary w-100 mt-3">Record Throwing</button>`;

    const type = $('#outing_type', form);
    const context = $('#opponent', form);
    const whole = $('#innings_whole', form);
    const role = $('#pitcher_type', form);
    const label = $('#ph-context-label', form);
    const help = $('#ph-context-help', form);

    function sync() {
      const isGame = type.value === 'Game';
      form.querySelectorAll('.ph-game-only').forEach((el) => el.classList.toggle('ph-hidden', !isGame));
      whole.required = isGame;
      role.required = isGame;
      context.required = isGame;
      label.textContent = isGame ? 'Opponent' : 'Context / Notes';
      context.placeholder = isGame ? 'Opponent' : (type.value === 'Practice' ? 'Optional — bullpen, flat ground, etc.' : 'Optional — instructor / lesson notes');
      help.textContent = isGame ? 'Required for game outings.' : 'Optional. Innings and Starter/Reliever do not apply to this session type.';
    }

    type.addEventListener('change', sync);
    sync();
  }

  function modernizeEditModal() {
    const modal = $('#editPitchingOutingModal');
    if (!modal || modal.dataset.pitchingV2 === '1') return;
    modal.dataset.pitchingV2 = '1';

    const type = $('#edit_outing_type', modal);
    const innings = $('#edit_innings', modal);
    const role = $('#edit_pitcher_type', modal);
    if (!type || !innings || !role) return;
    const inningsGroup = innings.closest('.col-6');
    const roleGroup = role.closest('.col-6');

    function sync() {
      const isGame = type.value === 'Game';
      inningsGroup?.classList.toggle('ph-hidden', !isGame);
      roleGroup?.classList.toggle('ph-hidden', !isGame);
      innings.required = isGame;
      role.required = isGame;
      const inningsLabel = inningsGroup?.querySelector('label');
      if (inningsLabel) inningsLabel.textContent = 'Innings Pitched';
      innings.placeholder = 'e.g., 2.1';
    }

    type.addEventListener('change', sync);
    modal.addEventListener('shown.bs.modal', sync);
    sync();
  }

  function watchSummary() {
    const container = $('#pitch-count-summary-container');
    if (!container) return;
    const observer = new MutationObserver(() => {
      if (!container.querySelector('[data-pitching-dashboard-fixed="1"]')) scheduleSummary();
    });
    observer.observe(container, {childList: true, subtree: true});
  }

  async function init() {
    installStyles();
    await rebuildAddForm();
    modernizeEditModal();
    watchSummary();
    setTimeout(renderSummary, 180);
    document.querySelectorAll('a[href="#pitching"]').forEach((link) => link.addEventListener('shown.bs.tab', () => {
      rebuildAddForm();
      renderSummary();
    }));
    window.addEventListener('orientationchange', () => setTimeout(renderSummary, 120));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(init, 80), {once: true});
  } else {
    setTimeout(init, 80);
  }
})();
