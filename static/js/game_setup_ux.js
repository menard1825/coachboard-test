(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);
  const query = new URLSearchParams(window.location.search);
  let pitchingState = null;
  let pitchingRuleState = null;
  let armCareState = null;
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
      box.innerHTML = '<strong>Ready to start.</strong> Pregame setup is complete. Tap Start Live Game when you are ready for first pitch.';
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
      #pitcher-availability-card .gpa-shell { padding:10px; background:#f8f9fb; }
      #pitcher-availability-card .gpa-summary { display:flex; gap:7px; align-items:center; flex-wrap:wrap; margin-bottom:9px; font-size:.67rem; color:#667085; }
      #pitcher-availability-card .gpa-summary strong { font-size:.74rem; color:#344054; }
      #pitcher-availability-card .gpa-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
      #pitcher-availability-card .gpa-card { border:1px solid #dfe4ea; border-radius:12px; background:#fff; overflow:hidden; min-width:0; }
      #pitcher-availability-card .gpa-card.attention { border-color:#ead7b5; }
      #pitcher-availability-card .gpa-card.resting { border-color:#efc6c1; }
      #pitcher-availability-card .gpa-top { display:flex; justify-content:space-between; gap:8px; align-items:flex-start; padding:10px 11px 7px; }
      #pitcher-availability-card .gpa-name { font-weight:850; color:#172033; font-size:.86rem; min-width:0; overflow:hidden; text-overflow:ellipsis; }
      #pitcher-availability-card .gpa-status { font-size:.57rem; font-weight:850; border-radius:999px; padding:4px 7px; white-space:nowrap; background:#e9f7ee; color:#176b38; }
      #pitcher-availability-card .gpa-card.attention .gpa-status { background:#fff3d8; color:#8a5800; }
      #pitcher-availability-card .gpa-card.resting .gpa-status { background:#feeceb; color:#a32929; }
      #pitcher-availability-card .gpa-decision { margin:0 10px 8px; padding:8px 9px; border-radius:9px; background:#f7f9fb; border:1px solid #e5e8ed; }
      #pitcher-availability-card .gpa-card.attention .gpa-decision { background:#fffaf1; border-color:#ecd9b4; }
      #pitcher-availability-card .gpa-card.resting .gpa-decision { background:#fff7f6; border-color:#efcfcb; }
      #pitcher-availability-card .gpa-label { display:block; font-size:.55rem; text-transform:uppercase; letter-spacing:.06em; font-weight:850; color:#667085; }
      #pitcher-availability-card .gpa-decision strong { display:block; font-size:.76rem; color:#1d2939; margin-top:2px; }
      #pitcher-availability-card .gpa-detail { display:block; font-size:.59rem; color:#7b8492; line-height:1.3; margin-top:3px; }
      #pitcher-availability-card .gpa-next { display:block; font-size:.63rem; color:#8a5a13; margin-top:3px; font-weight:750; }
      #pitcher-availability-card .gpa-arm { padding:8px 10px; border-top:1px solid #edf0f3; background:#fcfcfd; }
      #pitcher-availability-card .gpa-arm strong { display:block; font-size:.69rem; color:#344054; margin-top:1px; }
      #pitcher-availability-card .gpa-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border-top:1px solid #edf0f3; }
      #pitcher-availability-card .gpa-metric { padding:8px 10px; font-size:.68rem; min-width:0; color:#344054; }
      #pitcher-availability-card .gpa-metric + .gpa-metric { border-left:1px solid #edf0f3; }
      #pitcher-availability-card .gpa-value { display:block; margin-top:2px; font-weight:800; color:#1d2939; line-height:1.25; overflow-wrap:anywhere; }
      .cb-pitch-rule-note { color:#667085; font-size:.72rem; line-height:1.35; }
      .cb-pitch-plan-card { border:1px solid #e4e7ec !important; box-shadow:none !important; }
      .cb-pitch-plan-card .card-header { padding:11px 13px; }
      .cb-pitch-plan-card .card-body { padding:12px 13px; }
      .cb-workload-note { color:#8a5a00; font-size:.72rem; margin-top:3px; }
      #live-up-next-v2 .cb-board-help { color:#667085; font-size:.72rem; margin-top:2px; text-transform:none; letter-spacing:normal; font-weight:500; }
      @media (max-width:575.98px) {
        #pitcher-availability-card .gpa-grid { grid-template-columns:1fr; }
        #pitcher-availability-card .gpa-shell { padding:8px; }
        #pitcher-availability-card .gpa-metrics { grid-template-columns:1fr 1fr; }
        #pitcher-availability-card .gpa-metric:nth-child(3) { grid-column:1 / -1; border-left:0; border-top:1px solid #edf0f3; }
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

  function hasCompetitionRules() {
    return Boolean(pitchingRuleState?.effective);
  }

  function classifyPitcher(summary) {
    const status = String(summary?.status || 'Available');
    const normalized = status.toLowerCase();
    const practiceLesson = practiceLessonPitches(summary);

    if (!hasCompetitionRules()) {
      return { label: 'Rules?', tone: 'text-bg-warning', row: 'attention', rank: 1, practiceLesson, officialAvailable: false, needsRules: true };
    }
    if (normalized.includes('incomplete') || normalized.includes('verify')) {
      return { label: 'Verify', tone: 'text-bg-warning', row: 'attention', rank: 0, practiceLesson, officialAvailable: false };
    }
    if (status !== 'Available') {
      return { label: 'Resting', tone: 'text-bg-danger', row: 'resting', rank: 0, practiceLesson, officialAvailable: false };
    }
    if (practiceLesson !== null && practiceLesson >= 30) {
      return { label: 'Caution', tone: 'text-bg-warning', row: 'attention', rank: 2, practiceLesson, officialAvailable: true };
    }
    return { label: 'Available', tone: 'text-bg-success', row: '', rank: 3, practiceLesson, officialAvailable: true };
  }

  function competitionDecision(summary, classification) {
    if (classification.needsRules) return 'Select competition rules for this game';
    if (classification.officialAvailable) return 'Available by competition rule';
    if (summary?.next_available && summary.next_available !== 'Today') return `Can pitch again: ${summary.next_available}`;
    if (classification.label === 'Verify') return 'Verify pitching history before using this pitcher';
    return summary?.status_detail || 'Not available to pitch right now';
  }

  function officialToday(summary) {
    if (summary?.rule_type === 'innings') {
      const innings = summary?.daily_innings;
      return `${innings === null || innings === undefined ? '—' : innings} IP`;
    }
    const pitches = summary?.official_daily_pitches;
    const max = summary?.max_daily;
    if (pitches === null || pitches === undefined) return '—';
    return max ? `${pitches} / ${max} pitches` : `${pitches} pitches`;
  }

  function workloadText(summary) {
    const today = summary?.workload_daily_pitches;
    const seven = summary?.workload_7_day_pitches;
    const todayText = today === null || today === undefined ? '— today' : `${today} today`;
    const sevenText = seven === null || seven === undefined ? '— / 7d' : `${seven} / 7d`;
    return `${todayText} · ${sevenText}`;
  }

  function planText(player, summary) {
    const plan = (pitchingState?.pitching_plans || []).find((item) => Number(item.player_id) === Number(player.id));
    const pieces = [];
    if (plan?.role) pieces.push(plan.role);
    if (plan?.expected_innings) pieces.push(`${plan.expected_innings} IP`);
    if (summary?.coach_target) pieces.push(`Target ${summary.coach_target}`);
    return pieces.join(' · ') || 'No plan';
  }

  function armCareMarkup(playerName) {
    const ruleSet = armCareState?.rule_set || pitchingRuleState?.arm_care_rule_set || 'Pitch Smart';
    if (!armCareState) {
      return `<span class="gpa-label">Arm care · ${esc(ruleSet)}</span><strong class="text-muted">Guidance unavailable</strong>`;
    }
    if (!armCareState.enabled) {
      return '<span class="gpa-label">Arm care</span><strong>Off</strong>';
    }
    const item = armCareState.players?.[playerName];
    if (!item) {
      return `<span class="gpa-label">Arm care · ${esc(ruleSet)}</span><strong class="text-muted">No tracked throwing history</strong>`;
    }
    const onTrack = item.status === 'Available';
    return `
      <span class="gpa-label">Arm care · ${esc(ruleSet)}</span>
      <strong>${esc(onTrack ? 'On track' : (item.status || 'Needs attention'))}</strong>
      ${!onTrack && item.next_available && item.next_available !== 'Today' ? `<span class="gpa-next">Rest guidance: ${esc(item.next_available)}</span>` : ''}
      ${!onTrack && item.status_detail ? `<span class="gpa-detail">${esc(item.status_detail)}</span>` : ''}`;
  }

  function renderWhoCanPitchToday() {
    if (!pitchingState) return;
    const card = document.getElementById('pitcher-availability-card');
    if (!card) return;

    const rulesHref = card.querySelector('a')?.getAttribute('href') || '/rules';
    const rows = (pitchingState.roster || []).map((player) => {
      const summary = pitchingState.pitch_count_summary?.[player.name] || {};
      return { player, summary, classification: classifyPitcher(summary) };
    }).sort((a, b) => a.classification.rank - b.classification.rank || a.player.name.localeCompare(b.player.name));

    const availableCount = rows.filter((item) => item.classification.officialAvailable).length;
    const attentionCount = rows.length - availableCount;
    const ruleLabel = pitchingRuleState?.effective || 'Rules not selected';

    card.dataset.cbPitchingOwner = 'game-setup';
    card.innerHTML = `
      <div class="card-header bg-white py-3 d-flex justify-content-between align-items-start flex-wrap gap-2">
        <div>
          <strong>Who Can Pitch Today?</strong>
          <div class="cb-pitch-rule-note mt-1">Competition eligibility answers whether a player can pitch. Arm-care guidance is separate and advisory.</div>
        </div>
        <a href="${esc(rulesHref)}" class="btn btn-sm btn-outline-secondary">View Rules</a>
      </div>
      <div class="gpa-shell">
        <div class="gpa-summary">
          <strong>${hasCompetitionRules() ? `${availableCount} available` : 'Competition rules not selected'}</strong>
          ${hasCompetitionRules() ? `<span>•</span><strong>${attentionCount} need attention</strong>` : ''}
          <span>${esc(ruleLabel)}</span>
        </div>
        <div class="gpa-grid">
          ${rows.map(({ player, summary, classification }) => `
            <article class="gpa-card ${classification.row}" data-player-name="${esc(player.name)}" data-available="${classification.officialAvailable ? 'true' : 'false'}">
              <div class="gpa-top">
                <div class="gpa-name">${esc(player.name)}</div>
                <span class="gpa-status">${esc(classification.label)}</span>
              </div>
              <div class="gpa-decision">
                <span class="gpa-label">Competition eligibility</span>
                <strong>${esc(competitionDecision(summary, classification))}</strong>
                ${!classification.officialAvailable && summary?.status_detail && !classification.needsRules ? `<span class="gpa-detail">${esc(summary.status_detail)}</span>` : ''}
                ${classification.officialAvailable && classification.label === 'Caution' ? `<span class="gpa-detail">${esc(`${classification.practiceLesson} practice/lesson pitches today. Officially eligible; use coaching judgment.`)}</span>` : ''}
              </div>
              <div class="gpa-arm">${armCareMarkup(player.name)}</div>
              <div class="gpa-metrics">
                <div class="gpa-metric"><span class="gpa-label">Official today</span><span class="gpa-value">${esc(officialToday(summary))}</span></div>
                <div class="gpa-metric"><span class="gpa-label">Throwing workload</span><span class="gpa-value">${esc(workloadText(summary))}</span></div>
                <div class="gpa-metric"><span class="gpa-label">Game plan</span><span class="gpa-value">${esc(planText(player, summary))}</span></div>
              </div>
            </article>
          `).join('') || '<div class="text-muted small p-2">No pitchers found.</div>'}
        </div>
      </div>`;
  }

  function updatePitchingSummaryCard() {
    if (!pitchingState) return;
    const body = document.getElementById('viewPitchingBtn')?.closest('.card-body');
    if (!body) return;
    const entries = (pitchingState.roster || []).map((player) => classifyPitcher(pitchingState.pitch_count_summary?.[player.name] || {}));
    const canPitch = entries.filter((x) => x.officialAvailable).length;
    const caution = entries.filter((x) => x.label === 'Caution').length;
    const unavailable = entries.length - canPitch;
    const value = body.querySelector('.h4');
    const detail = body.querySelector('p.small.text-muted');
    if (value) value.innerHTML = `${canPitch} <span class="fs-6 text-muted fw-normal">Can Pitch</span>`;
    if (detail) {
      detail.textContent = !hasCompetitionRules()
        ? 'Select competition rules for this game'
        : ([caution ? `${caution} caution` : null, unavailable ? `${unavailable} unavailable/check` : null].filter(Boolean).join(' · ') || 'Everyone clear today');
    }
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
      if (!classification.officialAvailable) {
        button.disabled = true;
        button.classList.add('opacity-75');
        if (classification.needsRules) button.title = 'Select competition pitching rules before choosing a pitcher.';
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
      const [stateResponse, rulesResponse, armResponse] = await Promise.all([
        fetch(`/api/live-game/${gameId}/state`, { cache: 'no-store' }),
        fetch(`/api/game-day/${gameId}/pitching-rules`, { cache: 'no-store' }),
        fetch(`/api/pitching-preferences/arm-care-summary?game_id=${gameId}`, { cache: 'no-store' }),
      ]);
      if (!stateResponse.ok) return;

      pitchingState = await stateResponse.json();
      const rulesData = await rulesResponse.json().catch(() => ({}));
      const armData = await armResponse.json().catch(() => ({}));
      pitchingRuleState = rulesResponse.ok && rulesData?.status !== 'error' ? rulesData : null;
      armCareState = armResponse.ok && armData?.status !== 'error' ? armData : null;

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
