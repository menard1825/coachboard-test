(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const CARD_ID = 'live-board-prep-v3';
  const MODAL_ID = 'next-inning-adjust-modal';
  const BODY_ID = 'next-inning-adjust-body';
  const OWNED_ID = 'next-defense-editor-owned';
  const STYLE_ID = 'live-next-defense-styles';
  let latest = null;
  let draft = null;
  let selectedName = '';
  let busy = false;
  let lastSignature = '';
  let bodyObserver = null;
  let skipHiddenRefresh = false;

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
      #${CARD_ID} .nxd-change{width:100%;min-height:40px;border-radius:9px;font-size:.72rem;font-weight:820}
      #${CARD_ID} .nxd-moves{display:grid;gap:6px;margin-bottom:9px}
      #${CARD_ID} .nxd-move{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;border:1px solid #e3e7ec;background:#f8fafc;border-radius:9px;padding:7px 9px}
      #${CARD_ID} .nxd-move strong{font-size:.76rem;color:#1d2939}
      #${CARD_ID} .nxd-move small{display:block;font-size:.63rem;color:#667085;margin-top:1px}
      #${CARD_ID} .nxd-dest{min-width:46px;border-radius:7px;background:#172033;color:#fff;padding:5px 6px;text-align:center;font-size:.66rem;font-weight:850}
      #${CARD_ID} .nxd-dest.bench{background:#eef1f5;color:#475467}
      #${CARD_ID} .nxd-none{border:1px dashed #d6dce3;border-radius:9px;padding:9px;color:#667085;font-size:.72rem;text-align:center;background:#fafbfc;margin-bottom:9px}

      #${MODAL_ID} .modal-content{border:0;border-radius:15px;overflow:hidden}
      #${MODAL_ID} .modal-body{padding:12px 14px 0}
      #${MODAL_ID} .ni-label{font-size:.62rem;text-transform:uppercase;letter-spacing:.08em;font-weight:900;color:#667085;margin-bottom:6px}
      #${MODAL_ID} .ni-bench{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:9px}
      #${MODAL_ID} .ni-bench-player{border:1px solid #cfd5dd;background:#fff;color:#253047;border-radius:9px;padding:7px 9px;font-size:.72rem;font-weight:780;touch-action:manipulation}
      #${MODAL_ID} .ni-bench-player.selected{background:var(--primary-color,#102a66);border-color:var(--primary-color,#102a66);color:#fff}
      #${MODAL_ID} .ni-selected{min-height:34px;border:1px solid #dfe4ea;background:#f8fafc;border-radius:9px;padding:7px 9px;margin-bottom:8px;color:#475467;font-size:.72rem}
      #${MODAL_ID} .ni-selected strong{color:#172033}
      #${MODAL_ID} .ni-field-wrap{margin:0 -2px 8px}
      #${MODAL_ID} .cb-qd-field{width:100%!important;min-height:0!important;aspect-ratio:1.48/1!important;margin:0!important}
      #${MODAL_ID} .cb-qd-spot{cursor:pointer}
      #${MODAL_ID} .cb-qd-spot[data-ni-pos="P"]{cursor:default}
      #${MODAL_ID} .cb-qd-spot.ni-selected-spot .cb-qd-name{outline:3px solid rgba(16,42,102,.22);border-color:var(--primary-color,#102a66)}
      #${MODAL_ID} .ni-pitcher-note{font-size:.67rem;color:#667085;text-align:center;margin:-2px 0 8px}
      #${MODAL_ID} .ni-footer{position:sticky;bottom:0;z-index:3;background:#fff;border-top:1px solid #e7eaf0;margin:10px -14px 0;padding:10px 14px calc(10px + env(safe-area-inset-bottom));display:flex;gap:8px;align-items:center}
      #${MODAL_ID} .ni-footer .btn{min-height:46px;border-radius:10px;font-weight:800}
      #${MODAL_ID} .ni-warning{font-size:.7rem;color:#a32929;font-weight:750}
      @media(max-width:575.98px){
        #${CARD_ID} .nxd-actions{grid-template-columns:1fr 1fr}
        #${CARD_ID} .nxd-actions .btn:last-child{grid-column:1/-1}
        #${MODAL_ID} .modal-dialog{margin:.35rem}
        #${MODAL_ID} .modal-header{padding:11px 13px 9px}
        #${MODAL_ID} .modal-body{padding:9px 10px 0}
        #${MODAL_ID} .cb-qd-field{aspect-ratio:1.58/1!important;max-height:235px!important}
        #${MODAL_ID} .cb-qd-spot{width:62px!important}
        #${MODAL_ID} .cb-qd-name{font-size:.56rem!important;padding:4px!important}
        #${MODAL_ID} .ni-footer{margin:8px -10px 0;padding:9px 10px calc(9px + env(safe-area-inset-bottom))}
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

  function numberMap() {
    const map = new Map();
    document.querySelectorAll('#cbQuickDefense [data-cb-move-player]').forEach(el => {
      const name = String(el.dataset.cbMovePlayer || '').trim();
      if (!name || name === 'Open') return;
      const text = String(el.textContent || '').replace(/\s+/g,' ').trim();
      const found = text.match(/#(\d+)/);
      if (found) map.set(name, found[1]);
    });
    return map;
  }

  function playerLabel(name) {
    const clean = String(name || '').trim();
    if (!clean) return 'Open';
    const number = numberMap().get(clean);
    return number ? `#${number} ${clean}` : clean;
  }

  function coachLabel(value) {
    const clean = String(value || '').trim();
    if (!clean) return '';
    if (!clean.includes(' ')) return '';
    return clean;
  }

  function locationMap(alignment, roster) {
    const map = new Map();
    Object.entries(alignment || {}).forEach(([pos,name]) => { if (name) map.set(name,pos); });
    (roster || []).forEach(player => { if (!map.has(player.name)) map.set(player.name,'BENCH'); });
    return map;
  }

  function effectiveTarget(data) {
    const confirmed = data?.confirmed;
    if (!confirmed) return {};
    if (confirmed.source === 'current') return data.current_alignment || {};
    return confirmed.alignment || {};
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

  function pregameCandidate(data) {
    const planned = {...(data?.planned_alignment || {})};
    const currentPitcher = data?.current_alignment?.P || '';
    if (!Object.values(planned).some(Boolean) || !currentPitcher) return null;
    const conflict = Object.entries(planned).find(([pos,name]) => pos !== 'P' && name === currentPitcher)?.[0];
    if (conflict) return null;
    planned.P = currentPitcher;
    return planned;
  }

  function actionButtons(data) {
    const pregame = pregameCandidate(data);
    return `<div class="nxd-actions">
      <button type="button" class="btn btn-outline-dark" data-bp-action="current">Same Defense</button>
      <button type="button" class="btn btn-outline-primary" data-bp-action="planned" ${pregame ? '' : 'disabled'}>Use Planned Defense</button>
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
        ? `<div class="nxd-none">Your planned Inning ${esc(next)} defense is ready. <strong>Pregame Defense</strong> means the plan you saved before the game.</div>`
        : `<div class="nxd-none">No planned defense for Inning ${esc(next)}.</div>`;
      card.innerHTML = `${head}<div class="nxd-body"><div class="nxd-status waiting"><div><strong>Defense not set</strong><small>Choose who goes out after the third out.</small></div><span class="nxd-badge">NOT SET</span></div>${pregame}${actionButtons(data)}</div>`;
      wireActions(card);
      return true;
    }

    const target = effectiveTarget(data);
    const moves = movesBetween(current, target, roster);
    const moveMarkup = moves.length
      ? `<div class="nxd-moves">${moves.map(move => `<div class="nxd-move"><div><strong>${esc(playerLabel(move.name))}</strong><small>${esc(move.from)} → ${esc(move.to)}</small></div><div class="nxd-dest ${move.to === 'BENCH' ? 'bench' : ''}">${esc(move.to)}</div></div>`).join('')}</div>`
      : '<div class="nxd-none">Same nine going back out.</div>';
    const coach = coachLabel(confirmed.updated_by);
    const status = moves.length ? 'New defense locked in' : 'Same nine going back out';
    card.innerHTML = `${head}<div class="nxd-body"><div class="nxd-status ready"><div><strong>${status}</strong>${coach ? `<small>${esc(coach)} set this</small>` : ''}</div><span class="nxd-badge">LOCKED IN</span></div>${moveMarkup}<button type="button" class="btn btn-outline-primary nxd-change" data-bp-action="adjust">Change it</button></div>`;
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
      if (!quiet) toast(mode === 'current' ? 'Same defense set.' : 'Planned defense set.');
      return data;
    } catch (err) {
      toast(err.message,'danger');
      return null;
    } finally {
      busy = false;
    }
  }

  async function confirmPregame(quiet=false) {
    const candidate = pregameCandidate(latest);
    if (!candidate) {
      if (!quiet) toast('Use New Defense to set this inning.','danger');
      return null;
    }
    if (busy) return null;
    busy = true;
    try {
      const data = await api('POST',{mode:'custom', alignment:candidate});
      lastSignature = '';
      render(data);
      announce(data);
      if (!quiet) toast('Planned defense set.');
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
    card.querySelector('[data-bp-action="planned"]')?.addEventListener('click',()=>confirmPregame());
    card.querySelector('[data-bp-action="adjust"]')?.addEventListener('click',openAdjust);
  }

  function syncAdjustHeader(modal = document.getElementById(MODAL_ID)) {
    if (!modal) return;
    const inning = String(latest?.next_inning || '').trim();
    const title = modal.querySelector('.modal-title');
    const subtitle = title?.parentElement?.querySelector('.small.text-muted');
    if (title) title.textContent = inning ? `Set Defense — Inning ${inning}` : 'Set Defense';
    if (subtitle) subtitle.textContent = inning
      ? `Choose who takes the field for Inning ${inning}.`
      : 'Choose who takes the field next inning.';
  }

  function ensureAdjustModal() {
    let modal = document.getElementById(MODAL_ID);
    if (!modal) {
      modal = document.createElement('div');
      modal.id = MODAL_ID;
      modal.className = 'modal fade';
      modal.tabIndex = -1;
      modal.setAttribute('data-bs-backdrop','static');
      modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Set Defense</h5><div class="small text-muted">Choose who takes the field next inning.</div></div><button class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body" id="${BODY_ID}"></div></div></div>`;
      document.body.appendChild(modal);
      modal.addEventListener('hide.bs.modal', () => {
        const active = document.activeElement;
        if (modal.contains(active) && typeof active?.blur === 'function') active.blur();
      });
      modal.addEventListener('hidden.bs.modal', () => {
        selectedName = '';
        if (skipHiddenRefresh) {
          skipHiddenRefresh = false;
          return;
        }
        window.setTimeout(refresh,80);
      });
    }
    syncAdjustHeader(modal);
    guardModalOwnership();
    return modal;
  }

  function guardModalOwnership() {
    const body = document.getElementById(BODY_ID);
    if (!body || bodyObserver) return;
    bodyObserver = new MutationObserver(() => {
      const modal = document.getElementById(MODAL_ID);
      if (!modal?.classList.contains('show')) return;
      [...body.children].forEach(child => {
        if (child.id !== OWNED_ID) child.remove();
      });
    });
    bodyObserver.observe(body,{childList:true});
  }

  function draftBenchPlayers() {
    const assigned = new Set(Object.values(draft || {}).filter(Boolean));
    return (latest?.roster || [])
      .filter(player => !assigned.has(player.name))
      .sort((a,b)=>a.name.localeCompare(b.name));
  }

  function findDraftPosition(name) {
    return positions(latest?.outfielder_count).find(pos => draft?.[pos] === name) || '';
  }

  function fallbackField() {
    const field = document.createElement('div');
    field.className = 'cb-qd-field';
    const four = Number(latest?.outfielder_count) === 4;
    const outfield = four
      ? [['LF',10,24],['LCF',37,14],['RCF',63,14],['RF',90,24]]
      : [['LF',14,22],['CF',50,11],['RF',86,22]];
    const spots = [...outfield,['3B',18,57],['SS',38,43],['2B',62,43],['1B',82,57],['P',50,61],['C',50,84]];
    field.innerHTML = `<svg class="cb-qd-field-art" viewBox="0 0 100 88" preserveAspectRatio="none" aria-hidden="true"><path d="M7 57 Q9 13 50 6 Q91 13 93 57" fill="none" stroke="rgba(245,245,220,.38)" stroke-width="1.2"/><path d="M50 84 L8 38 M50 84 L92 38" fill="none" stroke="rgba(255,255,255,.88)" stroke-width=".7"/><polygon points="50,75 27,54 50,32 73,54" fill="#cfa56c" opacity=".95"/><polygon points="50,68 34,54 50,40 66,54" fill="#438f58"/><circle cx="50" cy="61" r="4.8" fill="#cfa56c"/><circle cx="50" cy="81" r="6.2" fill="#cfa56c"/></svg>${spots.map(([pos,left,top])=>`<button type="button" class="cb-qd-spot ${pos === 'P' ? 'pitcher' : ''}" style="left:${left}%;top:${top}%" data-cb-position="${pos}"><span class="cb-qd-pos">${pos}</span><span class="cb-qd-name"></span></button>`).join('')}`;
    return field;
  }

  function nextField() {
    const liveField = document.querySelector('#cbQuickDefense .cb-qd-field');
    const field = liveField ? liveField.cloneNode(true) : fallbackField();
    field.removeAttribute('id');
    field.querySelectorAll('[data-cb-move-player]').forEach(el => el.removeAttribute('data-cb-move-player'));
    field.querySelectorAll('.cb-qd-spot').forEach(spot => {
      const pos = String(spot.dataset.cbPosition || '').trim();
      const name = draft?.[pos] || '';
      spot.dataset.niPos = pos;
      spot.removeAttribute('disabled');
      spot.classList.toggle('ni-selected-spot', Boolean(selectedName && name === selectedName));
      if (pos === 'P') {
        spot.disabled = true;
        spot.setAttribute('aria-label', `${playerLabel(name)} stays at pitcher`);
      } else {
        spot.setAttribute('aria-label', name ? `${playerLabel(name)} at ${pos}` : `${pos} open`);
      }
      const label = spot.querySelector('.cb-qd-name');
      if (label) label.textContent = playerLabel(name);
      const posLabel = spot.querySelector('.cb-qd-pos');
      if (posLabel) posLabel.textContent = pos;
    });
    return field;
  }

  function selectOrMove(pos) {
    if (!draft || !pos || pos === 'P') return;
    const occupant = draft[pos] || '';

    if (!selectedName) {
      if (!occupant) return;
      selectedName = occupant;
      renderAdjust();
      return;
    }

    const source = findDraftPosition(selectedName);
    if (source === pos) {
      selectedName = '';
      renderAdjust();
      return;
    }

    if (source && source !== 'P') {
      draft[source] = occupant;
      draft[pos] = selectedName;
    } else if (!source) {
      draft[pos] = selectedName;
    }

    selectedName = '';
    renderAdjust();
  }

  function renderAdjust() {
    const body = document.getElementById(BODY_ID);
    if (!body || !latest || !draft) return;
    syncAdjustHeader();

    const pitcher = latest.current_alignment?.P || draft.P || '';
    if (pitcher) draft.P = pitcher;

    const posList = positions(latest.outfielder_count);
    const holes = posList.filter(pos => !draft[pos]);
    const bench = draftBenchPlayers();
    const selected = selectedName ? playerLabel(selectedName) : '';
    const inning = String(latest.next_inning || '').trim();
    const saveLabel = inning ? `Set Inning ${inning} Defense` : 'Set Defense';

    body.innerHTML = `<div id="${OWNED_ID}"><div class="ni-label">Who’s sitting</div><div class="ni-bench">${bench.length ? bench.map(player => `<button type="button" class="ni-bench-player ${selectedName === player.name ? 'selected' : ''}" data-ni-bench="${esc(player.name)}">${esc(playerLabel(player.name))}</button>`).join('') : '<span class="small text-muted">Nobody</span>'}</div><div class="ni-selected">${selected ? `<strong>${esc(selected)}</strong> — tap a position.` : 'Tap a bench player or fielder, then tap the spot.'}</div><div class="ni-field-wrap" data-ni-field></div><div class="ni-pitcher-note">${pitcher ? `${esc(playerLabel(pitcher))} stays at P.` : 'Pitcher stays the same.'}</div><div class="ni-footer"><div class="me-auto">${holes.length ? `<div class="ni-warning">Fill ${esc(holes.join(', '))}.</div>` : ''}</div><button class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button><button class="btn btn-dark" id="save-next-inning-adjust" ${holes.length ? 'disabled' : ''}>${esc(saveLabel)}</button></div></div>`;

    body.querySelector('[data-ni-field]')?.appendChild(nextField());

    body.querySelectorAll('[data-ni-bench]').forEach(button => {
      button.addEventListener('click',() => {
        selectedName = button.dataset.niBench || '';
        renderAdjust();
      });
    });
    body.querySelectorAll('[data-ni-pos]').forEach(spot => {
      spot.addEventListener('click',() => selectOrMove(spot.dataset.niPos));
    });
    document.getElementById('save-next-inning-adjust')?.addEventListener('click',saveAdjust);
  }

  function openAdjust() {
    if (!latest) return;
    const source = latest.confirmed?.alignment || latest.current_alignment || {};
    draft = {};
    positions(latest.outfielder_count).forEach(pos => { draft[pos] = source[pos] || ''; });
    if (latest.current_alignment?.P) draft.P = latest.current_alignment.P;
    selectedName = '';
    ensureAdjustModal();
    renderAdjust();
    bootstrap.Modal.getOrCreateInstance(document.getElementById(MODAL_ID)).show();
  }

  async function saveAdjust() {
    if (busy || !draft) return;
    busy = true;
    const button = document.getElementById('save-next-inning-adjust');
    if (button) { button.disabled = true; button.textContent = 'Saving…'; }
    try {
      const data = await api('POST',{mode:'custom', alignment:draft});
      skipHiddenRefresh = true;
      const modal = document.getElementById(MODAL_ID);
      const active = document.activeElement;
      if (modal?.contains(active) && typeof active?.blur === 'function') active.blur();
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      lastSignature = '';
      render(data);
      announce(data);
      toast(`Inning ${data.next_inning} defense set.`);
    } catch (err) {
      toast(err.message,'danger');
      const inning = String(latest?.next_inning || '').trim();
      if (button) { button.disabled = false; button.textContent = inning ? `Set Inning ${inning} Defense` : 'Set Defense'; }
    } finally {
      busy = false;
    }
  }

  function modalOpen() {
    return Boolean(document.getElementById(MODAL_ID)?.classList.contains('show'));
  }

  async function refresh() {
    if (busy || modalOpen()) return;
    try {
      const data = await api('GET');
      latest = data;
      const signature = JSON.stringify(data);
      if (signature !== lastSignature || !document.getElementById(CARD_ID)) {
        if (render(data)) lastSignature = signature;
      }
    } catch (_) {
      document.getElementById(CARD_ID)?.remove();
    }
  }

  async function syncSamePointer() {
    if (latest?.confirmed?.source !== 'current') return latest?.confirmed || null;
    return confirmMode('current', true);
  }

  window.CBNextDefense = {
    openNew: openAdjust,
    useSame: () => confirmMode('current', true),
    usePregame: () => confirmPregame(true),
    refresh,
    syncSamePointer,
  };

  installStyles();
  const start = () => {
    setTimeout(refresh,120);
    window.setInterval(refresh,3500);
  };
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded',start,{once:true})
    : start();
})();