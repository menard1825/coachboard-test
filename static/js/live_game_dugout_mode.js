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
  let moveBusy = false;
  // The move moveBusy is held for: resolves once it has settled -- true if
  // it was saved, false if it was refused or failed (whenIdle).
  let moveSettled = Promise.resolve(true);
  let lastFailedMove = null;
  let saveMode = 'saved';
  let saveMessage = 'Saved';
  let quickDefenseSignature = '';
  let lastFailureKind = null;
  let reconnectMessageUntil = 0;
  let openMoveContext = null;

  function failureKind(error) {
    const message = String(
      error?.message || ''
    ).toLowerCase();

    if (
      error instanceof TypeError ||
      message.includes('load failed') ||
      message.includes('failed to fetch') ||
      message.includes('networkerror') ||
      message.includes('network request failed') ||
      message.includes('offline')
    ) {
      return 'network';
    }

    return 'server';
  }

  function clearRecoveredNetworkFailure() {
    if (lastFailureKind !== 'network') return;

    lastFailureKind = null;
    lastFailedMove = null;
    saveMode = 'saved';
    saveMessage = 'Reconnected · Live field updated';
    reconnectMessageUntil = Date.now() + 5000;
    quickDefenseSignature = '';

    const modal = $('cbQuickMoveModal');

    if (modal) {
      modal
        .querySelectorAll('.alert-danger')
        .forEach(alert => alert.remove());

      if (modal.classList.contains('show')) {
        try {
          bootstrap.Modal
            .getOrCreateInstance(modal)
            .hide();
        } catch (_) {}
      }
    }
  }

  function sequenceFromState(value = state) {
    const eventSequence = (value?.rotation_events || []).reduce(
      (max, event) => {
        if (event?.reverted) return max;
        return Math.max(
          max,
          Number(event?.sequence) || 0,
        );
      },
      0,
    );

    // Fast live writes arrive as deltas and can contain a newer
    // authoritative sequence before rotation_events is refreshed.
    // Using only rotation_events makes an immediate Undo look stale.
    return Math.max(
      eventSequence,
      Number(value?.sequence) || 0,
      Number(value?.event?.sequence) || 0,
    );
  }

  function alignmentKey(alignment) {
    return JSON.stringify(
      Object.entries(alignment || {})
        .filter(([, name]) => name)
        .sort(([a], [b]) => a.localeCompare(b))
    );
  }

  function captureMoveContext(alignment = currentAlignment()) {
    return {
      alignment: {...(alignment || {})},
      baseSequence: sequenceFromState(),
    };
  }

  function moveContextIsCurrent(context) {
    if (!context) return true;

    return (
      Number(context.baseSequence || 0) === Number(sequenceFromState() || 0) &&
      alignmentKey(context.alignment) === alignmentKey(currentAlignment())
    );
  }

  function showStaleMove() {
    lastFailedMove = null;
    lastFailureKind = 'server';
    saveMode = 'error';
    saveMessage = `Not saved — ${STALE_MOVE_MESSAGE}`;
    quickDefenseSignature = '';

    const shell = document.querySelector('#live-game-overlay .coach-live-shell');
    if (shell) renderQuickDefense(shell);
  }

  function invalidateOpenMoveIfStale() {
    if (!openMoveContext || moveContextIsCurrent(openMoveContext)) return;

    const modal = $('cbQuickMoveModal');
    openMoveContext = null;

    if (modal?.classList.contains('show')) {
      bootstrap.Modal.getOrCreateInstance(modal).hide();
    }

    showStaleMove();
  }

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
      body.cb-dugout #live-game-overlay{
        min-height:100vh;
        background:#eef1f4!important;
        padding:0 0 24px!important;
      }
      body.cb-dugout .coach-live-shell{max-width:1100px!important;margin:auto!important;padding:0 10px 24px!important}
      body.cb-dugout #coach-pitcher-slot{display:none!important}

      #cbDugoutHeader{position:sticky;top:0;z-index:1040;margin:0 -10px 12px;padding:9px 12px;background:#101828;color:#fff;border-bottom:3px solid var(--primary-color,#102a66);box-shadow:0 4px 14px rgba(16,24,40,.2)}
      .cb-dh-main{display:grid;grid-template-columns:auto auto minmax(0,1fr) minmax(0,auto) auto auto auto;align-items:center;gap:10px}
      .cb-dh-live{display:flex;gap:6px;align-items:center;font-size:var(--cb-text-2xs);font-weight:900;text-transform:uppercase;letter-spacing:.08em;white-space:nowrap}
      .cb-dh-dot{width:8px;height:8px;border-radius:50%;background:#2dd36f}
      .cb-dh-inning{min-width:58px;text-align:center;border-inline:1px solid #ffffff2e;padding:0 10px}
      .cb-dh-inning small,.cb-dh-clock small,.cb-dh-pitcher small{display:block;color:#cbd5e1;font-size:var(--cb-text-2xs);font-weight:800;text-transform:uppercase;letter-spacing:.08em;line-height:1.1}
      .cb-dh-inning strong{display:block;font-size:1.35rem;line-height:1.05;margin-top:2px}
      .cb-dh-time{font-size:1.08rem;font-weight:850;font-variant-numeric:tabular-nums;white-space:nowrap;margin-top:2px}
      .cb-dh-time.warn{color:#ffd166}.cb-dh-time.danger{color:#ff8a80}
      .cb-dh-pitcher{text-align:right;min-width:0}
      .cb-dh-name{font-size:.88rem;font-weight:800;max-width:230px;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere;line-height:1.05}
      .cb-dh-btn{min-height:44px!important;border-radius:9px!important;font-weight:750!important}
      /* Undo lives in this header. It used to be pinned into .coach-live-head,
         which Dugout Mode otherwise hides, so gameday_pitching_steppers.js had
         to un-hide that row purely to keep one button reachable -- a whole
         control row of vertical space for a single 46px control. These
         selectors carry two ids so they outrank every earlier placement rule
         (#liveUndoBtn.cb-command-undo, body.cb-dugout #liveUndoBtn) wherever
         those modules still load. */
      body.cb-dugout #cbDugoutHeader #liveUndoBtn.cb-dh-undo{display:inline-flex!important;align-items:center!important;justify-content:center!important;gap:5px!important;min-width:44px!important;min-height:44px!important;height:44px!important;width:auto!important;margin:0!important;padding:0 10px!important;border:1px solid #ffffff5c!important;border-radius:9px!important;background:transparent!important;color:#fff!important;box-shadow:none!important;font-size:.7rem!important;font-weight:800!important;line-height:1!important;letter-spacing:.02em;flex:none!important;touch-action:manipulation}
      body.cb-dugout #cbDugoutHeader #liveUndoBtn.cb-dh-undo i{display:inline-block!important;margin:0!important;font-size:1rem!important}
      body.cb-dugout #cbDugoutHeader #liveUndoBtn .cb-dh-undo-text{display:inline-flex;flex-direction:column;align-items:flex-start;gap:2px;text-align:left}
      body.cb-dugout #cbDugoutHeader #liveUndoBtn .cb-dh-undo-scope{font-size:.58rem;font-weight:700;letter-spacing:0;opacity:.88;white-space:nowrap}
      body.cb-dugout #cbDugoutHeader #liveUndoBtn.cb-dh-undo:disabled{opacity:.42!important;cursor:not-allowed!important}
      body.cb-dugout #cbDugoutHeader #liveUndoBtn.cb-dh-undo[hidden]{display:none!important}
      /* The button is adopted from #coach-action-slot, where live_game_coach_ui
         first places it. Hide it there so it never flashes as a third action
         tile in the frame before this header claims it. */
      body.cb-dugout #coach-action-slot #liveUndoBtn{display:none!important}
      .cb-dh-title{margin-top:6px;color:#cbd5e1;font-size:var(--cb-text-xs);font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      body.cb-clock-paused #cbDugoutHeader{border-bottom-color:#f5b942!important}
      body.cb-clock-paused #cbDugoutHeader .cb-dh-time{color:#ffd166!important}
      /* The dot carries connection health, so a paused clock only tints it
         while the connection is healthy -- a pause must never make a broken
         connection look fine. Pause stays legible either way through the
         clock label ("Paused · Elapsed") and the header border. */
      body.cb-clock-paused #cbDugoutHeader[data-cb-sync="synced"] .cb-dh-dot{background:#f5b942!important}
      #cbDugoutHeader[data-cb-sync="reconnecting"] .cb-dh-dot{background:#f5b942!important}
      #cbDugoutHeader[data-cb-sync="offline"] .cb-dh-dot{background:#e5484d!important}
      #cbDugoutHeader[data-cb-sync="reconnecting"] .cb-dh-live{color:#ffd166!important}
      #cbDugoutHeader[data-cb-sync="offline"] .cb-dh-live{color:#ff9ea1!important}

      #cbCoachBoardNavModal .modal-content{border:0;border-radius:15px;overflow:hidden}
      #cbCoachBoardNavModal .cb-nav-safe{border:1px solid #b9dcc4;background:#f4fbf6;color:#22543d;border-radius:10px;padding:9px 10px;font-size:.75rem;line-height:1.4;margin-bottom:12px}
      #cbCoachBoardNavModal .cb-app-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
      #cbCoachBoardNavModal .cb-app-link{min-height:58px;border:1px solid #dfe4ea;border-radius:11px;background:#fff;color:#253047;text-decoration:none;display:flex;align-items:center;gap:9px;padding:10px 11px;font-size:.8rem;font-weight:780}
      #cbCoachBoardNavModal button.cb-app-link{width:100%;text-align:left;font-family:inherit}
      #cbCoachBoardNavModal .cb-app-link i{font-size:1.05rem;color:var(--cb-primary-text,#102a66)}
      #cbCoachBoardNavModal .cb-return-game{grid-column:1/-1;background:var(--primary-color,#102a66);border-color:var(--primary-color,#102a66);color:var(--cb-on-primary,#fff)}
      #cbCoachBoardNavModal .cb-return-game i{color:var(--cb-on-primary,#fff)}

      body.cb-dugout .coach-actions{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:10px!important;margin:0 0 12px!important}
      body.cb-dugout .coach-actions>.btn{min-height:68px!important;border-radius:12px!important;border-width:2px!important;padding:9px!important;align-items:center!important;text-align:center!important;justify-content:center!important;touch-action:manipulation}
      body.cb-dugout .coach-action-title{font-size:.96rem!important;font-weight:850!important}
      body.cb-dugout .coach-action-note{font-size:.67rem!important;margin-top:4px!important;opacity:.78!important}
      body.cb-dugout #liveChangePitcherBtn{background:var(--primary-color,#102a66)!important;border-color:var(--primary-color,#102a66)!important;color:var(--cb-on-primary,#fff)!important}
      body.cb-dugout #liveEndInningBtn{background:#172033!important;border-color:#172033!important;color:#fff!important}
      body.cb-dugout #liveUndoBtn{background:#fff!important;border-color:#cfd5dd!important;color:#475467!important}
      body.cb-dugout .coach-card{border:1.5px solid #cfd5dd!important;border-radius:14px!important;box-shadow:0 2px 7px #10182814!important;background:#fff!important;padding:13px!important;margin-bottom:12px!important}

      .cb-quick-defense{padding:0!important;overflow:hidden}
      .cb-qd-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;padding:12px 13px 10px;border-bottom:1px solid #e8ebef;background:#fff}
      .cb-qd-kicker{font-size:var(--cb-text-2xs);text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#667085}
      .cb-qd-title{font-size:1rem;font-weight:850;color:#172033;margin-top:1px}
      .cb-qd-help{font-size:.7rem;color:#667085;margin-top:2px;line-height:1.3}
      .cb-save-state{flex:0 0 auto;min-height:30px;border-radius:999px;padding:6px 9px;font-size:var(--cb-text-2xs);font-weight:850;display:inline-flex;align-items:center;gap:5px;border:1px solid #b8ddc4;background:#edf8f1;color:#176b38}
      .cb-save-state.saving{border-color:#c7d7ef;background:#f3f7fd;color:#315d98}
      .cb-save-state.error{border-color:#edb8b2;background:#fff2f0;color:#b42318;cursor:pointer}
      .cb-qd-body{padding:10px 11px 12px}
      .cb-qd-field{position:relative;aspect-ratio:1.28/1;min-height:238px;overflow:hidden;border:1px solid #d8e2d8;border-radius:12px;background:repeating-linear-gradient(90deg,#3d8f55 0,#3d8f55 12.5%,#438f58 12.5%,#438f58 25%)}
      .cb-qd-field-art{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
      /* Field markers (On the Field and Next Inning share them). Position
         and jersey ride on the grass line; the name box holds only the name
         so it can be the largest, easiest text on the field. The sizes are
         set once here per layout and used by every marker override.
         A marker is never narrower than the longest word in its name: names
         wrap between words ("Benjamin / Hollingsworth"), not inside them. */
      :root{--cb-marker-name:.67rem;--cb-marker-pos:.625rem}
      .cb-qd-spot{position:absolute;transform:translate(-50%,-50%);z-index:2;width:clamp(62px,20vw,112px);min-width:min-content;border:0;background:transparent;padding:0;text-align:center;touch-action:manipulation}
      .cb-qd-pos{display:block;color:#fff;font-size:var(--cb-marker-pos);font-weight:900;line-height:1;text-shadow:0 1px 2px rgba(0,0,0,.45);margin-bottom:2px;letter-spacing:.03em}
      .cb-qd-num{margin-left:.3em;font-weight:800}
      .cb-qd-name{display:block;width:100%;background:rgba(255,255,255,.96);border:1px solid #dce1e5;border-radius:8px;padding:4px 2px;font-size:var(--cb-marker-name);line-height:1.04;font-weight:820;color:#172033;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:break-word;box-shadow:0 1px 2px rgba(16,24,40,.1)}
      .cb-qd-spot:active .cb-qd-name,.cb-qd-bench-player:active{transform:scale(.98)}
      .cb-qd-spot.pitcher .cb-qd-name{border-color:#b7c8e8;background:#f5f8ff}
      .cb-qd-bench-wrap{margin-top:9px;border:1px solid #e2e6eb;border-radius:11px;background:#f8fafc;padding:9px}
      .cb-qd-bench-head{display:flex;justify-content:space-between;gap:8px;align-items:baseline;margin-bottom:7px}
      .cb-qd-bench-head strong{font-size:.74rem;color:#253047}
      .cb-qd-bench-head span{font-size:var(--cb-text-xs);color:var(--cb-muted);text-align:right}
      .cb-qd-bench{display:flex;flex-wrap:wrap;gap:6px}
      .cb-qd-bench-player{border:1px solid #cfd5dd;background:#fff;color:#253047;border-radius:10px;padding:7px 9px;text-align:left;font-size:.72rem;font-weight:760;line-height:1.08;touch-action:manipulation}
      .cb-qd-bench-player .cb-bench-note{display:block;margin-top:3px;color:#667085;font-size:.58rem;font-weight:650}
      .cb-qd-bench-player.priority{border-color:#d8b96a;background:#fff9e9}
      .cb-qd-actions{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-top:9px}
      .cb-qd-tip{font-size:.62rem;color:#667085;line-height:1.25}

      #cbQuickMoveModal .modal-content{border:0;border-radius:15px;overflow:hidden}
      #cbQuickMoveModal .cb-move-current{border:1px solid #dfe4ea;background:#f8fafc;border-radius:10px;padding:9px 10px;margin-bottom:10px;font-size:.76rem;color:#475467}
      #cbQuickMoveModal .cb-destination-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
      #cbQuickMoveModal .cb-destination{min-height:60px;border-radius:10px;text-align:left;font-weight:820;padding:8px 10px}
      #cbQuickMoveModal .cb-destination small{display:block;font-size:.62rem;font-weight:550;margin-top:3px;opacity:.75;line-height:1.15}

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
      .cb-board-flash{animation:cbBoardFlash 1.5s ease-out 1}@keyframes cbBoardFlash{50%{box-shadow:0 0 0 8px color-mix(in srgb,var(--cb-primary,#102a66) 14%,transparent)}}

      .cb-end-zone{margin-top:16px;padding-top:12px;border-top:1px solid #cfd5dd;text-align:right}
      .cb-end-zone small{display:block;color:#667085;font-size:.62rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}
      .cb-end-zone #liveEndGameBtn{min-height:42px!important;width:auto!important;border-radius:10px!important;padding:7px 13px!important;font-weight:800!important;background:#fff!important;color:#b42318!important;border:1.5px solid #d92d20!important;box-shadow:none!important}
      body.cb-dugout #live-pitcher-picker-v2 .pitcher-choice-v2{min-height:58px!important;padding:14px!important;font-size:.94rem!important;touch-action:manipulation}
      body.cb-dugout #live-pitcher-destination-v2 .btn,body.cb-dugout #next-inning-adjust-modal .btn{min-height:54px!important;font-size:.92rem!important;touch-action:manipulation}
      body.cb-dugout #next-inning-adjust-modal .form-select{min-height:52px!important;font-size:.95rem!important}

      @media(min-width:768px) and (min-height:600px){
        body.cb-dugout .coach-actions{grid-template-columns:repeat(4,minmax(0,1fr))!important}
        .cb-qd-field{min-height:330px}
        .cb-qd-spot{width:clamp(78px,11vw,122px)}
        :root{--cb-marker-name:.75rem;--cb-marker-pos:.66rem}
      }
      @media(max-width:575.98px){
        #cbDugoutHeader{margin:0 -10px 10px;padding:8px 9px}
        /* Phone: the controls get their own row -- status on the left,
           Undo / Pause / Menu (44px, each with its word) on the right -- and
           the game state gets the whole second row, so the inning, the clock
           and the pitcher's name never squeeze into each other. */
        .cb-dh-main{grid-template-columns:auto auto minmax(0,1fr) auto auto;grid-template-areas:"live live undo clockbtn menu" "inning clock pitcher pitcher pitcher";gap:6px 6px}
        .cb-dh-live{grid-area:live;display:flex;font-size:var(--cb-text-2xs);letter-spacing:.04em;gap:4px;min-width:0}
        .cb-dh-dot{width:8px;height:8px}
        .cb-dh-inning{grid-area:inning;min-width:44px;padding:0 8px 0 0;border-left:0}
        .cb-dh-clock{grid-area:clock;min-width:0;padding-right:8px;border-right:1px solid #ffffff2e}
        /* The clock's tap area (live_game_clock_controls) must not spill
           sideways into the inning and pitcher next to it. */
        html body #cbDugoutHeader .cb-dh-clock{margin:-4px 0}
        .cb-dh-pitcher{grid-area:pitcher;display:block!important;text-align:left;min-width:0}
        .cb-dh-undo-slot{grid-area:undo;justify-self:end}
        .cb-dh-main>[data-cb-clock]{grid-area:clockbtn}
        .cb-dh-main>[data-cb-menu]{grid-area:menu}
        .cb-dh-inning strong{font-size:1.2rem}
        .cb-dh-time{font-size:.95rem}
        .cb-dh-name{font-size:.82rem;max-width:none;line-height:1.15}
        .cb-dh-btn{font-size:.75rem!important;padding:5px 9px!important}
        body.cb-dugout #cbDugoutHeader #liveUndoBtn.cb-dh-undo{padding:0 9px!important;font-size:.75rem!important}
        .cb-dh-title{display:none}
        body.cb-dugout .coach-actions>.btn{min-height:70px!important}
        .cb-qd-field{min-height:232px}
        /* Names a little larger than before; the marker keeps its size so
           long names still wrap between words without meeting a neighbour. */
        .cb-qd-spot{width:66px;min-height:30px}
        :root{--cb-marker-name:.66rem;--cb-marker-pos:.62rem}
        .cb-qd-name{padding:2px}
        /* The phone field is short. Lift SS and 2B and drop 3B and 1B a
           few pixels, so a two-line name at short or second never reaches
           into the next marker's tap area. */
        .cb-qd-spot:is([data-cb-position="SS"],[data-cb-position="2B"],[data-next-position="SS"],[data-next-position="2B"]){margin-top:-6px}
        .cb-qd-spot:is([data-cb-position="3B"],[data-cb-position="1B"],[data-next-position="3B"],[data-next-position="1B"]){margin-top:6px}
        .cb-qd-bench-player{font-size:.69rem;padding:7px 8px}
        .cb-end-zone{text-align:center}.cb-end-zone #liveEndGameBtn{width:100%!important}
        #cbCoachBoardNavModal .cb-app-grid{grid-template-columns:1fr 1fr}
      }
      @media(max-width:374.98px){
        /* 320px: the same two rows, a little tighter. */
        .cb-dh-main{gap:5px 4px}
        .cb-dh-live{font-size:.56rem;letter-spacing:.02em}
        .cb-dh-inning{min-width:38px;padding-right:6px}
        .cb-dh-clock{padding-right:6px}
        .cb-dh-time{font-size:.88rem}
        .cb-dh-name{font-size:.78rem}
        .cb-dh-btn{font-size:.7rem!important;padding:4px 7px!important}
        body.cb-dugout #cbDugoutHeader #liveUndoBtn.cb-dh-undo{padding:0 7px!important;font-size:.7rem!important}
        /* The two-line name ("Undo / next inning") needs the icon's room. */
        body.cb-dugout #cbDugoutHeader #liveUndoBtn.cb-dh-undo i{display:none!important}
        /* Below 375px the field is too narrow for larger names: long ones
           would run into the next marker. Markers keep their earlier size. */
        .cb-qd-spot{width:61px}
        :root{--cb-marker-name:.6rem;--cb-marker-pos:.5625rem}
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

  /*
   * The running clock between /clock reads. A read gives whole seconds
   * (elapsed_seconds); counting on from each one moved the display by up to
   * a second at every read -- a 2-second step, then a 2-second pause, every
   * 15 s. Instead the clock runs from started_at on this device's clock,
   * shifted by clockOffsetMs (server time minus device time). Each read says
   * the server's time was in [started + E, started + E + 1 s) while this
   * device's clock read between sending and receiving; the offset only moves
   * when it falls outside that window -- a real correction (a wrong device
   * clock), not a rounding one. Paused or ended: the server's value.
   */
  let clockOffsetMs = null;

  function parseUtc(value) {
    // Microseconds (Python's isoformat) are not parsed by every browser.
    return Date.parse(String(value || '').replace(/(\.\d{3})\d+/, '$1'));
  }

  function correctClockOffset(payload, sentAt, receivedAt) {
    const started = parseUtc(payload?.started_at_utc);
    if (!payload?.is_live || payload.ended_at_utc || payload.elapsed_seconds == null || !Number.isFinite(started)) return;
    const reported = started + Number(payload.elapsed_seconds) * 1000;
    const lowest = reported - receivedAt;
    const highest = reported + 1000 - sentAt;
    const current = clockOffsetMs ?? Math.min(Math.max(0, lowest), highest);
    clockOffsetMs = Math.min(Math.max(current, lowest), highest);
  }

  function clockRunning() {
    return Boolean(
      clock?.is_live && !clock.ended_at_utc && !clock.is_paused &&
      clockOffsetMs !== null && Number.isFinite(parseUtc(clock.started_at_utc))
    );
  }

  function elapsedMs() {
    return Date.now() + clockOffsetMs - parseUtc(clock.started_at_utc);
  }

  function elapsed() {
    if (clock?.elapsed_seconds == null) return null;
    if (clockRunning()) return Math.max(0, Math.floor(elapsedMs() / 1000));
    return Number(clock.elapsed_seconds) || 0;
  }

  const SYNC_LABELS = {
    synced: 'Live · Synced',
    reconnecting: 'Reconnecting…',
    offline: 'Not Synced',
  };

  function readSyncState() {
    // The badge live_game_v2 maintains stays in the DOM as the state carrier
    // even though Dugout Mode no longer shows it. Order matters: "NOT SYNCED"
    // also contains "SYNCED", so the failure states are tested first.
    const text = $('live-sync-status-v2')?.textContent || '';

    if (/reconnecting/i.test(text)) return 'reconnecting';
    if (/not\s*synced/i.test(text)) return 'offline';
    if (/synced/i.test(text)) return 'synced';

    // No badge yet: live_game_v2 has not reported a state, so claiming a
    // healthy connection would be a guess.
    return 'reconnecting';
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
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">CoachBoard Menu</h5><div class="small text-muted">Leave this screen without ending the game.</div></div><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body"><div class="cb-nav-safe"><strong>The game stays live.</strong> Leaving this screen does not end the game, change the inning, or change the clock. If the clock is paused, it stays paused until you resume it.</div><div class="cb-app-grid"><a class="cb-app-link cb-return-game" href="/game/${gameId}"><i class="bi bi-diamond-fill"></i><span>Back to Live Game</span></a><button type="button" class="cb-app-link" data-cb-player-availability><i class="bi bi-person-check"></i><span>Player availability</span></button>${gameChanger ? '' : '<a class="cb-app-link" href="/#overview"><i class="bi bi-house-door"></i><span>Home</span></a>'}<a class="cb-app-link" href="/game-day"><i class="bi bi-calendar3"></i><span>Game Day</span></a>${gameChanger ? '' : '<a class="cb-app-link" href="/#roster"><i class="bi bi-people"></i><span>Roster</span></a><a class="cb-app-link" href="/#practice_plan"><i class="bi bi-clipboard-check"></i><span>Practice</span></a><a class="cb-app-link" href="/pitching"><i class="bi bi-bullseye"></i><span>Pitching</span></a><a class="cb-app-link" href="/#more"><i class="bi bi-three-dots"></i><span>More</span></a>'}</div></div></div></div>`;
    document.body.appendChild(modal);
    // Who is here during the game: one sheet (live_game_bench_report.js).
    // It opens once the Menu has closed, and returns focus to Menu.
    modal.querySelector('[data-cb-player-availability]')?.addEventListener('click', () => {
      modal.addEventListener('hidden.bs.modal', () => {
        window.CBPlayerAvailability?.open($('cbDugoutHeader')?.querySelector('[data-cb-menu]') || null);
      }, {once: true});
      bootstrap.Modal.getOrCreateInstance(modal).hide();
    });
    return modal;
  }

  function openAppMenu() {
    bootstrap.Modal.getOrCreateInstance(ensureAppMenu()).show();
  }
  window.openCoachBoardLiveMenu = openAppMenu;
  // End Inning's "Fix" and the "empty now" warning open the fill picker for
  // a position on the field directly.
  window.CBQuickField = {
    fillOpen: position => openOpenPositionModal(position),
  };

  // #liveUndoBtn is a template control (templates/_rotation_editor.html) that
  // live_game_coach_ui drops into #coach-action-slot and live_game_command_center
  // then moves into .coach-live-head. Dugout Mode hides that head, so the only
  // way it stayed reachable was gameday_pitching_steppers.js un-hiding the row
  // for it. Presenting it in this header instead removes that row entirely.
  // The button itself is never cloned or rebuilt -- it is the same element, so
  // the delegated /undo handler in live_game_v2 keeps working and
  // live_game_board_prep_v2's disabled toggling still lands on it.
  //
  // One button, two Undos: on the 2nd Inning tab live_game_board_prep_v2
  // takes the tap for the next inning's defense (data-cb-undo-scope="next");
  // everywhere else it is the live game's /undo. The label says which.
  const UNDO_LABELS = {
    live: {scope: 'live change', label: 'Undo live change', title: 'Undo the last live-game change'},
    // "next inning" fits beside LIVE · SYNCED at 320px; the name is in full.
    next: {scope: 'next inning', label: 'Undo next-inning edit', title: "Undo your last change to the next inning's defense"},
  };
  const undoMarkup = scope =>
    '<i class="bi bi-arrow-90deg-left" aria-hidden="true"></i>'
    + `<span class="cb-dh-undo-text">Undo<small class="cb-dh-undo-scope">${scope}</small></span>`;
  let undoOrigin = null;

  function adoptUndo(header) {
    const undo = $('liveUndoBtn');
    const slot = header.querySelector('.cb-dh-undo-slot');
    if (!undo || !slot) return;

    if (!undoOrigin) {
      undoOrigin = {
        className: undo.className,
        innerHTML: undo.innerHTML,
        title: undo.title,
        label: undo.getAttribute('aria-label'),
      };
    }

    const labels = UNDO_LABELS[undo.dataset.cbUndoScope === 'next' ? 'next' : 'live'];
    const markup = undoMarkup(labels.scope);
    if (undo.className !== 'btn cb-dh-undo') undo.className = 'btn cb-dh-undo';
    if (undo.innerHTML !== markup) undo.innerHTML = markup;
    if (undo.title !== labels.title) undo.title = labels.title;
    if (undo.getAttribute('aria-label') !== labels.label) {
      undo.setAttribute('aria-label', labels.label);
    }
    if (undo.parentElement !== slot) slot.appendChild(undo);
  }

  function releaseUndo() {
    // The header is about to be removed. Undo is a template element, so it has
    // to go back to the page rather than be destroyed with its host.
    const undo = $('liveUndoBtn');
    const header = $('cbDugoutHeader');
    if (!undo || !header || !header.contains(undo)) return;

    if (undoOrigin) {
      undo.className = undoOrigin.className;
      undo.innerHTML = undoOrigin.innerHTML;
      undo.title = undoOrigin.title;
      if (undoOrigin.label === null) undo.removeAttribute('aria-label');
      else undo.setAttribute('aria-label', undoOrigin.label);
    }

    const home =
      document.querySelector('#live-game-overlay #coach-action-slot')
      || document.querySelector('#live-game-overlay .coach-live-shell')
      || $('live-game-overlay');
    home?.appendChild(undo);
  }

  function renderHeader(shell) {
    let header = $('cbDugoutHeader');
    if (!header) {
      header = document.createElement('div');
      header.id = 'cbDugoutHeader';
      header.innerHTML = '<div class="cb-dh-main"><div class="cb-dh-live"><span class="cb-dh-dot"></span><span data-cb-live-label>Live Game</span></div><div class="cb-dh-inning"><small>Inning</small><strong data-cb-inning>1</strong></div><div class="cb-dh-clock"><small data-cb-clock-label>Elapsed</small><div class="cb-dh-time" data-cb-clock-time>—</div></div><div class="cb-dh-pitcher"><small>Pitcher</small><div class="cb-dh-name" data-cb-pitcher>None</div></div><span class="cb-dh-undo-slot"></span><button class="btn btn-outline-light btn-sm cb-dh-btn" data-cb-clock><i class="bi bi-clock me-1"></i>Clock</button><button class="btn btn-outline-light btn-sm cb-dh-btn" data-cb-menu aria-label="Open CoachBoard menu without ending the game"><i class="bi bi-grid me-1"></i>Menu</button></div><div class="cb-dh-title" data-cb-title></div>';
      shell.prepend(header);
      header.addEventListener('click', event => {
        if (event.target.closest('[data-cb-clock]')) document.querySelector('#cbLiveGameClock .cb-clock-config')?.click();
        if (event.target.closest('[data-cb-menu]')) openAppMenu();
      });
    }

    const info = clockInfo();
    const inning = state?.current_inning || clock?.current_inning || '1';
    const pitcher = state?.current_pitcher || state?.current_alignment?.P || 'None';
    // live_game_v2 owns the authoritative sync state and writes it into
    // #live-sync-status-v2; this header is the only thing that shows it in
    // Dugout Mode. Pause is deliberately NOT folded into this label -- it is
    // already carried by the clock ("Paused · Elapsed") and the header
    // border, and letting it replace the label would hide a dead connection
    // behind the word "Paused".
    const syncState = readSyncState();
    header.dataset.cbSync = syncState;
    setText(
      header.querySelector('[data-cb-live-label]'),
      SYNC_LABELS[syncState]
    );
    setText(header.querySelector('[data-cb-inning]'), String(inning));
    setText(header.querySelector('[data-cb-clock-label]'), info.label);
    const time = header.querySelector('[data-cb-clock-time]');
    setText(time, info.value);
    time?.classList.toggle('warn', info.tone === 'warn');
    time?.classList.toggle('danger', info.tone === 'danger');
    setText(header.querySelector('[data-cb-pitcher]'), displayName(pitcher));
    setText(header.querySelector('[data-cb-title]'), title());
    adoptUndo(header);
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
    const open = name === 'Open';
    const number = numberMap().get(name);
    const label = open && !pitcher ? 'Open' : name;
    const fullLabel = open ? `${pos} open` : `${number ? `#${number} ` : ''}${name} at ${pos}`;

    return `<button type="button"
                    class="cb-qd-spot ${pitcher ? 'pitcher' : ''} ${open ? 'cb-authoritative-open' : ''}"
                    style="left:${left}%;top:${top}%"
                    data-cb-move-player="${esc(name)}"
                    data-cb-position="${esc(pos)}"
                    aria-label="${esc(fullLabel)}">
              <span class="cb-qd-pos">${esc(pos)}${number && !open ? ` <span class="cb-qd-num">#${esc(number)}</span>` : ''}</span>
              <span class="cb-qd-name">${esc(label)}</span>
            </button>`;
  }

  function saveStateMarkup() {
    const icon = saveMode === 'saving' ? 'bi-arrow-repeat' : saveMode === 'error' ? 'bi-exclamation-triangle' : 'bi-check-circle-fill';
    const retry = saveMode === 'error' && lastFailedMove ? ' data-cb-retry-move role="button" tabindex="0"' : '';
    return `<div class="cb-save-state ${saveMode}"${retry}><i class="bi ${icon}"></i><span>${esc(saveMessage)}</span></div>`;
  }

  // This markup is the only owner of the Quick Field heading, help and tip
  // text. Other live scripts used to relabel them after each redraw, so the
  // heading flashed between two wordings.
  function quickDefenseMarkup() {
    const bench = benchPlayers();
    const benchMarkup = bench.length
      ? bench.map(player => {
          const number = String(player.number ?? '').trim();
          return `<button type="button" class="cb-qd-bench-player ${player.benchStreak >= 2 ? 'priority' : ''}" data-cb-move-player="${esc(player.name)}"><span>${esc(number ? `#${number} ${player.name}` : player.name)}</span><span class="cb-bench-note">${esc(benchNote(player.benchStreak))}</span></button>`;
        }).join('')
      : '<span class="small text-muted">No players are on the bench.</span>';

    return `<div class="cb-qd-head"><div><div class="cb-qd-kicker">Live Defense</div><div class="cb-qd-title">Inning ${esc(state?.current_inning || '')} · live</div><div class="cb-qd-help">Tap a player to move him. Occupied spots swap automatically. Bench leaves the old spot open.</div></div>${saveStateMarkup()}</div><div class="cb-qd-body"><div class="cb-qd-field"><svg class="cb-qd-field-art" viewBox="0 0 100 88" preserveAspectRatio="none" aria-hidden="true"><path d="M7 57 Q9 13 50 6 Q91 13 93 57" fill="none" stroke="rgba(245,245,220,.38)" stroke-width="1.2"/><path d="M50 84 L8 38 M50 84 L92 38" fill="none" stroke="rgba(255,255,255,.88)" stroke-width=".7"/><polygon points="50,75 27,54 50,32 73,54" fill="#cfa56c" opacity=".95"/><polygon points="50,68 34,54 50,40 66,54" fill="#438f58"/><circle cx="50" cy="61" r="4.8" fill="#cfa56c"/><circle cx="50" cy="81" r="6.2" fill="#cfa56c"/><rect x="49" y="31" width="2" height="2" fill="#fff" transform="rotate(45 50 32)"/><rect x="72" y="53" width="2" height="2" fill="#fff" transform="rotate(45 73 54)"/><rect x="26" y="53" width="2" height="2" fill="#fff" transform="rotate(45 27 54)"/><path d="M48.8 81.5 L50 80.4 L51.2 81.5 L50.8 83 L49.2 83 Z" fill="#fff"/></svg>${positionSpots().map(([pos, left, top]) => fieldSpot(pos, left, top)).join('')}</div><div class="cb-qd-bench-wrap"><div class="cb-qd-bench-head"><strong>Bench now · ${bench.length}</strong><span>${bench.length ? 'Players sitting longest are shown first' : 'Everyone is in the field'}</span></div><div class="cb-qd-bench">${benchMarkup}</div></div><div class="cb-qd-actions"><div class="cb-qd-tip">Pitcher changes stay in Change Pitcher. Use Undo if the move was not what you wanted.</div></div></div>`;
  }

  function quickDefenseStateSignature() {
    return JSON.stringify({
      inning: state?.current_inning || null,
      alignment: currentAlignment(),
      bench: benchPlayers().map(player => [player.id, player.name, player.number, player.benchStreak]),
      outfielderCount: state?.outfielder_count || 3,
      saveMode,
      saveMessage,
      retry: lastFailedMove ? [lastFailedMove.playerId, lastFailedMove.destination] : false,
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
        if (event.target.closest('[data-cb-retry-move]') && retryLastFailedSave()) return;
        const player = event.target.closest('[data-cb-move-player]');
        if (!player) return;

        const name = player.dataset.cbMovePlayer;
        const pos = player.dataset.cbPosition;

        // One move at a time, tapped or dragged: a Move or Fill sheet
        // opened while a move is saving would be decided against the field
        // that save is about to replace. (P still goes to Change Pitcher.)
        const busy = moveBusy && pos !== 'P';

        if (name === 'Open') {
          if (!busy) openOpenPositionModal(pos);
          return;
        }

        if (player.disabled) return;

        if (pos === 'P') {
          $('liveChangePitcherBtn')?.click();
          return;
        }

        if (!busy) openMoveModal(name);
      });
      card.addEventListener('keydown', event => {
        if ((event.key === 'Enter' || event.key === ' ') && event.target.closest('[data-cb-retry-move]')) {
          event.preventDefault();
          retryLastFailedSave();
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
    modal.innerHTML = '<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Move Player</h5><div class="small text-muted" data-cb-move-hint>Tap the new position. Occupied positions swap automatically.</div></div><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body"></div></div></div>';
    document.body.appendChild(modal);
    return modal;
  }

  // The Move Player and Fill sheets share one modal; each states its own rule.
  function setMoveModalHint(text) {
    const hint = ensureMoveModal().querySelector('[data-cb-move-hint]');
    if (hint) hint.textContent = text;
  }

  function openOpenPositionModal(position) {
    const pos = String(position || '').toUpperCase();
    if (!pos) return;

    if (pos === 'P') {
      $('liveChangePitcherBtn')?.click();
      return;
    }

    const modal = ensureMoveModal();
    const title = modal.querySelector('.modal-title');
    const body = modal.querySelector('.modal-body');
    const context = captureMoveContext();
    const alignment = context.alignment;
    openMoveContext = context;

    modal.addEventListener('hidden.bs.modal', () => {
      if (openMoveContext === context) openMoveContext = null;
    }, {once: true});

    if (title) {
      title.textContent = `Fill ${pos}`;
    }
    // Another spot open too: name it, so it's clear which one this fills.
    const others = positions().filter(other => other !== pos && !alignment?.[other]);
    setMoveModalHint(
      'Only the player you choose moves.' +
      (others.length ? ` Also open: ${others.join(', ')}.` : '')
    );

    /*
     * Anyone can fill an open position: a bench player, or a player at
     * another position -- the same move drag-and-drop makes (both commit
     * through commitMove): the player
     * moves here and their old position is left open. Nothing else moves;
     * the coach fills that spot next if they want to. The pitcher is
     * special: choosing them goes to Change Pitcher, which settles who
     * pitches (with its eligibility checks) before anyone leaves P.
     */
    const labelFor = player => {
      const number = String(player?.number ?? '').trim();
      return number ? `#${number} ${player.name}` : player.name;
    };
    const candidates = [
      ...benchPlayers().map(player => ({player, from: 'Bench'})),
      ...positions()
        .filter(spot => spot !== pos && alignment[spot])
        .map(spot => ({player: playerForName(alignment[spot]), from: spot}))
        .filter(item => item.player),
    ];

    if (!candidates.length) {
      body.innerHTML = `
        <div class="cb-move-current">
          <strong>${esc(pos)} is Open.</strong><br>
          No player is available to fill it.
        </div>
      `;

      bootstrap.Modal
        .getOrCreateInstance(modal)
        .show();

      return;
    }

    const detail = from => {
      if (from === 'P') return `P → ${pos} · choose a new pitcher first`;
      if (from === 'Bench') return `Bench → ${pos}`;
      return `${from} → ${pos} · ${from} left open`;
    };

    body.innerHTML = `
      <div class="cb-move-current">
        <strong>${esc(pos)} is Open.</strong><br>
        Choose a player to put at ${esc(pos)}.
      </div>

      <div class="cb-destination-grid">
        ${candidates.map(({player, from}) => `
          <button
            type="button"
            class="btn ${from === 'Bench' ? 'btn-outline-primary' : 'btn-outline-secondary'} cb-destination"
            data-cb-fill-open-player="${player.id}"
            data-cb-fill-from="${esc(from)}"
          >
            <span>${esc(labelFor(player))}</span>
            <small>${esc(detail(from))}</small>
          </button>
        `).join('')}
      </div>
    `;

    body.querySelectorAll(
      '[data-cb-fill-open-player]'
    ).forEach(button => {
      button.addEventListener(
        'click',
        () => {
          const playerId = Number(
            button.dataset.cbFillOpenPlayer
          );

          const choice = candidates.find(
            candidate =>
              Number(candidate.player.id) === playerId
          );

          if (!choice) return;

          // Choosing the pitcher never moves P here: commitMove sends it to
          // Change Pitcher, which asks who pitches, then where the pitcher
          // goes (this open spot is offered there as a one-tap choice).
          commitMove(choice.player.name, pos, context);
        }
      );
    });

    bootstrap.Modal
      .getOrCreateInstance(modal)
      .show();
  }

  function openMoveModal(name) {
    const player = playerForName(name);
    if (!player) return;
    const context = captureMoveContext();
    const alignment = context.alignment;
    const source = Object.entries(alignment).find(([, playerName]) => playerName === name)?.[0] || 'BENCH';
    if (source === 'P') {
      $('liveChangePitcherBtn')?.click();
      return;
    }
    const modal = ensureMoveModal();
    const title = modal.querySelector('.modal-title');
    const body = modal.querySelector('.modal-body');
    openMoveContext = context;

    modal.addEventListener('hidden.bs.modal', () => {
      if (openMoveContext === context) openMoveContext = null;
    }, {once: true});

    if (title) {
      title.textContent = 'Move Player';
    }
    setMoveModalHint("Tap the new position. Occupied positions swap automatically.");

    const destinations = positions().filter(pos => pos !== 'P' && pos !== source);
    const sourceText = source === 'BENCH' ? `${name} is currently on the bench.` : `${name} is currently playing ${source}.`;
    const benchDestination = source === 'BENCH'
      ? ''
      : `<button type="button" class="btn btn-outline-secondary cb-destination" data-cb-bench-current><span>Bench</span><small>Leave ${esc(source)} open</small></button>`;
    body.innerHTML = `<div class="cb-move-current"><strong>${esc(sourceText)}</strong><br>${source === 'BENCH' ? 'Choose a field position. If someone is there, that player goes to the bench.' : 'Choose another position, or Bench.'}</div><div class="cb-destination-grid">${benchDestination}${destinations.map(pos => {
      const occupant = alignment[pos] || '';
      return `<button type="button" class="btn btn-outline-primary cb-destination" data-cb-destination="${esc(pos)}"><span>${esc(pos)}</span><small>${occupant ? `Currently ${esc(occupant)}` : 'Open position'}</small></button>`;
    }).join('')}</div>`;

    body.querySelectorAll('[data-cb-destination]').forEach(button => {
      button.addEventListener(
        'click',
        () => commitMove(
          player.name,
          button.dataset.cbDestination,
          context
        )
      );
    });

    // Bench is an obvious one-step move: the old position stays open.
    body.querySelector('[data-cb-bench-current]')?.addEventListener('click', () => {
      commitMove(player.name, 'BENCH', context);
    });
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  const STALE_MOVE_MESSAGE =
    'Defense changed on another device. Check the field and try the move again.';

  /*
   * The one writer of a normal live defensive move.
   *
   * Tap (the Move and Fill sheets), drag-and-drop
   * (live_game_unified_field_entry.js, through CBQuickFieldMoves.commit)
   * and Retry all commit here. The gesture only says who goes where; this
   * decides the resulting field, checks it against the field the coach
   * acted on (`context`, captured when the sheet opened or the drag
   * began), saves it, and reports a refusal or a failure once, on the
   * Quick Field status. A later live update never changes who gets
   * swapped or benched: a move decided on an older field is refused.
   *
   * One move at a time: moveBusy is held from this decision to the
   * server's answer, and a move made meanwhile is dropped.
   */
  function commitMove(
    name,
    destination,
    context = captureMoveContext()
  ) {
    if (moveBusy) return;
    const player = playerForName(name);
    const target = String(destination || '').toUpperCase();
    if (!player || !target) return;

    const alignment = context.alignment || {};
    const source = Object.entries(alignment)
      .find(([, assigned]) => assigned === name)?.[0] || 'BENCH';

    // P is never a generic move: Change Pitcher settles who pitches.
    if (source === 'P' || target === 'P') {
      bootstrap.Modal.getOrCreateInstance(ensureMoveModal()).hide();
      $('liveChangePitcherBtn')?.click();
      return;
    }

    // Dropped where the player already is: nothing to do.
    if (source === target) return;

    // Resolve the obvious move immediately:
    // open spot = move, occupied spot = swap, Bench = leave the old spot open.
    moveBusy = true;
    moveSettled = new Promise(settle => closeMoveSheetThen(() => saveMove(
      player.id,
      target,
      name,
      context
    ).then(settle)));
  }

  /*
   * A decision is finished: close the move sheet, then save. The sheet is
   * never left open waiting on the network, so nothing (a server question,
   * another sheet) can stack on it, and the save's outcome is reported once,
   * on the Quick Field status -- Retry for a lost connection, the reason for
   * a refused change.
   */
  function closeMoveSheetThen(save) {
    // The decision is made: say so now, not after the sheet finishes closing.
    saveMode = 'saving';
    saveMessage = 'Saving…';
    quickDefenseSignature = '';
    const shell = document.querySelector('#live-game-overlay .coach-live-shell');
    if (shell) renderQuickDefense(shell);

    const modal = $('cbQuickMoveModal');
    const open = modal && (modal.classList.contains('show') || modal.style.display === 'block');
    if (!open) {
      save();
      return;
    }
    let started = false;
    const start = () => {
      if (started) return;
      started = true;
      save();
    };
    modal.addEventListener('hidden.bs.modal', start, {once: true});
    bootstrap.Modal.getOrCreateInstance(modal).hide();
    // Bootstrap ignores hide() mid-transition; never let that hold a save.
    window.setTimeout(() => {
      if (started) return;
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      start();
    }, 600);
  }

  // Retry is the same decision on the same field, through the same writer:
  // if the field has changed since, it is refused rather than reapplied.
  function retryLastFailedSave() {
    if (!lastFailedMove) return false;
    const failed = lastFailedMove;

    if (!moveContextIsCurrent(failed.context)) {
      lastFailedMove = null;
      showStaleMove();
      return true;
    }

    commitMove(failed.name, failed.destination, failed.context);
    return true;
  }

  // One place a save's failure is shown. A lost connection can be retried
  // exactly as decided; a refused change (the field changed on another
  // device, a player no longer available) says why and is not retried.
  function reportSaveFailure(error, retry) {
    lastFailureKind = failureKind(error);
    saveMode = 'error';
    if (lastFailureKind === 'network') {
      saveMessage = 'Not saved — Retry';
      retry();
    } else {
      saveMessage = `Not saved — ${error.message}`;
    }
    quickDefenseSignature = '';
    const shell = document.querySelector('#live-game-overlay .coach-live-shell');
    if (shell) renderQuickDefense(shell);
  }

  // Drag-and-drop commits through the same writer. `context` is what a
  // drag captures when it starts -- the field the coach picked a player up
  // from -- and `busy` holds a drag back while a move is saving.
  //
  // whenIdle: the move now saving, settled -- true once it is saved, false
  // if it was refused or failed (its status already says why); true at
  // once when no move is saving. End Inning waits on it
  // (live_game_contract.js), so it never checks or advances a field a
  // move is still changing.
  window.CBQuickFieldMoves = Object.freeze({
    context: () => captureMoveContext(),
    commit: commitMove,
    busy: () => moveBusy,
    whenIdle: () => (moveBusy ? moveSettled : Promise.resolve(true)),
  });

  async function applyQuickDefenseSaveResponse(data) {
    if (data?.delta) {
      // Use the exact same local contract as drag-and-drop and pitcher
      // changes. This updates this coach immediately while Socket.IO
      // sends the same authoritative delta to the other coaches.
      document.dispatchEvent(
        new CustomEvent('coachboard:live-delta', {
          detail: data.delta,
        })
      );
      return;
    }

    // Compatibility fallback only. Quick Field should normally receive
    // a delta from /defense-edit.
    if (data?.state) {
      state = data.state;
      quickDefenseSignature = '';
      queue();
      return;
    }

    await getState();
  }

  // commitMove's save. It holds moveBusy (set by commitMove) and always
  // releases it, whether the move is saved, refused or fails. Resolves
  // true only when the move was saved.
  async function saveMove(
    playerId,
    destination,
    name,
    context
  ) {
    try {
      if (!moveContextIsCurrent(context)) {
        showStaleMove();
        return false;
      }

      saveMode = 'saving';
      saveMessage = 'Saving…';
      lastFailedMove = null;
      quickDefenseSignature = '';

      const shell = document.querySelector('#live-game-overlay .coach-live-shell');
      if (shell) renderQuickDefense(shell);

      const player = (state?.roster || []).find(
        candidate => Number(candidate.id) === Number(playerId)
      );

      if (!player) {
        throw new Error(
          'That player is no longer available. Refresh the live field and try again.'
        );
      }

      // Build the result from the exact alignment the coach acted on.
      const alignment = {...(context.alignment || {})};
      const source = Object.entries(alignment)
        .find(([, assigned]) => assigned === player.name)?.[0] || 'BENCH';
      const target = String(destination || '').toUpperCase();

      if (!target || source === 'P' || target === 'P') {
        throw new Error(
          'Use Change Pitcher for changes involving P.'
        );
      }

      if (source === target) {
        throw new Error(
          source === 'BENCH'
            ? `${player.name} is already on the bench.`
            : `${player.name} is already playing ${target}.`
        );
      }

      const occupant =
        target === 'BENCH'
          ? ''
          : (alignment[target] || '');

      if (source !== 'BENCH') {
        delete alignment[source];
      }

      if (target !== 'BENCH') {
        alignment[target] = player.name;

        // Field-to-field occupied move = swap. Bench-to-field occupied move
        // = the fielder being replaced goes to the bench.
        if (
          occupant &&
          occupant !== player.name &&
          source !== 'BENCH'
        ) {
          alignment[source] = occupant;
        }
      }

      const response = await fetch(`/api/live-game/${gameId}/defense-edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          alignment,
          base_sequence: context.baseSequence,
        }),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok || data.status === 'error') {
        if (
          data.code === 'stale_live_state' ||
          data.code === 'missing_live_state_version'
        ) {
          await getState();
        }

        throw new Error(
          data.code === 'stale_live_state'
            ? STALE_MOVE_MESSAGE
            : data.message ||
              `Unable to save defense (${response.status}).`
        );
      }

      await applyQuickDefenseSaveResponse(data);

      lastFailureKind = null;
      reconnectMessageUntil = 0;
      saveMode = 'saved';
      saveMessage = 'Saved ✓';
      quickDefenseSignature = '';
      queue();
      return true;
    } catch (error) {
      reportSaveFailure(error, () => {
        lastFailedMove = {
          playerId,
          destination,
          name,
          context,
        };
      });
      return false;
    } finally {
      moveBusy = false;
    }
  }

  function applySharedLiveState(event) {
    const detail = event?.detail || {};

    if (Number(detail.game_id) !== gameId) {
      return;
    }

    const next = detail.state;

    if (
      !next ||
      Number(next?.game?.id) !== gameId
    ) {
      return;
    }

    // Full server state always wins after reconnect, wake, or an
    // explicit authoritative refresh.
    state = next;
    quickDefenseSignature = '';
    invalidateOpenMoveIfStale();

    const source = String(
      detail.source || ''
    );

    if (
      source === 'socket-reconnect' ||
      source === 'online' ||
      source === 'visibility'
    ) {
      clearRecoveredNetworkFailure();
    }

    /*
     * Undo is authoritative.
     *
     * The server has already reverted the event and returned the
     * complete replacement state. Paint Quick Field immediately
     * from that state instead of waiting for requestAnimationFrame.
     */
    if (source === 'undo') {
      const shell = document.querySelector(
        '#live-game-overlay .coach-live-shell'
      );

      const card = shell
        ? ensureQuickDefense(shell)
        : null;

      if (card && state?.game?.is_live) {
        quickDefenseSignature =
          quickDefenseStateSignature();

        card.innerHTML =
          quickDefenseMarkup();
      }
    }

    queue();
  }

  function applySharedLiveDelta(event) {
    const delta = event?.detail;
    if (!delta || Number(delta.game_id) !== gameId) return;

    // If this controller has not loaded its initial state yet, let the normal
    // state loader establish the full roster/team context.
    if (!state) {
      getState();
      return;
    }

    /*
     * An authoritative Undo leaves the reverted rotation event in
     * rotation_events with reverted=true.
     *
     * A delayed Socket.IO/local delta for that SAME old event must
     * never resurrect its pre-Undo alignment on this coach's screen.
     *
     * Prefer event id when available. Sequence is only a fallback for
     * older delta shapes that do not include an event id.
     */
    const incomingEventId =
      Number(delta.event?.id) || 0;

    const incomingSequence =
      Number(delta.event?.sequence) ||
      Number(delta.sequence) ||
      0;

    const matchesRevertedEvent =
      Array.isArray(state.rotation_events) &&
      state.rotation_events.some(existing => {
        if (!existing?.reverted) return false;

        const existingId =
          Number(existing?.id) || 0;

        const existingSequence =
          Number(existing?.sequence) || 0;

        if (
          incomingEventId &&
          existingId === incomingEventId
        ) {
          return true;
        }

        if (
          !incomingEventId &&
          incomingSequence &&
          existingSequence === incomingSequence
        ) {
          return true;
        }

        return false;
      });

    if (matchesRevertedEvent) {
      return;
    }

    const inning = String(
      delta.current_inning ||
      state.current_inning ||
      state.game?.live_current_inning ||
      '1'
    );

    state.game = state.game || {id: gameId};
    state.game.is_live = true;
    state.game.live_current_inning = inning;
    state.current_inning = inning;

    if (delta.current_alignment) {
      state.current_alignment = {...delta.current_alignment};
    }

    state.current_pitcher =
      delta.current_pitcher ||
      state.current_alignment?.P ||
      state.current_pitcher ||
      null;

    state.actual_rotation = state.actual_rotation || {};
    state.actual_rotation[inning] = {
      ...(state.current_alignment || {}),
    };

    if (Array.isArray(delta.bench)) {
      state.bench = delta.bench;
    }

    if (delta.event) {
      state.rotation_events = Array.isArray(state.rotation_events)
        ? state.rotation_events
        : [];

      const incomingId = Number(delta.event.id) || 0;
      const incomingSequence =
        Number(delta.event.sequence) ||
        Number(delta.sequence) ||
        0;

      const index = state.rotation_events.findIndex(existing => {
        const existingId = Number(existing?.id) || 0;
        const existingSequence = Number(existing?.sequence) || 0;

        if (incomingId && existingId === incomingId) return true;
        if (
          incomingSequence &&
          existingSequence === incomingSequence
        ) return true;

        return false;
      });

      if (index >= 0) {
        state.rotation_events[index] = delta.event;
      } else {
        state.rotation_events.push(delta.event);
      }
    }

    // Force Quick Field to redraw from the newest alignment. Any open move
    // sheet was decided against the prior field/version, so close it rather
    // than silently changing who a visible destination would move.
    invalidateOpenMoveIfStale();
    quickDefenseSignature = '';
    queue();
  }

  function arrange(shell) {
    // Canonical live action controls retain one DOM owner.
    // Dugout does not rewrite or reparent them on every patch.
    void shell;
  }

  function focusBoard() {
    const board = $('live-board-prep-v3');
    if (!board) return;
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
      releaseUndo();
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

      // A move still saving owns the status: a read that lands meanwhile
      // must not call it Saved (or Reconnected) before its answer.
      if (moveBusy) {
        // the move's own answer sets the status
      } else if (
        lastFailureKind === 'network' &&
        navigator.onLine
      ) {
        clearRecoveredNetworkFailure();
      } else if (
        saveMode !== 'error' &&
        Date.now() >= reconnectMessageUntil
      ) {
        saveMode = 'saved';
        saveMessage = 'Saved ✓';
      }

      quickDefenseSignature = '';
      queue();
    } catch (_) {
    } finally {
      stateBusy = false;
    }
  }

  async function getClock() {
    if (clockBusy) return;
    clockBusy = true;
    try {
      const sentAt = Date.now();
      const response = await fetch(`/api/live-game/${gameId}/clock`, { cache: 'no-store' });
      if (!response.ok) return;
      clock = (await response.json())?.clock || null;
      clockAt = Date.now();
      correctClockOffset(clock, sentAt, clockAt);
      queue();
    } catch (_) {
    } finally {
      clockBusy = false;
    }
  }

  function start() {
    styles();

    // live_game_feedback_pass.js publishes Socket.IO live deltas here, and
    // a saved move publishes its own response here as well.
    document.addEventListener(
      'coachboard:live-state',
      applySharedLiveState
    );

    document.addEventListener(
      'coachboard:live-delta',
      applySharedLiveDelta
    );

    // The tab changed which Undo the header button is.
    document.addEventListener('coachboard:undo-scope', () => {
      const header = $('cbDugoutHeader');
      if (header) adoptUndo(header);
    });

    const liveOverlay = $('live-game-overlay');
    if (liveOverlay) {
      // Watch only the live-game surface. Observing the entire document — including
      // clock text, menus, toasts, and unrelated Bootstrap changes — caused needless
      // redraw scheduling during every live inning.
      new MutationObserver(queue).observe(liveOverlay, {
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
    // Once a second -- just after the clock's own second turns while it
    // runs, so the display never shows a second twice or skips one.
    const tick = () => {
      if (document.body.classList.contains('cb-dugout')) queue();
      const delay = clockRunning() ? 1000 - (((elapsedMs() % 1000) + 1000) % 1000) + 20 : 1000;
      window.setTimeout(tick, delay);
    };
    window.setTimeout(tick, 1000);
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