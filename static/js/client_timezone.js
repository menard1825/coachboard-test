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

  function init() {
    const context = detectClientContext();
    fillContextFields(context);
    bindUseDeviceTimezone(context);
    syncSignedInSession(context);
  }

  window.CoachBoardClientTimezone = {detect: detectClientContext};
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, {once: true});
  } else {
    init();
  }
})();
