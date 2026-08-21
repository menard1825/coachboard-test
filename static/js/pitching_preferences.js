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

  async function getJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to load pitching settings.');
    return data;
  }

  function showPitchingSettingsTab() {
    if (path !== '/admin/settings' || window.location.hash !== '#pitching-rules-settings') return;
    const link = document.querySelector('a[data-bs-toggle="tab"][href="#pitching-rules-settings"]');
    if (link && typeof bootstrap !== 'undefined') bootstrap.Tab.getOrCreateInstance(link).show();
  }

  function polishAdminSaveButtons() {
    if (path !== '/admin/settings') return;
    const general = document.querySelector('#general-settings form button[type="submit"]');
    const appearance = document.querySelector('#appearance-settings form button[type="submit"]');
    if (general) general.textContent = 'Save General Settings';
    if (appearance) appearance.textContent = 'Save Team Colors';
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
        <p class="text-muted small mb-0">Competition rules determine official eligibility. Arm-care guidance is separate.</p>
      </div>
      <div class="card border-0 bg-light mb-3">
        <div class="card-body">
          <div class="d-flex gap-2 align-items-start mb-2">
            <i class="bi bi-trophy mt-1"></i>
            <div><strong>Default Competition Rules</strong><div class="small text-muted">Used as a team default. Any game can use different tournament or league rules.</div></div>
          </div>
          <select class="form-select" id="competitionDefaultRule" ${disabled}>
            <option value="" ${competition ? '' : 'selected'}>No default — choose by event/game</option>
            ${competitionOptions}
          </select>
          <div class="form-text">Use No Default when competition rules vary by event.</div>
        </div>
      </div>
      <div class="card border-0 bg-light mb-3">
        <div class="card-body">
          <div class="d-flex gap-2 align-items-start mb-2">
            <i class="bi bi-heart-pulse mt-1"></i>
            <div><strong>Arm Care Guidance</strong><div class="small text-muted">Independent workload and rest guidance.</div></div>
          </div>
          <select class="form-select" id="armCareRuleSet" ${disabled}>
            <option value="" ${armCare ? '' : 'selected'}>Off</option>
            ${armOptions}
          </select>
          <div class="form-text">Pitch Smart uses game pitches for rest guidance. Practice and lesson throwing remains visible as workload.</div>
        </div>
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
          headers: {'Content-Type':'application/json'},
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

  function armCard(item, enabled, ruleSet) {
    if (!enabled) {
      return '<div class="cb-pitch-arm-row"><span class="cb-pitch-arm-title">Arm Care</span><span class="cb-pitch-arm-value">Off</span></div>';
    }
    if (!item) {
      return `<div class="cb-pitch-arm-row"><span class="cb-pitch-arm-title">Arm Care · ${esc(ruleSet || 'Pitch Smart')}</span><span class="cb-pitch-arm-value text-muted">No History</span></div>`;
    }
    const available = item.status === 'Available';
    const value = available ? 'No Rest Required' : 'Rest Recommended';
    const next = !available && item.next_available && item.next_available !== 'Today'
      ? `<div class="cb-pitch-arm-next">Rest guidance: ${esc(item.next_available)}</div>` : '';
    const detail = !available && item.status_detail
      ? `<div class="cb-pitch-arm-detail">${esc(item.status_detail)}</div>` : '';
    return `
      <div class="cb-pitch-arm-row">
        <span class="cb-pitch-arm-title">Arm Care · ${esc(ruleSet || 'Pitch Smart')}</span>
        <span class="cb-pitch-arm-value">${esc(value)}</span>
      </div>${next}${detail}`;
  }

  function renderPitchingRuleStrip(settingsData, armData) {
    const settings = settingsData.settings || {};
    const competition = settings.competition_default_rule || '';
    const armCare = settings.arm_care_rule_set || '';
    const competitionName = document.getElementById('pitchingCompetitionName');
    const competitionNote = document.getElementById('pitchingCompetitionNote');
    const armName = document.getElementById('pitchingArmCareName');
    const armNote = document.getElementById('pitchingArmCareNote');

    if (competitionName) competitionName.textContent = competition || 'Select per game';
    if (competitionNote) {
      competitionNote.textContent = competition
        ? 'Team default; individual games can use different rules.'
        : 'No team default. Select event rules on each game.';
    }
    if (armName) armName.textContent = armCare || 'Off';
    if (armNote) armNote.textContent = armCare ? 'Advisory workload and rest guidance.' : 'No arm-care rule set selected.';

    document.querySelectorAll('.pitch-arm-care-slot[data-player-name]').forEach(slot => {
      const item = (armData.players || {})[slot.dataset.playerName];
      slot.innerHTML = armCard(item, Boolean(armData.enabled), armData.rule_set || armCare);
    });
  }

  async function initAdmin() {
    try {
      renderAdmin(await getJson(SETTINGS_URL, {cache: 'no-store'}));
    } catch (error) {
      console.error('Unable to load pitching preferences:', error);
    }
  }

  async function initPitching() {
    try {
      const settings = await getJson(SETTINGS_URL, {cache: 'no-store'});
      let arm = {enabled: false, rule_set: settings.settings?.arm_care_rule_set || '', players: {}};
      try {
        arm = await getJson(ARM_CARE_URL, {cache: 'no-store'});
      } catch (error) {
        console.error('Unable to load arm-care summary:', error);
      }
      renderPitchingRuleStrip(settings, arm);
      document.dispatchEvent(new CustomEvent('coachboard:pitching-preferences-ready'));
    } catch (error) {
      console.error('Unable to load pitching preferences:', error);
      document.querySelectorAll('.pitch-arm-care-slot').forEach(slot => {
        slot.innerHTML = '<div class="cb-pitch-arm-row"><span class="cb-pitch-arm-title">Arm Care</span><span class="cb-pitch-arm-value text-muted">Unavailable</span></div>';
      });
    }
  }

  function init() {
    if (path === '/admin/settings') {
      polishAdminSaveButtons();
      initAdmin();
    }
    if (path === '/pitching') initPitching();
  }

  window.addEventListener('hashchange', showPitchingSettingsTab);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
