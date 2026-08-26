(() => {
  'use strict';

  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-pitch-step][data-pitch-target]');
    if (!button) return;

    const input = document.getElementById(button.dataset.pitchTarget);
    const delta = Number(button.dataset.pitchStep);
    if (!input || !Number.isFinite(delta)) return;

    const minimum = input.min === '' ? Number.NEGATIVE_INFINITY : Number(input.min);
    const maximum = input.max === '' ? Number.POSITIVE_INFINITY : Number(input.max);
    const current = Number(input.value);
    const startingValue = Number.isFinite(current)
      ? current
      : (Number.isFinite(minimum) ? minimum : 0);
    const next = Math.min(maximum, Math.max(minimum, startingValue + delta));

    input.value = String(next);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  });
})();

(() => {
  'use strict';
  if (!/^\/game\/\d+\/?$/.test(window.location.pathname)) return;

  function loadOnce(src, datasetKey) {
    if (document.querySelector(`script[data-${datasetKey}]`)) return;
    const script = document.createElement('script');
    script.src = src;
    script.setAttribute(`data-${datasetKey}`, '1');
    document.head.appendChild(script);
  }

  function ensureDefenseAction() {
    const slot = document.querySelector('.coach-live-shell #coach-action-slot');
    if (!slot || document.getElementById('liveDefensiveChangeBtn')) return;

    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'liveDefensiveChangeBtn';
    button.className = 'btn';
    button.innerHTML = '<span class="coach-action-title">Defense Change</span><span class="coach-action-note">Move field / bench</span>';
    slot.prepend(button);
  }

  window.addEventListener('load', () => {
    loadOnce('/static/js/live_game_dugout_mode.js', 'live-dugout-mode');
    loadOnce('/static/js/live_game_clock_controls.js', 'live-clock-controls');
    loadOnce('/static/js/live_game_command_center.js', 'live-command-center');
    loadOnce('/static/js/live_game_connection_status.js', 'live-connection-status');

    const observer = new MutationObserver(ensureDefenseAction);
    observer.observe(document.body, {childList: true, subtree: true});
    ensureDefenseAction();
  }, {once: true});
})();
