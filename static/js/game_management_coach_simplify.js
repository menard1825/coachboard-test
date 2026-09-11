(() => {
  'use strict';

  const routeMatch = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!routeMatch) return;

  const gameId = Number(routeMatch[1]);
  const PANEL_ID = 'pregame-defense-editor-v3';
  let reportsCollapsed = false;
  let presetToolsOpen = false;
  let phonePlayingTimeOpen = false;
  let patchQueued = false;

  const setText = (element, value) => {
    if (element && element.textContent !== value) element.textContent = value;
  };
  const setHtml = (element, value) => {
    if (element && element.innerHTML !== value) element.innerHTML = value;
  };
  const sleep = (ms) => new Promise(resolve => window.setTimeout(resolve, ms));

  function installStyles() {
    if (document.getElementById('game-management-coach-simplify-styles')) return;
    const style = document.createElement('style');
    style.id = 'game-management-coach-simplify-styles';
    style.textContent = `
      #rotation-card-container .gm-coach-inning-picker{
        background:#fff!important;
        border:1px solid #dfe5ec!important;
        border-radius:12px!important;
        padding:8px 10px!important;
        gap:9px;
      }
      #rotation-card-container .gm-coach-inning-label{
        color:#475467;
        font-size:.72rem;
        font-weight:850;
        white-space:nowrap;
        margin-right:2px;
      }
      #rotation-card-container .gm-coach-help{
        color:#667085;
        font-size:.71rem;
        margin:5px 2px 9px;
      }
      #rotation-card-container .gm-coach-actions{align-items:center}
      #rotation-card-container .gm-coach-actions #copyPreviousInningBtn{
        border-radius:9px;
        min-height:38px;
      }
      #rotation-card-container .gm-coach-actions .dropdown-toggle{
        border-radius:9px;
        min-height:38px;
      }
      #rotation-card-container .gm-sub-inning-label{
        border-style:dashed!important;
        position:relative;
      }
      #rotation-card-container .gm-sub-inning-label::after{
        content:'SUB';
        position:absolute;
        top:-7px;
        right:-5px;
        font-size:.42rem;
        line-height:1;
        font-weight:900;
        letter-spacing:.04em;
        padding:2px 3px;
        border-radius:4px;
        color:#7a4b00;
        background:#fff3cd;
        border:1px solid #f2d38a;
      }
      #${PANEL_ID} .pde-inning{display:none!important}
      #${PANEL_ID} .pde-head{align-items:center!important}
      #${PANEL_ID} .pde-title{font-size:1rem!important}
      #${PANEL_ID} .pde-help{font-size:.72rem!important}
      #${PANEL_ID} .pde-tools{
        grid-template-columns:minmax(0,1fr) auto auto!important;
        align-items:end;
        padding:10px;
        background:#f8fafc;
        border:1px solid #e4e7ec;
        border-radius:11px;
        margin-bottom:12px!important;
      }
      #${PANEL_ID} .gm-preset-wrap{min-width:0}
      #${PANEL_ID} .gm-preset-label{
        display:block;
        color:#667085;
        font-size:.62rem;
        line-height:1.1;
        font-weight:850;
        text-transform:uppercase;
        letter-spacing:.06em;
        margin:0 0 5px 2px;
      }
      #${PANEL_ID} .gm-preset-help{display:none!important}
      #${PANEL_ID} #pde-save{display:none!important}
      #${PANEL_ID} #pde-apply{white-space:normal}
      #${PANEL_ID} #pde-primary-fill{white-space:nowrap}
      #${PANEL_ID} .pde-status{font-size:.7rem!important}
      #${PANEL_ID} .pde-field-caption strong{font-size:.72rem!important}
      #rotation-card-container .gm-secondary-report .accordion-collapse,
      #rotation-card-container .gm-secondary-report .collapse{scroll-margin-top:90px}

      #${PANEL_ID} .gm-mobile-preset-toggle{
        display:none;
      }
      @media(max-width:767.98px){
        #${PANEL_ID} .gm-mobile-preset-toggle{
          display:inline-flex;
          align-items:center;
          gap:5px;
          width:auto;
          min-height:30px;
          margin:0 0 6px;
          padding:4px 7px;
          border:1px solid #d7dde5;
          border-radius:8px;
          background:#fff;
          color:#475467;
          font-size:.59rem;
          font-weight:850;
        }
      }

      /*
       * Playing-time information stays available for fair-play review,
       * but on desktop/iPad it lives after the Rotation Table instead
       * of separating the field from the table.
       */
      #gm-playing-time-report{
        margin:0 0 12px;
      }
      #gm-playing-time-report .gm-playing-time-toggle{
        width:100%;
        min-height:42px;
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:10px;
        border:0;
        background:#fbfcfd;
        color:#172033;
        padding:10px 12px;
        text-align:left;
        font-size:.78rem;
        font-weight:850;
      }
      #gm-playing-time-report .gm-playing-time-toggle:hover,
      #gm-playing-time-report .gm-playing-time-toggle:focus{
        background:#f5f7fa;
      }
      #gm-playing-time-report .gm-playing-time-toggle small{
        display:block;
        margin-top:1px;
        color:#667085;
        font-size:.61rem;
        font-weight:650;
      }
      #gm-playing-time-report .pde-playing-time{
        margin:0!important;
        border:0!important;
        border-radius:0!important;
        background:#fff;
        overflow:hidden;
      }
      #gm-playing-time-report .pde-playing-time-head{
        display:none!important;
      }
      #gm-playing-time-report .pde-time-row{
        padding:8px 10px;
        border-top:1px solid #eef1f4;
      }
      #gm-playing-time-report .pde-time-row:first-child{
        border-top:0;
      }
      #gm-playing-time-report .pde-time-main{
        display:flex;
        justify-content:space-between;
        align-items:baseline;
        gap:8px;
      }
      #gm-playing-time-report .pde-time-name{
        font-size:.72rem;
        color:#172033;
        min-width:0;
      }
      #gm-playing-time-report .pde-time-total{
        font-size:.61rem;
        color:#667085;
        white-space:nowrap;
        font-weight:700;
      }
      #gm-playing-time-report .pde-time-chips{
        display:flex;
        flex-wrap:wrap;
        gap:4px;
        margin-top:5px;
      }
      #gm-playing-time-report .pde-time-chip{
        display:inline-flex;
        align-items:center;
        border:1px solid #4aae72;
        background:#f4fbf6;
        color:#176b38;
        border-radius:6px;
        padding:3px 6px;
        font-size:.59rem;
        font-weight:800;
        line-height:1;
      }
      #gm-playing-time-report .pde-time-chip.bench{
        border-color:#d6dbe1;
        background:#f4f5f7;
        color:#667085;
      }

      /*
       * Phones in either orientation, plus tablet landscape:
       * the field can consume the viewport vertically. Keep the inning
       * buttons reachable while the coach works on the diamond.
       *
       * This is enabled only while the pregame Game Management defense
       * panel exists, so Live Game does not inherit the behavior.
       */
      @media(max-width:767.98px),
             (min-width:640px) and (max-width:1366px) and (orientation:landscape){
        /*
         * The global Game Management card styling uses overflow:hidden.
         * That creates a sticky containing boundary and prevents the
         * inning picker from following the viewport. Allow overflow only
         * on this pregame defense card while the landscape planner is active.
         */
        body.gm-pregame-planning #rotation-card-container > .card{
          overflow:visible!important;
        }

        body.gm-pregame-planning #rotation-card-container .gm-coach-inning-picker{
          position:sticky!important;
          top:56px;
          z-index:1030;
          width:100%;
          margin-bottom:8px!important;
          background:#fff!important;
          box-shadow:0 4px 12px rgba(16,24,40,.14);
        }
        body.gm-pregame-planning #rotation-card-container #inning-btn-group{
          flex-wrap:nowrap!important;
          overflow-x:auto;
          overflow-y:hidden;
          min-width:0;
          scrollbar-width:thin;
        }
        body.gm-pregame-planning #rotation-card-container #inning-btn-group > *{
          flex:0 0 auto;
        }
      }

      /*
       * On phones, and on compact landscape layouts below Bootstrap's
       * lg breakpoint, CoachBoard does not scroll the browser window.
       * main.container-fluid is the scrollport and already begins below
       * the fixed top navigation. Therefore the sticky inning bar belongs
       * at the top of that scrollport rather than another 56px below it.
       */
      @media(max-width:767.98px),
             (min-width:640px) and (max-width:991.98px) and (orientation:landscape){
        body.gm-pregame-planning #rotation-card-container .gm-coach-inning-picker{
          top:0;
        }
      }

      @media(max-width:575.98px){
        #rotation-card-container .gm-coach-inning-picker{align-items:flex-start!important;flex-wrap:wrap}
        #rotation-card-container .gm-coach-inning-label{width:100%;margin-bottom:2px}
        #rotation-card-container .gm-coach-actions{display:grid!important;grid-template-columns:1fr auto;width:100%}
        #rotation-card-container .gm-coach-actions #copyPreviousInningBtn{width:100%}
        #${PANEL_ID} .pde-tools{
          display:grid!important;
          grid-template-columns:minmax(0,1fr)!important;
          gap:8px!important;
          align-items:stretch!important;
        }
        #${PANEL_ID} .gm-preset-wrap,
        #${PANEL_ID} #pde-preset,
        #${PANEL_ID} #pde-apply,
        #${PANEL_ID} #pde-primary-fill{
          width:100%!important;
          max-width:none!important;
        }
        #${PANEL_ID} .gm-preset-wrap{grid-row:1!important}
        #${PANEL_ID} #pde-apply{grid-row:2!important}
        #${PANEL_ID} #pde-primary-fill{grid-row:3!important}
        #${PANEL_ID} #pde-apply{
          display:block!important;
          min-height:42px;
          text-align:center;
          justify-self:stretch;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function currentInning() {
    const checked = document.querySelector('#inning-btn-group input[name="inning-radio"]:checked');
    if (checked?.value) return checked.value;
    const panelValue = document.querySelector(`#${PANEL_ID} .pde-inning strong`)?.textContent?.trim();
    if (panelValue) return panelValue;
    return '1';
  }

  function isSubInning(value = currentInning()) {
    const number = Number.parseFloat(value);
    return Number.isFinite(number) && Math.abs(number - Math.floor(number)) > 0.001;
  }

  function subIndex(value) {
    const number = Number.parseFloat(value);
    if (!Number.isFinite(number)) return 1;
    return Math.max(1, Math.round((number - Math.floor(number)) * 10));
  }

  function shortInningLabel(value) {
    if (!isSubInning(value)) return String(value);
    const base = Math.floor(Number.parseFloat(value));
    const letter = String.fromCharCode(64 + Math.min(subIndex(value), 26));
    return `${base}${letter}`;
  }

  function fullInningLabel(value) {
    if (!isSubInning(value)) return `Inning ${value}`;
    const base = Math.floor(Number.parseFloat(value));
    const letter = String.fromCharCode(64 + Math.min(subIndex(value), 26));
    return `Inning ${base} · Planned Mid-Inning Change ${letter}`;
  }

  function toast(message, kind = 'success') {
    let holder = document.getElementById('gm-coach-toast-holder');
    if (!holder) {
      holder = document.createElement('div');
      holder.id = 'gm-coach-toast-holder';
      holder.className = 'toast-container position-fixed top-0 end-0 p-3';
      holder.style.zIndex = '6000';
      document.body.appendChild(holder);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold"></div><button class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    el.querySelector('.toast-body').textContent = message;
    holder.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el, {delay: 2600});
    el.addEventListener('hidden.bs.toast', () => el.remove(), {once:true});
    instance.show();
  }

  function preventActionAnchorJumps(event) {
    const action = event.target.closest('#copyInningBtn, #clearInningBtn, #saveAsTemplateBtn, #printCardBtn, #deleteRotationBtn, #saveRotationBtn');
    if (action?.tagName === 'A') event.preventDefault();
  }

  async function fetchLatestRotationUntil(inningKey, attempts = 16) {
    let lastData = null;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const response = await fetch(`/api/game_data/${gameId}?_=${Date.now()}`, {cache:'no-store'});
      if (!response.ok) throw new Error('Could not read the latest defense plan.');
      lastData = await response.json();
      let innings = lastData?.rotation?.innings || {};
      if (typeof innings === 'string') {
        try { innings = JSON.parse(innings); } catch (_) { innings = {}; }
      }
      if (Object.prototype.hasOwnProperty.call(innings, inningKey)) {
        lastData.rotation.innings = innings;
        return lastData;
      }
      await sleep(180);
    }
    return lastData;
  }

  async function removeCurrentMidInningChange() {
    const raw = currentInning();
    if (!isSubInning(raw)) return;
    const base = String(Math.floor(Number.parseFloat(raw)));
    const display = shortInningLabel(raw);
    if (!window.confirm(`Remove planned change ${display}?\n\nThe normal Inning ${base} defense will stay in place.`)) return;

    const removeButton = document.getElementById('gmRemoveCurrentSubInning');
    if (removeButton) {
      removeButton.disabled = true;
      removeButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Removing…';
    }

    try {
      document.getElementById('saveRotationBtn')?.click();
      const data = await fetchLatestRotationUntil(raw);
      if (!data?.rotation) throw new Error('Could not find the current defense plan.');

      let innings = data.rotation.innings || {};
      if (typeof innings === 'string') innings = JSON.parse(innings);
      if (!Object.prototype.hasOwnProperty.call(innings, raw)) {
        throw new Error('That planned change was not found. Refresh the page and try again.');
      }

      document.querySelector(`#inning-btn-group input[name="inning-radio"][value="${CSS.escape(base)}"]`)?.click();

      delete innings[raw];
      const response = await fetch('/save_rotation', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          id:data.rotation.id,
          title:data.rotation.title || `Rotation for game ${gameId}`,
          innings,
          associated_game_id:gameId,
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.status !== 'success') throw new Error(result.message || 'Could not remove that planned change.');

      toast(`Removed planned change ${display}.`);
      window.setTimeout(() => {
        document.querySelector(`#inning-btn-group input[name="inning-radio"][value="${CSS.escape(base)}"]`)?.click();
        queuePatch();
      }, 250);
    } catch (error) {
      toast(error.message || 'Could not remove that planned change.', 'danger');
    } finally {
      if (removeButton?.isConnected) {
        removeButton.disabled = false;
        removeButton.innerHTML = '<i class="bi bi-trash me-2"></i>Remove This Planned Change';
      }
    }
  }

  function simplifyHeader() {
    const title = document.getElementById('rotation-editor-title');
    setText(title, 'Set Defense');

    const liveToggle = document.getElementById('liveGameModeToggle');
    const liveWrap = liveToggle?.closest('.form-check');
    if (liveWrap && !liveWrap.classList.contains('d-none')) {
      liveWrap.classList.add('d-none');
      liveWrap.setAttribute('aria-hidden', 'true');
    }

    const saveRotationDesktop = document.getElementById('saveRotationBtn');
    const saveRotationDesktopItem = saveRotationDesktop?.closest('li');
    if (saveRotationDesktopItem && !saveRotationDesktopItem.classList.contains('d-none')) saveRotationDesktopItem.classList.add('d-none');
    const saveRotationMobile = document.getElementById('saveRotationBtnMobile');
    if (saveRotationMobile && !saveRotationMobile.classList.contains('d-none')) saveRotationMobile.classList.add('d-none');

    const cardHeader = title?.closest('.card-header');
    const menuToggle = cardHeader?.querySelector('.dropdown-toggle');
    const menu = menuToggle?.nextElementSibling;
    if (menuToggle && menuToggle.dataset.coachSimplified !== '1') {
      menuToggle.dataset.coachSimplified = '1';
      setHtml(menuToggle, '<i class="bi bi-sliders me-1"></i> Defense Options');
      menuToggle.title = 'Defense tools';
    }

    const rotationTemplateSelect = document.getElementById('rotationTemplateSelect');
    if (rotationTemplateSelect?.options?.length) {
      setText(rotationTemplateSelect.options[0], 'Load full-game defense plan (all innings)…');
    }

    if (menu && rotationTemplateSelect && !document.getElementById('gmFullGamePlanHeader')) {
      const templateItem = rotationTemplateSelect.closest('li');
      if (templateItem) {
        const header = document.createElement('li');
        header.id = 'gmFullGamePlanHeader';
        header.innerHTML = '<div class="dropdown-header">Full-game defense plan · all innings</div>';
        menu.insertBefore(header, templateItem);
      }
    }

    const saveFullTemplate = document.getElementById('saveAsTemplateBtn');
    setHtml(saveFullTemplate, '<i class="bi bi-journal-plus me-1"></i> Save All Innings as Full-Game Plan');

    const printCard = document.getElementById('printCardBtn');
    setHtml(printCard, '<i class="bi bi-printer me-1"></i> Print Defense / Lineup Card');

    const deleteRotation = document.getElementById('deleteRotationBtn');
    setHtml(deleteRotation, '<i class="bi bi-trash me-1"></i> Delete Defense Plan');

    if (menu && !document.getElementById('gmSaveCurrentDefensePreset')) {
      const divider = document.createElement('li');
      divider.innerHTML = '<hr class="dropdown-divider">';
      const item = document.createElement('li');
      item.innerHTML = '<button type="button" class="dropdown-item" id="gmSaveCurrentDefensePreset"><i class="bi bi-bookmark-plus me-1"></i> Save This Inning as a Starting Defense</button>';
      const deleteItem = deleteRotation?.closest('li');
      if (deleteItem) {
        menu.insertBefore(divider, deleteItem);
        menu.insertBefore(item, deleteItem);
      } else {
        menu.appendChild(divider);
        menu.appendChild(item);
      }
      item.querySelector('button')?.addEventListener('click', () => document.getElementById('pde-save')?.click());
    }

    if (menu && !document.getElementById('gmPlanMidInningChange')) {
      const deleteItem = deleteRotation?.closest('li');
      const divider = document.createElement('li');
      divider.id = 'gmAdvancedPlanningDivider';
      divider.innerHTML = '<hr class="dropdown-divider"><div class="dropdown-header">Advanced planning</div>';
      const item = document.createElement('li');
      item.innerHTML = '<button type="button" class="dropdown-item" id="gmPlanMidInningChange"><i class="bi bi-arrow-left-right me-1"></i> Plan a Change During This Inning…</button>';
      if (deleteItem) {
        menu.insertBefore(divider, deleteItem);
        menu.insertBefore(item, deleteItem);
      } else {
        menu.appendChild(divider);
        menu.appendChild(item);
      }
      item.querySelector('button')?.addEventListener('click', () => {
        const raw = currentInning();
        const base = Math.floor(Number.parseFloat(raw));
        if (isSubInning(raw)) {
          toast('You are already editing a planned change during this inning.', 'warning');
          return;
        }
        const ok = window.confirm(
          `Plan a defensive change during Inning ${base}?\n\n` +
          'Use this only when you already know you want a substitution or defensive change during the same inning. ' +
          'For normal inning-to-inning changes, use Add Another Inning instead.'
        );
        if (ok) document.getElementById('addSubInningBtn')?.click();
      });
    }
  }

  function addInningOption(menu, id, icon, label, targetId, danger = false) {
    if (!menu || document.getElementById(id)) return;
    const li = document.createElement('li');
    li.innerHTML = `<button type="button" class="dropdown-item ${danger ? 'text-danger' : ''}" id="${id}"><i class="bi bi-${icon} me-2"></i>${label}</button>`;
    li.querySelector('button')?.addEventListener('click', () => document.getElementById(targetId)?.click());
    menu.appendChild(li);
  }

  function syncSubInningSelectorLabels(group) {
    group.querySelectorAll('input[name="inning-radio"]').forEach(input => {
      const label = group.querySelector(`label[for="${CSS.escape(input.id)}"]`);
      if (!label) return;
      if (isSubInning(input.value)) {
        setText(label, shortInningLabel(input.value));
        if (!label.classList.contains('gm-sub-inning-label')) label.classList.add('gm-sub-inning-label');
        label.title = fullInningLabel(input.value);
      } else {
        setText(label, input.value);
        label.classList.remove('gm-sub-inning-label');
        label.removeAttribute('title');
      }
    });
  }

  function syncRemoveCurrentSubAction(toolsMenu) {
    const existing = document.getElementById('gmRemoveCurrentSubInning')?.closest('li');
    if (!isSubInning()) {
      existing?.remove();
      return;
    }
    if (existing || !toolsMenu) return;
    const li = document.createElement('li');
    li.innerHTML = '<button type="button" class="dropdown-item text-danger" id="gmRemoveCurrentSubInning"><i class="bi bi-trash me-2"></i>Remove This Planned Change</button>';
    toolsMenu.appendChild(li);
    li.querySelector('button')?.addEventListener('click', removeCurrentMidInningChange);
  }

  function simplifyInningControls() {
    const group = document.getElementById('inning-btn-group');
    if (!group) return;
    syncSubInningSelectorLabels(group);

    const pickerRow = group.closest('.d-flex.align-items-center');
    if (pickerRow) {
      if (!pickerRow.classList.contains('gm-coach-inning-picker')) pickerRow.classList.add('gm-coach-inning-picker');
      if (!pickerRow.querySelector('.gm-coach-inning-label')) {
        const label = document.createElement('span');
        label.className = 'gm-coach-inning-label';
        label.textContent = 'Choose Inning';
        pickerRow.insertBefore(label, group);
      }
    }

    const addButton = document.getElementById('addInningBtn');
    const oldAdvancedGroup = addButton?.closest('.btn-group');
    if (oldAdvancedGroup && !oldAdvancedGroup.classList.contains('d-none')) oldAdvancedGroup.classList.add('d-none');

    const copyPrevious = document.getElementById('copyPreviousInningBtn');
    const actions = copyPrevious?.parentElement;
    if (actions && !actions.classList.contains('gm-coach-actions')) actions.classList.add('gm-coach-actions');
    if (copyPrevious) {
      setHtml(copyPrevious, '<i class="bi bi-copy me-1"></i> Use Previous Inning');
      const inning = Number.parseFloat(currentInning());
      const shouldHide = isSubInning() || (Number.isFinite(inning) && inning <= 1);
      if (copyPrevious.classList.contains('d-none') !== shouldHide) copyPrevious.classList.toggle('d-none', shouldHide);
      copyPrevious.title = 'Copy the previous inning defense into this inning';
    }

    const toolsToggle = actions?.querySelector('.dropdown-toggle');
    const toolsMenu = toolsToggle?.nextElementSibling;
    if (toolsToggle) {
      setHtml(toolsToggle, '<i class="bi bi-three-dots me-1"></i> Inning Options');
      toolsToggle.title = 'Inning tools';
    }

    if (toolsMenu && toolsMenu.dataset.coachSimplified !== '1') {
      toolsMenu.dataset.coachSimplified = '1';
      const existingCopy = document.getElementById('copyInningBtn');
      setHtml(existingCopy, '<i class="bi bi-files me-2"></i> Copy This Inning to Others…');
      const clear = document.getElementById('clearInningBtn');
      if (clear) {
        clear.classList.remove('text-warning');
        clear.classList.add('text-danger');
        setHtml(clear, '<i class="bi bi-eraser me-2"></i> Clear This Inning');
      }
      const divider = document.createElement('li');
      divider.id = 'gmInningStructureDivider';
      divider.innerHTML = '<hr class="dropdown-divider"><div class="dropdown-header">Inning structure</div>';
      toolsMenu.appendChild(divider);
      addInningOption(toolsMenu, 'gmAddInningAction', 'plus-circle', 'Add Another Inning', 'addInningBtn');
      addInningOption(toolsMenu, 'gmRemoveInningAction', 'dash-circle', 'Remove Last Inning', 'removeInningBtn', true);
      document.getElementById('gmAddSubInningAction')?.closest('li')?.remove();
    }
    syncRemoveCurrentSubAction(toolsMenu);

    const planner = pickerRow?.closest('.planner-controls');
    if (planner && !planner.querySelector('.gm-coach-help')) {
      const help = document.createElement('div');
      help.className = 'gm-coach-help';
      help.innerHTML = '<i class="bi bi-info-circle me-1"></i>Select an inning, then tap a position to assign a player. Saves automatically.';
      pickerRow.insertAdjacentElement('afterend', help);
    }
  }

  function syncInningPickerPlacement() {
    const board = document.getElementById(
      'rotation-board'
    );

    const controls = board?.querySelector(
      ':scope > .planner-controls'
    );

    const panel = document.getElementById(
      PANEL_ID
    );

    const group = document.getElementById(
      'inning-btn-group'
    );

    const picker = group?.closest(
      '.gm-coach-inning-picker'
    );

    if (
      !board ||
      !controls ||
      !picker
    ) {
      return;
    }

    const phoneViewport = window.matchMedia(
      '(max-width: 767.98px)'
    ).matches;

    const compactLandscape = window.matchMedia(
      '(min-width: 640px) and ' +
      '(max-width: 1366px) and ' +
      '(orientation: landscape)'
    ).matches;

    const shouldStick = Boolean(
      panel &&
      (
        phoneViewport ||
        compactLandscape
      )
    );

    if (shouldStick) {
      /*
       * position:sticky is constrained by the bounds of its
       * containing block. The original picker lives inside the
       * short .planner-controls wrapper, so it can only stick for
       * a moment before that wrapper scrolls away.
       *
       * Move only the picker row to rotation-board, immediately
       * before the pregame defense panel. rotation-board spans the
       * entire defensive workspace, giving sticky enough vertical
       * range to stay available while the coach works the field.
       */
      picker.classList.add(
        'gm-ipad-sticky-inning-picker'
      );

      if (
        picker.parentElement !== board ||
        picker.nextElementSibling !== panel
      ) {
        panel.insertAdjacentElement(
          'beforebegin',
          picker
        );
      }

      return;
    }

    /*
     * Portrait tablet, wide desktop, or Live Game:
     * put the picker back in its original planner-controls home.
     */
    picker.classList.remove(
      'gm-ipad-sticky-inning-picker'
    );

    if (picker.parentElement !== controls) {
      controls.insertBefore(
        picker,
        controls.firstElementChild
      );
    }
  }

  function syncMobilePresetDisclosure(
    panel,
    tools
  ) {
    if (!panel || !tools) return;

    const mobile = window.matchMedia(
      '(max-width: 767.98px)'
    ).matches;

    let toggle = panel.querySelector(
      '.gm-mobile-preset-toggle'
    );

    if (!toggle) {
      toggle = document.createElement(
        'button'
      );

      toggle.type = 'button';
      toggle.className = (
        'gm-mobile-preset-toggle'
      );

      tools.insertAdjacentElement(
        'beforebegin',
        toggle
      );

      toggle.addEventListener(
        'click',
        () => {
          presetToolsOpen = !presetToolsOpen;
          queuePatch();
        }
      );
    }

    if (!mobile) {
      toggle.hidden = true;
      tools.style.removeProperty(
        'display'
      );
      return;
    }

    toggle.hidden = false;

    toggle.setAttribute(
      'aria-expanded',
      presetToolsOpen
        ? 'true'
        : 'false'
    );

    toggle.innerHTML = (
      presetToolsOpen
        ? '<i class="bi bi-chevron-up"></i> Hide Preset / Apply'
        : '<i class="bi bi-bookmark"></i> Preset / Apply'
    );

    tools.style.setProperty(
      'display',
      presetToolsOpen
        ? 'grid'
        : 'none',
      'important'
    );
  }

  function simplifyDefensePanel() {
    const panel = document.getElementById(PANEL_ID);

    // Scope tablet sticky behavior to pregame Game Management only.
    document.body.classList.toggle(
      'gm-pregame-planning',
      Boolean(panel)
    );

    if (!panel) return;

    const inning = currentInning();
    const title = panel.querySelector('.pde-title');
    const help = panel.querySelector('.pde-help');
    setText(title, `Set Defense — ${fullInningLabel(inning)}`);
    setText(
      help,
      isSubInning(inning)
        ? `Set the defense after this planned change during Inning ${Math.floor(Number.parseFloat(inning))}. Saves automatically.`
        : 'Tap a position to assign or change a player. Saves automatically.'
    );

    const tools = panel.querySelector('.pde-tools');
    const select = document.getElementById('pde-preset');
    const apply = document.getElementById('pde-apply');
    if (select?.options?.length) setText(select.options[0], 'Choose Starting Defense…');
    setText(apply, `Apply to Inning ${shortInningLabel(inning)}`);

    let wrap = tools?.querySelector('.gm-preset-wrap');
    if (tools && select && !wrap) {
      wrap = document.createElement('div');
      wrap.className = 'gm-preset-wrap';
      tools.insertBefore(wrap, select);
      wrap.appendChild(select);
    }

    syncMobilePresetDisclosure(
      panel,
      tools
    );

    if (wrap) {
      let label = wrap.querySelector('.gm-preset-label');
      if (!label) {
        label = document.createElement('label');
        label.className = 'gm-preset-label';
        label.htmlFor = 'pde-preset';
        wrap.insertBefore(label, select);
      }
      setText(label, 'Starting Defense Preset (Optional)');
      wrap.querySelector('.gm-preset-help')?.remove();
    }

    setText(panel.querySelector('.pde-field-caption strong'), 'Current Defense');
    setText(panel.querySelector('.pde-label'), 'Bench');

    const status = panel.querySelector('.pde-status');
    if (status) {
      setText(status.querySelector('.pde-status-note'), 'Saves automatically.');
    }
  }

  function reportShell(collapse) {
    if (!collapse) return null;

    return (
      collapse.closest('.d-none.d-lg-block') ||
      collapse.closest('.card')
    );
  }

  function markPlayingTimeHandled(panel) {
    if (
      !panel ||
      panel.querySelector('#gm-playing-time-handled')
    ) {
      return;
    }

    const marker = document.createElement('span');
    marker.id = 'gm-playing-time-handled';
    marker.hidden = true;

    const status = panel.querySelector('.pde-status');

    if (status) {
      status.insertAdjacentElement(
        'beforebegin',
        marker
      );
    } else {
      panel.appendChild(marker);
    }
  }

  function syncPhonePlayingTimeDisclosure(
    panel,
    summary
  ) {
    if (!panel) return;

    const mobile = window.matchMedia(
      '(max-width: 767.98px)'
    ).matches;

    let toggle = panel.querySelector(
      '.gm-phone-playing-time-toggle'
    );

    if (!mobile || !summary) {
      toggle?.remove();

      if (summary) {
        summary.hidden = false;
      }

      return;
    }

    if (!toggle) {
      toggle = document.createElement(
        'button'
      );

      toggle.type = 'button';

      toggle.className = (
        'gm-phone-playing-time-toggle '
        + 'btn btn-light border w-100 '
        + 'd-flex align-items-center '
        + 'justify-content-between '
        + 'text-start mb-2'
      );

      toggle.addEventListener(
        'click',
        () => {
          phonePlayingTimeOpen = (
            !phonePlayingTimeOpen
          );

          queuePatch();
        }
      );
    }

    if (
      toggle.nextElementSibling !== summary
    ) {
      summary.insertAdjacentElement(
        'beforebegin',
        toggle
      );
    }

    summary.hidden = !phonePlayingTimeOpen;

    toggle.setAttribute(
      'aria-expanded',
      phonePlayingTimeOpen
        ? 'true'
        : 'false'
    );

    toggle.innerHTML = `
      <span>
        <i class="bi bi-person-check me-2"></i>
        <strong>Player Time / Position Summary</strong>
      </span>
      <span class="small text-muted">
        ${phonePlayingTimeOpen ? 'Hide' : 'View'}
        <i class="bi bi-chevron-${phonePlayingTimeOpen ? 'up' : 'down'} ms-1"></i>
      </span>
    `;
  }

  function syncPlayingTimePlacement() {
    const panel = document.getElementById(PANEL_ID);
    let host = document.getElementById(
      'gm-playing-time-report'
    );

    // Once Live Game replaces the pregame defense surface, remove
    // the pregame-only report wrapper as well.
    if (!panel) {
      host?.remove();
      return;
    }

    const desktop = window.matchMedia(
      '(min-width: 992px)'
    ).matches;

    const summary = panel.querySelector(
      '#pde-playing-time-summary'
    );

    const handled = panel.querySelector(
      '#gm-playing-time-handled'
    );

    // Preserve the original portrait-tablet presentation.
    // Phones keep the same data, but collapse the long report by
    // default so the defensive field stays primary.
    if (!desktop) {
      let activeSummary = summary;

      if (!activeSummary && host) {
        const moved = host.querySelector(
          '#pde-playing-time-summary'
        );

        const status = panel.querySelector(
          '.pde-status'
        );

        if (moved && status) {
          status.insertAdjacentElement(
            'beforebegin',
            moved
          );

          activeSummary = moved;
        }
      }

      handled?.remove();
      host?.remove();

      syncPhonePlayingTimeDisclosure(
        panel,
        activeSummary
      );

      return;
    }

    // Desktop/iPad landscape report handling must never inherit
    // phone-only hidden state or its disclosure button.
    syncPhonePlayingTimeDisclosure(
      panel,
      summary
    );

    /*
     * If the current render was already handled, the summary is
     * intentionally outside the panel. Do not rebuild the wrapper.
     */
    if (!summary && handled) {
      return;
    }

    /*
     * A fresh render with no summary means there are no planned
     * defensive innings to summarize. Do not leave stale player-time
     * information from the previous render.
     */
    if (!summary) {
      host?.remove();
      markPlayingTimeHandled(panel);
      return;
    }

    if (!host) {
      host = document.createElement('div');
      host.id = 'gm-playing-time-report';
      host.className = 'd-none d-lg-block';

      host.innerHTML = `
        <div class="card gm-secondary-report">
          <div class="card-header p-0">
            <button
              type="button"
              class="gm-playing-time-toggle"
              data-bs-toggle="collapse"
              data-bs-target="#gmPlayingTimeCollapse"
              aria-expanded="false"
              aria-controls="gmPlayingTimeCollapse"
            >
              <span>
                <i class="bi bi-person-check me-2"></i>
                Player Time / Position Summary
                <small>Fair-play and position totals</small>
              </span>
              <i class="bi bi-chevron-down"></i>
            </button>
          </div>
          <div
            id="gmPlayingTimeCollapse"
            class="collapse"
          >
            <div class="gm-playing-time-body"></div>
          </div>
        </div>
      `;
    }

    const body = host.querySelector(
      '.gm-playing-time-body'
    );

    if (body) {
      // The base defense renderer owns the summary data. We only move
      // its freshly rendered DOM; no rotation state is duplicated.
      body.replaceChildren(summary);
    }

    markPlayingTimeHandled(panel);

    const rotationCollapse = document.getElementById(
      'rotationMatrixCollapse'
    );

    const rotation = reportShell(
      rotationCollapse
    );

    /*
     * Original order is:
     * field -> legacy hidden layout -> Rotation Table -> Bench Summary.
     *
     * Put Player Time immediately after Rotation Table. The hidden
     * legacy layout stays untouched for Live Game restoration.
     */
    if (rotation) {
      if (rotation.nextElementSibling !== host) {
        rotation.insertAdjacentElement(
          'afterend',
          host
        );
      }
    } else if (panel.nextElementSibling !== host) {
      panel.insertAdjacentElement(
        'afterend',
        host
      );
    }
  }

  function collapseSecondaryReportsOnce() {
    if (reportsCollapsed) return;

    const rotation = document.getElementById(
      'rotationMatrixCollapse'
    );

    const bench = document.getElementById(
      'benchReportDesktopCollapse'
    );

    if (!rotation && !bench) return;

    if (rotation) {
      // Rotation Table is the coach's primary all-inning reference.
      // Start it open, but only set the default once so the coach can
      // still collapse it manually afterward.
      rotation.classList.add('show');

      const card = rotation.closest('.card');
      card?.classList.remove('gm-secondary-report');

      const header = rotation.previousElementSibling;
      const trigger = header?.matches?.(
        '[data-bs-toggle="collapse"]'
      )
        ? header
        : header?.querySelector(
            '[data-bs-toggle="collapse"]'
          );

      trigger?.setAttribute(
        'aria-expanded',
        'true'
      );

      const headerText = header?.querySelector(
        'span'
      );

      if (headerText) {
        setHtml(
          headerText,
          '<i class="bi bi-grid-3x3 me-2"></i>Rotation Table'
        );
      }
    }

    if (bench) {
      // Bench Summary remains useful but secondary.
      bench.classList.remove('show');
      bench
        .closest('.card')
        ?.classList.add('gm-secondary-report');

      const header = bench.previousElementSibling;
      const trigger = header?.matches?.(
        '[data-bs-toggle="collapse"]'
      )
        ? header
        : header?.querySelector(
            '[data-bs-toggle="collapse"]'
          );

      trigger?.setAttribute(
        'aria-expanded',
        'false'
      );

      const headerText = header?.querySelector(
        'span'
      );

      if (headerText) {
        setHtml(
          headerText,
          '<i class="bi bi-clipboard-x me-2"></i>Bench Summary'
        );
      }
    }

    reportsCollapsed = true;
  }

  function patch() {
    patchQueued = false;
    installStyles();
    simplifyHeader();
    simplifyInningControls();
    simplifyDefensePanel();
    syncInningPickerPlacement();
    syncPlayingTimePlacement();
    collapseSecondaryReportsOnce();
  }

  function queuePatch() {
    if (patchQueued) return;
    patchQueued = true;
    window.requestAnimationFrame(patch);
  }

  function start() {
    document.addEventListener(
      'click',
      preventActionAnchorJumps,
      true
    );

    window.addEventListener(
      'resize',
      queuePatch,
      {passive:true}
    );

    window.addEventListener(
      'orientationchange',
      queuePatch,
      {passive:true}
    );

    patch();

    const observer = new MutationObserver(
      queuePatch
    );

    observer.observe(
      document.body,
      {
        childList:true,
        subtree:true,
        attributes:true,
        attributeFilter:['class']
      }
    );
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once:true})
    : start();
})();
