(() => {
  'use strict';

  if (window.location.pathname !== '/game-day') return;

  let optionsConfig = null;
  const gameRuleCache = new Map();
  let loadingOptions = false;

  function installStyles() {
    if (document.getElementById('game-day-pitching-rules-styles')) return;
    const style = document.createElement('style');
    style.id = 'game-day-pitching-rules-styles';
    style.textContent = `
      .gd-rule-meta{font-size:.65rem;color:#667085;font-weight:700}
      .gd-rule-meta.override{color:#8b5c00}
      #gd-add-pitching-rules{min-height:46px;border-radius:10px}
      .gd-rule-help{font-size:.66rem;color:#667085;margin-top:4px}
    `;
    document.head.appendChild(style);
  }

  async function loadOptions() {
    if (optionsConfig || loadingOptions) return optionsConfig;
    loadingOptions = true;
    try {
      const response = await fetch('/api/game-day/pitching-rule-options', {cache:'no-store'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to load pitching rules.');
      optionsConfig = data;
      patchAddGameModal();
      return data;
    } catch (error) {
      console.error('Unable to load Game Day pitching rule options:', error);
      return null;
    } finally {
      loadingOptions = false;
    }
  }

  function patchAddGameModal() {
    const modal = document.getElementById('game-day-add-modal');
    if (!modal || modal.querySelector('#gd-add-pitching-rules') || !optionsConfig) return;

    const notes = modal.querySelector('#gd-add-notes')?.closest('.col-12');
    const field = document.createElement('div');
    field.className = 'col-12';
    field.innerHTML = `
      <label class="form-label" for="gd-add-pitching-rules">Pitching Rules</label>
      <select class="form-select" id="gd-add-pitching-rules" name="pitching_rule_set">
        <option value="">Team Default — ${optionsConfig.team_default || 'Not set'}</option>
        ${(optionsConfig.options || []).map(name => `<option value="${name}">${name}</option>`).join('')}
      </select>
      <div class="gd-rule-help">Only override this when the tournament or league uses different pitching rules.</div>`;
    if (notes?.parentNode) notes.parentNode.insertBefore(field, notes);
    else modal.querySelector('.modal-body .row')?.appendChild(field);
  }

  async function rulesForGame(gameId) {
    if (gameRuleCache.has(gameId)) return gameRuleCache.get(gameId);
    try {
      const response = await fetch(`/api/game-day/${gameId}/pitching-rules`, {cache:'no-store'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') return null;
      gameRuleCache.set(gameId, data);
      return data;
    } catch (_) {
      return null;
    }
  }

  async function decorateGameCard(card) {
    if (card.dataset.pitchingRulesDecorated === '1') return;
    const gameId = Number(card.dataset.gameId || 0);
    if (!gameId) return;
    card.dataset.pitchingRulesDecorated = '1';
    const data = await rulesForGame(gameId);
    const meta = card.querySelector('.gd-meta');
    if (!data || !meta || meta.querySelector('.gd-rule-meta')) return;
    const span = document.createElement('span');
    span.className = `gd-rule-meta ${data.source === 'game' ? 'override' : ''}`;
    span.textContent = `Pitching: ${data.effective}${data.source === 'game' ? ' · override' : ''}`;
    meta.appendChild(span);
  }

  async function decorateScheduleRow(row) {
    if (row.dataset.pitchingRulesDecorated === '1') return;
    const gameId = Number(row.dataset.gameId || 0);
    if (!gameId) return;
    row.dataset.pitchingRulesDecorated = '1';
    const data = await rulesForGame(gameId);
    if (!data) return;
    let detail = row.querySelector('.gd-up-loc');
    if (!detail) {
      detail = document.createElement('div');
      detail.className = 'gd-up-loc';
      row.querySelector('.gd-up-name')?.parentElement?.appendChild(detail);
    }
    if (detail && !detail.querySelector('.gd-rule-meta')) {
      const existing = detail.textContent.trim();
      detail.innerHTML = `${existing ? `${existing} · ` : ''}<span class="gd-rule-meta ${data.source === 'game' ? 'override' : ''}">Pitching: ${data.effective}${data.source === 'game' ? ' · override' : ''}</span>`;
    }
  }

  function patchVisible() {
    patchAddGameModal();
    document.querySelectorAll('.gd-game[data-game-id]').forEach(decorateGameCard);
    document.querySelectorAll('.gd-up-row[data-game-id]').forEach(decorateScheduleRow);
  }

  installStyles();
  const observer = new MutationObserver(() => window.requestAnimationFrame(patchVisible));
  const start = () => {
    observer.observe(document.body, {childList:true, subtree:true});
    loadOptions();
    patchVisible();
  };
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once:true})
    : start();
})();
