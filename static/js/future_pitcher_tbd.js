(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  const PANEL_ID = 'pregame-defense-editor-v3';
  const STYLE_ID = 'future-pitcher-tbd-styles';
  let queued = false;

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${PANEL_ID} .pde-spot.pitcher-tbd {
        background:#fff8e8!important;
        border-color:#e7c46b!important;
      }
      #${PANEL_ID} .pde-spot.pitcher-tbd .pde-name {
        color:#7a4b00!important;
      }
      #${PANEL_ID} .pde-pitcher-tbd-note {
        margin:8px 0 0;
        padding:7px 9px;
        border:1px solid #efd8ac;
        border-radius:8px;
        background:#fffaf0;
        color:#7a4b00;
        font-size:.68rem;
        font-weight:700;
        text-align:center;
      }
    `;
    document.head.appendChild(style);
  }

  function currentInning() {
    const checked = document.querySelector('#inning-btn-group input[name="inning-radio"]:checked');
    if (checked?.value) return checked.value;
    const strong = document.querySelector(`#${PANEL_ID} .pde-inning strong`);
    return strong?.textContent?.trim() || '1';
  }

  function futurePitcherMayBeTbd() {
    const value = Number.parseFloat(currentInning());
    return Number.isFinite(value) && value > 1;
  }

  function patchPregamePitcher() {
    installStyles();
    const panel = document.getElementById(PANEL_ID);
    if (!panel) return;

    const pitcher = panel.querySelector('[data-pde-pos="P"]');
    const name = pitcher?.querySelector('.pde-name');
    const noteId = 'pde-pitcher-tbd-note';
    let note = document.getElementById(noteId);

    if (!futurePitcherMayBeTbd()) {
      note?.remove();
      return;
    }

    const pitcherBlank = Boolean(
      pitcher &&
      (!name?.textContent?.trim() || /^(OPEN|PITCHER TBD)$/i.test(name.textContent.trim()))
    );

    if (!pitcherBlank) {
      note?.remove();
      return;
    }

    pitcher.classList.remove('open');
    pitcher.classList.add('pitcher-tbd');
    if (name && name.textContent !== 'PITCHER TBD') name.textContent = 'PITCHER TBD';
    if (pitcher.title !== 'Optional before the game. Choose the actual pitcher during Live Game.') {
      pitcher.title = 'Optional before the game. Choose the actual pitcher during Live Game.';
    }

    const status = panel.querySelector('.pde-status');
    const open = status?.querySelector('.open');
    if (open) {
      const spots = open.textContent
        .replace(/^Open:\s*/i, '')
        .split(',')
        .map(value => value.trim())
        .filter(Boolean)
        .filter(value => value !== 'P');

      if (spots.length) {
        const desired = `Open: ${spots.join(', ')}`;
        if (open.textContent !== desired) open.textContent = desired;
      } else if (status) {
        const desired = '<strong>Defense complete</strong> <span class="mx-1">•</span> Changes save automatically';
        if (status.innerHTML !== desired) status.innerHTML = desired;
      }
    }

    if (!note) {
      note = document.createElement('div');
      note.id = noteId;
      note.className = 'pde-pitcher-tbd-note';
      const status = panel.querySelector('.pde-status');
      if (status) status.insertAdjacentElement('afterend', note);
      else panel.querySelector('.pde-body')?.appendChild(note);
    }
    const noteHtml = '<i class="bi bi-info-circle me-1"></i>Future-inning pitcher is optional. Leave P as TBD and choose the actual pitcher during Live Game.';
    if (note.innerHTML !== noteHtml) note.innerHTML = noteHtml;
  }

  function queuePatch() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      patchPregamePitcher();
    });
  }

  function start() {
    patchPregamePitcher();
    const observer = new MutationObserver(queuePatch);
    observer.observe(document.body, {childList:true, subtree:true, characterData:true});
    document.addEventListener('change', event => {
      if (event.target?.matches?.('#inning-btn-group input[name="inning-radio"]')) queuePatch();
    });
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once:true})
    : start();
})();
