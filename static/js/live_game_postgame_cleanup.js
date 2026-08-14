(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  let seenLive = false;
  let reloading = false;
  let checking = false;

  async function checkState() {
    if (checking || reloading) return;
    checking = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/state`, {cache:'no-store'});
      if (!response.ok) return;
      const state = await response.json();
      const isLive = Boolean(state?.game?.is_live);
      if (isLive) {
        seenLive = true;
        return;
      }
      if (seenLive) {
        reloading = true;
        // Rebuild Game Management from the saved planned rotation instead of
        // leaving the legacy planner in a stale live-state DOM.
        window.location.reload();
      }
    } catch (_) {
      // The main Live Game controller owns user-facing sync errors.
    } finally {
      checking = false;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    checkState();
    setInterval(checkState, 1000);
  });

  document.addEventListener('click', event => {
    if (event.target.closest('#confirmFinalCountsBtn')) {
      seenLive = true;
      setTimeout(checkState, 200);
      setTimeout(checkState, 600);
    }
  }, true);
})();
