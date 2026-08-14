(() => {
  'use strict';
  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match || typeof io !== 'function') return;
  const gameId = Number(match[1]);
  const ID = 'coach-live-sync-status';
  let lastUpdate = null;

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
