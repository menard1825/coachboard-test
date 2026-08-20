(() => {
  'use strict';

  document.body.classList.add('cb-ui');

  const path = window.location.pathname;
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
    overview: ['Overview', 'Season snapshot and the items that need a coach’s attention.'],
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

  function addHomeIntros() {
    if (path !== '/') return;
    Object.entries(HOME_SECTIONS).forEach(([id, [title, subtitle]]) => {
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
    const activeHomeSection = window.location.hash.replace('#', '') || 'roster';
    const gameArea = path === '/game-day' || /^\/game\/\d+\/?$/.test(path) || /^\/game-day\/\d+\/report\/?$/.test(path);
    document.querySelectorAll('.coach-primary-nav [data-cb-section]').forEach((link) => {
      link.classList.remove('active');
      const section = link.dataset.cbSection;
      if (section === 'game-day' && gameArea) link.classList.add('active');
      if (section === 'pitching' && path === '/pitching') link.classList.add('active');
      if (path === '/' && activeHomeSection === section) link.classList.add('active');
    });
  }

  function applyHomeHash() {
    if (path !== '/') return;
    const target = window.location.hash || '#roster';
    const link = document.querySelector(`a[data-bs-toggle="tab"][href="${target}"]`);
    if (link && typeof bootstrap !== 'undefined') bootstrap.Tab.getOrCreateInstance(link).show();
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

  function init() {
    useNeutralFaviconWhenTeamHasNoLogo();
    addHomeIntros();
    modernizeLegacyAdminHeader();
    enhancePitchingStructure();
    markSimpleEmptyStates();
    markDesktopNav();
    loadFairPlayEnhancement();
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
