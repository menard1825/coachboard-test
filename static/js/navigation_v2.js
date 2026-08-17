(() => {
  'use strict';

  const ownScript = document.currentScript;
  let helperQuery = '';
  try {
    helperQuery = ownScript?.src ? new URL(ownScript.src, window.location.href).search : '';
  } catch (_) {
    helperQuery = '';
  }

  function mobileItem(href, icon, label, active = false, isTab = false) {
    return `<li class="nav-item flex-fill"><a class="nav-link text-center ${active ? 'active' : ''}" ${isTab ? 'data-bs-toggle="tab" role="tab"' : ''} href="${href}"><i class="bi bi-${icon} d-block"></i><span>${label}</span></a></li>`;
  }

  function versionedHelperSrc(src) {
    if (!helperQuery || src.includes('?')) return src;
    return `${src}${helperQuery}`;
  }

  function loadScript(src, key) {
    if (document.querySelector(`script[data-coach-helper="${key}"]`)) return;
    const script = document.createElement('script');
    script.src = versionedHelperSrc(src);
    script.dataset.coachHelper = key;
    document.head.appendChild(script);
  }

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

    document.querySelectorAll('a[href="#pitching"]').forEach((link) => {
      link.removeAttribute('data-bs-toggle');
      link.removeAttribute('role');
      link.setAttribute('href', '/pitching');
      const label = link.querySelector('span');
      if (label && /pitching/i.test(label.textContent || '')) label.textContent = 'Pitching';
      if (!label && /pitching log/i.test(link.textContent || '')) {
        link.childNodes.forEach(node => {
          if (node.nodeType === Node.TEXT_NODE && /pitching log/i.test(node.textContent || '')) node.textContent = ' Pitching';
        });
      }
    });

    loadScript('/static/js/season_management_v2.js', 'season-management');
    loadScript('/static/js/roster_pitching_traits.js', 'roster-pitching-traits');
    loadScript('/static/js/touch_reorder_guard.js', 'touch-reorder-guard');
    loadScript('/static/js/stats_dashboard_style.js', 'stats-dashboard-style');
    loadScript('/static/js/stats_dashboard_render.js', 'stats-dashboard-render');
    loadScript('/static/js/stats_dashboard_v2.js', 'stats-dashboard-v2');
  }

  if (window.location.pathname === '/game-day') {
    loadScript('/static/js/game_day_actions.js', 'game-day-actions');
    loadScript('/static/js/game_day_pitching_rules.js', 'game-day-pitching-rules');
  }

  if (/^\/game\/\d+\/?$/.test(window.location.pathname)) {
    loadScript('/static/js/game_management_visual_polish.js', 'game-management-visual-polish');
    loadScript('/static/js/game_management_team_theme_availability.js', 'game-management-team-theme-availability');
    loadScript('/static/js/pregame_defense_picker_clarity.js', 'pregame-defense-picker-clarity');
    loadScript('/static/js/game_management_coach_simplify.js', 'game-management-coach-simplify');
    loadScript('/static/js/game_prep_readiness.js', 'game-readiness');
    loadScript('/static/js/game_pitching_rule_picker.js', 'game-pitching-rules');
    loadScript('/static/js/live_game_sync_status.js', 'live-sync');
  }

  document.querySelectorAll('a[href="#games"] span, a[href="#games"], [data-nav-games]').forEach((el) => {
    if (el.childElementCount === 0 && el.textContent.trim() === 'Games') el.textContent = 'Schedule';
  });
})();