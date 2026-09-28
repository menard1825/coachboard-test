(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

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
      /* One obvious action: pick a saved defense, then Use. The scope
         (This inning / Whole game) is chosen from Use's menu; the buttons
         that do the work stay in the page, hidden, so every existing path
         (confirmations, quick start) runs unchanged. */
      #${PANEL_ID} .pde-tools.cb-starting-defense-tools{
        grid-template-columns:minmax(0,1fr) auto!important;
        align-items:end!important;
      }
      #${PANEL_ID} .pde-tools.cb-starting-defense-tools .gm-preset-wrap{grid-column:1!important;grid-row:1!important;min-width:0!important}
      #${PANEL_ID} .pde-tools.cb-starting-defense-tools .cb-saved-defense-use{grid-column:2!important;grid-row:1!important}
      #${PANEL_ID} .pde-tools.cb-starting-defense-tools #pde-apply,
      #${PANEL_ID} .pde-tools.cb-starting-defense-tools #pde-apply-game{display:none!important}
      #${PANEL_ID} .cb-saved-defense-use > .btn{min-height:38px;min-width:78px;font-weight:800}
      #${PANEL_ID} .pde-tools.cb-starting-defense-tools #pde-save{
        grid-column:1/-1!important;
        grid-row:2!important;
        justify-self:start!important;
        width:auto!important;
        min-height:0!important;
        padding:2px 0!important;
        border:0!important;
        background:none!important;
        color:var(--cb-primary-text,#102a66)!important;
        font-size:var(--cb-text-xs)!important;
        font-weight:750!important;
        text-decoration:underline;
        text-underline-offset:2px;
      }
      #${PANEL_ID} .gm-preset-label{display:none!important}
      #${PANEL_ID} .cb-starting-defense-label{
        display:block;
        color:#667085;
        font-size:var(--cb-text-2xs);
        line-height:1.1;
        font-weight:850;
        text-transform:uppercase;
        letter-spacing:.06em;
        margin:0 0 5px 2px;
      }
      #${PANEL_ID} .gm-preset-help{display:none!important}
      #${PANEL_ID} .cb-starting-defense-help{
        margin:-4px 0 11px;
        padding:7px 9px;
        border:1px solid #d9e2f2;
        border-radius:9px;
        background:#f7f9fd;
        color:#526176;
        font-size:var(--cb-text-xs);
        line-height:1.3;
      }
      #${PANEL_ID} .cb-starting-defense-help strong{color:#294a84}
    `;
    document.head.appendChild(style);
  }

  function currentInningLabel(panel) {
    const checked = document.querySelector('#inning-btn-group input[name="inning-radio"]:checked');
    if (checked?.value) return String(checked.value);
    const title = String(panel?.querySelector('.pde-title')?.textContent || '');
    const found = title.match(/Inning\s+([0-9.]+)/i);
    return found?.[1] || '1';
  }

  function syncInningButtonLabel(button, panel) {
    if (!button) return;
    const label = 'This inning';
    if (button.textContent.trim() !== label) button.textContent = label;
    button.title = `Use this saved defense for Inning ${currentInningLabel(panel)} only.`;
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
      // "This inning" and "Whole game" share one rule, owned by
      // live_game_board_prep.js: fielders only, each inning's pitcher kept,
      // conflicts left Open and explained, confirmed before anything
      // changes. Cancel leaves the canonical rotation untouched.
      if (!window.CBSavedDefense) throw new Error('The defense editor is not ready yet. Try again.');
      await window.CBSavedDefense.use('game', select.value);
    } catch (error) {
      window.alert(error.message || 'Unable to use the saved defense.');
    } finally {
      applying = false;
      if (button?.isConnected) {
        if (button.innerHTML !== original) button.innerHTML = original;
        button.disabled = !select?.value;
      }
      const use = document.getElementById('pde-use');
      if (use) use.disabled = !select?.value;
    }
  }

  function enhancePanel(panel) {
    const tools = panel?.querySelector('.pde-tools');
    const select = panel?.querySelector('#pde-preset');
    const inningButton = panel?.querySelector('#pde-apply');
    const saveButton = panel?.querySelector('#pde-save');
    if (!tools || !select || !inningButton || !saveButton) return;

    const kicker = panel.querySelector('.pde-kicker');
    if (kicker && kicker.textContent.trim() !== 'Defense Setup') kicker.textContent = 'Defense Setup';

    tools.classList.add('cb-starting-defense-tools');
    if (select.getAttribute('aria-label') !== 'Choose a saved defense') {
      select.setAttribute('aria-label', 'Choose a saved defense');
    }
    if (select.options.length && select.options[0].textContent !== 'Choose a saved defense…') {
      select.options[0].textContent = 'Choose a saved defense…';
    }

    const presetWrap = select.closest('.gm-preset-wrap');
    if (presetWrap && !presetWrap.querySelector('.cb-starting-defense-label')) {
      const canonicalLabel = document.createElement('label');
      canonicalLabel.className = 'cb-starting-defense-label';
      canonicalLabel.htmlFor = 'pde-preset';
      canonicalLabel.textContent = 'Use a saved defense';
      presetWrap.insertBefore(canonicalLabel, select);
    }

    syncInningButtonLabel(inningButton, panel);
    if (saveButton.textContent !== 'Save this defense') saveButton.textContent = 'Save this defense';
    saveButton.title = 'Save this field as a Saved Defense you can use in any game.';

    let gameButton = panel.querySelector('#pde-apply-game');
    if (!gameButton) {
      gameButton = document.createElement('button');
      gameButton.type = 'button';
      gameButton.id = 'pde-apply-game';
      gameButton.className = 'btn btn-primary';
      inningButton.insertAdjacentElement('beforebegin', gameButton);
      gameButton.addEventListener('click', applyStartingDefenseToGame);
    }
    if (!applying && gameButton.textContent.trim() !== 'Whole game') gameButton.textContent = 'Whole game';
    gameButton.title = 'Use this saved defense for the fielders in every planned inning. Pitchers stay as planned.';

    gameButton.disabled = !select.value || applying;
    if (select.dataset.cbStartingDefenseScope !== '1') {
      select.dataset.cbStartingDefenseScope = '1';
      select.addEventListener('change', () => {
        const currentButton = panel.querySelector('#pde-apply-game');
        if (currentButton) currentButton.disabled = !select.value || applying;
        const use = panel.querySelector('#pde-use');
        if (use) use.disabled = !select.value || applying;
      });
    }

    ensureUseMenu(panel, tools, select);
    let help = panel.querySelector('.cb-starting-defense-help');
    if (!help) {
      help = document.createElement('div');
      help.className = 'cb-starting-defense-help';
      tools.insertAdjacentElement('afterend', help);
    }
    const helpMarkup = '<strong>Saved defenses set fielders only.</strong> Pitchers stay as planned. Choose a saved defense, then Use it for this inning or the whole game.';
    if (help.innerHTML !== helpMarkup) help.innerHTML = helpMarkup;
  }

  function ensureUseMenu(panel, tools, select) {
    let use = tools.querySelector('.cb-saved-defense-use');
    if (!use) {
      use = document.createElement('div');
      use.className = 'dropdown cb-saved-defense-use';
      use.innerHTML = `
        <button type="button" class="btn btn-primary dropdown-toggle" id="pde-use"
                data-bs-toggle="dropdown" aria-expanded="false">Use</button>
        <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="pde-use">
          <li><button type="button" class="dropdown-item" id="pde-use-inning">This inning</button></li>
          <li><button type="button" class="dropdown-item" id="pde-use-game">Whole game</button></li>
        </ul>`;
      // The hidden buttons are re-rendered with the panel, so look them up
      // at click time.
      use.querySelector('#pde-use-inning').addEventListener('click', () => {
        panel.querySelector('#pde-apply')?.click();
      });
      use.querySelector('#pde-use-game').addEventListener('click', () => {
        panel.querySelector('#pde-apply-game')?.click();
      });
    }
    const anchor = select.closest('.gm-preset-wrap') || select;
    if (anchor.nextElementSibling !== use) anchor.insertAdjacentElement('afterend', use);
    const button = use.querySelector('#pde-use');
    const disabled = !select.value || applying;
    if (button.disabled !== disabled) button.disabled = disabled;
    const inning = `Inning ${currentInningLabel(panel)}`;
    const inningItem = use.querySelector('#pde-use-inning');
    if (inningItem.title !== `Use it for ${inning} only.`) inningItem.title = `Use it for ${inning} only.`;
  }

  function attachPanelObserver(panel) {
    if (!panel) return false;
    enhancePanel(panel);
    panelObserver?.disconnect();
    panelObserver = new MutationObserver(() => enhancePanel(panel));
    // The base pregame editor replaces the panel's direct children when it
    // re-renders. Watching descendants caused our own label updates to retrigger
    // this helper, so observe only those top-level replacements.
    panelObserver.observe(panel, {childList: true});
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