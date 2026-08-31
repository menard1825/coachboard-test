(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  function selectPlayerWhenEditorOpens(name) {
    let timeoutId = null;
    const onShown = event => {
      if (event.target?.id !== 'cb-live-field-editor') return;
      document.removeEventListener('shown.bs.modal', onShown);
      if (timeoutId) window.clearTimeout(timeoutId);
      window.requestAnimationFrame(() => {
        const player = [...document.querySelectorAll('#cb-live-field-editor [data-cb-editor-player]')]
          .find(button => button.dataset.cbEditorPlayer === name);
        player?.click();
      });
    };

    document.addEventListener('shown.bs.modal', onShown);
    timeoutId = window.setTimeout(() => {
      document.removeEventListener('shown.bs.modal', onShown);
    }, 5000);
  }

  document.addEventListener('click', event => {
    const fielder = event.target.closest?.(
      '#cbQuickDefense [data-cb-move-player][data-cb-position]'
    );
    if (!fielder || fielder.disabled) return;

    const position = String(fielder.dataset.cbPosition || '').toUpperCase();
    if (!position || position === 'P') return;

    const defenseButton = document.getElementById('liveDefensiveChangeBtn');
    if (!defenseButton || defenseButton.disabled) return;

    const name = fielder.dataset.cbMovePlayer;
    if (!name || name === 'Open') return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    selectPlayerWhenEditorOpens(name);
    defenseButton.click();
  }, true);
})();
