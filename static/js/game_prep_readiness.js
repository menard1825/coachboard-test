(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);
  const ID = 'coach-game-readiness-v2';

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
      .cgr-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;padding:10px 12px}.cgr-item{border:1px solid #e2e6eb;border-radius:9px;padding:7px 8px;background:#fff}.cgr-item.good{border-color:#cce7d4}.cgr-item.need{border-color:#efd8ac;background:#fffaf0}.cgr-l{font-size:.54rem;text-transform:uppercase;letter-spacing:.07em;font-weight:850;color:#667085}.cgr-v{font-size:.72rem;font-weight:800;color:#1d2939;margin-top:1px}.cgr-blockers{padding:0 12px 10px;font-size:.68rem;color:#8b5c00}.cgr-blockers div+div{margin-top:2px}
      @media(max-width:575.98px){.cgr-grid{grid-template-columns:1fr 1fr;padding:9px 10px}.cgr-head{padding:9px 10px}}
      @media(orientation:landscape) and (max-height:900px){.cgr-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}
    `;
    document.head.appendChild(style);
  }

  function item(label, good, value) {
    return `<div class="cgr-item ${good ? 'good' : 'need'}"><div class="cgr-l">${esc(label)}</div><div class="cgr-v">${esc(value)}</div></div>`;
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
    panel.className = r.ready ? 'ready' : 'needs';
    const blockers = (r.blockers || []).map((text) => `<div>${esc(text)}</div>`).join('');
    panel.innerHTML = `
      <div class="cgr-head"><div><strong>${r.ready ? 'Game setup is ready' : `${r.blockers.length} setup item${r.blockers.length === 1 ? '' : 's'} need attention`}</strong><small>Same readiness status shown on Game Day.</small></div><span class="cgr-badge">${r.ready ? 'READY' : 'PREP'}</span></div>
      <div class="cgr-grid">
        ${item('Availability', r.present_count > 0, `${r.present_count} present`)}
        ${item('Lineup', r.lineup_ready, r.lineup_ready ? `${r.lineup_count} set` : 'Not ready')}
        ${item('Defense', r.defense_ready, r.defense_ready ? `${r.defense_innings} innings` : 'Not ready')}
        ${item('Pitching Plan', r.pitching_plan_ready, r.pitching_plan_ready ? `${r.pitching_plan_count} planned` : 'Not set')}
      </div>
      ${blockers ? `<div class="cgr-blockers">${blockers}</div>` : ''}`;
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
  const start = () => { refresh(); window.setInterval(refresh, 5000); };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', start, {once:true}) : start();
})();
