(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  const STYLE_ID = 'game-management-visual-polish-v1';

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      body.coach-game-page{
        background:#eef2f6;
      }
      body.coach-game-page main.container-fluid{
        background:#eef2f6;
      }
      body.coach-game-page .game-workspace-v2{
        --gm-navy:var(--primary-color,#0b2a6b);
        --gm-gold:#d0a526;
        --gm-ink:#172033;
        --gm-muted:#667085;
        --gm-border:#dfe5ec;
        --gm-soft:#f7f9fb;
        width:100%;
        max-width:1480px;
        margin-left:auto!important;
        margin-right:auto!important;
        padding:0 clamp(10px,1.4vw,22px) 30px;
      }

      body.coach-game-page .game-workspace-v2 h3,
      body.coach-game-page .game-workspace-v2 h5,
      body.coach-game-page .game-workspace-v2 h6{
        color:var(--gm-ink);
      }

      body.coach-game-page .game-workspace-v2 .card{
        border:1px solid var(--gm-border)!important;
        border-radius:14px;
        box-shadow:0 3px 12px rgba(16,24,40,.055)!important;
        overflow:hidden;
      }
      body.coach-game-page .game-workspace-v2 .card-header{
        background:#fbfcfd!important;
        border-bottom:1px solid #e7ebef;
      }

      body.coach-game-page .game-workspace-v2 .btn{
        border-radius:9px;
        font-weight:700;
      }
      body.coach-game-page .game-workspace-v2 .btn-primary{
        background:var(--gm-navy)!important;
        border-color:var(--gm-navy)!important;
        color:#fff!important;
      }
      body.coach-game-page .game-workspace-v2 .btn-primary:hover,
      body.coach-game-page .game-workspace-v2 .btn-primary:focus{
        filter:brightness(.91);
      }
      body.coach-game-page .game-workspace-v2 .btn-outline-primary{
        color:var(--gm-navy)!important;
        border-color:rgba(17,52,112,.5)!important;
        background:#fff;
      }
      body.coach-game-page .game-workspace-v2 .btn-outline-primary:hover,
      body.coach-game-page .game-workspace-v2 .btn-outline-primary:focus{
        color:#fff!important;
        background:var(--gm-navy)!important;
        border-color:var(--gm-navy)!important;
      }

      body.coach-game-page #pregame-checklist-container > .d-flex:first-child{
        padding:4px 2px 2px;
      }
      body.coach-game-page #pregame-checklist-container > .row.g-3.mb-4 .card{
        border-top:3px solid var(--gm-navy)!important;
        background:#fff;
      }
      body.coach-game-page #pregame-checklist-container > .row.g-3.mb-4 .card-body{
        padding:15px;
      }

      body.coach-game-page #startLiveGameBtnAction{
        background:var(--gm-navy)!important;
        border:1px solid var(--gm-navy)!important;
        border-left:6px solid var(--gm-gold)!important;
        color:#fff!important;
        border-radius:13px!important;
        box-shadow:0 5px 14px rgba(15,42,100,.18)!important;
        letter-spacing:.025em;
      }
      body.coach-game-page #startLiveGameBtnAction i{
        color:#f0c34b;
      }
      body.coach-game-page #startLiveGameBtnAction:hover,
      body.coach-game-page #startLiveGameBtnAction:focus{
        filter:brightness(.94);
        transform:translateY(-1px);
      }

      body.coach-game-page #coach-game-readiness-v2{
        border-radius:14px!important;
        box-shadow:0 2px 8px rgba(16,24,40,.045)!important;
      }
      body.coach-game-page #coach-game-readiness-v2.needs{
        background:#fffdf8!important;
        border-color:#e6d6aa!important;
      }
      body.coach-game-page #coach-game-readiness-v2.ready{
        background:#f8fcf9!important;
        border-color:#c8dfcf!important;
      }
      body.coach-game-page #coach-game-readiness-v2 .cgr-item.need{
        background:#fffaf0!important;
        border-color:#e6d4a2!important;
      }
      body.coach-game-page #coach-game-readiness-v2 .cgr-badge{
        box-shadow:none!important;
      }

      body.coach-game-page #game-pitching-rules-v2{
        border:1px solid var(--gm-border)!important;
        border-left:4px solid var(--gm-gold)!important;
        border-radius:14px!important;
        box-shadow:0 2px 8px rgba(16,24,40,.045)!important;
      }
      body.coach-game-page #game-pitching-rules-v2 .gpr-title{
        color:var(--gm-ink)!important;
      }
      body.coach-game-page #game-pitching-rules-v2 .gpr-badge.game{
        background:#fff5d9!important;
        color:#73520a!important;
      }
      body.coach-game-page #game-pitching-rules-v2 .gpr-badge.team{
        background:#edf2f8!important;
        color:#344054!important;
      }
      body.coach-game-page #game-pitching-rules-v2 .form-select:focus{
        border-color:var(--gm-navy)!important;
        box-shadow:0 0 0 .2rem rgba(20,55,120,.12)!important;
      }

      body.coach-game-page #rotation-card-container > .card > .card-header{
        padding:12px 14px;
        border-bottom:1px solid #e4e8ed;
      }
      body.coach-game-page #rotation-card-container #liveGameModeToggle:checked{
        background-color:#b42318;
        border-color:#b42318;
      }

      body.coach-game-page #pregame-defense-editor-v3{
        border-color:#d9e1e8!important;
        box-shadow:0 2px 10px rgba(16,24,40,.05)!important;
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-head{
        background:#fbfcfd!important;
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-inning{
        background:var(--gm-navy)!important;
        border-top:3px solid var(--gm-gold);
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-field-card{
        width:100%;
        max-width:1240px;
        margin-left:auto!important;
        margin-right:auto!important;
        border-color:#cfd9d1!important;
        border-radius:16px!important;
        box-shadow:0 5px 16px rgba(22,67,38,.08);
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-field-caption{
        background:#fbfcfd!important;
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-field{
        background:repeating-linear-gradient(90deg,#347d4a 0,#347d4a 12.5%,#3b8450 12.5%,#3b8450 25%)!important;
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-spot{
        border-color:rgba(215,222,227,.98)!important;
        box-shadow:0 2px 7px rgba(16,24,40,.13)!important;
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-spot.open{
        background:#fffaf0!important;
        border-color:#d7b767!important;
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-spot.open .pde-name{
        color:#805900!important;
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-chips span{
        background:#f6f8fa!important;
      }

      body.coach-game-page #rotation-card-container .table-responsive{
        border-radius:10px;
      }
      body.coach-game-page #rotation-card-container table thead th{
        background:#eef3f8;
        color:#27364e;
        border-bottom-color:#d6dee7;
      }

      @media (min-width:1200px){
        body.coach-game-page #pregame-defense-editor-v3 .pde-field{
          height:clamp(560px,42vw,660px)!important;
        }
      }
      @media (min-width:992px) and (max-width:1199.98px){
        body.coach-game-page #pregame-defense-editor-v3 .pde-field{
          height:clamp(470px,48vw,560px)!important;
        }
      }
      @media (max-width:991.98px){
        body.coach-game-page .game-workspace-v2{
          max-width:none;
          padding-left:8px;
          padding-right:8px;
          padding-bottom:18px;
        }
      }
      @media (max-width:575.98px){
        body.coach-game-page #startLiveGameBtnAction{
          border-left-width:4px!important;
          padding-top:12px!important;
          padding-bottom:12px!important;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function init() {
    document.body.classList.add('coach-game-page');
    const host = document.getElementById('pregame-checklist-container');
    const workspace = host?.closest('.container-fluid.mt-3') || host?.parentElement;
    workspace?.classList.add('game-workspace-v2');
    installStyles();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, {once:true});
  } else {
    init();
  }
})();
