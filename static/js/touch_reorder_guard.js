(() => {
  'use strict';

  if (window.location.pathname !== '/') return;

  function loadMobileGameDayFields() {
    if (!window.matchMedia('(max-width: 991.98px)').matches) return;
    if (document.querySelector('script[data-cb-mobile-game-day-fields]')) return;
    const script = document.createElement('script');
    script.src = '/static/js/mobile_game_day_fields.js?v=20260822-1';
    script.dataset.cbMobileGameDayFields = 'true';
    document.head.appendChild(script);
  }

  loadMobileGameDayFields();

  const touchDevice = window.matchMedia?.('(pointer: coarse)').matches || Number(navigator.maxTouchPoints || 0) > 0;
  if (!touchDevice) return;

  const configs = [
    {
      id: 'roster-cards-container',
      pane: '#roster',
      label: 'Roster',
      toolbar: () => document.querySelector('#roster > .card > .card-header > .d-flex'),
      header: () => document.querySelector('#roster > .card > .card-header'),
    },
    {
      id: 'dev-player-list',
      pane: '#player_development',
      label: 'Development',
      toolbar: () => document.querySelector('#player_development .card .card-header'),
      header: () => document.querySelector('#player_development .card .card-header'),
    },
  ];

  const states = new Map();
  let attempts = 0;

  function installStyles() {
    if (document.getElementById('touch-reorder-guard-styles')) return;
    const style = document.createElement('style');
    style.id = 'touch-reorder-guard-styles';
    style.textContent = `
      .cb-touch-reorder-toggle{white-space:nowrap;min-height:36px}
      .cb-touch-reorder-toggle.is-active{background:var(--cb-primary,var(--primary-color,#344054))!important;border-color:var(--cb-primary,var(--primary-color,#344054))!important;color:#fff!important}
      .cb-touch-reorder-guide{padding:8px 12px;border-bottom:1px solid #e7ebef;background:#f8fafc;color:#475467;font-size:.7rem;font-weight:650}
      .cb-touch-reorder-guide i{color:var(--cb-primary,var(--primary-color,#344054))}
      .cb-touch-reorder-active{outline:2px solid color-mix(in srgb,var(--cb-primary,var(--primary-color,#344054)) 22%,transparent);outline-offset:2px;border-radius:10px}
      .cb-touch-reorder-active .drag-handle{opacity:1!important;color:var(--cb-primary,var(--primary-color,#344054))!important}
      @media(max-width:575.98px){
        #roster > .card > .card-header > .d-flex{flex-wrap:wrap!important;width:100%}
        .cb-touch-reorder-toggle{font-size:.72rem;padding:.38rem .55rem}
        .cb-touch-reorder-guide{font-size:.67rem}
      }
    `;
    document.head.appendChild(style);
  }

  function sortableFor(element) {
    if (!element || !window.Sortable || typeof window.Sortable.get !== 'function') return null;
    return window.Sortable.get(element);
  }

  function setActive(config, active) {
    const state = states.get(config.id);
    if (!state?.sortable) return;

    state.active = Boolean(active);
    state.sortable.option('disabled', !state.active);
    state.element.classList.toggle('cb-touch-reorder-active', state.active);

    if (state.button) {
      state.button.classList.toggle('is-active', state.active);
      state.button.setAttribute('aria-pressed', state.active ? 'true' : 'false');
      state.button.innerHTML = state.active
        ? '<i class="bi bi-check2 me-1"></i>Done'
        : '<i class="bi bi-arrow-down-up me-1"></i>Reorder';
    }
    if (state.guide) state.guide.hidden = !state.active;
  }

  function addControls(config, element, sortable) {
    if (states.has(config.id)) return true;

    const toolbar = config.toolbar();
    const header = config.header();
    if (!toolbar || !header) return false;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-sm btn-outline-secondary cb-touch-reorder-toggle';
    button.setAttribute('aria-pressed', 'false');
    button.innerHTML = '<i class="bi bi-arrow-down-up me-1"></i>Reorder';
    button.title = `Turn on ${config.label.toLowerCase()} reordering`;

    if (config.id === 'roster-cards-container') {
      toolbar.classList.add('flex-wrap');
      const newPlayer = toolbar.querySelector('[data-bs-target="#addPlayerModal"]');
      if (newPlayer) toolbar.insertBefore(button, newPlayer);
      else toolbar.appendChild(button);
    } else {
      const sortGroup = toolbar.querySelector('.btn-group');
      if (sortGroup) toolbar.insertBefore(button, sortGroup);
      else toolbar.appendChild(button);
    }

    const guide = document.createElement('div');
    guide.className = 'cb-touch-reorder-guide';
    guide.hidden = true;
    guide.innerHTML = '<i class="bi bi-grip-vertical me-1"></i>Reorder mode is on. Drag only from the grip beside a player, then tap <strong>Done</strong>.';
    header.insertAdjacentElement('afterend', guide);

    // Touch devices are intentionally locked by default. Even after a coach
    // enables reorder mode, require a brief hold so a fast swipe remains a
    // scroll gesture rather than immediately becoming a drag.
    sortable.option('delay', 180);
    sortable.option('delayOnTouchOnly', true);
    sortable.option('touchStartThreshold', 8);
    sortable.option('disabled', true);

    states.set(config.id, {element, sortable, button, guide, active:false});
    button.addEventListener('click', () => setActive(config, !states.get(config.id)?.active));
    return true;
  }

  function configure() {
    attempts += 1;
    let complete = true;

    configs.forEach((config) => {
      if (states.has(config.id)) return;
      const element = document.getElementById(config.id);
      const sortable = sortableFor(element);
      if (!element || !sortable || !addControls(config, element, sortable)) complete = false;
    });

    if (!complete && attempts < 60) window.setTimeout(configure, 100);
  }

  function lockOtherLists(activePane) {
    configs.forEach((config) => {
      if (config.pane !== activePane) setActive(config, false);
    });
  }

  function start() {
    installStyles();
    configure();

    document.addEventListener('shown.bs.tab', (event) => {
      const target = event.target?.getAttribute?.('href') || event.target?.dataset?.bsTarget || '';
      if (target) lockOtherLists(target);
    });

    window.addEventListener('pagehide', () => configs.forEach((config) => setActive(config, false)));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
