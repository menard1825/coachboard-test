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

  // Older live-game socket handling still calls this retired helper after the
  // modern rotation renderer has already refreshed both bench reports. Keep a
  // harmless compatibility binding so a live state broadcast cannot throw.
  if (typeof window.renderBenchReport !== 'function') {
    window.renderBenchReport = () => {};
  }

  function styles() {
    if (document.getElementById(`${ID}-styles`)) return;
    const style = document.createElement('style');
    style.id = `${ID}-styles`;
    style.textContent = `
      #${ID}{border:1px solid #e1e5ea;border-radius:13px;background:#fff;margin:0 0 14px;overflow:hidden;box-shadow:0 1px 3px rgba(16,24,40,.05)}
      #${ID}.ready{border-color:#b9dcc4;background:#f7fcf8}#${ID}.needs{border-color:#e1e5ea;background:#fff}
      .cgr-head{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:10px 12px;border-bottom:1px solid rgba(0,0,0,.06)}
      .cgr-head strong{font-size:.82rem;color:#172033}.cgr-head small{display:block;font-size:.65rem;color:#667085;margin-top:1px}.cgr-badge{border-radius:999px;padding:4px 8px;font-size:.59rem;font-weight:900;letter-spacing:.06em;white-space:nowrap}.ready .cgr-badge{background:#176b38;color:#fff}.needs .cgr-badge{background:#eef2f6;color:#475467}
      .cgr-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;padding:10px 12px}.cgr-item{appearance:none;-webkit-appearance:none;width:100%;border:1px solid #e2e6eb;border-radius:9px;padding:7px 8px;background:#fff;text-align:left;cursor:pointer}.cgr-item.good{border-color:#cce7d4;background:#f8fcf9}.cgr-item.need{border-color:#efd8ac;background:#fffaf0}.cgr-item.optional{background:#f8f9fb;border-color:#e4e7ec}.cgr-item:focus-visible{outline:3px solid rgba(18,56,123,.16);outline-offset:1px}.cgr-l{display:flex;justify-content:space-between;gap:5px;align-items:center;font-size:.54rem;text-transform:uppercase;letter-spacing:.07em;font-weight:850;color:#667085}.cgr-l i{font-size:.64rem}.cgr-v{font-size:.72rem;font-weight:800;color:#1d2939;margin-top:2px;line-height:1.2}

      /* Player names are operational information. Never replace part of a name
         with an ellipsis on a field or board; wrap it inside the existing spot. */
      html body #pregame-defense-editor-v3 .pde-field .pde-spot .pde-name,
      html body #live-board-prep-v3 .bp-field-spot .name,
      html body .coach-field .coach-field-spot span,
      html body .coach-player-name,
      html body #live-board-prep-v3 .bp-move strong,
      html body #cbDugoutHeader .cb-dh-name{
        white-space:normal!important;
        overflow:visible!important;
        text-overflow:clip!important;
        overflow-wrap:anywhere!important;
        word-break:normal!important;
        max-height:none!important;
      }
      html body #pregame-defense-editor-v3 .pde-field .pde-spot .pde-name{
        display:block!important;
        -webkit-line-clamp:unset!important;
        -webkit-box-orient:initial!important;
        max-width:100%;
        text-align:center;
      }
      html body #live-board-prep-v3 .bp-field-spot .name,
      html body .coach-field .coach-field-spot span{
        height:auto!important;
        min-height:0!important;
        line-height:1.08!important;
      }
      html body #cbDugoutHeader .cb-dh-name{max-width:none!important;line-height:1.12!important}

      /* Jersey number stays useful in Live Game, but gets its own line so it
         never steals horizontal space from the player's actual name. */
      html body .coach-field .coach-field-spot span[data-cb-number]::before,
      html body #live-board-prep-v3 .bp-field-spot .name[data-cb-number]::before{
        content:'#' attr(data-cb-number)!important;
        display:block!important;
        margin:0 0 2px!important;
        font-size:.78em!important;
        line-height:1!important;
        font-weight:900!important;
      }

      @media(max-width:767.98px){
        html body.coach-game-page #pregame-defense-editor-v3 .pde-field .pde-spot{
          width:64px!important;min-height:38px!important;padding:3px 2px!important;
        }
        html body.coach-game-page #pregame-defense-editor-v3 .pde-field .pde-spot .pde-pos{
          font-size:.4rem!important;line-height:1!important;margin-bottom:1px!important;
        }
        html body.coach-game-page #pregame-defense-editor-v3 .pde-field .pde-spot .pde-name{
          font-size:clamp(.56rem,2.35vw,.62rem)!important;
          line-height:1.05!important;
        }
        html body.coach-game-page #diamond-parent-mobile .position-dropzone .player-tag{
          white-space:normal!important;
          overflow:visible!important;
          text-overflow:clip!important;
          overflow-wrap:anywhere!important;
          word-break:normal!important;
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
        .cgr-v{font-size:.7rem}
      }
      @media(orientation:landscape) and (max-height:900px){.cgr-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}
    `;
    document.head.appendChild(style);
  }

  function item(label, state, value, action) {
    return `<button type="button" class="cgr-item ${state}" data-cgr-action="${esc(action)}" aria-label="${esc(`${label}: ${value}. Review ${label}.`)}"><div class="cgr-l"><span>${esc(label)}</span><i class="bi bi-chevron-right" aria-hidden="true"></i></div><div class="cgr-v">${esc(value)}</div></button>`;
  }

  function clockSummary() {
    const clock = document.getElementById('cbPregameClock');
    if (!clock) return 'Optional';
    const text = String(clock.textContent || '').replace(/\s+/g, ' ').trim();
    const minutes = text.match(/(\d{1,3})\s*(?:min|minute)/i);
    if (minutes) return `${minutes[1]} min limit`;
    if (/no time limit/i.test(text)) return 'No time limit';
    return 'Optional';
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

    const coreReady = Boolean(r.present_count > 0 && r.lineup_ready && r.defense_ready);
    const heading = coreReady ? 'Pregame overview' : 'Pregame setup';
    const subtitle = coreReady
      ? 'Availability, batting order, and defense are ready.'
      : 'Tap a box to review or make changes.';
    const defenseValue = r.defense_ready
      ? `${r.regulation_innings || r.defense_innings} innings ready`
      : `${r.defense_completed_innings || 0} of ${r.regulation_innings || r.defense_innings || 0} innings`;
    const lineupValue = r.lineup_ready ? `${r.lineup_count} hitters` : 'Needs attention';
    const availabilityValue = r.present_count > 0
      ? (r.absent_count ? `${r.absent_count} out` : 'Everyone available')
      : 'Confirm availability';
    const clockValue = clockSummary();

    panel.className = coreReady ? 'ready' : 'needs';
    panel.innerHTML = `
      <div class="cgr-head"><div><strong>${esc(heading)}</strong><small>${esc(subtitle)}</small></div><span class="cgr-badge">${coreReady ? 'READY' : 'SETUP'}</span></div>
      <div class="cgr-grid">
        ${item('Player Availability', r.present_count > 0 ? 'good' : 'need', availabilityValue, 'availability')}
        ${item('Batting Order', r.lineup_ready ? 'good' : 'need', lineupValue, 'lineup')}
        ${item('Defense', r.defense_ready ? 'good' : 'need', defenseValue, 'defense')}
        ${item('Game Clock', 'optional', clockValue, 'clock')}
      </div>`;
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
    if (action === 'clock') {
      const clock = document.getElementById('cbPregameClock');
      scrollTo(clock);
      const button = [...(clock?.querySelectorAll('button') || [])].find((item) => /Set Time Limit/i.test(item.textContent || ''));
      button?.focus({preventScroll:true});
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