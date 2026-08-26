(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  function installStyles() {
    if (document.getElementById('cb-live-connection-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-live-connection-styles';
    style.textContent = `
      #live-sync-status-v2.cb-command-sync{display:block!important;text-align:left!important;margin:5px 0 0!important;line-height:1!important}
      #live-sync-status-v2.cb-command-sync .badge{font-size:.55rem!important;padding:4px 7px!important;letter-spacing:.02em}
      body.cb-dugout #live-sync-status-v2.cb-command-sync{margin:0 0 7px!important;padding:0 2px!important}
      @media(max-width:575.98px){#live-sync-status-v2.cb-command-sync .badge{font-size:.52rem!important;padding:4px 6px!important}}
    `;
    document.head.appendChild(style);
  }

  function placeStatus() {
    const status = document.getElementById('live-sync-status-v2');
    const shell = document.querySelector('.coach-live-shell');
    if (!status || !shell) return;

    status.classList.add('cb-command-sync');

    // Dugout mode hides .coach-live-head, so keep the real sync badge on the
    // visible live surface instead of placing it inside that legacy header.
    const dugoutHeader = shell.querySelector('#cbDugoutHeader');
    if (document.body.classList.contains('cb-dugout') && dugoutHeader) {
      if (status.previousElementSibling !== dugoutHeader || status.parentElement !== shell) {
        dugoutHeader.insertAdjacentElement('afterend', status);
      }
      return;
    }

    const head = shell.querySelector('.coach-live-head');
    const context = head?.firstElementChild;
    if (!context) return;
    if (status.parentElement !== context) context.appendChild(status);
  }

  installStyles();
  const observer = new MutationObserver(() => window.requestAnimationFrame(placeStatus));
  observer.observe(document.body, {childList:true, subtree:true, attributes:true, attributeFilter:['class']});
  placeStatus();
})();
