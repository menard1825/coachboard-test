(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function polishAvailabilitySwitches() {
    const form = document.getElementById('gameAvailabilityForm');
    if (!form || form.dataset.cbAvailPolished === '1') return;
    form.dataset.cbAvailPolished = '1';

    form.querySelectorAll('.form-check').forEach((row) => {
      const input = row.querySelector('input[name="absent_players"]');
      const label = row.querySelector('label');
      if (!input || !label) return;

      row.classList.add('d-flex', 'align-items-center', 'justify-content-between', 'gap-2');
      label.classList.add('me-auto');

      let badge = row.querySelector('.cb-avail-badge');
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'cb-avail-badge badge rounded-pill';
        badge.style.minWidth = '58px';
        badge.style.textAlign = 'center';
        row.appendChild(badge);
      }

      const sync = () => {
        if (input.checked) {
          badge.textContent = 'OUT';
          badge.className = 'cb-avail-badge badge rounded-pill text-bg-danger';
          row.style.background = '#fff5f5';
        } else {
          badge.textContent = 'Present';
          badge.className = 'cb-avail-badge badge rounded-pill text-bg-success';
          row.style.background = '';
        }
      };
      input.addEventListener('change', sync);
      sync();
    });

    const help = document.createElement('div');
    help.className = 'small text-muted mb-2';
    help.textContent = 'Toggle OFF = Present today. Toggle ON = marked OUT for this game.';
    form.prepend(help);
  }

  function ensureStartFeedback() {
    const btn = document.getElementById('startLiveGameBtnAction');
    if (!btn) return null;
    let box = document.getElementById('start-live-blockers');
    if (!box) {
      box = document.createElement('div');
      box.id = 'start-live-blockers';
      box.className = 'alert alert-warning border-0 shadow-sm mb-3 d-none';
      box.setAttribute('role', 'status');
      btn.parentElement?.insertAdjacentElement('beforebegin', box);
    }
    return { btn, box };
  }

  function applyStartReadiness(readiness) {
    const nodes = ensureStartFeedback();
    if (!nodes) return;
    const { btn, box } = nodes;
    if (!readiness || readiness.is_live) {
      box.classList.add('d-none');
      btn.disabled = false;
      btn.classList.remove('disabled');
      return;
    }

    // Server still enforces Inning 1 pitcher + full defense on /start.
    // Surface the same class of blockers coaches already see on Game Day.
    const blockers = Array.isArray(readiness.blockers) ? readiness.blockers.filter(Boolean) : [];
    const hardBlockers = blockers.filter((text) => {
      const t = String(text).toLowerCase();
      return t.includes('pitcher') || t.includes('defense') || t.includes('inning 1') || t.includes('lineup') || t.includes('available');
    });

    if (!hardBlockers.length && readiness.ready) {
      box.className = 'alert alert-success border-0 shadow-sm mb-3';
      box.innerHTML = '<strong>Ready to start.</strong> Inning 1 defense and starting pitcher still need to be set on the board below if you have not finished them yet.';
      btn.disabled = false;
      btn.classList.remove('disabled');
      return;
    }

    if (hardBlockers.length) {
      box.className = 'alert alert-warning border-0 shadow-sm mb-3';
      box.innerHTML = `<strong>Finish setup before first pitch</strong><div class="small mt-1">${hardBlockers.map((t) => esc(t)).join('<br>')}</div><div class="small text-muted mt-2">The server will still block Live Game if Inning 1 is incomplete.</div>`;
    } else if (blockers.length) {
      box.className = 'alert alert-light border shadow-sm mb-3';
      box.innerHTML = `<strong>Optional items still open</strong><div class="small mt-1">${blockers.map((t) => esc(t)).join('<br>')}</div>`;
    } else {
      box.classList.add('d-none');
    }
  }

  async function refreshReadiness() {
    try {
      const response = await fetch(`/api/game-day/${gameId}/readiness`, { cache: 'no-store' });
      if (!response.ok) return;
      const data = await response.json();
      if (data?.readiness) applyStartReadiness(data.readiness);
    } catch (_) {}
  }

  function wirePitchingCardLabel() {
    const header = document.querySelector('#pitching-log-container .card-header h5');
    if (header) {
      header.innerHTML = '<i class="bi bi-bullseye me-2"></i>Pitcher Availability & Plan';
    }
    const pitchingCardValue = document.querySelector('#viewPitchingBtn')?.closest('.card-body')?.querySelector('.h4, .display-6');
    // Leave summary numbers alone; copy is updated in the template.
  }

  function start() {
    polishAvailabilitySwitches();
    wirePitchingCardLabel();
    ensureStartFeedback();
    refreshReadiness();
    window.setInterval(refreshReadiness, 8000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
