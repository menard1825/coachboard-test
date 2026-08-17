(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  const PANEL_ID = 'pregame-defense-editor-v3';
  let reportsCollapsed = false;
  let patchQueued = false;

  const setText = (element, value) => {
    if (element && element.textContent !== value) element.textContent = value;
  };
  const setHtml = (element, value) => {
    if (element && element.innerHTML !== value) element.innerHTML = value;
  };

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
      #${PANEL_ID} .pde-inning{display:none!important}
      #${PANEL_ID} .pde-head{align-items:center!important}
      #${PANEL_ID} .pde-title{font-size:1rem!important}
      #${PANEL_ID} .pde-help{font-size:.72rem!important}
      #${PANEL_ID} .pde-tools{
        grid-template-columns:minmax(0,1fr) auto!important;
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
      #${PANEL_ID} #pde-save{display:none!important}
      #${PANEL_ID} #pde-apply{white-space:nowrap}
      #${PANEL_ID} .pde-status{font-size:.7rem!important}
      #${PANEL_ID} .pde-field-caption strong{font-size:.72rem!important}
      #rotation-card-container .gm-secondary-report .accordion-collapse,
      #rotation-card-container .gm-secondary-report .collapse{scroll-margin-top:90px}
      @media(max-width:575.98px){
        #rotation-card-container .gm-coach-inning-picker{align-items:flex-start!important;flex-wrap:wrap}
        #rotation-card-container .gm-coach-inning-label{width:100%;margin-bottom:2px}
        #rotation-card-container .gm-coach-actions{display:grid!important;grid-template-columns:1fr auto;width:100%}
        #rotation-card-container .gm-coach-actions #copyPreviousInningBtn{width:100%}
        #${PANEL_ID} .pde-tools{grid-template-columns:1fr!important}
        #${PANEL_ID} #pde-apply{width:100%}
      }
    `;
    document.head.appendChild(style);
  }

  function currentInning() {
    const panelValue = document.querySelector(`#${PANEL_ID} .pde-inning strong`)?.textContent?.trim();
    if (panelValue) return panelValue;
    const active = document.querySelector('#inning-btn-group .active, #inning-btn-group input:checked + label, #inning-btn-group input:checked');
    const text = active?.textContent?.trim() || active?.value;
    return text || '1';
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
      menuToggle.title = 'Less-used defense tools';
    }

    const rotationTemplateSelect = document.getElementById('rotationTemplateSelect');
    if (rotationTemplateSelect?.options?.length) setText(rotationTemplateSelect.options[0], 'Load full rotation template…');

    const saveFullTemplate = document.getElementById('saveAsTemplateBtn');
    setHtml(saveFullTemplate, '<i class="bi bi-journal-plus me-1"></i> Save Full Rotation as Template');

    const printCard = document.getElementById('printCardBtn');
    setHtml(printCard, '<i class="bi bi-printer me-1"></i> Print Defense / Lineup Card');

    const deleteRotation = document.getElementById('deleteRotationBtn');
    setHtml(deleteRotation, '<i class="bi bi-trash me-1"></i> Delete Defense Plan');

    if (menu && !document.getElementById('gmSaveCurrentDefensePreset')) {
      const divider = document.createElement('li');
      divider.innerHTML = '<hr class="dropdown-divider">';
      const item = document.createElement('li');
      item.innerHTML = '<button type="button" class="dropdown-item" id="gmSaveCurrentDefensePreset"><i class="bi bi-bookmark-plus me-1"></i> Save Current Defense as Preset</button>';
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
  }

  function addInningOption(menu, id, icon, label, targetId, danger = false) {
    if (!menu || document.getElementById(id)) return;
    const li = document.createElement('li');
    li.innerHTML = `<button type="button" class="dropdown-item ${danger ? 'text-danger' : ''}" id="${id}"><i class="bi bi-${icon} me-2"></i>${label}</button>`;
    li.querySelector('button')?.addEventListener('click', () => document.getElementById(targetId)?.click());
    menu.appendChild(li);
  }

  function simplifyInningControls() {
    const group = document.getElementById('inning-btn-group');
    if (!group) return;

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
      const shouldHide = Number.isFinite(inning) && inning <= 1;
      if (copyPrevious.classList.contains('d-none') !== shouldHide) copyPrevious.classList.toggle('d-none', shouldHide);
      copyPrevious.title = 'Copy the previous inning defense into this inning';
    }

    const toolsToggle = actions?.querySelector('.dropdown-toggle');
    const toolsMenu = toolsToggle?.nextElementSibling;
    if (toolsToggle) {
      setHtml(toolsToggle, '<i class="bi bi-three-dots me-1"></i> Inning Options');
      toolsToggle.title = 'Less-used inning tools';
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
      addInningOption(toolsMenu, 'gmAddSubInningAction', 'node-plus', 'Add Mid-Inning Change', 'addSubInningBtn');
      addInningOption(toolsMenu, 'gmRemoveInningAction', 'dash-circle', 'Remove Last Inning', 'removeInningBtn', true);
    }

    const planner = pickerRow?.closest('.planner-controls');
    if (planner && !planner.querySelector('.gm-coach-help')) {
      const help = document.createElement('div');
      help.className = 'gm-coach-help';
      help.innerHTML = '<i class="bi bi-info-circle me-1"></i>Pick an inning, then tap a position on the field to assign a player. Changes save automatically.';
      pickerRow.insertAdjacentElement('afterend', help);
    }
  }

  function simplifyDefensePanel() {
    const panel = document.getElementById(PANEL_ID);
    if (!panel) return;

    const inning = currentInning();
    const title = panel.querySelector('.pde-title');
    const help = panel.querySelector('.pde-help');
    setText(title, `Set Defense — Inning ${inning}`);
    setText(help, 'Tap a position to assign or change a player. Changes save automatically.');

    const tools = panel.querySelector('.pde-tools');
    const select = document.getElementById('pde-preset');
    const apply = document.getElementById('pde-apply');
    if (select?.options?.length) setText(select.options[0], 'Optional: choose a defense preset…');
    setText(apply, 'Use Preset');

    if (tools && select && !tools.querySelector('.gm-preset-wrap')) {
      const wrap = document.createElement('div');
      wrap.className = 'gm-preset-wrap';
      const label = document.createElement('label');
      label.className = 'gm-preset-label';
      label.htmlFor = 'pde-preset';
      label.textContent = 'Quick Setup (Optional)';
      tools.insertBefore(wrap, select);
      wrap.appendChild(label);
      wrap.appendChild(select);
    }

    setText(panel.querySelector('.pde-field-caption strong'), 'Current Defense');
    setText(panel.querySelector('.pde-label'), 'Bench');

    const status = panel.querySelector('.pde-status');
    if (status) {
      const open = status.querySelector('.open')?.textContent?.trim();
      const desired = open
        ? `<span class="open">${open}</span> <span class="mx-1">•</span> Changes save automatically`
        : '<strong>Defense complete</strong> <span class="mx-1">•</span> Changes save automatically';
      setHtml(status, desired);
    }
  }

  function collapseSecondaryReportsOnce() {
    if (reportsCollapsed) return;
    const ids = ['rotationMatrixCollapse', 'benchReportDesktopCollapse'];
    ids.forEach((id) => {
      const collapse = document.getElementById(id);
      if (!collapse) return;
      collapse.classList.remove('show');
      collapse.closest('.card')?.classList.add('gm-secondary-report');
      const headerText = collapse.previousElementSibling?.querySelector('span');
      if (headerText) {
        if (id === 'rotationMatrixCollapse') setHtml(headerText, '<i class="bi bi-grid-3x3 me-2"></i>Rotation Table');
        if (id === 'benchReportDesktopCollapse') setHtml(headerText, '<i class="bi bi-clipboard-x me-2"></i>Bench Summary');
      }
    });
    reportsCollapsed = ids.some((id) => document.getElementById(id));
  }

  function patch() {
    patchQueued = false;
    installStyles();
    simplifyHeader();
    simplifyInningControls();
    simplifyDefensePanel();
    collapseSecondaryReportsOnce();
  }

  function queuePatch() {
    if (patchQueued) return;
    patchQueued = true;
    window.requestAnimationFrame(patch);
  }

  function start() {
    patch();
    const observer = new MutationObserver(queuePatch);
    observer.observe(document.body, {childList:true, subtree:true,attributes:true,attributeFilter:['class']});
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once:true})
    : start();
})();
