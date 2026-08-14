(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const CARD_ID = 'live-board-prep-v3';
  const STYLE_ID = 'live-board-prep-v3-styles';
  let lastSignature = '';
  let busy = false;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${CARD_ID}{border:1px solid #dfe4ea;border-radius:14px;background:#fff;box-shadow:0 1px 3px rgba(16,24,40,.06);overflow:hidden;margin-bottom:10px}
      .bp-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:13px 14px 10px;border-bottom:1px solid #edf0f3}
      .bp-kicker{font-size:.65rem;text-transform:uppercase;letter-spacing:.1em;font-weight:850;color:#667085}
      .bp-title{font-size:1.02rem;font-weight:800;color:#172033;margin-top:2px}
      .bp-help{font-size:.72rem;color:#8a94a3;margin-top:2px}
      .bp-inning{min-width:62px;border-radius:10px;background:#172033;color:#fff;padding:7px 9px;text-align:center}
      .bp-inning small{display:block;font-size:.52rem;letter-spacing:.08em;opacity:.72;font-weight:750}.bp-inning strong{display:block;font-size:1.3rem;line-height:1.05}
      .bp-body{padding:12px 14px 14px}.bp-grid{display:grid;grid-template-columns:minmax(0,.85fr) minmax(0,1.35fr);gap:13px;align-items:start}
      .bp-label{font-size:.62rem;text-transform:uppercase;letter-spacing:.09em;font-weight:850;color:#667085;margin-bottom:7px}
      .bp-moves{display:flex;flex-direction:column;gap:6px}.bp-move{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border:1px solid #e3e7ec;background:#f8fafc;border-radius:9px;padding:8px 9px}
      .bp-move strong{display:block;font-size:.78rem;color:#1d2939;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bp-move small{display:block;font-size:.65rem;color:#7b8492;margin-top:1px}
      .bp-dest{min-width:46px;border-radius:7px;background:#172033;color:#fff;padding:5px 6px;text-align:center;font-size:.68rem;font-weight:800}.bp-dest.bench{background:#eef1f5;color:#475467}
      .bp-none{border:1px dashed #d6dce3;border-radius:9px;padding:11px;color:#667085;font-size:.75rem;text-align:center}
      .bp-board{border:1px solid #dfe6dd;border-radius:12px;padding:9px;background:linear-gradient(180deg,#f4f9f2 0%,#faf8ef 100%)}
      .bp-row{display:grid;gap:6px;margin-bottom:6px}.bp-row.of3{grid-template-columns:repeat(3,minmax(0,1fr))}.bp-row.of4{grid-template-columns:repeat(4,minmax(0,1fr))}.bp-row.if{grid-template-columns:repeat(4,minmax(0,1fr))}.bp-row.battery{grid-template-columns:repeat(2,minmax(0,1fr));max-width:68%;margin:0 auto 6px}
      .bp-slot{min-width:0;border:1px solid #dfe4e8;border-radius:8px;background:rgba(255,255,255,.95);padding:6px 5px;text-align:center}.bp-slot .pos{display:block;font-size:.55rem;font-weight:850;letter-spacing:.05em;color:#778190;line-height:1;margin-bottom:3px}.bp-slot .name{display:block;font-size:.68rem;line-height:1.1;font-weight:760;color:#172033;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bp-slot.open .name{color:#b0b7c1;font-weight:600}
      .bp-bench{margin-top:8px;padding-top:8px;border-top:1px solid #e4e8e4}.bp-bench-list{display:flex;flex-wrap:wrap;gap:5px}.bp-bench-list span{border:1px solid #dfe3e8;background:#fff;color:#475467;border-radius:999px;padding:4px 7px;font-size:.63rem;font-weight:650}
      @media(max-width:575.98px){.bp-head{padding:11px 12px 9px}.bp-body{padding:10px 12px 12px}.bp-grid{grid-template-columns:1fr;gap:11px}.bp-moves{display:grid;grid-template-columns:1fr 1fr;gap:6px}.bp-move{padding:7px}.bp-move strong{font-size:.71rem}.bp-move small{font-size:.59rem}.bp-dest{min-width:40px;font-size:.62rem}.bp-slot{padding:5px 3px}.bp-slot .name{font-size:.59rem}.bp-slot .pos{font-size:.49rem}.bp-row.battery{max-width:78%}}
      @media(min-width:576px) and (max-width:1023.98px){.bp-grid{grid-template-columns:minmax(210px,.8fr) minmax(350px,1.4fr)}.bp-slot .name{font-size:.73rem}}
    `;
    document.head.appendChild(style);
  }

  function locations(alignment, roster) {
    const map = new Map();
    Object.entries(alignment || {}).forEach(([pos, name]) => { if (name) map.set(name, pos); });
    (roster || []).forEach(player => { if (!map.has(player.name)) map.set(player.name, 'BENCH'); });
    return map;
  }

  function movesBetween(current, next, roster) {
    const a = locations(current, roster);
    const b = locations(next, roster);
    const names = new Set([...a.keys(), ...b.keys()]);
    return [...names].map(name => ({name, from:a.get(name) || 'BENCH', to:b.get(name) || 'BENCH'}))
      .filter(move => move.from !== move.to)
      .sort((x,y) => {
        if (x.to === 'P') return -1;
        if (y.to === 'P') return 1;
        if (x.to === 'BENCH' && y.to !== 'BENCH') return 1;
        if (y.to === 'BENCH' && x.to !== 'BENCH') return -1;
        return x.to.localeCompare(y.to) || x.name.localeCompare(y.name);
      });
  }

  function slot(pos, alignment) {
    const name = alignment?.[pos] || '';
    return `<div class="bp-slot ${name ? '' : 'open'}"><span class="pos">${esc(pos)}</span><span class="name">${esc(name || 'Open')}</span></div>`;
  }

  function boardMarkup(alignment, roster, outfielderCount) {
    const four = Number(outfielderCount) === 4;
    const outfield = four
      ? `<div class="bp-row of4">${['LF','LCF','RCF','RF'].map(pos => slot(pos, alignment)).join('')}</div>`
      : `<div class="bp-row of3">${['LF','CF','RF'].map(pos => slot(pos, alignment)).join('')}</div>`;
    const infield = `<div class="bp-row if">${['3B','SS','2B','1B'].map(pos => slot(pos, alignment)).join('')}</div>`;
    const battery = `<div class="bp-row battery">${['P','C'].map(pos => slot(pos, alignment)).join('')}</div>`;
    const assigned = new Set(Object.values(alignment || {}).filter(Boolean));
    const bench = (roster || []).filter(player => !assigned.has(player.name)).map(player => player.name);
    return `${outfield}${infield}${battery}<div class="bp-bench"><div class="bp-label">Bench</div><div class="bp-bench-list">${bench.length ? bench.map(name => `<span>${esc(name)}</span>`).join('') : '<span>None</span>'}</div></div>`;
  }

  function ensureCard() {
    const extra = document.getElementById('coach-existing-extra');
    if (!extra) return null;

    let card = document.getElementById(CARD_ID);
    if (!card) {
      card = document.createElement('div');
      card.id = CARD_ID;
      const legacy = document.getElementById('live-up-next-v2');
      if (legacy && legacy.parentElement === extra) extra.insertBefore(card, legacy);
      else extra.prepend(card);
    }

    const legacy = document.getElementById('live-up-next-v2');
    if (legacy) legacy.style.display = 'none';
    return card;
  }

  function render(state) {
    const card = ensureCard();
    if (!card) return false;

    if (!state?.game?.is_live) {
      card.remove();
      return true;
    }

    const nextInning = state.planned_next_inning;
    const next = state.planned_next_alignment || {};
    const current = state.current_alignment || {};
    const roster = state.roster || [];
    const hasNext = Object.values(next).some(Boolean);

    if (!hasNext) {
      card.innerHTML = `<div class="bp-head"><div><div class="bp-kicker">Physical Board Prep</div><div class="bp-title">Next inning</div><div class="bp-help">No planned next inning is saved.</div></div><div class="bp-inning"><small>NEXT</small><strong>${esc(nextInning || '—')}</strong></div></div><div class="bp-body"><div class="bp-none">Current defense will carry forward unless a coach makes a live change.</div></div>`;
      return true;
    }

    const moves = movesBetween(current, next, roster);
    const movesHtml = moves.length
      ? moves.map(move => `<div class="bp-move"><div><strong>${esc(move.name)}</strong><small>${esc(move.from)} → ${esc(move.to)}</small></div><div class="bp-dest ${move.to === 'BENCH' ? 'bench' : ''}">${esc(move.to)}</div></div>`).join('')
      : '<div class="bp-none">Same defense next inning. No magnets need to move.</div>';

    card.innerHTML = `<div class="bp-head"><div><div class="bp-kicker">Physical Board Prep</div><div class="bp-title">Set the board for Inning ${esc(nextInning)}</div><div class="bp-help">Use this while your team is batting so the magnetic board is ready.</div></div><div class="bp-inning"><small>UP NEXT</small><strong>${esc(nextInning)}</strong></div></div><div class="bp-body"><div class="bp-grid"><section><div class="bp-label">Magnets to move</div><div class="bp-moves">${movesHtml}</div></section><section><div class="bp-label">Full next-inning board</div><div class="bp-board">${boardMarkup(next, roster, state.outfielder_count)}</div></section></div></div>`;
    return true;
  }

  async function refresh() {
    if (busy) return;
    busy = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/state`, {cache:'no-store'});
      if (!response.ok) return;
      const state = await response.json();
      const signature = JSON.stringify({live:state?.game?.is_live, inning:state?.current_inning, next:state?.planned_next_inning, current:state?.current_alignment, planned:state?.planned_next_alignment, roster:(state?.roster || []).map(p => [p.id,p.name]), of:state?.outfielder_count});
      const cardMissing = state?.game?.is_live && !document.getElementById(CARD_ID);
      if (signature !== lastSignature || cardMissing) {
        if (render(state)) lastSignature = signature;
      } else {
        const legacy = document.getElementById('live-up-next-v2');
        if (legacy) legacy.style.display = 'none';
      }
    } catch (_) {
      // Main live-game controller owns sync/error reporting.
    } finally {
      busy = false;
    }
  }

  installStyles();
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(refresh, 150);
    setInterval(refresh, 1000);
  });
})();
