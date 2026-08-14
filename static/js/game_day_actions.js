(() => {
  'use strict';

  if (window.location.pathname !== '/game-day') return;

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
    }[ch]));
  }

  function installStyles() {
    if (document.getElementById('game-day-actions-styles')) return;
    const style = document.createElement('style');
    style.id = 'game-day-actions-styles';
    style.textContent = `
      .gd-game-menu{margin-left:auto;flex:0 0 auto}
      .gd-game-menu>.btn{min-width:44px!important;width:44px!important;padding:0!important;flex:0 0 44px!important;font-size:1.2rem;line-height:1}
      .gd-game-menu .dropdown-menu{min-width:190px;border-radius:11px;padding:6px;box-shadow:0 8px 24px rgba(16,24,40,.14)}
      .gd-game-menu .dropdown-item{border-radius:7px;padding:9px 10px;font-size:.82rem;font-weight:650}
      .gd-game-menu .dropdown-item.text-danger{color:#b42318!important}
    `;
    document.head.appendChild(style);
  }

  function opponentFor(card) {
    return (card.querySelector('.gd-opponent')?.textContent || 'this game')
      .replace(/^\s*vs\s+/i, '')
      .trim();
  }

  function addMenu(card) {
    if (card.querySelector('.gd-game-menu')) return;
    const gameId = Number(card.dataset.gameId || 0);
    const actions = card.querySelector('.gd-actions');
    if (!gameId || !actions) return;

    const isLive = (card.querySelector('.gd-status')?.textContent || '').trim().toUpperCase() === 'LIVE';
    const menu = document.createElement('div');
    menu.className = 'dropdown gd-game-menu';
    menu.innerHTML = `
      <button type="button" class="btn btn-outline-secondary" data-bs-toggle="dropdown" aria-expanded="false" aria-label="Game options" title="Game options">•••</button>
      <ul class="dropdown-menu dropdown-menu-end">
        <li><a class="dropdown-item" href="/game/${gameId}"><i class="bi bi-pencil-square me-2"></i>Open / Edit Game</a></li>
        <li><hr class="dropdown-divider"></li>
        <li><button type="button" class="dropdown-item text-danger gd-delete-game" ${isLive ? 'disabled' : ''}><i class="bi bi-trash me-2"></i>${isLive ? 'End Live Game First' : 'Delete Game'}</button></li>
      </ul>`;
    actions.appendChild(menu);
  }

  async function deleteGame(button) {
    const card = button.closest('.gd-game');
    const gameId = Number(card?.dataset.gameId || 0);
    if (!card || !gameId || button.disabled) return;

    const opponent = opponentFor(card);
    const okay = window.confirm(
      `Delete the game vs ${opponent}?\n\nThis permanently removes this game and its attached lineup, rotation, pitching plan/history, and live-game data. This cannot be undone.`
    );
    if (!okay) return;

    button.disabled = true;
    const original = button.innerHTML;
    button.textContent = 'Deleting…';

    try {
      const response = await fetch(`/game-day/${gameId}/delete`, {
        method: 'POST',
        headers: {'Accept': 'application/json'},
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') {
        throw new Error(data.message || `Unable to delete game (${response.status}).`);
      }
      window.location.reload();
    } catch (error) {
      window.alert(error.message || 'Unable to delete game.');
      button.disabled = false;
      button.innerHTML = original;
    }
  }

  function init() {
    installStyles();
    document.querySelectorAll('.gd-game[data-game-id]').forEach(addMenu);
    document.addEventListener('click', event => {
      const button = event.target.closest('.gd-delete-game');
      if (button) deleteGame(button);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, {once:true});
  } else {
    init();
  }
})();
