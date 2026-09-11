(() => {
  'use strict';

  if (window.location.pathname !== '/game-day') return;

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
    }[ch]));
  }

  function canDeleteGames() {
    return ['Head Coach', 'Super Admin'].includes(document.body?.dataset?.coachRole || '');
  }

  function installStyles() {
    if (document.getElementById('game-day-actions-styles')) return;
    const style = document.createElement('style');
    style.id = 'game-day-actions-styles';
    style.textContent = `
      .gd-upcoming{overflow:visible!important}
      .gd-game-menu{margin-left:auto;flex:0 0 auto}
      .gd-game-menu>.btn{min-width:44px!important;width:44px!important;padding:0!important;flex:0 0 44px!important;font-size:1.2rem;line-height:1}
      .gd-game-menu .dropdown-menu{min-width:190px;border-radius:11px;padding:6px;box-shadow:0 8px 24px rgba(16,24,40,.14);z-index:1080}
      .gd-game-menu .dropdown-item{border-radius:7px;padding:9px 10px;font-size:.82rem;font-weight:650}
      .gd-game-menu .dropdown-item.text-danger{color:#b42318!important}
      .gd-hero-tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
      .gd-add-game{min-height:40px;border-radius:10px;font-weight:800;white-space:nowrap}
      .gd-schedule-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:24px;margin-bottom:9px}
      .gd-schedule-head .gd-section-title{margin:0}
      .gd-schedule-actions{display:flex;gap:6px;align-items:center;justify-content:flex-end;flex-wrap:wrap}
      .gd-schedule-actions>.btn{white-space:nowrap}
      .gd-schedule-empty{border:1px dashed #ccd3db;border-radius:14px;padding:20px;text-align:center;background:#fafbfc;color:#667085;font-size:.78rem}
      #game-day-add-modal .modal-content{border:0;border-radius:16px;overflow:hidden}
      #game-day-add-modal .modal-header{border-bottom:1px solid #eef1f4}
      #game-day-add-modal .form-label{font-size:.76rem;font-weight:750;color:#344054}
      #game-day-add-modal .form-control{min-height:46px;border-radius:10px}
      #game-day-add-modal textarea.form-control{min-height:86px}
      @media(max-width:767.98px){
        .gd-hero{align-items:flex-start!important}
        .gd-hero-tools{margin-left:auto}
        .gd-add-game{padding-left:12px;padding-right:12px}
        .gd-schedule-head{margin-top:20px}
        .gd-schedule-actions{grid-column:2!important;justify-content:flex-start;margin-top:4px}
        .gd-schedule-actions>.btn:first-child{flex:1 1 auto}
        #game-day-add-modal .modal-dialog{height:calc(100dvh - 16px);margin:8px}
        #game-day-add-modal .modal-content{max-height:100%}
        #game-day-add-modal .modal-header{padding:14px 16px}
        #game-day-add-modal .modal-body{padding:16px;overscroll-behavior:contain}
        #game-day-add-modal .modal-footer{flex:0 0 auto;padding:10px 16px calc(10px + env(safe-area-inset-bottom));background:#fff}
        #game-day-add-modal .modal-footer .btn-primary{flex:1 1 auto;min-height:46px}
      }
    `;
    document.head.appendChild(style);
  }

  function ensurePrimaryButtonContrast() {
    document.querySelectorAll('.gd-primary').forEach(button => {
      const background = window.getComputedStyle(button).backgroundColor.replace(/\s/g, '');
      if (
        background === 'rgba(0,0,0,0)' ||
        background === 'transparent' ||
        background === 'rgb(255,255,255)' ||
        background === 'rgba(255,255,255,1)'
      ) {
        button.style.backgroundColor = '#102a66';
        button.style.borderColor = '#102a66';
        button.style.color = '#fff';
      }
    });
  }

  function todayLocalValue() {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  }

  function ensureAddGameModal() {
    let modal = document.getElementById('game-day-add-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'game-day-add-modal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
        <form class="modal-content" action="/game-day/add" method="POST">
          <div class="modal-header">
            <div>
              <h5 class="modal-title mb-0">Add Game</h5>
              <div class="small text-muted">Create the game and open pregame setup.</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
              <div class="row g-3">
                <div class="col-7">
                  <label class="form-label" for="gd-add-date">Date</label>
                  <input class="form-control" id="gd-add-date" type="date" name="game_date" required>
                </div>
                <div class="col-5">
                  <label class="form-label" for="gd-add-time">Time</label>
                  <input class="form-control" id="gd-add-time" type="time" name="game_start_time">
                </div>
                <div class="col-12">
                  <label class="form-label" for="gd-add-opponent">Opponent</label>
                  <input class="form-control" id="gd-add-opponent" name="game_opponent" autocomplete="off" placeholder="Team name" required>
                </div>
                <div class="col-12">
                  <label class="form-label" for="gd-add-location">Location / Field</label>
                  <input class="form-control" id="gd-add-location" name="game_location" autocomplete="off" placeholder="Grand Park Field 12">
                </div>
                <div class="col-12">
                  <label class="form-label" for="gd-add-notes">Game Notes</label>
                  <textarea class="form-control" id="gd-add-notes" name="game_notes" rows="3" placeholder="Pool play, arrival time, opponent notes, etc."></textarea>
                </div>
              </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="submit" class="btn btn-primary">Add & Prepare Game</button>
          </div>
        </form>
      </div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function openAddGame() {
    const modal = ensureAddGameModal();
    const date = modal.querySelector('#gd-add-date');
    if (date && !date.value) date.value = todayLocalValue();
    bootstrap.Modal.getOrCreateInstance(modal).show();
    window.setTimeout(() => modal.querySelector('#gd-add-opponent')?.focus(), 250);
  }

  function addHeroButton() {
    const hero = document.querySelector('.gd-hero');
    if (!hero || hero.querySelector('.gd-add-game')) return;

    const date = hero.querySelector('.gd-date');
    const tools = document.createElement('div');
    tools.className = 'gd-hero-tools';
    if (date) tools.appendChild(date);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-primary gd-add-game';
    button.innerHTML = '<i class="bi bi-plus-lg me-1"></i>Add Game';
    button.addEventListener('click', openAddGame);
    tools.appendChild(button);
    hero.appendChild(tools);
  }

  function opponentFor(container) {
    const text = container.querySelector('.gd-opponent, .gd-up-name')?.textContent || 'this game';
    return text.replace(/^\s*vs\s+/i, '').trim();
  }

  function menuMarkup(gameId, isLive = false) {
    const deleteItems = canDeleteGames()
      ? `<li><hr class="dropdown-divider"></li>
         <li><button type="button" class="dropdown-item text-danger gd-delete-game" ${isLive ? 'disabled' : ''}><i class="bi bi-trash me-2"></i>${isLive ? 'End Live Game First' : 'Delete Game'}</button></li>`
      : '';
    return `
      <button type="button" class="btn btn-outline-secondary" data-bs-toggle="dropdown" aria-expanded="false" aria-label="Game options" title="Game options">•••</button>
      <ul class="dropdown-menu dropdown-menu-end">
        <li><a class="dropdown-item" href="/game/${gameId}"><i class="bi bi-pencil-square me-2"></i>Open / Edit Game</a></li>
        ${deleteItems}
      </ul>`;
  }

  function addCardMenu(card) {
    if (card.querySelector('.gd-game-menu')) return;
    const gameId = Number(card.dataset.gameId || 0);
    const actions = card.querySelector('.gd-actions');
    if (!gameId || !actions) return;

    const isLive = (card.querySelector('.gd-status')?.textContent || '').trim().toUpperCase() === 'LIVE';
    const menu = document.createElement('div');
    menu.className = 'dropdown gd-game-menu';
    menu.innerHTML = menuMarkup(gameId, isLive);
    actions.appendChild(menu);
  }

  function inferScheduleGameId(row) {
    const gameLink = [...row.querySelectorAll('a[href]')]
      .map(link => ({link, match: link.getAttribute('href')?.match(/^\/game\/(\d+)/)}))
      .find(item => item.match);
    return gameLink ? Number(gameLink.match[1]) : 0;
  }

  function addScheduleRowMenu(row) {
    if (row.querySelector('.gd-game-menu')) return;
    const gameId = inferScheduleGameId(row);
    if (!gameId) return;
    row.dataset.gameId = String(gameId);

    const existingActions = row.querySelector(':scope > .gd-up-actions, :scope > .gd-schedule-actions');
    if (existingActions) {
      existingActions.classList.add('gd-schedule-actions');
      const menu = document.createElement('div');
      menu.className = 'dropdown gd-game-menu';
      menu.innerHTML = menuMarkup(gameId, false);
      existingActions.appendChild(menu);
      return;
    }

    const existingAction = [...row.children].find(child => child.matches?.('a.btn'));
    const actions = document.createElement('div');
    actions.className = 'gd-schedule-actions';
    if (existingAction) actions.appendChild(existingAction);

    const menu = document.createElement('div');
    menu.className = 'dropdown gd-game-menu';
    menu.innerHTML = menuMarkup(gameId, false);
    actions.appendChild(menu);
    row.appendChild(actions);
  }

  function scheduleSection() {
    const shell = document.querySelector('.gd-shell');
    if (!shell) return;

    const titles = [...shell.querySelectorAll('.gd-section-title')];
    let title = titles.find(item => item.textContent.trim().toLowerCase() === 'coming up');
    let list = title?.nextElementSibling?.classList.contains('gd-upcoming') ? title.nextElementSibling : null;

    if (title) {
      title.textContent = 'Schedule';
      const head = document.createElement('div');
      head.className = 'gd-schedule-head';
      title.parentNode.insertBefore(head, title);
      head.appendChild(title);
      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'btn btn-sm btn-outline-primary gd-add-game';
      add.innerHTML = '<i class="bi bi-plus-lg me-1"></i>Add Game';
      add.addEventListener('click', openAddGame);
      head.appendChild(add);
    } else {
      const head = document.createElement('div');
      head.className = 'gd-schedule-head';
      head.innerHTML = '<div class="gd-section-title">Schedule</div>';
      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'btn btn-sm btn-outline-primary gd-add-game';
      add.innerHTML = '<i class="bi bi-plus-lg me-1"></i>Add Game';
      add.addEventListener('click', openAddGame);
      head.appendChild(add);
      shell.appendChild(head);

      list = document.createElement('div');
      list.className = 'gd-schedule-empty';
      list.innerHTML = '<strong>No additional games scheduled.</strong>';
      shell.appendChild(list);
    }

    list?.querySelectorAll('.gd-up-row').forEach(addScheduleRowMenu);
  }

  function pastGameSection() {
    if (!canDeleteGames()) return;
    const shell = document.querySelector('.gd-shell');
    if (!shell) return;
    const title = [...shell.querySelectorAll('.gd-section-title')]
      .find(item => item.textContent.trim().toLowerCase() === 'past games');
    const list = title?.nextElementSibling?.classList.contains('gd-upcoming') ? title.nextElementSibling : null;
    list?.querySelectorAll('.gd-up-row').forEach(addScheduleRowMenu);
  }

  function fixEmptyState() {
    const empty = document.querySelector('.gd-empty');
    if (!empty) return;
    const link = empty.querySelector('a.btn');
    if (!link) return;
    link.href = '#';
    link.innerHTML = '<i class="bi bi-plus-lg me-1"></i>Add Game';
    link.classList.remove('btn-outline-primary');
    link.classList.add('btn-primary');
    link.addEventListener('click', event => {
      event.preventDefault();
      openAddGame();
    });
    const detail = empty.querySelector('div.mt-1');
    if (detail) detail.textContent = 'No games scheduled.';
  }

  async function deleteGame(button) {
    const container = button.closest('.gd-game, .gd-up-row[data-game-id]');
    const gameId = Number(container?.dataset.gameId || 0);
    if (!container || !gameId || button.disabled || !canDeleteGames()) return;

    const opponent = opponentFor(container);
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
    ensureAddGameModal();
    ensurePrimaryButtonContrast();
    addHeroButton();
    document.querySelectorAll('.gd-game[data-game-id]').forEach(addCardMenu);
    scheduleSection();
    pastGameSection();
    fixEmptyState();

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
