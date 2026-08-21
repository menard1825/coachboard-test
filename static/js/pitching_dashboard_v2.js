(() => {
  'use strict';

  if (window.location.pathname !== '/pitching') return;
  if (window.CoachBoardPitchingDashboardV2?.initialized) return;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function cardByHeading(text) {
    return [...document.querySelectorAll('main .card')]
      .find(card => card.querySelector('h5')?.textContent.trim() === text) || null;
  }

  function installStyles() {
    if (document.getElementById('pitching-dashboard-v2-styles')) return;
    const style = document.createElement('style');
    style.id = 'pitching-dashboard-v2-styles';
    style.textContent = `
      body.cb-pitching main>.container-fluid{max-width:1180px;margin:0 auto}
      body.cb-pitching main>.container-fluid>.d-flex:first-child h3{font-size:1.55rem;font-weight:850;letter-spacing:-.02em;color:#172033}
      .cb-pitch-status-shell{padding:14px;background:#f7f8fa}
      .cb-pitch-counts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:14px}
      .cb-pitch-count{border:1px solid #e1e5ea;background:#fff;border-radius:11px;padding:10px 11px}
      .cb-pitch-count span{display:block;font-size:.61rem;text-transform:uppercase;letter-spacing:.06em;color:#667085;font-weight:800}
      .cb-pitch-count strong{display:block;margin-top:2px;font-size:1.18rem;line-height:1.05;color:#1d2939}
      .cb-pitch-group+.cb-pitch-group{margin-top:15px}
      .cb-pitch-group-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:0 1px 8px}
      .cb-pitch-group-head strong{font-size:.72rem;text-transform:uppercase;letter-spacing:.07em;color:#475467}
      .cb-pitch-group-head span{font-size:.66rem;color:#8a94a3}
      .cb-pitch-card-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
      .cb-pitcher-card{border:1px solid #dfe4ea;border-radius:14px;background:#fff;box-shadow:0 1px 3px rgba(16,24,40,.05);overflow:hidden;min-width:0}
      .cb-pitcher-card[data-available="false"]{border-color:#ead7b5}
      .cb-pitcher-top{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:12px 13px 9px}
      .cb-pitcher-name{font-size:.98rem;font-weight:850;color:#172033;line-height:1.15}
      .cb-pitcher-last{font-size:.64rem;color:#8a94a3;margin-top:3px}
      .cb-pitch-status{font-size:.6rem;font-weight:850;border-radius:999px;padding:5px 8px;white-space:nowrap}
      .cb-pitch-status.available{background:#e9f7ee;color:#176b38}
      .cb-pitch-status.warning{background:#fff3d8;color:#8a5800}
      .cb-pitch-status.danger{background:#feecec;color:#a32929}
      .cb-pitch-decision{margin:0 12px 10px;padding:10px 11px;border:1px solid #e3e7ec;border-radius:10px;background:#f8fafc}
      .cb-pitcher-card[data-available="false"] .cb-pitch-decision{background:#fffaf1;border-color:#ecd9b4}
      .cb-pitch-kicker{display:block;font-size:.57rem;text-transform:uppercase;letter-spacing:.07em;font-weight:850;color:#667085}
      .cb-pitch-decision strong{display:block;font-size:.85rem;color:#1d2939;margin-top:2px}
      .cb-pitch-decision .cb-pitch-detail{font-size:.65rem;color:#667085;line-height:1.35;margin-top:3px}
      .pitch-arm-care-slot{margin:0 12px 10px;padding:9px 10px;border:1px solid #e7eaf0;border-radius:10px;background:#fff}
      .cb-pitch-arm-row{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
      .cb-pitch-arm-title{font-size:.6rem;text-transform:uppercase;letter-spacing:.06em;color:#667085;font-weight:850}
      .cb-pitch-arm-value{font-size:.68rem;font-weight:800;color:#344054;text-align:right}
      .cb-pitch-arm-next{font-size:.63rem;color:#8a5a13;margin-top:3px;text-align:right}
      .cb-pitch-arm-detail{font-size:.61rem;color:#7b8492;line-height:1.3;margin-top:4px}
      .cb-pitch-metrics{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #edf0f3;border-bottom:1px solid #edf0f3}
      .cb-pitch-metric{padding:10px 12px;min-width:0}
      .cb-pitch-metric+.cb-pitch-metric{border-left:1px solid #edf0f3}
      .cb-pitch-metric>.cb-pitch-kicker{margin-bottom:3px}
      .cb-pitch-metric .fw-bold{font-size:.78rem;color:#1d2939}
      .cb-pitch-metric .small{font-size:.62rem;line-height:1.35}
      .cb-pitch-target{padding:10px 12px;background:#fcfcfd}
      .cb-pitch-target>.cb-pitch-kicker{margin-bottom:3px}
      .cb-pitch-target .fw-bold{font-size:.76rem}
      .cb-pitch-target .btn-link{font-size:.68rem;font-weight:750;text-decoration:none;min-height:34px}
      .cb-pitch-target br{display:none}
      .cb-pitch-source{display:none!important}
      .cb-pitch-history-tools{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-top:9px}
      .cb-pitch-history-tools .form-select{min-height:38px;font-size:.72rem;border-radius:8px;min-width:145px}
      .cb-pitch-history-count{font-size:.65rem;color:#667085;margin-left:auto}
      .cb-pitch-history-empty{padding:22px;text-align:center;color:#667085;font-size:.76rem}
      body.cb-pitching #newPitchingOutingForm .form-control,
      body.cb-pitching #newPitchingOutingForm .form-select,
      body.cb-pitching #editPitchingOutingForm .form-control,
      body.cb-pitching #editPitchingOutingForm .form-select{min-height:46px;border-radius:9px}
      body.cb-pitching #newPitchingOutingForm button[type="submit"]{min-height:48px;border-radius:10px;font-weight:800}
      body.cb-pitching .list-group-item .btn{min-height:38px}
      .cb-pitch-save-feedback{font-size:.68rem;font-weight:700;margin-right:auto}
      @media(max-width:767.98px){
        .cb-pitch-status-shell{padding:10px}
        .cb-pitch-card-grid{grid-template-columns:1fr}
        .cb-pitch-counts{grid-template-columns:repeat(3,minmax(0,1fr))}
        .cb-pitch-count{padding:8px}
        .cb-pitch-count strong{font-size:1rem}
        .cb-pitch-metric{padding:9px 10px}
        body.cb-pitching main>.container-fluid>.d-flex:first-child{align-items:flex-start!important}
        body.cb-pitching main>.container-fluid>.d-flex:first-child .btn{width:100%;margin-top:4px;min-height:44px}
        .cb-pitch-history-tools{display:grid;grid-template-columns:1fr 1fr;width:100%}
        .cb-pitch-history-tools .form-select{min-width:0;width:100%;min-height:44px}
        .cb-pitch-history-count{grid-column:1 / -1;margin-left:0}
      }
      @media(max-width:390px){
        .cb-pitch-counts{grid-template-columns:1fr}
        .cb-pitch-count{display:flex;align-items:center;justify-content:space-between;gap:10px}
        .cb-pitch-count strong{font-size:1rem;margin-top:0}
      }
    `;
    document.head.appendChild(style);
  }

  function statusKind(status) {
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'available') return 'available';
    if (normalized.includes('verify') || normalized.includes('incomplete') || normalized.includes('restriction')) return 'warning';
    return 'danger';
  }

  function decisionCopy(status, nextAvailable) {
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'available') return 'Eligible today';
    if (normalized.includes('verify') || normalized.includes('incomplete')) return 'Verify pitching history';
    if (normalized.includes('rules not selected') || normalized.includes('verify rules')) return 'Competition rules needed';
    if (nextAvailable && !/^verify/i.test(nextAvailable)) return `Next Available: ${nextAvailable}`;
    return status || 'Eligibility needs attention';
  }

  function nextFromCell(cell) {
    const line = [...cell.querySelectorAll('div')]
      .find(node => /^Next\s*:/i.test(node.textContent.trim()));
    return line ? line.textContent.replace(/^Next\s*:\s*/i, '').trim() : '';
  }

  function statusDetailFromCell(cell) {
    const candidates = [...cell.querySelectorAll('.small.text-muted')];
    return candidates.map(node => node.textContent.trim()).find(Boolean) || '';
  }

  function makePitcherCard(row) {
    const cells = [...row.children];
    if (cells.length < 5) return null;
    const name = cells[0].querySelector('.fw-bold')?.textContent.trim();
    if (!name) return null;
    const targetButton = cells[4].querySelector('.open-target-modal');
    const playerId = targetButton?.dataset.playerId || '';
    const status = cells[1].querySelector('.badge')?.textContent.trim() || 'Available';
    const available = status === 'Available';
    const nextAvailable = nextFromCell(cells[1]);
    const detail = statusDetailFromCell(cells[1]);
    const last = cells[0].querySelector('.small')?.textContent.trim() || '';

    const card = document.createElement('article');
    card.className = 'cb-pitcher-card';
    card.dataset.playerName = name;
    card.dataset.playerId = playerId;
    card.dataset.officialStatus = status;
    card.dataset.available = available ? 'true' : 'false';
    card.innerHTML = `
      <div class="cb-pitcher-top">
        <div><div class="cb-pitcher-name">${esc(name)}</div>${last ? `<div class="cb-pitcher-last">${esc(last)}</div>` : ''}</div>
        <span class="cb-pitch-status ${statusKind(status)}">${esc(status)}</span>
      </div>
      <div class="cb-pitch-decision">
        <span class="cb-pitch-kicker">Competition eligibility</span>
        <strong>${esc(decisionCopy(status, nextAvailable))}</strong>
        ${detail ? `<div class="cb-pitch-detail">${esc(detail)}</div>` : ''}
      </div>
      <div class="pitch-arm-care-slot" data-player-name="${esc(name)}">
        <div class="cb-pitch-arm-row"><span class="cb-pitch-arm-title">Arm care</span><span class="cb-pitch-arm-value text-muted">Loading…</span></div>
      </div>
      <div class="cb-pitch-metrics">
        <div class="cb-pitch-metric"><span class="cb-pitch-kicker">Official today</span>${cells[2].innerHTML}</div>
        <div class="cb-pitch-metric"><span class="cb-pitch-kicker">Throwing workload</span>${cells[3].innerHTML}</div>
      </div>
      <div class="cb-pitch-target" data-target-slot="true"><span class="cb-pitch-kicker">Pitch target</span>${cells[4].innerHTML}</div>`;

    card.querySelectorAll('.open-target-modal').forEach(bindFreshTargetButton);
    return card;
  }

  function groupMarkup(title, note, cards) {
    const group = document.createElement('section');
    group.className = 'cb-pitch-group';
    group.innerHTML = `<div class="cb-pitch-group-head"><strong>${esc(title)}</strong>${note ? `<span>${esc(note)}</span>` : ''}</div><div class="cb-pitch-card-grid"></div>`;
    const grid = group.querySelector('.cb-pitch-card-grid');
    cards.forEach(card => grid.appendChild(card));
    return group;
  }

  function upgradeStatusBoard() {
    const statusCard = cardByHeading('Who Can Pitch?');
    if (!statusCard || statusCard.dataset.cbPitchingV2 === '1') return;
    const tableWrap = statusCard.querySelector('.table-responsive');
    const table = tableWrap?.querySelector('table');
    if (!table) return;

    const cards = [...table.querySelectorAll('tbody tr')].map(makePitcherCard).filter(Boolean);
    if (!cards.length) return;
    const available = cards.filter(card => card.dataset.available === 'true');
    const attention = cards.filter(card => card.dataset.available !== 'true');
    const verify = attention.filter(card => /verify|incomplete/i.test(card.dataset.officialStatus || ''));

    statusCard.dataset.cbPitchingV2 = '1';
    tableWrap.classList.add('cb-pitch-source');
    const heading = statusCard.querySelector('.card-header h5');
    if (heading) heading.textContent = 'Pitcher Availability';
    const subtitle = statusCard.querySelector('.card-header .small.text-muted');
    if (subtitle) subtitle.textContent = '';

    const shell = document.createElement('div');
    shell.className = 'cb-pitch-status-shell';
    shell.innerHTML = `
      <div class="cb-pitch-counts" aria-label="Pitcher availability summary">
        <div class="cb-pitch-count"><span>Eligible Today</span><strong>${available.length}</strong></div>
        <div class="cb-pitch-count"><span>Unavailable / Verify</span><strong>${attention.length}</strong></div>
        <div class="cb-pitch-count"><span>Verify Data</span><strong>${verify.length}</strong></div>
      </div>`;
    if (available.length) shell.appendChild(groupMarkup('Eligible Today', '', available));
    if (attention.length) shell.appendChild(groupMarkup('Unavailable / Verify', '', attention));
    tableWrap.insertAdjacentElement('beforebegin', shell);
  }

  function historyItems(card) {
    return [...card.querySelectorAll('.list-group > .list-group-item')]
      .filter(item => item.querySelector('[data-outing-id]'));
  }

  function enhanceHistory() {
    const card = cardByHeading('Recent Throwing History');
    if (!card || card.dataset.cbPitchingHistoryV2 === '1') return;
    const items = historyItems(card);
    if (!items.length) return;
    card.dataset.cbPitchingHistoryV2 = '1';

    const players = new Map();
    items.forEach(item => {
      const edit = item.querySelector('[data-outing-id]');
      const playerId = edit?.dataset.playerId || '';
      const name = item.querySelector('strong')?.textContent.trim() || 'Unknown';
      const date = edit?.dataset.date || '';
      item.dataset.pitchHistoryPlayer = playerId;
      item.dataset.pitchHistoryDate = date;
      if (playerId) players.set(playerId, name);
    });

    const header = card.querySelector('.card-header');
    const tools = document.createElement('div');
    tools.className = 'cb-pitch-history-tools';
    tools.innerHTML = `
      <select class="form-select form-select-sm" id="cbPitchHistoryPlayer" aria-label="Filter throwing history by pitcher">
        <option value="">All pitchers</option>
        ${[...players.entries()].sort((a,b) => a[1].localeCompare(b[1])).map(([id,name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join('')}
      </select>
      <select class="form-select form-select-sm" id="cbPitchHistoryRange" aria-label="Filter throwing history by date">
        <option value="7">Last 7 days</option>
        <option value="30">Last 30 days</option>
        <option value="all">All recent</option>
      </select>
      <span class="cb-pitch-history-count" id="cbPitchHistoryCount"></span>`;
    header?.appendChild(tools);

    const list = card.querySelector('.list-group');
    const empty = document.createElement('div');
    empty.className = 'cb-pitch-history-empty d-none';
    empty.textContent = 'No throwing records match these filters.';
    list?.insertAdjacentElement('afterend', empty);

    const apply = () => {
      const selectedPlayer = tools.querySelector('#cbPitchHistoryPlayer')?.value || '';
      const range = tools.querySelector('#cbPitchHistoryRange')?.value || '7';
      const today = new Date();
      today.setHours(12,0,0,0);
      let visible = 0;
      items.forEach(item => {
        const playerOk = !selectedPlayer || item.dataset.pitchHistoryPlayer === selectedPlayer;
        let dateOk = true;
        if (range !== 'all' && item.dataset.pitchHistoryDate) {
          const date = new Date(`${item.dataset.pitchHistoryDate}T12:00:00`);
          const diff = Math.floor((today - date) / 86400000);
          dateOk = diff >= 0 && diff < Number(range);
        }
        const show = playerOk && dateOk;
        item.classList.toggle('d-none', !show);
        if (show) visible += 1;
      });
      const count = tools.querySelector('#cbPitchHistoryCount');
      if (count) count.textContent = `Showing ${visible} of ${items.length}`;
      empty.classList.toggle('d-none', visible !== 0);
    };
    tools.querySelectorAll('select').forEach(select => select.addEventListener('change', apply));
    apply();
  }

  function bindFreshTargetButton(button) {
    if (!button || button.dataset.cbPitchTargetV2 === '1') return;
    button.dataset.cbPitchTargetV2 = '1';
    button.addEventListener('click', () => {
      if (typeof window.openTargetModal === 'function') window.openTargetModal(button);
    });
  }

  function plannedTargetsCard(root = document) {
    return [...root.querySelectorAll('.card')]
      .find(card => card.querySelector('h5')?.textContent.trim() === 'Planned Game-Pitch Targets') || null;
  }

  async function refreshTargetUi(playerId) {
    const response = await fetch('/pitching', {cache:'no-store', headers:{'X-CoachBoard-Refresh':'pitching-target'}});
    if (!response.ok) return;
    const html = await response.text();
    const parsed = new DOMParser().parseFromString(html, 'text/html');

    const currentPlans = plannedTargetsCard(document);
    const freshPlans = plannedTargetsCard(parsed);
    if (currentPlans && freshPlans) {
      const imported = document.importNode(freshPlans, true);
      currentPlans.replaceWith(imported);
      imported.querySelectorAll('.open-target-modal').forEach(bindFreshTargetButton);
    }

    const selector = `.open-target-modal[data-player-id="${CSS.escape(String(playerId))}"][data-game-id=""]`;
    const freshButton = parsed.querySelector(selector);
    const freshCell = freshButton?.closest('td');
    const card = document.querySelector(`.cb-pitcher-card[data-player-id="${CSS.escape(String(playerId))}"]`);
    const slot = card?.querySelector('[data-target-slot]');
    if (slot && freshCell) {
      slot.innerHTML = `<span class="cb-pitch-kicker">Pitch target</span>${freshCell.innerHTML}`;
      slot.querySelectorAll('.open-target-modal').forEach(bindFreshTargetButton);
    }
  }

  function toast(message, kind = 'success') {
    let holder = document.getElementById('cb-pitching-toast-holder');
    if (!holder) {
      holder = document.createElement('div');
      holder.id = 'cb-pitching-toast-holder';
      holder.className = 'toast-container position-fixed top-0 end-0 p-3';
      holder.style.zIndex = '2000';
      document.body.appendChild(holder);
    }
    const el = document.createElement('div');
    el.className = `toast align-items-center text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    holder.appendChild(el);
    if (typeof bootstrap !== 'undefined') {
      const instance = bootstrap.Toast.getOrCreateInstance(el, {delay:2600});
      el.addEventListener('hidden.bs.toast', () => el.remove(), {once:true});
      instance.show();
    } else {
      window.setTimeout(() => el.remove(), 2600);
    }
  }

  function replaceTargetSaveHandler() {
    const original = document.getElementById('saveTargetBtn');
    if (!original || original.dataset.cbPitchTargetSaveV2 === '1') return;
    const button = original.cloneNode(true);
    button.dataset.cbPitchTargetSaveV2 = '1';
    original.replaceWith(button);

    button.addEventListener('click', async () => {
      const playerInput = document.getElementById('targetPlayerInput');
      const scopeInput = document.getElementById('targetScopeInput');
      const gameSelect = document.getElementById('targetGameInput');
      const dateInput = document.getElementById('targetDateInput');
      const pitchesInput = document.getElementById('targetPitchesInput');
      const reasonInput = document.getElementById('targetReasonInput');
      const playerId = playerInput?.value || '';
      const scope = scopeInput?.value || 'day';
      const gameId = scope === 'game' ? (gameSelect?.value || '') : '';
      if (!playerId) { playerInput?.focus(); return; }
      if (scope === 'game' && !gameId) { gameSelect?.focus(); return; }
      const selectedGame = gameSelect?.selectedOptions?.[0];
      const targetDate = scope === 'game' ? selectedGame?.dataset.date : dateInput?.value;
      if (!targetDate) { dateInput?.focus(); return; }
      const raw = pitchesInput?.value.trim() || '';

      button.disabled = true;
      const oldText = button.textContent;
      button.textContent = 'Saving…';
      try {
        const response = await fetch('/save_player_target', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({
            player_id:playerId,
            target_pitches:raw === '' ? null : Number(raw),
            local_date:targetDate,
            game_id:gameId || null,
            reason:reasonInput?.value.trim() || null,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status !== 'success') throw new Error(data.message || 'Unable to save target.');
        bootstrap.Modal.getOrCreateInstance(document.getElementById('coachTargetModal')).hide();
        await refreshTargetUi(playerId);
        toast(raw === '' ? 'Pitch target cleared.' : 'Pitch target saved.');
      } catch (error) {
        toast(error.message || 'Unable to save target.', 'danger');
      } finally {
        button.disabled = false;
        button.textContent = oldText;
      }
    });
  }

  function polishHeader() {
    const root = document.querySelector('main > .container-fluid.pb-4');
    const head = root?.querySelector(':scope > .d-flex:first-child');
    const title = head?.querySelector('h3');
    const subtitle = title?.nextElementSibling;
    if (title) title.textContent = 'Pitching';
    if (subtitle) subtitle.textContent = 'Competition eligibility, arm-care guidance, workload, and pitch targets.';
  }

  function init() {
    installStyles();
    polishHeader();
    upgradeStatusBoard();
    enhanceHistory();
    replaceTargetSaveHandler();
    window.CoachBoardPitchingDashboardV2 = {
      initialized:true,
      refreshTargetUi,
      upgradeStatusBoard,
      enhanceHistory,
    };
    document.dispatchEvent(new CustomEvent('coachboard:pitching-dashboard-ready'));
  }

  init();
})();