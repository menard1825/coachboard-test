(() => {
  'use strict';

  document.body.classList.add('cb-ui');

  const path = window.location.pathname;
  // main.js historically defaulted an un-hashed visit to Roster. Capture the
  // user's original destination before DOMContentLoaded so the newer Home
  // experience can make the final landing decision without breaking explicit
  // deep links such as /#roster or /#practice_plan.
  const initialHomeRequested = path === '/' && !window.location.hash;

  if (path === '/') document.body.classList.add('cb-home');
  if (path === '/pitching') document.body.classList.add('cb-pitching');
  if (path === '/rules') document.body.classList.add('cb-rules');
  if (path === '/admin/settings') document.body.classList.add('cb-settings', 'cb-admin');
  if (path.startsWith('/admin/')) document.body.classList.add('cb-admin');
  if (path === '/game-day') document.body.classList.add('cb-game-day');
  if (/^\/game\/\d+\/?$/.test(path)) document.body.classList.add('cb-game-management');
  if (/^\/game-day\/\d+\/report\/?$/.test(path)) document.body.classList.add('cb-game-report');
  if (/^\/rotation-template\//.test(path)) document.body.classList.add('cb-rotation-template');

  const HOME_SECTIONS = {
    overview: ['Home', 'Your coaching command center for the next game, arm care, practice, and items that need attention.'],
    roster: ['Roster', 'Manage player information, positions, notes, and persistent pitching traits.'],
    player_development: ['Player Development', 'Keep each player’s coaching focus, progress, and notes in one place.'],
    practice_plan: ['Practice', 'Build, reuse, and adjust practice plans without starting from scratch.'],
    lineups: ['Lineup Templates', 'Create reusable batting orders that can be loaded into any game.'],
    rotations: ['Defensive Templates', 'Manage Starting Defense templates and full-game rotation templates.'],
    stats: ['Team Stats', 'Review actual playing history and season-level usage.'],
    scouting_list: ['Scouting', 'Track prospects, committed players, and roster possibilities.'],
    collaboration: ['Coach Notes', 'Keep team and player notes shared among the coaching staff.'],
    games: ['Schedule', 'Add, review, and manage scheduled games. Game Day remains the fastest game-day view.'],
  };

  function useNeutralFaviconWhenTeamHasNoLogo() {
    if (document.querySelector('.navbar-logo')) return;
    const favicon = document.querySelector('link[rel~="icon"]');
    if (!favicon) return;
    favicon.type = 'image/svg+xml';
    favicon.href = '/static/coachboard-icon.svg?v=1';
  }

  function ensureHomeNavigation() {
    const role = document.body.dataset.coachRole || '';
    const primary = document.querySelector('.coach-primary-nav');
    if (role !== 'Game Changer' && primary && !primary.querySelector('[data-cb-section="overview"]')) {
      const home = document.createElement('a');
      home.className = 'cb-nav-link';
      home.dataset.cbSection = 'overview';
      home.href = '/#overview';
      home.innerHTML = '<i class="bi bi-house-door"></i>Home';
      primary.prepend(home);
    }

    if (path !== '/') return;
    const desktopTab = document.querySelector('a[data-bs-toggle="tab"][href="#overview"]');
    if (desktopTab) {
      desktopTab.innerHTML = '<i class="bi bi-house-door me-1"></i>Home';
      desktopTab.setAttribute('aria-label', 'Home');
      const item = desktopTab.closest('li');
      const list = item?.parentElement;
      if (item && list && list.firstElementChild !== item) list.prepend(item);
    }
  }

  function addHomeIntros() {
    if (path !== '/') return;
    Object.entries(HOME_SECTIONS).forEach(([id, [title, subtitle]]) => {
      if (id === 'overview') return;
      const pane = document.getElementById(id);
      if (!pane || pane.querySelector(':scope > .cb-tab-intro') || pane.querySelector(':scope > .cb-page-head')) return;
      const intro = document.createElement('div');
      intro.className = 'cb-tab-intro';
      intro.innerHTML = `<div><div class="cb-kicker">CoachBoard</div><h1>${title}</h1><p>${subtitle}</p></div>`;
      pane.prepend(intro);
    });

    const rosterHeader = document.querySelector('#roster > .card > .card-header h5');
    if (rosterHeader && rosterHeader.textContent.trim() === 'Current Roster') rosterHeader.textContent = 'Players';
  }

  function modernizeLegacyAdminHeader() {
    if (!document.body.classList.contains('cb-admin')) return;
    const root = document.querySelector('main > .container-fluid.mt-4');
    if (!root) return;
    root.classList.add('cb-legacy-admin-shell');
    const head = root.querySelector(':scope > .d-flex:first-child');
    const title = head?.querySelector('h1');
    if (!head || !title || head.querySelector('.cb-admin-kicker')) return;

    if (path === '/admin/settings') title.textContent = 'Team Settings';
    const wrap = document.createElement('div');
    wrap.className = 'cb-admin-title-wrap';
    const kicker = document.createElement('div');
    kicker.className = 'cb-kicker cb-admin-kicker';
    kicker.textContent = 'CoachBoard';
    title.parentNode.insertBefore(wrap, title);
    wrap.append(kicker, title);

    const back = head.querySelector('a.btn');
    if (back) back.innerHTML = '<i class="bi bi-arrow-left me-1"></i>Back to CoachBoard';
  }

  function enhancePitchingStructure() {
    if (!document.body.classList.contains('cb-pitching')) return;
    const root = document.querySelector('main > .container-fluid.pb-4');
    if (!root) return;
    root.classList.add('cb-pitching-shell');
    const head = root.querySelector(':scope > .d-flex:first-child');
    if (head) head.classList.add('cb-pitching-head');
    const firstTable = root.querySelector('.card table');
    if (firstTable) firstTable.classList.add('cb-pitcher-status-table');
  }

  function markSimpleEmptyStates() {
    document.querySelectorAll('main .text-center.text-muted').forEach((el) => {
      const text = (el.textContent || '').trim();
      if (/^(No |Select a player|Nothing )/i.test(text) && !el.closest('table')) {
        el.classList.add('cb-empty-state');
      }
    });
  }

  function markDesktopNav() {
    const activePane = document.querySelector('#mainTabContent > .tab-pane.active');
    const activeHomeSection = activePane?.id || window.location.hash.replace('#', '') || 'overview';
    const gameArea = path === '/game-day' || /^\/game\/\d+\/?$/.test(path) || /^\/game-day\/\d+\/report\/?$/.test(path);
    document.querySelectorAll('.coach-primary-nav [data-cb-section]').forEach((link) => {
      link.classList.remove('active');
      const section = link.dataset.cbSection;
      if (section === 'game-day' && gameArea) link.classList.add('active');
      if (section === 'pitching' && path === '/pitching') link.classList.add('active');
      if (path === '/' && activeHomeSection === section) link.classList.add('active');
    });
  }

  function showHomePane({cleanUrl = false} = {}) {
    if (path !== '/' || typeof bootstrap === 'undefined') return;
    const link = document.querySelector('#mainTabsDesktop a[data-bs-toggle="tab"][href="#overview"]')
      || document.querySelector('a[data-bs-toggle="tab"][href="#overview"]');
    const pane = document.getElementById('overview');
    if (!link || !pane) return;

    if (!pane.classList.contains('active')) {
      bootstrap.Tab.getOrCreateInstance(link).show();
    }
    if (cleanUrl) {
      history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    }
    markDesktopNav();
  }

  function applyHomeHash() {
    if (path !== '/') return;
    if (initialHomeRequested && !document.documentElement.dataset.cbInitialHomeApplied) {
      document.documentElement.dataset.cbInitialHomeApplied = 'true';
      showHomePane({cleanUrl: true});
      return;
    }

    const target = window.location.hash || '#overview';
    const pane = document.querySelector(target);
    const link = document.querySelector(`#mainTabsDesktop a[data-bs-toggle="tab"][href="${target}"]`)
      || document.querySelector(`a[data-bs-toggle="tab"][href="${target}"]`);
    if (link && pane && !pane.classList.contains('active') && typeof bootstrap !== 'undefined') {
      bootstrap.Tab.getOrCreateInstance(link).show();
    }
    markDesktopNav();
  }

  function loadFairPlayEnhancement() {
    const shouldLoad = path === '/admin/settings' || /^\/game\/\d+\/?$/.test(path);
    if (!shouldLoad || document.querySelector('script[data-cb-fair-play]')) return;

    const script = document.createElement('script');
    script.src = '/static/js/fair_play_assistant.js?v=20260819-1';
    script.dataset.cbFairPlay = 'true';
    document.body.appendChild(script);
  }

  function loadPitchingPreferences() {
    const shouldLoad = path === '/admin/settings' || path === '/pitching';
    if (!shouldLoad || document.querySelector('script[data-cb-pitching-preferences]')) return;

    const script = document.createElement('script');
    script.src = '/static/js/pitching_preferences.js?v=20260820-1';
    script.dataset.cbPitchingPreferences = 'true';
    document.body.appendChild(script);
  }

  function loadHomeDashboard() {
    if (path !== '/') return;

    if (!document.querySelector('link[data-cb-home-dashboard]')) {
      const style = document.createElement('link');
      style.rel = 'stylesheet';
      style.href = '/static/css/home_dashboard.css?v=20260820-2';
      style.dataset.cbHomeDashboard = 'true';
      document.head.appendChild(style);
    }

    if (!document.querySelector('script[data-cb-home-dashboard]')) {
      const script = document.createElement('script');
      script.src = '/static/js/home_dashboard.js?v=20260820-2';
      script.dataset.cbHomeDashboard = 'true';
      document.body.appendChild(script);
    }
  }

  function init() {
    useNeutralFaviconWhenTeamHasNoLogo();
    ensureHomeNavigation();
    addHomeIntros();
    modernizeLegacyAdminHeader();
    enhancePitchingStructure();
    markSimpleEmptyStates();
    markDesktopNav();
    loadFairPlayEnhancement();
    loadPitchingPreferences();
    loadHomeDashboard();
    // main.js finishes its legacy tab bootstrap in the same DOMContentLoaded
    // turn. Run after it so Home becomes the final, stable default.
    window.setTimeout(applyHomeHash, 0);
  }

  window.addEventListener('hashchange', applyHomeHash);
  document.addEventListener('shown.bs.tab', () => {
    markDesktopNav();
    markSimpleEmptyStates();
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
