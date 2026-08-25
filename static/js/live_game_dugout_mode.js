(() => {
  'use strict';

  const match = location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const $ = id => document.getElementById(id);
  const setText = (el, value) => {
    if (el && el.textContent !== value) el.textContent = value;
  };
  const setHtml = (el, value) => {
    if (el && el.innerHTML !== value) el.innerHTML = value;
  };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));

  let state = null;
  let clock = null;
  let clockAt = 0;
  let stateBusy = false;
  let clockBusy = false;
  let queued = false;
  let endInningFrom = null;
  let moveBusy = false;
  let lastFailedMove = null;
  let saveMode = 'saved';
  let saveMessage = 'Saved';
  let quickDefenseSignature = '';

  function styles() {
    if ($('dugout-mode-styles')) return;
    const style = document.createElement('style');
    style.id = 'dugout-mode-styles';
    style.textContent = `
      body.cb-dugout{background:#eef1f4!important}
      body.cb-dugout .navbar,body.cb-dugout .bottom-nav-fixed{display:none!important}
      body.cb-dugout main.container-fluid,body.cb-dugout main.container-fluid>.container-fluid{padding:0!important;max-width:none!important;margin-top:0!important}
      body.cb-dugout #game-management-planner-row{margin:0!important}
      body.cb-dugout #rotation-card-container{padding:0!important;margin:0!important}
      body.cb-dugout #rotation-card-container>.card{border:0!important;border-radius:0!important;box-shadow:none!important;background:#eef1f4!important}
      body.cb-dugout #rotation-card-container>.card>.card-header,body.cb-dugout .coach-live-head,body.cb-dugout #cbLiveGameClock{display:none!important}
      body.cb-dugout #live-game-overlay{min-height:100vh;background:#eef1f4!important;padding:0 0 24px!important}
      body.cb-dugout .coach-live-shell{max-width:1100px!important;margin:auto!important;padding:0 10px 24px!important}
      body.cb-dugout #coach-pitcher-slot{display:none!important}
      body.cb-dugout .cb-legacy-defense-card{display:none!important}

      #cbDugoutHeader{position:sticky;top:0;z-index:1040;margin:0 -10px 12px;padding:9px 12px;background:#101828;color:#fff;border-bottom:3px solid var(--primary-color,#102a66);box-shadow:0 4px 14px rgba(16,24,40,.2)}
      .cb-dh-main{display:grid;grid-template-columns:auto auto minmax(0,1fr) minmax(0,auto) auto auto;align-items:center;gap:10px}
      .cb-dh-live{display:flex;gap:6px;align-items:center;font-size:.66rem;font-weight:900;text-transform:uppercase;letter-spacing:.08em;white-space:nowrap}
      .cb-dh-dot{width:8px;height:8px;border-radius:50%;background:#2dd36f}
      .cb-dh-inning{min-width:58px;text-align:center;border-inline:1px solid #ffffff2e;padding:0 10px}
      .cb-dh-inning small,.cb-dh-clock small,.cb-dh-pitcher small{display:block;color:#cbd5e1;font-size:.55rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;line-height:1.1}
      .cb-dh-inning strong{display:block;font-size:1.35rem;line-height:1.05;margin-top:2px}
      .cb-dh-time{font-size:1.08rem;font-weight:850;font-variant-numeric:tabular-nums;white-space:nowrap;margin-top:2px}
      .cb-dh-time.warn{color:#ffd166}.cb-dh-time.danger{color:#ff8a80}
      .cb-dh-pitcher{text-align:right;min-width:0}
      .cb-dh-name{font-size:.88rem;font-weight:800;max-width:230px;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere;line-height:1.05}
      .cb-dh-btn{min-height:40px!important;border-radius:9px!important;font-weight:750!important}
      .cb-dh-title{margin-top:6px;color:#cbd5e1;font-size:.67rem;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      body.cb-clock-paused #cbDugoutHeader{border-bottom-color:#f5b942!important}
      body.cb-clock-paused #cbDugoutHeader .cb-dh-dot{background:#f5b942!important}
      body.cb-clock-paused #cbDugoutHeader .cb-dh-time{color:#ffd166!important}

      #cbCoachBoardNavModal .modal-content{border:0;border-radius:15px;overflow:hidden}
      #cbCoachBoardNavModal .cb-nav-safe{border:1px solid #b9dcc4;background:#f4fbf6;color:#22543d;border-radius:10px;padding:9px 10px;font-size:.75rem;line-height:1.4;margin-bottom:12px}
      #cbCoachBoardNavModal .cb-app-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
      #cbCoachBoardNavModal .cb-app-link{min-height:58px;border:1px solid #dfe4ea;border-radius:11px;background:#fff;color:#253047;text-decoration:none;display:flex;align-items:center;gap:9px;padding:10px 11px;font-size:.8rem;font-weight:780}
      #cbCoachBoardNavModal .cb-app-link i{font-size:1.05rem;color:var(--primary-color,#102a66)}
      #cbCoachBoardNavModal .cb-return-game{grid-column:1/-1;background:var(--primary-color,#102a66);border-color:var(--primary-color,#102a66);color:#fff}
      #cbCoachBoardNavModal .cb-return-game i{color:#fff}

      body.cb-dugout .coach-actions{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:10px!important;margin:0 0 12px!important}
      body.cb-dugout .coach-actions>.btn{min-height:68px!important;border-radius:12px!important;border-width:2px!important;padding:9px!important;align-items:center!important;text-align:center!important;justify-content:center!important;touch-action:manipulation}
      body.cb-dugout .coach-action-title{font-size:.96rem!important;font-weight:850!important}
      body.cb-dugout .coach-action-note{font-size:.67rem!important;margin-top:4px!important;opacity:.78!important}
      body.cb-dugout #liveChangePitcherBtn{background:var(--primary-color,#102a66)!important;border-color:var(--primary-color,#102a66)!important;color:#fff!important}
      body.cb-dugout #liveDefensiveChangeBtn{background:#fff!important;border-color:#667085!important;color:#1d2939!important}
      body.cb-dugout #liveEndInningBtn{background:#172033!important;border-color:#172033!important;color:#fff!important}
      body.cb-dugout #liveUndoBtn{background:#fff!important;border-color:#cfd5dd!important;color:#475467!important}
      body.cb-dugout .coach-card{border:1.5px solid #cfd5dd!important;border-radius:14px!important;box-shadow:0 2px 7px #10182814!important;background:#fff!important;padding:13px!important;margin-bottom:12px!important}

      .cb-quick-defense{padding:0!important;overflow:hidden}
      .cb-qd-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;padding:12px 13px 10px;border-bottom:1px solid #e8ebef;background:#fff}
      .cb-qd-kicker{font-size:.64rem;text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#667085}
      .cb-qd-title{font-size:1rem;font-weight:850;color:#172033;margin-top:1px}
      .cb-qd-help{font-size:.7rem;color:#667085;margin-top:2px;line-height:1.3}
      .cb-save-state{flex:0 0 auto;min-height:30px;border-radius:999px;padding:6px 9px;font-size:.65rem;font-weight:850;display:inline-flex;align-items:center;gap:5px;border:1px solid #b8ddc4;background:#edf8f1;color:#176b38}
      .cb-save-state.saving{border-color:#c7d7ef;background:#f3f7fd;color:#315d98}
      .cb-save-state.error{border-color:#edb8b2;background:#fff2f0;color:#b42318;cursor:pointer}
      .cb-qd-body{padding:10px 11px 12px}
      .cb-qd-field{position:relative;aspect-ratio:1.28/1;min-height:238px;overflow:hidden;border:1px solid #d8e2d8;border-radius:12px;background:repeating-linear-gradient(90deg,#3d8f55 0,#3d8f55 12.5%,#438f58 12.5%,#438f58 25%)}
      .cb-qd-field-art{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
      .cb-qd-spot{position:absolute;transform:translate(-50%,-50%);z-index:2;width:clamp(62px,20vw,112px);border:0;background:transparent;padding:0;text-align:center;touch-action:manipulation}
      .cb-qd-pos{display:block;color:#fff;font-size:.49rem;font-weight:900;line-height:1;text-shadow:0 1px 2px rgba(0,0,0,.45);margin-bottom:3px;letter-spacing:.04em}
      .cb-qd-name{display:block;width:100%;background:rgba(255,255,255,.96);border:1px solid #dce1e5;border-radius:8px;padding:5px 5px;font-size:.67rem;line-height:1.08;font-weight:820;color:#172033;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere;box-shadow:0 1px 2px rgba(16,24,40,.1)}
      .cb-qd-spot:active .cb-qd-name,.cb-qd-bench-player:active{transform:scale(.98)}
      .cb-qd-spot.pitcher .cb-qd-name{border-color:#b7c8e8;background:#f5f8ff}
      .cb-qd-bench-wrap{margin-top:9px;border:1px solid #e2e6eb;border-radius:11px;background:#f8fafc;padding:9px}
      .cb-qd-bench-head{display:flex;justify-content:space-between;gap:8px;align-items:baseline;margin-bottom:7px}
      .cb-qd-bench-head strong{font-size:.74rem;color:#253047}
      .cb-qd-bench-head span{font-size:.61rem;color:#7b8492;text-align:right}
      .cb-qd-bench{display:flex;flex-wrap:wrap;gap:6px}
      .cb-qd-bench-player{border:1px solid #cfd5dd;background:#fff;color:#253047;border-radius:10px;padding:7px 9px;text-align:left;font-size:.72rem;font-weight:760;line-height:1.08;touch-action:manipulation}
      .cb-qd-bench-player .cb-bench-note{display:block;margin-top:3px;color:#667085;font-size:.58rem;font-weight:650}
      .cb-qd-bench-player.priority{border-color:#d8b96a;background:#fff9e9}
      .cb-qd-actions{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-top:9px}
      .cb-qd-actions .btn{min-height:40px;border-radius:9px;font-size:.7rem;font-weight:780}
      .cb-qd-tip{font-size:.62rem;color:#667085;line-height:1.25}

      #cbQuickMoveModal .modal-content{border:0;border-radius:15px;overflow:hidden}
      #cbQuickMoveModal .cb-move-current{border:1px solid #dfe4ea;background:#f8fafc;border-radius:10px;padding:9px 10px;margin-bottom:10px;font-size:.76rem;color:#475467}
      #cbQuickMoveModal .cb-destination-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
      #cbQuickMoveModal .cb-destination{min-height:60px;border-radius:10px;text-align:left;font-weight:820;padding:8px 10px}
      #cbQuickMoveModal .cb-destination small{display:block;font-size:.62rem;font-weight:550;margin-top:3px;opacity:.75;line-height:1.15}

      .cb-defense-tools{display:none!important}
      body.cb-dugout #live-board-prep-v3{border:1.5px solid #9aa7b8!important;border-radius:13px!important;box-shadow:0 1px 5px #10182814!important;scroll-margin-top:96px!important}
      body.cb-dugout #live-board-prep-v3 .bp-head{background:#fff!important;padding:10px 11px 8px!important}
      body.cb-dugout #live-board-prep-v3 .bp-kicker{color:#344054!important;font-size:.62rem!important;font-weight:900!important}
      body.cb-dugout #live-board-prep-v3 .bp-title{font-size:.94rem!important;color:#101828!important}
      body.cb-dugout #live-board-prep-v3 .bp-help{font-size:.67rem!important;color:#667085!important}
      body.cb-dugout #live-board-prep-v3 .bp-body{padding:9px 10px 10px!important}
      body.cb-dugout #live-board-prep-v3 .bp-main{display:block!important}
      body.cb-dugout #live-board-prep-v3 .bp-main>section:last-child{display:none!important}
      body.cb-dugout #live-board-prep-v3 .bp-move{min-height:44px!important;background:#fff!important;border-color:#dfe4ea!important}
      body.cb-dugout #live-board-prep-v3 .bp-move strong{white-space:normal!important;overflow:visible!important;text-overflow:clip!important;overflow-wrap:anywhere!important}
      body.cb-dugout #live-board-prep-v3 .bp-actions .btn{min-height:44px!important;font-size:.73rem!important;font-weight:850!important;touch-action:manipulation}
      .cb-board-flash{animation:cbBoardFlash 1.5s ease-out 1}@keyframes cbBoardFlash{50%{box-shadow:0 0 0 8px #102a6624}}

      .cb-end-zone{margin-top:16px;padding-top:12px;border-top:1px solid #cfd5dd;text-align:right}
      .cb-end-zone small{display:block;color:#667085;font-size:.62rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}
      .cb-end-zone #liveEndGameBtn{min-height:42px!important;width:auto!important;border-radius:10px!important;padding:7px 13px!important;font-weight:800!important;background:#fff!important;color:#b42318!important;border:1.5px solid #d92d20!important;box-shadow:none!important}
      body.cb-dugout #live-defense-v2 .list-group-item,body.cb-dugout #live-pitcher-picker-v2 .pitcher-choice-v2{min-height:58px!important;padding:14px!important;font-size:.94rem!important;touch-action:manipulation}
      body.cb-dugout #live-defense-destination-v2 .btn,body.cb-dugout #live-pitcher-destination-v2 .btn,body.cb-dugout #next-inning-adjust-modal .btn{min-height:54px!important;font-size:.92rem!important;touch-action:manipulation}
      body.cb-dugout #next-inning-adjust-modal .form-select{min-height:52px!important;font-size:.95rem!important}

      @media(min-width:768px){
        body.cb-dugout .coach-actions{grid-template-columns:repeat(4,minmax(0,1fr))!important}
        .cb-qd-field{min-height:330px}
        .cb-qd-spot{width:clamp(78px,11vw,122px)}
        .cb-qd-name{font-size:.75rem}
      }
      @media(max-width:575.98px){
        #cbDugoutHeader{margin:0 -10px 10px;padding:8px 9px}
        .cb-dh-main{grid-template-columns:auto minmax(62px,.8fr) minmax(70px,1fr) auto auto;gap:5px}
        .cb-dh-live{display:none}
        .cb-dh-pitcher{display:block!important;text-align:left}
        .cb-dh-inning{min-width:43px;padding:0 5px;border-left:0}
        .cb-dh-inning strong{font-size:1.12rem}
        .cb-dh-time{font-size:.84rem}
        .cb-dh-name{font-size:.68rem;max-width:none}
        .cb-dh-btn{font-size:.65rem!important;padding:5px 6px!important}
        .cb-dh-title{display:none}
        body.cb-dugout .coach-actions>.btn{min-height:70px!important}
        .cb-qd-field{min-height:232px}
        .cb-qd-spot{width:66px}
        .cb-qd-name{font-size:.59rem;padding:4px}
        .cb-qd-bench-player{font-size:.69rem;padding:7px 8px}
        .cb-end-zone{text-align:center}.cb-end-zone #liveEndGameBtn{width:100%!important}
        #cbCoachBoardNavModal .cb-app-grid{grid-template-columns:1fr 1fr}
      }
      @media(max-width:374.98px){
        .cb-dh-main{grid-template-columns:auto minmax(54px,.75fr) minmax(62px,.9fr) auto auto;gap:3px}
        .cb-dh-btn{font-size:.6rem!important;padding:4px 5px!important}
        .cb-qd-spot{width:61px}
        .cb-qd-name{font-size:.55rem}
      }
    `;
    document.head.appendChild(style);
  }

  function numberMap() {
    const map = new Map();
    (state?.roster || []).forEach(player => {
      const name = String(player?.name || '').trim();
      const number = String(player?.number ?? '').trim();
      if (name && number) map.set(name, number);
    });
    return map;
  }

  function displayName(name) {
    const clean = String(name || '').trim();
    const number = numberMap().get(clean);
    return number ? `#${number} ${clean}` : (clean || 'None');
  }

  function addNumbers() {
    const map = numberMap();
    if (!map.size) return;
    document.querySelectorAll('.coach-player-name,.coach-field-spot span,.coach-bench span,#live-board-prep-v3 .bp-field-spot .name,#live-board-prep-v3 .bp-move strong,#live-board-prep-v3 .bp-bench-list span,#live-pitcher-picker-v2 .pitcher-choice-v2 strong').forEach(el => {
      const number = map.get(String(el.textContent || '').trim());
      if (number) el.dataset.cbNumber = number;
      else delete el.dataset.cbNumber;
    });
  }

  function fmtSeconds(value) {
    let seconds = Number(value);
    if (!Number.isFinite(seconds)) return '—';
    const negative = seconds < 0;
    seconds = Math.abs(Math.floor(seconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    const valueText = hours
      ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
      : `${minutes}:${String(remainder).padStart(2, '0')}`;
    return negative ? `+${valueText}` : valueText;
  }

  function elapsed() {
    if (clock?.elapsed_seconds == null) return null;
    let value = Number(clock.elapsed_seconds) || 0;
    if (clock.is_live && clock.started_at_utc && !clock.ended_at_utc && !clock.is_paused && clockAt) {
      value += Math.max(0, Math.floor((Date.now() - clockAt) / 1000));
    }
    return value;
  }

  function clockInfo() {
    const current = elapsed();
    const limit = Number(clock?.time_limit_minutes || 0);
    const paused = Boolean(clock?.is_paused);
    if (limit && current != null) {
      const remaining = limit * 60 - current;
      return {
        label: `${paused ? 'Paused · ' : ''}${remaining < 0 ? 'Past limit' : 'Time left'}`,
        value: fmtSeconds(remaining),
        tone: remaining <= 0 ? 'danger' : remaining <= 600 ? 'warn' : '',
      };
    }
    return { label: `${paused ? 'Paused · ' : ''}Elapsed`, value: fmtSeconds(current), tone: '' };
  }

  function title() {
    return $('coach-game-title')?.textContent?.trim() || document.title.replace(/^Game\s+/i, '').trim();
  }

  function ensureAppMenu() {
    let modal = $('cbCoachBoardNavModal');
    if (modal) return modal;
    const role = String(document.body.dataset.coachRole || '');
    const gameChanger = role === 'Game Changer';
    modal = document.createElement('div');
    modal.id = 'cbCoachBoardNavModal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">CoachBoard Menu</h5><div class="small text-muted">Leave this screen without ending the game.</div></div><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body"><div class="cb-nav-safe"><strong>The game stays live.</strong> Leaving this screen does not end the game, change the inning, or change the clock. If the clock is paused, it stays paused until you resume it.</div><div class="cb-app-grid"><a class="cb-app-link cb-return-game" href="/game/${gameId}"><i class="bi bi-diamond-fill"></i><span>Back to Live Game</span></a>${gameChanger ? '' : '<a class="cb-app-link" href="/#overview"><i class="bi bi-house-door"></i><span>Home</span></a>'}<a class="cb-app-link" href="/game-day"><i class="bi bi-calendar3"></i><span>Game Day</span></a>${gameChanger ? '' : '<a class="cb-app-link" href="/#roster"><i class="bi bi-people"></i><span>Roster</span></a><a class="cb-app-link" href="/#practice_plan"><i class="bi bi-clipboard-check"></i><span>Practice</span></a><a class="cb-app-link" href="/pitching"><i class="bi bi-bullseye"></i><span>Pitching</span></a><a class="cb-app-link" href="/#more"><i class="bi bi-three-dots"></i><span>More</span></a>'}</div></div></div></div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function openAppMenu() {
    bootstrap.Modal.getOrCreateInstance(ensureAppMenu()).show();
  }
  window.openCoachBoardLiveMenu = openAppMenu;

  function renderHeader(shell) {
    let header = $('cbDugoutHeader');
    if (!header) {
      header = document.createElement('div');
      header.id = 'cbDugoutHeader';
      header.innerHTML = '<div class="cb-dh-main"><div class="cb-dh-live"><span class="cb-dh-dot"></span><span data-cb-live-label>Live Game</span></div><div class="cb-dh-inning"><small>Inning</small><strong data-cb-inning>1</strong></div><div class="cb-dh-clock"><small data-cb-clock-label>Elapsed</small><div class="cb-dh-time" data-cb-clock-time>—</div></div><div class="cb-dh-pitcher"><small>Pitcher</small><div class="cb-dh-name" data-cb-pitcher>None</div></div><button class="btn btn-outline-light btn-sm cb-dh-btn" data-cb-clock><i class="bi bi-clock me-1"></i>Clock</button><button class="btn btn-outline-light btn-sm cb-dh-btn" data-cb-menu aria-label="Open CoachBoard menu without ending the game"><i class="bi bi-grid me-1"></i>Menu</button></div><div class="cb-dh-title" data-cb-title></div>';
      shell.prepend(header);
      header.addEventListener('click', event => {
        if (event.target.closest('[data-cb-clock]')) document.querySelector('#cbLiveGameClock .cb-clock-config')?.click();
        if (event.target.closest('[data-cb-menu]')) openAppMenu();
      });
    }

    const info = clockInfo();
    const inning = state?.current_inning || clock?.current_inning || '1';
    const pitcher = state?.current_pitcher || state?.current_alignment?.P || 'None';
    const sync = $('live-sync-status-v2')?.textContent || '';
    const synced = /synced/i.test(sync) && !/not synced|reconnecting/i.test(sync);
    setText(header.querySelector('[data-cb-live-label]'), synced ? 'Live · Synced' : 'Live Game');
    setText(header.querySelector('[data-cb-inning]'), String(inning));
    setText(header.querySelector('[data-cb-clock-label]'), info.label);
    const time = header.querySelector('[data-cb-clock-time]');
    setText(time, info.value);
    time?.classList.toggle('warn', info.tone === 'warn');
    time?.classList.toggle('danger', info.tone === 'danger');
    setText(header.querySelector('[data-cb-pitcher]'), displayName(pitcher));
    setText(header.querySelector('[data-cb-title]'), title());
  }

  function positions() {
    return Number(state?.outfielder_count) === 4
      ? ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'LCF', 'RCF', 'RF']
      : ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'];
  }

  function positionSpots() {
    const outfield = Number(state?.outfielder_count) === 4
      ? [['LF', 10, 24], ['LCF', 37, 14], ['RCF', 63, 14], ['RF', 90, 24]]
      : [['LF', 14, 22], ['CF', 50, 11], ['RF', 86, 22]];
    return [...outfield, ['3B', 18, 57], ['SS', 38, 43], ['2B', 62, 43], ['1B', 82, 57], ['P', 50, 61], ['C', 50, 84]];
  }

  function currentAlignment() {
    return state?.current_alignment || {};
  }

  function playerForName(name) {
    return (state?.roster || []).find(player => player.name === name) || null;
  }

  function benchStreak(name) {
    const current = Number.parseFloat(state?.current_inning);
    if (!Number.isFinite(current)) return 0;
    const previous = Object.entries(state?.actual_rotation || {})
      .map(([inning, alignment]) => ({ inning: Number.parseFloat(inning), alignment: alignment || {} }))
      .filter(item => Number.isFinite(item.inning) && item.inning < current)
      .sort((a, b) => b.inning - a.inning);
    let streak = 0;
    for (const item of previous) {
      if (Object.values(item.alignment).includes(name)) break;
      streak += 1;
    }
    return streak;
  }

  function benchPlayers() {
    const assigned = new Set(Object.values(currentAlignment()).filter(Boolean));
    return (state?.roster || [])
      .filter(player => !assigned.has(player.name))
      .map(player => ({ ...player, benchStreak: benchStreak(player.name) }))
      .sort((a, b) => b.benchStreak - a.benchStreak || a.name.localeCompare(b.name));
  }

  function benchNote(streak) {
    if (streak >= 2) return `Sat ${streak} straight innings`;
    if (streak === 1) return 'Sat last inning';
    return 'Bench now';
  }

  function fieldSpot(pos, left, top) {
    const name = currentAlignment()?.[pos] || 'Open';
    const pitcher = pos === 'P';
    const number = numberMap().get(name);
    const label = number ? `#${number} ${name}` : name;
    return `<button type="button" class="cb-qd-spot ${pitcher ? 'pitcher' : ''}" style="left:${left}%;top:${top}%" data-cb-move-player="${esc(name)}" data-cb-position="${esc(pos)}" ${name === 'Open' ? 'disabled' : ''}><span class="cb-qd-pos">${esc(pos)}</span><span class="cb-qd-name">${esc(label)}</span></button>`;
  }

  function saveStateMarkup() {
    const icon = saveMode === 'saving' ? 'bi-arrow-repeat' : saveMode === 'error' ? 'bi-exclamation-triangle' : 'bi-check-circle-fill';
    const retry = saveMode === 'error' && lastFailedMove ? ' data-cb-retry-move role="button" tabindex="0"' : '';
    return `<div class="cb-save-state ${saveMode}"${retry}><i class="bi ${icon}"></i><span>${esc(saveMessage)}</span></div>`;
  }

  function quickDefenseMarkup() {
    const bench = benchPlayers();
    const benchMarkup = bench.length
      ? bench.map(player => {
          const number = String(player.number ?? '').trim();
          return `<button type="button" class="cb-qd-bench-player ${player.benchStreak >= 2 ? 'priority' : ''}" data-cb-move-player="${esc(player.name)}"><span>${esc(number ? `#${number} ${player.name}` : player.name)}</span><span class="cb-bench-note">${esc(benchNote(player.benchStreak))}</span></button>`;
        }).join('')
      : '<span class="small text-muted">No players are on the bench.</span>';

    return `<div class="cb-qd-head"><div><div class="cb-qd-kicker">Current Defense</div><div class="cb-qd-title">Field + bench at a glance</div><div class="cb-qd-help">Tap any fielder or bench player to move them. Pitcher changes stay in Change Pitcher.</div></div>${saveStateMarkup()}</div><div class="cb-qd-body"><div class="cb-qd-field"><svg class="cb-qd-field-art" viewBox="0 0 100 88" preserveAspectRatio="none" aria-hidden="true"><path d="M7 57 Q9 13 50 6 Q91 13 93 57" fill="none" stroke="rgba(245,245,220,.38)" stroke-width="1.2"/><path d="M50 84 L8 38 M50 84 L92 38" fill="none" stroke="rgba(255,255,255,.88)" stroke-width=".7"/><polygon points="50,75 27,54 50,32 73,54" fill="#cfa56c" opacity=".95"/><polygon points="50,68 34,54 50,40 66,54" fill="#438f58"/><circle cx="50" cy="61" r="4.8" fill="#cfa56c"/><circle cx="50" cy="81" r="6.2" fill="#cfa56c"/><rect x="49" y="31" width="2" height="2" fill="#fff" transform="rotate(45 50 32)"/><rect x="72" y="53" width="2" height="2" fill="#fff" transform="rotate(45 73 54)"/><rect x="26" y="53" width="2" height="2" fill="#fff" transform="rotate(45 27 54)"/><path d="M48.8 81.5 L50 80.4 L51.2 81.5 L50.8 83 L49.2 83 Z" fill="#fff"/></svg>${positionSpots().map(([pos, left, top]) => fieldSpot(pos, left, top)).join('')}</div><div class="cb-qd-bench-wrap"><div class="cb-qd-bench-head"><strong>Bench now · ${bench.length}</strong><span>${bench.length ? 'Players sitting longest are shown first' : 'Everyone is in the field'}</span></div><div class="cb-qd-bench">${benchMarkup}</div></div><div class="cb-qd-actions"><div class="cb-qd-tip">For a substitution, tap the bench player first, then tap the field position. The outgoing player moves to the bench automatically.</div><button type="button" class="btn btn-outline-secondary" data-cb-full-defense><i class="bi bi-sliders me-1"></i>Full editor</button></div></div>`;
  }

  function quickDefenseStateSignature() {
    return JSON.stringify({
      inning: state?.current_inning || null,
      alignment: currentAlignment(),
      bench: benchPlayers().map(player => [player.id, player.name, player.number, player.benchStreak]),
      outfielderCount: state?.outfielder_count || 3,
      saveMode,
      saveMessage,
      retry: lastFailedMove ? [lastFailedMove.playerId, lastFailedMove.destination] : null,
    });
  }

  function ensureQuickDefense(shell) {
    let card = $('cbQuickDefense');
    if (!card) {
      card = document.createElement('div');
      card.id = 'cbQuickDefense';
      card.className = 'coach-card cb-quick-defense';
      const actions = shell.querySelector('#coach-action-slot');
      if (actions) actions.insertAdjacentElement('beforebegin', card);
      else shell.prepend(card);
      card.addEventListener('click', event => {
        const retry = event.target.closest('[data-cb-retry-move]');
        if (retry && lastFailedMove) {
          saveMove(lastFailedMove.playerId, lastFailedMove.destination, lastFailedMove.name);
          return;
        }
        const full = event.target.closest('[data-cb-full-defense]');
        if (full) {
          const button = $('liveSetDefenseBtnCoach');
          if (button) button.click();
          else $('liveDefensiveChangeBtn')?.click();
          return;
        }
        const player = event.target.closest('[data-cb-move-player]');
        if (!player || player.disabled) return;
        const name = player.dataset.cbMovePlayer;
        const pos = player.dataset.cbPosition;
        if (pos === 'P') {
          $('liveChangePitcherBtn')?.click();
          return;
        }
        openMoveModal(name);
      });
      card.addEventListener('keydown', event => {
        if ((event.key === 'Enter' || event.key === ' ') && event.target.closest('[data-cb-retry-move]') && lastFailedMove) {
          event.preventDefault();
          saveMove(lastFailedMove.playerId, lastFailedMove.destination, lastFailedMove.name);
        }
      });
    }
    return card;
  }

  function renderQuickDefense(shell) {
    const card = ensureQuickDefense(shell);
    if (!card || !state?.game?.is_live) return;
    const signature = quickDefenseStateSignature();
    if (signature === quickDefenseSignature && card.childElementCount) return;
    quickDefenseSignature = signature;
    card.innerHTML = quickDefenseMarkup();
  }

  function ensureMoveModal() {
    let modal = $('cbQuickMoveModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'cbQuickMoveModal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = '<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Move Player</h5><div class="small text-muted">Tap the new position. Occupied positions swap automatically.</div></div><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body"></div></div></div>';
    document.body.appendChild(modal);
    return modal;
  }

  function openMoveModal(name) {
    const player = playerForName(name);
    if (!player) return;
    const alignment = currentAlignment();
    const source = Object.entries(alignment).find(([, playerName]) => playerName === name)?.[0] || 'BENCH';
    if (source === 'P') {
      $('liveChangePitcherBtn')?.click();
      return;
    }
    const modal = ensureMoveModal();
    const body = modal.querySelector('.modal-body');
    const destinations = positions().filter(pos => pos !== 'P' && pos !== source);
    const sourceText = source === 'BENCH' ? `${name} is currently on the bench.` : `${name} is currently playing ${source}.`;
    body.innerHTML = `<div class="cb-move-current"><strong>${esc(sourceText)}</strong><br>${source === 'BENCH' ? 'Choose a field position. The player currently there will move to the bench.' : 'Choose another field position to swap the two players.'}</div><div class="cb-destination-grid">${destinations.map(pos => {
      const occupant = alignment[pos] || '';
      return `<button type="button" class="btn btn-outline-primary cb-destination" data-cb-destination="${esc(pos)}"><span>${esc(pos)}</span><small>${occupant ? `Currently ${esc(occupant)}` : 'Open position'}</small></button>`;
    }).join('')}</div>`;
    body.querySelectorAll('[data-cb-destination]').forEach(button => {
      button.addEventListener('click', () => saveMove(player.id, button.dataset.cbDestination, player.name));
    });
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  async function saveMove(playerId, destination, name) {
    if (moveBusy) return;
    moveBusy = true;
    saveMode = 'saving';
    saveMessage = 'Saving…';
    lastFailedMove = null;
    quickDefenseSignature = '';
    const shell = document.querySelector('#live-game-overlay .coach-live-shell');
    if (shell) renderQuickDefense(shell);
    try {
      const response = await fetch(`/api/live-game/${gameId}/defensive-change`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: playerId, destination_position: destination }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || `Unable to save defense (${response.status}).`);
      if (data.state) state = data.state;
      saveMode = 'saved';
      saveMessage = 'Saved ✓';
      quickDefenseSignature = '';
      bootstrap.Modal.getOrCreateInstance(ensureMoveModal()).hide();
      queue();
    } catch (error) {
      saveMode = 'error';
      saveMessage = 'Not saved — Retry';
      lastFailedMove = { playerId, destination, name };
      quickDefenseSignature = '';
      if (shell) renderQuickDefense(shell);
      const modal = ensureMoveModal();
      const body = modal.querySelector('.modal-body');
      if (body && !body.querySelector('.alert-danger')) {
        body.insertAdjacentHTML('afterbegin', `<div class="alert alert-danger py-2 small"><strong>Change was not saved.</strong><br>${esc(error.message)}</div>`);
      }
    } finally {
      moveBusy = false;
    }
  }

  function defenseCard(shell) {
    return [...shell.querySelectorAll('.coach-card')].find(card => card !== $('cbQuickDefense') && card.querySelector('.coach-defense-row,.coach-field,.coach-view-toggle')) || null;
  }

  function arrange(shell) {
    [
      ['liveChangePitcherBtn', 'Change Pitcher', 'Mound change'],
      ['liveDefensiveChangeBtn', 'Change Defense', 'Tap a player or choose manually'],
      ['liveEndInningBtn', 'End Inning', 'Load the saved next defense'],
      ['liveUndoBtn', 'Undo', 'Reverse the last live change'],
    ].forEach(([id, titleText, note]) => setHtml($(id), `<span class="coach-action-title">${titleText}</span><span class="coach-action-note">${note}</span>`));

    const whole = $('liveSetDefenseBtnCoach');
    const legacyCard = defenseCard(shell);
    if (legacyCard) {
      legacyCard.classList.add('cb-legacy-defense-card');
      legacyCard.querySelector('.coach-view-toggle')?.remove();
    }
    if (whole && legacyCard) {
      let tools = legacyCard.querySelector('.cb-defense-tools');
      if (!tools) {
        tools = document.createElement('div');
        tools.className = 'cb-defense-tools';
        legacyCard.prepend(tools);
      }
      if (whole.parentElement !== tools) tools.appendChild(whole);
      setHtml(whole, '<span class="coach-action-title">Set Whole Defense</span><span class="coach-action-note">Replace multiple positions at once</span>');
    }

    const end = $('liveEndGameBtn');
    if (end) {
      let zone = shell.querySelector('.cb-end-zone');
      if (!zone) {
        zone = document.createElement('div');
        zone.className = 'cb-end-zone';
        zone.innerHTML = '<small>Only when the baseball game is over</small>';
        shell.appendChild(zone);
      }
      if (end.parentElement !== zone) zone.appendChild(end);
      setHtml(end, '<i class="bi bi-stop-circle me-1"></i> End Game');
    }

    const board = $('live-board-prep-v3');
    if (board) {
      setText(board.querySelector('.bp-kicker'), 'Next Inning');
      setText(board.querySelector('.bp-help'), 'Pick the next defense. CoachBoard shows the physical-board moves you need to make.');
      const badge = board.querySelector('.bp-status.ready .bp-status-badge');
      if (badge) setText(badge, 'DEFENSE SAVED');
    }
  }

  function focusBoard() {
    const board = $('live-board-prep-v3');
    if (!board) return;
    board.scrollIntoView({ behavior: 'smooth', block: 'start' });
    board.classList.remove('cb-board-flash');
    void board.offsetWidth;
    board.classList.add('cb-board-flash');
    setTimeout(() => board.classList.remove('cb-board-flash'), 1700);
  }

  function patch() {
    queued = false;
    styles();
    const live = Boolean(state?.game?.is_live || !$('live-game-overlay')?.classList.contains('d-none'));
    document.body.classList.toggle('cb-dugout', live);
    document.body.classList.toggle('cb-clock-paused', live && Boolean(clock?.is_paused));
    if (!live) {
      $('cbDugoutHeader')?.remove();
      $('cbQuickDefense')?.remove();
      quickDefenseSignature = '';
      return;
    }
    const shell = document.querySelector('#live-game-overlay .coach-live-shell');
    if (!shell) return;
    renderHeader(shell);
    renderQuickDefense(shell);
    arrange(shell);
    addNumbers();
  }

  function queue() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(patch);
  }

  async function getState() {
    if (stateBusy) return;
    stateBusy = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/state`, { cache: 'no-store' });
      if (!response.ok) return;
      const next = await response.json();
      state = next;
      if (saveMode !== 'error') {
        saveMode = 'saved';
        saveMessage = 'Saved ✓';
      }
      queue();
      if (endInningFrom && String(next.current_inning) !== String(endInningFrom)) {
        endInningFrom = null;
        setTimeout(focusBoard, 220);
      }
    } catch (_) {
    } finally {
      stateBusy = false;
    }
  }

  async function getClock() {
    if (clockBusy) return;
    clockBusy = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/clock`, { cache: 'no-store' });
      if (!response.ok) return;
      clock = (await response.json())?.clock || null;
      clockAt = Date.now();
      queue();
    } catch (_) {
    } finally {
      clockBusy = false;
    }
  }

  function start() {
    styles();
    document.addEventListener('click', event => {
      const button = event.target.closest('#liveEndInningBtn');
      if (!button || button.disabled) return;
      endInningFrom = String(state?.current_inning || $('live-inning-display')?.textContent || '');
      // The End Inning request and Socket.IO broadcast normally update the page.
      // One delayed state read is enough as a network fallback; the old three-read
      // sequence made the dugout feel busier on phones and tablets.
      setTimeout(getState, 700);
    }, true);
    const liveOverlay = $('live-game-overlay');
    if (liveOverlay) {
      // Watch only the live-game surface. Observing the entire document — including
      // clock text, menus, toasts, and unrelated Bootstrap changes — caused needless
      // redraw scheduling during every live inning.
      new MutationObserver(queue).observe(liveOverlay, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['class'],
      });
    }
    getState();
    getClock();
    // Socket/API responses are the primary source of live changes. Periodic reads
    // remain only as recovery in case a browser misses an update.
    setInterval(getState, 12000);
    setInterval(getClock, 15000);
    setInterval(() => {
      if (document.body.classList.contains('cb-dugout')) queue();
    }, 1000);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        getState();
        getClock();
      }
    });
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, { once: true })
    : start();
})();