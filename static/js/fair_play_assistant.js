(() => {
  'use strict';

  const path = window.location.pathname;
  const isSettingsPage = path === '/admin/settings';
  const isGamePage = /^\/game\/\d+\/?$/.test(path);
  if (!isSettingsPage && !isGamePage) return;

  const API_URL = '/api/fair-play/settings';
  const ALL_INFIELD_POSITIONS = ['P', 'C', '1B', '2B', '3B', 'SS'];
  let settingsResponse = null;
  let matrixObserver = null;
  let renderTimer = null;

  const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]));

  async function fetchSettings() {
    const response = await fetch(API_URL, {
      method: 'GET',
      headers: {Accept: 'application/json'},
      cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || 'Could not load playing-time settings.');
    return data;
  }

  async function saveSettings(payload) {
    const response = await fetch(API_URL, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || 'Could not save playing-time settings.');
    return data;
  }

  function modeLabel(mode) {
    if (mode === 'track') return 'Track Only';
    if (mode === 'rules') return 'Fair Play Rules';
    return 'Off';
  }

  function injectSettingsTab() {
    if (!isSettingsPage || document.getElementById('fair-play-settings')) return;

    const tabList = document.querySelector('.nav-tabs.card-header-tabs');
    const tabContent = document.querySelector('.tab-content');
    if (!tabList || !tabContent) return;

    const navItem = document.createElement('li');
    navItem.className = 'nav-item';
    navItem.innerHTML = `
      <a class="nav-link" data-bs-toggle="tab" href="#fair-play-settings" id="fairPlaySettingsTab">
        Playing Time
      </a>
    `;
    tabList.appendChild(navItem);

    const pane = document.createElement('div');
    pane.className = 'tab-pane fade';
    pane.id = 'fair-play-settings';
    pane.innerHTML = `
      <div class="mb-4">
        <div class="d-flex align-items-start justify-content-between gap-3 flex-wrap mb-2">
          <div>
            <h6 class="text-muted mb-1">Playing Time Assistance</h6>
            <p class="small text-muted mb-0">
              Team-level playing-time tracking and Fair Play checks.
            </p>
          </div>
          <span class="badge text-bg-light border" id="fairPlayModeBadge">Loading…</span>
        </div>
      </div>

      <div class="vstack gap-2 mb-4" id="fairPlayModeChoices">
        <label class="border rounded p-3 d-flex gap-3 align-items-start" style="cursor:pointer;">
          <input class="form-check-input mt-1" type="radio" name="fair_play_mode" value="off">
          <span>
            <span class="fw-semibold d-block">Off</span>
            <span class="small text-muted">No Fair Play checks or Game Day warnings.</span>
          </span>
        </label>
        <label class="border rounded p-3 d-flex gap-3 align-items-start" style="cursor:pointer;">
          <input class="form-check-input mt-1" type="radio" name="fair_play_mode" value="track">
          <span>
            <span class="fw-semibold d-block">Track Only</span>
            <span class="small text-muted">Show playing-time and bench summaries without rule warnings.</span>
          </span>
        </label>
        <label class="border rounded p-3 d-flex gap-3 align-items-start" style="cursor:pointer;">
          <input class="form-check-input mt-1" type="radio" name="fair_play_mode" value="rules">
          <span>
            <span class="fw-semibold d-block">Fair Play Rules</span>
            <span class="small text-muted">Check the rotation against the settings below.</span>
          </span>
        </label>
      </div>

      <div class="card border-0 bg-light mb-3" id="fairPlayRuleFields">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
            <div>
              <div class="fw-semibold">Fair Play Rules</div>
              <div class="small text-muted">Guidance only. Fair Play never changes or blocks a rotation.</div>
            </div>
            <span class="badge text-bg-secondary" id="fairPlayRulesState">Inactive</span>
          </div>

          <div class="row g-3">
            <div class="col-md-6">
              <label class="form-label fw-semibold" for="fairPlayMinInfield">Minimum infield innings per player</label>
              <input class="form-control" type="number" id="fairPlayMinInfield" min="0" max="12" step="1" value="1">
              <div class="form-text">Set to 0 if your team does not have an infield requirement.</div>
            </div>
            <div class="col-md-6">
              <label class="form-label fw-semibold" for="fairPlayMaxBench">Maximum consecutive bench innings</label>
              <select class="form-select" id="fairPlayMaxBench">
                <option value="0">Do not check this</option>
                <option value="1">1 inning</option>
                <option value="2">2 innings</option>
                <option value="3">3 innings</option>
                <option value="4">4 innings</option>
              </select>
              <div class="form-text">CoachBoard warns only after a player exceeds this number.</div>
            </div>
          </div>

          <div class="mt-3">
            <div class="form-label fw-semibold mb-1">Positions that count as infield</div>
            <div class="small text-muted mb-2">League definitions differ, so choose what counts for your team.</div>
            <div class="d-flex flex-wrap gap-2" id="fairPlayPositionChoices">
              ${ALL_INFIELD_POSITIONS.map((pos) => `
                <label class="border rounded px-3 py-2 bg-white" style="cursor:pointer;">
                  <input class="form-check-input me-1 fair-play-position" type="checkbox" value="${pos}">
                  ${pos}
                </label>
              `).join('')}
            </div>
          </div>
        </div>
      </div>

      <div class="alert d-none mb-3" id="fairPlaySaveStatus" role="alert"></div>
      <button type="button" class="btn btn-primary w-100" id="fairPlaySaveButton">
        <i class="bi bi-check2-circle me-1"></i>Save Playing Time Settings
      </button>
    `;
    tabContent.appendChild(pane);

    pane.querySelectorAll('input[name="fair_play_mode"]').forEach((input) => {
      input.addEventListener('change', updateSettingsFieldState);
    });
    document.getElementById('fairPlaySaveButton')?.addEventListener('click', handleSettingsSave);

    if (window.location.hash === '#fair-play-settings' && typeof bootstrap !== 'undefined') {
      bootstrap.Tab.getOrCreateInstance(document.getElementById('fairPlaySettingsTab')).show();
    }
  }

  function selectedMode() {
    return document.querySelector('input[name="fair_play_mode"]:checked')?.value || 'off';
  }

  function updateSettingsFieldState() {
    const mode = selectedMode();
    const ruleFields = document.getElementById('fairPlayRuleFields');
    const ruleState = document.getElementById('fairPlayRulesState');
    const badge = document.getElementById('fairPlayModeBadge');
    const active = mode === 'rules';

    if (badge) badge.textContent = modeLabel(mode);
    if (ruleState) {
      ruleState.textContent = active ? 'Active' : 'Inactive';
      ruleState.className = `badge ${active ? 'text-bg-success' : 'text-bg-secondary'}`;
    }
    if (ruleFields) {
      ruleFields.classList.toggle('opacity-50', !active);
      ruleFields.querySelectorAll('input, select').forEach((field) => {
        field.disabled = !active;
      });
    }
  }

  function populateSettingsForm(data) {
    settingsResponse = data;
    const settings = data.settings || {};
    const mode = settings.mode || 'off';
    const modeInput = document.querySelector(`input[name="fair_play_mode"][value="${mode}"]`);
    if (modeInput) modeInput.checked = true;

    const minInfield = document.getElementById('fairPlayMinInfield');
    const maxBench = document.getElementById('fairPlayMaxBench');
    if (minInfield) minInfield.value = Number.isFinite(Number(settings.min_infield_innings)) ? settings.min_infield_innings : 1;
    if (maxBench) maxBench.value = String(Number.isFinite(Number(settings.max_consecutive_bench)) ? settings.max_consecutive_bench : 1);

    const activePositions = new Set(settings.infield_positions || ['1B', '2B', '3B', 'SS']);
    document.querySelectorAll('.fair-play-position').forEach((input) => {
      input.checked = activePositions.has(input.value);
    });

    const saveButton = document.getElementById('fairPlaySaveButton');
    if (saveButton && data.can_edit === false) {
      saveButton.disabled = true;
      saveButton.textContent = 'Head Coach access required';
      document.querySelectorAll('#fair-play-settings input, #fair-play-settings select').forEach((field) => {
        field.disabled = true;
      });
    } else {
      updateSettingsFieldState();
    }
  }

  function showSettingsStatus(message, kind = 'success') {
    const status = document.getElementById('fairPlaySaveStatus');
    if (!status) return;
    status.className = `alert alert-${kind} mb-3`;
    status.textContent = message;
  }

  async function handleSettingsSave() {
    const button = document.getElementById('fairPlaySaveButton');
    if (!button || button.disabled) return;

    const payload = {
      mode: selectedMode(),
      min_infield_innings: Number(document.getElementById('fairPlayMinInfield')?.value || 0),
      max_consecutive_bench: Number(document.getElementById('fairPlayMaxBench')?.value || 0),
      infield_positions: Array.from(document.querySelectorAll('.fair-play-position:checked')).map((input) => input.value),
    };

    button.disabled = true;
    const oldText = button.innerHTML;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Saving…';

    try {
      const data = await saveSettings(payload);
      settingsResponse = {...settingsResponse, settings: data.settings};
      populateSettingsForm(settingsResponse);
      showSettingsStatus('Playing-time settings saved for this team.', 'success');
    } catch (error) {
      showSettingsStatus(error.message, 'danger');
    } finally {
      button.disabled = false;
      button.innerHTML = oldText;
    }
  }

  async function initSettingsPage() {
    injectSettingsTab();
    if (!document.getElementById('fair-play-settings')) return;
    try {
      populateSettingsForm(await fetchSettings());
    } catch (error) {
      showSettingsStatus(error.message, 'danger');
    }
  }

  function ensureGameStatusCard() {
    if (document.getElementById('fairPlayGameStatus')) return document.getElementById('fairPlayGameStatus');

    const rotationBoard = document.getElementById('rotation-board');
    if (!rotationBoard) return null;

    const wrapper = document.createElement('div');
    wrapper.id = 'fairPlayGameStatus';
    wrapper.className = 'px-3 pt-3';
    wrapper.innerHTML = `
      <div class="card border-warning-subtle shadow-sm mb-0">
        <div class="card-body py-3">
          <div class="d-flex justify-content-between align-items-start gap-2 flex-wrap">
            <div>
              <div class="d-flex align-items-center gap-2 mb-1">
                <i class="bi bi-people-fill text-warning" id="fairPlayGameIcon"></i>
                <span class="fw-semibold">Fair Play</span>
                <span class="badge text-bg-light border">Rules active</span>
              </div>
              <div class="small" id="fairPlayGameSummary">Checking the defensive rotation…</div>
            </div>
            <button class="btn btn-sm btn-outline-secondary" type="button" data-bs-toggle="collapse" data-bs-target="#fairPlayGameDetails" aria-expanded="false">
              Review players
            </button>
          </div>
          <div class="collapse mt-3" id="fairPlayGameDetails">
            <div id="fairPlayGameDetailsBody" class="small"></div>
          </div>
        </div>
      </div>
    `;
    rotationBoard.insertAdjacentElement('beforebegin', wrapper);
    return wrapper;
  }

  function parseRotationMatrix() {
    const table = document.querySelector('#rotation-matrix-container table');
    if (!table) return [];

    return Array.from(table.querySelectorAll('tbody tr')).map((row) => {
      const cells = Array.from(row.querySelectorAll('td'));
      if (cells.length < 2) return null;
      const player = cells[0].textContent.trim();
      const assignments = cells.slice(1).map((cell) => {
        const badge = cell.querySelector('.badge');
        if (badge) return badge.textContent.trim().toUpperCase();
        return cell.textContent.toUpperCase().includes('BENCH') ? 'BENCH' : '';
      });
      return {player, assignments};
    }).filter(Boolean);
  }

  function playerStatus(row, settings) {
    const infieldPositions = new Set(settings.infield_positions || []);
    let infieldInnings = 0;
    let fieldInnings = 0;
    let currentBenchStreak = 0;
    let maxBenchStreak = 0;

    row.assignments.forEach((position) => {
      if (!position || position === 'BENCH') {
        currentBenchStreak += 1;
        maxBenchStreak = Math.max(maxBenchStreak, currentBenchStreak);
        return;
      }

      fieldInnings += 1;
      currentBenchStreak = 0;
      if (infieldPositions.has(position)) infieldInnings += 1;
    });

    const minInfield = Number(settings.min_infield_innings || 0);
    const maxBench = Number(settings.max_consecutive_bench || 0);
    return {
      player: row.player,
      infieldInnings,
      fieldInnings,
      benchInnings: row.assignments.length - fieldInnings,
      maxBenchStreak,
      needsInfield: minInfield > 0 && infieldInnings < minInfield,
      benchWarning: maxBench > 0 && maxBenchStreak > maxBench,
    };
  }

  function renderGameStatus() {
    const settings = settingsResponse?.settings;
    const wrapper = document.getElementById('fairPlayGameStatus');
    if (!settings || settings.mode !== 'rules') {
      wrapper?.remove();
      return;
    }

    const card = ensureGameStatusCard();
    if (!card) return;

    const summary = document.getElementById('fairPlayGameSummary');
    const details = document.getElementById('fairPlayGameDetailsBody');
    const icon = document.getElementById('fairPlayGameIcon');
    const innerCard = card.querySelector('.card');
    const rows = parseRotationMatrix();

    if (!rows.length) {
      if (summary) summary.textContent = 'Add defensive innings to see Fair Play status.';
      if (details) details.innerHTML = '<span class="text-muted">No rotation data yet.</span>';
      return;
    }

    const statuses = rows.map((row) => playerStatus(row, settings));
    const needsInfield = statuses.filter((item) => item.needsInfield);
    const benchWarnings = statuses.filter((item) => item.benchWarning);
    const issueNames = new Set([...needsInfield.map((item) => item.player), ...benchWarnings.map((item) => item.player)]);
    const issues = statuses.filter((item) => issueNames.has(item.player));
    const minInfield = Number(settings.min_infield_innings || 0);
    const maxBench = Number(settings.max_consecutive_bench || 0);
    const metInfield = statuses.length - needsInfield.length;

    const summaryParts = [];
    if (minInfield > 0) summaryParts.push(`${metInfield}/${statuses.length} meet the ${minInfield}-inning IF goal`);
    if (maxBench > 0) summaryParts.push(`${benchWarnings.length} bench-streak warning${benchWarnings.length === 1 ? '' : 's'}`);
    if (!summaryParts.length) summaryParts.push('Rules are active, but no checks are currently enabled.');

    if (summary) summary.textContent = summaryParts.join(' · ');

    const hasIssues = issues.length > 0;
    if (icon) {
      icon.className = `bi ${hasIssues ? 'bi-exclamation-triangle-fill text-warning' : 'bi-check-circle-fill text-success'}`;
    }
    if (innerCard) {
      innerCard.classList.toggle('border-warning-subtle', hasIssues);
      innerCard.classList.toggle('border-success-subtle', !hasIssues);
    }

    if (!details) return;
    if (!hasIssues) {
      details.innerHTML = `
        <div class="text-success">
          <i class="bi bi-check-circle-fill me-1"></i>Current rotation meets Fair Play settings.
        </div>
      `;
      return;
    }

    details.innerHTML = `
      <div class="table-responsive">
        <table class="table table-sm align-middle mb-0">
          <thead>
            <tr>
              <th>Player</th>
              <th class="text-center">IF</th>
              <th class="text-center">Bench</th>
              <th>Needs attention</th>
            </tr>
          </thead>
          <tbody>
            ${issues.map((item) => {
              const messages = [];
              if (item.needsInfield) {
                const remaining = Math.max(0, minInfield - item.infieldInnings);
                messages.push(`Needs ${remaining} more IF inning${remaining === 1 ? '' : 's'}`);
              }
              if (item.benchWarning) messages.push(`Sits ${item.maxBenchStreak} straight`);
              return `
                <tr>
                  <td class="fw-semibold">${escapeHTML(item.player)}</td>
                  <td class="text-center">${item.infieldInnings}</td>
                  <td class="text-center">${item.benchInnings}</td>
                  <td>${messages.map(escapeHTML).join(' · ')}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
      <div class="text-muted mt-2">Guidance only — CoachBoard never changes the rotation automatically.</div>
    `;
  }

  function observeRotationMatrix() {
    const container = document.getElementById('rotation-matrix-container');
    if (!container || matrixObserver) return;

    matrixObserver = new MutationObserver(() => {
      window.clearTimeout(renderTimer);
      renderTimer = window.setTimeout(renderGameStatus, 75);
    });
    matrixObserver.observe(container, {childList: true, subtree: true, characterData: true});
  }

  async function initGamePage() {
    try {
      settingsResponse = await fetchSettings();
      if (settingsResponse?.settings?.mode !== 'rules') return;
      ensureGameStatusCard();
      observeRotationMatrix();
      renderGameStatus();
      window.setTimeout(() => {
        observeRotationMatrix();
        renderGameStatus();
      }, 300);
      window.setTimeout(renderGameStatus, 900);
    } catch (error) {
      console.warn('Fair Play Assistant could not load:', error);
    }
  }

  function init() {
    if (isSettingsPage) initSettingsPage();
    if (isGamePage) initGamePage();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();