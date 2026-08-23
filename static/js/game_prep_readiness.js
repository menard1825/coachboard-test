(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);
  const ID = 'coach-game-readiness-v2';
  let actionsBound = false;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function styles() {
    if (document.getElementById(`${ID}-styles`)) return;
    const style = document.createElement('style');
    style.id = `${ID}-styles`;
    style.textContent = `
      #${ID}{border:1px solid #e1e5ea;border-radius:13px;background:#fff;margin:0 0 14px;overflow:hidden;box-shadow:0 1px 3px rgba(16,24,40,.05)}
      #${ID}.ready{border-color:#b9dcc4;background:#f7fcf8}#${ID}.needs{border-color:#eed4a4;background:#fffdf8}
      .cgr-head{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:10px 12px;border-bottom:1px solid rgba(0,0,0,.06)}
      .cgr-head strong{font-size:.82rem;color:#172033}.cgr-head small{display:block;font-size:.65rem;color:#667085;margin-top:1px}.cgr-badge{border-radius:999px;padding:4px 8px;font-size:.59rem;font-weight:900;letter-spacing:.06em;white-space:nowrap}.ready .cgr-badge{background:#176b38;color:#fff}.needs .cgr-badge{background:#8b5c00;color:#fff}
      .cgr-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;padding:10px 12px}.cgr-item{appearance:none;-webkit-appearance:none;width:100%;border:1px solid #e2e6eb;border-radius:9px;padding:7px 8px;background:#fff;text-align:left;cursor:pointer}.cgr-item.good{border-color:#cce7d4;background:#f8fcf9}.cgr-item.need{border-color:#efd8ac;background:#fffaf0}.cgr-item.optional{background:#f8f9fb;border-color:#e4e7ec}.cgr-item:focus-visible{outline:3px solid rgba(18,56,123,.16);outline-offset:1px}.cgr-l{display:flex;justify-content:space-between;gap:5px;align-items:center;font-size:.54rem;text-transform:uppercase;letter-spacing:.07em;font-weight:850;color:#667085}.cgr-l i{font-size:.64rem}.cgr-v{font-size:.72rem;font-weight:800;color:#1d2939;margin-top:2px;line-height:1.2}.cgr-blockers{padding:0 12px 10px;font-size:.68rem;color:#8b5c00}.cgr-blockers div{display:flex;gap:6px;align-items:flex-start}.cgr-blockers div+div{margin-top:3px}.cgr-blockers i{margin-top:1px;flex:0 0 auto}
      @media(max-width:767.98px){
        html body.coach-game-page #pregame-defense-editor-v3 .pde-field .pde-spot{
          width:64px!important;min-height:38px!important;padding:3px 2px!important;
        }
        html body.coach-game-page #pregame-defense-editor-v3 .pde-field .pde-spot .pde-pos{
          font-size:.4rem!important;line-height:1!important;margin-bottom:1px!important;
        }
        html body.coach-game-page #pregame-defense-editor-v3 .pde-field .pde-spot .pde-name{
          display:-webkit-box!important;
          -webkit-box-orient:vertical;
          -webkit-line-clamp:2;
          max-width:100%;
          overflow:hidden!important;
          white-space:normal!important;
          overflow-wrap:anywhere;
          word-break:normal;
          font-size:clamp(.56rem,2.35vw,.62rem)!important;
          line-height:1.05!important;
          text-align:center;
        }
        html body.coach-game-page #diamond-parent-mobile .position-dropzone .player-tag{
          white-space:normal!important;
          overflow-wrap:anywhere;
          word-break:normal;
          font-size:.7rem!important;
          line-height:1.05!important;
          padding:3px 4px!important;
        }
      }
      @media(max-width:379.98px){
        html body.coach-game-page #pregame-defense-editor-v3 .pde-field .pde-spot{width:60px!important}
        html body.coach-game-page #pregame-defense-editor-v3 .pde-field .pde-spot .pde-name{font-size:.54rem!important}
      }
      @media(max-width:575.98px){
        #${ID}{margin-bottom:9px;border-radius:12px}
        .cgr-grid{grid-template-columns:1fr 1fr;gap:6px;padding:8px 9px}
        .cgr-head{padding:8px 9px}
        .cgr-head strong{font-size:.78rem}.cgr-head small{font-size:.61rem}
        .cgr-item{min-height:57px;padding:7px 8px}
        .cgr-v{font-size:.7rem}.cgr-blockers{padding:0 10px 8px;font-size:.66rem}
      }
      @media(orientation:landscape) and (max-height:900px){.cgr-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}
    `;
    document.head.appendChild(style);
  }

  function item(label, state, value, action) {
    return `<button type="button" class="cgr-item ${state}" data-cgr-action="${esc(action)}" aria-label="${esc(`${label}: ${value}. Review ${label}.`)}"><div class="cgr-l"><span>${esc(label)}</span><i class="bi bi-chevron-right" aria-hidden="true"></i></div><div class="cgr-v">${esc(value)}</div></button>`;
  }

  function inningPhrase(values) {
    const innings = [...new Set((values || []).map((value) => Number.parseInt(value, 10)).filter(Number.isFinite))].sort((a, b) => a - b);
    if (!innings.length) return '';

    const ranges = [];
    let start = innings[0];
    let previous = innings[0];
    for (let index = 1; index <= innings.length; index += 1) {
      const current = innings[index];
      if (current === previous + 1) {
        previous = current;
        continue;
      }
      ranges.push(start === previous ? String(start) : `${start}–${previous}`);
      start = current;
      previous = current;
    }
    return `${innings.length === 1 ? 'inning' : 'innings'} ${ranges.join(', ')}`;
  }

  function coachBlockers(r) {
    const result = [];
    const incomplete = Array.isArray(r.incomplete_innings) ? r.incomplete_innings : [];

    if (!r.defense_ready) {
      const first = incomplete.find((item) => String(item?.inning) === '1');
      const firstMissing = Array.isArray(first?.missing) ? first.missing : [];
      const startingPitcherOnly = firstMissing.length === 1 && firstMissing[0] === 'P';
      if (startingPitcherOnly) result.push('Choose the starting pitcher for the 1st inning.');

      const otherIncomplete = incomplete.filter((item) => !(String(item?.inning) === '1' && startingPitcherOnly));
      const phrase = inningPhrase(otherIncomplete.map((item) => item?.inning));
      if (phrase) result.push(`Finish the defense for ${phrase}.`);
      else if (!startingPitcherOnly) result.push(`Set the defense for all ${r.regulation_innings || r.defense_innings || ''} innings.`.replace('all  innings', 'the game'));
    }

    (r.blockers || []).forEach((raw) => {
      const text = String(raw || '').trim();
      const lower = text.toLowerCase();
      if (!text || lower.includes('defense needs attention') || lower.includes('defensive rotation') || lower.includes('starting pitcher')) return;
      if (lower === 'batting lineup is not set.') {
        result.push('Set the batting order.');
      } else if (lower.startsWith('bat everyone requires')) {
        result.push(`Add all ${r.lineup_expected_count || r.present_count || ''} available players to the batting order.`.replace('all  available', 'all available'));
      } else if (lower.startsWith('fixed lineup requires')) {
        result.push(`Set ${r.lineup_expected_count || ''} hitters in the batting order.`.replace('Set  hitters', 'Set the batting order'));
      } else if (lower.startsWith('remove unavailable lineup player')) {
        result.push(text.replace(/^Remove unavailable lineup player\(s\):/i, 'Remove unavailable player(s) from the batting order:').replace(/…\.$/, '…'));
      } else if (lower.startsWith('no available players')) {
        result.push('Mark at least one player available for this game.');
      } else {
        result.push(text.replace(/…\.$/, '…'));
      }
    });

    return [...new Set(result)];
  }

  function render(r) {
    const host = document.getElementById('pregame-checklist-container');
    if (!host || r.is_live) {
      document.getElementById(ID)?.remove();
      return;
    }
    let panel = document.getElementById(ID);
    if (!panel) {
      panel = document.createElement('section');
      panel.id = ID;
      const heading = host.querySelector(':scope > .d-flex:first-child');
      if (heading) heading.insertAdjacentElement('afterend', panel);
      else host.prepend(panel);
    }

    const blockers = coachBlockers(r);
    const count = blockers.length;
    const heading = r.ready
      ? 'Ready for first pitch'
      : `${count} pregame item${count === 1 ? '' : 's'} ${count === 1 ? 'needs' : 'need'} attention`;
    const subtitle = r.ready
      ? 'Availability, batting order, and defense are ready.'
      : 'Tap a box to review or make changes.';
    const defenseValue = r.defense_ready
      ? `${r.regulation_innings || r.defense_innings} innings ready`
      : `${r.defense_completed_innings || 0} of ${r.regulation_innings || r.defense_innings || 0} innings`;
    const lineupValue = r.lineup_ready ? `${r.lineup_count} hitters` : 'Needs attention';
    const availabilityValue = r.absent_count ? `${r.absent_count} out` : 'Everyone available';
    const pitchingValue = r.pitching_plan_ready ? `${r.pitching_plan_count} planned` : 'Optional';

    panel.className = r.ready ? 'ready' : 'needs';
    panel.innerHTML = `
      <div class="cgr-head"><div><strong>${esc(heading)}</strong><small>${esc(subtitle)}</small></div><span class="cgr-badge">${r.ready ? 'READY' : 'TO DO'}</span></div>
      <div class="cgr-grid">
        ${item("Who's Out", r.present_count > 0 ? 'good' : 'need', availabilityValue, 'availability')}
        ${item('Batting Order', r.lineup_ready ? 'good' : 'need', lineupValue, 'lineup')}
        ${item('Defense', r.defense_ready ? 'good' : 'need', defenseValue, 'defense')}
        ${item('Pitch Plan', r.pitching_plan_ready ? 'good' : 'optional', pitchingValue, 'pitching')}
      </div>
      ${blockers.length ? `<div class="cgr-blockers">${blockers.map((text) => `<div><i class="bi bi-exclamation-circle" aria-hidden="true"></i><span>${esc(text)}</span></div>`).join('')}</div>` : ''}`;
  }

  function scrollTo(target) {
    target?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  function runAction(action) {
    if (action === 'availability') {
      const trigger = document.getElementById('availabilityToggleBtn');
      if (trigger) trigger.click();
      else scrollTo(document.getElementById('availabilityCollapse'));
      return;
    }
    if (action === 'lineup') {
      const modal = document.getElementById('lineupEditorModal');
      if (modal && window.bootstrap?.Modal) {
        window.bootstrap.Modal.getOrCreateInstance(modal).show();
      } else {
        document.querySelector('[data-bs-target="#lineupEditorModal"]')?.click();
      }
      return;
    }
    if (action === 'defense') {
      scrollTo(document.getElementById('rotation-card-container'));
      return;
    }
    if (action === 'pitching') {
      scrollTo(document.getElementById('pitcher-availability-card') || document.getElementById('pitching-log-container'));
    }
  }

  function bindActions() {
    if (actionsBound) return;
    actionsBound = true;
    document.addEventListener('click', (event) => {
      const button = event.target.closest(`#${ID} [data-cgr-action]`);
      if (!button) return;
      event.preventDefault();
      runAction(button.dataset.cgrAction);
    });
  }

  async function refresh() {
    try {
      const response = await fetch(`/api/game-day/${gameId}/readiness`, {cache:'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      if (data?.readiness) render(data.readiness);
    } catch (_) {}
  }

  styles();
  bindActions();
  const start = () => { refresh(); window.setInterval(refresh, 5000); };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start, {once:true}) : start();
})();