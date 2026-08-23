(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  const STYLE_ID = 'game-management-visual-polish-v2';
  const MOBILE_QUERY = '(max-width: 767.98px)';
  const mobileMedia = window.matchMedia(MOBILE_QUERY);
  const pitchDetailsOpen = new Set();
  let showAvailablePitchers = false;
  let startPlaceholder = null;
  let passQueued = false;

  function isMobile() {
    return mobileMedia.matches;
  }

  function workspace() {
    const host = document.getElementById('pregame-checklist-container');
    return host?.closest('.container-fluid.mt-3') || host?.parentElement || null;
  }

  function setText(element, value) {
    if (element && element.textContent.trim() !== value) element.textContent = value;
  }

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      body.coach-game-page{background:#eef2f6}
      body.coach-game-page main.container-fluid{background:#eef2f6}
      body.coach-game-page .game-workspace-v2{
        --gm-navy:var(--primary-color,#0b2a6b);
        --gm-gold:#d0a526;
        --gm-ink:#172033;
        --gm-muted:#667085;
        --gm-border:#dfe5ec;
        --gm-soft:#f7f9fb;
        width:100%;max-width:1480px;margin-left:auto!important;margin-right:auto!important;
        padding:0 clamp(10px,1.4vw,22px) 30px;
      }
      body.coach-game-page .game-workspace-v2 h3,
      body.coach-game-page .game-workspace-v2 h5,
      body.coach-game-page .game-workspace-v2 h6{color:var(--gm-ink)}
      body.coach-game-page .game-workspace-v2 .card{
        border:1px solid var(--gm-border)!important;border-radius:14px;
        box-shadow:0 3px 12px rgba(16,24,40,.055)!important;overflow:hidden;
      }
      body.coach-game-page .game-workspace-v2 .card-header{background:#fbfcfd!important;border-bottom:1px solid #e7ebef}
      body.coach-game-page .game-workspace-v2 .btn{border-radius:9px;font-weight:700}
      body.coach-game-page .game-workspace-v2 .btn-primary{
        background:var(--gm-navy)!important;border-color:var(--gm-navy)!important;color:#fff!important;
      }
      body.coach-game-page .game-workspace-v2 .btn-primary:hover,
      body.coach-game-page .game-workspace-v2 .btn-primary:focus{filter:brightness(.91)}
      body.coach-game-page .game-workspace-v2 .btn-outline-primary{
        color:var(--gm-navy)!important;border-color:rgba(17,52,112,.5)!important;background:#fff;
      }
      body.coach-game-page .game-workspace-v2 .btn-outline-primary:hover,
      body.coach-game-page .game-workspace-v2 .btn-outline-primary:focus{
        color:#fff!important;background:var(--gm-navy)!important;border-color:var(--gm-navy)!important;
      }
      body.coach-game-page #pregame-checklist-container > .d-flex:first-child{padding:4px 2px 2px}
      body.coach-game-page #pregame-checklist-container > .row.g-3.mb-4 .card{
        border-top:3px solid var(--gm-navy)!important;background:#fff;
      }
      body.coach-game-page #pregame-checklist-container > .row.g-3.mb-4 .card-body{padding:15px}
      body.coach-game-page #startLiveGameBtnAction{
        background:var(--gm-navy)!important;border:1px solid var(--gm-navy)!important;
        border-left:6px solid var(--gm-gold)!important;color:#fff!important;border-radius:13px!important;
        box-shadow:0 5px 14px rgba(15,42,100,.18)!important;letter-spacing:.01em;
      }
      body.coach-game-page #startLiveGameBtnAction i{color:#f0c34b}
      body.coach-game-page #startLiveGameBtnAction:hover,
      body.coach-game-page #startLiveGameBtnAction:focus{filter:brightness(.94);transform:translateY(-1px)}
      body.coach-game-page #game-pitching-rules-v2{
        border:1px solid var(--gm-border)!important;border-left:4px solid var(--gm-gold)!important;
        border-radius:14px!important;box-shadow:0 2px 8px rgba(16,24,40,.045)!important;
      }
      body.coach-game-page #game-pitching-rules-v2 .gpr-title{color:var(--gm-ink)!important}
      body.coach-game-page #game-pitching-rules-v2 .gpr-badge.game{background:#fff5d9!important;color:#73520a!important}
      body.coach-game-page #game-pitching-rules-v2 .gpr-badge.team{background:#edf2f8!important;color:#344054!important}
      body.coach-game-page #game-pitching-rules-v2 .form-select:focus{
        border-color:var(--gm-navy)!important;box-shadow:0 0 0 .2rem rgba(20,55,120,.12)!important;
      }
      body.coach-game-page #rotation-card-container > .card > .card-header{padding:12px 14px;border-bottom:1px solid #e4e8ed}
      body.coach-game-page #rotation-card-container #liveGameModeToggle:checked{background-color:#b42318;border-color:#b42318}
      body.coach-game-page #pregame-defense-editor-v3{
        border-color:#d9e1e8!important;box-shadow:0 2px 10px rgba(16,24,40,.05)!important;
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-head{background:#fbfcfd!important}
      body.coach-game-page #pregame-defense-editor-v3 .pde-inning{background:var(--gm-navy)!important;border-top:3px solid var(--gm-gold)}
      body.coach-game-page #pregame-defense-editor-v3 .pde-field-card{
        width:100%;max-width:1240px;margin-left:auto!important;margin-right:auto!important;
        border-color:#cfd9d1!important;border-radius:16px!important;box-shadow:0 5px 16px rgba(22,67,38,.08);
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-field-caption{background:#fbfcfd!important}
      body.coach-game-page #pregame-defense-editor-v3 .pde-field{
        background:repeating-linear-gradient(90deg,#347d4a 0,#347d4a 12.5%,#3b8450 12.5%,#3b8450 25%)!important;
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-spot{
        border-color:rgba(215,222,227,.98)!important;box-shadow:0 2px 7px rgba(16,24,40,.13)!important;
      }
      body.coach-game-page #pregame-defense-editor-v3 .pde-spot.open{background:#fffaf0!important;border-color:#d7b767!important}
      body.coach-game-page #pregame-defense-editor-v3 .pde-spot.open .pde-name{color:#805900!important}
      body.coach-game-page #pregame-defense-editor-v3 .pde-chips span{background:#f6f8fa!important}
      body.coach-game-page #rotation-card-container .table-responsive{border-radius:10px}
      body.coach-game-page #rotation-card-container table thead th{
        background:#eef3f8;color:#27364e;border-bottom-color:#d6dee7;
      }
      .gm-optional-badge{
        display:inline-flex;align-items:center;margin-left:7px;padding:3px 7px;border-radius:999px;
        background:#f2f4f7;color:#667085;font-size:.56rem;font-weight:850;letter-spacing:.04em;text-transform:uppercase;
        vertical-align:middle;
      }
      .gm-pitcher-list-toggle{
        width:100%;min-height:38px;border:1px solid #d9e0e8;border-radius:9px;background:#fff;
        color:#23324b;font-size:.72rem;font-weight:800;margin:0 0 8px;padding:7px 10px;
      }
      .gm-pitch-card-more{
        display:none;width:100%;border:0;border-top:1px solid #edf0f3;background:#fff;color:#526078;
        min-height:34px;font-size:.65rem;font-weight:800;
      }

      @media (min-width:1200px){
        body.coach-game-page #pregame-defense-editor-v3 .pde-field{height:clamp(560px,42vw,660px)!important}
      }
      @media (min-width:992px) and (max-width:1199.98px){
        body.coach-game-page #pregame-defense-editor-v3 .pde-field{height:clamp(470px,48vw,560px)!important}
      }
      @media (max-width:991.98px){
        body.coach-game-page .game-workspace-v2{max-width:none;padding-left:8px;padding-right:8px;padding-bottom:18px}
      }
      @media (max-width:767.98px){
        body.coach-game-page .game-workspace-v2{padding-left:4px;padding-right:4px;padding-bottom:12px}
        body.coach-game-page #pregame-checklist-container > h5.text-uppercase{display:none!important}
        body.coach-game-page #pregame-checklist-container > .row.g-3.mb-4{display:none!important}
        body.coach-game-page #start-live-blockers{display:none!important}

        body.coach-game-page #pregame-checklist-container > .d-flex:first-child{
          display:grid!important;grid-template-columns:1fr;gap:8px;margin-bottom:9px!important;padding:0 1px!important;
        }
        body.coach-game-page #pregame-checklist-container > .d-flex:first-child h3{
          font-size:clamp(1.35rem,6.2vw,1.7rem);line-height:1.08;margin-bottom:4px!important;
        }
        body.coach-game-page #pregame-checklist-container > .d-flex:first-child p{
          font-size:.78rem;line-height:1.35;margin:0!important;
        }
        body.coach-game-page #pregame-checklist-container > .d-flex:first-child > div:last-child{
          display:grid!important;grid-template-columns:1fr 1fr;gap:7px;width:100%;
        }
        body.coach-game-page #pregame-checklist-container > .d-flex:first-child > div:last-child .btn{
          margin:0!important;min-height:38px;padding:6px 9px;font-size:.76rem;
        }
        body.coach-game-page #game-pitching-rules-v2{margin-bottom:9px!important}
        body.coach-game-page #game-pitching-rules-v2 .gpr-summary{padding:8px 9px!important}
        body.coach-game-page #game-pitching-rules-v2 .gpr-summary-copy{gap:2px!important}
        body.coach-game-page #game-pitching-rules-v2 .gpr-line{gap:5px!important}
        body.coach-game-page #game-pitching-rules-v2 .gpr-label{min-width:66px!important;font-size:.55rem!important}
        body.coach-game-page #game-pitching-rules-v2 .gpr-rule,
        body.coach-game-page #game-pitching-rules-v2 .gpr-arm{font-size:.7rem!important}

        body.coach-game-page .gm-mobile-start-wrap{margin:0 0 10px!important}
        body.coach-game-page #startLiveGameBtnAction{
          border-left-width:4px!important;min-height:52px;padding:10px 12px!important;font-size:1rem!important;
        }

        body.coach-game-page #rotation-card-container,
        body.coach-game-page #pitcher-availability-card,
        body.coach-game-page #pitching-log-container{scroll-margin-top:12px}
        body.coach-game-page #rotation-card-container{margin-bottom:12px!important}
        body.coach-game-page #rotation-card-container > .card > .card-header{padding:9px 10px!important}
        body.coach-game-page #rotation-card-container #rotation-editor-title{font-size:1.06rem!important}
        body.coach-game-page #rotation-card-container .gm-coach-inning-picker{
          display:grid!important;grid-template-columns:1fr!important;gap:5px!important;padding:7px!important;margin-bottom:5px!important;
        }
        body.coach-game-page #rotation-card-container .gm-coach-inning-label{
          width:auto!important;margin:0!important;font-size:.62rem!important;line-height:1!important;
        }
        body.coach-game-page #rotation-card-container #inning-btn-group{
          display:grid!important;grid-template-columns:repeat(6,minmax(0,1fr));gap:4px;width:100%;
        }
        body.coach-game-page #rotation-card-container #inning-btn-group .btn-check + label.btn{
          width:100%!important;min-width:0!important;min-height:38px;padding:7px 0!important;margin:0!important;
          border-radius:8px!important;font-size:.82rem!important;line-height:1!important;
        }
        body.coach-game-page #rotation-card-container .gm-coach-help{
          margin:3px 1px 7px!important;font-size:.64rem!important;line-height:1.3!important;
        }
        body.coach-game-page #rotation-card-container .gm-coach-actions{
          display:grid!important;grid-template-columns:minmax(0,1fr) minmax(0,.8fr)!important;gap:6px!important;width:100%;
        }
        body.coach-game-page #rotation-card-container .gm-coach-actions #copyPreviousInningBtn,
        body.coach-game-page #rotation-card-container .gm-coach-actions .btn-group,
        body.coach-game-page #rotation-card-container .gm-coach-actions .dropdown-toggle{
          width:100%!important;min-width:0!important;min-height:38px!important;font-size:.7rem!important;
        }

        body.coach-game-page #pregame-defense-editor-v3{margin-bottom:9px!important;border-radius:12px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-head{padding:9px 10px 7px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-kicker{display:none!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-title{font-size:.96rem!important;line-height:1.1!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-help{font-size:.64rem!important;line-height:1.25!important;margin-top:3px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-body{padding:8px 9px 9px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-tools{
          display:grid!important;grid-template-columns:minmax(0,1fr) 76px!important;gap:6px!important;padding:7px!important;margin-bottom:7px!important;
        }
        body.coach-game-page #pregame-defense-editor-v3 .gm-preset-wrap{min-width:0!important}
        body.coach-game-page #pregame-defense-editor-v3 .gm-preset-label{margin-bottom:3px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-tools .form-select,
        body.coach-game-page #pregame-defense-editor-v3 .pde-tools .btn{min-height:38px!important;font-size:.68rem!important}
        body.coach-game-page #pregame-defense-editor-v3 #pde-apply{width:auto!important;padding-left:7px!important;padding-right:7px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-field-caption{padding:6px 8px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-field-caption strong{font-size:.67rem!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-field-caption span{display:none!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-field{
          height:clamp(238px,64vw,265px)!important;min-height:0!important;
        }
        body.coach-game-page #pregame-defense-editor-v3 .pde-spot{
          width:58px!important;min-height:36px!important;padding:3px!important;border-radius:8px!important;
        }
        body.coach-game-page #pregame-defense-editor-v3 .pde-pos{font-size:.42rem!important;margin-bottom:1px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-name{font-size:.52rem!important;line-height:1.05!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-bench{padding:6px 8px 7px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-label{font-size:.55rem!important;margin-bottom:4px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-chips{gap:4px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-chips span{font-size:.57rem!important;padding:3px 5px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-status{margin-top:7px!important;padding:7px 8px!important;gap:7px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-status-copy strong{font-size:.68rem!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-status-copy span{font-size:.6rem!important}

        body.coach-game-page #pitcher-availability-card{scroll-margin-top:10px}
        body.coach-game-page #pitcher-availability-card > .card-header{padding:9px 10px!important}
        body.coach-game-page #pitcher-availability-card > .card-header strong{font-size:.92rem!important}
        body.coach-game-page #pitcher-availability-card .cb-pitch-rule-note{font-size:.62rem!important;line-height:1.25!important}
        body.coach-game-page #pitcher-availability-card .gpa-shell{padding:7px!important}
        body.coach-game-page #pitcher-availability-card .gpa-summary{margin-bottom:6px!important;font-size:.62rem!important;gap:5px!important}
        body.coach-game-page #pitcher-availability-card .gpa-summary strong{font-size:.68rem!important}
        body.coach-game-page #pitcher-availability-card .gpa-grid{gap:6px!important}
        body.coach-game-page #pitcher-availability-card .gpa-card{border-radius:10px!important}
        body.coach-game-page #pitcher-availability-card .gpa-top{padding:8px 9px 5px!important}
        body.coach-game-page #pitcher-availability-card .gpa-name{font-size:.82rem!important}
        body.coach-game-page #pitcher-availability-card .gpa-status{font-size:.52rem!important;padding:3px 6px!important}
        body.coach-game-page #pitcher-availability-card .gpa-decision{margin:0 8px 6px!important;padding:6px 7px!important}
        body.coach-game-page #pitcher-availability-card .gpa-decision strong{font-size:.69rem!important}
        body.coach-game-page #pitcher-availability-card .gpa-label{font-size:.5rem!important}
        body.coach-game-page #pitcher-availability-card .gpa-arm{padding:6px 8px!important}
        body.coach-game-page #pitcher-availability-card .gpa-arm strong{font-size:.64rem!important}
        body.coach-game-page #pitcher-availability-card .gpa-card:not(.gm-details-open) .gpa-metrics{display:none!important}
        body.coach-game-page #pitcher-availability-card .gpa-metrics{grid-template-columns:1fr 1fr!important}
        body.coach-game-page #pitcher-availability-card .gpa-metric{padding:6px 8px!important;font-size:.62rem!important}
        body.coach-game-page #pitcher-availability-card .gm-pitch-card-more{display:block}
        body.coach-game-page #pitcher-availability-card .btn-outline-secondary{min-height:34px;font-size:.66rem;padding:5px 9px}

        body.coach-game-page .cb-pitch-plan-card .card-header{padding:9px 10px!important}
        body.coach-game-page .cb-pitch-plan-card .card-header h5{font-size:1rem!important}
        body.coach-game-page .cb-pregame-clock{padding:8px 9px!important;margin-bottom:9px!important}
      }
      @media (max-width:380px){
        body.coach-game-page #rotation-card-container #inning-btn-group{gap:3px}
        body.coach-game-page #pregame-defense-editor-v3 .pde-field{height:232px!important}
        body.coach-game-page #pregame-defense-editor-v3 .pde-spot{width:54px!important}
      }
    `;
    document.head.appendChild(style);
  }

  function currentInningLabel() {
    const checked = document.querySelector('#inning-btn-group input[name="inning-radio"]:checked');
    if (!checked) return '1';
    const label = document.querySelector(`label[for="${CSS.escape(checked.id)}"]`);
    return label?.textContent.trim() || checked.value || '1';
  }

  function polishGeneralCopy() {
    const startButton = document.getElementById('startLiveGameBtnAction');
    if (startButton && /start live game/i.test(startButton.textContent)) {
      startButton.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i>Start Live Game';
    }

    document.querySelectorAll('#game-pitching-rules-v2 .gpr-label').forEach((label, index) => {
      const text = label.textContent.trim().toLowerCase();
      if (index === 0 || text === 'competition') setText(label, 'Game Rules');
      if (text === 'arm care') setText(label, 'Arm Care');
    });

    const plan = document.getElementById('pitching-board-v2');
    const planTitle = plan?.querySelector(':scope > .card .card-header h5');
    if (planTitle) {
      if (/^Pitching Plan(?: \(Optional\))?$/i.test(planTitle.textContent.trim())) setText(planTitle, 'Pitching Plan');
      if (!planTitle.parentElement?.querySelector('.gm-optional-badge')) {
        const badge = document.createElement('span');
        badge.className = 'gm-optional-badge';
        badge.textContent = 'Optional';
        planTitle.insertAdjacentElement('afterend', badge);
      }
    }
    const planSubtitle = plan?.querySelector(':scope > .card .card-header .small.text-muted');
    if (planSubtitle && /No pitching plan set\.?/i.test(planSubtitle.textContent.trim())) setText(planSubtitle, 'No pitchers planned yet.');

    const clock = document.getElementById('cbPregameClock');
    clock?.querySelectorAll('span').forEach((span) => {
      if (/No time limit set yet/i.test(span.textContent.trim())) {
        setText(span, 'No time limit set. The clock starts with Live Game.');
      }
    });
  }

  function polishDefenseCopy() {
    const inning = currentInningLabel();
    setText(document.querySelector('#rotation-card-container .gm-coach-inning-label'), 'Innings');

    const help = document.querySelector('#rotation-card-container .gm-coach-help');
    setText(help, 'Pick an inning, then set the defense below.');

    const copy = document.getElementById('copyPreviousInningBtn');
    if (copy && !copy.classList.contains('d-none') && copy.textContent.trim() !== 'Copy Previous') {
      copy.innerHTML = '<i class="bi bi-copy me-1"></i>Copy Previous';
      copy.title = 'Copy the previous inning defense into this inning';
    }

    const actions = copy?.parentElement;
    const inningTools = actions?.querySelector('.dropdown-toggle');
    if (inningTools && inningTools.textContent.trim() !== 'Inning Tools') {
      inningTools.innerHTML = '<i class="bi bi-three-dots me-1"></i>Inning Tools';
      inningTools.title = 'Inning tools';
    }

    const panel = document.getElementById('pregame-defense-editor-v3');
    if (!panel) return;
    setText(panel.querySelector('.pde-title'), `Set Defense — Inning ${inning}`);
    setText(panel.querySelector('.pde-help'), 'Tap a position to assign or change a player. Saves automatically.');

    const label = panel.querySelector('.gm-preset-label');
    setText(label, 'Defense Preset (Optional)');
    const select = document.getElementById('pde-preset');
    if (select?.options?.length) setText(select.options[0], 'Choose a starting defense…');
    setText(document.getElementById('pde-apply'), 'Apply');

    setText(panel.querySelector('.pde-field-caption strong'), 'Current Defense');
    setText(panel.querySelector('.pde-field-caption span'), 'Tap a position to change it');
    setText(panel.querySelector('.pde-label'), 'Bench');

    const statusStrong = panel.querySelector('.pde-status-copy strong');
    const statusMatch = statusStrong?.textContent.trim().match(/^(\d+) open position(?:s)?$/i);
    if (statusMatch) {
      const count = Number(statusMatch[1]);
      setText(statusStrong, `${count} position${count === 1 ? '' : 's'} open`);
    }
    setText(panel.querySelector('.pde-status-note'), 'Saves automatically.');
  }

  function polishPitcherCard(card) {
    const status = card.querySelector('.gpa-status');
    const statusText = status?.textContent.trim().toLowerCase() || '';
    if (status) {
      if (statusText === 'eligible') setText(status, 'Can Pitch');
      else if (statusText === 'rest required') setText(status, 'Rest');
      else if (statusText === 'verify' || statusText === 'caution') setText(status, 'Check');
    }

    card.querySelectorAll('.gpa-label').forEach((label) => {
      const text = label.textContent.trim().toLowerCase();
      if (text === 'competition eligibility') setText(label, 'Game eligibility');
      else if (text === 'official today') setText(label, 'Game pitches today');
      else if (text === 'throwing workload') setText(label, 'Total throwing');
      else if (text === 'game plan') setText(label, 'Pitch plan');
    });

    const decision = card.querySelector('.gpa-decision strong');
    if (decision && /Eligible by competition rules/i.test(decision.textContent.trim())) setText(decision, 'Eligible for this game');

    const arm = card.querySelector('.gpa-arm strong');
    if (arm) {
      const text = arm.textContent.trim();
      if (/^No Rest Required$/i.test(text)) setText(arm, 'No rest needed');
      else if (/^No tracked throwing history$/i.test(text)) setText(arm, 'No recent throwing logged');
    }

    card.querySelectorAll('.gpa-metric').forEach((metric) => {
      const label = metric.querySelector('.gpa-label')?.textContent.trim().toLowerCase();
      const value = metric.querySelector('.gpa-value');
      if (!value) return;
      if (label === 'total throwing') {
        const next = value.textContent.trim().replace(/\s*\/\s*7d\b/gi, ' last 7 days');
        setText(value, next);
      }
      if (label === 'pitch plan' && /^No plan$/i.test(value.textContent.trim())) setText(value, 'Not set');
    });

    const playerName = card.dataset.playerName || card.querySelector('.gpa-name')?.textContent.trim() || '';
    const metrics = card.querySelector('.gpa-metrics');
    if (metrics && !card.querySelector('.gm-pitch-card-more')) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'gm-pitch-card-more';
      button.dataset.playerName = playerName;
      card.querySelector('.gpa-arm')?.insertAdjacentElement('afterend', button);
    }
    const detailsOpen = pitchDetailsOpen.has(playerName);
    card.classList.toggle('gm-details-open', detailsOpen);
    const more = card.querySelector('.gm-pitch-card-more');
    if (more) {
      more.setAttribute('aria-expanded', detailsOpen ? 'true' : 'false');
      more.textContent = detailsOpen ? 'Hide pitch details' : 'Pitch details';
    }
  }

  function polishPitcherAvailability() {
    const card = document.getElementById('pitcher-availability-card');
    if (!card) return;

    const header = card.querySelector(':scope > .card-header');
    setText(header?.querySelector('strong, h5'), 'Who Can Pitch?');
    setText(header?.querySelector('.cb-pitch-rule-note'), 'Game eligibility uses the selected pitching rules. Arm-care guidance is separate.');
    const rulesButton = header?.querySelector('a.btn');
    if (rulesButton) setText(rulesButton, isMobile() ? 'Rules' : 'View Rules');

    const rows = [...card.querySelectorAll('.gpa-card')];
    if (!rows.length) return;
    rows.forEach(polishPitcherCard);

    const summary = card.querySelector('.gpa-summary');
    if (summary) {
      const prior = summary.textContent.trim();
      const ruleLabel = summary.lastElementChild?.textContent.trim() || '';
      const rulesNeeded = /rules (?:needed|not selected)/i.test(prior) || rows.some((row) => /rules needed/i.test(row.querySelector('.gpa-status')?.textContent || ''));
      const canPitch = rows.filter((row) => row.dataset.available === 'true').length;
      const review = rows.filter((row) => row.dataset.available !== 'true' || row.classList.contains('attention') || row.classList.contains('resting')).length;
      const markup = rulesNeeded
        ? `<strong>Pitching rules needed</strong><span>·</span><strong>${rows.length} to review</strong>${ruleLabel ? `<span>${ruleLabel}</span>` : ''}`
        : `<strong>${canPitch} can pitch</strong><span>·</span><strong>${review} need${review === 1 ? 's' : ''} review</strong>${ruleLabel ? `<span>${ruleLabel}</span>` : ''}`;
      if (summary.innerHTML !== markup) summary.innerHTML = markup;
    }

    let toggle = card.querySelector('.gm-pitcher-list-toggle');
    const safeRows = rows.filter((row) => row.dataset.available === 'true' && !row.classList.contains('attention') && !row.classList.contains('resting'));
    const attentionRows = rows.filter((row) => !safeRows.includes(row));
    const grid = card.querySelector('.gpa-grid');

    if (!toggle && safeRows.length) {
      toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'gm-pitcher-list-toggle';
      card.querySelector('.gpa-summary')?.insertAdjacentElement('afterend', toggle);
    }

    if (isMobile()) {
      safeRows.forEach((row) => { row.hidden = !showAvailablePitchers; });
      attentionRows.forEach((row) => { row.hidden = false; });
      if (toggle) {
        toggle.hidden = false;
        toggle.setAttribute('aria-expanded', showAvailablePitchers ? 'true' : 'false');
        toggle.textContent = showAvailablePitchers
          ? `Hide ${safeRows.length} available pitcher${safeRows.length === 1 ? '' : 's'}`
          : `Show ${safeRows.length} available pitcher${safeRows.length === 1 ? '' : 's'}`;
      }
      if (grid) grid.hidden = rows.every((row) => row.hidden);
    } else {
      rows.forEach((row) => { row.hidden = false; row.classList.add('gm-details-open'); });
      if (toggle) toggle.hidden = true;
      if (grid) grid.hidden = false;
    }
  }

  function positionStartButton() {
    const button = document.getElementById('startLiveGameBtnAction');
    const wrap = button?.closest('.d-grid');
    if (!button || !wrap) return;

    if (!startPlaceholder && wrap.parentNode) {
      startPlaceholder = document.createComment('CoachBoard start-live original position');
      wrap.parentNode.insertBefore(startPlaceholder, wrap);
    }

    if (!isMobile()) {
      wrap.classList.remove('gm-mobile-start-wrap');
      if (startPlaceholder?.parentNode && startPlaceholder.nextSibling !== wrap) {
        startPlaceholder.parentNode.insertBefore(wrap, startPlaceholder.nextSibling);
      }
      return;
    }

    wrap.classList.add('gm-mobile-start-wrap');
    const readiness = document.getElementById('coach-game-readiness-v2');
    if (readiness && readiness.nextElementSibling !== wrap) readiness.insertAdjacentElement('afterend', wrap);
  }

  function runPass() {
    passQueued = false;
    polishGeneralCopy();
    polishDefenseCopy();
    polishPitcherAvailability();
    positionStartButton();
  }

  function schedulePass() {
    if (passQueued) return;
    passQueued = true;
    window.requestAnimationFrame(runPass);
  }

  function bindControls() {
    document.addEventListener('click', (event) => {
      const listToggle = event.target.closest('.gm-pitcher-list-toggle');
      if (listToggle) {
        event.preventDefault();
        showAvailablePitchers = !showAvailablePitchers;
        schedulePass();
        return;
      }

      const details = event.target.closest('.gm-pitch-card-more');
      if (details) {
        event.preventDefault();
        const name = details.dataset.playerName || details.closest('.gpa-card')?.dataset.playerName || '';
        if (pitchDetailsOpen.has(name)) pitchDetailsOpen.delete(name);
        else pitchDetailsOpen.add(name);
        schedulePass();
      }
    });
  }

  function init() {
    document.body.classList.add('coach-game-page');
    workspace()?.classList.add('game-workspace-v2');
    installStyles();
    bindControls();
    runPass();

    const observer = new MutationObserver(schedulePass);
    observer.observe(document.body, {childList:true, subtree:true});
    mobileMedia.addEventListener?.('change', schedulePass);
    window.addEventListener('orientationchange', () => window.setTimeout(schedulePass, 120));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, {once:true});
  } else {
    init();
  }
})();