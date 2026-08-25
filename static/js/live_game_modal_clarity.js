(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;
  if (window.CoachBoardLiveModalClarity?.initialized) return;

  function nextInning() {
    return (
      document.querySelector('#live-board-prep-v3 .nxd-inning strong')?.textContent?.trim() ||
      document.querySelector('#live-board-prep-v3 .bp-inning strong')?.textContent?.trim() ||
      ''
    );
  }

  function clarifyNextDefenseModal(modal) {
    if (!modal || modal.id !== 'next-inning-adjust-modal') return;
    const inning = nextInning();
    if (!inning) return;

    const title = modal.querySelector('.modal-title');
    if (title) title.textContent = `Set Defense — Inning ${inning}`;

    const subtitle = title?.parentElement?.querySelector('.small.text-muted');
    if (subtitle) subtitle.textContent = `Choose who takes the field for Inning ${inning}.`;

    const save = modal.querySelector('#save-next-inning-adjust');
    if (save && !save.disabled && !/^Saving/i.test(save.textContent || '')) {
      save.textContent = `Set Inning ${inning} Defense`;
    }
  }

  document.addEventListener('show.bs.modal', event => {
    clarifyNextDefenseModal(event.target);
  });

  // Bootstrap warns when aria-hidden is applied while a control inside the
  // closing modal still owns focus. Release focus before any game modal hides.
  document.addEventListener('hide.bs.modal', event => {
    const modal = event.target;
    const active = document.activeElement;
    if (modal?.contains?.(active) && typeof active.blur === 'function') active.blur();
  });

  // The next-defense editor replaces its footer while coaches tap players.
  // Keep the inning-specific button copy after those rerenders too.
  const observer = new MutationObserver(mutations => {
    if (!mutations.some(mutation => mutation.addedNodes.length || mutation.removedNodes.length)) return;
    const modal = document.getElementById('next-inning-adjust-modal');
    if (modal?.classList.contains('show')) clarifyNextDefenseModal(modal);
  });
  observer.observe(document.body, {childList:true, subtree:true});

  window.CoachBoardLiveModalClarity = {initialized:true, clarifyNextDefenseModal};
})();