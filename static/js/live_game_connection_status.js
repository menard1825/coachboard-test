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
      @media(max-width:575.98px){#live-sync-status-v2.cb-command-sync .badge{font-size:.52rem!important;padding:4px 6px!important}}
    `;
    document.head.appendChild(style);
  }

  function placeStatus() {
    const status = document.getElementById('live-sync-status-v2');
    const shell = document.querySelector('.coach-live-shell');
    const head = shell?.querySelector('.coach-live-head');
    if (!status || !head) return;

    const context = head.firstElementChild;
    if (!context) return;

    status.classList.add('cb-command-sync');
    if (status.parentElement !== context) context.appendChild(status);
  }

  installStyles();
  const observer = new MutationObserver(() => window.requestAnimationFrame(placeStatus));
  observer.observe(document.body, {childList:true, subtree:true});
  placeStatus();
})();
