(() => {
  'use strict';

  if (window.location.pathname !== '/') return;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  let cachedModel = null;
  let rendering = false;
  let observer = null;

  async function getJson(url, fallback = null) {
    try {
      const response = await fetch(url, {cache: 'no-store'});
      const data = await response.json().catch(() => fallback);
      if (!response.ok || data?.status === 'error') return fallback;
      return data;
    } catch (_) {
      return fallback;
    }
  }

  function parseDate(value) {
    if (!value) return null;
    const text = String(value).replace(' ', 'T');
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function dateOnlyKey(value) {
    const dt = parseDate(value);
    return dt ? dt.getTime() : Number.MAX_SAFE_INTEGER;
  }

  function localStartOfTodayMs() {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return today.getTime();
  }

  function formatDate(value, startTime = '') {
    const dt = parseDate(value);
    if (!dt) return 'Date TBD';
    const dateText = dt.toLocaleDateString('en-US', {
      weekday: 'short', month: 'short', day: 'numeric'
    });
    return startTime ? `${dateText} · ${esc(startTime)}` : dateText;
  }

  function coachName() {
    const desktop = document.getElementById('userMenuDesktop')?.textContent || '';
    const match = desktop.replace(/\s+/g, ' ').match(/Welcome,\s*(.+?)!/i);
    return match ? match[1].trim().split(/\s+/)[0] : '';
  }

  function greeting() {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }

  function toneClass(ok, warning = false) {
    if (ok === true) return 'is-ready';
    if (warning) return 'is-warning';
    return 'is-neutral';
  }

  function statusItem(icon, label, detail, ok, warning = false) {
    return `<div class="cb-home-status ${toneClass(ok, warning)}">
      <span class="cb-home-status-icon"><i class="bi bi-${icon}"></i></span>
      <span><strong>${esc(label)}</strong><small>${detail}</small></span>
    </div>`;
  }

  function quickLink(href, icon, title, detail) {
    return `<a class="cb-home-quick" href="${href}">
      <span class="cb-home-quick-icon"><i class="bi bi-${icon}"></i></span>
      <span><strong>${esc(title)}</strong><small>${esc(detail)}</small></span>
      <i class="bi bi-chevron-right"></i>
    </a>`;
  }

  function attentionRow(icon, title, detail, href = '') {
    const tag = href ? 'a' : 'div';
    const hrefAttr = href ? ` href="${href}"` : '';
    return `<${tag} class="cb-home-attention-row"${hrefAttr}>
      <span class="cb-home-attention-icon"><i class="bi bi-${icon}"></i></span>
      <span class="min-w-0"><strong>${esc(title)}</strong><small>${esc(detail)}</small></span>
      ${href ? '<i class="bi bi-chevron-right ms-auto"></i>' : ''}
    </${tag}>`;
  }

  function liveBanner(model) {
    const game = model.liveGame;
    if (!game) return '';
    return `<a class="cb-home-live" href="/game/${game.id}">
      <span class="cb-live-dot"></span>
      <span><strong>Game in progress</strong><small>vs ${esc(game.opponent)} · Resume CoachBoard Live Game</small></span>
      <span class="cb-home-live-action">Resume <i class="bi bi-arrow-right"></i></span>
    </a>`;
  }

  function nextGameCard(model) {
    const game = model.nextGame;
    if (!game) {
      return `<section class="cb-home-card cb-home-next-game">
        <div class="cb-home-card-head"><div><span class="cb-home-eyebrow">Next up</span><h2>No upcoming game</h2></div><i class="bi bi-calendar-plus cb-home-card-icon"></i></div>
        <p class="cb-home-muted">Add the next game when the schedule is available. CoachBoard will bring lineup, defense, pitching rules, and availability together here.</p>
        <a class="btn btn-primary" href="/game-day">Open Game Day & Schedule</a>
      </section>`;
    }

    const r = model.readiness || {};
    const rules = model.rules || {};
    const rulesSelected = Boolean(rules.effective) && rules.source !== 'unselected';
    const statusLabel = r.status || (game.is_live ? 'LIVE' : 'PREP');
    const statusTone = statusLabel === 'READY' ? 'success' : statusLabel === 'LIVE' ? 'danger' : 'warning';
    const absent = Number(r.absent_count || 0);
    const present = Number(r.present_count || 0);

    return `<section class="cb-home-card cb-home-next-game">
      <div class="cb-home-card-head">
        <div>
          <div class="d-flex align-items-center gap-2 flex-wrap mb-1"><span class="cb-home-eyebrow">Next game</span><span class="badge text-bg-${statusTone}">${esc(statusLabel)}</span></div>
          <h2>vs ${esc(game.opponent)}</h2>
          <div class="cb-home-game-meta"><span><i class="bi bi-calendar3"></i>${formatDate(game.date, game.start_time)}</span><span><i class="bi bi-geo-alt"></i>${esc(game.location || 'Location TBD')}</span></div>
          ${game.game_notes ? `<div class="cb-home-game-note"><i class="bi bi-chat-left-text"></i>${esc(game.game_notes)}</div>` : ''}
        </div>
        <i class="bi bi-diamond cb-home-card-icon"></i>
      </div>

      <div class="cb-home-readiness">
        ${statusItem(r.lineup_ready ? 'check-circle-fill' : 'exclamation-circle', 'Batting lineup', r.lineup_ready ? `${r.lineup_count || 0} hitters ready` : 'Needs attention before game day', r.lineup_ready, !r.lineup_ready)}
        ${statusItem(r.defense_ready ? 'check-circle-fill' : 'exclamation-circle', 'Defense', r.defense_ready ? `${r.defense_completed_innings || r.defense_innings || 0} innings planned` : 'Rotation is not complete', r.defense_ready, !r.defense_ready)}
        ${statusItem('people', 'Availability', r.present_count == null ? 'Open game to review availability' : `${present} available${absent ? ` · ${absent} out` : ''}`, true)}
        ${statusItem(rulesSelected ? 'check-circle-fill' : 'exclamation-circle', 'Competition rules', rulesSelected ? `${esc(rules.effective)}${rules.source === 'game' ? ' · game override' : ' · team default'}` : 'Select tournament / league rules', rulesSelected, !rulesSelected)}
      </div>

      ${Array.isArray(r.blockers) && r.blockers.length ? `<div class="cb-home-prep-note"><strong>${r.blockers.length} preparation item${r.blockers.length === 1 ? '' : 's'} remaining</strong><span>${esc(r.blockers[0])}</span></div>` : '<div class="cb-home-ready-note"><i class="bi bi-check2-circle"></i><span>Game plan is ready. Review it before first pitch.</span></div>'}

      <div class="cb-home-card-actions">
        <a class="btn btn-primary" href="/game/${game.id}">${game.is_live ? 'Resume Live Game' : 'Manage Game'}</a>
        <a class="btn btn-outline-secondary" href="/game-day">Schedule</a>
      </div>
    </section>`;
  }

  function attentionCard(model) {
    const rows = [];
    const r = model.readiness || {};
    const rules = model.rules || {};

    if (model.nextGame) {
      if (!r.lineup_ready) rows.push(attentionRow('card-list', 'Batting lineup', 'Build or finish the lineup for the next game.', `/game/${model.nextGame.id}`));
      if (!r.defense_ready) rows.push(attentionRow('diagram-3', 'Defensive plan', 'Complete the starting defense / rotation.', `/game/${model.nextGame.id}`));
      if (!rules.effective || rules.source === 'unselected') rows.push(attentionRow('trophy', 'Competition rules', 'Choose the rules that apply to this event.', `/game/${model.nextGame.id}`));
      (r.pitching_alerts || []).slice(0, 2).forEach(item => {
        rows.push(attentionRow('exclamation-triangle', item.name, `${item.status}${item.detail ? ` · ${item.detail}` : ''}`, '/pitching'));
      });
    }

    model.armCareConcerns.slice(0, 2).forEach(([name, item]) => {
      rows.push(attentionRow('heart-pulse', `${name} arm care`, item.status_detail || item.status || 'Review workload guidance.', '/pitching'));
    });

    if (model.incompleteProfiles > 0) {
      rows.push(attentionRow('person-lines-fill', 'Roster profiles', `${model.incompleteProfiles} player profile${model.incompleteProfiles === 1 ? '' : 's'} still need baseball details.`, '/#roster'));
    }

    const body = rows.length
      ? rows.slice(0, 6).join('')
      : `<div class="cb-home-all-clear"><i class="bi bi-check2-circle"></i><strong>Nothing urgent right now</strong><span>Your next-game plan and tracked team items look caught up.</span></div>`;

    return `<section class="cb-home-card cb-home-attention">
      <div class="cb-home-card-head compact"><div><span class="cb-home-eyebrow">Coach checklist</span><h3>Needs Attention</h3></div><i class="bi bi-lightning-charge cb-home-card-icon"></i></div>
      <div class="cb-home-attention-list">${body}</div>
    </section>`;
  }

  function practiceCard(model) {
    const plan = model.nextPractice;
    if (!plan) {
      return `<section class="cb-home-card cb-home-small-card">
        <div class="cb-home-card-head compact"><div><span class="cb-home-eyebrow">Next practice</span><h3>No practice planned</h3></div><i class="bi bi-clipboard-plus cb-home-card-icon"></i></div>
        <p class="cb-home-muted">Create the next practice plan or reuse a successful one.</p>
        <a class="cb-home-text-link" href="/#practice_plan">Open Practice <i class="bi bi-arrow-right"></i></a>
      </section>`;
    }

    const taskCount = Array.isArray(plan.tasks) ? plan.tasks.length : 0;
    const absentCount = Array.isArray(plan.absent_player_ids) ? plan.absent_player_ids.length : 0;
    return `<section class="cb-home-card cb-home-small-card">
      <div class="cb-home-card-head compact"><div><span class="cb-home-eyebrow">Next practice</span><h3>${formatDate(plan.date)}</h3></div><i class="bi bi-clipboard-check cb-home-card-icon"></i></div>
      <div class="cb-home-small-copy">${plan.emphasis ? `<strong>${esc(plan.emphasis)}</strong>` : '<strong>Plan ready for details</strong>'}<span>${taskCount} setup task${taskCount === 1 ? '' : 's'}${absentCount ? ` · ${absentCount} out` : ''}</span></div>
      <a class="cb-home-text-link" href="/#practice_plan">View Practice Plan <i class="bi bi-arrow-right"></i></a>
    </section>`;
  }

  function armCareCard(model) {
    const arm = model.armCare || {};
    const setting = model.pitchingSettings?.settings?.arm_care_rule_set || '';
    if (!setting || arm.enabled === false) {
      return `<section class="cb-home-card cb-home-small-card">
        <div class="cb-home-card-head compact"><div><span class="cb-home-eyebrow">Arm care</span><h3>Guidance is off</h3></div><i class="bi bi-heart-pulse cb-home-card-icon"></i></div>
        <p class="cb-home-muted">Competition rules still work normally. Turn on arm-care guidance if the staff wants an independent workload view.</p>
        <a class="cb-home-text-link" href="/admin/settings#pitching-rules-settings">Pitching Settings <i class="bi bi-arrow-right"></i></a>
      </section>`;
    }

    const concerns = model.armCareConcerns;
    return `<section class="cb-home-card cb-home-small-card">
      <div class="cb-home-card-head compact"><div><span class="cb-home-eyebrow">Arm care</span><h3>${esc(setting)}</h3></div><i class="bi bi-heart-pulse cb-home-card-icon"></i></div>
      ${concerns.length
        ? `<div class="cb-home-arm-list">${concerns.slice(0, 3).map(([name, item]) => `<div><strong>${esc(name)}</strong><span>${esc(item.status || 'Review')} ${item.game_pitches_today != null ? `· ${item.game_pitches_today}${item.max_daily ? `/${item.max_daily}` : ''} game pitches` : ''}</span></div>`).join('')}</div>`
        : '<div class="cb-home-all-clear small"><i class="bi bi-check2-circle"></i><strong>Tracked pitchers are on track</strong><span>No current arm-care warnings.</span></div>'}
      <a class="cb-home-text-link" href="/pitching">Open Pitching <i class="bi bi-arrow-right"></i></a>
    </section>`;
  }

  function teamCard(model) {
    const notes = (model.overview?.recent_notes || []).slice(0, 2);
    const upcomingCount = model.games.filter(game => dateOnlyKey(game.date) >= localStartOfTodayMs()).length;
    return `<section class="cb-home-card cb-home-small-card">
      <div class="cb-home-card-head compact"><div><span class="cb-home-eyebrow">Team snapshot</span><h3>${model.roster.length} players</h3></div><i class="bi bi-people cb-home-card-icon"></i></div>
      <div class="cb-home-metrics"><span><strong>${model.pitcherCount}</strong><small>pitchers</small></span><span><strong>${upcomingCount}</strong><small>upcoming games</small></span><span><strong>${model.incompleteProfiles}</strong><small>profiles to finish</small></span></div>
      ${notes.length ? `<div class="cb-home-recent-notes"><span class="cb-home-eyebrow">Recent coach notes</span>${notes.map(note => `<div><strong>${esc(note.author || 'Coach')}</strong><span>${esc(note.text || '')}</span></div>`).join('')}</div>` : ''}
      <a class="cb-home-text-link" href="/#roster">Open Roster <i class="bi bi-arrow-right"></i></a>
    </section>`;
  }

  function render(model) {
    const container = document.getElementById('overview-content-container');
    if (!container) return;

    rendering = true;
    const firstName = coachName();
    const role = model.session?.session?.role || '';
    const competitionDefault = model.pitchingSettings?.settings?.competition_default_rule || '';

    container.innerHTML = `<div class="cb-home-dashboard">
      <header class="cb-home-welcome">
        <div><span class="cb-home-eyebrow">CoachBoard Home</span><h1>${greeting()}${firstName ? `, ${esc(firstName)}` : ''}</h1><p>Everything that needs a coach's attention, without digging through the app.</p></div>
        <div class="cb-home-context"><span>${esc(role || 'Coach')}</span>${competitionDefault ? `<small>Default rules: ${esc(competitionDefault)}</small>` : '<small>Competition rules: choose by game/event</small>'}</div>
      </header>

      ${liveBanner(model)}

      <div class="cb-home-grid cb-home-grid-top">
        ${nextGameCard(model)}
        ${attentionCard(model)}
      </div>

      <div class="cb-home-grid cb-home-grid-three">
        ${practiceCard(model)}
        ${armCareCard(model)}
        ${teamCard(model)}
      </div>

      <section class="cb-home-quick-section">
        <div class="cb-home-section-head"><div><span class="cb-home-eyebrow">Shortcuts</span><h3>Quick Actions</h3></div></div>
        <div class="cb-home-quick-grid">
          ${quickLink('/game-day', 'diamond', 'Game Day', 'Plan or open the next game')}
          ${quickLink('/#practice_plan', 'clipboard-check', 'Practice', 'Build the next practice plan')}
          ${quickLink('/pitching', 'bullseye', 'Pitching', 'Eligibility and arm care')}
          ${quickLink('/#roster', 'people', 'Roster', 'Player profiles and roles')}
        </div>
      </section>
    </div>`;
    rendering = false;
  }

  function installMobileNav() {
    const update = () => {
      const nav = document.querySelector('nav.bottom-nav-fixed ul');
      if (!nav) return;
      nav.innerHTML = `
        <li class="nav-item flex-fill"><a class="nav-link text-center active" data-bs-toggle="tab" role="tab" href="#overview"><i class="bi bi-house-door d-block"></i><span>Home</span></a></li>
        <li class="nav-item flex-fill"><a class="nav-link text-center" href="/game-day"><i class="bi bi-diamond d-block"></i><span>Game Day</span></a></li>
        <li class="nav-item flex-fill"><a class="nav-link text-center" data-bs-toggle="tab" role="tab" href="#roster"><i class="bi bi-people d-block"></i><span>Roster</span></a></li>
        <li class="nav-item flex-fill"><a class="nav-link text-center" data-bs-toggle="tab" role="tab" href="#practice_plan"><i class="bi bi-clipboard-check d-block"></i><span>Practice</span></a></li>
        <li class="nav-item flex-fill"><a class="nav-link text-center" data-bs-toggle="tab" role="tab" href="#more"><i class="bi bi-three-dots d-block"></i><span>More</span></a></li>`;

      const moreCard = document.querySelector('#more .cb-mobile-more-card');
      if (moreCard && !moreCard.querySelector('a[href="#player_development"]')) {
        const link = document.createElement('a');
        link.className = 'cb-mobile-more-link';
        link.href = '#player_development';
        link.setAttribute('data-bs-toggle', 'tab');
        link.setAttribute('role', 'tab');
        link.innerHTML = '<span class="cb-mobile-more-icon"><i class="bi bi-graph-up-arrow"></i></span><span class="cb-mobile-more-copy"><strong>Development</strong><small>Player priorities, progress, and coaching focus.</small></span><span class="cb-mobile-more-arrow"><i class="bi bi-chevron-right"></i></span>';
        moreCard.prepend(link);
      }
    };

    update();
    window.setTimeout(update, 250);
  }

  async function buildModel() {
    const [overview, games, practices, roster, sessionData, pitchingSettings, armCare] = await Promise.all([
      getJson('/api/overview_data', {}),
      getJson('/api/games', []),
      getJson('/api/practice_plans', []),
      getJson('/api/roster', []),
      getJson('/api/session_data', {}),
      getJson('/api/pitching-preferences/settings', {}),
      getJson('/api/pitching-preferences/arm-care-summary', {}),
    ]);

    const gameList = games || [];
    const fallbackNextGame = [...gameList]
      .filter(game => dateOnlyKey(game.date) >= localStartOfTodayMs())
      .sort((a, b) => dateOnlyKey(a.date) - dateOnlyKey(b.date) || Number(a.id || 0) - Number(b.id || 0))[0] || null;
    // The older overview endpoint compared date-only game records to the exact
    // current clock time. Fall back to the schedule so a game today remains on
    // Home throughout the day rather than disappearing after midnight/start time.
    const nextGame = overview?.next_game || fallbackNextGame;
    let readiness = {};
    let rules = {};
    if (nextGame?.id) {
      const [readyPayload, rulesPayload] = await Promise.all([
        getJson(`/api/game-day/${nextGame.id}/readiness`, {}),
        getJson(`/api/game-day/${nextGame.id}/pitching-rules`, {}),
      ]);
      readiness = readyPayload?.readiness || {};
      rules = rulesPayload || {};
    }

    const now = Date.now();
    const nextPractice = [...(practices || [])]
      .filter(plan => dateOnlyKey(plan.date) >= now - 86400000)
      .sort((a, b) => dateOnlyKey(a.date) - dateOnlyKey(b.date))[0] || null;
    const liveGame = gameList.find(game => Boolean(game.is_live)) || null;
    const pitcherCount = (roster || []).filter(player => player.pitcher_role && player.pitcher_role !== 'Not a Pitcher').length;
    const incompleteProfiles = (roster || []).filter(player => !(player.number && player.position1 && player.throws && player.bats)).length;
    const armPlayers = armCare?.players || {};
    const armCareConcerns = Object.entries(armPlayers).filter(([, item]) => {
      const status = String(item?.status || '');
      return status && status !== 'Available';
    });

    return {
      overview: overview || {},
      games: gameList,
      practices: practices || [],
      roster: roster || [],
      session: sessionData || {},
      pitchingSettings: pitchingSettings || {},
      armCare: armCare || {},
      armCareConcerns,
      nextGame,
      nextPractice,
      liveGame,
      readiness,
      rules,
      pitcherCount,
      incompleteProfiles,
    };
  }

  function guardAgainstLegacyOverview() {
    const container = document.getElementById('overview-content-container');
    if (!container || observer) return;
    observer = new MutationObserver(() => {
      if (rendering || !cachedModel) return;
      if (!container.querySelector('.cb-home-dashboard')) {
        window.setTimeout(() => render(cachedModel), 0);
      }
    });
    observer.observe(container, {childList: true, subtree: true});
  }

  async function init() {
    installMobileNav();
    const container = document.getElementById('overview-content-container');
    if (container) {
      container.innerHTML = '<div class="cb-home-loading"><div class="spinner-border spinner-border-sm" role="status"></div><span>Building your coaching home...</span></div>';
    }

    cachedModel = await buildModel();
    render(cachedModel);
    guardAgainstLegacyOverview();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
