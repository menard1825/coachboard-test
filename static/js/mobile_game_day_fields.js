(() => {
  'use strict';

  if (window.location.pathname !== '/' || !window.matchMedia('(max-width: 991.98px)').matches) return;

  let gamesById = new Map();
  let scheduleObserver = null;
  let patchQueued = false;

  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function installStyles() {
    if (document.getElementById('cb-mobile-game-day-fields-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-mobile-game-day-fields-styles';
    style.textContent = `
      @media(max-width:991.98px){
        #games .cb-game-datetime-fields{
          display:grid;
          grid-template-columns:minmax(0,1fr) minmax(0,1fr);
          gap:10px;
          width:100%;
        }
        #games .cb-game-native-field{min-width:0}
        #games .cb-game-native-field>label{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:8px;
          margin:0 0 6px;
          color:#475467;
          font-size:.72rem;
          font-weight:800;
          letter-spacing:.01em;
        }
        #games .cb-game-native-field>label small{
          color:#98a2b3;
          font-size:.62rem;
          font-weight:700;
        }
        #games .cb-game-native-input{
          position:relative;
          min-width:0;
        }
        #games .cb-game-native-input .form-control{
          width:100%;
          min-width:0;
          min-height:50px;
          font-size:16px;
          padding:.7rem .75rem;
          background:#fff;
        }
        #games .cb-game-native-empty{
          position:absolute;
          left:13px;
          top:50%;
          transform:translateY(-50%);
          color:#667085;
          font-size:.82rem;
          font-weight:650;
          line-height:1;
          pointer-events:none;
          background:#fff;
          padding-right:4px;
        }
        #games .cb-game-native-input.has-value .cb-game-native-empty{display:none}
        #games .cb-mobile-past-games-card[hidden]{display:none!important}
        #games .cb-mobile-past-games-card .card-header h5{margin:0}
        #games .cb-schedule-empty{padding:18px 16px;color:#667085;text-align:center}
      }
      @media(max-width:430px){
        #games .cb-game-datetime-fields{grid-template-columns:1fr}
      }
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
    return local.toLocaleDateString('en-US', {
      weekday:'long', year:'2-digit', month:'2-digit', day:'2-digit'
    });
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

  function sortGameItems(container, direction = 'asc') {
    if (!container) return;
    const items = [...container.querySelectorAll(':scope > li.list-group-item')]
      .filter(item => gameIdForItem(item) !== null);
    items.sort((a, b) => {
      const gameA = gamesById.get(gameIdForItem(a)) || {};
      const gameB = gamesById.get(gameIdForItem(b)) || {};
      const keyA = `${dateKey(gameA.date)}|${gameA.start_time || '99:99'}|${String(gameA.id || '').padStart(8, '0')}`;
      const keyB = `${dateKey(gameB.date)}|${gameB.start_time || '99:99'}|${String(gameB.id || '').padStart(8, '0')}`;
      return direction === 'desc' ? keyB.localeCompare(keyA) : keyA.localeCompare(keyB);
    });
    items.forEach(item => container.appendChild(item));
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

  function patchSchedule() {
    patchQueued = false;
    const schedule = document.getElementById('games-list-container');
    if (!schedule || gamesById.size === 0) return;

    const {card:pastCard, list:pastList} = ensurePastGamesSection(schedule);
    if (!pastCard || !pastList) return;

    schedule.querySelectorAll('.cb-schedule-empty').forEach(node => node.remove());

    const mainItems = [...schedule.querySelectorAll(':scope > li.list-group-item')]
      .filter(item => gameIdForItem(item) !== null);
    const mainIds = new Set(mainItems.map(gameIdForItem));

    // main.js periodically rebuilds the legacy schedule with every game. When
    // that happens, treat the fresh main list as authoritative and discard the
    // previously moved history nodes before splitting again.
    if (mainIds.size === gamesById.size) pastList.replaceChildren();

    const combined = new Map();
    pastList.querySelectorAll(':scope > li.list-group-item').forEach(item => {
      const id = gameIdForItem(item);
      if (id !== null) combined.set(id, item);
    });
    schedule.querySelectorAll(':scope > li.list-group-item').forEach(item => {
      const id = gameIdForItem(item);
      if (id !== null) combined.set(id, item);
    });

    const today = todayKey();
    combined.forEach((item, gameId) => {
      const game = gamesById.get(gameId);
      if (!game) return;
      patchGameMeta(item, game);
      const isPast = Boolean(dateKey(game.date) && dateKey(game.date) < today);
      const target = isPast ? pastList : schedule;
      if (item.parentElement !== target) target.appendChild(item);
    });

    sortGameItems(schedule, 'asc');
    sortGameItems(pastList, 'desc');

    const scheduleCount = schedule.querySelectorAll(':scope > li.list-group-item a[href^="/game/"]').length;
    const pastCount = pastList.querySelectorAll(':scope > li.list-group-item a[href^="/game/"]').length;

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
