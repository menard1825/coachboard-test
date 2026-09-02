(() => {
  'use strict';

  document.body.classList.add('cb-ui');

  const path = window.location.pathname;
  const initialHomeRequested = path === '/' && !window.location.hash;
  let initialHomeObserver = null;
  let mobileTabObserver = null;
  let mobileNavigationBound = false;
  const mobileWorkspaceScroll = new Map();

  // main.js historically defaults an un-hashed visit to Roster after its async
  // startup work. Keep #overview in the URL for the initial page lifetime so
  // every legacy startup path agrees that Home is the requested destination.
  // Once the app is running, tapping Home uses the clean root URL normally.
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
    games: ['Game Day', 'Add, review, and manage scheduled games without leaving the primary mobile workspace.'],
  };

  const MOBILE_PRIMARY_TARGETS = new Set(['#overview', '#games', '#roster', '#practice_plan', '#more']);

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

  function activeWorkspaceTarget() {
    const activePane = document.querySelector('#mainTabContent > .tab-pane.active');
    return activePane?.id ? `#${activePane.id}` : (window.location.hash || '#overview');
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
    const navTarget = MOBILE_PRIMARY_TARGETS.has(target) ? target : '#more';
    document.querySelectorAll('nav.bottom-nav-fixed a[href^="#"]').forEach((link) => {
      const active = link.getAttribute('href') === navTarget;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function enforceWorkspacePaneState(pane, target) {
    const root = document.getElementById('mainTabContent');
    if (!root || !pane) return;

    root.querySelectorAll(':scope > .tab-pane').forEach((item) => {
      const active = item === pane;
      item.classList.toggle('active', active);
      item.classList.toggle('show', active);
    });

    document.querySelectorAll('#mainTabsDesktop a[data-bs-toggle="tab"]').forEach((link) => {
      const active = link.getAttribute('href') === target;
      link.classList.toggle('active', active);
      link.setAttribute('aria-selected', active ? 'true' : 'false');
    });
  }

  function showHashPane(target = window.location.hash || '#overview') {
    if (path !== '/') return false;
    if (!/^#[A-Za-z0-9_-]+$/.test(target)) return false;
    const pane = document.querySelector(target);
    if (!pane || pane.parentElement?.id !== 'mainTabContent') return false;

    const link = document.querySelector(`#mainTabsDesktop a[data-bs-toggle="tab"][href="${target}"]`);
    const isMobile = window.matchMedia('(max-width: 991.98px)').matches;

    // Desktop keeps Bootstrap's normal tab lifecycle. Mobile intentionally uses
    // one direct state transition so Bootstrap and legacy main.js cannot both
    // react to the same tap. Enforce the final state either way so the mobile-
    // only More pane can never remain active beside another workspace.
    if (!isMobile && link && typeof bootstrap !== 'undefined' && !pane.classList.contains('active')) {
      bootstrap.Tab.getOrCreateInstance(link).show();
    }
    enforceWorkspacePaneState(pane, target);

    syncMobileNav(target);
    markDesktopNav();
    return true;
  }

  function mainScroller() {
    return document.querySelector('main.container-fluid');
  }

  function rememberWorkspaceScroll(target = activeWorkspaceTarget()) {
    if (!window.matchMedia('(max-width: 991.98px)').matches) return;
    const scroller = mainScroller();
    if (scroller && target) mobileWorkspaceScroll.set(target, scroller.scrollTop);
  }

  function restoreWorkspaceScroll(target) {
    if (!window.matchMedia('(max-width: 991.98px)').matches) return;
    const scroller = mainScroller();
    if (!scroller) return;
    const top = mobileWorkspaceScroll.get(target) || 0;
    requestAnimationFrame(() => requestAnimationFrame(() => scroller.scrollTo({top, behavior: 'auto'})));
  }

  function workspaceUrl(target) {
    const base = `${window.location.pathname}${window.location.search}`;
    return target === '#overview' ? base : `${base}${target}`;
  }

  function navigateWorkspace(target, {push = true} = {}) {
    if (path !== '/' || !/^#[A-Za-z0-9_-]+$/.test(target)) return false;
    const pane = document.querySelector(target);
    if (!pane || pane.parentElement?.id !== 'mainTabContent') return false;

    const previous = activeWorkspaceTarget();
    if (previous === target) {
      enforceWorkspacePaneState(pane, target);
      syncMobileNav(target);
      return true;
    }

    rememberWorkspaceScroll(previous);
    if (!showHashPane(target)) return false;
    if (push) history.pushState({cbWorkspace: target}, '', workspaceUrl(target));
    restoreWorkspaceScroll(target);
    return true;
  }

  function workspaceTargetFromLink(link) {
    if (!link || path !== '/' || !window.matchMedia('(max-width: 991.98px)').matches) return null;
    let url;
    try {
      url = new URL(link.href, window.location.href);
    } catch (_) {
      return null;
    }
    if (url.origin !== window.location.origin || url.pathname !== '/' || !url.hash) return null;
    if (!/^#[A-Za-z0-9_-]+$/.test(url.hash)) return null;
    const pane = document.querySelector(url.hash);
    if (!pane || pane.parentElement?.id !== 'mainTabContent') return null;
    return url.hash;
  }

  function installMobileWorkspaceNavigation() {
    if (path !== '/' || mobileNavigationBound) return;
    mobileNavigationBound = true;

    // main.js and Bootstrap both historically reacted to the same tab click.
    // Own mobile workspace clicks in capture phase so every tap results in one
    // pane change, one history entry, and no browser anchor jump.
    document.addEventListener('click', (event) => {
      const link = event.target.closest('a[href]');
      const target = workspaceTargetFromLink(link);
      if (!target) return;
      event.preventDefault();
      event.stopPropagation();
      navigateWorkspace(target, {push: true});
    }, true);

    window.addEventListener('popstate', () => {
      const target = window.location.hash || '#overview';
      rememberWorkspaceScroll(activeWorkspaceTarget());
      if (showHashPane(target)) restoreWorkspaceScroll(target);
    });
  }

  function settleInitialHome() {
    if (!initialHomeRequested || path !== '/') return;
    const root = document.getElementById('mainTabContent');
    const pane = document.getElementById('overview');
    if (!root || !pane) return;

    const finish = () => {
      if (!pane.classList.contains('active')) return false;
      enforceWorkspacePaneState(pane, '#overview');
      document.documentElement.dataset.cbInitialHomeApplied = 'true';
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
    const target = window.location.hash || '#overview';
    const previous = activeWorkspaceTarget();
    if (previous !== target) rememberWorkspaceScroll(previous);
    if (showHashPane(target) && previous !== target) restoreWorkspaceScroll(target);
  }

  function makeMobileTabsHashDriven() {
    if (path !== '/') return;

    const normalize = () => {
      document.querySelectorAll('nav.bottom-nav-fixed a[data-bs-toggle="tab"][href^="#"], #more a[data-bs-toggle="tab"][href^="#"]').forEach((link) => {
        // The legacy dashboard and Home enhancement can still rebuild these
        // anchors. Strip Bootstrap ownership immediately; the capture-phase
        // workspace navigator above is the single mobile tab owner.
        link.removeAttribute('data-bs-toggle');
        link.removeAttribute('role');
        link.dataset.cbWorkspaceLink = 'true';
      });
      const target = activeWorkspaceTarget();
      const pane = document.querySelector(target);
      if (pane && pane.parentElement?.id === 'mainTabContent') enforceWorkspacePaneState(pane, target);
      syncMobileNav(target);
    };

    normalize();
    mobileTabObserver?.disconnect();
    mobileTabObserver = new MutationObserver(normalize);
    const navRoot = document.querySelector('nav.bottom-nav-fixed ul');
    const moreRoot = document.getElementById('more');
    if (navRoot) mobileTabObserver.observe(navRoot, {subtree: true, childList: true});
    if (moreRoot) mobileTabObserver.observe(moreRoot, {subtree: true, childList: true});
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
    installMobileWorkspaceNavigation();
    makeMobileTabsHashDriven();
    loadFairPlayEnhancement();
    loadPitchingPreferences();
    loadHomeDashboard();

    if (initialHomeRequested) settleInitialHome();
    else window.setTimeout(applyHomeHash, 0);
  }

  window.addEventListener('hashchange', applyHomeHash);
  document.addEventListener('shown.bs.tab', (event) => {
    const target = event.target?.getAttribute?.('href');
    if (path === '/' && target && /^#[A-Za-z0-9_-]+$/.test(target)) syncMobileNav(target);
    markDesktopNav();
    markSimpleEmptyStates();
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
