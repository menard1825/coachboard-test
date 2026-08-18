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
      label: 'Pitch Count Limits',
      short: 'Pitch count',
      description: 'Tracks pitches thrown and required rest before the pitcher can throw again.',
      reference: 'MLB Pitch Smart',
    },
    'USSSA': {
      label: 'Innings Limits',
      short: 'Innings',
      description: 'Tracks innings and outs pitched across game days.',
      reference: 'USSSA',
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
    return `${info.label} — ${info.reference}`;
  }

  function installStyles() {
    if (document.getElementById('game-pitching-rule-picker-styles')) return;
    const style = document.createElement('style');
    style.id = 'game-pitching-rule-picker-styles';
    style.textContent = `
      #game-pitching-rules-v2{border:1px solid #dfe5ec;border-radius:14px;background:#fff;box-shadow:0 2px 7px rgba(16,24,40,.05);margin-bottom:14px;overflow:hidden}
      #game-pitching-rules-v2 .gpr-body{padding:13px 14px}
      #game-pitching-rules-v2 .gpr-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:10px}
      #game-pitching-rules-v2 .gpr-title{font-size:.83rem;font-weight:850;color:#1d2939}
      #game-pitching-rules-v2 .gpr-help{font-size:.68rem;color:#667085;margin-top:2px;max-width:620px}
      #game-pitching-rules-v2 .gpr-badge{font-size:.62rem;font-weight:850;border-radius:999px;padding:5px 8px;white-space:nowrap}
      #game-pitching-rules-v2 .gpr-badge.team{background:#eef2f6;color:#475467}
      #game-pitching-rules-v2 .gpr-badge.game{background:#fff4dd;color:#8b5c00}
      #game-pitching-rules-v2 .form-select{min-height:48px;border-radius:10px;font-weight:750;color:#1d2939}
      #game-pitching-rules-v2 .gpr-explain{margin-top:9px;padding:9px 10px;border:1px solid #e4e7ec;border-radius:10px;background:#f8fafc}
      #game-pitching-rules-v2 .gpr-explain strong{display:block;font-size:.74rem;color:#344054}
      #game-pitching-rules-v2 .gpr-explain span{display:block;font-size:.67rem;color:#667085;margin-top:2px;line-height:1.35}
      #game-pitching-rules-v2 .gpr-ref{font-size:.63rem!important;color:#8a94a3!important;margin-top:4px!important}
      #game-pitching-rules-v2 .gpr-current{font-size:.67rem;color:#667085;margin-top:7px}
      @media(max-width:575.98px){#game-pitching-rules-v2 .gpr-body{padding:11px 12px}.gpr-badge{display:none}}
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
    if (pregame) pregame.insertBefore(card, pregame.firstChild);
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
      <div class="gpr-body">
        <div class="gpr-head">
          <div>
            <div class="gpr-title">How are pitchers limited in this game?</div>
            <div class="gpr-help">Choose what this tournament or league uses. You usually only need to change this when an event uses different rules than your team default.</div>
          </div>
          <span class="gpr-badge ${data.source === 'game' ? 'game' : 'team'}">${esc(source)}</span>
        </div>
        <select class="form-select" id="game-pitch-rule-select-v2" ${isLive ? 'disabled' : ''} aria-label="Pitcher limit type for this game">
          <option value="">Use Team Default — ${esc(defaultInfo.label)}</option>
          ${options.map(name => `<option value="${esc(name)}" ${data.override === name ? 'selected' : ''}>${esc(optionLabel(name))}</option>`).join('')}
        </select>
        <div class="gpr-explain">
          <strong>${esc(effectiveInfo.label)}</strong>
          <span>${esc(effectiveInfo.description)}</span>
          <span class="gpr-ref">Rule reference: ${esc(effectiveInfo.reference)}</span>
        </div>
        <div class="gpr-current">CoachBoard is using <strong>${esc(effectiveInfo.short)}</strong> rules for this game${isLive ? ' · Locked while Live Game is active' : ''}.</div>
      </div>`;

    card.querySelector('#game-pitch-rule-select-v2')?.addEventListener('change', save);
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
