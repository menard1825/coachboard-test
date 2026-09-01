(() => {
  'use strict';

  const ownScript = document.currentScript;
  let helperQuery = '';
  try {
    helperQuery = ownScript?.src ? new URL(ownScript.src, window.location.href).search : '';
  } catch (_) {
    helperQuery = '';
  }

  function installDesktopRosterBootGuard() {
    if (
      window.location.pathname !== '/' ||
      window.location.hash.toLowerCase() !== '#roster' ||
      !window.matchMedia('(min-width: 992px)').matches
    ) return;

    const root = document.documentElement;
    const main = document.querySelector('main.container-fluid');
    const roster = document.getElementById('roster-cards-container');
    if (!main || !roster) return;

    root.classList.add('cb-desktop-workspace-boot');
    main.dataset.cbWorkspaceLoading = 'Loading Roster…';

    if (!document.getElementById('cb-desktop-workspace-boot-styles')) {
      const style = document.createElement('style');
      style.id = 'cb-desktop-workspace-boot-styles';
      style.textContent = `
        @media(min-width:992px){
          html.cb-desktop-workspace-boot body.cb-ui main.container-fluid{position:relative;min-height:240px}
          html.cb-desktop-workspace-boot body.cb-ui #mainTabContent{visibility:hidden!important;opacity:0!important;pointer-events:none!important}
          html.cb-desktop-workspace-boot body.cb-ui main.container-fluid::before{
            content:attr(data-cb-workspace-loading);
            position:absolute;
            z-index:3;
            top:58px;
            left:50%;
            transform:translateX(-50%);
            width:min(560px,calc(100% - 48px));
            padding:18px 20px;
            border:1px solid #dfe5ec;
            border-radius:14px;
            background:#fff;
            box-shadow:0 2px 9px rgba(16,24,40,.055);
            color:#667085;
            font-size:.8rem;
            font-weight:700;
            text-align:center;
          }
        }
      `;
      document.head.appendChild(style);
    }

    let observer = null;
    const finish = () => {
      const currentRoster = document.getElementById('roster-cards-container');
      const error = document.querySelector('#mainTabContent > .alert-danger, main > .alert-danger');
      const rosterReady = currentRoster && !currentRoster.querySelector('.spinner-border') && currentRoster.children.length > 0;
      if (!rosterReady && !error) return false;
      observer?.disconnect();
      observer = null;
      root.classList.remove('cb-desktop-workspace-boot');
      delete main.dataset.cbWorkspaceLoading;
      return true;
    };

    if (finish()) return;
    observer = new MutationObserver(finish);
    observer.observe(document.getElementById('mainTabContent') || main, {subtree: true, childList: true});

    window.setTimeout(() => {
      if (!root.classList.contains('cb-desktop-workspace-boot')) return;
      observer?.disconnect();
      observer = null;
      root.classList.remove('cb-desktop-workspace-boot');
      delete main.dataset.cbWorkspaceLoading;
    }, 10000);
  }

  function mobileItem(href, icon, label, active = false, isWorkspace = false) {
    const workspaceAttr = isWorkspace ? ' data-cb-workspace-link="true"' : '';
    const currentAttr = active ? ' aria-current="page"' : '';
    return `<li class="nav-item flex-fill"><a class="nav-link text-center ${active ? 'active' : ''}"${workspaceAttr}${currentAttr} href="${href}"><i class="bi bi-${icon} d-block"></i><span>${label}</span></a></li>`;
  }

  function versionedHelperSrc(src) {
    if (!helperQuery || src.includes('?')) return src;
    return `${src}${helperQuery}`;
  }

  function loadScript(src, key) {
    if (document.querySelector(`script[data-coach-helper="${key}"]`)) return;
    const script = document.createElement('script');
    script.async = false;
    script.src = versionedHelperSrc(src);
    script.dataset.coachHelper = key;
    document.head.appendChild(script);
  }

  function normalizeHomeEntry() {
    if (window.location.pathname !== '/' || window.location.hash) return;
    if (window.history?.replaceState) window.history.replaceState(null, '', '#overview');
    else window.location.hash = '#overview';
  }

  function redirectLegacySchedule() {
    if (
      window.location.pathname === '/' &&
      window.location.hash.toLowerCase() === '#games'
    ) {
      window.location.replace('/game-day');
      return true;
    }
    return false;
  }

  function installMobileNavigationStyles() {
    if (document.getElementById('cb-mobile-navigation-v2-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-mobile-navigation-v2-styles';
    style.textContent = `
      #more .cb-mobile-more-shell{max-width:720px;margin:0 auto;padding:2px 0 84px}
      #more .cb-mobile-more-head{margin:0 0 12px}
      #more .cb-mobile-more-head h2{font-size:1.25rem;font-weight:850;color:#172033;margin:2px 0 3px}
      #more .cb-mobile-more-head p{font-size:.76rem;color:#667085;margin:0}
      #more .cb-mobile-more-card{border:1px solid #e2e6eb;border-radius:14px;background:#fff;overflow:hidden;box-shadow:0 1px 3px rgba(16,24,40,.05)}
      #more .cb-mobile-more-link{display:grid;grid-template-columns:38px minmax(0,1fr) 20px;gap:10px;align-items:center;padding:12px 13px;border:0;border-bottom:1px solid #edf0f3;text-decoration:none;color:#1d2939;background:#fff}
      #more .cb-mobile-more-link:last-child{border-bottom:0}
      #more .cb-mobile-more-icon{width:36px;height:36px;border-radius:9px;background:#f1f4f8;color:var(--primary-color,#102a66);display:flex;align-items:center;justify-content:center;font-size:1rem}
      #more .cb-mobile-more-copy strong{display:block;font-size:.79rem;font-weight:800;color:#1d2939}
      #more .cb-mobile-more-copy small{display:block;font-size:.65rem;color:#7b8492;margin-top:1px;line-height:1.2}
      #more .cb-mobile-more-arrow{color:#98a2b3;font-size:.8rem;text-align:right}
      #userOffcanvas .cb-account-context{padding:3px 16px 10px;color:#667085;font-size:.72rem;border-bottom:1px solid #eef1f4;margin-bottom:4px}
      #userOffcanvas .list-group-item{min-height:44px;display:flex;align-items:center}
      #userOffcanvas h6{font-size:.64rem;text-transform:uppercase;letter-spacing:.08em;font-weight:850;color:#667085!important;margin-top:12px!important}
      @media(max-width:991.98px){
        html{scroll-padding-top:70px}
        body[data-coachboard-authenticated="1"]{--cb-mobile-topbar-height:58px;padding-top:var(--cb-mobile-topbar-height)!important}
        body[data-coachboard-authenticated="1"]>nav.navbar.sticky-top{position:fixed!important;top:0;left:0;right:0;width:100%;height:var(--cb-mobile-topbar-height);min-height:var(--cb-mobile-topbar-height);max-height:var(--cb-mobile-topbar-height);z-index:1040;margin:0!important;padding:.35rem 0!important;overflow:hidden}
        body[data-coachboard-authenticated="1"]>nav.navbar.sticky-top>.container-fluid{height:100%;min-height:0;flex-wrap:nowrap}
        body[data-coachboard-authenticated="1"]>nav.navbar.sticky-top .navbar-brand{min-width:0;max-width:calc(100% - 46px);margin-right:0;overflow:hidden}
        body[data-coachboard-authenticated="1"]>nav.navbar.sticky-top .navbar-logo{height:34px!important;width:auto;max-width:44px;flex:0 0 auto;margin-right:8px!important;object-fit:contain}
        body[data-coachboard-authenticated="1"]>nav.navbar.sticky-top .navbar-brand-text{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.96rem!important;line-height:1.1}
        body[data-coachboard-authenticated="1"]>nav.navbar.sticky-top .navbar-nav{flex:0 0 38px;justify-content:flex-end}
        body[data-coachboard-authenticated="1"]>nav.navbar.sticky-top .nav-item.d-lg-none .nav-link{display:flex;align-items:center;justify-content:center;height:44px;width:38px;padding:0}
        body[data-coachboard-authenticated="1"] main.container-fluid{margin-top:0!important;padding-top:12px}
        body.cb-home #mainTabContent>.tab-pane.fade{transition:none!important}
        .bottom-nav-fixed .nav-link{touch-action:manipulation;-webkit-tap-highlight-color:transparent}
      }
      @media(min-width:992px){#more .cb-mobile-more-shell{padding-bottom:0}}
    `;
    document.head.appendChild(style);
  }

  function cleanAccountDrawer() {
    const drawer = document.getElementById('userOffcanvas');
    if (!drawer || drawer.dataset.cbNavigationCleaned === '1') return;
    drawer.dataset.cbNavigationCleaned = '1';

    const title = drawer.querySelector('.offcanvas-title');
    if (title) title.textContent = 'Account & Team';

    const list = drawer.querySelector('.list-group');
    if (!list) return;

    // Primary navigation owns the frequently used coaching workspaces. Remove
    // any legacy second copy from the account drawer.
    const coachHeading = [...list.querySelectorAll('h6')]
      .find((heading) => heading.textContent.trim() === 'CoachBoard');
    if (coachHeading) {
      let node = coachHeading;
      while (node) {
        const next = node.nextElementSibling;
        const isDivider = node.matches?.('hr');
        node.remove();
        if (isDivider) break;
        node = next;
      }
    }

    const accountHeading = [...list.querySelectorAll('h6')]
      .find((heading) => heading.textContent.trim() === 'Account');
    if (accountHeading) accountHeading.textContent = 'Account';

    [...list.querySelectorAll('a')].forEach((link) => {
      const text = link.textContent.replace(/\s+/g, ' ').trim();
      if (/^Change Password$/i.test(text)) {
        link.innerHTML = '<i class="bi bi-shield-lock me-2"></i>Account Security';
      }
      if (/^Logout$/i.test(text)) {
        link.innerHTML = '<i class="bi bi-box-arrow-right me-2"></i>Log Out';
      }
    });

    const context = document.createElement('div');
    context.className = 'cb-account-context';
    context.innerHTML = '<i class="bi bi-info-circle me-1"></i>Team, account, and admin controls';
    list.before(context);
  }

  function moreLink(href, icon, title, description, isWorkspace = true) {
    const workspaceAttr = isWorkspace ? ' data-cb-workspace-link="true"' : '';
    return `<a class="cb-mobile-more-link" href="${href}"${workspaceAttr}>
      <span class="cb-mobile-more-icon"><i class="bi bi-${icon}"></i></span>
      <span class="cb-mobile-more-copy"><strong>${title}</strong><small>${description}</small></span>
      <span class="cb-mobile-more-arrow"><i class="bi bi-chevron-right"></i></span>
    </a>`;
  }

  function renderMobileMore() {
    const pane = document.getElementById('more');
    if (!pane || pane.dataset.cbNavigationCleaned === '1') return;
    pane.dataset.cbNavigationCleaned = '1';
    pane.innerHTML = `
      <div class="cb-mobile-more-shell">
        <div class="cb-mobile-more-head">
          <div class="cb-kicker">CoachBoard</div>
          <h2>More</h2>
          <p>Planning, records, and coaching tools that do not need to live in the bottom bar.</p>
        </div>
        <div class="cb-mobile-more-card">
          ${moreLink('#practice_plan', 'clipboard-check', 'Practice', 'Build, reuse, and run practice plans.')}
          ${moreLink('#player_development', 'graph-up-arrow', 'Development', 'Player priorities, progress, and coaching focus.')}
          ${moreLink('#lineups', 'card-list', 'Lineup Templates', 'Reusable batting orders for Game Day.')}
          ${moreLink('#rotations', 'diagram-3', 'Defensive Templates', 'First-pitch defense and full-game rotations.')}
          ${moreLink('#stats', 'bar-chart', 'Stats', 'Actual season usage and playing history.')}
          ${moreLink('#scouting_list', 'binoculars', 'Scouting', 'Track prospects and roster possibilities.')}
          ${moreLink('#collaboration', 'chat-left-text', 'Coach Notes', 'Shared team and player notes.')}
          ${moreLink('#signs', 'hand-index-thumb', 'Sign Set', 'Keep the team sign set easy to find.')}
        </div>
      </div>`;
  }

  function renameAccountSecurityLinks() {
    document.querySelectorAll('a').forEach((link) => {
      const text = link.textContent.replace(/\s+/g, ' ').trim();
      if (/^Change Password$/i.test(text)) {
        const icon = link.querySelector('i');
        if (icon) icon.className = 'bi bi-shield-lock me-2';
        const textNodes = [...link.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE);
        if (textNodes.length) textNodes[textNodes.length - 1].textContent = ' Account Security';
        else if (!icon) link.textContent = 'Account Security';
      }
    });
  }

  function sharedMobileNav() {
    return document.getElementById('cb-global-mobile-nav');
  }

  function normalizeSharedMobileNav() {
    const nav = sharedMobileNav();
    if (!nav) return;
    const gameDay = nav.querySelector('[data-cb-mobile-section="game-day"]');
    if (gameDay) gameDay.setAttribute('href', '/game-day');
    const pitching = nav.querySelector('[data-cb-mobile-section="pitching"]');
    if (pitching) pitching.setAttribute('href', '/pitching');
    if (window.location.pathname !== '/') {
      const home = nav.querySelector('[data-cb-mobile-section="overview"]');
      if (home) home.setAttribute('href', '/');
    }
  }

  function protectSharedMobileNavActiveState() {
    const nav = sharedMobileNav();
    if (!nav || nav.dataset.cbActiveStateProtected === '1') return;
    nav.dataset.cbActiveStateProtected = '1';

    const enforce = () => {
      nav.querySelectorAll('[data-cb-mobile-section]').forEach((link) => {
        const current = link.getAttribute('aria-current') === 'page';
        link.classList.toggle('active', current);
      });
    };

    const select = (selected) => {
      nav.querySelectorAll('[data-cb-mobile-section]').forEach((link) => {
        if (link === selected) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });
      enforce();
    };

    nav.addEventListener('click', (event) => {
      const link = event.target.closest('[data-cb-mobile-section]');
      if (!link || !nav.contains(link)) return;
      const href = link.getAttribute('href') || '';
      if (!href.startsWith('#')) return;
      select(link);
      window.requestAnimationFrame(enforce);
    });

    const observer = new MutationObserver(enforce);
    observer.observe(nav, {subtree: true, attributes: true, attributeFilter: ['class', 'aria-current']});
    enforce();
  }

  function keepPrimaryMobileWorkspaceAtTop() {
    const nav = sharedMobileNav();
    if (!nav || nav.dataset.cbScrollStabilized === '1') return;
    nav.dataset.cbScrollStabilized = '1';

    const reset = () => window.scrollTo({top: 0, left: 0, behavior: 'auto'});
    nav.addEventListener('click', (event) => {
      const link = event.target.closest('[data-cb-mobile-section]');
      if (!link) return;
      const href = link.getAttribute('href') || '';
      if (href.startsWith('#')) {
        window.requestAnimationFrame(() => window.requestAnimationFrame(reset));
      }
    });

    if (window.location.pathname === '/' && ['#overview', '#roster', '#more'].includes(window.location.hash || '#overview')) {
      window.requestAnimationFrame(() => window.requestAnimationFrame(reset));
    }
  }

  function installHomeBottomNav() {
    if (sharedMobileNav()) return;
    const nav = document.querySelector('nav.bottom-nav-fixed ul');
    if (!nav) return;
    const target = window.location.hash || '#overview';
    const moreActive = !['#overview', '#roster'].includes(target);
    nav.innerHTML = [
      mobileItem('#overview', 'house-door', 'Home', target === '#overview', true),
      mobileItem('/game-day', 'diamond', 'Game Day'),
      mobileItem('#roster', 'people', 'Roster', target === '#roster', true),
      mobileItem('/pitching', 'bullseye', 'Pitching'),
      mobileItem('#more', 'three-dots', 'More', moreActive, true),
    ].join('');
  }

  function installGameDayBottomNav() {
    if (sharedMobileNav()) return;
    const nav = document.querySelector('nav.bottom-nav-fixed ul');
    if (!nav) return;
    nav.innerHTML = [
      mobileItem('/', 'house-door', 'Home'),
      mobileItem('/game-day', 'diamond', 'Game Day', true),
      mobileItem('/#roster', 'people', 'Roster'),
      mobileItem('/pitching', 'bullseye', 'Pitching'),
      mobileItem('/#more', 'three-dots', 'More'),
    ].join('');
  }

  installDesktopRosterBootGuard();
  normalizeHomeEntry();
  window.addEventListener('hashchange', redirectLegacySchedule);
  if (redirectLegacySchedule()) return;

  installMobileNavigationStyles();
  cleanAccountDrawer();
  renameAccountSecurityLinks();
  normalizeSharedMobileNav();
  protectSharedMobileNavActiveState();
  keepPrimaryMobileWorkspaceAtTop();

  if (window.location.pathname === '/') {
    installHomeBottomNav();
    renderMobileMore();

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
    loadScript('/static/js/stats_dashboard_integrity.js', 'stats-dashboard-integrity');
    loadScript('/static/js/stats_dashboard_v2.js', 'stats-dashboard-v2');
  }

  if (window.location.pathname === '/game-day') {
    installGameDayBottomNav();
    loadScript('/static/js/game_day_actions.js', 'game-day-actions');
    loadScript('/static/js/game_day_pitching_rules.js', 'game-day-pitching-rules');
  }

  if (window.location.pathname === '/admin/users') {
    loadScript('/static/js/user_management_password_help.js', 'user-management-password-help');
    loadScript('/static/js/user_management_cleanup.js', 'user-management-cleanup');
  }

  if (/^\/game\/\d+\/?$/.test(window.location.pathname)) {
    loadScript('/static/js/postgame_game_management_cleanup.js', 'postgame-game-management-cleanup');
    loadScript('/static/js/live_game_board_prep.js', 'pregame-defense-editor');
    loadScript('/static/js/game_management_visual_polish.js', 'game-management-visual-polish');
    loadScript('/static/js/game_management_team_theme_availability.js', 'game-management-team-theme-availability');
    loadScript('/static/js/pregame_defense_picker_clarity.js', 'pregame-defense-picker-clarity');
    loadScript('/static/js/game_management_coach_simplify.js', 'game-management-coach-simplify');
    loadScript('/static/js/future_pitcher_tbd.js', 'future-pitcher-tbd');
    loadScript('/static/js/game_pitching_rule_picker.js', 'game-pitching-rules');
    loadScript('/static/js/live_game_sync_status.js', 'live-sync');
    loadScript('/static/js/live_game_clock.js', 'live-game-clock');
    loadScript('/static/js/assignment_picker_availability.js', 'assignment-picker-availability');
  }

  if (/^\/(?:rotation-template|starting-defense-template)\/(?:new|\d+)\/?$/.test(window.location.pathname)) {
    loadScript('/static/js/assignment_picker_availability.js', 'assignment-picker-availability');
  }

  document.querySelectorAll('a[href="#games"]').forEach((link) => {
    link.removeAttribute('data-bs-toggle');
    link.removeAttribute('role');
    link.setAttribute('href', '/game-day');
    const label = link.querySelector('span');
    if (label && /games|schedule|game day/i.test(label.textContent || '')) label.textContent = 'Game Day';
    else if (!label && /games|schedule/i.test(link.textContent || '')) link.textContent = 'Game Day';
  });
})();