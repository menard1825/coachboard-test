(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const CARD_ID = 'live-board-prep-v3';
  const STYLE_ID = 'live-next-defense-styles';
  let latest = null;
  let draft = null;
  let busy = false;
  let lastSignature = '';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
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
      #${CARD_ID}{border:1.5px solid #cfd6df;border-radius:13px;background:#fff;overflow:hidden;margin-bottom:12px;box-shadow:0 1px 4px rgba(16,24,40,.06)}
      #${CARD_ID} .nxd-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;padding:11px 12px 9px;border-bottom:1px solid #edf0f3}
      #${CARD_ID} .nxd-kicker{font-size:.61rem;text-transform:uppercase;letter-spacing:.09em;font-weight:900;color:#667085}
      #${CARD_ID} .nxd-title{font-size:1rem;font-weight:850;color:#172033;margin-top:1px}
      #${CARD_ID} .nxd-help{font-size:.68rem;color:#667085;margin-top:2px}
      #${CARD_ID} .nxd-inning{min-width:58px;border-radius:10px;background:#172033;color:#fff;padding:7px 9px;text-align:center}
      #${CARD_ID} .nxd-inning small{display:block;font-size:.5rem;letter-spacing:.08em;opacity:.72;font-weight:800}
      #${CARD_ID} .nxd-inning strong{display:block;font-size:1.25rem;line-height:1.05}
      #${CARD_ID} .nxd-body{padding:10px 12px 12px}
      #${CARD_ID} .nxd-status{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 9px;border-radius:10px;margin-bottom:9px}
      #${CARD_ID} .nxd-status.waiting{background:#f7f9fc;border:1px solid #d8dee7}
      #${CARD_ID} .nxd-status.ready{background:#edf8f1;border:1px solid #b7dcc3}
      #${CARD_ID} .nxd-status strong{font-size:.78rem;color:#1d2939}
      #${CARD_ID} .nxd-status small{display:block;margin-top:1px;font-size:.64rem;color:#667085}
      #${CARD_ID} .nxd-badge{flex:0 0 auto;border-radius:999px;padding:4px 8px;font-size:.58rem;font-weight:900;letter-spacing:.04em;background:#667085;color:#fff}
      #${CARD_ID} .ready .nxd-badge{background:#176b38}
      #${CARD_ID} .nxd-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}
      #${CARD_ID} .nxd-actions .btn{min-height:43px;border-radius:9px;font-size:.72rem;font-weight:820}
      #${CARD_ID} .nxd-moves{display:grid;gap:6px;margin-bottom:9px}
      #${CARD_ID} .nxd-move{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border:1px solid #e3e7ec;background:#f8fafc;border-radius:9px;padding:7px 9px}
      #${CARD_ID} .nxd-move strong{font-size:.76rem;color:#1d2939}
      #${CARD_ID} .nxd-move small{display:block;font-size:.63rem;color:#667085;margin-top:1px}
      #${CARD_ID} .nxd-dest{min-width:46px;border-radius:7px;background:#172033;color:#fff;padding:5px 6px;text-align:center;font-size:.66rem;font-weight:850}
      #${CARD_ID} .nxd-dest.bench{background:#eef1f5;color:#475467}
      #${CARD_ID} .nxd-none{border:1px dashed #d6dce3;border-radius:9px;padding:9px;color:#667085;font-size:.72rem;text-align:center;background:#fafbfc;margin-bottom:9px}
      #next-inning-adjust-modal .modal-content{border:0;border-radius:15px;overflow:hidden}
      #next-inning-adjust-modal .ni-row{display:grid;grid-template-columns:48px minmax(0,1fr);gap:9px;align-items:center;margin-bottom:8px}
      #next-inning-adjust-modal .ni-pos{height:36px;border-radius:8px;background:#eef1f5;display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:850;color:#344054}
      #next-inning-adjust-modal .form-select{min-height:46px;border-radius:9px;font-weight:650}
      #next-inning-adjust-modal .ni-row.open .ni-pos{background:#fff0f0;color:#a32929}
      #next-inning-adjust-modal .ni-row.open .form-select{border-color:#d88b8b;background:#fffafa}
      #next-inning-adjust-modal .ni-bench{display:flex;flex-wrap:wrap;gap:6px}
      #next-inning-adjust-modal .ni-bench span{border:1px solid #dfe3e8;background:#f8f9fb;border-radius:999px;padding:5px 8px;font-size:.7rem}
      #next-inning-adjust-modal .ni-footer{position:sticky;bottom:0;background:#fff;border-top:1px solid #e7eaf0;margin:13px -16px -16px;padding:11px 16px;display:flex;gap:8px;align-items:center}
      #next-inning-adjust-modal .ni-warning{font-size:.72rem;color:#a32929;font-weight:700}
      @media(max-width:575.98px){
        #${CARD_ID} .nxd-actions{grid-template-columns:1fr 1fr}
        #${CARD_ID} .nxd-actions .btn:last-child{grid-column:1/-1}
        #next-inning-adjust-modal .modal-dialog{margin:.5rem}
      }
    `;
    document.head.appendChild(style);
  }

  function ensureCard() {
    const host = document.getElementById('coach-existing-extra');
    if (!host) return null;
    let card = document.getElementById(CARD_ID);
    if (!card) {
      card = document.createElement('div');
      card.id = CARD_ID;
      host.prepend(card);
    }
    const legacy = document.getElementById('live-up-next-v2');
    if (legacy) legacy.style.display = 'none';
    return card;
  }

  function locationMap(alignment, roster) {
    const map = new Map();
    Object.entries(alignment || {}).forEach(([pos,name]) => { if (name) map.set(name,pos); });
    (roster || []).forEach(player => { if (!map.has(player.name)) map.set(player.name,'BENCH'); });
    return map;
  }

  function movesBetween(current, next, roster) {
    const before = locationMap(current, roster);
    const after = locationMap(next, roster);
    return [...new Set([...before.keys(), ...after.keys()])]
      .map(name => ({name, from:before.get(name)||'BENCH', to:after.get(name)||'BENCH'}))
      .filter(move => move.from !== move.to)
      .sort((a,b) => {
        if (a.to === 'P') return -1;
        if (b.to === 'P') return 1;
        if (a.to === 'BENCH' && b.to !== 'BENCH') return 1;
        if (b.to === 'BENCH' && a.to !== 'BENCH') return -1;
        return a.to.localeCompare(b.to) || a.name.localeCompare(b.name);
      });
  }

  function sourceLabel(source) {
    if (source === 'current') return 'Same defense';
    if (source === 'planned' || source === 'planned_current_pitcher') return 'Pregame defense';
    return 'New defense';
  }

  function actionButtons(data) {
    const hasPregame = Object.values(data.planned_alignment || {}).some(Boolean);
    return `<div class="nxd-actions">
      <button type="button" class="btn btn-outline-dark" data-bp-action="current">Same Defense</button>
      <button type="button" class="btn btn-outline-primary" data-bp-action="planned" ${hasPregame ? '' : 'disabled'}>Pregame Defense</button>
      <button type="button" class="btn btn-primary" data-bp-action="adjust">New Defense</button>
    </div>`;
  }

  function render(data) {
    latest = data;
    if (!data || data.status === 'inactive' || data.is_live === false) {
      document.getElementById(CARD_ID)?.remove();
      return false;
    }

    const card = ensureCard();
    if (!card) return false;
    const next = data.next_inning || '';
    const confirmed = data.confirmed;
    const current = data.current_alignment || {};
    const roster = data.roster || [];
    const head = `<div class="nxd-head"><div><div class="nxd-kicker">NEXT INNING</div><div class="nxd-title">Who’s Going Out Next?</div><div class="nxd-help">Inning ${esc(next)} defense</div></div><div class="nxd-inning"><small>NEXT</small><strong>${esc(next)}</strong></div></div>`;

    if (!confirmed) {
      const pregame = Object.values(data.planned_alignment || {}).some(Boolean)
        ? '<div class="nxd-none">Pregame defense available.</div>'
        : '<div class="nxd-none">No pregame defense saved.</div>';
      card.innerHTML = `${head}<div class="nxd-body"><div class="nxd-status waiting"><div><strong>Defense not set</strong><small>Choose who goes out after the third out.</small></div><span class="nxd-badge">NOT SET</span></div>${pregame}${actionButtons(data)}</div>`;
      wireActions(card);
      return true;
    }

    const target = confirmed.alignment || {};
    const moves = movesBetween(current, target, roster);
    const moveMarkup = moves.length
      ? `<div class="nxd-moves">${moves.map(move => `<div class="nxd-move"><div><strong>${esc(move.name)}</strong><small>${esc(move.from)} → ${esc(move.to)}</small></div><div class="nxd-dest ${move.to === 'BENCH' ? 'bench' : ''}">${esc(move.to)}</div></div>`).join('')}</div>`
      : '<div class="nxd-none">Same defense goes back out.</div>';
    const coach = confirmed.updated_by ? `${esc(confirmed.updated_by)} set this` : 'Defense set';
    card.innerHTML = `${head}<div class="nxd-body"><div class="nxd-status ready"><div><strong>${esc(sourceLabel(confirmed.source))} locked in</strong><small>${coach}</small></div><span class="nxd-badge">LOCKED IN</span></div>${moveMarkup}${actionButtons(data)}</div>`;
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
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status === 'error') throw new Error(data.message || `Unable to set the next defense (${response.status}).`);
    return data;
  }

  function toast(message, kind='success') {
    let host = document.getElementById('next-defense-toast');
    if (!host) {
      host = document.createElement('div');
      host.id = 'next-defense-toast';
      host.className = 'toast-container position-fixed top-0 end-0 p-3';
      host.style.zIndex = '4500';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    host.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el,{delay:2200});
    el.addEventListener('hidden.bs.toast',()=>el.remove(),{once:true});
    instance.show();
  }

  function announce(data) {
    document.dispatchEvent(new CustomEvent('coachboard:next-defense-set', { detail:{ data } }));
  }

  async function confirmMode(mode, quiet=false) {
    if (busy) return null;
    busy = true;
    try {
      const data = await api('POST',{mode});
      lastSignature = '';
      render(data);
      announce(data);
      if (!quiet) toast(mode === 'current' ? 'Same defense set.' : 'Pregame defense set.');
      return data;
    } catch (err) {
      toast(err.message,'danger');
      return null;
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
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Set New Defense</h5><div class="small text-muted">Who takes the field next inning?</div></div><button class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body" id="next-inning-adjust-body"></div></div></div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function draftBench() {
    const assigned = new Set(Object.values(draft || {}).filter(Boolean));
    return (latest?.roster || []).map(player => player.name).filter(name => !assigned.has(name));
  }

  function renderAdjust() {
    const body = document.getElementById('next-inning-adjust-body');
    if (!body || !latest || !draft) return;
    const posList = positions(latest.outfielder_count);
    const roster = [...(latest.roster || [])].sort((a,b)=>a.name.localeCompare(b.name));
    const holes = posList.filter(pos => !draft[pos]);
    const rows = posList.map(pos => {
      const selected = draft[pos] || '';
      const options = ['<option value="">Open position</option>'].concat(
        roster.map(player => `<option value="${esc(player.name)}" ${player.name === selected ? 'selected' : ''}>${esc(player.name)}</option>`)
      ).join('');
      return `<div class="ni-row ${selected ? '' : 'open'}"><div class="ni-pos">${esc(pos)}</div><select class="form-select ni-select" data-pos="${esc(pos)}">${options}</select></div>`;
    }).join('');
    const bench = draftBench();
    body.innerHTML = `${rows}<div class="small text-uppercase text-muted fw-bold mt-3 mb-2">On the Bench</div><div class="ni-bench">${bench.length ? bench.map(name=>`<span>${esc(name)}</span>`).join('') : '<span>None</span>'}</div><div class="ni-footer"><div class="me-auto">${holes.length ? `<div class="ni-warning">Fill ${esc(holes.join(', '))}.</div>` : ''}</div><button class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button><button class="btn btn-dark fw-bold" id="save-next-inning-adjust" ${holes.length ? 'disabled' : ''}>Set Defense</button></div>`;

    body.querySelectorAll('.ni-select').forEach(select => select.addEventListener('change', () => {
      const pos = select.dataset.pos;
      const newName = select.value || '';
      if ((draft[pos] || '') === newName) return;
      if (newName) {
        const other = posList.find(otherPos => otherPos !== pos && draft[otherPos] === newName);
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
    const hasPregame = Object.values(planned).some(Boolean);
    const source = latest.confirmed?.alignment || (hasPregame ? planned : latest.current_alignment) || {};
    draft = {};
    const posList = positions(latest.outfielder_count);
    posList.forEach(pos => { draft[pos] = source[pos] || ''; });
    if (!draft.P && latest.current_alignment?.P) {
      const currentPitcher = latest.current_alignment.P;
      const conflict = posList.find(pos => pos !== 'P' && draft[pos] === currentPitcher);
      if (conflict) draft[conflict] = '';
      draft.P = currentPitcher;
    }
    ensureAdjustModal();
    renderAdjust();
    bootstrap.Modal.getOrCreateInstance(document.getElementById('next-inning-adjust-modal')).show();
  }

  async function saveAdjust() {
    if (busy || !draft) return;
    busy = true;
    const button = document.getElementById('save-next-inning-adjust');
    if (button) { button.disabled = true; button.textContent = 'Saving…'; }
    try {
      const data = await api('POST',{mode:'custom', alignment:draft});
      bootstrap.Modal.getOrCreateInstance(document.getElementById('next-inning-adjust-modal')).hide();
      lastSignature = '';
      render(data);
      announce(data);
      toast(`Inning ${data.next_inning} defense set.`);
    } catch (err) {
      toast(err.message,'danger');
      if (button) { button.disabled = false; button.textContent = 'Set Defense'; }
    } finally {
      busy = false;
    }
  }

  async function refresh() {
    if (busy) return;
    try {
      const data = await api('GET');
      const signature = JSON.stringify(data);
      if (signature !== lastSignature || !document.getElementById(CARD_ID)) {
        if (render(data)) lastSignature = signature;
      }
    } catch (_) {
      document.getElementById(CARD_ID)?.remove();
    }
  }

  window.CBNextDefense = {
    openNew: openAdjust,
    useSame: () => confirmMode('current', true),
    usePregame: () => confirmMode('planned', true),
    refresh,
  };

  installStyles();
  const start = () => {
    setTimeout(refresh,120);
    window.setInterval(refresh,1800);
  };
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded',start,{once:true})
    : start();
})();