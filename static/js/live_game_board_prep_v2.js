(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const CARD_ID = 'live-board-prep-v3';
  const STYLE_ID = 'live-board-prep-v6-styles';
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
      #${CARD_ID}{border:1px solid #e1e5ea;border-radius:14px;background:#fff;box-shadow:0 1px 3px rgba(16,24,40,.06);overflow:hidden;margin-bottom:10px}
      .bp-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:13px 14px 10px;border-bottom:1px solid #edf0f3}
      .bp-kicker{font-size:.63rem;text-transform:uppercase;letter-spacing:.1em;font-weight:850;color:#667085}
      .bp-title{font-size:1.02rem;font-weight:800;color:#172033;margin-top:2px}.bp-help{font-size:.7rem;color:#8a94a3;margin-top:2px;max-width:620px}
      .bp-inning{min-width:60px;border-radius:10px;background:#172033;color:#fff;padding:7px 9px;text-align:center}.bp-inning small{display:block;font-size:.5rem;letter-spacing:.08em;opacity:.72;font-weight:750}.bp-inning strong{display:block;font-size:1.3rem;line-height:1.05}
      .bp-body{padding:12px 14px 14px}.bp-status{display:flex;align-items:center;justify-content:space-between;gap:10px;border-radius:10px;padding:9px 10px;margin-bottom:10px}
      .bp-status.waiting{background:#fff8eb;border:1px solid #f0d5a2}.bp-status.ready{background:#edf8f1;border:1px solid #b7dcc3}.bp-status strong{font-size:.78rem;color:#1d2939}.bp-status small{display:block;font-size:.65rem;color:#667085;margin-top:1px}
      .bp-status-badge{flex:0 0 auto;border-radius:999px;padding:4px 8px;font-size:.59rem;font-weight:850;letter-spacing:.05em}.waiting .bp-status-badge{background:#8b5c00;color:#fff}.ready .bp-status-badge{background:#176b38;color:#fff}
      .bp-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:10px 0 0}.bp-actions .btn{border-radius:9px;font-size:.72rem;font-weight:780;min-height:40px}.bp-actions .btn-primary{background:var(--primary-color,#102a66);border-color:var(--primary-color,#102a66)}
      .bp-main{display:grid;grid-template-columns:minmax(220px,.78fr) minmax(380px,1.35fr);gap:13px;align-items:start}.bp-label{font-size:.61rem;text-transform:uppercase;letter-spacing:.09em;font-weight:850;color:#667085;margin-bottom:7px}.bp-note{font-size:.66rem;color:#8a94a3;margin:-3px 0 7px}
      .bp-decision{padding:2px 0}.bp-decision h6{font-size:.9rem;font-weight:800;color:#1d2939;margin:0 0 4px}.bp-decision p{font-size:.72rem;color:#667085;margin:0}.bp-pitcher-note{margin-top:8px;padding:7px 9px;border:1px solid #efd8ac;border-radius:8px;background:#fffaf0;color:#7a4b00;font-size:.68rem;font-weight:700}
      .bp-moves{display:flex;flex-direction:column;gap:6px}.bp-move{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border:1px solid #e3e7ec;background:#f8fafc;border-radius:9px;padding:8px 9px}.bp-move strong{display:block;font-size:.78rem;color:#1d2939;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bp-move small{display:block;font-size:.65rem;color:#7b8492;margin-top:1px}.bp-dest{min-width:46px;border-radius:7px;background:#172033;color:#fff;padding:5px 6px;text-align:center;font-size:.68rem;font-weight:800}.bp-dest.bench{background:#eef1f5;color:#475467}.bp-none{border:1px dashed #d6dce3;border-radius:9px;padding:11px;color:#667085;font-size:.75rem;text-align:center;background:#fafbfc}

      .bp-field-card{border:1px solid #dce5dc;border-radius:12px;overflow:hidden;background:#f8faf8}.bp-field-caption{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:8px 9px;border-bottom:1px solid #e4e9e4;background:#fff}.bp-field-caption strong{font-size:.72rem;color:#344054}.bp-field-caption span{font-size:.61rem;color:#98a2b3}
      .bp-field{position:relative;aspect-ratio:1.32/1;min-height:245px;overflow:hidden;background:repeating-linear-gradient(90deg,#3d8f55 0,#3d8f55 12.5%,#438f58 12.5%,#438f58 25%)}
      .bp-field-art{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.bp-field-spot{position:absolute;transform:translate(-50%,-50%);min-width:64px;max-width:112px;text-align:center;z-index:2}.bp-field-spot .pos{display:block;color:#fff;font-size:.5rem;font-weight:900;line-height:1;text-shadow:0 1px 2px rgba(0,0,0,.45);margin-bottom:3px}.bp-field-spot .name{display:block;background:rgba(255,255,255,.95);border:1px solid rgba(220,225,229,.95);border-radius:7px;padding:4px 6px;font-size:.64rem;line-height:1.05;font-weight:780;color:#172033;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-shadow:0 1px 2px rgba(16,24,40,.08)}.bp-field-spot.open .name{background:#fff3f3;border-color:#e3a8a8;color:#a32929}.bp-field-spot.tbd .name{background:#fff8e8;border-color:#e7c46b;color:#7a4b00}
      .bp-bench{padding:8px 9px 9px;background:#fff;border-top:1px solid #e4e9e4}.bp-bench-list{display:flex;flex-wrap:wrap;gap:5px}.bp-bench-list span{border:1px solid #dfe3e8;background:#f8f9fb;color:#475467;border-radius:999px;padding:4px 7px;font-size:.62rem;font-weight:650}

      #next-inning-adjust-modal .modal-content{border:0;border-radius:16px;overflow:hidden}#next-inning-adjust-modal .modal-dialog{max-width:720px}
      #next-inning-adjust-modal .ni-row{display:grid;grid-template-columns:48px minmax(0,1fr);gap:9px;align-items:center;margin-bottom:8px}#next-inning-adjust-modal .ni-pos{height:36px;border-radius:8px;background:#eef1f5;display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:850;color:#344054}#next-inning-adjust-modal .form-select{min-height:46px;border-radius:9px;font-weight:650}#next-inning-adjust-modal .ni-row.open .ni-pos{background:#fff0f0;color:#a32929}#next-inning-adjust-modal .ni-row.open .form-select{border-color:#d88b8b;background:#fffafa}
      #next-inning-adjust-modal .ni-bench{display:flex;flex-wrap:wrap;gap:6px}#next-inning-adjust-modal .ni-bench span{border:1px solid #dfe3e8;background:#f8f9fb;border-radius:999px;padding:5px 8px;font-size:.7rem}#next-inning-adjust-modal .ni-footer{position:sticky;bottom:0;background:#fff;border-top:1px solid #e7eaf0;margin:13px -16px -16px;padding:11px 16px;display:flex;gap:8px;align-items:center}.ni-warning{font-size:.72rem;color:#a32929;font-weight:700}

      @media(max-width:575.98px){.bp-head{padding:11px 12px 9px}.bp-body{padding:10px 12px 12px}.bp-main{grid-template-columns:1fr;gap:11px}.bp-actions{grid-template-columns:1fr 1fr}.bp-actions .btn:last-child{grid-column:1/-1}.bp-moves{display:grid;grid-template-columns:1fr 1fr;gap:6px}.bp-move{padding:7px}.bp-move strong{font-size:.7rem}.bp-move small{font-size:.58rem}.bp-dest{min-width:40px;font-size:.61rem}.bp-field{min-height:225px}.bp-field-spot{min-width:52px;max-width:74px}.bp-field-spot .name{font-size:.56rem;padding:4px}.bp-field-spot .pos{font-size:.45rem}#next-inning-adjust-modal .modal-dialog{margin:.5rem}}
      @media(min-width:576px) and (max-width:1023.98px){.bp-main{grid-template-columns:minmax(210px,.75fr) minmax(390px,1.35fr)}.bp-field{min-height:270px}.bp-field-spot .name{font-size:.68rem}}
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

  function fieldSpot(pos, alignment, left, top, pitcherTbd=false) {
    const name = alignment?.[pos] || '';
    const tbd = pitcherTbd && pos === 'P' && !name;
    const className = name ? '' : (tbd ? 'tbd' : 'open');
    const label = name || (tbd ? 'TBD' : 'Open');
    return `<div class="bp-field-spot ${className}" style="left:${left}%;top:${top}%"><span class="pos">${esc(pos)}</span><span class="name">${esc(label)}</span></div>`;
  }

  function fieldMarkup(alignment, roster, outfielderCount, caption, note, pitcherTbd=false) {
    const four = Number(outfielderCount) === 4;
    const outfield = four
      ? [['LF',11,24],['LCF',38,14],['RCF',62,14],['RF',89,24]]
      : [['LF',15,22],['CF',50,11],['RF',85,22]];
    const spots = [...outfield,['3B',18,57],['SS',38,43],['2B',62,43],['1B',82,57],['P',50,61],['C',50,84]];
    const assigned = new Set(Object.values(alignment || {}).filter(Boolean));
    const bench = (roster || []).filter(player => !assigned.has(player.name)).map(player => player.name);
    return `<div class="bp-field-card"><div class="bp-field-caption"><strong>${esc(caption)}</strong><span>${esc(note || '')}</span></div><div class="bp-field"><svg class="bp-field-art" viewBox="0 0 100 88" preserveAspectRatio="none" aria-hidden="true"><path d="M7 57 Q9 13 50 6 Q91 13 93 57" fill="none" stroke="rgba(245,245,220,.35)" stroke-width="1.2"/><path d="M50 84 L8 38 M50 84 L92 38" fill="none" stroke="rgba(255,255,255,.88)" stroke-width=".7"/><polygon points="50,75 27,54 50,32 73,54" fill="#cfa56c" opacity=".95"/><polygon points="50,68 34,54 50,40 66,54" fill="#438f58"/><circle cx="50" cy="61" r="4.8" fill="#cfa56c"/><circle cx="50" cy="81" r="6.2" fill="#cfa56c"/><rect x="49" y="31" width="2" height="2" fill="#fff" transform="rotate(45 50 32)"/><rect x="72" y="53" width="2" height="2" fill="#fff" transform="rotate(45 73 54)"/><rect x="26" y="53" width="2" height="2" fill="#fff" transform="rotate(45 27 54)"/><path d="M48.8 81.5 L50 80.4 L51.2 81.5 L50.8 83 L49.2 83 Z" fill="#fff"/></svg>${spots.map(([pos,left,top])=>fieldSpot(pos,alignment,left,top,pitcherTbd)).join('')}</div><div class="bp-bench"><div class="bp-label">Bench</div><div class="bp-bench-list">${bench.length ? bench.map(name=>`<span>${esc(name)}</span>`).join('') : '<span>None</span>'}</div></div></div>`;
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
    if (source === 'current') return 'Current defense is staying';
    if (source === 'planned_current_pitcher') return 'Pregame defense confirmed · current pitcher continues';
    if (source === 'planned') return 'Pregame defense confirmed';
    return 'Custom defense confirmed';
  }

  function plannedPitcherConflict(data) {
    const planned = data.planned_alignment || {};
    const currentPitcher = data.current_alignment?.P || '';
    if (!currentPitcher || planned.P) return null;
    return Object.entries(planned).find(([pos,name]) => pos !== 'P' && name === currentPitcher)?.[0] || null;
  }

  function actionButtons(data) {
    const planned = data.planned_alignment || {};
    const hasPlan = Object.values(planned).some(Boolean);
    const currentPitcher = data.current_alignment?.P || '';
    const pitcherTbd = hasPlan && !planned.P && Boolean(currentPitcher);
    const conflict = pitcherTbd ? plannedPitcherConflict(data) : null;
    const planUsable = hasPlan && !conflict;
    const planLabel = pitcherTbd && !conflict ? 'Use Plan + Keep Pitcher' : 'Use Plan';
    const adjustLabel = pitcherTbd ? 'Choose Pitcher / Adjust' : 'Adjust Defense';
    const title = conflict ? `${currentPitcher} is planned at ${conflict}; resolve the pitcher and that position first.` : '';
    return `<div class="bp-actions"><button class="btn btn-outline-dark" data-bp-action="current">Keep Current</button><button class="btn btn-outline-primary" data-bp-action="planned" ${planUsable?'':'disabled'} title="${esc(title)}">${esc(planLabel)}</button><button class="btn btn-primary" data-bp-action="adjust">${esc(adjustLabel)}</button></div>`;
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
    const plannedPitcherTbd = Object.values(planned).some(Boolean) && !planned.P;
    const conflict = plannedPitcherConflict(data);
    const head = `<div class="bp-head"><div><div class="bp-kicker">Next Inning Prep</div><div class="bp-title">Get the board ready for Inning ${esc(next)}</div><div class="bp-help">Confirm the actual defense before ending the inning. A pregame pitcher marked TBD can stay current or be changed now.</div></div><div class="bp-inning"><small>NEXT</small><strong>${esc(next)}</strong></div></div>`;

    if (!confirmed) {
      const planExists = Object.values(planned).some(Boolean);
      const preview = planExists
        ? fieldMarkup(planned, roster, data.outfielder_count, 'Pregame Plan Preview', plannedPitcherTbd ? 'Pitcher TBD · choose now or keep current' : 'Not active yet', plannedPitcherTbd)
        : '<div class="bp-none">No pregame plan is saved for this inning.</div>';
      let pitcherNote = '';
      if (plannedPitcherTbd && current.P && conflict) {
        pitcherNote = `<div class="bp-pitcher-note"><i class="bi bi-exclamation-triangle me-1"></i>${esc(current.P)} is the current pitcher but is planned at ${esc(conflict)}. Use “Choose Pitcher / Adjust” to decide the pitcher and fill ${esc(conflict)}.</div>`;
      } else if (plannedPitcherTbd && current.P) {
        pitcherNote = `<div class="bp-pitcher-note"><i class="bi bi-info-circle me-1"></i>Pregame pitcher is TBD. “Use Plan + Keep Pitcher” will keep ${esc(current.P)} on the mound while using the planned fielders.</div>`;
      }
      card.innerHTML = `${head}<div class="bp-body"><div class="bp-status waiting"><div><strong>Next inning not set</strong><small>Choose what you actually want before moving the board.</small></div><span class="bp-status-badge">NOT SET</span></div><div class="bp-main"><section class="bp-decision"><div class="bp-label">Choose next inning</div><h6>What defense are we using?</h6><p>Current defense is already shown above. The plan on the right is only a preview.</p>${pitcherNote}${actionButtons(data)}</section><section>${preview}</section></div></div>`;
      wireActions(card);
      return true;
    }

    const target = confirmed.alignment || {};
    const moves = movesBetween(current,target,roster);
    const movesHtml = moves.length
      ? moves.map(move => `<div class="bp-move"><div><strong>${esc(move.name)}</strong><small>${esc(move.from)} → ${esc(move.to)}</small></div><div class="bp-dest ${move.to==='BENCH'?'bench':''}">${esc(move.to)}</div></div>`).join('')
      : '<div class="bp-none">No magnet moves. Keep the board as-is.</div>';
    const updated = confirmed.updated_by ? `Confirmed by ${esc(confirmed.updated_by)}` : 'Confirmed';
    card.innerHTML = `${head}<div class="bp-body"><div class="bp-status ready"><div><strong>${esc(sourceLabel(confirmed.source))}</strong><small>${updated}. End Inning will load this defense.</small></div><span class="bp-status-badge">BOARD READY</span></div><div class="bp-main"><section><div class="bp-label">Moves to make</div><div class="bp-moves">${movesHtml}</div>${actionButtons(data)}</section><section>${fieldMarkup(target,roster,data.outfielder_count,'Confirmed Board','Ready for next inning')}</section></div></div>`;
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
      const carried = data.confirmed?.source === 'planned_current_pitcher';
      toast(mode === 'current'
        ? 'Current defense confirmed for next inning.'
        : carried
          ? 'Pregame defense confirmed. Current pitcher will continue.'
          : 'Pregame defense confirmed for next inning.');
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
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Set Next Inning</h5><div class="small text-muted">Confirm the fielders and the pitcher who will actually start the inning.</div></div><button class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body" id="next-inning-adjust-body"></div></div></div>`;
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
    const currentPitcher = latest.current_alignment?.P || '';
    const holes = posList.filter(pos=>!draft[pos]);
    const rows = posList.map(pos => {
      const selected = draft[pos] || '';
      const options = ['<option value="">Open position</option>'].concat(roster.map(p=>{
        const keepLabel = pos === 'P' && currentPitcher && p.name === currentPitcher ? ' — keep current pitcher' : '';
        return `<option value="${esc(p.name)}" ${p.name===selected?'selected':''}>${esc(p.name + keepLabel)}</option>`;
      })).join('');
      return `<div class="ni-row ${selected?'':'open'}"><div class="ni-pos">${esc(pos)}</div><select class="form-select ni-select" data-pos="${esc(pos)}">${options}</select></div>`;
    }).join('');
    const bench = draftBench();
    const conflict = plannedPitcherConflict(latest);
    let pitcherHint = '';
    if (latest.planned_alignment && !latest.planned_alignment.P && currentPitcher && conflict) {
      pitcherHint = `<div class="small text-muted mb-2"><i class="bi bi-exclamation-triangle me-1"></i>${esc(currentPitcher)} stays at P by default, so ${esc(conflict)} has been opened for you to fill. Choose a different pitcher if that better matches the game situation.</div>`;
    } else if (latest.planned_alignment && !latest.planned_alignment.P && currentPitcher) {
      pitcherHint = `<div class="small text-muted mb-2"><i class="bi bi-info-circle me-1"></i>${esc(currentPitcher)} is carried forward at P by default because the pregame pitcher was TBD. Choose another pitcher here if the game situation calls for it.</div>`;
    }
    body.innerHTML = `${pitcherHint}${rows}<div class="bp-label mt-3">Bench</div><div class="ni-bench">${bench.length?bench.map(name=>`<span>${esc(name)}</span>`).join(''):'<span>None</span>'}</div><div class="ni-footer"><div class="me-auto">${holes.length?`<div class="ni-warning">Fill ${esc(holes.join(', '))} before confirming.</div>`:'<div class="small text-muted">This exact setup becomes the next-inning board.</div>'}</div><button class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button><button class="btn btn-dark fw-bold" id="save-next-inning-adjust" ${holes.length?'disabled':''}>Confirm Setup</button></div>`;

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
    const planned = latest.planned_alignment || {};
    const hasPlan = Object.values(planned).some(Boolean);
    const source = latest.confirmed?.alignment || (hasPlan ? planned : latest.current_alignment) || {};
    draft = {};
    const posList = positions(latest.outfielder_count);
    posList.forEach(pos=>{ draft[pos] = source[pos] || ''; });
    if (!draft.P && latest.current_alignment?.P) {
      const currentPitcher = latest.current_alignment.P;
      const conflictPos = posList.find(pos => pos !== 'P' && draft[pos] === currentPitcher);
      if (conflictPos) draft[conflictPos] = '';
      draft.P = currentPitcher;
    }
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
      toast('Next-inning defense confirmed.');
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
    setTimeout(refresh,120);
    setInterval(refresh,1000);
  });
})();
