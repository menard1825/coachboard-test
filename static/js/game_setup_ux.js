(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);
  const query = new URLSearchParams(window.location.search);
  let pitchingState = null;
  let refreshInFlight = false;
  let dynamicPassQueued = false;

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

  function addPitchingStyles() {
    if (document.getElementById('cb-prepare-pitching-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-prepare-pitching-styles';
    style.textContent = `
      .cb-pitch-list { display:grid; gap:8px; padding:12px; }
      .cb-pitch-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:center; border:1px solid #e4e7ec; border-radius:11px; padding:10px 12px; background:#fff; }
      .cb-pitch-row.caution { background:#fffaf0; border-color:#f2d49b; }
      .cb-pitch-row.resting { background:#fff6f5; border-color:#f3c7c2; }
      .cb-pitch-row.check { background:#fffaf0; border-color:#f2d49b; }
      .cb-pitch-name { font-weight:800; color:#1d2939; }
      .cb-pitch-detail { margin-top:2px; color:#667085; font-size:.72rem; line-height:1.3; }
      .cb-pitch-status { min-width:78px; text-align:center; }
      .cb-pitch-rule-note { color:#667085; font-size:.72rem; line-height:1.35; }
      .cb-pitch-plan-card { border:1px solid #e4e7ec !important; box-shadow:none !important; }
      .cb-pitch-plan-card .card-header { padding:11px 13px; }
      .cb-pitch-plan-card .card-body { padding:12px 13px; }
      .cb-workload-note { color:#8a5a00; font-size:.72rem; margin-top:3px; }
      #live-up-next-v2 .cb-board-help { color:#667085; font-size:.72rem; margin-top:2px; text-transform:none; letter-spacing:normal; font-weight:500; }
      @media (max-width:575.98px) {
        .cb-pitch-row { padding:10px; }
        .cb-pitch-status { min-width:72px; }
      }
    `;
    document.head.appendChild(style);
  }

  function practiceLessonPitches(summary) {
    const workload = Number(summary?.workload_daily_pitches);
    const official = Number(summary?.official_daily_pitches);
    if (!Number.isFinite(workload) || !Number.isFinite(official)) return null;
    return Math.max(0, workload - official);
  }

  function classifyPitcher(summary) {
    const status = String(summary?.status || 'Available');
    const normalized = status.toLowerCase();
    const practiceLesson = practiceLessonPitches(summary);

    if (normalized.includes('incomplete') || normalized.includes('verify')) {
      return { label: 'Check', tone: 'text-bg-warning', row: 'check', rank: 3, practiceLesson };
    }
    if (status !== 'Available') {
      return { label: 'Resting', tone: 'text-bg-danger', row: 'resting', rank: 2, practiceLesson };
    }
    if (practiceLesson !== null && practiceLesson >= 30) {
      return { label: 'Caution', tone: 'text-bg-warning', row: 'caution', rank: 1, practiceLesson };
    }
    return { label: 'Eligible', tone: 'text-bg-success', row: 'eligible', rank: 0, practiceLesson };
  }

  function pitcherDetail(summary, classification) {
    if (classification.label === 'Caution') {
      return `${classification.practiceLesson} practice/lesson pitches today. Still officially eligible; use coaching judgment.`;
    }
    if (classification.label === 'Eligible') {
      const remaining = summary?.pitches_remaining_today;
      if (remaining !== null && remaining !== undefined) return `${remaining} official game pitches remain today.`;
      return 'No current rest restriction.';
    }
    return summary?.status_detail || (classification.label === 'Check' ? 'Verify pitching history before using this pitcher.' : 'Not available to pitch right now.');
  }

  function renderWhoCanPitchToday() {
    if (!pitchingState) return;
    const card = document.getElementById('pitcher-availability-card');
    if (!card) return;

    const rulesHref = card.querySelector('a')?.getAttribute('href') || '#';
    const rows = (pitchingState.roster || []).map((player) => {
      const summary = pitchingState.pitch_count_summary?.[player.name] || {};
      return { player, summary, classification: classifyPitcher(summary) };
    }).sort((a, b) => a.classification.rank - b.classification.rank || a.player.name.localeCompare(b.player.name));

    card.innerHTML = `
      <div class="card-header bg-white py-3 d-flex justify-content-between align-items-start flex-wrap gap-2">
        <div>
          <strong>Who Can Pitch Today?</strong>
          <div class="cb-pitch-rule-note mt-1">Official rest uses game pitches/innings only. 30+ practice or lesson pitches today adds <strong>Caution</strong> but does not make a player officially resting.</div>
        </div>
        <a href="${esc(rulesHref)}" class="btn btn-sm btn-outline-secondary">View Rules</a>
      </div>
      <div class="cb-pitch-list">
        ${rows.map(({ player, summary, classification }) => `
          <div class="cb-pitch-row ${classification.row}">
            <div>
              <div class="cb-pitch-name">${esc(player.name)}</div>
              <div class="cb-pitch-detail">${esc(pitcherDetail(summary, classification))}${summary?.next_available && summary.next_available !== 'Today' ? ` • Next: ${esc(summary.next_available)}` : ''}</div>
            </div>
            <span class="badge rounded-pill cb-pitch-status ${classification.tone}">${classification.label}</span>
          </div>
        `).join('') || '<div class="text-muted small p-2">No pitchers found.</div>'}
      </div>`;
  }

  function updatePitchingSummaryCard() {
    if (!pitchingState) return;
    const body = document.getElementById('viewPitchingBtn')?.closest('.card-body');
    if (!body) return;
    const entries = (pitchingState.roster || []).map((player) => classifyPitcher(pitchingState.pitch_count_summary?.[player.name] || {}));
    const eligible = entries.filter((x) => x.label === 'Eligible').length;
    const caution = entries.filter((x) => x.label === 'Caution').length;
    const unavailable = entries.length - eligible - caution;
    const canPitch = eligible + caution;
    const value = body.querySelector('.h4');
    const detail = body.querySelector('p.small.text-muted');
    if (value) value.innerHTML = `${canPitch} <span class="fs-6 text-muted fw-normal">Can Pitch</span>`;
    if (detail) detail.textContent = [caution ? `${caution} caution` : null, unavailable ? `${unavailable} resting/check` : null].filter(Boolean).join(' · ') || 'Everyone clear today';
    const btn = document.getElementById('viewPitchingBtn');
    if (btn) btn.textContent = 'See Pitchers';
  }

  function hidePregamePostgameEntry() {
    const details = document.getElementById('postgame-pitch-entry');
    if (!details) return;
    if (query.has('pitching') || query.has('finalize')) return;
    const hint = details.querySelector('.hint')?.textContent || '';
    if (/recorded/i.test(hint)) return;
    details.classList.add('d-none');
  }

  function polishPitchingPlan() {
    const board = document.getElementById('pitching-board-v2');
    const card = board?.querySelector(':scope > .card');
    if (!board || !card || card.dataset.cbPlanPolished === '1') return;
    card.dataset.cbPlanPolished = '1';
    card.classList.add('cb-pitch-plan-card');

    const header = card.querySelector('.card-header');
    const body = card.querySelector('.card-body');
    const addButton = card.querySelector('#add-pitcher-plan-v2');
    const planCount = card.querySelectorAll('.edit-plan-v2').length;
    const title = header?.querySelector('h5');
    const subtitle = header?.querySelector('.small.text-muted');
    if (title) title.textContent = 'Pitching Plan (Optional)';
    if (subtitle) subtitle.textContent = planCount ? `${planCount} pitcher${planCount === 1 ? '' : 's'} planned. Use this only if it helps you think ahead.` : 'No plan required. Add a starter or relief idea only if it helps.';

    body?.querySelectorAll('.small.text-muted').forEach((node) => {
      node.textContent = node.textContent.replace(/\s*•\s*Target\s+[^•]+/gi, '').trim();
    });

    if (addButton) {
      addButton.className = 'btn btn-sm btn-outline-primary';
      addButton.innerHTML = '<i class="bi bi-plus-lg me-1"></i>Add Pitcher';
    }

    if (!header || !body) return;
    header.classList.add('gap-2', 'flex-wrap');
    let actions = header.querySelector('.cb-plan-actions');
    if (!actions) {
      actions = document.createElement('div');
      actions.className = 'cb-plan-actions d-flex gap-2 ms-auto';
      if (addButton) actions.appendChild(addButton);
      header.appendChild(actions);
    }

    if (planCount > 0) {
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'btn btn-sm btn-outline-secondary';
      const sync = () => {
        const open = board.dataset.cbPlanOpen === '1';
        body.hidden = !open;
        toggle.textContent = open ? 'Hide Plan' : 'View Plan';
      };
      toggle.addEventListener('click', () => {
        board.dataset.cbPlanOpen = board.dataset.cbPlanOpen === '1' ? '0' : '1';
        sync();
      });
      actions.prepend(toggle);
      sync();
    } else {
      body.hidden = true;
    }
  }

  function decorateLivePitcherPicker() {
    if (!pitchingState) return;
    document.querySelectorAll('#live-pitcher-picker-v2 .pitcher-choice-v2').forEach((button) => {
      if (button.dataset.cbPitchStatus === '1') return;
      button.dataset.cbPitchStatus = '1';
      const playerId = Number(button.dataset.playerId);
      const player = (pitchingState.roster || []).find((p) => Number(p.id) === playerId);
      if (!player) return;
      const summary = pitchingState.pitch_count_summary?.[player.name] || {};
      const classification = classifyPitcher(summary);
      const status = button.querySelector('.d-flex.justify-content-between span');
      if (status) {
        status.className = `badge rounded-pill ${classification.tone}`;
        status.textContent = classification.label;
      }
      const info = button.querySelector('.small.text-muted.mt-1');
      if (info) info.textContent = info.textContent.replace(/\s*•\s*Coach target:\s*[^•]+/gi, '').trim();
      if (classification.label === 'Caution' && !button.querySelector('.cb-workload-note')) {
        button.insertAdjacentHTML('beforeend', `<div class="cb-workload-note">${classification.practiceLesson} practice/lesson pitches today — officially eligible, but use caution.</div>`);
      }
      if (classification.label === 'Check') {
        button.disabled = true;
        button.classList.add('opacity-75');
      }
    });
  }

  function labelNextInningBoard() {
    const card = document.getElementById('live-up-next-v2');
    if (!card) return;
    const title = card.querySelector('.card-body > .small.text-uppercase');
    if (title && !/^Next Inning Board/i.test(title.textContent.trim())) {
      title.textContent = title.textContent.replace(/^Up Next/i, 'Next Inning Board');
    }
    if (title && !card.querySelector('.cb-board-help')) {
      title.insertAdjacentHTML('afterend', '<div class="cb-board-help mb-2">Use this to update the physical dugout board for the next inning.</div>');
    }
    const actionNote = document.querySelector('#liveEndInningBtn .coach-action-note');
    if (actionNote && actionNote.textContent !== 'Show next board') actionNote.textContent = 'Show next board';
  }

  function wirePitchingCardLabel() {
    const header = document.querySelector('#pitching-log-container .card-header h5');
    if (header) header.innerHTML = '<i class="bi bi-bullseye me-2"></i>Pitching';
  }

  function runDynamicPass() {
    dynamicPassQueued = false;
    polishPitchingPlan();
    decorateLivePitcherPicker();
    labelNextInningBoard();
  }

  function queueDynamicPass() {
    if (dynamicPassQueued) return;
    dynamicPassQueued = true;
    window.requestAnimationFrame(runDynamicPass);
  }

  async function refreshPitchingState() {
    if (refreshInFlight) return;
    refreshInFlight = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/state`, { cache: 'no-store' });
      if (!response.ok) return;
      pitchingState = await response.json();
      renderWhoCanPitchToday();
      updatePitchingSummaryCard();
      queueDynamicPass();
    } catch (_) {
    } finally {
      refreshInFlight = false;
    }
  }

  function start() {
    polishAvailabilitySwitches();
    addPitchingStyles();
    wirePitchingCardLabel();
    hidePregamePostgameEntry();
    ensureStartFeedback();
    refreshReadiness();
    refreshPitchingState();

    const observer = new MutationObserver(queueDynamicPass);
    observer.observe(document.body, { childList: true, subtree: true });
    queueDynamicPass();

    window.setInterval(refreshReadiness, 8000);
    window.setInterval(refreshPitchingState, 12000);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) refreshPitchingState();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
