(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);
  let saving = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if (document.getElementById('game-pitching-rule-picker-styles')) return;
    const style = document.createElement('style');
    style.id = 'game-pitching-rule-picker-styles';
    style.textContent = `
      #game-pitching-rules-v2{border:1px solid #dfe5ec;border-radius:14px;background:#fff;box-shadow:0 2px 7px rgba(16,24,40,.05);margin-bottom:14px;overflow:hidden}
      #game-pitching-rules-v2 .gpr-body{padding:13px 14px}
      #game-pitching-rules-v2 .gpr-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:10px}
      #game-pitching-rules-v2 .gpr-title{font-size:.83rem;font-weight:850;color:#1d2939}
      #game-pitching-rules-v2 .gpr-help{font-size:.68rem;color:#667085;margin-top:2px}
      #game-pitching-rules-v2 .gpr-badge{font-size:.62rem;font-weight:850;border-radius:999px;padding:5px 8px;white-space:nowrap}
      #game-pitching-rules-v2 .gpr-badge.team{background:#eef2f6;color:#475467}
      #game-pitching-rules-v2 .gpr-badge.game{background:#fff4dd;color:#8b5c00}
      #game-pitching-rules-v2 .form-select{min-height:46px;border-radius:10px;font-weight:700}
      #game-pitching-rules-v2 .gpr-current{font-size:.68rem;color:#667085;margin-top:7px}
      @media(max-width:575.98px){#game-pitching-rules-v2 .gpr-body{padding:11px 12px}}
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
    const isLive = Boolean(document.getElementById('liveGameModeToggle')?.checked) || !document.getElementById('live-game-overlay')?.classList.contains('d-none');
    const source = data.source === 'game' ? 'Game override' : 'Team default';
    const options = Array.isArray(data.options) ? data.options : [];
    card.innerHTML = `
      <div class="gpr-body">
        <div class="gpr-head">
          <div>
            <div class="gpr-title">Pitching Rules for This Game</div>
            <div class="gpr-help">Choose the tournament/league rules CoachBoard should use for pitcher eligibility.</div>
          </div>
          <span class="gpr-badge ${data.source === 'game' ? 'game' : 'team'}">${esc(source)}</span>
        </div>
        <select class="form-select" id="game-pitch-rule-select-v2" ${isLive ? 'disabled' : ''}>
          <option value="">Team Default — ${esc(data.team_default || 'Not set')}</option>
          ${options.map(name => `<option value="${esc(name)}" ${data.override === name ? 'selected' : ''}>${esc(name)}</option>`).join('')}
        </select>
        <div class="gpr-current">Effective for this game: <strong>${esc(data.effective || data.team_default || 'Unknown')}</strong>${isLive ? ' · Locked while Live Game is active' : ''}</div>
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
