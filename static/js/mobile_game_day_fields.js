(() => {
  'use strict';

  if (window.location.pathname !== '/' || !window.matchMedia('(max-width: 991.98px)').matches) return;

  let gamesById = new Map();
  let scheduleObserver = null;
  let patchQueued = false;

  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function canDeleteGames() {
    return ['Head Coach', 'Super Admin'].includes(document.body?.dataset?.coachRole || '');
  }

  function installStyles() {
    if (document.getElementById('cb-mobile-game-day-fields-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-mobile-game-day-fields-styles';
    style.textContent = `
      @media(max-width:991.98px){
        #games .cb-game-datetime-fields{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;width:100%}
        #games .cb-game-native-field{min-width:0}
        #games .cb-game-native-field>label{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:0 0 6px;color:#475467;font-size:.72rem;font-weight:800;letter-spacing:.01em}
        #games .cb-game-native-field>label small{color:#98a2b3;font-size:.62rem;font-weight:700}
        #games .cb-game-native-input{position:relative;min-width:0}
        #games .cb-game-native-input .form-control{width:100%;min-width:0;min-height:50px;font-size:16px;padding:.7rem .75rem;background:#fff}
        #games .cb-game-native-empty{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:#667085;font-size:.82rem;font-weight:650;line-height:1;pointer-events:none;background:#fff;padding-right:4px}
        #games .cb-game-native-input.has-value .cb-game-native-empty{display:none}
        #games .cb-mobile-past-games-card[hidden]{display:none!important}
        #games .cb-mobile-past-games-card .card-header h5{margin:0}
        #games .cb-schedule-empty{padding:18px 16px;color:#667085;text-align:center}
        #games .cb-api-game-row .btn{min-height:40px;display:inline-flex;align-items:center}
        #games .cb-mobile-delete-game{min-width:42px;justify-content:center}
      }
      @media(max-width:430px){#games .cb-game-datetime-fields{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function syncEmptyState(input, wrapper) {
    if (!input || !wrapper) return;
    wrapper.classList.toggle('has-value', Boolean(input.value));
  }

  function wrapNativeField(input, labelText, emptyText, optional = false) {
    const field = document.createElement('div');
    field.className = 'cb-game-native-field';

    const label = document.createElement('label');
    label.setAttribute('for', input.id);
    label.innerHTML = `${escapeHTML(labelText)}${optional ? '<small>Optional</small>' : ''}`;

    const inputWrap = document.createElement('div');
    inputWrap.className = 'cb-game-native-input';
    const hint = document.createElement('span');
    hint.className = 'cb-game-native-empty';
    hint.textContent = emptyText;

    input.setAttribute('aria-label', optional ? `${labelText} (optional)` : labelText);
    inputWrap.append(input, hint);
    field.append(label, inputWrap);

    const update = () => syncEmptyState(input, inputWrap);
    input.addEventListener('input', update);
    input.addEventListener('change', update);
    input.addEventListener('blur', update);
    update();

    return field;
  }

  function enhanceAddGameForm() {
    const dateInput = document.getElementById('add_game_date');
    const form = dateInput?.closest('form');
    const timeInput = form?.querySelector('input[name="game_start_time"]');
    const group = dateInput?.closest('.input-group');
    if (!dateInput || !timeInput || !group || group.dataset.cbDateTimeEnhanced === '1') return;

    group.dataset.cbDateTimeEnhanced = '1';
    group.classList.remove('input-group');
    group.classList.add('cb-game-datetime-fields');

    if (!timeInput.id) timeInput.id = 'add_game_start_time';
    const dateField = wrapNativeField(dateInput, 'Date', 'Select date');
    const timeField = wrapNativeField(timeInput, 'Start time', 'Select time', true);
    group.replaceChildren(dateField, timeField);
  }

  function dateOnly(value) {
    const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    return match ? {year:Number(match[1]), month:Number(match[2]), day:Number(match[3])} : null;
  }

  function dateKey(value) {
    const parts = dateOnly(value);
    return parts
      ? `${String(parts.year).padStart(4, '0')}-${String(parts.month).padStart(2, '0')}-${String(parts.day).padStart(2, '0')}`
      : '';
  }

  function todayKey() {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  }

  function formatGameDate(value) {
    const parts = dateOnly(value);
    if (!parts) return String(value || 'Date TBD');
    const local = new Date(parts.year, parts.month - 1, parts.day, 12, 0, 0);
    return local.toLocaleDateString('en-US', {weekday:'long', year:'2-digit', month:'2-digit', day:'2-digit'});
  }

  function formatStartTime(value) {
    const match = String(value || '').match(/^(\d{1,2}):(\d{2})/);
    if (!match) return 'Time TBD';
    let hours = Number(match[1]);
    const minutes = Number(match[2]);
    if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return 'Time TBD';
    const suffix = hours >= 12 ? 'PM' : 'AM';
    hours %= 12;
    if (hours === 0) hours = 12;
    return `${hours}:${String(minutes).padStart(2, '0')} ${suffix}`;
  }

  function gameIdForItem(item) {
    const explicit = Number(item?.dataset?.cbGameId);
    if (Number.isInteger(explicit) && explicit > 0) return explicit;
    const manage = item?.querySelector('a[href^="/game/"]');
    const match = manage?.getAttribute('href')?.match(/^\/game\/(\d+)/);
    return match ? Number(match[1]) : null;
  }

  function ensurePastGamesSection(scheduleContainer) {
    const scheduleCard = scheduleContainer?.closest('.card');
    if (!scheduleCard) return {card:null, list:null};

    let card = document.getElementById('cb-mobile-past-games-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'cb-mobile-past-games-card';
      card.className = 'card mt-4 cb-mobile-past-games-card';
      card.innerHTML = `
        <div class="card-header"><h5 class="mb-0">Past Games</h5></div>
        <ul class="list-group list-group-flush" id="games-past-list-container"></ul>`;
      scheduleCard.insertAdjacentElement('afterend', card);
    }
    return {card, list:card.querySelector('#games-past-list-container')};
  }

  function buildApiGameItem(game) {
    const item = document.createElement('li');
    item.className = 'list-group-item cb-api-game-row';
    item.dataset.cbGameId = String(game.id);
    item.innerHTML = `
      <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
        <div class="me-auto">
          <h5 class="mb-1">vs ${escapeHTML(game.opponent || 'Opponent TBD')}</h5>
          <p class="mb-1"></p>
        </div>
        <a href="/game/${Number(game.id)}" class="btn btn-primary btn-sm"><i class="bi bi-tools me-1"></i>Manage</a>
      </div>`;
    patchGameMeta(item, game);
    return item;
  }

  function gameSortKey(game) {
    return `${dateKey(game?.date)}|${game?.start_time || '99:99'}|${String(game?.id || '').padStart(8, '0')}`;
  }

  function sortGameItems(container, direction = 'asc') {
    if (!container) return;
    const items = [...container.querySelectorAll(':scope > li.list-group-item')]
      .filter(item => gameIdForItem(item) !== null);
    const sorted = [...items].sort((a, b) => {
      const keyA = gameSortKey(gamesById.get(gameIdForItem(a)) || {});
      const keyB = gameSortKey(gamesById.get(gameIdForItem(b)) || {});
      return direction === 'desc' ? keyB.localeCompare(keyA) : keyA.localeCompare(keyB);
    });
    const currentIds = items.map(gameIdForItem).join(',');
    const sortedIds = sorted.map(gameIdForItem).join(',');
    if (currentIds !== sortedIds) sorted.forEach(item => container.appendChild(item));
  }

  function patchGameMeta(item, game) {
    const meta = item.querySelector('p.mb-1');
    if (!meta) return;
    const signature = `${game.date || ''}|${game.start_time || ''}|${game.location || ''}`;
    if (meta.dataset.cbGameMetaSignature === signature) return;
    meta.dataset.cbGameMetaSignature = signature;

    const dateLabel = formatGameDate(game.date);
    const timeLabel = formatStartTime(game.start_time);
    const locationLabel = escapeHTML(game.location || 'TBD');
    meta.innerHTML = `<i class="bi bi-calendar-event"></i> ${escapeHTML(dateLabel)} · ${escapeHTML(timeLabel)} <span class="text-muted mx-2">|</span> <i class="bi bi-geo-alt"></i> ${locationLabel}`;
  }

  function ensurePastDeleteAction(item, game) {
    item.dataset.cbGameId = String(game.id);
    item.querySelectorAll('[data-delete-url^="/delete_game/"]').forEach(button => button.remove());
    if (!canDeleteGames()) {
      item.querySelectorAll('.cb-mobile-delete-game').forEach(button => button.remove());
      return;
    }
    if (item.querySelector('.cb-mobile-delete-game')) return;

    const manage = item.querySelector('a[href^="/game/"]');
    if (!manage) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-sm btn-outline-danger cb-mobile-delete-game';
    button.dataset.gameId = String(game.id);
    button.setAttribute('aria-label', `Delete game vs ${game.opponent || 'opponent'}`);
    button.title = 'Delete Game';
    button.innerHTML = '<i class="bi bi-trash"></i>';
    manage.insertAdjacentElement('afterend', button);
  }

  function removePastDeleteAction(item) {
    item.querySelectorAll('.cb-mobile-delete-game').forEach(button => button.remove());
  }

  async function deletePastGame(button) {
    if (!canDeleteGames() || button.disabled) return;
    const gameId = Number(button.dataset.gameId || button.closest('[data-cb-game-id]')?.dataset?.cbGameId || 0);
    const game = gamesById.get(gameId);
    if (!gameId || !game) return;

    const okay = window.confirm(
      `Delete the game vs ${game.opponent || 'this opponent'}?\n\nThis permanently removes the game and its attached planning, pitching, and live-game data. This cannot be undone.`
    );
    if (!okay) return;

    button.disabled = true;
    try {
      const response = await fetch(`/game-day/${gameId}/delete`, {
        method:'POST',
        headers:{'Accept':'application/json'},
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') {
        throw new Error(data.message || `Unable to delete game (${response.status}).`);
      }
      gamesById.delete(gameId);
      window.location.reload();
    } catch (error) {
      window.alert(error.message || 'Unable to delete game.');
      button.disabled = false;
    }
  }

  function collectUniqueRows(schedule, pastList) {
    const combined = new Map();
    const candidates = [
      ...pastList.querySelectorAll(':scope > li.list-group-item'),
      ...schedule.querySelectorAll(':scope > li.list-group-item'),
    ];

    candidates.forEach(item => {
      const id = gameIdForItem(item);
      if (id === null) return;
      const existing = combined.get(id);
      if (!existing) {
        combined.set(id, item);
        return;
      }

      // Prefer main.js's richer row over our API fallback if both exist.
      if (existing.classList.contains('cb-api-game-row') && !item.classList.contains('cb-api-game-row')) {
        existing.remove();
        combined.set(id, item);
      } else {
        item.remove();
      }
    });
    return combined;
  }

  function patchSchedule() {
    patchQueued = false;
    const schedule = document.getElementById('games-list-container');
    if (!schedule || gamesById.size === 0) return;

    const {card:pastCard, list:pastList} = ensurePastGamesSection(schedule);
    if (!pastCard || !pastList) return;

    schedule.querySelectorAll('.cb-schedule-empty').forEach(node => node.remove());

    const legacyMainRows = [...schedule.querySelectorAll(':scope > li.list-group-item')]
      .filter(item => gameIdForItem(item) !== null && !item.classList.contains('cb-api-game-row'));
    const legacyMainIds = new Set(legacyMainRows.map(gameIdForItem));

    // When main.js has just rebuilt all rows, discard our old moved/fallback
    // nodes so the richer legacy rows can be split cleanly again.
    if (legacyMainIds.size === gamesById.size) pastList.replaceChildren();

    const combined = collectUniqueRows(schedule, pastList);

    // /api/games is the source of truth. If the legacy renderer is late or
    // omitted a game, create a clean row so schedule/history never loses it.
    gamesById.forEach((game, gameId) => {
      if (!combined.has(gameId)) combined.set(gameId, buildApiGameItem(game));
    });

    const today = todayKey();
    combined.forEach((item, gameId) => {
      const game = gamesById.get(gameId);
      if (!game) {
        item.remove();
        return;
      }
      patchGameMeta(item, game);
      const key = dateKey(game.date);
      const isPast = Boolean(key && key < today);
      const target = isPast ? pastList : schedule;
      if (item.parentElement !== target) target.appendChild(item);
      if (isPast) ensurePastDeleteAction(item, game);
      else removePastDeleteAction(item);
    });

    sortGameItems(schedule, 'asc');
    sortGameItems(pastList, 'desc');

    const scheduleCount = [...schedule.querySelectorAll(':scope > li.list-group-item')]
      .filter(item => gameIdForItem(item) !== null).length;
    const pastCount = [...pastList.querySelectorAll(':scope > li.list-group-item')]
      .filter(item => gameIdForItem(item) !== null).length;

    if (scheduleCount === 0) {
      const empty = document.createElement('li');
      empty.className = 'list-group-item cb-schedule-empty';
      empty.textContent = 'No upcoming games scheduled.';
      schedule.appendChild(empty);
    }
    pastCard.hidden = pastCount === 0;
  }

  function queueSchedulePatch() {
    if (patchQueued) return;
    patchQueued = true;
    window.requestAnimationFrame(patchSchedule);
  }

  async function loadGames() {
    try {
      const response = await fetch(`/api/games?_=${Date.now()}`, {
        cache:'no-store',
        headers:{'Cache-Control':'no-cache'}
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const games = await response.json();
      gamesById = new Map((Array.isArray(games) ? games : []).map(game => [Number(game.id), game]));
      queueSchedulePatch();
    } catch (error) {
      console.warn('Unable to refresh Game Day schedule:', error);
    }
  }

  function observeSchedule() {
    const container = document.getElementById('games-list-container');
    if (!container || scheduleObserver) return;
    scheduleObserver = new MutationObserver(queueSchedulePatch);
    scheduleObserver.observe(container, {childList:true, subtree:true});
    queueSchedulePatch();
  }

  function start() {
    installStyles();
    enhanceAddGameForm();
    observeSchedule();
    loadGames();

    document.addEventListener('click', event => {
      const button = event.target.closest('.cb-mobile-delete-game');
      if (button) deletePastGame(button);
    });

    window.addEventListener('pageshow', loadGames);
    window.addEventListener('hashchange', () => {
      if (window.location.hash === '#games') {
        enhanceAddGameForm();
        loadGames();
      }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
