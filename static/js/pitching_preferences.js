(() => {
  'use strict';

  const path = window.location.pathname;
  const SETTINGS_URL = '/api/pitching-preferences/settings';
  const ARM_CARE_URL = '/api/pitching-preferences/arm-care-summary';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function optionLabel(name) {
    if (name === 'MLB Pitch Smart') return 'MLB Pitch Smart — pitch count / rest guidance';
    if (name === 'USSSA') return 'USSSA — innings / outs';
    if (name === 'Bullpen Tournaments') return 'Bullpen Tournaments — event preset';
    if (name === 'Little League Baseball') return 'Little League Baseball — pitch count / rest';
    return name;
  }

  function badge(status) {
    if (status === 'Available') return '<span class="badge text-bg-success">On Track</span>';
    if (status === 'Pitch Count Incomplete') return '<span class="badge text-bg-warning">Verify Pitch Count</span>';
    if (!status) return '<span class="badge text-bg-light border">No Data</span>';
    return `<span class="badge text-bg-warning">${esc(status)}</span>`;
  }

  async function getJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === 'error') {
      throw new Error(data.message || 'Unable to load pitching settings.');
    }
    return data;
  }

  function showPitchingSettingsTab() {
    if (path !== '/admin/settings' || window.location.hash !== '#pitching-rules-settings') return;
    const link = document.querySelector('a[data-bs-toggle="tab"][href="#pitching-rules-settings"]');
    if (link && typeof bootstrap !== 'undefined') bootstrap.Tab.getOrCreateInstance(link).show();
  }

  function renderAdmin(data) {
    const pane = document.getElementById('pitching-rules-settings');
    if (!pane) return;

    const settings = data.settings || {};
    const competition = settings.competition_default_rule || '';
    const armCare = settings.arm_care_rule_set || '';
    const disabled = data.can_edit ? '' : 'disabled';
    const competitionOptions = (data.competition_options || []).map(name =>
      `<option value="${esc(name)}" ${competition === name ? 'selected' : ''}>${esc(optionLabel(name))}</option>`
    ).join('');
    const armOptions = (data.arm_care_options || []).map(name =>
      `<option value="${esc(name)}" ${armCare === name ? 'selected' : ''}>${esc(optionLabel(name))}</option>`
    ).join('');

    pane.innerHTML = `
      <div class="mb-4">
        <h5 class="mb-1">Pitching Settings</h5>
        <p class="text-muted small mb-0">Tournament eligibility and arm-care guidance are separate. A team default is optional because many teams play under different rules from event to event.</p>
      </div>

      <div class="card border-0 bg-light mb-3">
        <div class="card-body">
          <div class="d-flex gap-2 align-items-start mb-2">
            <i class="bi bi-trophy mt-1"></i>
            <div><strong>Default Competition Rules</strong><div class="small text-muted">Used only as a shortcut. Any game can override this with the tournament or league rules that actually apply.</div></div>
          </div>
          <select class="form-select" id="competitionDefaultRule" ${disabled}>
            <option value="" ${competition ? '' : 'selected'}>No default — choose by event/game</option>
            ${competitionOptions}
          </select>
          <div class="form-text">For teams that play many tournament formats, “No default” is usually the cleanest choice.</div>
        </div>
      </div>

      <div class="card border-0 bg-light mb-3">
        <div class="card-body">
          <div class="d-flex gap-2 align-items-start mb-2">
            <i class="bi bi-heart-pulse mt-1"></i>
            <div><strong>Arm Care Guidance</strong><div class="small text-muted">Independent of tournament eligibility. CoachBoard can keep tracking pitch-count/rest guidance even when the event uses innings or another rule system.</div></div>
          </div>
          <select class="form-select" id="armCareRuleSet" ${disabled}>
            <option value="" ${armCare ? '' : 'selected'}>Off</option>
            ${armOptions}
          </select>
          <div class="form-text">Pitch Smart uses game pitches for its rest guidance. Practice and lesson throws remain visible as workload context rather than being silently treated as official game pitches.</div>
        </div>
      </div>

      <div class="alert alert-light border small">
        <strong>Example:</strong> a USSSA tournament can show a pitcher as <em>USSSA eligible</em> while the separate Pitch Smart arm-care view recommends rest. CoachBoard will show both instead of pretending they are the same rule.
      </div>

      <div id="pitchingPreferencesFeedback" class="small mb-2"></div>
      <button type="button" class="btn btn-primary w-100" id="savePitchingPreferences" ${disabled}>Save Pitching Settings</button>
      ${data.can_edit ? '' : '<div class="form-text mt-2">Only a Head Coach or Super Admin can change these team settings.</div>'}
    `;

    pane.querySelector('#savePitchingPreferences')?.addEventListener('click', async event => {
      const button = event.currentTarget;
      const feedback = pane.querySelector('#pitchingPreferencesFeedback');
      button.disabled = true;
      if (feedback) feedback.textContent = 'Saving…';
      try {
        const saved = await getJson(SETTINGS_URL, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            competition_default_rule: pane.querySelector('#competitionDefaultRule')?.value || '',
            arm_care_rule_set: pane.querySelector('#armCareRuleSet')?.value || '',
          }),
        });
        if (feedback) {
          feedback.className = 'small mb-2 text-success fw-semibold';
          feedback.textContent = saved.message || 'Pitching settings saved.';
        }
      } catch (error) {
        if (feedback) {
          feedback.className = 'small mb-2 text-danger fw-semibold';
          feedback.textContent = error.message;
        }
      } finally {
        button.disabled = !data.can_edit;
      }
    });

    showPitchingSettingsTab();
  }

  function armCell(item, enabled) {
    if (!enabled) return '<span class="text-muted small">Off</span>';
    if (!item) return '<span class="text-muted small">No pitching history</span>';
    const today = item.game_pitches_today == null ? '—' : item.game_pitches_today;
    const max = item.max_daily == null ? '' : ` / ${item.max_daily}`;
    const workload = item.workload_today == null ? '—' : item.workload_today;
    return `
      ${badge(item.status)}
      <div class="small mt-1"><strong>${esc(today)}${esc(max)}</strong> game pitches today</div>
      <div class="small text-muted">${esc(workload)} total throws recorded today</div>
      ${item.status_detail ? `<div class="small text-muted mt-1">${esc(item.status_detail)}</div>` : ''}
    `;
  }

  function renderPitchingDashboard(settingsData, armData) {
    const root = document.querySelector('main > .container-fluid.pb-4');
    if (!root) return;
    const settings = settingsData.settings || {};
    const competition = settings.competition_default_rule;
    const armCare = settings.arm_care_rule_set;

    const head = root.querySelector(':scope > .d-flex:first-child');
    const existing = document.getElementById('pitchingDualRuleSummary');
    if (!existing && head) {
      const summary = document.createElement('div');
      summary.id = 'pitchingDualRuleSummary';
      summary.className = 'card border-0 shadow-sm mb-3';
      summary.innerHTML = `
        <div class="card-body py-3">
          <div class="row g-3">
            <div class="col-md-6"><div class="small text-uppercase fw-bold text-muted">Competition Eligibility</div><div class="fw-bold mt-1">${competition ? esc(competition) : 'Choose per event/game'}</div><div class="small text-muted">${competition ? 'Team default; individual games can override it.' : 'No team default is required.'}</div></div>
            <div class="col-md-6"><div class="small text-uppercase fw-bold text-muted">Arm Care</div><div class="fw-bold mt-1">${armCare ? esc(armCare) : 'Off'}</div><div class="small text-muted">Tracked separately from tournament eligibility.</div></div>
          </div>
        </div>`;
      head.insertAdjacentElement('afterend', summary);
    }

    const rulesButton = head?.querySelector('a.btn');
    if (rulesButton) {
      rulesButton.href = '/admin/settings#pitching-rules-settings';
      rulesButton.textContent = 'Pitching Settings';
    }

    const infoAlert = root.querySelector('.alert.alert-primary');
    if (infoAlert) {
      infoAlert.innerHTML = '<i class="bi bi-info-circle-fill mt-1"></i><div><strong>Competition rules and arm care are intentionally separate.</strong><br><span class="small">Event rules decide tournament eligibility. Your arm-care setting can still track Pitch Smart guidance and throwing workload regardless of the event format. Game-pitch targets are coaching plans, not rule limits.</span></div>';
    }

    const cards = [...root.querySelectorAll('.card')];
    const statusCard = cards.find(card => card.querySelector('h5')?.textContent.trim() === 'Who Can Pitch?');
    const table = statusCard?.querySelector('table');
    if (!table || table.dataset.dualRules === 'true') return;
    table.dataset.dualRules = 'true';

    const subtitle = statusCard.querySelector('.card-header .small.text-muted');
    if (subtitle) subtitle.textContent = 'Competition eligibility and team arm-care guidance are shown separately.';

    const headerRow = table.querySelector('thead tr');
    if (headerRow?.children[1]) {
      const th = document.createElement('th');
      th.textContent = 'Arm Care';
      headerRow.children[1].insertAdjacentElement('afterend', th);
    }

    table.querySelectorAll('tbody tr').forEach(row => {
      const name = row.querySelector('td:first-child .fw-bold')?.textContent.trim();
      if (!name) {
        const onlyCell = row.querySelector('td[colspan]');
        if (onlyCell) onlyCell.colSpan = 6;
        return;
      }

      const officialCell = row.children[1];
      if (!competition && officialCell) {
        officialCell.innerHTML = '<span class="badge text-bg-secondary">Rules Not Selected</span><div class="small text-muted mt-1">Choose the tournament or league rules on the game.</div>';
      }

      const td = document.createElement('td');
      td.style.minWidth = '185px';
      td.innerHTML = armCell((armData.players || {})[name], armData.enabled);
      officialCell?.insertAdjacentElement('afterend', td);
    });
  }

  async function initAdmin() {
    try {
      const data = await getJson(SETTINGS_URL, {cache: 'no-store'});
      renderAdmin(data);
    } catch (error) {
      console.error('Unable to load pitching preferences:', error);
    }
  }

  async function initPitching() {
    try {
      const [settings, arm] = await Promise.all([
        getJson(SETTINGS_URL, {cache: 'no-store'}),
        getJson(ARM_CARE_URL, {cache: 'no-store'}),
      ]);
      renderPitchingDashboard(settings, arm);
    } catch (error) {
      console.error('Unable to load dual pitching guidance:', error);
    }
  }

  function init() {
    if (path === '/admin/settings') initAdmin();
    if (path === '/pitching') initPitching();
  }

  window.addEventListener('hashchange', showPitchingSettingsTab);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
