(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const PREFIX = 'DEFENSE PRESET — ';
  const PANEL_ID = 'pregame-defense-editor-v3';
  const STYLE_ID = 'cb-starting-defense-scope-styles';
  let findingObserver = null;
  let panelObserver = null;
  let applying = false;

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${PANEL_ID} .pde-tools.cb-starting-defense-tools{
        grid-template-columns:minmax(190px,1fr) auto auto auto;
      }
      #${PANEL_ID} #pde-apply-game{font-weight:800;white-space:nowrap}
      #${PANEL_ID} .cb-starting-defense-help{
        margin:-4px 0 11px;
        padding:8px 10px;
        border:1px solid #d9e2f2;
        border-radius:9px;
        background:#f7f9fd;
        color:#526176;
        font-size:.67rem;
        line-height:1.35;
      }
      #${PANEL_ID} .cb-starting-defense-help strong{color:#294a84}
      @media(max-width:767.98px){
        #${PANEL_ID} .pde-tools.cb-starting-defense-tools{grid-template-columns:1fr 1fr}
        #${PANEL_ID} .pde-tools.cb-starting-defense-tools select{grid-column:1/-1}
        #${PANEL_ID} .pde-tools.cb-starting-defense-tools #pde-save{grid-column:1/-1}
      }
    `;
    document.head.appendChild(style);
  }

  function presetLabel(template) {
    const title = String(template?.title || '').trim();
    return title.startsWith(PREFIX) ? title.slice(PREFIX.length).trim() : null;
  }

  function parseInnings(value) {
    if (value && typeof value === 'object') return {...value};
    if (typeof value === 'string') {
      try {
        const parsed = JSON.parse(value);
        return parsed && typeof parsed === 'object' ? parsed : {};
      } catch (_) {
        return {};
      }
    }
    return {};
  }

  function wholeInningKeys(innings) {
    return Object.keys(innings || {})
      .filter(key => /^\d+$/.test(String(key)))
      .sort((a, b) => Number(a) - Number(b));
  }

  function positionsFor(data) {
    return Number(data?.outfielder_count) === 4
      ? ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'LCF', 'RCF', 'RF']
      : ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'];
  }

  function selectedPreset(data, selectedId) {
    return (data?.rotation_templates || []).find(template =>
      String(template.id) === String(selectedId) && presetLabel(template)
    );
  }

  async function fetchGameData() {
    const response = await fetch(`/api/game_data/${gameId}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`Unable to load game defense (${response.status}).`);
    return response.json();
  }

  async function saveRotation(data, innings) {
    const rotation = data.rotation || {};
    const response = await fetch('/save_rotation', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        id: rotation.id || null,
        title: rotation.title || `Rotation for vs ${data.game?.opponent || 'Opponent'}`,
        innings,
        associated_game_id: gameId,
      }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.status === 'error') {
      throw new Error(result.message || 'Unable to apply the starting defense.');
    }
  }

  async function applyStartingDefenseToGame() {
    if (applying) return;
    const select = document.getElementById('pde-preset');
    const button = document.getElementById('pde-apply-game');
    if (!select?.value || !button) return;

    applying = true;
    button.disabled = true;
    const original = button.innerHTML;
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Applying…';

    try {
      const data = await fetchGameData();
      const preset = selectedPreset(data, select.value);
      if (!preset) throw new Error('That Starting Defense is no longer available.');

      const label = presetLabel(preset) || 'Starting Defense';
      const sourceInnings = parseInnings(preset.innings);
      const source = sourceInnings['1'] || Object.values(sourceInnings).find(value => value && typeof value === 'object') || {};
      const innings = parseInnings(data.rotation?.innings);
      const targetKeys = wholeInningKeys(innings);
      if (!targetKeys.length) targetKeys.push('1');

      const absent = new Set((data.absent_player_ids || []).map(Number));
      const presentPlayers = (data.roster || []).filter(player => !absent.has(Number(player.id)));
      const available = new Set(presentPlayers.map(player => String(player.name || '').trim()).filter(Boolean));
      const positions = positionsFor(data);
      const unavailable = new Set();

      targetKeys.forEach(key => {
        const existing = innings[key] && typeof innings[key] === 'object' ? innings[key] : {};
        const next = {};

        // Starting Defense is a field-position base, not a pitching plan.
        // Preserve an already assigned pitcher when that player is present.
        if (existing.P && available.has(existing.P)) next.P = existing.P;

        positions.forEach(position => {
          if (position === 'P') return;
          const playerName = String(source[position] || '').trim();
          if (!playerName) return;
          if (available.has(playerName)) next[position] = playerName;
          else unavailable.add(playerName);
        });
        innings[key] = next;
      });

      const inningRange = targetKeys.length === 1
        ? `Inning ${targetKeys[0]}`
        : `Innings ${targetKeys[0]}–${targetKeys[targetKeys.length - 1]}`;
      const warning = unavailable.size
        ? `\n\n${[...unavailable].join(', ')} is unavailable, so those positions will remain open.`
        : '';
      const confirmed = window.confirm(
        `Use “${label}” as the base defense for ${inningRange}?\n\n` +
        'Non-pitcher positions in those innings will be replaced. Existing pitcher assignments will stay unchanged.' +
        warning
      );
      if (!confirmed) return;

      await saveRotation(data, innings);

      // The existing pregame editor owns its local state. Reload once after this
      // game-wide operation so every inning selector immediately reflects the
      // saved server state instead of maintaining a second competing state owner.
      window.location.reload();
    } catch (error) {
      window.alert(error.message || 'Unable to apply the Starting Defense.');
    } finally {
      applying = false;
      if (button?.isConnected) {
        button.innerHTML = original;
        button.disabled = !select?.value;
      }
    }
  }

  function enhancePanel(panel) {
    const tools = panel?.querySelector('.pde-tools');
    const select = panel?.querySelector('#pde-preset');
    const inningButton = panel?.querySelector('#pde-apply');
    const saveButton = panel?.querySelector('#pde-save');
    if (!tools || !select || !inningButton || !saveButton) return;

    tools.classList.add('cb-starting-defense-tools');
    select.setAttribute('aria-label', 'Choose Starting Defense');
    if (select.options.length) select.options[0].textContent = 'Choose Starting Defense…';

    inningButton.textContent = 'This Inning';
    inningButton.title = 'Apply this Starting Defense only to the inning currently shown.';
    saveButton.textContent = 'Save Current';
    saveButton.title = 'Save the current field as a reusable Starting Defense.';

    let gameButton = panel.querySelector('#pde-apply-game');
    if (!gameButton) {
      gameButton = document.createElement('button');
      gameButton.type = 'button';
      gameButton.id = 'pde-apply-game';
      gameButton.className = 'btn btn-primary';
      gameButton.textContent = 'Use for Game';
      gameButton.title = 'Use this Starting Defense as the base for all planned innings.';
      inningButton.insertAdjacentElement('beforebegin', gameButton);
      gameButton.addEventListener('click', applyStartingDefenseToGame);
    }

    gameButton.disabled = !select.value || applying;
    if (select.dataset.cbStartingDefenseScope !== '1') {
      select.dataset.cbStartingDefenseScope = '1';
      select.addEventListener('change', () => {
        const button = panel.querySelector('#pde-apply-game');
        if (button) button.disabled = !select.value || applying;
      });
    }

    let help = panel.querySelector('.cb-starting-defense-help');
    if (!help) {
      help = document.createElement('div');
      help.className = 'cb-starting-defense-help';
      tools.insertAdjacentElement('afterend', help);
    }
    help.innerHTML = '<strong>Starting Defense:</strong> Use for Game fills the non-pitcher positions across every planned inning. Pitchers stay as you already assigned them. Use This Inning for a one-inning variation.';
  }

  function attachPanelObserver(panel) {
    if (!panel) return false;
    enhancePanel(panel);
    panelObserver?.disconnect();
    panelObserver = new MutationObserver(() => enhancePanel(panel));
    panelObserver.observe(panel, {childList: true, subtree: true});
    findingObserver?.disconnect();
    findingObserver = null;
    return true;
  }

  function start() {
    installStyles();
    if (attachPanelObserver(document.getElementById(PANEL_ID))) return;

    findingObserver = new MutationObserver(() => {
      const panel = document.getElementById(PANEL_ID);
      if (panel) attachPanelObserver(panel);
    });
    findingObserver.observe(document.body, {childList: true, subtree: true});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, {once: true});
  } else {
    start();
  }
})();