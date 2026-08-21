(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);
  let saving = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  const RULE_INFO = {
    'MLB Pitch Smart': {
      label: 'Pitch Smart', short: 'Pitch count',
      description: 'MLB / USA Baseball pitch-count limits and required rest guidance based on age.',
      reference: 'MLB Pitch Smart',
    },
    'Bullpen Tournaments': {
      label: 'Bullpen Tournaments', short: 'Event preset',
      description: 'Uses Bullpen’s published event preset and its Pitch Smart arm-care reference. Verify the specific tournament rules when needed.',
      reference: 'Bullpen Tournaments',
    },
    'USSSA': {
      label: 'USSSA', short: 'Innings / outs',
      description: 'Tracks innings and outs pitched across consecutive game days using USSSA youth pitching limits.',
      reference: 'USSSA Baseball',
    },
    'Little League Baseball': {
      label: 'Little League Baseball', short: 'Pitch count',
      description: 'Uses Little League game pitch-count and calendar-day rest rules for supported youth divisions.',
      reference: 'Little League Baseball',
    },
  };

  function infoFor(name) {
    if (!name) {
      return {
        label: 'Competition rules not selected',
        short: 'Choose for this game',
        description: 'Select the tournament or league rules that actually apply to this game. A team default is optional.',
        reference: 'Event / league rules',
      };
    }
    return RULE_INFO[name] || {
      label: name,
      short: name,
      description: 'CoachBoard will apply the configured pitching eligibility rules for this selection.',
      reference: name,
    };
  }

  function optionLabel(name) {
    const info = infoFor(name);
    return `${info.label} — ${info.short}`;
  }

  function armCareConcernMarkup(armData) {
    if (!armData?.enabled) {
      return '<div class="gpr-arm-note text-muted">Arm-care guidance is off for this team.</div>';
    }
    const concerns = Object.entries(armData.players || {}).filter(([, item]) => item.status && item.status !== 'Available');
    if (!concerns.length) {
      return '<div class="gpr-arm-note"><span class="badge text-bg-success me-1">On Track</span>No Pitch Smart rest flags for tracked pitchers.</div>';
    }
    const items = concerns.slice(0, 3).map(([name, item]) =>
      `<div class="gpr-arm-player"><strong>${esc(name)}</strong> — ${esc(item.status)}${item.next_available && item.next_available !== 'Today' ? ` · next ${esc(item.next_available)}` : ''}</div>`
    ).join('');
    const more = concerns.length > 3 ? `<div class="gpr-arm-player text-muted">+${concerns.length - 3} more pitcher${concerns.length - 3 === 1 ? '' : 's'} need attention</div>` : '';
    return items + more;
  }

  function armCardMarkup(item, armData) {
    if (!armData?.enabled) return '<span class="gpa-label">Arm care</span><strong>Off</strong>';
    if (!item) return `<span class="gpa-label">Arm care · ${esc(armData.rule_set || 'Pitch Smart')}</span><strong class="text-muted">No history</strong>`;
    const onTrack = item.status === 'Available';
    return `
      <span class="gpa-label">Arm care · ${esc(armData.rule_set || 'Pitch Smart')}</span>
      <strong>${esc(onTrack ? 'On track' : (item.status || 'Needs attention'))}</strong>
      ${!onTrack && item.next_available && item.next_available !== 'Today' ? `<span class="gpa-next">Rest guidance: ${esc(item.next_available)}</span>` : ''}
      ${!onTrack && item.status_detail ? `<span class="gpa-detail">${esc(item.status_detail)}</span>` : ''}`;
  }

  function installStyles() {
    if (document.getElementById('game-pitching-rule-picker-styles')) return;
    const style = document.createElement('style');
    style.id = 'game-pitching-rule-picker-styles';
    style.textContent = `
      #game-pitching-rules-v2{border:1px solid #dfe5ec;border-radius:12px;background:#fff;box-shadow:0 1px 4px rgba(16,24,40,.04);margin-bottom:14px;overflow:hidden}
      #game-pitching-rules-v2.needs-rule{border-color:#e7bd70}
      #game-pitching-rules-v2 .gpr-summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 11px}
      #game-pitching-rules-v2 .gpr-summary-copy{display:grid;gap:4px;min-width:0}
      #game-pitching-rules-v2 .gpr-line{display:flex;align-items:center;gap:7px;min-width:0;flex-wrap:wrap}
      #game-pitching-rules-v2 .gpr-label{font-size:.62rem;font-weight:850;letter-spacing:.06em;text-transform:uppercase;color:#667085;min-width:82px}
      #game-pitching-rules-v2 .gpr-rule{font-size:.79rem;font-weight:850;color:#1d2939}
      #game-pitching-rules-v2 .gpr-arm{font-size:.73rem;font-weight:750;color:#344054}
      #game-pitching-rules-v2 .gpr-edit{min-height:34px;border-radius:8px;font-size:.7rem;font-weight:800;white-space:nowrap}
      #game-pitching-rules-v2 .gpr-editor{padding:11px;border-top:1px solid #e7ebef;background:#fbfcfd}
      #game-pitching-rules-v2 .gpr-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:9px}
      #game-pitching-rules-v2 .gpr-title{font-size:.78rem;font-weight:850;color:#1d2939}
      #game-pitching-rules-v2 .gpr-help{font-size:.67rem;color:#667085;margin-top:2px;max-width:650px}
      #game-pitching-rules-v2 .gpr-badge{font-size:.61rem;font-weight:850;border-radius:999px;padding:5px 8px;white-space:nowrap}
      #game-pitching-rules-v2 .gpr-badge.team{background:#eef2f6;color:#475467}
      #game-pitching-rules-v2 .gpr-badge.game{background:#fff4dd;color:#8b5c00}
      #game-pitching-rules-v2 .gpr-badge.unselected{background:#fff4dd;color:#8b5c00}
      #game-pitching-rules-v2 .form-select{min-height:44px;border-radius:9px;font-weight:750;color:#1d2939}
      #game-pitching-rules-v2 .gpr-explain{margin-top:9px;padding:9px 10px;border:1px solid #e4e7ec;border-radius:10px;background:#f8fafc}
      #game-pitching-rules-v2 .gpr-explain strong{display:block;font-size:.74rem;color:#344054}
      #game-pitching-rules-v2 .gpr-explain span{display:block;font-size:.67rem;color:#667085;margin-top:2px;line-height:1.35}
      #game-pitching-rules-v2 .gpr-arm-box{margin-top:9px;padding:9px 10px;border:1px solid #e4e7ec;border-radius:10px;background:#fff}
      #game-pitching-rules-v2 .gpr-arm-box-title{font-size:.67rem;text-transform:uppercase;letter-spacing:.05em;font-weight:850;color:#667085;margin-bottom:4px}
      #game-pitching-rules-v2 .gpr-arm-note,#game-pitching-rules-v2 .gpr-arm-player{font-size:.68rem;color:#475467;line-height:1.4}
      #pitcher-availability-card .gpa-source{display:none!important}
      #pitcher-availability-card .gpa-shell{padding:10px;background:#f8f9fb}
      #pitcher-availability-card .gpa-summary{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-bottom:9px;font-size:.67rem;color:#667085}
      #pitcher-availability-card .gpa-summary strong{font-size:.74rem;color:#344054}
      #pitcher-availability-card .gpa-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
      #pitcher-availability-card .gpa-card{border:1px solid #dfe4ea;border-radius:12px;background:#fff;overflow:hidden;min-width:0}
      #pitcher-availability-card .gpa-card.attention{border-color:#ead7b5}
      #pitcher-availability-card .gpa-top{display:flex;justify-content:space-between;gap:8px;align-items:flex-start;padding:10px 11px 7px}
      #pitcher-availability-card .gpa-name{font-weight:850;color:#172033;font-size:.86rem}
      #pitcher-availability-card .gpa-status{font-size:.57rem;font-weight:850;border-radius:999px;padding:4px 7px;white-space:nowrap;background:#e9f7ee;color:#176b38}
      #pitcher-availability-card .gpa-card.attention .gpa-status{background:#fff3d8;color:#8a5800}
      #pitcher-availability-card .gpa-decision{margin:0 10px 8px;padding:8px 9px;border-radius:9px;background:#f7f9fb;border:1px solid #e5e8ed}
      #pitcher-availability-card .gpa-card.attention .gpa-decision{background:#fffaf1;border-color:#ecd9b4}
      #pitcher-availability-card .gpa-label{display:block;font-size:.55rem;text-transform:uppercase;letter-spacing:.06em;font-weight:850;color:#667085}
      #pitcher-availability-card .gpa-decision strong{display:block;font-size:.75rem;color:#1d2939;margin-top:2px}
      #pitcher-availability-card .gpa-metrics{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #edf0f3}
      #pitcher-availability-card .gpa-metric{padding:8px 10px;font-size:.68rem;min-width:0}
      #pitcher-availability-card .gpa-metric+.gpa-metric{border-left:1px solid #edf0f3}
      #pitcher-availability-card .gpa-metric .pitch-limit-progress{max-width:100%}
      #pitcher-availability-card .gpa-arm{padding:8px 10px;border-top:1px solid #edf0f3;background:#fcfcfd}
      #pitcher-availability-card .gpa-arm strong{display:block;font-size:.68rem;color:#344054;margin-top:1px}
      #pitcher-availability-card .gpa-next{display:block;font-size:.61rem;color:#8a5a13;margin-top:2px}
      #pitcher-availability-card .gpa-detail{display:block;font-size:.59rem;color:#7b8492;line-height:1.3;margin-top:3px}
      @media(max-width:575.98px){
        #game-pitching-rules-v2 .gpr-summary{align-items:flex-start}#game-pitching-rules-v2 .gpr-label{min-width:72px}#game-pitching-rules-v2 .gpr-badge{display:none}
        #pitcher-availability-card .gpa-grid{grid-template-columns:1fr}
        #pitcher-availability-card .gpa-shell{padding:8px}
      }
    `;
    document.head.appendChild(style);
  }

  function container() {
    let card = document.getElementById('game-pitching-rules-v2');
    if (card) return card;
    card = document.createElement('div');
    card.id = 'game-pitching-rules-v2';
    const pregame = document.getElementById('pregame-checklist-container');
    const overlay = document.getElementById('live-game-overlay');
    const gameHeading = pregame?.querySelector(':scope > .d-flex:first-child');
    if (gameHeading) gameHeading.insertAdjacentElement('afterend', card);
    else if (pregame) pregame.prepend(card);
    else if (overlay) overlay.prepend(card);
    else document.querySelector('main, .container, .container-fluid')?.prepend(card);
    return card;
  }

  function pregameStatus(row, competitionSelected) {
    if (!competitionSelected) return {label:'Rules not selected', available:false, next:'Select rules for this game'};
    const statusCell = row.children[1];
    const available = Boolean(statusCell?.querySelector('.pitch-status-available'));
    const label = available ? 'Available' : (statusCell?.querySelector('.badge')?.textContent.trim() || statusCell?.textContent.trim() || 'Needs attention');
    const next = row.children[4]?.textContent.trim() || '';
    return {label, available, next};
  }

  function upgradePitcherAvailabilityTable(data, armData) {
    const card = document.getElementById('pitcher-availability-card');
    const wrap = card?.querySelector('.table-responsive');
    const table = wrap?.querySelector('table');
    if (!card || !wrap || !table || card.dataset.gpaV2 === '1') return;
    const competitionSelected = Boolean(data?.effective);
    const rows = [...table.querySelectorAll('tbody tr')].filter(row => row.children.length >= 5);
    if (!rows.length) return;

    const cards = rows.map(row => {
      const name = row.children[0]?.textContent.trim();
      if (!name) return null;
      const status = pregameStatus(row, competitionSelected);
      const official = row.children[2]?.innerHTML || '—';
      const workload = row.children[3]?.innerHTML || '—';
      const armItem = (armData?.players || {})[name];
      const decision = status.available
        ? 'Available by competition rule'
        : (!competitionSelected ? 'Select competition rules for this game' : (status.next && status.next !== 'Today' ? `Can pitch again: ${status.next}` : status.label));
      const article = document.createElement('article');
      article.className = `gpa-card ${status.available ? '' : 'attention'}`;
      article.dataset.playerName = name;
      article.dataset.available = status.available ? 'true' : 'false';
      article.innerHTML = `
        <div class="gpa-top"><div class="gpa-name">${esc(name)}</div><span class="gpa-status">${esc(status.label)}</span></div>
        <div class="gpa-decision"><span class="gpa-label">Competition eligibility</span><strong>${esc(decision)}</strong></div>
        <div class="gpa-arm">${armCardMarkup(armItem, armData)}</div>
        <div class="gpa-metrics">
          <div class="gpa-metric"><span class="gpa-label">Official today</span>${official}</div>
          <div class="gpa-metric"><span class="gpa-label">Throwing workload</span>${workload}</div>
        </div>`;
      return article;
    }).filter(Boolean);

    const availableCount = cards.filter(item => item.dataset.available === 'true').length;
    const attentionCount = cards.length - availableCount;
    const shell = document.createElement('div');
    shell.className = 'gpa-shell';
    shell.innerHTML = `<div class="gpa-summary"><strong>${availableCount} available</strong><span>•</span><strong>${attentionCount} need attention</strong><span>Competition and arm-care guidance remain separate.</span></div><div class="gpa-grid"></div>`;
    const grid = shell.querySelector('.gpa-grid');
    cards.sort((a,b) => Number(b.dataset.available === 'true') - Number(a.dataset.available === 'true')).forEach(item => grid.appendChild(item));
    wrap.classList.add('gpa-source');
    wrap.insertAdjacentElement('beforebegin', shell);
    card.dataset.gpaV2 = '1';
    const subtitle = card.querySelector('.card-header .small.text-muted');
    if (subtitle) subtitle.textContent = 'Can he pitch? If not, the next available day is called out first. Arm-care guidance stays advisory.';
  }

  function render(data, armData) {
    const card = container();
    const toggle = document.getElementById('liveGameModeToggle');
    const overlay = document.getElementById('live-game-overlay');
    const isLive = Boolean(toggle?.checked || (overlay && !overlay.classList.contains('d-none')));
    const options = Array.isArray(data.options) ? data.options : [];
    const teamDefault = data.team_default || null;
    const effective = data.effective || null;
    const effectiveInfo = infoFor(effective);
    const source = data.source === 'game' ? 'Game override' : data.source === 'team' ? 'Team default' : 'Select for game';
    const sourceClass = data.source === 'game' ? 'game' : data.source === 'team' ? 'team' : 'unselected';
    const armCare = data.arm_care_rule_set || null;
    const defaultOption = teamDefault
      ? `Use Team Default — ${optionLabel(teamDefault)}`
      : 'No game rule selected';

    card.classList.toggle('needs-rule', !effective);
    card.innerHTML = `
      <div class="gpr-summary">
        <div class="gpr-summary-copy">
          <div class="gpr-line">
            <span class="gpr-label">Competition</span>
            <span class="gpr-rule">${esc(effectiveInfo.label)}</span>
            <span class="gpr-badge ${sourceClass}">${esc(source)}</span>
          </div>
          <div class="gpr-line">
            <span class="gpr-label">Arm Care</span>
            <span class="gpr-arm">${armCare ? esc(armCare) : 'Off'}</span>
          </div>
        </div>
        <button type="button" class="btn btn-sm ${effective ? 'btn-outline-secondary' : 'btn-outline-warning'} gpr-edit" id="game-pitch-rule-edit-v2" aria-expanded="false" aria-controls="game-pitch-rule-editor-v2" ${isLive ? 'disabled' : ''}>
          ${isLive ? '<i class="bi bi-lock-fill me-1"></i>Locked' : `<i class="bi bi-pencil me-1"></i>${effective ? 'Edit' : 'Select Rules'}`}
        </button>
      </div>
      <div class="gpr-editor" id="game-pitch-rule-editor-v2" hidden>
        <div class="gpr-head">
          <div>
            <div class="gpr-title">Which competition pitching rules apply to this game?</div>
            <div class="gpr-help">Choose the tournament or league rules that determine official eligibility. Arm-care guidance stays separate and does not change when you choose a different event rule.</div>
          </div>
          <span class="gpr-badge ${sourceClass}">${esc(source)}</span>
        </div>
        <select class="form-select" id="game-pitch-rule-select-v2" ${isLive ? 'disabled' : ''} aria-label="Competition pitching rules for this game">
          <option value="" ${data.override ? '' : 'selected'}>${esc(defaultOption)}</option>
          ${options.map(name => `<option value="${esc(name)}" ${data.override === name ? 'selected' : ''}>${esc(optionLabel(name))}</option>`).join('')}
        </select>
        <div class="gpr-explain">
          <strong>${esc(effectiveInfo.label)}</strong>
          <span>${esc(effectiveInfo.description)}</span>
          <span>Competition reference: ${esc(effectiveInfo.reference)}</span>
        </div>
        <div class="gpr-arm-box">
          <div class="gpr-arm-box-title">Separate Arm-Care Check · ${esc(armCare || 'Off')}</div>
          ${armCareConcernMarkup(armData)}
        </div>
      </div>`;

    card.querySelector('#game-pitch-rule-select-v2')?.addEventListener('change', save);
    card.querySelector('#game-pitch-rule-edit-v2')?.addEventListener('click', event => {
      const editor = card.querySelector('#game-pitch-rule-editor-v2');
      if (!editor) return;
      const opening = editor.hidden;
      editor.hidden = !opening;
      event.currentTarget.setAttribute('aria-expanded', opening ? 'true' : 'false');
      event.currentTarget.innerHTML = opening
        ? '<i class="bi bi-chevron-up me-1"></i>Close'
        : `<i class="bi bi-pencil me-1"></i>${effective ? 'Edit' : 'Select Rules'}`;
      if (opening) card.querySelector('#game-pitch-rule-select-v2')?.focus();
    });

    upgradePitcherAvailabilityTable(data, armData);
  }

  async function load() {
    try {
      const [rulesResponse, armResponse] = await Promise.all([
        fetch(`/api/game-day/${gameId}/pitching-rules`, {cache:'no-store'}),
        fetch(`/api/pitching-preferences/arm-care-summary?game_id=${gameId}`, {cache:'no-store'}),
      ]);
      const data = await rulesResponse.json().catch(() => ({}));
      const armData = await armResponse.json().catch(() => ({}));
      if (!rulesResponse.ok || data.status === 'error') throw new Error(data.message || 'Unable to load pitching rules.');
      if (!armResponse.ok || armData.status === 'error') throw new Error(armData.message || 'Unable to load arm-care guidance.');
      render(data, armData);
    } catch (error) {
      console.error('Unable to load game pitching guidance:', error);
    }
  }

  async function save(event) {
    if (saving) return;
    saving = true;
    const select = event.currentTarget;
    select.disabled = true;
    try {
      const response = await fetch(`/api/game-day/${gameId}/pitching-rules`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({rule_set: select.value || ''}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to save pitching rules.');
      window.location.reload();
    } catch (error) {
      window.alert(error.message || 'Unable to save pitching rules.');
      select.disabled = false;
      saving = false;
    }
  }

  installStyles();
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', load, {once:true})
    : load();
})();
