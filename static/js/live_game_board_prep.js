(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const STYLE_ID = 'coach-board-prep-styles';
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
      #live-up-next-v2.coach-board-prep-card {
        border:1px solid #dfe4ea !important;
        border-radius:14px !important;
        box-shadow:0 1px 3px rgba(16,24,40,.06) !important;
        overflow:hidden;
      }
      .board-prep-head {
        display:flex;
        align-items:flex-start;
        justify-content:space-between;
        gap:12px;
        padding:14px 15px 11px;
        border-bottom:1px solid #edf0f3;
        background:#fff;
      }
      .board-prep-kicker {
        font-size:.66rem;
        text-transform:uppercase;
        letter-spacing:.11em;
        font-weight:850;
        color:#667085;
      }
      .board-prep-title {
        margin-top:2px;
        font-size:1.05rem;
        font-weight:800;
        color:#172033;
      }
      .board-prep-help {
        margin-top:2px;
        font-size:.74rem;
        color:#8a94a3;
      }
      .board-prep-inning {
        flex:0 0 auto;
        min-width:64px;
        border-radius:10px;
        background:#172033;
        color:#fff;
        padding:7px 10px;
        text-align:center;
      }
      .board-prep-inning small {
        display:block;
        font-size:.54rem;
        font-weight:750;
        letter-spacing:.08em;
        opacity:.72;
      }
      .board-prep-inning strong {
        display:block;
        font-size:1.35rem;
        line-height:1.05;
        margin-top:2px;
      }
      .board-prep-body {
        padding:13px 15px 15px;
        background:#fff;
      }
      .board-prep-grid {
        display:grid;
        grid-template-columns:minmax(0,.85fr) minmax(0,1.35fr);
        gap:14px;
        align-items:start;
      }
      .board-prep-section-label {
        font-size:.64rem;
        color:#667085;
        text-transform:uppercase;
        letter-spacing:.09em;
        font-weight:850;
        margin-bottom:7px;
      }
      .board-prep-moves {
        display:flex;
        flex-direction:column;
        gap:6px;
      }
      .board-prep-move {
        border:1px solid #e3e7ec;
        background:#f8fafc;
        border-radius:9px;
        padding:8px 9px;
        display:grid;
        grid-template-columns:minmax(0,1fr) auto;
        gap:8px;
        align-items:center;
      }
      .board-prep-move strong {
        display:block;
        color:#1d2939;
        font-size:.78rem;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
      }
      .board-prep-move small {
        display:block;
        color:#7b8492;
        font-size:.66rem;
        margin-top:1px;
      }
      .board-prep-destination {
        min-width:48px;
        border-radius:7px;
        background:#172033;
        color:#fff;
        padding:5px 7px;
        text-align:center;
        font-size:.69rem;
        font-weight:800;
      }
      .board-prep-destination.bench {
        background:#eef1f5;
        color:#475467;
      }
      .board-prep-no-moves {
        border:1px dashed #d6dce3;
        border-radius:9px;
        padding:12px;
        color:#667085;
        font-size:.76rem;
        text-align:center;
      }
      .board-prep-board {
        border:1px solid #dfe6dd;
        border-radius:12px;
        padding:10px;
        background:linear-gradient(180deg,#f4f9f2 0%,#faf8ef 100%);
      }
      .board-prep-row {
        display:grid;
        gap:6px;
        margin-bottom:6px;
      }
      .board-prep-row.outfield { grid-template-columns:repeat(3,minmax(0,1fr)); }
      .board-prep-row.outfield.four { grid-template-columns:repeat(4,minmax(0,1fr)); }
      .board-prep-row.infield { grid-template-columns:repeat(4,minmax(0,1fr)); }
      .board-prep-row.battery { grid-template-columns:repeat(2,minmax(0,1fr)); max-width:68%; margin:0 auto 6px; }
      .board-prep-slot {
        min-width:0;
        border:1px solid #dfe4e8;
        border-radius:8px;
        background:rgba(255,255,255,.94);
        padding:6px 5px;
        text-align:center;
      }
      .board-prep-slot .pos {
        display:block;
        color:#778190;
        font-size:.57rem;
        line-height:1;
        font-weight:850;
        letter-spacing:.05em;
        margin-bottom:3px;
      }
      .board-prep-slot .name {
        display:block;
        color:#172033;
        font-size:.68rem;
        line-height:1.1;
        font-weight:760;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
      }
      .board-prep-slot.empty .name { color:#b0b7c1; font-weight:600; }
      .board-prep-bench {
        margin-top:8px;
        padding-top:8px;
        border-top:1px solid #e4e8e4;
      }
      .board-prep-bench-list {
        display:flex;
        flex-wrap:wrap;
        gap:5px;
      }
      .board-prep-bench-list span {
        border:1px solid #dfe3e8;
        background:#fff;
        color:#475467;
        border-radius:999px;
        padding:4px 7px;
        font-size:.64rem;
        font-weight:650;
      }
      .board-prep-carry {
        color:#667085;
        font-size:.78rem;
        padding:4px 0 2px;
      }

      @media (max-width:575.98px) {
        .board-prep-head { padding:12px 12px 10px; }
        .board-prep-body { padding:11px 12px 13px; }
        .board-prep-grid { grid-template-columns:1fr; gap:12px; }
        .board-prep-title { font-size:.98rem; }
        .board-prep-help { font-size:.7rem; }
        .board-prep-moves { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
        .board-prep-move { padding:7px 8px; }
        .board-prep-move strong { font-size:.72rem; }
        .board-prep-move small { font-size:.61rem; }
        .board-prep-destination { min-width:43px; font-size:.64rem; padding:4px 6px; }
        .board-prep-board { padding:8px 7px; }
        .board-prep-slot { padding:5px 3px; }
        .board-prep-slot .name { font-size:.61rem; }
        .board-prep-slot .pos { font-size:.51rem; }
        .board-prep-row.battery { max-width:76%; }
      }

      @media (min-width:576px) and (max-width:1023.98px) {
        .board-prep-grid { grid-template-columns:minmax(220px,.8fr) minmax(360px,1.4fr); }
        .board-prep-slot .name { font-size:.74rem; }
        .board-prep-move strong { font-size:.82rem; }
      }
    `;
    document.head.appendChild(style);
  }

  function playerLocation(alignment, roster) {
    const map = new Map();
    Object.entries(alignment || {}).forEach(([pos,name]) => {
      if (name) map.set(name, pos);
    });
    (roster || []).forEach(player => {
      if (!map.has(player.name)) map.set(player.name, 'BENCH');
    });
    return map;
  }

  function movesBetween(current, next, roster) {
    const currentLoc = playerLocation(current, roster);
    const nextLoc = playerLocation(next, roster);
    const names = new Set([...currentLoc.keys(), ...nextLoc.keys()]);
    const moves = [];
    names.forEach(name => {
      const from = currentLoc.get(name) || 'BENCH';
      const to = nextLoc.get(name) || 'BENCH';
      if (from !== to) moves.push({name, from, to});
    });
    return moves.sort((a,b) => {
      if (a.to === 'P') return -1;
      if (b.to === 'P') return 1;
      if (a.to === 'BENCH' && b.to !== 'BENCH') return 1;
      if (b.to === 'BENCH' && a.to !== 'BENCH') return -1;
      return a.to.localeCompare(b.to) || a.name.localeCompare(b.name);
    });
  }

  function slot(pos, alignment) {
    const name = alignment?.[pos] || '';
    return `<div class="board-prep-slot ${name ? '' : 'empty'}"><span class="pos">${esc(pos)}</span><span class="name">${esc(name || 'Open')}</span></div>`;
  }

  function fullBoard(alignment, roster, outfielderCount) {
    const four = Number(outfielderCount) === 4;
    const outfield = four
      ? `<div class="board-prep-row outfield four">${['LF','LCF','RCF','RF'].map(pos => slot(pos,alignment)).join('')}</div>`
      : `<div class="board-prep-row outfield">${['LF','CF','RF'].map(pos => slot(pos,alignment)).join('')}</div>`;
    const infield = `<div class="board-prep-row infield">${['3B','SS','2B','1B'].map(pos => slot(pos,alignment)).join('')}</div>`;
    const battery = `<div class="board-prep-row battery">${['P','C'].map(pos => slot(pos,alignment)).join('')}</div>`;
    const assigned = new Set(Object.values(alignment || {}).filter(Boolean));
    const bench = (roster || []).filter(player => !assigned.has(player.name)).map(player => player.name);
    return `${outfield}${infield}${battery}<div class="board-prep-bench"><div class="board-prep-section-label">Bench</div><div class="board-prep-bench-list">${bench.length ? bench.map(name => `<span>${esc(name)}</span>`).join('') : '<span>None</span>'}</div></div>`;
  }

  function render(state) {
    const card = document.getElementById('live-up-next-v2');
    if (!card || !state?.game?.is_live) return;

    const nextInning = state.planned_next_inning;
    const next = state.planned_next_alignment || {};
    const current = state.current_alignment || {};
    const roster = state.roster || [];
    const hasNext = Object.values(next).some(Boolean);

    card.className = 'card border-0 shadow-sm mb-3 coach-board-prep-card';

    if (!hasNext) {
      card.innerHTML = `<div class="board-prep-head"><div><div class="board-prep-kicker">Physical Board Prep</div><div class="board-prep-title">Next inning</div><div class="board-prep-help">No planned next inning is saved.</div></div><div class="board-prep-inning"><small>NEXT</small><strong>${esc(nextInning || '—')}</strong></div></div><div class="board-prep-body"><div class="board-prep-carry">Current defense will carry forward unless a coach makes a live change.</div></div>`;
      return;
    }

    const moves = movesBetween(current,next,roster);
    const movesHtml = moves.length
      ? moves.map(move => `<div class="board-prep-move"><div><strong>${esc(move.name)}</strong><small>${esc(move.from)} → ${esc(move.to)}</small></div><div class="board-prep-destination ${move.to === 'BENCH' ? 'bench' : ''}">${esc(move.to)}</div></div>`).join('')
      : '<div class="board-prep-no-moves">Same defense next inning. No magnets need to move.</div>';

    card.innerHTML = `
      <div class="board-prep-head">
        <div>
          <div class="board-prep-kicker">Physical Board Prep</div>
          <div class="board-prep-title">Set the board for Inning ${esc(nextInning)}</div>
          <div class="board-prep-help">Use this while your team is batting so the board is ready when you take the field.</div>
        </div>
        <div class="board-prep-inning"><small>UP NEXT</small><strong>${esc(nextInning)}</strong></div>
      </div>
      <div class="board-prep-body">
        <div class="board-prep-grid">
          <section><div class="board-prep-section-label">Magnets to move</div><div class="board-prep-moves">${movesHtml}</div></section>
          <section><div class="board-prep-section-label">Full next-inning board</div><div class="board-prep-board">${fullBoard(next,roster,state.outfielder_count)}</div></section>
        </div>
      </div>`;
  }

  async function refresh() {
    if (busy) return;
    busy = true;
    try {
      const response = await fetch(`/api/live-game/${gameId}/state`, {cache:'no-store'});
      if (!response.ok) return;
      const state = await response.json();
      const signature = JSON.stringify({
        live:state?.game?.is_live,
        inning:state?.current_inning,
        next:state?.planned_next_inning,
        current:state?.current_alignment,
        planned:state?.planned_next_alignment,
        roster:(state?.roster || []).map(p => [p.id,p.name]),
        of:state?.outfielder_count,
      });
      if (signature !== lastSignature) {
        lastSignature = signature;
        render(state);
      }
    } catch (_) {
      // Main live-game controller owns sync/error reporting.
    } finally {
      busy = false;
    }
  }

  installStyles();
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(refresh,250);
    setInterval(refresh,1500);
  });
})();
