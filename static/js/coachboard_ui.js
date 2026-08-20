(() => {
  'use strict';

  document.body.classList.add('cb-ui');

  const path = window.location.pathname;
  const initialHomeRequested = path === '/' && !window.location.hash;
  let initialHomeObserver = null;
  let mobileTabObserver = null;

  // main.js still owns the legacy workspace tabs and historically defaults an
  // un-hashed visit to Roster after its async data load. Seed the intended Home
  // hash before DOMContentLoaded so that legacy initialization selects Home
  // instead. The hash is cleaned again once Home is actually active.
  if (initialHomeRequested) {
    history.replaceState(null, '', `${window.location.pathname}${window.location.search}#overview`);
  }

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

  function syncMobileNav(target) {
    document.querySelectorAll('nav.bottom-nav-fixed a[href^="#"]').forEach((link) => {
      link.classList.toggle('active', link.getAttribute('href') === target);
    });
  }

  function activatePaneWithoutTrigger(pane) {
    const root = document.getElementById('mainTabContent');
    if (!root || !pane) return;
    root.querySelectorAll(':scope > .tab-pane').forEach((item) => {
      item.classList.remove('active', 'show');
    });
    pane.classList.add('active', 'show');
  }

  function showHashPane(target = window.location.hash || '#overview') {
    if (path !== '/') return false;
    if (!/^#[A-Za-z0-9_-]+$/.test(target)) return false;
    const pane = document.querySelector(target);
    if (!pane) return false;

    const link = document.querySelector(`#mainTabsDesktop a[data-bs-toggle="tab"][href="${target}"]`)
      || document.querySelector(`a[data-bs-toggle="tab"][href="${target}"]`);

    if (link && typeof bootstrap !== 'undefined') {
      if (!pane.classList.contains('active')) bootstrap.Tab.getOrCreateInstance(link).show();
    } else {
      // More is a mobile-only pane and has no desktop Bootstrap trigger. Keep
      // it in the same canonical tab state as every other workspace pane.
      activatePaneWithoutTrigger(pane);
    }

    syncMobileNav(target);
    markDesktopNav();
    return true;
  }

  function settleInitialHome() {
    if (!initialHomeRequested || path !== '/') return;
    const root = document.getElementById('mainTabContent');
    const pane = document.getElementById('overview');
    if (!root || !pane) return;

    const finish = () => {
      if (!pane.classList.contains('active')) return false;
      document.documentElement.dataset.cbInitialHomeApplied = 'true';
      history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
      initialHomeObserver?.disconnect();
      initialHomeObserver = null;
      syncMobileNav('#overview');
      markDesktopNav();
      return true;
    };

    if (finish()) return;
    initialHomeObserver = new MutationObserver(() => finish());
    initialHomeObserver.observe(root, {subtree: true, attributes: true, attributeFilter: ['class']});

    // If a slow API response prevents the legacy initializer from reaching its
    // tab step, keep Home usable rather than leaving the workspace blank.
    window.setTimeout(() => {
      if (!document.documentElement.dataset.cbInitialHomeApplied) {
        showHashPane('#overview');
        finish();
      }
    }, 15000);
  }

  function applyHomeHash() {
    if (path !== '/') return;
    showHashPane(window.location.hash || '#overview');
  }

  function makeMobileTabsHashDriven() {
    if (path !== '/') return;

    const normalize = () => {
      document.querySelectorAll('nav.bottom-nav-fixed a[data-bs-toggle="tab"][href^="#"], #more a[data-bs-toggle="tab"][href^="#"]').forEach((link) => {
        // main.js installs its own click handler on data-bs-toggle=tab links.
        // Bootstrap also has a delegated handler for the same click. On the
        // rebuilt mobile nav that double handling can leave a pane with .show
        // but without .active. Mobile workspace links only need to change the
        // hash; applyHomeHash then performs one canonical tab switch.
        link.removeAttribute('data-bs-toggle');
        link.removeAttribute('role');
      });
    };

    normalize();
    const root = document.body;
    mobileTabObserver?.disconnect();
    mobileTabObserver = new MutationObserver(normalize);
    mobileTabObserver.observe(root, {subtree: true, childList: true});
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
    makeMobileTabsHashDriven();
    loadFairPlayEnhancement();
    loadPitchingPreferences();
    loadHomeDashboard();

    if (initialHomeRequested) settleInitialHome();
    else window.setTimeout(applyHomeHash, 0);
  }

  window.addEventListener('hashchange', applyHomeHash);
  document.addEventListener('shown.bs.tab', () => {
    markDesktopNav();
    markSimpleEmptyStates();
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
