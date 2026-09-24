(() => {
  'use strict';

  const routeMatch = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!routeMatch) return;

  const gameId = Number(routeMatch[1]);
  const PANEL_ID = 'pregame-defense-editor-v3';
  let reportsCollapsed = false;
  let presetToolsOpen = false;
  let phonePlayingTimeOpen = false;
  let coachRailCollapsed = false;
  let coachRailTab = 'rotation';
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
        font-size:var(--cb-text-xs);
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

      /*
       * Plan Options must paint above the sticky inning picker.
       * The picker intentionally uses z-index:1030 on phones/tablets.
       */
      #rotation-card-container .gm-plan-options-menu{
        z-index:1040!important;
      }
      #rotation-card-container .gm-legacy-inning-actions{
        display:none!important;
      }

      #rotation-card-container .gm-coach-apply-actions{
        flex:1 0 100%;
        width:100%;
        display:grid;
        grid-template-columns:
          minmax(0,1.35fr)
          minmax(0,1fr)
          minmax(0,1fr);
        gap:6px;
        margin-top:2px;
      }

      #rotation-card-container .gm-coach-apply-actions .btn{
        min-height:38px;
        border-radius:9px;
        font-size:var(--cb-text-xs);
        font-weight:800;
        white-space:normal;
      }


      #gm-coach-toast-holder .gm-toast-action{
        flex:0 0 auto;
        align-self:center;
        font-weight:850;
      }

      .gm-coach-sheet .modal-content{
        border:0;
        border-radius:16px;
        overflow:hidden;
        box-shadow:0 18px 48px rgba(16,24,40,.22);
      }

      .gm-coach-sheet .modal-header{
        border-bottom:1px solid #e7ebef;
      }

      .gm-coach-sheet .modal-footer{
        border-top:1px solid #e7ebef;
      }

      #gmPickInningsModal .gm-pick-inning-grid{
        display:grid;
        grid-template-columns:repeat(3,minmax(0,1fr));
        gap:8px;
        margin:12px 0;
      }

      #gmPickInningsModal .gm-pick-inning-choice{
        min-height:48px;
        border-radius:10px;
        font-size:1rem;
        font-weight:900;
      }

      #gmPickInningsModal .gm-pick-note{
        color:#667085;
        font-size:.75rem;
        line-height:1.35;
      }

      @media(max-width:575.98px){
        .gm-coach-sheet .modal-dialog{
          min-height:100%;
          margin:0;
          align-items:flex-end;
        }

        .gm-coach-sheet .modal-content{
          width:100%;
          max-height:calc(100dvh - 72px);
          border-radius:18px 18px 0 0;
          padding-bottom:env(safe-area-inset-bottom);
        }

        #gmPickInningsModal .gm-pick-inning-grid{
          grid-template-columns:repeat(3,minmax(0,1fr));
        }

        #gm-coach-toast-holder{
          top:auto!important;
          bottom:calc(env(safe-area-inset-bottom) + 8px)!important;
          left:10px!important;
          right:10px!important;
          padding:0!important;
        }

        #gm-coach-toast-holder .toast{
          width:100%;
        }
      }

      #rotation-card-container #inning-paste-controls.gm-apply-picker{
        margin:8px 0 10px!important;
        border:1px solid #b9d1ec;
        border-radius:10px;
        background:#f3f8fd;
      }

      @media(max-width:575.98px){
        #rotation-card-container .gm-coach-apply-actions{
          grid-template-columns:1fr 1fr;
        }

        #rotation-card-container .gm-coach-apply-actions #gmApplyDefenseAllBtn{
          grid-column:1 / -1;
        }
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
      #${PANEL_ID} .pde-status{font-size:var(--cb-text-xs)!important}
      #${PANEL_ID} .pde-field-caption strong{font-size:.72rem!important}
      #rotation-card-container .gm-secondary-report .accordion-collapse,
      #rotation-card-container .gm-secondary-report .collapse{scroll-margin-top:90px}

      #${PANEL_ID} .gm-mobile-preset-toggle{
        display:none;
      }
      @media(max-width:1199.98px),
             (min-width:1200px) and (max-width:1399.98px) and (min-height:900px) and (max-height:1100px){
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
          font-size:var(--cb-text-xs);
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
             (min-width:640px) and (max-width:991.98px) and (orientation:landscape),
             (min-width:992px) and (max-width:1399.98px) and (min-height:760px) and (orientation:landscape){
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

      /*
       * Landscape iPad Coach Rail
       *
       * The field remains the canonical defensive editor.
       * This rail is read-only and mirrors the canonical Rotation Table.
       */
      #gm-landscape-defense-workspace{
        display:block;
      }

      #gm-landscape-coach-rail{
        display:none;
      }

      @media
        (min-width:992px)
        and (max-width:1399.98px)
        and (min-height:760px)
        and (orientation:landscape){

        #gm-landscape-defense-workspace{
          display:grid;
          grid-template-columns:
            minmax(0,1fr)
            minmax(285px,32%);
          align-items:start;
          gap:10px;
          width:100%;
        }

        #gm-landscape-defense-workspace.gm-rail-collapsed{
          grid-template-columns:minmax(0,1fr) 46px;
        }

        #gm-landscape-defense-workspace > .pde-field-card{
          width:100%!important;
          max-width:none!important;
          min-width:0!important;
          margin-left:0!important;
          margin-right:0!important;
        }

        #gm-landscape-coach-rail{
          display:block;
          min-width:0;
          position:sticky;
          top:116px;
          align-self:start;
          max-height:calc(100vh - 128px);
          overflow:hidden;
          border:1px solid #d8e0e8;
          border-radius:13px;
          background:#fff;
          box-shadow:0 4px 14px rgba(16,24,40,.08);
        }

        #gm-landscape-coach-rail .gm-rail-head{
          min-height:42px;
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:8px;
          padding:7px 8px 7px 10px;
          border-bottom:1px solid #e7ebef;
          background:#fbfcfd;
        }

        #gm-landscape-coach-rail .gm-rail-title{
          min-width:0;
        }

        #gm-landscape-coach-rail .gm-rail-title strong{
          display:block;
          color:#172033;
          font-size:.75rem;
          line-height:1.1;
          font-weight:900;
        }

        #gm-landscape-coach-rail .gm-rail-title small{
          display:block;
          margin-top:2px;
          color:#667085;
          font-size:.55rem;
          line-height:1.15;
          font-weight:650;
        }

        #gm-landscape-coach-rail .gm-rail-collapse{
          flex:0 0 auto;
          width:30px;
          height:30px;
          display:inline-flex;
          align-items:center;
          justify-content:center;
          padding:0;
          border:1px solid #d7dde5;
          border-radius:8px;
          background:#fff;
          color:#344054;
        }

        #gm-landscape-coach-rail .gm-rail-tabs{
          display:grid;
          grid-template-columns:1fr 1fr;
          gap:5px;
          padding:7px;
          border-bottom:1px solid #edf0f3;
        }

        #gm-landscape-coach-rail .gm-rail-tab{
          min-height:32px;
          border:1px solid #d7dde5;
          border-radius:8px;
          background:#f8fafc;
          color:#475467;
          font-size:.62rem;
          line-height:1;
          font-weight:850;
        }

        #gm-landscape-coach-rail .gm-rail-tab.active{
          border-color:#173b78;
          background:#173b78;
          color:#fff;
        }

        #gm-landscape-coach-rail .gm-rail-body{
          max-height:calc(100vh - 220px);
          overflow:auto;
          overscroll-behavior:contain;
          padding:8px;
        }

        #gm-landscape-coach-rail .gm-rail-summary{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:8px;
          margin-bottom:7px;
          padding:7px 8px;
          border:1px solid #e4e7ec;
          border-radius:9px;
          background:#f8fafc;
        }

        #gm-landscape-coach-rail .gm-rail-summary strong{
          color:#172033;
          font-size:.66rem;
          line-height:1.1;
        }

        #gm-landscape-coach-rail .gm-rail-summary span{
          color:#667085;
          font-size:.55rem;
          font-weight:750;
          white-space:nowrap;
        }

        #gm-landscape-coach-rail .gm-rail-grid-head,
        #gm-landscape-coach-rail .gm-rail-row{
          display:grid;
          grid-template-columns:minmax(0,1fr) 52px 52px;
          align-items:center;
          gap:4px;
        }

        #gm-landscape-coach-rail .gm-rail-grid-head{
          padding:0 6px 4px;
          color:#667085;
          font-size:.49rem;
          text-transform:uppercase;
          letter-spacing:.05em;
          font-weight:900;
        }

        #gm-landscape-coach-rail .gm-rail-row{
          min-height:31px;
          padding:5px 6px;
          border-top:1px solid #eef1f4;
        }

        #gm-landscape-coach-rail .gm-rail-player{
          min-width:0;
          color:#26354c;
          font-size:.61rem;
          line-height:1.1;
          font-weight:800;
          white-space:normal;
          overflow-wrap:anywhere;
        }

        #gm-landscape-coach-rail .gm-rail-pos{
          min-height:23px;
          display:flex;
          align-items:center;
          justify-content:center;
          padding:2px 4px;
          border-radius:6px;
          background:#eef4fb;
          color:#173b78;
          font-size:.55rem;
          line-height:1;
          font-weight:900;
          text-align:center;
        }

        #gm-landscape-coach-rail .gm-rail-pos.bench{
          background:#f2f4f7;
          color:#667085;
          font-size:.48rem;
        }

        #gm-landscape-coach-rail .gm-rail-bench-section{
          margin-bottom:9px;
          padding:8px;
          border:1px solid #e4e7ec;
          border-radius:9px;
          background:#fbfcfd;
        }

        #gm-landscape-coach-rail .gm-rail-bench-head{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:8px;
          margin-bottom:6px;
        }

        #gm-landscape-coach-rail .gm-rail-bench-head strong{
          color:#172033;
          font-size:.64rem;
        }

        #gm-landscape-coach-rail .gm-rail-count{
          min-width:22px;
          height:20px;
          display:inline-flex;
          align-items:center;
          justify-content:center;
          padding:0 6px;
          border-radius:999px;
          background:#eef2f6;
          color:#475467;
          font-size:.52rem;
          font-weight:900;
        }

        #gm-landscape-coach-rail .gm-rail-bench-list{
          display:flex;
          flex-wrap:wrap;
          gap:4px;
        }

        #gm-landscape-coach-rail .gm-rail-bench-chip{
          max-width:100%;
          padding:4px 6px;
          border:1px solid #e0e5eb;
          border-radius:7px;
          background:#fff;
          color:#344054;
          font-size:.55rem;
          line-height:1.1;
          font-weight:750;
          white-space:normal;
          overflow-wrap:anywhere;
        }

        #gm-landscape-coach-rail .gm-rail-empty{
          padding:14px 8px;
          color:#667085;
          font-size:.61rem;
          line-height:1.35;
          text-align:center;
        }

        #gm-landscape-coach-rail .gm-rail-full-table{
          width:100%;
          min-height:32px;
          margin-top:8px;
          border:1px solid #ccd6e1;
          border-radius:8px;
          background:#fff;
          color:#173b78;
          font-size:.59rem;
          font-weight:850;
        }

        #gm-landscape-defense-workspace.gm-rail-collapsed
        #gm-landscape-coach-rail{
          width:46px;
        }

        #gm-landscape-defense-workspace.gm-rail-collapsed
        #gm-landscape-coach-rail .gm-rail-head{
          min-height:112px;
          padding:6px;
          flex-direction:column;
          justify-content:flex-start;
        }

        #gm-landscape-defense-workspace.gm-rail-collapsed
        #gm-landscape-coach-rail .gm-rail-title{
          flex:1 1 auto;
          width:100%;
          display:flex;
          align-items:center;
          justify-content:center;
        }

        #gm-landscape-defense-workspace.gm-rail-collapsed
        #gm-landscape-coach-rail .gm-rail-title strong{
          writing-mode:vertical-rl;
          transform:rotate(180deg);
          font-size:.58rem;
          letter-spacing:.04em;
        }

        #gm-landscape-defense-workspace.gm-rail-collapsed
        #gm-landscape-coach-rail .gm-rail-title small,
        #gm-landscape-defense-workspace.gm-rail-collapsed
        #gm-landscape-coach-rail .gm-rail-tabs,
        #gm-landscape-defense-workspace.gm-rail-collapsed
        #gm-landscape-coach-rail .gm-rail-body{
          display:none!important;
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

  function toast(
    message,
    kind = 'success',
    action = null
  ) {
    let holder =
      document.getElementById(
        'gm-coach-toast-holder'
      );

    if (!holder) {
      holder =
        document.createElement('div');

      holder.id =
        'gm-coach-toast-holder';

      holder.className =
        'toast-container position-fixed top-0 end-0 p-3';

      holder.style.zIndex = '6000';

      document.body.appendChild(
        holder
      );
    }

    const el =
      document.createElement('div');

    el.className =
      `toast text-bg-${kind} border-0`;

    el.innerHTML = `
      <div class="d-flex align-items-center">
        <div class="toast-body fw-semibold"></div>
        ${
          action
            ? '<button type="button" class="btn btn-sm btn-light me-2 gm-toast-action"></button>'
            : ''
        }
        <button
          type="button"
          class="btn-close btn-close-white me-2"
          data-bs-dismiss="toast"
          aria-label="Close"
        ></button>
      </div>
    `;

    el.querySelector(
      '.toast-body'
    ).textContent = message;

    const actionButton =
      el.querySelector(
        '.gm-toast-action'
      );

    if (
      actionButton &&
      action?.label &&
      typeof action?.onClick === 'function'
    ) {
      actionButton.textContent =
        action.label;

      actionButton.addEventListener(
        'click',
        () => {
          bootstrap.Toast
            .getOrCreateInstance(el)
            .hide();

          action.onClick();
        },
        {once:true}
      );
    }

    holder.appendChild(el);

    const instance =
      bootstrap.Toast.getOrCreateInstance(
        el,
        {
          delay: action
            ? 6000
            : 2600,
        }
      );

    el.addEventListener(
      'hidden.bs.toast',
      () => el.remove(),
      {once:true}
    );

    instance.show();
  }


  function ensureCoachConfirmModal() {
    let modal =
      document.getElementById(
        'gmCoachConfirmModal'
      );

    if (modal) return modal;

    modal =
      document.createElement('div');

    modal.id =
      'gmCoachConfirmModal';

    modal.className =
      'modal fade gm-coach-sheet';

    modal.tabIndex = -1;

    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title mb-0"></h5>
            <button
              type="button"
              class="btn-close"
              data-bs-dismiss="modal"
              aria-label="Close"
            ></button>
          </div>

          <div class="modal-body">
            <p class="gm-confirm-message mb-0"></p>
          </div>

          <div class="modal-footer">
            <button
              type="button"
              class="btn btn-outline-secondary"
              data-bs-dismiss="modal"
            >
              Cancel
            </button>

            <button
              type="button"
              class="btn btn-primary"
              data-gm-confirm-action
            >
              Continue
            </button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(
      modal
    );

    modal
      .querySelector(
        '[data-gm-confirm-action]'
      )
      ?.addEventListener(
        'click',
        event => {
          // Confirm is one-shot while Bootstrap is closing the sheet.
          // A second tap must not call hide() again during the fade,
          // because competing hide calls can leave the reusable modal
          // stuck in its visible/transitioning state.
          if (
            modal.dataset
              .gmConfirmClosing === '1'
          ) {
            return;
          }

          modal.dataset
            .gmConfirmClosing = '1';

          const confirmButton =
            event.currentTarget;

          confirmButton.disabled =
            true;

          const action =
            modal._gmConfirmAction;

          // Consume the pending action immediately as an independent
          // guard against executing it more than once.
          modal._gmConfirmAction =
            null;

          const instance =
            bootstrap.Modal
              .getOrCreateInstance(
                modal
              );

          modal.addEventListener(
            'hidden.bs.modal',
            () => {
              delete modal.dataset
                .gmConfirmClosing;

              confirmButton.disabled =
                false;

              if (
                typeof action ===
                'function'
              ) {
                action();
              }
            },
            {once:true}
          );

          instance.hide();
        }
      );

    return modal;
  }


  function showCoachConfirm({
    title,
    message,
    confirmLabel = 'Continue',
    danger = false,
    onConfirm,
  }) {
    const modal =
      ensureCoachConfirmModal();

    setText(
      modal.querySelector(
        '.modal-title'
      ),
      title
    );

    setText(
      modal.querySelector(
        '.gm-confirm-message'
      ),
      message
    );

    const confirm =
      modal.querySelector(
        '[data-gm-confirm-action]'
      );

    if (confirm) {
      confirm.textContent =
        confirmLabel;

      confirm.classList.toggle(
        'btn-danger',
        danger
      );

      confirm.classList.toggle(
        'btn-primary',
        !danger
      );

      // Do not allow confirmation while Bootstrap is still opening
      // the modal. hide() can be ignored during the show transition,
      // which would otherwise leave the one-shot closing guard stuck.
      confirm.disabled =
        true;
    }

    delete modal.dataset
      .gmConfirmClosing;

    modal._gmConfirmAction =
      onConfirm;

    modal.addEventListener(
      'shown.bs.modal',
      () => {
        if (confirm) {
          confirm.disabled =
            false;
        }
      },
      {once:true}
    );

    bootstrap.Modal
      .getOrCreateInstance(
        modal
      )
      .show();
  }


  function ensurePickInningsModal() {
    let modal =
      document.getElementById(
        'gmPickInningsModal'
      );

    if (modal) return modal;

    modal =
      document.createElement('div');

    modal.id =
      'gmPickInningsModal';

    modal.className =
      'modal fade gm-coach-sheet';

    modal.tabIndex = -1;

    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <h5 class="modal-title mb-0">
                Pick Innings
              </h5>
              <div class="small text-muted gm-pick-source"></div>
            </div>

            <button
              type="button"
              class="btn-close"
              data-bs-dismiss="modal"
              aria-label="Close"
            ></button>
          </div>

          <div class="modal-body">
            <div class="fw-semibold">
              Which innings should use this defense?
            </div>

            <div class="gm-pick-inning-grid"></div>

            <div class="gm-pick-note">
              Planned mid-inning changes stay as-is.
            </div>
          </div>

          <div class="modal-footer">
            <button
              type="button"
              class="btn btn-outline-secondary"
              data-bs-dismiss="modal"
            >
              Cancel
            </button>

            <button
              type="button"
              class="btn btn-primary"
              data-gm-pick-apply
              disabled
            >
              Apply Defense
            </button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(
      modal
    );

    modal.addEventListener(
      'click',
      event => {
        const choice =
          event.target.closest(
            '[data-gm-pick-inning]'
          );

        if (choice) {
          const active =
            choice.getAttribute(
              'aria-pressed'
            ) === 'true';

          choice.setAttribute(
            'aria-pressed',
            active
              ? 'false'
              : 'true'
          );

          choice.classList.toggle(
            'active',
            !active
          );

          modal
            .querySelector(
              '[data-gm-pick-apply]'
            )
            ?.toggleAttribute(
              'disabled',
              !modal.querySelector(
                '[data-gm-pick-inning][aria-pressed="true"]'
              )
            );

          return;
        }

        const apply =
          event.target.closest(
            '[data-gm-pick-apply]'
          );

        if (!apply) return;

        const selected =
          Array.from(
            modal.querySelectorAll(
              '[data-gm-pick-inning][aria-pressed="true"]'
            )
          ).map(
            button =>
              button.dataset.gmPickInning
          );

        const expectedSource =
          modal.dataset.gmSourceInning;

        const context =
          defenseApplyContext();

        if (!context) return;

        if (
          context.current !==
          expectedSource
        ) {
          bootstrap.Modal
            .getOrCreateInstance(
              modal
            )
            .hide();

          toast(
            'The selected inning changed. Open Pick Innings again.',
            'warning'
          );

          return;
        }

        copyDefenseToTargets(
          context,
          selected
        );

        bootstrap.Modal
          .getOrCreateInstance(
            modal
          )
          .hide();
      }
    );

    return modal;
  }


  function openPickInningsModal() {
    const context =
      defenseApplyContext();

    if (!context) return;

    const targets =
      baseInningKeys(
        context.rotation
      ).filter(
        inning =>
          inning !== context.current
      );

    if (!targets.length) {
      toast(
        'There are no other innings to update.',
        'warning'
      );

      return;
    }

    const modal =
      ensurePickInningsModal();

    modal.dataset.gmSourceInning =
      context.current;

    setText(
      modal.querySelector(
        '.modal-title'
      ),
      `Copy Inning ${context.current}`
    );

    setText(
      modal.querySelector(
        '.gm-pick-source'
      ),
      'Pick exactly where to use this defense.'
    );

    const grid =
      modal.querySelector(
        '.gm-pick-inning-grid'
      );

    grid.innerHTML =
      targets
        .map(
          inning => `
            <button
              type="button"
              class="btn btn-outline-primary gm-pick-inning-choice"
              data-gm-pick-inning="${inning}"
              aria-pressed="false"
            >
              ${inning}
            </button>
          `
        )
        .join('');

    modal
      .querySelector(
        '[data-gm-pick-apply]'
      )
      ?.setAttribute(
        'disabled',
        ''
      );

    bootstrap.Modal
      .getOrCreateInstance(
        modal
      )
      .show();
  }

  function preventActionAnchorJumps(event) {
    const action = event.target.closest('#copyInningBtn, #clearInningBtn, #saveAsTemplateBtn, #printCardBtn, #deleteRotationBtn, #saveRotationBtn');
    if (action?.tagName === 'A') event.preventDefault();
  }

  function removeCurrentMidInningChange() {
    const raw =
      currentInning();

    if (!isSubInning(raw)) return;

    const base =
      String(
        Math.floor(
          Number.parseFloat(raw)
        )
      );

    const display =
      shortInningLabel(raw);

    showCoachConfirm({
      title:
        `Remove planned change ${display}?`,

      message:
        `The normal Inning ${base} defense will stay in place.`,

      confirmLabel:
        'Remove',

      danger:
        true,

      onConfirm:
        () => {
          const rotation =
            window.CBPregameRotation
              .getRotation(
                'Rotation'
              );

          if (
            !Object.prototype
              .hasOwnProperty.call(
                rotation.innings,
                raw
              )
          ) {
            toast(
              'That planned change was not found. Refresh the page and try again.',
              'danger'
            );

            return;
          }

          delete rotation.innings[raw];

          document.querySelector(
            `#inning-btn-group input[name="inning-radio"][value="${CSS.escape(base)}"]`
          )?.click();

          window.CBPregameRotation
            .commitLocalChange(
              'Rotation',
              false
            );

          toast(
            `Removed planned change ${display}.`
          );

          queuePatch();
        },
    });
  }

  function simplifyHeader() {
    const title =
      document.getElementById(
        'rotation-editor-title'
      );

    setText(
      title,
      'Set Defense'
    );

    const liveToggle =
      document.getElementById(
        'liveGameModeToggle'
      );

    const liveWrap =
      liveToggle?.closest(
        '.form-check'
      );

    if (
      liveWrap &&
      !liveWrap.classList.contains(
        'd-none'
      )
    ) {
      liveWrap.classList.add(
        'd-none'
      );

      liveWrap.setAttribute(
        'aria-hidden',
        'true'
      );
    }

    const saveRotationDesktop =
      document.getElementById(
        'saveRotationBtn'
      );

    saveRotationDesktop
      ?.closest('li')
      ?.classList.add(
        'd-none'
      );

    document
      .getElementById(
        'saveRotationBtnMobile'
      )
      ?.classList.add(
        'd-none'
      );

    const cardHeader =
      title?.closest(
        '.card-header'
      );

    const menuToggle =
      cardHeader?.querySelector(
        '.dropdown-toggle'
      );

    const menu =
      menuToggle
        ?.nextElementSibling;

    if (
      menuToggle &&
      menuToggle.dataset
        .coachSimplified !== '1'
    ) {
      menuToggle.dataset
        .coachSimplified = '1';

      setHtml(
        menuToggle,
        '<i class="bi bi-sliders me-1"></i> Plan Options'
      );

      menuToggle.title =
        'Defense plan tools';
    }

    const rotationTemplateSelect =
      document.getElementById(
        'rotationTemplateSelect'
      );

    if (
      rotationTemplateSelect
        ?.options
        ?.length
    ) {
      setText(
        rotationTemplateSelect
          .options[0],
        'Load saved defense plan…'
      );
    }

    if (
      menu &&
      rotationTemplateSelect &&
      !document.getElementById(
        'gmFullGamePlanHeader'
      )
    ) {
      const templateItem =
        rotationTemplateSelect
          .closest('li');

      if (templateItem) {
        const header =
          document.createElement(
            'li'
          );

        header.id =
          'gmFullGamePlanHeader';

        header.innerHTML =
          '<div class="dropdown-header">Saved plans</div>';

        menu.insertBefore(
          header,
          templateItem
        );
      }
    }

    setHtml(
      document.getElementById(
        'saveAsTemplateBtn'
      ),
      '<i class="bi bi-journal-plus me-1"></i> Save Current Plan'
    );

    setHtml(
      document.getElementById(
        'printCardBtn'
      ),
      '<i class="bi bi-printer me-1"></i> Print Defense / Lineup'
    );

    setHtml(
      document.getElementById(
        'deleteRotationBtn'
      ),
      '<i class="bi bi-trash me-1"></i> Delete Plan'
    );

    if (
      menu &&
      !document.getElementById(
        'gmSaveCurrentDefensePreset'
      )
    ) {
      const item =
        document.createElement('li');

      item.innerHTML = `
        <button
          type="button"
          class="dropdown-item"
          id="gmSaveCurrentDefensePreset"
        >
          <i class="bi bi-bookmark-plus me-1"></i>
          Save Inning as Defense Preset
        </button>
      `;

      menu.appendChild(item);

      item.querySelector(
        'button'
      )?.addEventListener(
        'click',
        () =>
          document
            .getElementById(
              'pde-save'
            )
            ?.click()
      );
    }

    if (
      menu &&
      !document.getElementById(
        'gmPlanMidInningChange'
      )
    ) {
      const item =
        document.createElement('li');

      item.innerHTML = `
        <button
          type="button"
          class="dropdown-item"
          id="gmPlanMidInningChange"
        >
          <i class="bi bi-arrow-left-right me-1"></i>
          Plan a Change During This Inning…
        </button>
      `;

      menu.appendChild(item);

      item.querySelector(
        'button'
      )?.addEventListener(
        'click',
        () => {
          const raw =
            currentInning();

          const base =
            Math.floor(
              Number.parseFloat(raw)
            );

          if (isSubInning(raw)) {
            toast(
              'You are already editing a planned change during this inning.',
              'warning'
            );

            return;
          }

          showCoachConfirm({
            title:
              `Plan a change during Inning ${base}?`,

            message:
              'Use this only for a defensive change during the same inning. Normal inning-to-inning changes do not need this.',

            confirmLabel:
              'Plan Change',

            onConfirm:
              () =>
                document
                  .getElementById(
                    'addSubInningBtn'
                  )
                  ?.click(),
          });
        }
      );
    }
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



  function cloneDefense(alignment) {
    return JSON.parse(
      JSON.stringify(
        alignment || {}
      )
    );
  }

  function inningKeys(rotation) {
    return Object.keys(
      rotation?.innings || {}
    ).sort(
      (a, b) =>
        Number.parseFloat(a) -
        Number.parseFloat(b)
    );
  }

  function baseInningKeys(rotation) {
    return inningKeys(rotation).filter(
      inning => !isSubInning(inning)
    );
  }

  function defenseApplyContext() {
    const store =
      window.CBPregameRotation;

    if (!store) {
      toast(
        'Defense planner is still loading. Try again.',
        'warning'
      );

      return null;
    }

    const rotation =
      store.getRotation(
        'Rotation'
      );

    const current =
      currentInning();

    if (isSubInning(current)) {
      toast(
        'Return to the normal inning before copying this defense.',
        'warning'
      );

      return null;
    }

    const source =
      rotation
        ?.innings
        ?.[current];

    if (
      !source ||
      !Object.values(
        source
      ).some(Boolean)
    ) {
      toast(
        `Set the defense for Inning ${current} first.`,
        'warning'
      );

      return null;
    }

    return {
      store,
      rotation,
      current,
      source,
    };
  }


  function sameDefense(
    left,
    right
  ) {
    const normalize =
      value =>
        Object.entries(
          value || {}
        ).sort(
          ([a], [b]) =>
            a.localeCompare(b)
        );

    return (
      JSON.stringify(
        normalize(left)
      ) ===
      JSON.stringify(
        normalize(right)
      )
    );
  }


  function targetInningLabel(
    targets
  ) {
    if (!targets.length) {
      return 'selected innings';
    }

    if (targets.length === 1) {
      return `Inning ${targets[0]}`;
    }

    const numbers =
      targets.map(
        value =>
          Number.parseInt(
            value,
            10
          )
      );

    const contiguous =
      numbers.every(
        (value, index) =>
          index === 0 ||
          value ===
            numbers[index - 1] + 1
      );

    if (
      contiguous &&
      targets.length >= 3
    ) {
      return (
        `Innings ${targets[0]}–`
        + `${targets[targets.length - 1]}`
      );
    }

    return (
      'Innings '
      + targets.join(', ')
    );
  }


  function copyDefenseToTargets(
    context,
    requestedTargets
  ) {
    const valid =
      new Set(
        baseInningKeys(
          context.rotation
        )
      );

    const targets =
      Array.from(
        new Set(
          requestedTargets
            .map(String)
            .filter(
              inning =>
                inning !==
                  context.current &&
                valid.has(inning)
            )
        )
      ).sort(
        (a, b) =>
          Number.parseFloat(a) -
          Number.parseFloat(b)
      );

    if (!targets.length) {
      toast(
        'Pick at least one other inning.',
        'warning'
      );

      return false;
    }

    const before = {};

    targets.forEach(
      inning => {
        before[inning] =
          cloneDefense(
            context.rotation
              .innings[inning]
          );
      }
    );

    const applied =
      cloneDefense(
        context.source
      );

    targets.forEach(
      inning => {
        context.rotation
          .innings[inning] =
            cloneDefense(
              context.source
            );
      }
    );

    context.store
      .commitLocalChange(
        'Rotation',
        false
      );

    const label =
      targetInningLabel(
        targets
      );

    toast(
      `Copied Inning ${context.current} to ${label}.`,
      'success',
      {
        label:
          'Undo',

        onClick:
          () => {
            const rotation =
              context.store
                .getRotation(
                  'Rotation'
                );

            const unchanged =
              targets.every(
                inning =>
                  sameDefense(
                    rotation
                      .innings[inning],
                    applied
                  )
              );

            if (!unchanged) {
              toast(
                'Defense changed since then, so Undo was not applied.',
                'warning'
              );

              return;
            }

            targets.forEach(
              inning => {
                rotation
                  .innings[inning] =
                    cloneDefense(
                      before[inning]
                    );
              }
            );

            context.store
              .commitLocalChange(
                'Rotation',
                false
              );

            toast(
              'Defense copy undone.'
            );

            queuePatch();
          },
      }
    );

    queuePatch();

    return true;
  }


  function applyCurrentDefense(
    scope
  ) {
    const context =
      defenseApplyContext();

    if (!context) return;

    const currentNumber =
      Number.parseFloat(
        context.current
      );

    let targets =
      baseInningKeys(
        context.rotation
      ).filter(
        inning =>
          inning !==
          context.current
      );

    if (scope === 'remaining') {
      targets =
        targets.filter(
          inning =>
            Number.parseFloat(
              inning
            ) >
            currentNumber
        );
    }

    if (!targets.length) {
      toast(
        scope === 'remaining'
          ? 'There are no later innings to update.'
          : 'There are no other innings to update.',
        'warning'
      );

      return;
    }

    copyDefenseToTargets(
      context,
      targets
    );
  }

  function preventToolHashJump(element) {
    if (
      !element ||
      element.dataset.gmPreventHashJump === '1'
    ) {
      return;
    }

    element.dataset.gmPreventHashJump = '1';

    element.addEventListener(
      'click',
      event => {
        event.preventDefault();
      }
    );
  }

  function ensurePlanInningTools() {
    const title =
      document.getElementById(
        'rotation-editor-title'
      );

    const menu =
      title
        ?.closest('.card-header')
        ?.querySelector(
          '.dropdown-toggle'
        )
        ?.nextElementSibling;

    if (!menu) return;

    menu.classList.add(
      'gm-plan-options-menu'
    );

    let header =
      document.getElementById(
        'gmPlanInningToolsHeader'
      );

    if (!header) {
      header =
        document.createElement('li');

      header.id =
        'gmPlanInningToolsHeader';

      header.innerHTML =
        '<div class="dropdown-header">Inning setup</div>';

      menu.appendChild(header);

      const definitions = [
        {
          id:
            'gmPlanUsePreviousInning',
          icon:
            'copy',
          label:
            'Use Previous Inning',
          target:
            'copyPreviousInningBtn',
          hidden:
            true,
        },
        {
          id:
            'gmPlanAddInning',
          icon:
            'plus-circle',
          label:
            'Add Another Inning',
          target:
            'addInningBtn',
        },
        {
          id:
            'gmPlanRemoveLastInning',
          icon:
            'dash-circle',
          label:
            'Remove Last Inning',
          target:
            'removeInningBtn',
          danger:
            true,
        },
        {
          id:
            'gmPlanClearCurrentInning',
          icon:
            'eraser',
          label:
            'Clear Current Inning',
          target:
            'clearInningBtn',
          danger:
            true,
          hidden:
            true,
        },
      ];

      definitions.forEach(
        definition => {
          const li =
            document.createElement(
              'li'
            );

          if (
            definition.hidden
          ) {
            li.classList.add(
              'd-none'
            );
          }

          li.innerHTML = `
            <button
              type="button"
              class="dropdown-item ${
                definition.danger
                  ? 'text-danger'
                  : ''
              }"
              id="${definition.id}"
            >
              <i class="bi bi-${definition.icon} me-2"></i>
              ${definition.label}
            </button>
          `;

          li.querySelector(
            'button'
          )?.addEventListener(
            'click',
            () => {
              document
                .getElementById(
                  definition.target
                )
                ?.click();
            }
          );

          menu.appendChild(li);
        }
      );

      const removeSub =
        document.createElement(
          'li'
        );

      removeSub.innerHTML = `
        <button
          type="button"
          class="dropdown-item text-danger d-none"
          id="gmRemoveCurrentSubInning"
        >
          <i class="bi bi-trash me-2"></i>
          Remove This Planned Change
        </button>
      `;

      removeSub
        .querySelector(
          'button'
        )
        ?.addEventListener(
          'click',
          removeCurrentMidInningChange
        );

      menu.appendChild(
        removeSub
      );
    }

    const sub =
      isSubInning();

    [
      'gmPlanAddInning',
      'gmPlanRemoveLastInning',
      'gmPlanMidInningChange',
    ].forEach(
      id => {
        document
          .getElementById(id)
          ?.closest('li')
          ?.classList.toggle(
            'd-none',
            sub
          );
      }
    );

    document
      .getElementById(
        'gmRemoveCurrentSubInning'
      )
      ?.classList.toggle(
        'd-none',
        !sub
      );

    // The old Bootstrap separators are no longer useful now that the
    // menu has two clear coach-facing sections.
    menu
      .querySelectorAll(
        ':scope > li'
      )
      .forEach(
        li => {
          if (
            li.querySelector(
              ':scope > hr.dropdown-divider'
            )
          ) {
            li.classList.add(
              'd-none'
            );
          }
        }
      );

    const visibleOrder = [
      document.getElementById(
        'gmPlanInningToolsHeader'
      ),
      document
        .getElementById(
          'gmPlanAddInning'
        )
        ?.closest('li'),
      document
        .getElementById(
          'gmPlanRemoveLastInning'
        )
        ?.closest('li'),
      document
        .getElementById(
          'gmPlanMidInningChange'
        )
        ?.closest('li'),
      document
        .getElementById(
          'gmRemoveCurrentSubInning'
        )
        ?.closest('li'),
      document.getElementById(
        'gmFullGamePlanHeader'
      ),
      document
        .getElementById(
          'rotationTemplateSelect'
        )
        ?.closest('li'),
      document
        .getElementById(
          'saveAsTemplateBtn'
        )
        ?.closest('li'),
      document
        .getElementById(
          'gmSaveCurrentDefensePreset'
        )
        ?.closest('li'),
      document
        .getElementById(
          'printCardBtn'
        )
        ?.closest('li'),
      document
        .getElementById(
          'deleteRotationBtn'
        )
        ?.closest('li'),
    ].filter(Boolean);

    // Reordering existing children creates childList mutations.
    // Because this module observes body mutations and queues patch(),
    // doing this on every patch creates a perpetual observer/rAF loop.
    // Once all expected items exist, establish the coach-facing order
    // exactly once.
    if (
      visibleOrder.length >= 11 &&
      menu.dataset.gmOrdered !== '1'
    ) {
      visibleOrder.forEach(
        item =>
          menu.appendChild(
            item
          )
      );

      menu.dataset.gmOrdered =
        '1';
    }
  }

  function ensureApplyControls(
    pickerRow,
    legacyActions
  ) {
    if (!pickerRow) return;

    legacyActions
      ?.classList.add(
        'gm-legacy-inning-actions'
      );

    let controls =
      document.querySelector(
        '#rotation-card-container .gm-coach-apply-actions'
      );

    if (!controls) {
      controls =
        document.createElement(
          'div'
        );

      controls.className =
        'gm-coach-apply-actions';

      controls.innerHTML = `
        <button
          type="button"
          class="btn btn-primary btn-sm"
          id="gmApplyDefenseAllBtn"
        >
          <i class="bi bi-layers me-1"></i>
          Apply to All Innings
        </button>

        <button
          type="button"
          class="btn btn-outline-primary btn-sm"
          id="gmApplyDefenseRemainingBtn"
        >
          Apply to Later Innings
        </button>

        <button
          type="button"
          class="btn btn-outline-secondary btn-sm"
          id="gmChooseDefenseInningsBtn"
        >
          Pick Innings
        </button>
      `;

      pickerRow.insertAdjacentElement(
        'afterend',
        controls
      );

      controls
        .querySelector(
          '#gmApplyDefenseAllBtn'
        )
        ?.addEventListener(
          'click',
          () =>
            applyCurrentDefense(
              'all'
            )
        );

      controls
        .querySelector(
          '#gmApplyDefenseRemainingBtn'
        )
        ?.addEventListener(
          'click',
          () =>
            applyCurrentDefense(
              'remaining'
            )
        );

      controls
        .querySelector(
          '#gmChooseDefenseInningsBtn'
        )
        ?.addEventListener(
          'click',
          openPickInningsModal
        );
    }

    controls.classList.toggle(
      'd-none',
      isSubInning()
    );
  }

  function simplifyInningControls() {
    const group =
      document.getElementById(
        'inning-btn-group'
      );

    if (!group) return;

    syncSubInningSelectorLabels(
      group
    );

    const pickerRow =
      group.closest(
        '.d-flex.align-items-center'
      );

    if (pickerRow) {
      pickerRow.classList.add(
        'gm-coach-inning-picker'
      );

      if (
        !pickerRow.querySelector(
          '.gm-coach-inning-label'
        )
      ) {
        const label =
          document.createElement(
            'span'
          );

        label.className =
          'gm-coach-inning-label';

        label.textContent =
          'Choose Inning';

        pickerRow.insertBefore(
          label,
          group
        );
      }
    }

    const addButton =
      document.getElementById(
        'addInningBtn'
      );

    const oldAdvancedGroup =
      addButton?.closest(
        '.btn-group'
      );

    oldAdvancedGroup
      ?.classList.add(
        'd-none'
      );

    const copyPrevious =
      document.getElementById(
        'copyPreviousInningBtn'
      );

    const legacyActions =
      copyPrevious?.parentElement;

    preventToolHashJump(
      document.getElementById(
        'copyInningBtn'
      )
    );

    preventToolHashJump(
      document.getElementById(
        'clearInningBtn'
      )
    );

    ensureApplyControls(
      pickerRow,
      legacyActions
    );

    const paste =
      document.getElementById(
        'inning-paste-controls'
      );

    if (
      pickerRow &&
      paste &&
      pickerRow.nextElementSibling !==
        paste
    ) {
      paste.classList.add(
        'gm-apply-picker'
      );

      pickerRow
        .insertAdjacentElement(
          'afterend',
          paste
        );
    }

    ensurePlanInningTools();

    let help =
      document.getElementById(
        'gm-defense-apply-help'
      );

    if (
      pickerRow &&
      !help
    ) {
      help =
        document.createElement(
          'div'
        );

      help.id =
        'gm-defense-apply-help';

      help.className =
        'gm-coach-help';

      help.innerHTML =
        '<i class="bi bi-info-circle me-1"></i>'
        + 'Edit this inning, then apply it to other innings. '
        + 'Adding a new inning automatically copies the previous inning.';

      pickerRow
        .insertAdjacentElement(
          'afterend',
          help
        );
    }

    help?.classList.toggle(
      'd-none',
      isSubInning()
    );
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
      '(min-width: 640px) and '
      + '(max-width: 991.98px) and '
      + '(orientation: landscape), '
      + '(min-width: 992px) and '
      + '(max-width: 1399.98px) and '
      + '(min-height: 760px) and '
      + '(orientation: landscape)'
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
      '(max-width: 1199.98px), '
      + '(min-width: 1200px) and '
      + '(max-width: 1399.98px) and '
      + '(min-height: 900px) and '
      + '(max-height: 1100px)'
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
      '(max-width: 991.98px)'
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


  function landscapeCoachRailEnabled() {
    return window.matchMedia(
      '(min-width: 992px) and '
      + '(max-width: 1399.98px) and '
      + '(min-height: 760px) and '
      + '(orientation: landscape)'
    ).matches;
  }

  function coachRailEscape(value) {
    return String(value ?? '').replace(
      /[&<>"']/g,
      char => ({
        '&':'&amp;',
        '<':'&lt;',
        '>':'&gt;',
        '"':'&quot;',
        "'":'&#39;',
      }[char])
    );
  }

  function coachRailMatrixData() {
    const table = document.querySelector(
      '#rotationMatrixCollapse table'
    );

    if (!table) return null;

    const headers = Array.from(
      table.querySelectorAll('thead th')
    ).map(
      cell => cell.textContent.trim()
    );

    const rows = Array.from(
      table.querySelectorAll('tbody tr')
    ).map(row => {
      const cells = Array.from(
        row.querySelectorAll('th,td')
      ).map(
        cell => cell.textContent.trim()
      );

      return {
        player:cells[0] || '',
        cells,
      };
    }).filter(
      row => row.player
    );

    return {headers, rows};
  }

  function coachRailInningColumns(matrix) {
    const raw = Number.parseFloat(
      currentInning()
    );

    const currentNumber = (
      Number.isFinite(raw)
        ? Math.floor(raw)
        : 1
    );

    const nextNumber = currentNumber + 1;

    const findColumn = number => {
      const wanted = `inning ${number}`;

      return matrix.headers.findIndex(
        header => (
          header.trim().toLowerCase() === wanted
        )
      );
    };

    return {
      currentNumber,
      nextNumber,
      currentIndex:findColumn(currentNumber),
      nextIndex:findColumn(nextNumber),
    };
  }

  function coachRailPosition(row, index) {
    if (
      !row ||
      !Number.isInteger(index) ||
      index < 1
    ) {
      return '—';
    }

    return row.cells[index]?.trim() || '—';
  }

  function coachRailPositionHtml(value) {
    const normalized = (
      value || '—'
    ).trim();

    const isBench = (
      normalized.toUpperCase() === 'BENCH'
    );

    return `
      <span
        class="gm-rail-pos${isBench ? ' bench' : ''}"
        title="${coachRailEscape(normalized)}"
      >
        ${isBench ? 'BENCH' : coachRailEscape(normalized)}
      </span>
    `;
  }

  function coachRailRotationHtml(matrix, columns) {
    if (
      !matrix ||
      columns.currentIndex < 1
    ) {
      return `
        <div
          id="gm-coach-rail-rotation"
          class="gm-rail-empty"
        >
          Rotation information is still loading.
        </div>
      `;
    }

    const hasNext = (
      columns.nextIndex >= 1
    );

    const rows = matrix.rows.map(row => {
      const current = coachRailPosition(
        row,
        columns.currentIndex
      );

      const next = (
        hasNext
          ? coachRailPosition(
              row,
              columns.nextIndex
            )
          : '—'
      );

      return `
        <div class="gm-rail-row">
          <div class="gm-rail-player">
            ${coachRailEscape(row.player)}
          </div>
          ${coachRailPositionHtml(current)}
          ${coachRailPositionHtml(next)}
        </div>
      `;
    }).join('');

    return `
      <div id="gm-coach-rail-rotation">
        <div class="gm-rail-summary">
          <strong>
            Inning ${columns.currentNumber}
            ${hasNext ? ` → Inning ${columns.nextNumber}` : ''}
          </strong>
          <span>
            ${hasNext ? 'Current → Next' : 'Current inning'}
          </span>
        </div>

        <div class="gm-rail-grid-head">
          <span>Player</span>
          <span>Current</span>
          <span>${hasNext ? 'Next' : '—'}</span>
        </div>

        ${rows}

        <button
          type="button"
          class="gm-rail-full-table"
        >
          <i class="bi bi-grid-3x3 me-1"></i>
          Full Rotation Table
        </button>
      </div>
    `;
  }

  function coachRailBenchNames(matrix, index) {
    if (
      !matrix ||
      !Number.isInteger(index) ||
      index < 1
    ) {
      return [];
    }

    return matrix.rows.filter(row => (
      coachRailPosition(
        row,
        index
      ).toUpperCase() === 'BENCH'
    )).map(
      row => row.player
    );
  }

  function coachRailBenchSectionHtml(label, names) {
    const chips = (
      names.length
        ? names.map(name => `
            <span class="gm-rail-bench-chip">
              ${coachRailEscape(name)}
            </span>
          `).join('')
        : `
            <span class="gm-rail-empty p-0">
              No one planned on the bench.
            </span>
          `
    );

    return `
      <section class="gm-rail-bench-section">
        <div class="gm-rail-bench-head">
          <strong>${coachRailEscape(label)}</strong>
          <span class="gm-rail-count">
            ${names.length}
          </span>
        </div>

        <div class="gm-rail-bench-list">
          ${chips}
        </div>
      </section>
    `;
  }

  function coachRailBenchHtml(matrix, columns) {
    if (
      !matrix ||
      columns.currentIndex < 1
    ) {
      return `
        <div
          id="gm-coach-rail-bench"
          class="gm-rail-empty"
        >
          Bench information is still loading.
        </div>
      `;
    }

    const current = coachRailBenchNames(
      matrix,
      columns.currentIndex
    );

    const next = (
      columns.nextIndex >= 1
        ? coachRailBenchNames(
            matrix,
            columns.nextIndex
          )
        : []
    );

    return `
      <div id="gm-coach-rail-bench">
        ${coachRailBenchSectionHtml(
          `Inning ${columns.currentNumber} Bench`,
          current
        )}

        ${
          columns.nextIndex >= 1
            ? coachRailBenchSectionHtml(
                `Inning ${columns.nextNumber} Bench`,
                next
              )
            : ''
        }

        <button
          type="button"
          class="gm-rail-full-table"
        >
          <i class="bi bi-grid-3x3 me-1"></i>
          Full Rotation Table
        </button>
      </div>
    `;
  }

  function removeLandscapeCoachRail() {
    const wrapper = document.getElementById(
      'gm-landscape-defense-workspace'
    );

    if (!wrapper) return;

    const fieldCard = wrapper.querySelector(
      ':scope > .pde-field-card'
    );

    if (
      fieldCard &&
      wrapper.parentElement
    ) {
      wrapper.insertAdjacentElement(
        'beforebegin',
        fieldCard
      );
    }

    wrapper.remove();
  }

  function syncLandscapeCoachRail() {
    const panel = document.getElementById(
      PANEL_ID
    );

    if (
      !panel ||
      !landscapeCoachRailEnabled()
    ) {
      removeLandscapeCoachRail();
      return;
    }

    const fieldCard = panel.querySelector(
      '.pde-field-card'
    );

    if (!fieldCard) return;

    let wrapper = document.getElementById(
      'gm-landscape-defense-workspace'
    );

    let rail = document.getElementById(
      'gm-landscape-coach-rail'
    );

    if (
      !wrapper ||
      !wrapper.contains(fieldCard)
    ) {
      removeLandscapeCoachRail();

      wrapper = document.createElement('div');
      wrapper.id = (
        'gm-landscape-defense-workspace'
      );

      fieldCard.insertAdjacentElement(
        'beforebegin',
        wrapper
      );

      wrapper.appendChild(fieldCard);

      rail = document.createElement('aside');
      rail.id = 'gm-landscape-coach-rail';

      rail.setAttribute(
        'aria-label',
        'Landscape rotation planning view'
      );

      rail.innerHTML = `
        <div class="gm-rail-head">
          <div class="gm-rail-title">
            <strong>Rotation View</strong>
            <small>
              Current and next inning at a glance
            </small>
          </div>

          <button
            type="button"
            class="gm-rail-collapse"
            aria-label="Collapse Rotation View"
          ></button>
        </div>

        <div
          class="gm-rail-tabs"
          role="tablist"
          aria-label="Coach Rail views"
        >
          <button
            type="button"
            class="gm-rail-tab"
            data-gm-rail-tab="rotation"
            role="tab"
          >
            Rotation
          </button>

          <button
            type="button"
            class="gm-rail-tab"
            data-gm-rail-tab="bench"
            role="tab"
          >
            Bench
          </button>
        </div>

        <div
          id="gm-coach-rail-body"
          class="gm-rail-body"
        ></div>
      `;

      wrapper.appendChild(rail);

      rail.addEventListener(
        'click',
        event => {
          const collapse = event.target.closest(
            '.gm-rail-collapse'
          );

          if (collapse) {
            coachRailCollapsed = (
              !coachRailCollapsed
            );

            queuePatch();
            return;
          }

          const tab = event.target.closest(
            '[data-gm-rail-tab]'
          );

          if (tab) {
            coachRailTab = (
              tab.dataset.gmRailTab ||
              'rotation'
            );

            queuePatch();
            return;
          }

          const fullTable = event.target.closest(
            '.gm-rail-full-table'
          );

          if (fullTable) {
            const rotationCollapse = (
              document.getElementById(
                'rotationMatrixCollapse'
              )
            );

            if (
              rotationCollapse &&
              !rotationCollapse.classList.contains('show')
            ) {
              const header = (
                rotationCollapse.previousElementSibling
              );

              const trigger = header?.matches?.(
                '[data-bs-toggle="collapse"]'
              )
                ? header
                : header?.querySelector(
                    '[data-bs-toggle="collapse"]'
                  );

              trigger?.click();
            }

            const shell = reportShell(
              rotationCollapse
            );

            shell?.scrollIntoView({
              behavior:'smooth',
              block:'start',
            });
          }
        }
      );
    }

    if (!rail) return;

    wrapper.classList.toggle(
      'gm-rail-collapsed',
      coachRailCollapsed
    );

    const collapseButton = rail.querySelector(
      '.gm-rail-collapse'
    );

    if (collapseButton) {
      collapseButton.setAttribute(
        'aria-label',
        coachRailCollapsed
          ? 'Expand Rotation View'
          : 'Collapse Rotation View'
      );

      setHtml(
        collapseButton,
        coachRailCollapsed
          ? '<i class="bi bi-chevron-left"></i>'
          : '<i class="bi bi-chevron-right"></i>'
      );
    }

    rail.querySelectorAll(
      '[data-gm-rail-tab]'
    ).forEach(button => {
      const active = (
        button.dataset.gmRailTab ===
        coachRailTab
      );

      button.classList.toggle(
        'active',
        active
      );

      button.setAttribute(
        'aria-selected',
        active ? 'true' : 'false'
      );
    });

    const inningGroup = document.getElementById(
      'inning-btn-group'
    );

    if (
      inningGroup &&
      inningGroup.dataset.coachRailBound !== '1'
    ) {
      inningGroup.dataset.coachRailBound = '1';

      inningGroup.addEventListener(
        'change',
        queuePatch
      );
    }

    const matrix = coachRailMatrixData();
    if (!matrix) return;

    const columns = coachRailInningColumns(
      matrix
    );

    const body = rail.querySelector(
      '#gm-coach-rail-body'
    );

    if (!body) return;

    const html = (
      coachRailTab === 'bench'
        ? coachRailBenchHtml(
            matrix,
            columns
          )
        : coachRailRotationHtml(
            matrix,
            columns
          )
    );

    const renderKey = JSON.stringify({
      tab:coachRailTab,
      current:columns.currentNumber,
      next:columns.nextNumber,
      headers:matrix.headers,
      rows:matrix.rows.map(
        row => row.cells
      ),
    });

    if (
      body.dataset.renderKey !== renderKey
    ) {
      body.dataset.renderKey = renderKey;
      body.innerHTML = html;
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
    syncLandscapeCoachRail();
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
