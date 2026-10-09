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
      /* One obvious action: pick a saved defense, then tap Use (this
         inning) or Whole game -- two plain buttons, no menu to open. The
         buttons that do the work stay in the page, hidden, so every existing
         path (confirmations, pitcher kept, quick start) runs unchanged. */
      /* "html body" outranks the phone layout rules in
         game_management_visual_polish.js, which squeezed these into two
         columns at 38px. */
      html body #${PANEL_ID} .pde-tools.cb-starting-defense-tools{
        grid-template-columns:minmax(0,1fr)!important;
        align-items:end!important;
      }
      html body #${PANEL_ID} .pde-tools.cb-starting-defense-tools .gm-preset-wrap{grid-column:1!important;grid-row:1!important;min-width:0!important;width:100%!important}
      html body #${PANEL_ID} .pde-tools.cb-starting-defense-tools #pde-preset{min-height:44px!important;width:100%!important;max-width:none!important;font-size:.85rem!important}
      html body #${PANEL_ID} .pde-tools.cb-starting-defense-tools .cb-saved-defense-use{
        grid-column:1!important;grid-row:2!important;
        display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:8px;width:100%
      }
      #${PANEL_ID} .pde-tools.cb-starting-defense-tools #pde-apply,
      #${PANEL_ID} .pde-tools.cb-starting-defense-tools #pde-apply-game{display:none!important}
      html body #${PANEL_ID} .pde-tools.cb-starting-defense-tools .cb-saved-defense-use > .btn{
        min-height:44px!important;font-size:.82rem!important;font-weight:800;white-space:nowrap;margin:0;width:100%!important
      }
      html body #${PANEL_ID} .pde-tools.cb-starting-defense-tools #pde-save{
        grid-column:1/-1!important;
        grid-row:3!important;
        justify-self:start!important;
        width:auto!important;
        min-height:44px!important;
        display:inline-flex!important;
        align-items:center!important;
        padding:0 2px!important;
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
      document.querySelectorAll('.cb-saved-defense-use .btn').forEach((item) => {
        item.disabled = !select?.value;
      });
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
        panel.querySelectorAll('.cb-saved-defense-use .btn').forEach((item) => {
          item.disabled = !select.value || applying;
        });
      });
    }

    ensureUseMenu(panel, tools, select);
    let help = panel.querySelector('.cb-starting-defense-help');
    if (!help) {
      help = document.createElement('div');
      help.className = 'cb-starting-defense-help';
      tools.insertAdjacentElement('afterend', help);
    }
    const helpMarkup = '<strong>Saved defenses set fielders only.</strong> Pitchers stay as planned. Choose a saved defense, then tap Use.';
    if (help.innerHTML !== helpMarkup) help.innerHTML = helpMarkup;
  }

  function ensureUseMenu(panel, tools, select) {
    let use = tools.querySelector('.cb-saved-defense-use');
    if (!use) {
      use = document.createElement('div');
      use.className = 'cb-saved-defense-use';
      use.innerHTML = `
        <button type="button" class="btn btn-primary" id="pde-use">Use</button>
        <button type="button" class="btn btn-outline-primary" id="pde-use-game">Whole game</button>`;
      // The hidden buttons are re-rendered with the panel, so look them up
      // at click time.
      use.querySelector('#pde-use').addEventListener('click', () => {
        panel.querySelector('#pde-apply')?.click();
      });
      use.querySelector('#pde-use-game').addEventListener('click', () => {
        panel.querySelector('#pde-apply-game')?.click();
      });
    }
    const anchor = select.closest('.gm-preset-wrap') || select;
    if (anchor.nextElementSibling !== use) anchor.insertAdjacentElement('afterend', use);
    const disabled = !select.value || applying;
    const inning = currentInningLabel(panel);
    const button = use.querySelector('#pde-use');
    const label = `Use for Inning ${inning}`;
    if (button.textContent !== label) button.textContent = label;
    if (button.title !== `Use it for Inning ${inning} only. The pitcher stays as planned.`) {
      button.title = `Use it for Inning ${inning} only. The pitcher stays as planned.`;
    }
    use.querySelectorAll('.btn').forEach((item) => {
      if (item.disabled !== disabled) item.disabled = disabled;
    });
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