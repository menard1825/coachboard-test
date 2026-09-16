(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  let placementQueued = false;

  function installStyles() {
    if (document.getElementById('cb-live-connection-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-live-connection-styles';
    style.textContent = `
      #live-sync-status-v2.cb-command-sync{display:block!important;text-align:left!important;margin:5px 0 0!important;line-height:1!important}
      #live-sync-status-v2.cb-command-sync .badge{font-size:.55rem!important;padding:4px 7px!important;letter-spacing:.02em}
      @media(max-width:575.98px){#live-sync-status-v2.cb-command-sync .badge{font-size:.52rem!important;padding:4px 6px!important}}
      /* Dugout Mode shows connection health in #cbDugoutHeader instead. The
         badge stays in the DOM because live_game_v2 writes the authoritative
         state into it and the header reads it back, but it must not render a
         second status row of its own. */
      body.cb-dugout #live-sync-status-v2{display:none!important}
    `;
    document.head.appendChild(style);
  }

  function placeStatus() {
    const status = document.getElementById('live-sync-status-v2');
    const shell = document.querySelector('.coach-live-shell');
    if (!status || !shell) return;

    status.classList.add('cb-command-sync');

    // Dugout Mode presents connection health in #cbDugoutHeader, which reads
    // this element's text. Placing it here as well produced a second visible
    // status row directly beneath that header, so the badge is left where it
    // is and hidden by CSS rather than relocated.
    if (document.body.classList.contains('cb-dugout')) return;

    const head = shell.querySelector('.coach-live-head');
    const context = head?.firstElementChild;
    if (!context) return;
    if (status.parentElement !== context) context.appendChild(status);
  }

  function queuePlacement() {
    if (placementQueued) return;
    placementQueued = true;
    window.requestAnimationFrame(() => {
      placementQueued = false;
      placeStatus();
    });
  }

  installStyles();

  // Only two things can affect placement: the live overlay being rebuilt and
  // entering/leaving dugout mode on the body. The shell is appended directly
  // to the overlay, so watching the overlay's own children is enough --
  // subtree:true additionally fired on every clock tick and board re-render
  // for a placement that could not have changed.
  const liveOverlay = document.getElementById('live-game-overlay');
  if (liveOverlay) {
    const overlayObserver = new MutationObserver(queuePlacement);
    overlayObserver.observe(liveOverlay, {childList:true});
  }

  const bodyObserver = new MutationObserver(queuePlacement);
  bodyObserver.observe(document.body, {attributes:true, attributeFilter:['class']});
  placeStatus();
})();