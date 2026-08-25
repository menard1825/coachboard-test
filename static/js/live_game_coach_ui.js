(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  const $ = (id) => document.getElementById(id);
  let enhanced = false;
  let defenseView = 'list';
  let lastDefenseSignature = '';
  let tickQueued = false;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function addStyles() {
    if ($('coach-live-polish-styles')) return;
    const style = document.createElement('style');
    style.id = 'coach-live-polish-styles';
    style.textContent = `
      .coach-game-header { gap:14px; align-items:flex-start !important; padding:2px 0 8px; }
      .coach-game-header h3 { font-size:clamp(1.55rem,4.2vw,2rem); line-height:1.12; letter-spacing:-.02em; }
      .coach-game-meta { display:flex; flex-wrap:wrap; align-items:center; gap:6px 10px; margin-top:7px; color:#667085 !important; font-size:.94rem; }
      .coach-game-meta .meta-divider { color:#c2c8d0; }
      .coach-game-meta .meta-location { flex-basis:auto; }
      .coach-game-header-actions { display:flex; gap:6px; flex-shrink:0; }
      .coach-game-header-actions .btn { border-radius:9px; font-weight:650; }

      #live-game-overlay.coach-live-polished { background:#f5f6f8 !important; padding:10px !important; }
      #live-game-overlay.coach-live-polished > :not(.coach-live-shell):not(.modal) { display:none !important; }
      .coach-live-shell { max-width:980px; margin:0 auto; }
      .coach-live-head { display:flex; justify-content:space-between; align-items:flex-start; gap:14px; margin-bottom:10px; }
      .coach-live-kicker { font-size:.68rem; color:#667085; text-transform:uppercase; letter-spacing:.11em; font-weight:800; }
      .coach-live-context { margin-top:2px; color:#344054; font-size:.9rem; font-weight:650; }
      .coach-live-subcontext { color:#8a94a3; font-size:.76rem; margin-top:1px; }
      .coach-inning-pill { background:#172033; color:#fff; border-radius:10px; min-width:74px; padding:8px 10px; text-align:center; box-shadow:0 1px 2px rgba(16,24,40,.12); }
      .coach-inning-pill small { display:block; font-size:.58rem; opacity:.7; font-weight:750; letter-spacing:.1em; }
      .coach-inning-pill strong { display:block; font-size:1.45rem; line-height:1.05; margin-top:2px; }
      .coach-card { background:#fff; border:1px solid #e4e7ec; border-radius:13px; box-shadow:0 1px 3px rgba(16,24,40,.06); padding:12px; margin-bottom:10px; }
      .coach-label { font-size:.66rem; color:#667085; text-transform:uppercase; letter-spacing:.09em; font-weight:800; }
      .coach-help { color:#98a2b3; font-size:.76rem; margin-top:1px; }

      .coach-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
      .coach-actions .btn { min-height:58px; border-radius:11px !important; padding:8px 10px; box-shadow:none !important; text-align:left; display:flex !important; flex-direction:column; justify-content:center; align-items:flex-start !important; line-height:1.1; }
      .coach-actions .btn i { display:none !important; }
      .coach-action-title { display:block; font-weight:780; font-size:.94rem; }
      .coach-action-note { display:block; margin-top:4px; font-size:.67rem; font-weight:550; opacity:.68; }
      .coach-action-primary { background:var(--primary-color,#102a66) !important; border-color:var(--primary-color,#102a66) !important; color:#fff !important; }
      .coach-action-end { background:#202733 !important; border-color:#202733 !important; color:#fff !important; }
      .coach-action-undo { background:#fff !important; border:1px solid #d6dae1 !important; color:#5f6b7a !important; }

      .coach-defense-row { display:grid; grid-template-columns:42px minmax(0,1fr); gap:9px; align-items:center; padding:8px 0; border-bottom:1px solid #f0f1f3; }
      .coach-defense-row:last-child { border-bottom:0; }
      .coach-pos { display:flex; align-items:center; justify-content:center; width:38px; height:28px; border-radius:7px; background:#eef1f5; color:#344054; font-weight:800; font-size:.7rem; }
      .coach-player-name { font-weight:700; color:#1d2939; white-space:normal; overflow:visible; text-overflow:clip; overflow-wrap:anywhere; }
      .coach-player-name.empty { color:#98a2b3; font-weight:600; }
      .coach-bench { display:flex; flex-wrap:wrap; gap:6px; margin-top:7px; }
      .coach-bench span { border:1px solid #e0e4e9; background:#f8f9fb; color:#475467; border-radius:999px; padding:5px 9px; font-size:.72rem; font-weight:650; }

      .coach-view-toggle { padding:2px; border:1px solid #d9dde4; background:#f4f5f7; border-radius:9px; }
      .coach-view-toggle .btn { border:0 !important; border-radius:7px !important; padding:6px 11px; min-height:0; font-size:.72rem; font-weight:750; box-shadow:none !important; }
      .coach-view-toggle .btn-dark { background:#fff !important; color:#1d2939 !important; box-shadow:0 1px 2px rgba(16,24,40,.08) !important; }
      .coach-view-toggle .btn-outline-dark { background:transparent !important; color:#7b8492 !important; }

      .coach-field { position:relative; width:100%; aspect-ratio:1.08 / 1; max-height:520px; margin-top:10px; overflow:hidden; border:1px solid #dfe5de; border-radius:14px; background:linear-gradient(180deg,#edf5ec 0%,#f7f6ed 100%); }
      .coach-field-infield { position:absolute; width:37%; aspect-ratio:1; left:31.5%; top:38%; border:1px solid rgba(143,126,91,.34); background:rgba(232,220,186,.28); transform:rotate(45deg); border-radius:3px; }
      .coach-field-arc { position:absolute; left:12%; right:12%; top:8%; height:60%; border:1px solid rgba(93,132,92,.20); border-bottom:0; border-radius:50% 50% 0 0; }
      .coach-field-spot { position:absolute; transform:translate(-50%,-50%); text-align:center; min-width:70px; max-width:112px; }
      .coach-field-spot strong { display:block; color:#7b8492; font-size:.58rem; line-height:1; letter-spacing:.06em; margin-bottom:3px; }
      .coach-field-spot span { display:block; padding:5px 7px; border-radius:8px; border:1px solid rgba(208,213,221,.9); background:rgba(255,255,255,.92); color:#1d2939; font-weight:750; font-size:.68rem; white-space:normal; overflow:visible; text-overflow:clip; overflow-wrap:anywhere; box-shadow:0 1px 2px rgba(16,24,40,.05); }
      .coach-field-help { text-align:center; color:#98a2b3; font-size:.7rem; margin-top:7px; }

      #rotation-board.coach-live-board-hidden { display:none !important; }
      #live-defense-v2 .modal-dialog, #live-pitcher-picker-v2 .modal-dialog, #live-defense-destination-v2 .modal-dialog, #live-pitcher-destination-v2 .modal-dialog { margin:.55rem; }
      #live-defense-v2 .list-group-item, #live-pitcher-picker-v2 .pitcher-choice-v2 { border:1px solid #e4e7ec !important; border-radius:10px !important; margin-bottom:7px; padding:12px !important; }
      #live-defense-destination-v2 .btn, #live-pitcher-destination-v2 .btn { min-height:60px; border-radius:10px; font-weight:750; }
      #live-defense-v2 .modal-title::after { content:' - choose a player, then a position'; font-size:.7rem; font-weight:400; color:#7b8492; }

      @media (max-width:575.98px) {
        .coach-game-header { display:block !important; }
        .coach-game-header-actions { margin-top:10px; }
        .coach-game-header-actions .btn { flex:1; }
        .coach-game-meta .meta-location { flex-basis:100%; }
        #live-game-overlay.coach-live-polished { padding:8px !important; }
        .coach-card { border-radius:12px; padding:11px; }
        .coach-field-spot { min-width:58px; max-width:82px; }
        .coach-field-spot span { font-size:.62rem; padding:4px 5px; }
      }
    `;
    document.head.appendChild(style);
  }

  function parseTime(value) {
    const match = String(value || '').match(/^(\d{1,2}):(\d{2})/);
    if (!match) return '';
    let hour = Number(match[1]);
    const minute = match[2];
    if (!Number.isFinite(hour)) return '';
    const suffix = hour >= 12 ? 'PM' : 'AM';
    hour %= 12;
    if (!hour) hour = 12;
    return `${hour}:${minute} ${suffix}`;
  }

  function formatGameHeader() {
    const pregame = $('pregame-checklist-container');
    if (!pregame) return;
    const header = pregame.firstElementChild;
    if (!header) return;
    header.classList.add('coach-game-header');

    const title = header.querySelector('h3');
    if (title) title.id = 'coach-game-title';

    const meta = header.querySelector('p.text-muted');
    if (meta) {
      const dateValue = $('game_date')?.value || '';
      const timeValue = $('game_start_time')?.value || '';
      const locationValue = $('game_location')?.value || '';
      let dateLabel = '';
      const parts = dateValue.match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (parts) {
        const localDate = new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]));
        if (!Number.isNaN(localDate.getTime())) {
          dateLabel = new Intl.DateTimeFormat('en-US', { weekday:'short', month:'short', day:'numeric' }).format(localDate);
        }
      }
      if (!dateLabel) dateLabel = dateValue;
      const timeLabel = parseTime(timeValue);
      const bits = [];
      if (dateLabel) bits.push(`<span class="meta-date">${esc(dateLabel)}</span>`);
      if (timeLabel) bits.push(`<span class="meta-divider">•</span><span class="meta-time">${esc(timeLabel)}</span>`);
      if (locationValue) bits.push(`<span class="meta-divider">•</span><span class="meta-location">${esc(locationValue)}</span>`);
      meta.className = 'coach-game-meta';
      meta.innerHTML = bits.join('');
      meta.id = 'coach-game-meta';
    }

    const actionWrap = header.lastElementChild;
    if (actionWrap && actionWrap !== header.firstElementChild) {
      actionWrap.classList.add('coach-game-header-actions');
      actionWrap.querySelectorAll('.btn i').forEach(icon => icon.remove());
      actionWrap.querySelectorAll('.btn').forEach(btn => btn.classList.remove('ms-1'));
    }
  }

  function positionsFromDom() {
    return $('pos-mobile-LCF') || $('pos-desktop-LCF')
      ? ['P','C','1B','2B','3B','SS','LF','LCF','RCF','RF']
      : ['P','C','1B','2B','3B','SS','LF','CF','RF'];
  }

  function currentMode() {
    return window.matchMedia('(min-width: 992px)').matches ? 'desktop' : 'mobile';
  }

  function posName(pos, mode) {
    const tag = $(`pos-${mode}-${pos}`)?.querySelector('.player-tag');
    return tag?.dataset?.playerName || tag?.textContent?.trim() || '';
  }

  function currentDefense() {
    const mode = currentMode();
    const result = {};
    positionsFromDom().forEach(pos => { result[pos] = posName(pos, mode); });
    return result;
  }

  function benchNames() {
    const host = currentMode() === 'desktop' ? $('bench-list-desktop') : $('bench-list-mobile');
    if (!host) return [];
    return [...host.querySelectorAll('.player-tag, .badge')]
      .map(el => el.dataset?.playerName || el.textContent.trim())
      .filter(name => name && !/No one on bench/i.test(name));
  }

  function listMarkup(defense, bench) {
    const rows = positionsFromDom().map(pos => `<div class="coach-defense-row"><div class="coach-pos">${esc(pos)}</div><div class="coach-player-name ${defense[pos] ? '' : 'empty'}">${esc(defense[pos] || 'Open')}</div></div>`).join('');
    return `${rows}<div class="coach-label mt-3">Bench</div><div class="coach-bench">${bench.length ? bench.map(name => `<span>${esc(name)}</span>`).join('') : '<span>No players on bench</span>'}</div>`;
  }

  function fieldSpot(pos, defense, left, top) {
    return `<div class="coach-field-spot" style="left:${left}%;top:${top}%"><strong>${esc(pos)}</strong><span>${esc(defense[pos] || 'Open')}</span></div>`;
  }

  function fieldMarkup(defense) {
    const fourOutfielders = positionsFromDom().includes('LCF');
    const outfield = fourOutfielders
      ? [['LF',9,20],['LCF',36,11],['RCF',64,11],['RF',91,20]]
      : [['LF',13,19],['CF',50,9],['RF',87,19]];
    const spots = [...outfield,['3B',16,55],['SS',36,41],['2B',64,41],['1B',84,55],['P',50,61],['C',50,86]];
    return `<div class="coach-field"><div class="coach-field-arc"></div><div class="coach-field-infield"></div>${spots.map(([pos,left,top]) => fieldSpot(pos, defense, left, top)).join('')}</div><div class="coach-field-help">Reference view only. Use Defense Now to move players.</div>`;
  }

  function refreshDefense(force = false) {
    const host = $('coach-current-defense');
    if (!host) return;
    const defense = currentDefense();
    const bench = benchNames();
    const signature = JSON.stringify({ defense, bench, defenseView });
    if (!force && signature === lastDefenseSignature) return;
    lastDefenseSignature = signature;
    host.innerHTML = defenseView === 'list' ? listMarkup(defense, bench) : fieldMarkup(defense);
    document.querySelectorAll('[data-coach-defense-view]').forEach(btn => {
      const active = btn.dataset.coachDefenseView === defenseView;
      btn.classList.toggle('btn-dark', active);
      btn.classList.toggle('btn-outline-dark', !active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function setActionContent(button, title, note, className) {
    if (!button) return;
    button.className = `btn w-100 ${className}`;
    button.innerHTML = `<span class="coach-action-title">${esc(title)}</span><span class="coach-action-note">${esc(note)}</span>`;
  }

  function gameContextText() {
    const title = $('coach-game-title')?.textContent?.trim() || '';
    const vsIndex = title.toLowerCase().indexOf(' vs ');
    return vsIndex >= 0 ? title.slice(vsIndex + 1) : title;
  }

  function enhance() {
    const overlay = $('live-game-overlay');
    if (!overlay || overlay.classList.contains('d-none') || enhanced) return;
    addStyles();
    overlay.classList.add('coach-live-polished');

    const inning = $('live-inning-display');
    const pitcherCard = $('live-current-pitcher')?.closest('.card');
    const endGame = $('liveEndGameBtn')?.closest('.d-grid') || $('liveEndGameBtn');
    const changePitcher = $('liveChangePitcherBtn');
    const endInning = $('liveEndInningBtn');
    const undo = $('liveUndoBtn');

    const shell = document.createElement('div');
    shell.className = 'coach-live-shell';
    const formattedMeta = $('coach-game-meta')?.textContent?.replace(/\s+/g, ' ').trim() || '';
    shell.innerHTML = `<div class="coach-live-head"><div><div class="coach-live-kicker">Live Dugout</div><div class="coach-live-context">${esc(gameContextText())}</div><div class="coach-live-subcontext">${esc(formattedMeta)}</div></div><div class="coach-inning-pill"><small>INNING</small><strong id="coach-inning-copy">${esc(inning?.textContent || '1')}</strong></div></div><div id="coach-pitcher-slot"></div><div class="coach-actions" id="coach-action-slot"></div><div class="coach-card"><div class="d-flex align-items-center justify-content-between gap-2"><div><div class="coach-label">Current Defense</div><div class="coach-help">List is quickest for in-game checks</div></div><div class="btn-group coach-view-toggle" role="group" aria-label="Defense view"><button class="btn btn-dark" data-coach-defense-view="list" aria-pressed="true">List</button><button class="btn btn-outline-dark" data-coach-defense-view="field" aria-pressed="false">Field</button></div></div><div id="coach-current-defense" class="mt-2"></div></div><div id="coach-existing-extra"></div>`;
    overlay.appendChild(shell);

    const sync = $('live-sync-status-v2');
    if (sync) {
      sync.classList.add('mb-1');
      shell.querySelector('.coach-live-head > div:first-child')?.prepend(sync);
    }
    if (pitcherCard) {
      pitcherCard.classList.add('coach-card');
      pitcherCard.classList.remove('border-primary');
      pitcherCard.querySelectorAll('i').forEach(icon => icon.remove());
      shell.querySelector('#coach-pitcher-slot')?.appendChild(pitcherCard);
    }

    setActionContent(changePitcher, 'Change Pitcher', 'Mound change', 'coach-action-primary');
    setActionContent(endInning, 'End Inning', 'Load next plan', 'coach-action-end');
    setActionContent(undo, 'Undo', 'Revert last change', 'coach-action-undo');

    const actionSlot = shell.querySelector('#coach-action-slot');
    [changePitcher, endInning, undo].filter(Boolean).forEach(btn => actionSlot?.appendChild(btn));

    const extra = shell.querySelector('#coach-existing-extra');
    const upNext = $('live-up-next-v2');
    if (upNext) extra?.appendChild(upNext);
    if (endGame) {
      const endButton = $('liveEndGameBtn');
      if (endButton) {
        endButton.classList.remove('btn-outline-danger');
        endButton.classList.add('btn-link','text-danger','text-decoration-none','px-0','small');
        endButton.innerHTML = 'End Game & Enter Final Pitch Counts';
      }
      extra?.appendChild(endGame);
    }

    $('rotation-board')?.classList.add('coach-live-board-hidden');
    if ($('rotation-editor-title')) $('rotation-editor-title').textContent = 'Live Dugout';
    shell.addEventListener('click', event => {
      const view = event.target.closest('[data-coach-defense-view]');
      if (!view) return;
      defenseView = view.dataset.coachDefenseView;
      refreshDefense(true);
    });
    enhanced = true;
    refreshDefense(true);
  }

  function polishLiveModals() {
    document.querySelectorAll('#live-defense-v2 .list-group-item').forEach(item => {
      if (item.querySelector('strong')?.textContent?.trim() !== 'P') return;
      if (!item.hasAttribute('disabled')) item.setAttribute('disabled','disabled');
      item.classList.add('opacity-50');
      item.title = 'Use Change Pitcher to replace the pitcher.';
    });
    document.querySelectorAll('#live-defense-destination-v2 [data-destination="P"]').forEach(btn => {
      if (!btn.hasAttribute('disabled')) btn.setAttribute('disabled','disabled');
      btn.classList.add('opacity-50');
      if (!btn.querySelector('.coach-use-pitcher-note')) {
        btn.insertAdjacentHTML('beforeend','<div class="small coach-use-pitcher-note">Use Change Pitcher</div>');
      }
    });
    document.querySelectorAll('#live-pitcher-picker-v2 .pitcher-choice-v2').forEach(btn => {
      if (!/Pitch Count Incomplete|Eligibility unknown/i.test(btn.textContent || '')) return;
      if (!btn.hasAttribute('disabled')) btn.setAttribute('disabled','disabled');
      btn.classList.add('opacity-50');
    });
  }

  function keepExistingExtrasInShell() {
    const extra = $('coach-existing-extra');
    if (!extra) return;
    const upNext = $('live-up-next-v2');
    if (upNext && !extra.contains(upNext)) extra.prepend(upNext);
    const endGame = $('liveEndGameBtn')?.closest('.d-grid') || $('liveEndGameBtn');
    if (endGame && !extra.contains(endGame)) extra.appendChild(endGame);
  }

  function tick() {
    const overlay = $('live-game-overlay');
    if (overlay && !overlay.classList.contains('d-none')) {
      enhance();
      if (!enhanced) return;
      const inningCopy = $('coach-inning-copy');
      const inning = $('live-inning-display');
      if (inningCopy && inning && inningCopy.textContent !== inning.textContent) {
        inningCopy.textContent = inning.textContent;
      }
      keepExistingExtrasInShell();
      refreshDefense();
      polishLiveModals();
      return;
    }

    if (enhanced) {
      $('rotation-board')?.classList.remove('coach-live-board-hidden');
      if ($('rotation-editor-title') && $('rotation-editor-title').textContent !== 'Defensive Rotation') {
        $('rotation-editor-title').textContent = 'Defensive Rotation';
      }
    }
  }

  function queueTick() {
    if (tickQueued) return;
    tickQueued = true;
    window.requestAnimationFrame(() => {
      tickQueued = false;
      tick();
    });
  }

  function startObservers() {
    const overlay = $('live-game-overlay');
    if (overlay) {
      const lifecycleObserver = new MutationObserver(queueTick);
      lifecycleObserver.observe(overlay, {attributes:true, attributeFilter:['class']});

      const overlayContentObserver = new MutationObserver(queueTick);
      overlayContentObserver.observe(overlay, {childList:true, subtree:true, characterData:true});
    }

    const rotationBoard = $('rotation-board');
    if (rotationBoard) {
      const defenseObserver = new MutationObserver(() => {
        lastDefenseSignature = '';
        queueTick();
      });
      defenseObserver.observe(rotationBoard, {childList:true, subtree:true});
    }

    const modalObserver = new MutationObserver(mutations => {
      const relevant = mutations.some(mutation => {
        const target = mutation.target.nodeType === 1 ? mutation.target : mutation.target.parentElement;
        if (target?.closest?.('#live-pitcher-picker-v2, #live-defense-v2, #live-defense-destination-v2, #live-pitcher-destination-v2')) return true;
        return [...mutation.addedNodes].some(node => node.nodeType === 1 && (
          node.matches?.('#live-pitcher-picker-v2, #live-defense-v2, #live-defense-destination-v2, #live-pitcher-destination-v2') ||
          node.querySelector?.('#live-pitcher-picker-v2, #live-defense-v2, #live-defense-destination-v2, #live-pitcher-destination-v2')
        ));
      });
      if (relevant) queueTick();
    });
    modalObserver.observe(document.body, {childList:true, subtree:true});

    window.addEventListener('resize', queueTick, {passive:true});
    window.addEventListener('orientationchange', queueTick, {passive:true});
    document.addEventListener('shown.bs.modal', queueTick);
    document.addEventListener('coachboard:next-defense-set', queueTick);
  }

  document.addEventListener('DOMContentLoaded', () => {
    addStyles();
    formatGameHeader();
    startObservers();
    tick();
  });
})();
