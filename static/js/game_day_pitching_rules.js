(() => {
  'use strict';

  if (window.location.pathname !== '/game-day') return;

  let optionsConfig = null;
  let loadingOptions = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  const RULE_INFO = {
    'MLB Pitch Smart': {
      label: 'Pitch Count Limits',
      description: 'Tracks pitches thrown and required rest.',
      reference: 'MLB Pitch Smart',
    },
    'USSSA': {
      label: 'Innings Limits',
      description: 'Tracks innings and outs pitched across game days.',
      reference: 'USSSA',
    },
  };

  function infoFor(name) {
    return RULE_INFO[name] || {
      label: name || 'Pitching limits',
      description: 'Uses the configured pitching eligibility rules.',
      reference: name || 'Team rules',
    };
  }

  function optionLabel(name) {
    const info = infoFor(name);
    return `${info.label} — ${info.reference}`;
  }

  function installStyles() {
    if (document.getElementById('game-day-pitching-rules-styles')) return;
    const style = document.createElement('style');
    style.id = 'game-day-pitching-rules-styles';
    style.textContent = `
      #gd-add-pitching-rules{min-height:46px;border-radius:10px;font-weight:700}
      .gd-rule-help{font-size:.66rem;color:#667085;margin-top:4px;line-height:1.35}
      .gd-rule-explain{margin-top:7px;padding:8px 9px;border:1px solid #e4e7ec;border-radius:9px;background:#f8fafc}
      .gd-rule-explain strong{display:block;font-size:.7rem;color:#344054}
      .gd-rule-explain span{display:block;font-size:.64rem;color:#667085;margin-top:2px}
      .gd-rule-explain .gd-rule-ref{color:#8a94a3}
    `;
    document.head.appendChild(style);
  }

  function updateAddGameExplanation(field) {
    const select = field?.querySelector('#gd-add-pitching-rules');
    const explain = field?.querySelector('.gd-rule-explain');
    if (!select || !explain || !optionsConfig) return;
    const selectedName = select.value || optionsConfig.team_default || 'MLB Pitch Smart';
    const info = infoFor(selectedName);
    explain.innerHTML = `
      <strong>${esc(info.label)}</strong>
      <span>${esc(info.description)}</span>
      <span class="gd-rule-ref">Rule reference: ${esc(info.reference)}</span>`;
  }

  function patchAddGameModal() {
    const modal = document.getElementById('game-day-add-modal');
    if (!modal || modal.querySelector('#gd-add-pitching-rules') || !optionsConfig) return;

    const notes = modal.querySelector('#gd-add-notes')?.closest('.col-12');
    const field = document.createElement('div');
    field.className = 'col-12';
    const defaultInfo = infoFor(optionsConfig.team_default || 'MLB Pitch Smart');
    field.innerHTML = `
      <label class="form-label" for="gd-add-pitching-rules">How are pitchers limited?</label>
      <select class="form-select" id="gd-add-pitching-rules" name="pitching_rule_set">
        <option value="">Use Team Default — ${esc(defaultInfo.label)}</option>
        ${(optionsConfig.options || []).map(name => `<option value="${esc(name)}">${esc(optionLabel(name))}</option>`).join('')}
      </select>
      <div class="gd-rule-help">Most games can stay on Team Default. Change this only when the tournament or league uses a different type of pitching limit.</div>
      <div class="gd-rule-explain"></div>`;
    if (notes?.parentNode) notes.parentNode.insertBefore(field, notes);
    else modal.querySelector('.modal-body .row')?.appendChild(field);

    field.querySelector('#gd-add-pitching-rules')?.addEventListener('change', () => updateAddGameExplanation(field));
    updateAddGameExplanation(field);
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

  function start() {
    installStyles();
    loadOptions();
    document.addEventListener('shown.bs.modal', event => {
      if (event.target?.id === 'game-day-add-modal') patchAddGameModal();
    });
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once:true})
    : start();
})();
