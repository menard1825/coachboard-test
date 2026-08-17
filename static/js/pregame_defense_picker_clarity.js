(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  const STYLE_ID = 'pregame-defense-picker-clarity-styles';

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #pde-player-modal .pde-picker-section-label{
        padding:9px 14px 6px;
        background:#f8fafc;
        border-top:1px solid #eaecf0;
        border-bottom:1px solid #eef1f4;
        color:#667085;
        font-size:.62rem;
        font-weight:850;
        letter-spacing:.08em;
        text-transform:uppercase;
      }
      #pde-player-modal .pde-picker-section-label:first-child{border-top:0}
      #pde-player-modal .pde-bench-choice small{color:#176b38!important;font-weight:650}
      #pde-player-modal .pde-field-move-toggle{
        width:calc(100% - 24px);
        margin:12px;
        min-height:44px;
        border-radius:10px;
        font-weight:750;
      }
      #pde-player-modal .pde-field-move-wrap{
        border-top:1px solid #eef1f4;
        background:#fbfcfd;
      }
      #pde-player-modal .pde-field-choice{background:#fbfcfd}
      #pde-player-modal .pde-field-choice small{color:#8b5c00!important}
      #pde-player-modal .pde-picker-empty{
        padding:15px 14px;
        color:#667085;
        font-size:.78rem;
        background:#fff;
      }
    `;
    document.head.appendChild(style);
  }

  function sectionLabel(text) {
    const el = document.createElement('div');
    el.className = 'pde-picker-section-label';
    el.textContent = text;
    return el;
  }

  function enhanceList(list) {
    if (!list || list.dataset.pdeClarifying === '1') return;

    const choices = [...list.querySelectorAll(':scope > .pde-choice')];
    if (!choices.length) return;

    list.dataset.pdeClarifying = '1';
    try {
      const clearChoice = choices.find(button => button.dataset.clear);
      const playerChoices = choices.filter(button => button.dataset.player);
      const benchChoices = [];
      const fieldChoices = [];

      playerChoices.forEach(button => {
        const detail = button.querySelector('small')?.textContent?.trim() || '';
        if (/^On bench this inning$/i.test(detail)) {
          button.classList.add('pde-bench-choice');
          benchChoices.push(button);
        } else if (/^Currently at /i.test(detail)) {
          // The player already occupying the target spot does not need to appear
          // as a selectable choice: closing the modal simply keeps him there.
          if (/will become open/i.test(detail)) {
            button.classList.add('pde-field-choice');
            fieldChoices.push(button);
          }
        }
      });

      list.replaceChildren();

      if (clearChoice) list.appendChild(clearChoice);

      list.appendChild(sectionLabel('Available — On Bench'));
      if (benchChoices.length) {
        benchChoices
          .sort((a, b) => (a.dataset.player || '').localeCompare(b.dataset.player || ''))
          .forEach(button => list.appendChild(button));
      } else {
        const empty = document.createElement('div');
        empty.className = 'pde-picker-empty';
        empty.textContent = 'No unassigned players remain this inning.';
        list.appendChild(empty);
      }

      if (fieldChoices.length) {
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'btn btn-outline-secondary pde-field-move-toggle';
        toggle.setAttribute('aria-expanded', 'false');
        toggle.innerHTML = `<i class="bi bi-arrow-left-right me-1"></i>Move someone already on field <span class="badge text-bg-light border ms-1">${fieldChoices.length}</span>`;

        const wrap = document.createElement('div');
        wrap.className = 'pde-field-move-wrap d-none';
        wrap.appendChild(sectionLabel('Already On Field — Moving Opens Old Spot'));
        fieldChoices
          .sort((a, b) => (a.dataset.player || '').localeCompare(b.dataset.player || ''))
          .forEach(button => wrap.appendChild(button));

        toggle.addEventListener('click', () => {
          const opening = wrap.classList.contains('d-none');
          wrap.classList.toggle('d-none', !opening);
          toggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
          toggle.innerHTML = opening
            ? '<i class="bi bi-chevron-up me-1"></i>Hide on-field players'
            : `<i class="bi bi-arrow-left-right me-1"></i>Move someone already on field <span class="badge text-bg-light border ms-1">${fieldChoices.length}</span>`;
        });

        list.appendChild(toggle);
        list.appendChild(wrap);
      }

      const help = document.getElementById('pde-help');
      if (help) {
        const hasOccupant = Boolean(clearChoice);
        help.textContent = hasOccupant
          ? 'Choose a player from the bench. To move someone already on the field, use the option below.'
          : 'Choose from players still available on the bench. On-field players are hidden unless you choose to move one.';
      }
    } finally {
      // Leave this marker in place until the base picker replaces innerHTML on
      // the next position tap. The observer removes it when that happens.
    }
  }

  function watchPicker() {
    const observer = new MutationObserver(mutations => {
      for (const mutation of mutations) {
        const list = mutation.target.closest?.('#pde-list') ||
          [...mutation.addedNodes].find(node => node.nodeType === 1 && (node.id === 'pde-list' || node.querySelector?.('#pde-list')))?.querySelector?.('#pde-list') ||
          document.getElementById('pde-list');
        if (!list) continue;

        // A fresh render from live_game_board_prep.js replaces the list's
        // children. Reset our marker only when raw direct choices are back.
        if ([...list.children].some(child => child.classList?.contains('pde-choice')) &&
            !list.querySelector('.pde-picker-section-label')) {
          delete list.dataset.pdeClarifying;
        }
        enhanceList(list);
        break;
      }
    });

    observer.observe(document.body, {childList:true, subtree:true});
    enhanceList(document.getElementById('pde-list'));
  }

  installStyles();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watchPicker, {once:true});
  } else {
    watchPicker();
  }
})();
