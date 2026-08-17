(() => {
  'use strict';

  document.body.classList.add('cb-ui');

  const path = window.location.pathname;
  if (path === '/') document.body.classList.add('cb-home');
  if (path === '/pitching') document.body.classList.add('cb-pitching');
  if (path === '/admin/settings') document.body.classList.add('cb-settings');
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
    rotations: ['Defensive Templates', 'Manage one-inning defense presets and full-game rotation templates.'],
    stats: ['Team Stats', 'Review actual playing history and season-level usage.'],
    scouting_list: ['Scouting', 'Track prospects, committed players, and roster possibilities.'],
    collaboration: ['Coach Notes', 'Keep team and player notes shared among the coaching staff.'],
    games: ['Schedule', 'Add, review, and manage scheduled games. Game Day remains the fastest game-day view.'],
  };

  function addHomeIntros() {
    if (path !== '/') return;
    Object.entries(HOME_SECTIONS).forEach(([id, [title, subtitle]]) => {
      const pane = document.getElementById(id);
      if (!pane || pane.querySelector(':scope > .cb-tab-intro')) return;
      const intro = document.createElement('div');
      intro.className = 'cb-tab-intro';
      intro.innerHTML = `<div><div class="cb-kicker">CoachBoard</div><h1>${title}</h1><p>${subtitle}</p></div>`;
      pane.prepend(intro);
    });
  }

  function settingsHeader() {
    if (!document.body.classList.contains('cb-settings')) return;
    const head = document.querySelector('main > .container-fluid.mt-4 > .d-flex:first-child');
    const title = head?.querySelector('h1');
    if (!head || !title || head.querySelector('.cb-settings-kicker')) return;
    title.textContent = 'Team Settings';
    const wrap = document.createElement('div');
    wrap.className = 'cb-settings-title-wrap';
    const kicker = document.createElement('div');
    kicker.className = 'cb-kicker cb-settings-kicker';
    kicker.textContent = 'CoachBoard';
    title.parentNode.insertBefore(wrap, title);
    wrap.append(kicker, title);
    const back = head.querySelector('a.btn');
    if (back) back.innerHTML = '<i class="bi bi-arrow-left me-1"></i>Back to CoachBoard';
  }

  function markDesktopNav() {
    document.querySelectorAll('.coach-primary-nav [data-cb-section]').forEach((link) => {
      link.classList.remove('active');
      const section = link.dataset.cbSection;
      if (section === 'game-day' && path === '/game-day') link.classList.add('active');
      if (section === 'pitching' && path === '/pitching') link.classList.add('active');
      if (path === '/' && window.location.hash.replace('#', '') === section) link.classList.add('active');
    });
  }

  function applyHomeHash() {
    if (path !== '/') return;
    const target = window.location.hash || '#roster';
    const link = document.querySelector(`a[data-bs-toggle="tab"][href="${target}"]`);
    if (link && typeof bootstrap !== 'undefined') bootstrap.Tab.getOrCreateInstance(link).show();
    markDesktopNav();
  }

  function init() {
    addHomeIntros();
    settingsHeader();
    markDesktopNav();
    window.setTimeout(applyHomeHash, 0);
  }

  window.addEventListener('hashchange', applyHomeHash);
  document.addEventListener('shown.bs.tab', markDesktopNav);

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
