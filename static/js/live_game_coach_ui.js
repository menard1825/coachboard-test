(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  const $ = id => document.getElementById(id);
  let enhanced = false;
  let tickQueued = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function addStyles() {
    if ($('coach-live-polish-styles')) return;
    const style = document.createElement('style');
    style.id = 'coach-live-polish-styles';
    style.textContent = `
      .coach-game-header{gap:14px;align-items:flex-start!important;padding:2px 0 8px}
      .coach-game-header h3{font-size:clamp(1.55rem,4.2vw,2rem);line-height:1.12;letter-spacing:-.02em}
      .coach-game-meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin-top:7px;color:#667085!important;font-size:.94rem}
      .coach-game-meta .meta-divider{color:#c2c8d0}.coach-game-meta .meta-location{flex-basis:auto}
      .coach-game-header-actions{display:flex;gap:6px;flex-shrink:0}.coach-game-header-actions .btn{border-radius:9px;font-weight:650}
      #live-game-overlay.coach-live-polished{background:#f5f6f8!important;padding:10px!important}
      #live-game-overlay.coach-live-polished>:not(.coach-live-shell):not(.modal){display:none!important}
      .coach-live-shell{max-width:980px;margin:0 auto}
      .coach-live-head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:10px}
      .coach-live-kicker{font-size:.68rem;color:#667085;text-transform:uppercase;letter-spacing:.11em;font-weight:800}
      .coach-live-context{margin-top:2px;color:#344054;font-size:.9rem;font-weight:650}
      .coach-live-subcontext{color:#8a94a3;font-size:.76rem;margin-top:1px}
      .coach-inning-pill{background:#172033;color:#fff;border-radius:10px;min-width:74px;padding:8px 10px;text-align:center;box-shadow:0 1px 2px rgba(16,24,40,.12)}
      .coach-inning-pill small{display:block;font-size:.58rem;opacity:.7;font-weight:750;letter-spacing:.1em}.coach-inning-pill strong{display:block;font-size:1.45rem;line-height:1.05;margin-top:2px}
      .coach-card{background:#fff;border:1px solid #e4e7ec;border-radius:13px;box-shadow:0 1px 3px rgba(16,24,40,.06);padding:12px;margin-bottom:10px}
      .coach-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
      .coach-actions .btn{min-height:58px;border-radius:11px!important;padding:8px 10px;box-shadow:none!important;text-align:left;display:flex!important;flex-direction:column;justify-content:center;align-items:flex-start!important;line-height:1.1}
      .coach-actions .btn i{display:none!important}.coach-action-title{display:block;font-weight:780;font-size:.94rem}.coach-action-note{display:block;margin-top:4px;font-size:.67rem;font-weight:550;opacity:.68}
      .coach-action-primary{background:var(--primary-color,#102a66)!important;border-color:var(--primary-color,#102a66)!important;color:#fff!important}.coach-action-end{background:#202733!important;border-color:#202733!important;color:#fff!important}.coach-action-undo{background:#fff!important;border:1px solid #d6dae1!important;color:#5f6b7a!important}
      #rotation-board.coach-live-board-hidden{display:none!important}
      @media(max-width:575.98px){.coach-game-header{display:block!important}.coach-game-header-actions{margin-top:10px}.coach-game-header-actions .btn{flex:1}.coach-game-meta .meta-location{flex-basis:100%}#live-game-overlay.coach-live-polished{padding:8px!important}.coach-card{border-radius:12px;padding:11px}}
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
          dateLabel = new Intl.DateTimeFormat('en-US', {weekday:'short', month:'short', day:'numeric'}).format(localDate);
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
    shell.innerHTML = `<div class="coach-live-head"><div><div class="coach-live-kicker">Live Dugout</div><div class="coach-live-context">${esc(gameContextText())}</div><div class="coach-live-subcontext">${esc(formattedMeta)}</div></div><div class="coach-inning-pill"><small>INNING</small><strong id="coach-inning-copy">${esc(inning?.textContent || '1')}</strong></div></div><div id="coach-pitcher-slot"></div><div class="coach-actions" id="coach-action-slot"></div><div id="coach-existing-extra"></div>`;
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
    [changePitcher, endInning, undo].filter(Boolean).forEach(button => actionSlot?.appendChild(button));

    const extra = shell.querySelector('#coach-existing-extra');
    const upNext = $('live-up-next-v2');
    if (upNext) extra?.appendChild(upNext);
    if (endGame) {
      const endButton = $('liveEndGameBtn');
      if (endButton) {
        endButton.classList.remove('btn-outline-danger');
        endButton.classList.add('btn-link', 'text-danger', 'text-decoration-none', 'px-0', 'small');
        endButton.innerHTML = 'End Game & Enter Final Pitch Counts';
      }
      extra?.appendChild(endGame);
    }

    $('rotation-board')?.classList.add('coach-live-board-hidden');
    if ($('rotation-editor-title')) $('rotation-editor-title').textContent = 'Live Dugout';
    enhanced = true;
  }

  function polishPitcherPicker() {
    document.querySelectorAll('#live-pitcher-picker-v2 .pitcher-choice-v2').forEach(button => {
      if (!/Pitch Count Incomplete|Eligibility unknown/i.test(button.textContent || '')) return;
      if (!button.hasAttribute('disabled')) button.setAttribute('disabled', 'disabled');
      button.classList.add('opacity-50');
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
      if (inningCopy && inning && inningCopy.textContent !== inning.textContent) inningCopy.textContent = inning.textContent;
      keepExistingExtrasInShell();
      polishPitcherPicker();
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
      const contentObserver = new MutationObserver(queueTick);
      contentObserver.observe(overlay, {childList:true, subtree:true, characterData:true});
    }
    const modalObserver = new MutationObserver(queueTick);
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