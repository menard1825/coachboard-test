(() => {
  'use strict';
  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match || typeof io !== 'function') return;
  const gameId = Number(match[1]);
  const ID = 'coach-live-sync-status';
  const RESPONSIVE_STYLE_ID = 'coach-live-responsive-layout';
  let lastUpdate = null;

  function installResponsiveStyles() {
    if (document.getElementById(RESPONSIVE_STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = RESPONSIVE_STYLE_ID;
    style.textContent = `
      /* Live Game is responsive by viewport shape, not by device model. */
      html body.cb-dugout #cbCoachBoardNavBtn {
        display: none !important;
      }

      html body.cb-dugout #live-game-overlay {
        width: 100% !important;
        max-width: none !important;
      }

      /* Phones and narrow foldables: keep everything single-column and touchable. */
      @media (max-width: 599.98px) {
        html body.cb-dugout .coach-live-shell {
          width: 100% !important;
          max-width: none !important;
          padding-left: 8px !important;
          padding-right: 8px !important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-field {
          width: 100% !important;
          max-width: 560px !important;
          min-height: 0 !important;
          margin-left: auto !important;
          margin-right: auto !important;
        }
      }

      /* Medium-width phones, foldables and small tablets need a compact header. */
      @media (min-width: 576px) and (max-width: 899.98px) {
        html body.cb-dugout #cbDugoutHeader .cb-dh-live {
          display: none !important;
        }
        html body.cb-dugout #cbDugoutHeader .cb-dh-main {
          grid-template-columns: auto minmax(74px,.8fr) minmax(92px,1.15fr) auto auto !important;
          gap: 6px !important;
        }
        html body.cb-dugout #cbDugoutHeader .cb-dh-pitcher {
          text-align: left !important;
        }
        html body.cb-dugout #cbDugoutHeader .cb-dh-name {
          max-width: 180px !important;
          font-size: .78rem !important;
        }
        html body.cb-dugout #cbDugoutHeader .cb-dh-btn {
          padding: 6px 8px !important;
          font-size: .7rem !important;
        }
        html body.cb-dugout #cbDugoutHeader .cb-dh-title {
          display: none !important;
        }
      }

      /* Portrait tablets: prevent a giant full-width diamond. */
      @media (min-width: 600px) and (orientation: portrait) {
        html body.cb-dugout .coach-live-shell {
          width: 100% !important;
          max-width: 900px !important;
          padding-left: 12px !important;
          padding-right: 12px !important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-field {
          width: min(100%, 680px) !important;
          min-height: 0 !important;
          margin: 0 auto !important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-bench-wrap,
        html body.cb-dugout #cbQuickDefense .cb-qd-actions {
          width: min(100%, 680px) !important;
          margin-left: auto !important;
          margin-right: auto !important;
        }
      }

      /* Landscape tablets and desktop-sized viewports: use the width instead of
         stretching the field. This covers iPad mini/Air/Pro, Android tablets,
         Chromebooks and desktop browsers without device-specific rules. */
      @media (min-width: 760px) and (min-height: 600px) and (orientation: landscape) {
        html body.cb-dugout .coach-live-shell {
          width: 100% !important;
          max-width: 1160px !important;
          padding: 0 14px 24px !important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-body {
          display: grid !important;
          grid-template-columns: minmax(0,1.55fr) minmax(230px,.75fr) !important;
          grid-template-areas: 'field bench' 'field tools' !important;
          gap: 12px 14px !important;
          align-items: start !important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-field {
          grid-area: field !important;
          width: min(100%, 690px) !important;
          min-height: 0 !important;
          aspect-ratio: 1.28 / 1 !important;
          margin: 0 auto !important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-bench-wrap {
          grid-area: bench !important;
          width: auto !important;
          margin: 0 !important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-actions {
          grid-area: tools !important;
          width: auto !important;
          display: flex !important;
          flex-direction: column !important;
          align-items: stretch !important;
          gap: 10px !important;
          margin: 0 !important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-actions .btn {
          width: 100% !important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-tip {
          font-size: .72rem !important;
          line-height: 1.35 !important;
        }
        html body.cb-dugout .coach-actions {
          grid-template-columns: repeat(4,minmax(0,1fr)) !important;
        }
      }

      /* Phone landscape is short even when its width looks tablet-sized. */
      @media (orientation: landscape) and (max-height: 599.98px) {
        html body.cb-dugout #cbDugoutHeader .cb-dh-live,
        html body.cb-dugout #cbDugoutHeader .cb-dh-title {
          display: none !important;
        }
        html body.cb-dugout #cbDugoutHeader {
          padding-top: 6px !important;
          padding-bottom: 6px !important;
          margin-bottom: 8px !important;
        }
        html body.cb-dugout #cbQuickDefense .cb-qd-field {
          width: min(74vw, 560px) !important;
          min-height: 0 !important;
          margin-left: auto !important;
          margin-right: auto !important;
        }
        html body.cb-dugout .coach-actions {
          grid-template-columns: repeat(4,minmax(0,1fr)) !important;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function ensure() {
    let badge = document.getElementById(ID);
    if (badge) return badge;
    badge = document.createElement('div');
    badge.id = ID;
    badge.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:2300;border-radius:999px;padding:6px 9px;font:700 11px/1.1 system-ui,-apple-system,sans-serif;box-shadow:0 2px 8px rgba(16,24,40,.18);display:none;';
    document.body.appendChild(badge);
    return badge;
  }

  function gameIsLive() {
    const overlay = document.getElementById('live-game-overlay');
    return Boolean(overlay && !overlay.classList.contains('d-none'));
  }

  function paint(mode) {
    const badge = ensure();
    if (!gameIsLive()) {
      badge.style.display = 'none';
      return;
    }
    badge.style.display = 'block';
    if (mode === 'connected') {
      badge.textContent = lastUpdate ? 'Live Sync ✓ · just now' : 'Live Sync ✓';
      badge.style.background = '#e9f7ee';
      badge.style.color = '#176b38';
      badge.style.border = '1px solid #b9dcc4';
    } else if (mode === 'connecting') {
      badge.textContent = 'Reconnecting…';
      badge.style.background = '#fff4dd';
      badge.style.color = '#8b5c00';
      badge.style.border = '1px solid #eed4a4';
    } else {
      badge.textContent = 'Offline';
      badge.style.background = '#feecec';
      badge.style.color = '#a32929';
      badge.style.border = '1px solid #e9a7a7';
    }
  }

  installResponsiveStyles();

  const socket = io();
  socket.on('connect', () => {
    socket.emit('join_game_room', {game_id: gameId});
    paint('connected');
  });
  socket.on('disconnect', () => paint('connecting'));
  socket.io.on('reconnect_attempt', () => paint('connecting'));
  socket.on('game_state_update', () => {
    lastUpdate = Date.now();
    paint('connected');
  });

  window.setInterval(() => paint(socket.connected ? 'connected' : 'connecting'), 2500);
})();
