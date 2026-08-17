(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  const STYLE_ID = 'game-management-team-theme-availability-v1';

  function cssColor(variableName, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(variableName).trim();
    if (value && window.CSS?.supports?.('color', value)) return value;
    return fallback;
  }

  function workspace() {
    const host = document.getElementById('pregame-checklist-container');
    return host?.closest('.container-fluid.mt-3') || host?.parentElement || null;
  }

  function applyTeamTheme() {
    const shell = workspace();
    if (!shell) return;

    // Override the visual-polish defaults with the active team's actual colors.
    // Inline custom properties win regardless of which helper script loads first.
    const primary = cssColor('--primary-color', '#344054');
    const secondary = cssColor('--secondary-color', '#98a2b3');
    shell.style.setProperty('--gm-navy', primary);
    shell.style.setProperty('--gm-gold', secondary);
    shell.style.setProperty('--gm-primary', primary);
    shell.style.setProperty('--gm-accent', secondary);
  }

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      body.coach-game-page #startLiveGameBtnAction i{
        color:var(--gm-accent,var(--gm-gold,#98a2b3))!important;
      }

      #availabilityCollapse .availability-guide-v2{
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:16px;
        padding:2px 2px 14px;
        margin-bottom:12px;
        border-bottom:1px solid #e7ebef;
      }
      #availabilityCollapse .availability-kicker-v2{
        font-size:.63rem;
        line-height:1;
        text-transform:uppercase;
        letter-spacing:.1em;
        font-weight:850;
        color:#667085;
        margin-bottom:6px;
      }
      #availabilityCollapse .availability-guide-v2 h6{
        margin:0 0 4px;
        color:#172033;
        font-size:1rem;
        font-weight:850;
      }
      #availabilityCollapse .availability-guide-v2 p{
        margin:0;
        color:#667085;
        font-size:.76rem;
        max-width:650px;
      }
      #availabilityCollapse .availability-out-count-v2{
        min-width:64px;
        border:1px solid #ead2cf;
        border-radius:11px;
        padding:7px 10px;
        background:#fff8f7;
        color:#9b2c22;
        text-align:center;
        flex:0 0 auto;
      }
      #availabilityCollapse .availability-out-count-v2 strong{
        display:block;
        font-size:1.15rem;
        line-height:1;
      }
      #availabilityCollapse .availability-out-count-v2 span{
        display:block;
        margin-top:3px;
        font-size:.56rem;
        font-weight:900;
        letter-spacing:.08em;
      }

      #availabilityCollapse .availability-grid-v2{
        --bs-gutter-x:10px;
        --bs-gutter-y:10px;
      }
      #availabilityCollapse .availability-player-v2{
        display:grid;
        grid-template-columns:auto minmax(0,1fr) auto;
        align-items:center;
        gap:10px;
        min-height:60px;
        margin:0;
        padding:10px 12px;
        border:1px solid #dfe5ec;
        border-radius:11px;
        background:#fff;
        transition:border-color .15s ease,background-color .15s ease,box-shadow .15s ease;
      }
      #availabilityCollapse .availability-player-v2.is-out{
        border-color:#e1b8b3;
        background:#fff8f7;
        box-shadow:0 0 0 1px rgba(180,35,24,.03);
      }
      #availabilityCollapse .availability-player-v2 .form-check-input{
        float:none;
        margin:0!important;
        width:2.45rem;
        height:1.3rem;
        cursor:pointer;
      }
      #availabilityCollapse .availability-player-v2 .form-check-input:not(:checked){
        background-color:#d7dde5;
        border-color:#c7ced8;
      }
      #availabilityCollapse .availability-player-v2 .form-check-input:checked{
        background-color:#b42318!important;
        border-color:#b42318!important;
      }
      #availabilityCollapse .availability-player-v2 .form-check-input:focus{
        box-shadow:0 0 0 .18rem rgba(16,24,40,.08);
      }
      #availabilityCollapse .availability-player-v2 .form-check-label{
        display:flex;
        flex-direction:column;
        min-width:0;
        margin:0;
        cursor:pointer;
      }
      #availabilityCollapse .availability-player-name-v2{
        color:#1d2939;
        font-size:.82rem;
        line-height:1.15;
        font-weight:800;
        overflow:hidden;
        text-overflow:ellipsis;
        white-space:nowrap;
      }
      #availabilityCollapse .availability-state-v2{
        margin-top:3px;
        color:#19713e;
        font-size:.66rem;
        line-height:1;
        font-weight:750;
      }
      #availabilityCollapse .availability-player-v2.is-out .availability-state-v2{
        color:#b42318;
      }
      #availabilityCollapse .availability-out-word-v2{
        color:#7a8797;
        font-size:.64rem;
        font-weight:900;
        letter-spacing:.08em;
      }
      #availabilityCollapse .availability-player-v2.is-out .availability-out-word-v2{
        color:#b42318;
      }
      #availabilityCollapse .availability-save-v2{
        min-height:44px;
        border-radius:10px;
        font-weight:800;
      }

      @media(max-width:575.98px){
        #availabilityCollapse .card-body{padding:12px!important}
        #availabilityCollapse .availability-guide-v2{gap:10px}
        #availabilityCollapse .availability-guide-v2 h6{font-size:.92rem}
        #availabilityCollapse .availability-guide-v2 p{font-size:.7rem}
        #availabilityCollapse .availability-player-v2{min-height:58px;padding:9px 10px}
      }
    `;
    document.head.appendChild(style);
  }

  function updateAvailabilityState(input) {
    const row = input.closest('.availability-player-v2');
    if (!row) return;
    const isOut = input.checked;
    row.classList.toggle('is-out', isOut);
    const state = row.querySelector('.availability-state-v2');
    if (state) state.textContent = isOut ? 'OUT for this game' : 'Available';
    input.setAttribute('aria-label', `${row.querySelector('.availability-player-name-v2')?.textContent || 'Player'} ${isOut ? 'out' : 'available'} for this game`);
  }

  function updateOutCount(form) {
    const count = form.querySelectorAll('input[name="absent_players"]:checked').length;
    const value = form.querySelector('#availability-out-count-v2-value');
    if (value) value.textContent = String(count);
  }

  function enhanceAvailability() {
    const collapse = document.getElementById('availabilityCollapse');
    const form = collapse?.querySelector('form');
    if (!collapse || !form || form.dataset.availabilityEnhanced === 'true') return;

    const inputs = [...form.querySelectorAll('input[name="absent_players"]')];
    if (!inputs.length) return;
    form.dataset.availabilityEnhanced = 'true';

    const grid = inputs[0].closest('.row');
    if (grid) grid.classList.add('availability-grid-v2');

    const guide = document.createElement('div');
    guide.className = 'availability-guide-v2';
    guide.innerHTML = `
      <div>
        <div class="availability-kicker-v2">Game Availability</div>
        <h6>Who's OUT for this game?</h6>
        <p>Everyone is available by default. Turn on <strong>OUT</strong> only for players who will miss this game.</p>
      </div>
      <div class="availability-out-count-v2" aria-live="polite">
        <strong id="availability-out-count-v2-value">0</strong>
        <span>OUT</span>
      </div>`;
    if (grid) form.insertBefore(guide, grid);
    else form.prepend(guide);

    inputs.forEach((input) => {
      const col = input.closest('[class*="col-"]');
      if (col) {
        col.className = 'col-12 col-sm-6 col-lg-4 availability-player-col-v2';
      }

      const holder = input.closest('.form-check');
      const label = holder?.querySelector(`label[for="${input.id}"]`);
      if (!holder || !label) return;

      holder.classList.add('availability-player-v2');
      holder.classList.remove('form-switch');
      const playerName = label.textContent.trim();
      label.innerHTML = `<span class="availability-player-name-v2"></span><span class="availability-state-v2"></span>`;
      label.querySelector('.availability-player-name-v2').textContent = playerName;

      const outWord = document.createElement('span');
      outWord.className = 'availability-out-word-v2';
      outWord.textContent = 'OUT';
      holder.appendChild(outWord);

      // Keep Bootstrap's switch visual while making the meaning explicit.
      holder.classList.add('form-switch');
      updateAvailabilityState(input);
      input.addEventListener('change', () => {
        updateAvailabilityState(input);
        updateOutCount(form);
      });
    });

    const save = form.querySelector('button[type="submit"]');
    if (save) {
      save.classList.remove('btn-success', 'mt-3');
      save.classList.add('btn-primary', 'availability-save-v2', 'mt-3');
      save.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Save Game Availability';
    }

    const trigger = document.querySelector('[data-bs-target="#availabilityCollapse"]');
    if (trigger) trigger.textContent = "Set Who's Out";

    const availabilityCard = trigger?.closest('.card');
    const metricLabel = availabilityCard?.querySelector('.h4 .text-muted');
    if (metricLabel) metricLabel.textContent = 'Available';
    const detail = availabilityCard?.querySelector('.small.text-muted');
    if (detail) detail.textContent = detail.textContent.replace(/absent/i, 'out');

    updateOutCount(form);
  }

  function init() {
    applyTeamTheme();
    installStyles();
    enhanceAvailability();

    // The visual-polish helper may add the workspace class after this helper has
    // already run. Reapply once on the next frame; inline theme vars still win.
    requestAnimationFrame(applyTeamTheme);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, {once:true});
  } else {
    init();
  }
})();
