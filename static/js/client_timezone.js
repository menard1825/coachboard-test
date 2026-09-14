(() => {
  'use strict';

  function detectClientContext() {
    let timezone = '';
    try {
      timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    } catch (_) {
      timezone = '';
    }
    return {
      timezone,
      utcOffsetMinutes: -new Date().getTimezoneOffset(),
    };
  }

  function fillContextFields(context) {
    document.querySelectorAll('input[name="client_timezone"], [data-client-timezone]').forEach((input) => {
      if ('value' in input) input.value = context.timezone;
    });
    document.querySelectorAll('input[name="client_utc_offset_minutes"], [data-client-utc-offset]').forEach((input) => {
      if ('value' in input) input.value = String(context.utcOffsetMinutes);
    });
    document.querySelectorAll('[data-detected-timezone]').forEach((element) => {
      element.textContent = context.timezone || 'Unable to detect';
    });
  }

  async function syncSignedInSession(context) {
    const body = document.body;
    if (!body || body.dataset.coachboardAuthenticated !== '1' || !context.timezone) return;

    const sessionTimezone = body.dataset.sessionTimezone || '';
    const sessionOffset = body.dataset.sessionUtcOffset || '';
    if (sessionTimezone === context.timezone && sessionOffset === String(context.utcOffsetMinutes)) return;

    try {
      await fetch('/api/client-context', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          timezone: context.timezone,
          utc_offset_minutes: context.utcOffsetMinutes,
        }),
      });
      body.dataset.sessionTimezone = context.timezone;
      body.dataset.sessionUtcOffset = String(context.utcOffsetMinutes);
    } catch (_) {
      // Timezone context is helpful audit metadata, never a reason to block CoachBoard.
    }
  }

  function bindUseDeviceTimezone(context) {
    document.querySelectorAll('[data-use-device-timezone]').forEach((button) => {
      button.addEventListener('click', () => {
        const targetId = button.dataset.useDeviceTimezone;
        const target = targetId ? document.getElementById(targetId) : null;
        if (target && context.timezone) {
          target.value = context.timezone;
          target.dispatchEvent(new Event('change', {bubbles: true}));
        }
      });
    });
  }

  function installGettingStartedDesktopLink() {
    const body = document.body;
    if (!body || body.dataset.coachboardAuthenticated !== '1') return;
    if (!['Head Coach', 'Super Admin'].includes(body.dataset.coachRole || '')) return;

    const menu = document.querySelector('.coach-primary-nav .dropdown-menu');
    if (!menu || menu.querySelector('[data-cb-getting-started-link]')) return;

    const divider = document.createElement('li');
    divider.dataset.cbGettingStartedDivider = 'true';
    divider.innerHTML = '<hr class="dropdown-divider">';

    const item = document.createElement('li');
    item.innerHTML = '<a class="dropdown-item" data-cb-getting-started-link="true" href="/getting-started"><i class="bi bi-compass me-2"></i>Getting Started</a>';
    menu.append(divider, item);
  }

  function usageSessionId() {
    const key = 'coachboard-usage-session-id';
    try {
      let value = window.sessionStorage.getItem(key);
      if (!value) {
        value = (window.crypto && typeof window.crypto.randomUUID === 'function')
          ? window.crypto.randomUUID()
          : `cb-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        window.sessionStorage.setItem(key, value);
      }
      return value;
    } catch (_) {
      return `cb-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
  }

  function usageArea() {
    const path = window.location.pathname || '/';
    const hash = (window.location.hash || '').replace(/^#/, '').toLowerCase();
    if (path === '/') {
      const labels = {
        overview: 'Home',
        roster: 'Roster',
        player_development: 'Player Development',
        lineups: 'Lineup Templates',
        pitching: 'Pitching',
        scouting_list: 'Scouting',
        rotations: 'Defensive Templates',
        games: 'Schedule',
        collaboration: 'Coach Notes',
        practice_plan: 'Practice',
        stats: 'Stats',
        more: 'More',
      };
      return labels[hash] || 'Home';
    }
    if (/^\/game\/\d+\/?$/.test(path)) {
      return document.body?.classList.contains('cb-dugout') ? 'Live Game' : 'Game Planning';
    }
    if (path.startsWith('/game-day')) return 'Game Day';
    if (path.startsWith('/pitching')) return 'Pitching';
    if (path.startsWith('/practice')) return 'Practice';
    if (path.startsWith('/admin/coach-usage')) return 'Coach Usage';
    if (path.startsWith('/admin/activity')) return 'Coach Activity';
    if (path.startsWith('/admin')) return 'Administration';
    if (path.startsWith('/getting-started')) return 'Getting Started';
    return 'CoachBoard';
  }

  function installPresenceTracking(context) {
    const body = document.body;
    if (!body || body.dataset.coachboardAuthenticated !== '1') return;

    const browserSessionId = usageSessionId();
    const readOnlyRole = body.dataset.coachRole === 'Game Changer';
    let sending = false;

    const sendHeartbeat = async () => {
      if (document.hidden || sending) return;
      const payload = {
        browser_session_id: browserSessionId,
        area: usageArea(),
        path: `${window.location.pathname || '/'}${window.location.hash || ''}`.slice(0, 180),
        timezone: context.timezone,
        utc_offset_minutes: context.utcOffsetMinutes,
      };
      sending = true;
      try {
        if (readOnlyRole) {
          const query = new URLSearchParams();
          Object.entries(payload).forEach(([key, value]) => query.set(key, String(value ?? '')));
          await fetch(`/api/coach-usage/heartbeat?${query.toString()}`, {
            method: 'GET',
            credentials: 'same-origin',
            cache: 'no-store',
          });
        } else {
          await fetch('/api/coach-usage/heartbeat', {
            method: 'POST',
            credentials: 'same-origin',
            keepalive: true,
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
          });
        }
      } catch (_) {
        // Presence is testing/administrative telemetry and must never block app use.
      } finally {
        sending = false;
      }
    };

    window.setTimeout(sendHeartbeat, 500);
    window.setInterval(sendHeartbeat, 60000);
    window.addEventListener('hashchange', () => window.setTimeout(sendHeartbeat, 100));
    window.addEventListener('popstate', () => window.setTimeout(sendHeartbeat, 100));
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) sendHeartbeat();
    });
  }

  function init() {
    const context = detectClientContext();
    fillContextFields(context);
    bindUseDeviceTimezone(context);
    installGettingStartedDesktopLink();
    syncSignedInSession(context);
    installPresenceTracking(context);
  }

  window.CoachBoardClientTimezone = {detect: detectClientContext};
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, {once: true});
  } else {
    init();
  }
})();