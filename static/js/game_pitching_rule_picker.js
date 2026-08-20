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
      label: 'Pitch Smart',
      short: 'Pitch count',
      description: 'MLB / USA Baseball pitch-count limits and required rest guidance based on age.',
      reference: 'MLB Pitch Smart',
    },
    'Bullpen Tournaments': {
      label: 'Bullpen Tournaments',
      short: 'Pitch Smart guidance',
      description: 'Uses Bullpen’s published USA Baseball / MLB Pitch Smart arm-care guidelines. Bullpen notes these are guidance rather than tournament-policed pitching restrictions.',
      reference: 'Bullpen Tournaments',
    },
    'USSSA': {
      label: 'USSSA',
      short: 'Innings / outs',
      description: 'Tracks innings and outs pitched across consecutive game days using USSSA youth pitching limits.',
      reference: 'USSSA Baseball',
    },
    'Little League Baseball': {
      label: 'Little League Baseball',
      short: 'Pitch count',
      description: 'Uses Little League game pitch-count and calendar-day rest rules for 12U and younger. Older divisions should verify division-specific rules.',
      reference: 'Little League Baseball',
    },
  };

  function infoFor(name) {
    return RULE_INFO[name] || {
      label: name || 'Unknown rule type',
      short: name || 'Unknown',
      description: 'CoachBoard will apply the configured pitching eligibility rules for this selection.',
      reference: name || 'Unknown',
    };
  }

  function optionLabel(name) {
    const info = infoFor(name);
    return `${info.label} — ${info.short}`;
  }

  function installStyles() {
    if (document.getElementById('game-pitching-rule-picker-styles')) return;
    const style = document.createElement('style');
    style.id = 'game-pitching-rule-picker-styles';
    style.textContent = `
      #game-pitching-rules-v2{border:1px solid #dfe5ec;border-radius:12px;background:#fff;box-shadow:0 1px 4px rgba(16,24,40,.04);margin-bottom:14px;overflow:hidden}
      #game-pitching-rules-v2 .gpr-summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 11px}
      #game-pitching-rules-v2 .gpr-summary-copy{display:flex;align-items:center;gap:7px;min-width:0;flex-wrap:wrap}
      #game-pitching-rules-v2 .gpr-label{font-size:.64rem;font-weight:850;letter-spacing:.06em;text-transform:uppercase;color:#667085}
      #game-pitching-rules-v2 .gpr-rule{font-size:.8rem;font-weight:850;color:#1d2939}
      #game-pitching-rules-v2 .gpr-edit{min-height:34px;border-radius:8px;font-size:.7rem;font-weight:800;white-space:nowrap}
      #game-pitching-rules-v2 .gpr-editor{padding:11px;border-top:1px solid #e7ebef;background:#fbfcfd}
      #game-pitching-rules-v2 .gpr-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:9px}
      #game-pitching-rules-v2 .gpr-title{font-size:.78rem;font-weight:850;color:#1d2939}
      #game-pitching-rules-v2 .gpr-help{font-size:.67rem;color:#667085;margin-top:2px;max-width:620px}
      #game-pitching-rules-v2 .gpr-badge{font-size:.62rem;font-weight:850;border-radius:999px;padding:5px 8px;white-space:nowrap}
      #game-pitching-rules-v2 .gpr-badge.team{background:#eef2f6;color:#475467}
      #game-pitching-rules-v2 .gpr-badge.game{background:#fff4dd;color:#8b5c00}
      #game-pitching-rules-v2 .form-select{min-height:44px;border-radius:9px;font-weight:750;color:#1d2939}
      #game-pitching-rules-v2 .gpr-explain{margin-top:9px;padding:9px 10px;border:1px solid #e4e7ec;border-radius:10px;background:#f8fafc}
      #game-pitching-rules-v2 .gpr-explain strong{display:block;font-size:.74rem;color:#344054}
      #game-pitching-rules-v2 .gpr-explain span{display:block;font-size:.67rem;color:#667085;margin-top:2px;line-height:1.35}
      #game-pitching-rules-v2 .gpr-ref{font-size:.63rem!important;color:#8a94a3!important;margin-top:4px!important}
      @media(max-width:575.98px){#game-pitching-rules-v2 .gpr-summary{padding:9px 10px}#game-pitching-rules-v2 .gpr-label{width:100%}#game-pitching-rules-v2 .gpr-badge{display:none}}
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

  function render(data) {
    const card = container();
    const toggle = document.getElementById('liveGameModeToggle');
    const overlay = document.getElementById('live-game-overlay');
    const isLive = Boolean(toggle?.checked || (overlay && !overlay.classList.contains('d-none')));
    const source = data.source === 'game' ? 'Game override' : 'Team default';
    const options = Array.isArray(data.options) ? data.options : [];
    const teamDefault = data.team_default || 'MLB Pitch Smart';
    const effective = data.effective || teamDefault;
    const effectiveInfo = infoFor(effective);
    const defaultInfo = infoFor(teamDefault);

    card.innerHTML = `
      <div class="gpr-summary">
        <div class="gpr-summary-copy">
          <span class="gpr-label">Pitching rule</span>
          <span class="gpr-rule">${esc(effectiveInfo.label)}</span>
          <span class="gpr-badge ${data.source === 'game' ? 'game' : 'team'}">${esc(source)}</span>
        </div>
        <button type="button" class="btn btn-sm btn-outline-secondary gpr-edit" id="game-pitch-rule-edit-v2" aria-expanded="false" aria-controls="game-pitch-rule-editor-v2" ${isLive ? 'disabled' : ''}>
          ${isLive ? '<i class="bi bi-lock-fill me-1"></i>Locked' : '<i class="bi bi-pencil me-1"></i>Edit'}
        </button>
      </div>
      <div class="gpr-editor" id="game-pitch-rule-editor-v2" hidden>
        <div class="gpr-head">
          <div>
            <div class="gpr-title">Which pitching rules apply to this game?</div>
            <div class="gpr-help">Choose the tournament or league preset. You normally only change this when an event uses different rules than your team default.</div>
          </div>
          <span class="gpr-badge ${data.source === 'game' ? 'game' : 'team'}">${esc(source)}</span>
        </div>
        <select class="form-select" id="game-pitch-rule-select-v2" ${isLive ? 'disabled' : ''} aria-label="Pitching rules for this game">
          <option value="">Use Team Default — ${esc(defaultInfo.label)}</option>
          ${options.map(name => `<option value="${esc(name)}" ${data.override === name ? 'selected' : ''}>${esc(optionLabel(name))}</option>`).join('')}
        </select>
        <div class="gpr-explain">
          <strong>${esc(effectiveInfo.label)}</strong>
          <span>${esc(effectiveInfo.description)}</span>
          <span class="gpr-ref">Rule reference: ${esc(effectiveInfo.reference)}</span>
        </div>
      </div>`;

    card.querySelector('#game-pitch-rule-select-v2')?.addEventListener('change', save);
    card.querySelector('#game-pitch-rule-edit-v2')?.addEventListener('click', (event) => {
      const editor = card.querySelector('#game-pitch-rule-editor-v2');
      if (!editor) return;
      const opening = editor.hidden;
      editor.hidden = !opening;
      event.currentTarget.setAttribute('aria-expanded', opening ? 'true' : 'false');
      event.currentTarget.innerHTML = opening
        ? '<i class="bi bi-chevron-up me-1"></i>Close'
        : '<i class="bi bi-pencil me-1"></i>Edit';
      if (opening) card.querySelector('#game-pitch-rule-select-v2')?.focus();
    });
  }

  async function load() {
    try {
      const response = await fetch(`/api/game-day/${gameId}/pitching-rules`, {cache:'no-store'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to load pitching rules.');
      render(data);
    } catch (error) {
      console.error('Unable to load game pitching rules:', error);
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
