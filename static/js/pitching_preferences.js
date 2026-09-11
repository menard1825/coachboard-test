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

  function isMobilePitching() {
    return window.matchMedia('(max-width: 767.98px)').matches;
  }

  function classifyPitcherCard(card) {
    const status = (card.querySelector('.cb-pitch-status')?.textContent || '').trim().toLowerCase();
    if (status.includes('eligible')) return 'eligible';
    if (status.includes('verify') || status.includes('rules needed')) return 'review';
    return 'unavailable';
  }

  function setPitcherExpanded(card, expanded) {
    card.dataset.mobileExpanded = expanded ? 'true' : 'false';
    const button = card.querySelector('.cb-pitcher-details-toggle');
    if (!button) return;
    button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    const label = button.querySelector('.cb-pitcher-details-label');
    if (label) label.textContent = expanded ? 'Hide details' : 'Details';
    const icon = button.querySelector('i');
    if (icon) icon.className = expanded ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
  }

  function installPitcherCardControls() {
    document.querySelectorAll('.cb-pitcher-card').forEach(card => {
      const group = classifyPitcherCard(card);
      card.dataset.availabilityGroup = group;
      const status = (card.querySelector('.cb-pitch-status')?.textContent || '').trim().toLowerCase();
      if (status.includes('rules needed')) card.dataset.reviewKind = 'rules';

      if (card.querySelector('.cb-pitcher-details-toggle')) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'cb-pitcher-details-toggle';
      button.setAttribute('aria-expanded', 'true');
      button.innerHTML = '<span class="cb-pitcher-details-label">Hide details</span><i class="bi bi-chevron-up"></i>';
      button.addEventListener('click', () => {
        const next = card.dataset.mobileExpanded !== 'true';
        setPitcherExpanded(card, next);
      });

      const arm = card.querySelector('.pitch-arm-care-slot');
      if (arm) arm.insertAdjacentElement('afterend', button);
      else card.querySelector('.cb-pitch-decision')?.insertAdjacentElement('afterend', button);
    });
  }

  function installSummaryFilters() {
    const summary = document.querySelector('.cb-pitch-counts');
    const grid = document.querySelector('.cb-pitch-card-grid');
    if (!summary || !grid || summary.dataset.cbInteractive === '1') return;
    summary.dataset.cbInteractive = '1';

    const groupForLabel = label => {
      const text = label.toLowerCase();
      if (text.includes('eligible')) return 'eligible';
      if (text.includes('unavailable')) return 'unavailable';
      return 'review';
    };

    const filterState = document.createElement('div');
    filterState.className = 'cb-pitch-filter-state';
    filterState.hidden = true;
    filterState.setAttribute('aria-live', 'polite');
    filterState.innerHTML = '<span></span><button type="button">Show all</button>';
    summary.insertAdjacentElement('afterend', filterState);

    const items = [...summary.querySelectorAll('.cb-pitch-summary-item')];
    items.forEach(item => {
      const group = groupForLabel(item.querySelector('span')?.textContent || '');
      const count = Number(item.querySelector('strong')?.textContent || 0);
      item.dataset.cbPitchFilter = group;
      item.setAttribute('role', 'button');
      item.setAttribute('tabindex', count > 0 ? '0' : '-1');
      item.setAttribute('aria-pressed', 'false');
      if (count <= 0) item.setAttribute('aria-disabled', 'true');
    });

    const applyFilter = group => {
      const cards = [...grid.querySelectorAll('.cb-pitcher-card')];
      const activeItem = items.find(item => item.dataset.cbPitchFilter === group);
      const alreadyActive = activeItem?.getAttribute('aria-pressed') === 'true';
      const effectiveGroup = alreadyActive ? 'all' : group;

      items.forEach(item => item.setAttribute('aria-pressed', item.dataset.cbPitchFilter === effectiveGroup ? 'true' : 'false'));
      const visible = [];
      cards.forEach(card => {
        const show = effectiveGroup === 'all' || card.dataset.availabilityGroup === effectiveGroup;
        card.hidden = !show;
        if (show) visible.push(card);
      });

      if (effectiveGroup === 'all') {
        filterState.hidden = true;
      } else {
        const label = effectiveGroup === 'eligible' ? 'eligible' : effectiveGroup === 'unavailable' ? 'unavailable' : 'needing review';
        filterState.querySelector('span').textContent = `Showing ${visible.length} ${label}`;
        filterState.hidden = false;
        if (isMobilePitching() && visible.length === 1) setPitcherExpanded(visible[0], true);
        window.requestAnimationFrame(() => grid.scrollIntoView({behavior: 'smooth', block: 'start'}));
      }
    };

    items.forEach(item => {
      const activate = () => {
        if (item.getAttribute('aria-disabled') === 'true') return;
        applyFilter(item.dataset.cbPitchFilter);
      };
      item.addEventListener('click', activate);
      item.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        activate();
      });
    });

    filterState.querySelector('button')?.addEventListener('click', () => {
      items.forEach(item => item.setAttribute('aria-pressed', 'false'));
      grid.querySelectorAll('.cb-pitcher-card').forEach(card => { card.hidden = false; });
      filterState.hidden = true;
    });
  }

  function installMobileSectionToggles() {
    const sections = [
      {card: document.getElementById('pitchTargetsCard'), label: 'Pitch Targets'},
      {card: document.getElementById('newPitchingOutingForm')?.closest('.cb-pitch-section-card'), label: 'Record Throwing', className: 'cb-pitch-record-card'},
      {card: document.getElementById('pitchHistoryCard'), label: 'Recent Throwing History'},
    ].filter(item => item.card);

    sections.forEach(({card, label, className}) => {
      if (className) card.classList.add(className);
      if (card.querySelector(':scope > .card-header .cb-pitch-section-toggle')) return;
      const header = card.querySelector(':scope > .card-header');
      if (!header) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'cb-pitch-section-toggle';
      button.setAttribute('aria-expanded', 'true');
      button.setAttribute('aria-label', `Collapse ${label}`);
      button.innerHTML = '<i class="bi bi-chevron-up"></i>';
      button.addEventListener('click', () => {
        const collapsed = card.dataset.mobileCollapsed !== 'true';
        card.dataset.mobileCollapsed = collapsed ? 'true' : 'false';
        button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        button.setAttribute('aria-label', `${collapsed ? 'Expand' : 'Collapse'} ${label}`);
        button.querySelector('i').className = collapsed ? 'bi bi-chevron-down' : 'bi bi-chevron-up';
      });
      header.appendChild(button);
    });
  }

  function installPitchingFocusUX() {
    const root = document.querySelector('.cb-pitching-v3');
    if (!root || root.dataset.cbFocusUx === '1') return;
    root.dataset.cbFocusUx = '1';

    installPitcherCardControls();
    installSummaryFilters();
    installMobileSectionToggles();

    let lastMobile = null;
    const applyResponsiveMode = () => {
      const mobile = isMobilePitching();
      if (mobile === lastMobile) return;
      lastMobile = mobile;

      document.querySelectorAll('.cb-pitcher-card').forEach(card => setPitcherExpanded(card, !mobile));
      document.querySelectorAll('#pitchTargetsCard, .cb-pitch-record-card, #pitchHistoryCard').forEach(card => {
        card.dataset.mobileCollapsed = mobile ? 'true' : 'false';
        const button = card.querySelector(':scope > .card-header .cb-pitch-section-toggle');
        if (!button) return;
        button.setAttribute('aria-expanded', mobile ? 'false' : 'true');
        const label = card.id === 'pitchTargetsCard' ? 'Pitch Targets' : card.id === 'pitchHistoryCard' ? 'Recent Throwing History' : 'Record Throwing';
        button.setAttribute('aria-label', `${mobile ? 'Expand' : 'Collapse'} ${label}`);
        const icon = button.querySelector('i');
        if (icon) icon.className = mobile ? 'bi bi-chevron-down' : 'bi bi-chevron-up';
      });
    };

    applyResponsiveMode();
    window.addEventListener('resize', applyResponsiveMode, {passive: true});
  }

  async function initAdmin() {
    try {
      renderAdmin(await getJson(SETTINGS_URL, {cache: 'no-store'}));
    } catch (error) {
      console.error('Unable to load pitching preferences:', error);
    }
  }

  async function initPitching() {
    installPitchingFocusUX();
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