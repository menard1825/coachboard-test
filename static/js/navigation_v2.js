(() => {
  'use strict';

  function mobileItem(href, icon, label, active = false, isTab = false) {
    return `<li class="nav-item flex-fill"><a class="nav-link text-center ${active ? 'active' : ''}" ${isTab ? 'data-bs-toggle="tab" role="tab"' : ''} href="${href}"><i class="bi bi-${icon} d-block"></i><span>${label}</span></a></li>`;
  }

  function loadScript(src, key) {
    if (document.querySelector(`script[data-coach-helper="${key}"]`)) return;
    const script = document.createElement('script');
    script.src = src;
    script.dataset.coachHelper = key;
    document.head.appendChild(script);
  }

  // Run immediately at the bottom of <body> so main.js sees the final links when
  // DOMContentLoaded fires and attaches its tab behavior.
  if (window.location.pathname === '/') {
    const nav = document.querySelector('nav.bottom-nav-fixed ul');
    if (nav) {
      nav.innerHTML = [
        mobileItem('/game-day', 'diamond', 'Game Day'),
        mobileItem('#roster', 'people', 'Roster', false, true),
        mobileItem('#player_development', 'graph-up-arrow', 'Development', false, true),
        mobileItem('#practice_plan', 'clipboard-check', 'Practice', false, true),
        mobileItem('#more', 'three-dots', 'More', false, true),
      ].join('');
    }
  }

  // Every game page gets the same readiness calculation as Game Day and a tiny
  // connection indicator while Live Game is active.
  if (/^\/game\/\d+\/?$/.test(window.location.pathname)) {
    loadScript('/static/js/game_prep_readiness.js', 'game-readiness');
    loadScript('/static/js/live_game_sync_status.js', 'live-sync');
  }

  // Normalize old visible wording anywhere it still says Games.
  document.querySelectorAll('a[href="#games"] span, a[href="#games"], [data-nav-games]').forEach((el) => {
    if (el.childElementCount === 0 && el.textContent.trim() === 'Games') el.textContent = 'Schedule';
  });
})();
