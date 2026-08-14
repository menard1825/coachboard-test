(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const CARD_ID = 'live-board-prep-v3';
  const STYLE_ID = 'live-board-prep-v4-styles';
  let lastSignature = '';
  let busy = false;
  let latest = null;
  let draft = null;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function positions(count) {
    return Number(count) === 4
      ? ['P','C','1B','2B','3B','SS','LF','LCF','RCF','RF']
      : ['P','C','1B','2B','3B','SS','LF','CF','RF'];
  }

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${CARD_ID}{border:1px solid #dfe4ea;border-radius:14px;background:#fff;box-shadow:0 1px 3px rgba(16,24,40,.06);overflow:hidden;margin-bottom:10px}
      .bp-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:13px 14px 10px;border-bottom:1px solid #edf0f3}
      .bp-kicker{font-size:.65rem;text-transform:uppercase;letter-spacing:.1em;font-weight:850;color:#667085}.bp-title{font-size:1.02rem;font-weight:800;color:#172033;margin-top:2px}.bp-help{font-size:.72rem;color:#8a94a3;margin-top:2px}
      .bp-inning{min-width:62px;border-radius:10px;background:#172033;color:#fff;padding:7px 9px;text-align:center}.bp-inning small{display:block;font-size:.52rem;letter-spacing:.08em;opacity:.72;font-weight:750}.bp-inning strong{display:block;font-size:1.3rem;line-height:1.05}
      .bp-body{padding:12px 14px 14px}.bp-status{display:flex;align-items:center;justify-content:space-between;gap:10px;border-radius:10px;padding:9px 10px;margin-bottom:10px}.bp-status.waiting{background:#fff7e8;border:1px solid #f3d39a}.bp-status.ready{background:#ecf8f0;border:1px solid #add7bb}.bp-status strong{font-size:.76rem;color:#1d2939}.bp-status small{display:block;font-size:.65rem;color:#667085;margin-top:1px}.bp-status-badge{flex:0 0 auto;border-radius:999px;padding:4px 8px;font-size:.6rem;font-weight:850;letter-spacing:.05em}.waiting .bp-status-badge{background:#8b5c00;color:#fff}.ready .bp-status-badge{background:#176b38;color:#fff}
      .bp-actions{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:12px}.bp-actions .btn{border-radius:9px;font-size:.72rem;font-weight:750;min-height:38px}.bp-actions .btn-primary{background:var(--primary-color,#102a66);border-color:var(--primary-color,#102a66)}
      .bp-preview-grid,.bp-ready-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}.bp-label{font-size:.62rem;text-transform:uppercase;letter-spacing:.09em;font-weight:850;color:#667085;margin-bottom:7px}.bp-note{font-size:.68rem;color:#8a94a3;margin:-3px 0 7px}
      .bp-moves{display:flex;flex-direction:column;gap:6px}.bp-move{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border:1px solid #e3e7ec;background:#f8fafc;border-radius:9px;padding:8px 9px}.bp-move strong{display:block;font-size:.78rem;color:#1d2939;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bp-move small{display:block;font-size:.65rem;color:#7b8492;margin-top:1px}.bp-dest{min-width:46px;border-radius:7px;background:#172033;color:#fff;padding:5px 6px;text-align:center;font-size:.68rem;font-weight:800}.bp-dest.bench{background:#eef1f5;color:#475467}.bp-none{border:1px dashed #d6dce3;border-radius:9px;padding:11px;color:#667085;font-size:.75rem;text-align:center}
      .bp-board{border:1px solid #dfe6dd;border-radius:12px;padding:9px;background:linear-gradient(180deg,#f4f9f2 0%,#faf8ef 100%)}.bp-row{display:grid;gap:6px;margin-bottom:6px}.bp-row.of3{grid-template-columns:repeat(3,minmax(0,1fr))}.bp-row.of4{grid-template-columns:repeat(4,minmax(0,1fr))}.bp-row.if{grid-template-columns:repeat(4,minmax(0,1fr))}.bp-row.battery{grid-template-columns:repeat(2,minmax(0,1fr));max-width:68%;margin:0 auto 6px}
      .bp-slot{min-width:0;border:1px solid #dfe4e8;border-radius:8px;background:rgba(255,255,255,.95);padding:6px 5px;text-align:center}.bp-slot .pos{display:block;font-size:.55rem;font-weight:850;letter-spacing:.05em;color:#778190;line-height:1;margin-bottom:3px}.bp-slot .name{display:block;font-size:.68rem;line-height:1.1;font-weight:760;color:#172033;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bp-slot.open{border-color:#e2b4b4;background:#fff8f8}.bp-slot.open .name{color:#b04a4a;font-weight:650}.bp-bench{margin-top:8px;padding-top:8px;border-top:1px solid #e4e8e4}.bp-bench-list{display:flex;flex-wrap:wrap;gap:5px}.bp-bench-list span{border:1px solid #dfe3e8;background:#fff;color:#475467;border-radius:999px;padding:4px 7px;font-size:.63rem;font-weight:650}
      #next-inning-adjust-modal .modal-content{border:0;border-radius:16px;overflow:hidden}#next-inning-adjust-modal .modal-dialog{max-width:720px}#next-inning-adjust-modal .ni-row{display:grid;grid-template-columns:48px minmax(0,1fr);gap:9px;align-items:center;margin-bottom:8px}#next-inning-adjust-modal .ni-pos{height:36px;border-radius:8px;background:#eef1f5;display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:850;color:#344054}#next-inning-adjust-modal .form-select{min-height:46px;border-radius:9px;font-weight:650}#next-inning-adjust-modal .ni-row.open .ni-pos{background:#fff0f0;color:#a32929}#next-inning-adjust-modal .ni-row.open .form-select{border-color:#d88b8b;background:#fffafa}#next-inning-adjust-modal .ni-bench{display:flex;flex-wrap:wrap;gap:6px}#next-inning-adjust-modal .ni-bench span{border:1px solid #dfe3e8;background:#f8f9fb;border-radius:999px;padding:5px 8px;font-size:.7rem}#next-inning-adjust-modal .ni-footer{position:sticky;bottom:0;background:#fff;border-top:1px solid #e7eaf0;margin:13px -16px -16px;padding:11px 16px;display:flex;gap:8px;align-items:center}.ni-warning{font-size:.72rem;color:#a32929;font-weight:700}
      @media(max-width:575.98px){.bp-head{padding:11px 12px 9px}.bp-body{padding:10px 12px 12px}.bp-preview-grid,.bp-ready-grid{grid-template-columns:1fr;gap:11px}.bp-actions{display:grid;grid-template-columns:1fr 1fr}.bp-actions .btn:last-child{grid-column:1/-1}.bp-moves{display:grid;grid-template-columns:1fr 1fr;gap:6px}.bp-move{padding:7px}.bp-move strong{font-size:.71rem}.bp-move small{font-size:.59rem}.bp-dest{min-width:40px;font-size:.62rem}.bp-slot{padding:5px 3px}.bp-slot .name{font-size:.59rem}.bp-slot .pos{font-size:.49rem}.bp-row.battery{max-width:78%}#next-inning-adjust-modal .modal-dialog{margin:.5rem}}
      @media(min-width:768px){.bp-ready-grid{grid-template-columns:minmax(240px,.8fr) minmax(420px,1.4fr)}}
    `;
    document.head.appendChild(style);
  }

  function locations(alignment, roster) {
    const map = new Map();
    Object.entries(alignment || {}).forEach(([pos,name]) => { if (name) map.set(name,pos); });
    (roster || []).forEach(player => { if (!map.has(player.name)) map.set(player.name,'BENCH'); });
    return map;
  }

  function movesBetween(current, next, roster) {
    const a = locations(current, roster), b = locations(next, roster);
    const names = new Set([...a.keys(), ...b.keys()]);
    return [...names].map(name => ({name,from:a.get(name)||'BENCH',to:b.get(name)||'BENCH'}))
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
      ? `<div class="bp-row of4">${['LF','LCF','RCF','RF'].map(pos => slot(pos,alignment)).join('')}</div>`
      : `<div class="bp-row of3">${['LF','CF','RF'].map(pos => slot(pos,alignment)).join('')}</div>`;
    const infield = `<div class="bp-row if">${['3B','SS','2B','1B'].map(pos => slot(pos,alignment)).join('')}</div>`;
    const battery = `<div class="bp-row battery">${['P','C'].map(pos => slot(pos,alignment)).join('')}</div>`;
    const assigned = new Set(Object.values(alignment || {}).filter(Boolean));
    const bench = (roster || []).filter(player => !assigned.has(player.name)).map(player => player.name);
    return `${outfield}${infield}${battery}<div class="bp-bench"><div class="bp-label">Bench</div><div class="bp-bench-list">${bench.length ? bench.map(name=>`<span>${esc(name)}</span>`).join('') : '<span>None</span>'}</div></div>`;
  }

  function ensureCard() {
    const extra = document.getElementById('coach-existing-extra');
    if (!extra) return null;
    let card = document.getElementById(CARD_ID);
    if (!card) {
      card = document.createElement('div');
      card.id = CARD_ID;
      extra.prepend(card);
    }
    const legacy = document.getElementById('live-up-next-v2');
    if (legacy) legacy.style.display = 'none';
    return card;
  }

  function sourceLabel(source) {
    if (source === 'current') return 'Keeping current defense';
    if (source === 'planned') return 'Using pregame plan';
    return 'Custom next-inning setup';
  }

  function actionButtons(data) {
    const hasPlan = Object.values(data.planned_alignment || {}).some(Boolean);
    return `<div class="bp-actions"><button class="btn btn-outline-dark" data-bp-action="current">Keep Current Defense</button><button class="btn btn-outline-primary" data-bp-action="planned" ${hasPlan?'':'disabled'}>Use Pregame Plan</button><button class="btn btn-primary" data-bp-action="adjust">Adjust Next Inning</button></div>`;
  }

  function render(data) {
    latest = data;
    const card = ensureCard();
    if (!card) return false;
    const next = data.next_inning;
    const current = data.current_alignment || {};
    const planned = data.planned_alignment || {};
    const confirmed = data.confirmed;
    const roster = data.roster || [];

    const head = `<div class="bp-head"><div><div class="bp-kicker">Physical Board Prep</div><div class="bp-title">Next Inning Setup — Inning ${esc(next)}</div><div class="bp-help">Pregame plan is a suggestion until a coach confirms what you actually want.</div></div><div class="bp-inning"><small>UP NEXT</small><strong>${esc(next)}</strong></div></div>`;

    if (!confirmed) {
      const planExists = Object.values(planned).some(Boolean);
      card.innerHTML = `${head}<div class="bp-body"><div class="bp-status waiting"><div><strong>No next-inning defense has been confirmed.</strong><small>Do not move magnets yet. Choose what the team will actually use.</small></div><span class="bp-status-badge">NOT CONFIRMED</span></div>${actionButtons(data)}<div class="bp-preview-grid"><section><div class="bp-label">Current defense</div><div class="bp-note">What is on the field right now</div><div class="bp-board">${boardMarkup(current,roster,data.outfielder_count)}</div></section><section><div class="bp-label">Pregame plan — preview only</div><div class="bp-note">${planExists ? 'Not active until you choose Use Pregame Plan.' : 'No pregame plan is saved for this inning.'}</div>${planExists ? `<div class="bp-board">${boardMarkup(planned,roster,data.outfielder_count)}</div>` : '<div class="bp-none">No planned next inning.</div>'}</section></div></div>`;
      wireActions(card);
      return true;
    }

    const target = confirmed.alignment || {};
    const moves = movesBetween(current,target,roster);
    const movesHtml = moves.length
      ? moves.map(move => `<div class="bp-move"><div><strong>${esc(move.name)}</strong><small>${esc(move.from)} → ${esc(move.to)}</small></div><div class="bp-dest ${move.to==='BENCH'?'bench':''}">${esc(move.to)}</div></div>`).join('')
      : '<div class="bp-none">No magnets need to move. Keep the current defense.</div>';
    const updated = confirmed.updated_by ? ` • confirmed by ${esc(confirmed.updated_by)}` : '';
    card.innerHTML = `${head}<div class="bp-body"><div class="bp-status ready"><div><strong>${esc(sourceLabel(confirmed.source))}</strong><small>This is the defense End Inning will load${updated}.</small></div><span class="bp-status-badge">READY</span></div>${actionButtons(data)}<div class="bp-ready-grid"><section><div class="bp-label">Magnets to move</div><div class="bp-moves">${movesHtml}</div></section><section><div class="bp-label">Confirmed next-inning board</div><div class="bp-board">${boardMarkup(target,roster,data.outfielder_count)}</div></section></div></div>`;
    wireActions(card);
    return true;
  }

  async function api(method='GET', body=null) {
    const response = await fetch(`/api/live-game/${gameId}/next-inning-prep`, {
      method,
      headers: body ? {'Content-Type':'application/json'} : undefined,
      body: body ? JSON.stringify(body) : undefined,
      cache:'no-store'
    });
    const data = await response.json().catch(()=>({}));
    if (!response.ok || data.status === 'error') throw new Error(data.message || `Unable to update board prep (${response.status}).`);
    return data;
  }

  function toast(message, kind='success') {
    let host = document.getElementById('board-prep-toast');
    if (!host) {
      host = document.createElement('div');
      host.id = 'board-prep-toast';
      host.className = 'toast-container position-fixed top-0 end-0 p-3';
      host.style.zIndex = '4500';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    host.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el,{delay:2800});
    el.addEventListener('hidden.bs.toast',()=>el.remove(),{once:true});
    instance.show();
  }

  async function confirmMode(mode) {
    if (busy) return;
    busy = true;
    try {
      const data = await api('POST',{mode});
      lastSignature = '';
      render(data);
      toast(mode === 'current' ? 'Next inning will keep the current defense.' : 'Pregame plan confirmed for the next inning.');
    } catch (err) {
      toast(err.message,'danger');
    } finally {
      busy = false;
    }
  }

  function wireActions(card) {
    card.querySelector('[data-bp-action="current"]')?.addEventListener('click',()=>confirmMode('current'));
    card.querySelector('[data-bp-action="planned"]')?.addEventListener('click',()=>confirmMode('planned'));
    card.querySelector('[data-bp-action="adjust"]')?.addEventListener('click',openAdjust);
  }

  function ensureAdjustModal() {
    let modal = document.getElementById('next-inning-adjust-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'next-inning-adjust-modal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('data-bs-backdrop','static');
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Adjust Next Inning</h5><div class="small text-muted">Choose the exact defense. Nothing moves automatically.</div></div><button class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body" id="next-inning-adjust-body"></div></div></div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function draftBench() {
    const assigned = new Set(Object.values(draft || {}).filter(Boolean));
    return (latest?.roster || []).map(p=>p.name).filter(name=>!assigned.has(name));
  }

  function renderAdjust() {
    const body = document.getElementById('next-inning-adjust-body');
    if (!body || !latest || !draft) return;
    const posList = positions(latest.outfielder_count);
    const roster = [...(latest.roster || [])].sort((a,b)=>a.name.localeCompare(b.name));
    const holes = posList.filter(pos=>!draft[pos]);
    const rows = posList.map(pos => {
      const selected = draft[pos] || '';
      const options = ['<option value="">Open position</option>'].concat(roster.map(p=>`<option value="${esc(p.name)}" ${p.name===selected?'selected':''}>${esc(p.name)}</option>`)).join('');
      return `<div class="ni-row ${selected?'':'open'}"><div class="ni-pos">${esc(pos)}</div><select class="form-select ni-select" data-pos="${esc(pos)}">${options}</select></div>`;
    }).join('');
    const bench = draftBench();
    body.innerHTML = `${rows}<div class="bp-label mt-3">Bench</div><div class="ni-bench">${bench.length?bench.map(name=>`<span>${esc(name)}</span>`).join(''):'<span>None</span>'}</div><div class="ni-footer"><div class="me-auto">${holes.length?`<div class="ni-warning">Fill ${esc(holes.join(', '))} before confirming.</div>`:'<div class="small text-muted">This exact setup will become the Board Prep instructions.</div>'}</div><button class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button><button class="btn btn-dark fw-bold" id="save-next-inning-adjust" ${holes.length?'disabled':''}>Confirm Setup</button></div>`;

    body.querySelectorAll('.ni-select').forEach(select=>select.addEventListener('change',()=>{
      const pos = select.dataset.pos;
      const newName = select.value || '';
      if ((draft[pos] || '') === newName) return;
      if (newName) {
        const other = posList.find(otherPos=>otherPos!==pos && draft[otherPos]===newName);
        if (other) draft[other] = '';
      }
      draft[pos] = newName;
      renderAdjust();
    }));
    document.getElementById('save-next-inning-adjust')?.addEventListener('click',saveAdjust);
  }

  function openAdjust() {
    if (!latest) return;
    const source = latest.confirmed?.alignment || latest.current_alignment || {};
    draft = {};
    positions(latest.outfielder_count).forEach(pos=>{ draft[pos] = source[pos] || ''; });
    ensureAdjustModal();
    renderAdjust();
    bootstrap.Modal.getOrCreateInstance(document.getElementById('next-inning-adjust-modal')).show();
  }

  async function saveAdjust() {
    if (busy || !draft) return;
    busy = true;
    const btn = document.getElementById('save-next-inning-adjust');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }
    try {
      const data = await api('POST',{mode:'custom',alignment:draft});
      bootstrap.Modal.getOrCreateInstance(document.getElementById('next-inning-adjust-modal')).hide();
      lastSignature = '';
      render(data);
      toast('Custom next-inning defense confirmed.');
    } catch (err) {
      toast(err.message,'danger');
      if (btn) { btn.disabled = false; btn.textContent = 'Confirm Setup'; }
    } finally {
      busy = false;
    }
  }

  async function refresh() {
    if (busy) return;
    try {
      const data = await api('GET');
      const signature = JSON.stringify(data);
      const cardMissing = !document.getElementById(CARD_ID);
      if (signature !== lastSignature || cardMissing) {
        if (render(data)) lastSignature = signature;
      }
    } catch (_) {
      const card = document.getElementById(CARD_ID);
      if (card) card.remove();
    }
  }

  installStyles();
  document.addEventListener('DOMContentLoaded',()=>{
    setTimeout(refresh,180);
    setInterval(refresh,1000);
  });
})();
