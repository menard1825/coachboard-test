(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);

  const CARD_ID = 'live-board-prep-v3';
  const PLAN_CARD_ID = 'live-board-pregame-plan';
  const SWITCH_ID = 'cb-now-next-switch';
  const STYLE_ID = 'live-next-defense-styles';
  const PITCH_MODAL_ID = 'cbNextPitchingChange';
  const OPEN_PICKER_ID = 'cbNextOpenPositionPicker';

  let latest = null;
  let draft = {};
  let activeView = 'now';
  // Pregame Plan: the inning being looked at, and the live inning it was
  // chosen during (a new live inning opens the plan on its next inning).
  let planChoice = {inning: '', during: ''};
  // Pregame Plan's List / Field choice (phones) and its Only changes filter.
  let planView = 'list';
  let planOnlyChanges = false;
  let planBenchOpen = false;
  let liveChangeTimer = null;
  // One next-inning read at a time (see refresh()).
  let readInFlight = null;
  let readStale = false;
  let readForce = false;
  let selected = null;
  let selectedPosition = '';
  // Next Inning saves in the background, one request at a time, like the
  // Pregame Plan. A move changes `draft` (the board) at once; the queue then
  // sends the newest board. `serverBase` is the defense the server last
  // confirmed -- each save sends it so a save cannot overwrite a defense that
  // changed somewhere else in the meantime.
  let serverBase = null;
  let dirty = false;
  let pendingMode = 'custom';
  // Where the board's defense came from while a change is still saving
  // ('custom' after an edit, 'planned' after "Use 2nd-inning plan"), so the
  // header names it at once instead of the last saved source.
  let localSource = null;
  // What the Next Inning Undo just took back; shown until the next change.
  let undoNote = '';
  let activeSavePromise = null;
  let conflictCount = 0;
  // Another device's defense replaced a change of this coach's that never
  // saved. End Inning waits until the coach has looked at what is there
  // now ("Use this defense") or changed it again.
  let conflictPending = false;
  // Whether the defense that replaced it has been read since the conflict.
  // Until it has, the board shows an older defense: no "Use this defense",
  // and End Inning stays held.
  let conflictLoaded = false;
  // The prep revision of this board's own last save: "Your changes" only
  // while the saved defense is still that one.
  let ownRevision = null;
  let rejectCount = 0;
  // Bumped by every local move and every confirmed save, so a poll that was
  // already on its way cannot put an older board back afterwards.
  let localRevision = 0;
  let lastSignature = '';
  let saveMode = 'saved';
  let saveMessage = 'Saved ✓';
  let successMessage = 'Saved ✓';
  let noticeMessage = '';
  let errorMessage = '';
  // "Undo next-inning edit" restores the server's one previous saved
  // defense (confirmed.previous) -- it survives a reload, and brings back
  // its source and whether a coach chose it.
  // The saved defense that Undo is taking back (its revision).
  let undoBaseRevision = null;
  // Pitching readiness from the shared live state (see pitchingReadiness).
  let pitchSummary = null;
  let socketBound = false;
  let dragSurface = null;

  const $ = id => document.getElementById(id);

  const esc = value => String(value ?? '').replace(
    /[&<>"']/g,
    ch => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[ch])
  );

  function positions(count = latest?.outfielder_count) {
    return Number(count) === 4
      ? ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'LCF', 'RCF', 'RF']
      : ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'];
  }

  function spots(count = latest?.outfielder_count) {
    const outfield = Number(count) === 4
      ? [
          ['LF', 10, 24],
          ['LCF', 37, 14],
          ['RCF', 63, 14],
          ['RF', 90, 24],
        ]
      : [
          ['LF', 14, 22],
          ['CF', 50, 11],
          ['RF', 86, 22],
        ];

    return [
      ...outfield,
      ['3B', 18, 57],
      ['SS', 38, 43],
      ['2B', 62, 43],
      ['1B', 82, 57],
      ['P', 50, 61],
      ['C', 50, 84],
    ];
  }

  function normalize(alignment) {
    const clean = {};
    positions().forEach(pos => {
      clean[pos] = alignment?.[pos] || '';
    });
    return clean;
  }

  function snapshot() {
    return normalize(draft);
  }

  function sameAlignment(a, b) {
    return positions().every(
      pos => (a?.[pos] || '') === (b?.[pos] || '')
    );
  }

  function playerByName(name) {
    return (latest?.roster || []).find(
      player => player.name === name
    ) || null;
  }

  function playerLabel(name) {
    if (!name) return 'OPEN';

    const player = playerByName(name);
    const number = String(player?.number ?? '').trim();

    return number
      ? `#${number} ${name}`
      : name;
  }

  function assignedNames() {
    return new Set(
      Object.values(draft || {}).filter(Boolean)
    );
  }

  function benchPlayers() {
    const assigned = assignedNames();

    return (latest?.roster || [])
      .filter(player => !assigned.has(player.name))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  function findSource(name) {
    return positions().find(
      pos => draft?.[pos] === name
    ) || 'BENCH';
  }

  function duplicateNames() {
    const counts = new Map();

    Object.values(draft || {})
      .filter(Boolean)
      .forEach(name => {
        counts.set(name, (counts.get(name) || 0) + 1);
      });

    return [...counts.entries()]
      .filter(([, count]) => count > 1)
      .map(([name]) => name);
  }

  function openPositions() {
    return positions().filter(
      pos => !draft?.[pos]
    );
  }

  function nextWarningsMarkup() {
    const open = openPositions();
    const duplicates = duplicateNames();
    const items = [];

    if (!draft?.P) {
      items.push(
        '<div class="cb-next-warning danger" id="cb-next-needs-pitcher">' +
        'Set a pitcher for the next inning.' +
        '</div>'
      );
    }

    const otherOpen = open.filter(pos => pos !== 'P');

    if (otherOpen.length) {
      items.push(
        `<div class="cb-next-warning">⚠ ${esc(
          otherOpen.join(', ')
        )} ${otherOpen.length === 1 ? 'is' : 'are'} open.</div>`
      );
    }

    duplicates.forEach(name => {
      items.push(
        `<div class="cb-next-warning danger">` +
        `${esc(playerLabel(name))} is assigned to more than one position.` +
        `</div>`
      );
    });

    return items.join('');
  }

  function planStateText() {
    const source = boardSource();
    const nextLabel = inningOrdinal(
      latest?.next_inning || ''
    );
    const currentLabel = inningOrdinal(
      latest?.current_inning || ''
    );

    // What the board shows during a conflict: the other device's defense,
    // or -- when it could not be read -- the last one this board loaded.
    if (conflictPending) {
      const inning = nextLabel ? ` for the ${nextLabel}` : '';
      return conflictLoaded
        ? `Saved on another device${inning}`
        : `Last loaded defense${inning} · may be out of date`;
    }

    if (source === 'planned') {
      const carry = pitcherCarried();
      const plan = nextLabel
        ? `Pregame plan for the ${nextLabel}`
        : 'Pregame defensive plan';
      // The plan named another pitcher: say who pitches, and where the
      // plan's pitcher goes instead (the two trade places).
      return carry ? `${plan} · ${carriedSwap(carry)}` : plan;
    }

    if (source === 'current') {
      return currentLabel
        ? `Same defense as the ${currentLabel}`
        : 'Same defense as this inning';
    }

    const saved = nextLabel
      ? `Changes saved for the ${nextLabel}`
      : 'Changes saved';
    // The saved fielding edit, with the pitcher a live change carried in.
    const carry = pitcherCarried();
    return carry ? `${saved} · ${carriedSwap(carry)}` : saved;
  }

  // The server carried the current pitcher forward instead of the plan's
  // (pitching_eligibility.carry_planned_pitcher), and the board still has
  // that pitcher on the mound.
  function pitcherCarried() {
    const carry = latest?.pitcher_carry;
    return carry?.pitcher && snapshot().P === carry.pitcher ? carry : null;
  }

  // "Hansen keeps pitching; Reed moves to 1B." -- or sits (Hansen was
  // planned to sit), or the spot is open (Reed is no longer here).
  function carriedSwap(carry) {
    const board = snapshot();
    const spot = carry.position;
    let move;
    if (!spot) move = `${carry.planned_pitcher} sits`;
    else if (board[spot] === carry.planned_pitcher) move = `${carry.planned_pitcher} moves to ${spot}`;
    else if (!board[spot]) move = `${spot} is open`;
    else move = `${board[spot]} plays ${spot}`;
    return `${carry.pitcher} keeps pitching; ${move}.`;
  }

  function boardSource() {
    return localSource || latest?.confirmed?.source || '';
  }

  // The upcoming inning's own plan, when it has one ("planned_seed").
  function plannedSeed() {
    const seed = latest?.planned_seed;
    return seed && Object.values(seed).some(Boolean) ? normalize(seed) : null;
  }

  // A separately planned upcoming inning that the board is not using: say so
  // and offer it back. An inning with no plan just carries the field forward.
  function skippedPlanText() {
    const seed = plannedSeed();
    if (!seed || sameAlignment(seed, draft)) return '';
    const next = inningOrdinal(latest?.next_inning || '');
    const current = inningOrdinal(latest?.current_inning || '');
    return boardSource() === 'current'
      ? `Using the ${current}-inning field. Your ${next}-inning plan won't be used.`
      : `Changed for the ${next}. Your ${next}-inning plan won't be used.`;
  }

  // One line in the card header while a player is moving. It replaces the
  // plan line in place, so the field never moves when a player is tapped.
  function moveHint() {
    if (!selected) return '';
    const who = playerLabel(selected.name);
    return selected.source === 'BENCH'
      ? `Moving ${who} — tap a spot`
      : `Moving ${who} — tap a spot or Bench`;
  }

  function fieldSpot(pos, left, top) {
    const name = draft?.[pos] || '';
    const isOpen = !name;
    const number = isOpen ? '' : String(playerByName(name)?.number ?? '').trim();

    const selectedHere =
      (
        selected &&
        selected.source === pos &&
        selected.name === name
      ) ||
      selectedPosition === pos;

    const isDestination =
      Boolean(selected) &&
      selected.source !== pos;

    return `
      <button
        type="button"
        class="cb-qd-spot cb-next-spot
          ${pos === 'P' ? 'pitcher' : ''}
          ${isOpen ? 'cb-next-open' : ''}
          ${selectedHere ? 'cb-next-selected' : ''}
          ${isDestination ? 'cb-next-destination' : ''}"
        style="left:${left}%;top:${top}%"
        data-next-position="${esc(pos)}"
        data-next-player="${esc(name)}"
        ${pos === 'P' && isOpen ? 'aria-describedby="cb-next-needs-pitcher"' : ''}
        aria-label="${esc(
          isOpen
            ? `${pos} open`
            : `${playerLabel(name)} at ${pos}`
        )}"
      >
        <span class="cb-qd-pos">${esc(pos)}${number ? ` <span class="cb-qd-num">#${esc(number)}</span>` : ''}</span>
        <span class="cb-qd-name">
          ${esc(isOpen ? 'OPEN' : name)}
        </span>
      </button>`;
  }

  // The diamond, baselines and outfield arc shared by Next Inning and
  // Pregame Plan; each draws its own markers on top.
  function fieldArt() {
    return `
        <svg
          class="cb-qd-field-art"
          viewBox="0 0 100 88"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <path
            d="M7 57 Q9 13 50 6 Q91 13 93 57"
            fill="none"
            stroke="rgba(245,245,220,.38)"
            stroke-width="1.2"
          />
          <path
            d="M50 84 L8 38 M50 84 L92 38"
            fill="none"
            stroke="rgba(255,255,255,.88)"
            stroke-width=".7"
          />
          <polygon
            points="50,75 27,54 50,32 73,54"
            fill="#cfa56c"
            opacity=".95"
          />
          <polygon
            points="50,68 34,54 50,40 66,54"
            fill="#438f58"
          />
          <circle cx="50" cy="61" r="4.8" fill="#cfa56c"/>
          <circle cx="50" cy="81" r="6.2" fill="#cfa56c"/>
        </svg>`;
  }

  function fieldMarkup() {
    return `
      <div class="cb-qd-field cb-next-field">
        ${fieldArt()}

        ${spots().map(
          ([pos, left, top]) => fieldSpot(pos, left, top)
        ).join('')}
      </div>`;
  }

  function benchMarkup() {
    const bench = benchPlayers();
    // A fielder is moving: "Bench #27 Riggins" (and the Bench's empty
    // space) benches them. A bench player's own chip never does -- it
    // selects that player instead.
    const benchTarget = Boolean(selected) && selected.source !== 'BENCH';
    const who = selected ? playerLabel(selected.name) : '';

    return `
      <div
        class="cb-next-bench ${benchTarget ? 'destination-active' : ''}"
        ${benchTarget ? 'data-next-bench-area' : ''}
      >
        <div class="cb-next-bench-head">
          <strong>Bench · ${bench.length}</strong>
          ${
            benchTarget
              ? `<button
                  type="button"
                  class="cb-next-bench-cta"
                  data-next-bench-selected
                >Bench ${esc(who)}</button>`
              : '<span>Tap a bench player to move them</span>'
          }
        </div>

        <div class="cb-next-bench-chips">
          ${
            bench.length
              ? bench.map(player => `
                  <button
                    type="button"
                    class="cb-next-bench-player
                      ${
                        selected?.source === 'BENCH' &&
                        selected?.name === player.name
                          ? 'selected'
                          : ''
                      }"
                    data-next-bench-player="${esc(player.name)}"
                  >
                    ${esc(playerLabel(player.name))}
                  </button>
                `).join('')
              : '<span class="small text-muted">Nobody on the bench.</span>'
          }
        </div>
      </div>`;
  }


  function openPositionPickerModal() {
    let modal = $(OPEN_PICKER_ID);

    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = OPEN_PICKER_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('aria-hidden', 'true');
    modal.setAttribute('aria-labelledby', `${OPEN_PICKER_ID}-title`);

    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-sm">
        <div class="modal-content">
          <div class="modal-header">
            <h5
              class="modal-title"
              id="${OPEN_PICKER_ID}-title"
              data-open-position-title
            ></h5>
            <button
              type="button"
              class="btn-close"
              data-bs-dismiss="modal"
              aria-label="Close"
            ></button>
          </div>
          <div class="modal-body">
            <div
              class="small text-muted mb-3"
              data-open-position-help
            ></div>
            <div data-open-position-choices></div>
          </div>
        </div>
      </div>`;

    document.body.appendChild(modal);
    return modal;
  }

  // An open spot is a "who plays here?" decision, not a two-step move mode.
  // Bench players fill it directly; choosing a fielder moves them here and
  // leaves their old spot open. Moves involving P still flow through
  // movePlayer(), which owns the special pitching questions.
  function askOpenPosition(pos) {
    const board = snapshot();

    if (!pos || board[pos]) return;

    const modal = openPositionPickerModal();
    const instance = bootstrap.Modal.getOrCreateInstance(modal);
    const title = modal.querySelector('[data-open-position-title]');
    const help = modal.querySelector('[data-open-position-help]');
    const choices = modal.querySelector('[data-open-position-choices]');
    const inning = inningOrdinal(latest?.next_inning || '');

    title.textContent =
      pos === 'P'
        ? (inning ? `Who's pitching in the ${inning}?` : "Who's pitching next inning?")
        : (inning ? `Who plays ${pos} in the ${inning}?` : `Who plays ${pos} next inning?`);

    // Another spot open too: name it, so it's clear which one this fills.
    const others = positions().filter(other => other !== pos && !board[other]);
    help.textContent =
      'Choose a player. If they are already on the field, their current spot will be left open.' +
      (others.length ? ` Also open: ${others.join(', ')}.` : '');

    choices.replaceChildren();

    const addHeading = label => {
      const heading = document.createElement('div');
      heading.className =
        'small fw-bold text-uppercase text-muted mt-2 mb-1';
      heading.textContent = label;
      choices.appendChild(heading);
    };

    const choose = name => {
      const apply = () => {
        if (!sameAlignment(snapshot(), board) || (snapshot()[pos] || '')) {
          noticeMessage =
            'The defense changed while you were choosing. Nothing was moved.';
          renderSyncState();
          return;
        }

        movePlayer(name, findSource(name), pos);
      };

      modal.addEventListener('hidden.bs.modal', apply, {once: true});
      instance.hide();
    };

    const addPlayer = (name, detail = '') => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className =
        'btn btn-outline-primary w-100 text-start mb-2';
      button.textContent =
        detail
          ? `${playerLabel(name)} · ${detail}`
          : playerLabel(name);
      button.addEventListener('click', () => choose(name));
      choices.appendChild(button);
    };

    const bench = benchPlayers();

    if (bench.length) {
      addHeading('Bench');
      bench.forEach(player => addPlayer(player.name));
    }

    const fielders = positions()
      .filter(position => board[position] && position !== pos)
      .map(position => ({
        position,
        name: board[position],
      }));

    if (fielders.length) {
      addHeading('On the field');
      fielders.forEach(player => addPlayer(player.name, player.position));
    }

    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'btn btn-outline-secondary w-100 mt-1';
    cancel.textContent = 'Cancel';
    cancel.setAttribute('data-bs-dismiss', 'modal');
    choices.appendChild(cancel);

    instance.show();
  }

  function installStyles() {
    if ($(STYLE_ID)) return;

    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${SWITCH_ID}{
        display:flex;
        justify-content:flex-end;
        padding:0;
        margin:0 0 8px;
        border:0;
        background:transparent;
      }

      #${SWITCH_ID} .btn{
        min-height:44px;
        padding:8px 12px;
        border:1px solid #c7ced8!important;
        border-radius:10px!important;
        background:#fff;
        color:#344054;
        font-size:.82rem;
        font-weight:850;
        line-height:1.2;
        box-shadow:none!important;
      }

      /* Pregame Plan: the coach's plan as a reference next to what the game
         actually has. Violet is only ever the plan; black is the game. */
      #${PLAN_CARD_ID}{
        --cb-plan-ink:#1b1f2a;
        --cb-plan-muted:#5c6576;
        --cb-plan-line:#dde1e8;
        --cb-plan-ref:#4b3fa8;
        --cb-plan-ref-bg:#f1efff;
        --cb-plan-ref-line:#d4cff7;
        --cb-plan-chg:#8a4f00;
        --cb-plan-chg-bg:#fff3dc;
        --cb-plan-red:#b42318;
        --cb-plan-red-bg:#fff0ee;
        --cb-plan-ok:#067647;
        border:1.5px solid var(--cb-plan-ref-line);
        border-radius:14px;
        background:linear-gradient(#fbfaff,#fff 64px);
        margin:0 0 10px;
        box-shadow:0 2px 7px rgba(16,24,40,.08);
        color:var(--cb-plan-ink);
        padding:12px;
        display:flex;
        flex-direction:column;
        gap:10px;
        min-width:0;
      }

      #${PLAN_CARD_ID}[hidden]{
        display:none!important;
      }

      #${PLAN_CARD_ID} button{
        font-family:inherit;
        touch-action:manipulation;
      }

      #${PLAN_CARD_ID} button:focus-visible{
        outline:3px solid #f5c400;
        outline-offset:2px;
      }

      #${PLAN_CARD_ID} .cb-plan-head{
        display:flex;
        justify-content:space-between;
        align-items:center;
        gap:8px;
        flex-wrap:wrap;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-title{
        margin:0;
        font-size:1.15rem;
        font-weight:900;
        line-height:1.2;
        min-width:0;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-title .cb-plan-tag{
        display:inline-block;
        margin-left:6px;
        padding:2px 8px;
        border-radius:999px;
        background:#eef0f3;
        color:#344054;
        font-size:.75rem;
        font-weight:800;
        vertical-align:3px;
      }

      #${PLAN_CARD_ID} .cb-plan-readonly{
        font-size:.75rem;
        font-weight:800;
        color:var(--cb-plan-ref);
        background:var(--cb-plan-ref-bg);
        border:1px solid var(--cb-plan-ref-line);
        border-radius:999px;
        padding:4px 10px;
        white-space:nowrap;
      }

      #${PLAN_CARD_ID} .cb-plan-empty,
      #${PLAN_CARD_ID} .cb-plan-note{
        color:var(--cb-plan-muted);
        font-size:.9rem;
        font-weight:600;
        line-height:1.35;
      }

      #${PLAN_CARD_ID} .cb-plan-innings{
        display:grid;
        gap:5px;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-btn{
        min-height:50px;
        min-width:0;
        border:1.5px solid var(--cb-plan-line);
        border-radius:11px;
        background:#fff;
        color:var(--cb-plan-ink);
        display:flex;
        flex-direction:column;
        align-items:center;
        justify-content:center;
        gap:2px;
        padding:4px 2px;
        font-size:1.05rem;
        font-weight:900;
        line-height:1;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-btn small{
        font-size:.68rem;
        font-weight:800;
        color:var(--cb-plan-muted);
        line-height:1.05;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-btn[data-plan-has="false"]{
        background:#f6f7f9;
        border-style:dashed;
        border-color:#b8bec9;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-btn[aria-pressed="true"]{
        border-color:#0e0b6e;
        box-shadow:0 0 0 2px #0e0b6e inset;
        background:#fff;
      }

      /* The game differed from this inning's plan. */
      #${PLAN_CARD_ID} .cb-plan-inning-btn[data-plan-live-differs="true"] b::after{
        content:"";
        display:inline-block;
        width:7px;
        height:7px;
        margin-left:3px;
        border-radius:50%;
        background:var(--cb-plan-chg);
        vertical-align:3px;
      }

      /* One line: what changed for the inning chosen. */
      #${PLAN_CARD_ID} .cb-plan-status{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:4px 10px;
        flex-wrap:wrap;
      }

      #${PLAN_CARD_ID} .cb-plan-summary{
        margin:0;
        font-size:1rem;
        font-weight:850;
        line-height:1.25;
        color:var(--cb-plan-ink);
      }

      #${PLAN_CARD_ID} .cb-plan-summary[data-kind="changes"]{color:var(--cb-plan-chg)}
      #${PLAN_CARD_ID} .cb-plan-summary[data-kind="match"]{color:var(--cb-plan-ok)}
      #${PLAN_CARD_ID} .cb-plan-summary[data-kind="norec"],
      #${PLAN_CARD_ID} .cb-plan-summary[data-kind="noplan"],
      #${PLAN_CARD_ID} .cb-plan-summary[data-kind="later"]{color:var(--cb-plan-muted)}

      /* Plan against the plan's inning before. */
      #${PLAN_CARD_ID} .cb-plan-changes{
        margin-top:-6px;
        color:var(--cb-plan-muted);
        font-size:.8rem;
        font-weight:750;
      }

      #${PLAN_CARD_ID} .cb-plan-changes.has-changes{
        color:var(--cb-plan-ref);
      }

      /* List or Field: the only two views, on every screen. */
      #${PLAN_CARD_ID} .cb-plan-toolbar{
        display:flex;
        background:#e1e4ea;
        border-radius:10px;
        padding:3px;
        gap:3px;
        width:100%;
        max-width:360px;
      }

      #${PLAN_CARD_ID} .cb-plan-toolbar button{
        flex:1 1 0;
        min-height:44px;
        border:0;
        border-radius:8px;
        background:transparent;
        color:#344054;
        font-size:.9rem;
        font-weight:800;
        padding:0 6px;
        white-space:nowrap;
      }

      #${PLAN_CARD_ID} .cb-plan-toolbar button[aria-pressed="true"]{
        background:#fff;
        color:var(--cb-plan-ink);
        box-shadow:0 1px 2px rgba(0,0,0,.15);
      }

      /* Small text actions: the list filter, the bench, Edit next inning. */
      #${PLAN_CARD_ID} .cb-plan-linkbtn{
        min-height:44px;
        border:0;
        background:transparent;
        color:#0e0b6e;
        font-size:.85rem;
        font-weight:800;
        padding:0 4px;
        text-decoration:underline;
        text-underline-offset:3px;
        white-space:nowrap;
      }

      #${PLAN_CARD_ID} .cb-plan-listbar{
        display:flex;
        justify-content:flex-end;
        margin:-4px 0 -8px;
      }

      #${PLAN_CARD_ID} .cb-plan-benchline{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:4px 10px;
        flex-wrap:wrap;
        padding:0 4px;
        color:var(--cb-plan-muted);
        font-size:.875rem;
        font-weight:700;
      }

      #${PLAN_CARD_ID} .cb-plan-views{
        min-width:0;
      }

      #${PLAN_CARD_ID} .cb-plan-listwrap{
        display:flex;
        flex-direction:column;
        gap:10px;
        min-width:0;
      }

      /* One view at a time, on phones and iPads alike. */
      #${PLAN_CARD_ID} .cb-plan-views[data-plan-view="list"] .cb-plan-fieldwrap,
      #${PLAN_CARD_ID} .cb-plan-views[data-plan-view="field"] .cb-plan-listwrap{
        display:none;
      }

      #${PLAN_CARD_ID} .cb-plan-list{
        display:flex;
        flex-direction:column;
        border:1px solid var(--cb-plan-line);
        border-radius:12px;
        background:#fff;
        overflow:hidden;
      }

      #${PLAN_CARD_ID} .cb-plan-row{
        display:grid;
        grid-template-columns:38px minmax(0,1fr) minmax(0,1fr);
        gap:8px;
        align-items:center;
        min-height:50px;
        padding:5px 8px;
        border-top:1px solid var(--cb-plan-line);
      }

      #${PLAN_CARD_ID} .cb-plan-list.single .cb-plan-row{
        grid-template-columns:38px minmax(0,1fr);
      }

      #${PLAN_CARD_ID} .cb-plan-row.cb-plan-colhead{
        min-height:0;
        padding:7px 8px 6px;
        border-top:0;
        background:#f8f9fb;
        font-size:.72rem;
        font-weight:800;
        letter-spacing:.04em;
        text-transform:uppercase;
        color:var(--cb-plan-muted);
      }

      #${PLAN_CARD_ID} .cb-plan-colhead .cb-plan-planned{
        color:var(--cb-plan-ref);
      }

      #${PLAN_CARD_ID} .cb-plan-row[data-plan-changed="true"]{
        background:var(--cb-plan-chg-bg);
      }

      #${PLAN_CARD_ID} .cb-plan-pos{
        font-size:.95rem;
        font-weight:900;
        color:#344054;
      }

      /* Names wrap between words, never inside one ("Hollingswort-h"). */
      #${PLAN_CARD_ID} .cb-plan-nm{
        display:block;
        font-size:1rem;
        font-weight:700;
        line-height:1.15;
        overflow-wrap:break-word;
      }

      #${PLAN_CARD_ID} .cb-plan-nm small{
        margin-left:4px;
        font-size:.75rem;
        font-weight:600;
        color:var(--cb-plan-muted);
        white-space:nowrap;
      }

      #${PLAN_CARD_ID} .cb-plan-planned .cb-plan-nm{
        color:var(--cb-plan-ref);
      }

      #${PLAN_CARD_ID} .cb-plan-na{
        font-size:.85rem;
        font-weight:600;
        font-style:italic;
        color:#6b7385;
      }

      #${PLAN_CARD_ID} .cb-plan-flag{
        display:inline-block;
        margin-top:3px;
        padding:1px 7px;
        border-radius:999px;
        background:#ffe1ad;
        color:var(--cb-plan-chg);
        font-size:.7rem;
        font-weight:800;
      }

      #${PLAN_CARD_ID} .cb-plan-emp{
        display:inline-flex;
        align-items:center;
        gap:5px;
        color:var(--cb-plan-red);
        font-size:.95rem;
        font-weight:800;
      }

      #${PLAN_CARD_ID} .cb-plan-emp::before{
        content:"";
        width:9px;
        height:9px;
        border-radius:50%;
        background:var(--cb-plan-red);
      }

      #${PLAN_CARD_ID} .cb-plan-norec{
        font-size:.85rem;
        font-weight:600;
        color:#5c6576;
      }

      #${PLAN_CARD_ID} .cb-plan-bench{
        align-items:start;
        font-size:.875rem;
      }

      #${PLAN_CARD_ID} .cb-plan-bench .cb-plan-pos{
        padding-top:2px;
        font-size:.72rem;
      }

      #${PLAN_CARD_ID} .cb-plan-bench .cb-plan-planned{
        color:var(--cb-plan-ref);
        font-weight:600;
      }

      #${PLAN_CARD_ID} .cb-plan-fieldwrap{
        display:flex;
        flex-direction:column;
        gap:6px;
        min-width:0;
        width:100%;
        max-width:460px;
        margin:0 auto;
        container-type:inline-size;
      }


      #${PLAN_CARD_ID} .cb-plan-field{
        position:relative;
        width:100%;
        aspect-ratio:1/1.3;
        max-height:560px;
        overflow:hidden;
        border-radius:12px;
        background:linear-gradient(#3d8b4c,#357d43);
      }

      #${PLAN_CARD_ID} .cb-plan-field::before{
        content:"";
        position:absolute;
        left:50%;
        bottom:-24%;
        width:118%;
        aspect-ratio:1;
        transform:translateX(-50%);
        border:2px solid rgba(255,255,255,.22);
        border-radius:50%;
      }

      #${PLAN_CARD_ID} .cb-plan-diamond{
        position:absolute;
        left:50%;
        top:47%;
        width:30%;
        aspect-ratio:1;
        background:#c9a06a;
        transform:translate(-50%,0) rotate(45deg);
        border-radius:4px;
      }

      #${PLAN_CARD_ID} .cb-plan-spot{
        position:absolute;
        transform:translate(-50%,-50%);
        width:31%;
        min-height:56px;
        border-radius:10px;
        background:#fff;
        border:1.5px solid #cfd4dc;
        padding:4px;
        text-align:center;
        display:flex;
        flex-direction:column;
        justify-content:center;
        gap:2px;
        line-height:1.1;
      }

      #${PLAN_CARD_ID} .cb-plan-spot[data-plan-changed="true"]{
        border:2.5px solid #e3a33a;
      }

      #${PLAN_CARD_ID} .cb-plan-spot-pos{
        font-size:.75rem;
        font-weight:900;
        color:#344054;
      }

      /* Short names ("Alexander M.") on one line, so a marker never grows
         into its neighbour; the list and the marker's label have full names. */
      #${PLAN_CARD_ID} .cb-plan-spot-plan,
      #${PLAN_CARD_ID} .cb-plan-spot-game{
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
      }

      #${PLAN_CARD_ID} .cb-plan-spot-plan{
        font-size:.8rem;
        font-weight:700;
        color:var(--cb-plan-ref);
      }

      #${PLAN_CARD_ID} .cb-plan-spot-game{
        font-size:.84rem;
        font-weight:800;
        border-top:1px solid #e4e7ec;
        padding-top:2px;
      }

      #${PLAN_CARD_ID} .cb-plan-spot .cb-plan-emp{
        font-size:.8rem;
      }

      #${PLAN_CARD_ID} .cb-plan-spot .cb-plan-na,
      #${PLAN_CARD_ID} .cb-plan-spot .cb-plan-norec{
        font-size:.75rem;
      }

      /* After the marker rules above, so these win. A narrow field (small phones, the iPad's side-by-side column): wider
         markers and slightly smaller type, so "Alexander M." still fits. */
      @container (max-width:360px){
        #${PLAN_CARD_ID} .cb-plan-spot{
          width:32.5%;
          padding:4px 2px;
        }

        #${PLAN_CARD_ID} .cb-plan-spot-plan{
          font-size:.72rem;
        }

        #${PLAN_CARD_ID} .cb-plan-spot-game{
          font-size:.76rem;
        }
      }

      /* 320px phones (a field about 288px wide). */
      @container (max-width:300px){
        #${PLAN_CARD_ID} .cb-plan-spot{
          width:33%;
        }

        #${PLAN_CARD_ID} .cb-plan-spot-plan,
        #${PLAN_CARD_ID} .cb-plan-spot-game{
          font-size:.68rem;
          font-weight:750;
        }
      }

      #${PLAN_CARD_ID} .cb-plan-legend{
        display:flex;
        flex-wrap:wrap;
        gap:4px 12px;
        font-size:.75rem;
        color:var(--cb-plan-muted);
      }

      #${PLAN_CARD_ID} .cb-plan-legend b.ref{
        color:var(--cb-plan-ref);
      }

      #${PLAN_CARD_ID} .cb-plan-next{
        border:1.5px solid #c7d6f5;
        border-radius:12px;
        background:#f5f8ff;
        padding:10px 12px;
        display:flex;
        flex-direction:column;
        gap:6px;
      }

      #${PLAN_CARD_ID} .cb-plan-next-head{
        display:flex;
        justify-content:space-between;
        align-items:center;
        gap:8px;
        flex-wrap:wrap;
      }

      #${PLAN_CARD_ID} .cb-plan-next-head strong{
        display:block;
        font-size:1rem;
      }

      #${PLAN_CARD_ID} .cb-plan-next-head span{
        display:block;
        font-size:.85rem;
        color:var(--cb-plan-muted);
      }

      #${PLAN_CARD_ID} .cb-plan-next-list{
        display:grid;
        grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
        gap:4px 12px;
        margin:0;
        padding:0;
        list-style:none;
        font-size:.9rem;
      }

      #${PLAN_CARD_ID} .cb-plan-next-list li{
        min-width:0;
        overflow-wrap:anywhere;
      }

      #${PLAN_CARD_ID} .cb-plan-next-list b{
        display:inline-block;
        min-width:30px;
        color:#344054;
      }

      @media(max-width:399.98px){
        #${PLAN_CARD_ID} .cb-plan-inw{
          display:none;
        }

        /* The chosen inning's button already says Now / Next / Played:
           keep the tag for screen readers, and the title on one row. */
        #${PLAN_CARD_ID} .cb-plan-inning-title .cb-plan-tag{
          position:absolute;
          width:1px;
          height:1px;
          overflow:hidden;
          clip:rect(0 0 0 0);
          white-space:nowrap;
        }

        #${PLAN_CARD_ID} .cb-plan-readonly{
          font-size:.7rem;
          padding:3px 8px;
        }

        #${PLAN_CARD_ID} .cb-plan-inning-title{
          font-size:1.05rem;
        }
      }

      @media(max-width:374.98px){
        #${PLAN_CARD_ID}{
          padding:10px 8px;
        }

        #${PLAN_CARD_ID} .cb-plan-toolbar button{
          font-size:.8rem;
          padding:0 4px;
        }

        #${PLAN_CARD_ID} .cb-plan-row{
          grid-template-columns:28px minmax(0,1fr) minmax(0,1fr);
          gap:4px;
          padding:5px 4px;
        }

        #${PLAN_CARD_ID} .cb-plan-list.single .cb-plan-row{
          grid-template-columns:28px minmax(0,1fr);
        }

        #${PLAN_CARD_ID} .cb-plan-nm{
          font-size:.94rem;
        }

        #${PLAN_CARD_ID} .cb-plan-inning-btn small{
          font-size:.66rem;
        }

      }

      body.cb-next-sheet-open::after{
        content:"";
        position:fixed;
        inset:0;
        z-index:1085;
        background:rgba(16,24,40,.38);
      }

      #${CARD_ID}{
        position:fixed;
        left:50%;
        right:auto;
        bottom:0;
        z-index:1090;
        width:min(100%,960px);
        max-height:90dvh;
        overflow:auto;
        transform:translateX(-50%);
        border:1.5px solid #cfd6df;
        border-radius:18px 18px 0 0;
        background:#fff;
        margin:0;
        box-shadow:0 -10px 32px rgba(16,24,40,.22);
      }

      #${CARD_ID}[hidden]{
        display:none!important;
      }

      @media(min-width:760px){
        #${CARD_ID}{
          bottom:18px;
          max-height:88dvh;
          border-radius:18px;
        }
      }

      #${CARD_ID} .cb-next-head{
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:10px;
        padding:11px 12px 9px;
        border-bottom:1px solid #e7ebef;
      }

      #${CARD_ID} .cb-next-title{
        color:#172033;
        font-size:1.05rem;
        line-height:1.15;
        font-weight:900;
      }

      /*
       * Title and save chip share the first row; the plan / move hint and
       * the pitcher line below them use the card's full width, so the move
       * hint fits on one line on a phone.
       */
      #${CARD_ID} .cb-next-head{
        display:grid;
        grid-template-columns:minmax(0,1fr) auto;
        align-items:center;
        column-gap:10px;
      }

      #${CARD_ID} .cb-next-head-main{
        display:contents;
      }

      #${CARD_ID} .cb-next-title{
        grid-column:1;
        grid-row:1;
      }

      #${CARD_ID} .cb-next-save{
        grid-column:2;
        grid-row:1;
      }

      #${CARD_ID} .cb-next-head-main > :not(.cb-next-title){
        grid-column:1 / -1;
        min-width:0;
      }

      /* One line, plan or move hint, so tapping a player shifts nothing. */
      #${CARD_ID} .cb-next-sub{
        margin-top:2px;
        color:#667085;
        font-size:var(--cb-text-xs);
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
      }

      /* The plan line can explain a carried pitcher: let it wrap on a phone
         instead of cutting off the part that explains it. */
      #${CARD_ID} .cb-next-sub[data-next-hint]{
        white-space:normal;
        overflow:visible;
        text-overflow:clip;
        overflow-wrap:anywhere;
      }

      #${CARD_ID} .cb-next-sub.cb-next-hint{
        color:#173b78;
        font-weight:850;
      }

      #${CARD_ID} .cb-next-save{
        flex:0 0 auto;
        min-height:30px;
        display:inline-flex;
        align-items:center;
        gap:5px;
        padding:5px 8px;
        border:1px solid #b8ddc4;
        border-radius:999px;
        background:#edf8f1;
        color:#176b38;
        font-size:var(--cb-text-2xs);
        font-weight:850;
      }

      #${CARD_ID} .cb-next-save.saving{
        border-color:#bdd0ea;
        background:#f2f6fc;
        color:#315d98;
      }

      #${CARD_ID} .cb-next-save.error,
      #${CARD_ID} .cb-next-save.conflict{
        border-color:#efb5ae;
        background:#fff1ef;
        color:#a12d26;
      }

      #${CARD_ID} .cb-next-save.waiting{
        border-color:#e6ca82;
        background:#fff8e6;
        color:#775a10;
      }

      #${CARD_ID} .cb-next-notice{
        border:1px solid #bdd0ea;
        border-radius:8px;
        background:#f2f6fc;
        color:#315d98;
        padding:7px 8px;
        font-size:.68rem;
        font-weight:780;
      }

      #${CARD_ID} .cb-next-notice[hidden]{
        display:none;
      }

      #${CARD_ID} .cb-next-pitcher-status{
        margin-top:3px;
        color:#176b38;
        font-size:var(--cb-text-xs);
        font-weight:750;
        line-height:1.3;
      }

      #${CARD_ID} .cb-next-pitcher-status[hidden]{
        display:none;
      }

      #${CARD_ID} .cb-next-pitcher-status.unknown,
      #${CARD_ID} .cb-next-pitcher-status.advisory,
      #${CARD_ID} .cb-next-pitcher-status.rule_conflict{
        margin-top:5px;
        padding:4px 7px;
        border-radius:7px;
        font-weight:800;
      }

      #${CARD_ID} .cb-next-pitcher-status.unknown,
      #${CARD_ID} .cb-next-pitcher-status.advisory{
        border:1px solid #e6ca82;
        background:#fff8e6;
        color:#775a10;
      }

      #${CARD_ID} .cb-next-pitcher-status.rule_conflict{
        border:1px solid #efb5ae;
        background:#fff1ef;
        color:#a12d26;
      }

      #cbNowOpenWarning{
        grid-column:1 / -1;
        order:-2;
        margin:0;
        padding:4px 8px;
        border:1px solid #efb5ae;
        border-radius:8px;
        background:#fff1ef;
        color:#a12d26;
        font-size:.72rem;
        font-weight:850;
        line-height:1.25;
        text-align:center;
        cursor:pointer;
        touch-action:manipulation;
      }

      #cbNextOpenWarning{
        cursor:pointer;
        touch-action:manipulation;
        grid-column:1 / -1;
        order:-1;
        margin:0;
        padding:4px 8px;
        border:1px solid #e6ca82;
        border-radius:8px;
        background:#fff8e6;
        color:#775a10;
        font-size:.72rem;
        font-weight:800;
        line-height:1.25;
        text-align:center;
      }

      @media(max-width:575.98px){
        html body.cb-dugout.cb-next-open-warning .coach-live-shell{
          padding-bottom:
            calc(128px + env(safe-area-inset-bottom))!important;
        }
        /* Both lines showing: room for the second one. */
        html body.cb-dugout.cb-now-open-warning .coach-live-shell{
          padding-bottom:
            calc(156px + env(safe-area-inset-bottom))!important;
        }
      }

      #${CARD_ID} .cb-next-body{
        padding:10px 11px 11px;
      }

      #${CARD_ID} .cb-next-field{
        width:min(100%,760px);
        min-height:0;
        margin-inline:auto;
        aspect-ratio:1.28/1;
      }

      #${CARD_ID} .cb-next-spot,
      #${CARD_ID} .cb-next-bench-player{
        touch-action:manipulation;
        cursor:grab;
      }

      #${CARD_ID} .cb-next-spot:active,
      #${CARD_ID} .cb-next-bench-player:active{
        cursor:grabbing;
      }

      #${CARD_ID} .cb-next-spot.cb-drag-over .cb-qd-name{
        outline:4px solid rgba(49,93,152,.24);
        border-color:#315d98!important;
        background:#eef4ff!important;
      }

      #${CARD_ID} .cb-next-bench.cb-drag-over{
        outline:4px solid rgba(23,107,56,.18);
        border-color:#5b9b70;
        background:#f0f8f2;
      }


      #${CARD_ID} .cb-next-open .cb-qd-name{
        border:2px dashed #b5473d!important;
        background:#fff3f1!important;
        color:#9b2c24!important;
        font-weight:950!important;
      }

      #${CARD_ID} .cb-next-selected .cb-qd-name{
        outline:4px solid rgba(23,59,120,.32);
        border-color:#173b78!important;
        background:#173b78!important;
        color:#fff!important;
      }

      #${CARD_ID} .cb-next-destination .cb-qd-name{
        border:2px solid #4d75b3!important;
        box-shadow:
          0 0 0 3px rgba(77,117,179,.15),
          0 2px 5px rgba(16,24,40,.12)!important;
      }

      #${CARD_ID} .cb-next-bench{
        margin-top:8px;
        padding:8px;
        border:1px solid #e2e6eb;
        border-radius:10px;
        background:#f8fafc;
      }

      #${CARD_ID} .cb-next-bench-head{
        display:flex;
        justify-content:space-between;
        gap:8px;
        align-items:baseline;
        margin-bottom:6px;
      }

      #${CARD_ID} .cb-next-bench-head strong{
        color:#253047;
        font-size:.72rem;
      }

      #${CARD_ID} .cb-next-bench-head span{
        color:var(--cb-muted);
        font-size:var(--cb-text-xs);
      }

      #${CARD_ID} .cb-next-bench-chips{
        display:flex;
        flex-wrap:wrap;
        gap:6px;
      }

      #${CARD_ID} .cb-next-bench-player{
        min-height:38px;
        border:1px solid #cfd5dd;
        border-radius:9px;
        background:#fff;
        color:#253047;
        padding:6px 8px;
        font-size:.68rem;
        font-weight:800;
        touch-action:manipulation;
      }

      #${CARD_ID} .cb-next-bench-player.selected{
        border-color:#173b78;
        background:#173b78;
        color:#fff;
      }

      /* Border colour and a shadow only: the Bench keeps its size. */
      #${CARD_ID} .cb-next-bench.destination-active{
        border-color:#4d75b3;
        background:#f3f7fd;
        box-shadow:0 0 0 2px rgba(77,117,179,.35);
        cursor:pointer;
      }

      /* Sized like the hint it replaces, so the Bench keeps its height. */
      #${CARD_ID} .cb-next-bench-head .cb-next-bench-cta{
        margin:0;
        padding:0;
        border:0;
        background:none;
        color:#315d98;
        font:inherit;
        font-size:var(--cb-text-xs);
        font-weight:850;
        line-height:inherit;
        white-space:nowrap;
        text-decoration:underline;
        text-underline-offset:2px;
        cursor:pointer;
        touch-action:manipulation;
      }

      #${CARD_ID} .cb-next-tools{
        display:flex;
        flex-wrap:wrap;
        gap:6px;
        align-items:center;
        margin-top:8px;
      }

      #${CARD_ID} .cb-next-undo-note{
        border:1px solid #b8ddc4;
        border-radius:9px;
        background:#edf8f1;
        color:#176b38;
        padding:6px 9px;
        font-size:var(--cb-text-xs);
        font-weight:750;
      }

      #${CARD_ID} .cb-next-plan-note{
        flex:1 1 100%;
        color:#5b4300;
        background:#fff8e6;
        border:1px solid #f1d38a;
        border-radius:9px;
        padding:6px 9px;
        font-size:var(--cb-text-xs);
        font-weight:750;
        line-height:1.3;
      }

      /* Plain secondary actions here read as actions, not disabled. */
      #${CARD_ID} .cb-next-tools .btn-outline-secondary{
        color:#344054;
        border-color:#8a94a6;
        background:#fff;
      }

      #${CARD_ID} .cb-next-tools .btn{
        min-height:44px;
        border-radius:9px;
        font-size:var(--cb-text-xs);
        font-weight:820;
      }

      #${CARD_ID} .cb-next-warnings{
        margin-top:8px;
        display:grid;
        gap:5px;
      }

      #${CARD_ID} .cb-next-warning{
        border-radius:8px;
        padding:7px 8px;
        font-size:.68rem;
        font-weight:780;
      }

      #${CARD_ID} .cb-next-warning{
        border:1px solid #e6ca82;
        background:#fff8e6;
        color:#775a10;
      }

      #${CARD_ID} .cb-next-warning.danger{
        border-color:#efb5ae;
        background:#fff1ef;
        color:#912d28;
      }

      #${CARD_ID} .cb-next-error{
        margin-top:8px;
        border:1px solid #efb5ae;
        border-radius:8px;
        background:#fff1ef;
        color:#912d28;
        padding:7px 8px;
        font-size:.68rem;
        font-weight:750;
      }

      #live-up-next-v2,
      #next-inning-adjust-modal{
        display:none!important;
      }

      @media(max-width:575.98px){
        #${CARD_ID} .cb-next-head{
          padding:8px 9px 7px;
        }

        #${CARD_ID} .cb-next-body{
          padding:7px;
        }

        #${CARD_ID} .cb-next-field{
          width:100%;
          min-height:0;
          aspect-ratio:1.36/1;
        }

        #${CARD_ID} .cb-qd-spot{
          width:clamp(54px,17vw,66px)!important;
          min-height:30px!important;
        }

        #${CARD_ID} .cb-qd-name{
          font-size:var(--cb-marker-name)!important;
          padding:2px!important;
        }

        #${CARD_ID} .cb-next-bench-player{
          min-height:36px;
          padding:5px 7px;
          font-size:.64rem;
        }

        /*
         * Live game actions are a phone dock.
         *
         * Keep this owner here with the NOW/NEXT surface so the canonical
         * End Inning button cannot disappear at larger phone widths such
         * as the 440px iPhone 16 Pro Max viewport.
         */
        html body.cb-dugout .coach-live-shell{
          padding-bottom:
            calc(96px + env(safe-area-inset-bottom))!important;
        }

        html body.cb-dugout #coach-action-slot{
          position:fixed!important;
          left:8px!important;
          right:8px!important;
          bottom:0!important;
          z-index:1080!important;
          display:grid!important;
          grid-template-columns:
            repeat(2,minmax(0,1fr))!important;
          gap:8px!important;
          margin:0!important;
          padding:
            8px 8px
            calc(8px + env(safe-area-inset-bottom))!important;
          border-top:1px solid #d9dee5;
          background:rgba(245,246,248,.98);
          box-shadow:0 -6px 18px rgba(16,24,40,.10);
        }

        html body.cb-dugout
        #coach-action-slot.cb-single-live-action{
          grid-template-columns:1fr!important;
        }

        html body.cb-dugout
        #coach-action-slot #liveEndInningBtn{
          display:flex!important;
        }
      }

      @media(min-width:576px) and (max-width:899.98px){
        #${CARD_ID} .cb-next-field{
          width:min(100%,680px);
        }
      }

      @media(min-width:1200px){
        #${CARD_ID} .cb-next-field{
          width:min(100%,720px);
        }
      }

      /*
       * FINAL portrait-tablet override.
       *
       * Keep this AFTER every other field-width rule so an older
       * 744/768/820px iPad cannot fall back to the generic tablet
       * width after portrait sizing has been calculated.
       *
       * Use both viewport width and viewport height. This makes the
       * live board adapt to the usable screen rather than an iPad model.
       *
       * The landscape owner blocks below are the one thing that follows it.
       * A viewport cannot be portrait and landscape at once, so they never
       * compete; they are last so that they outrank the generic width rules
       * above them, min-width:1200px included.
       */
      @media(
        orientation:portrait
      ) and (
        min-width:600px
      ){
        #${CARD_ID} .cb-next-field{
          width:clamp(
            500px,
            min(82vw, calc(36vh * 1.28)),
            600px
          );
          margin-inline:auto;
        }

        #${CARD_ID} .cb-next-body{
          padding-top:8px;
          padding-bottom:9px;
        }

        #${CARD_ID} .cb-next-bench{
          margin-top:7px;
        }
      }

      /*
       * LANDSCAPE OWNER -- NEXT INNING FIELD.
       *
       * Landscape is a vertical-budget problem, not a width problem: at
       * 1024x768 a width-derived field pushed End Inning and Change Pitcher
       * below the fold. Size from the viewport height instead.
       *
       * Next Inning gets a smaller cap than On the Field on purpose. It
       * carries its own heading and save chip above the
       * field, so the same field height does not leave the same room.
       *
       * The bench, tools and warnings move beside the field here, mirroring
       * what Quick Field already does in landscape. That is what buys the
       * field its height back rather than shrinking it further -- stacking
       * them under the field cost roughly 135px that landscape does not have.
       */
      @media(
        min-width:700px
      ) and (
        min-height:500px
      ) and (
        orientation:landscape
      ){
        #${CARD_ID} .cb-next-body{
          display:grid;
          grid-template-columns:minmax(0,1.5fr) minmax(220px,.8fr);
          grid-template-areas:
            "field bench"
            "field tools"
            "field warnings"
            "error error";
          gap:8px 12px;
          align-items:start;
          padding:9px 11px 11px;
        }

        #${CARD_ID} .cb-next-field{
          grid-area:field;
          width:min(
            100%,
            690px,
            calc(46dvh * 1.28)
          );
          min-height:0;
          aspect-ratio:1.28/1;
          margin:0 auto;
        }

        #${CARD_ID} .cb-next-bench{
          grid-area:bench;
          margin-top:0;
          padding:7px;
        }

        #${CARD_ID} .cb-next-tools{
          grid-area:tools;
          margin-top:0;
        }

        #${CARD_ID} .cb-next-warnings{
          grid-area:warnings;
          margin-top:0;
        }

        #${CARD_ID} .cb-next-error{
          grid-area:error;
          margin-top:0;
        }

        #${CARD_ID} .cb-next-head{
          padding-top:8px;
          padding-bottom:7px;
        }

        /*
         * Markers are a share of the field, so nine of them sit at the same
         * density whatever the field measures. The floor keeps them tappable
         * at the smallest landscape field the cap above can produce.
         */
        #${CARD_ID} .cb-next-field .cb-qd-spot{
          width:clamp(56px,17%,112px);
          min-height:44px;
        }
      }

      /*
       * LANDSCAPE OWNER -- ON THE FIELD (Quick Field).
       *
       * This is the same media range live_game_sync_status.js uses for its
       * landscape two-column layout, which keeps the grid and the field
       * sizing switching on together. Sizing used to be set in three places
       * at once -- sync_status (width:min(100%,690px)), field_realism
       * (width:min(100%,665px)) and the .cb-qd-field base min-height:330px --
       * all of them width-only. Those now defer to this block; see the notes
       * left in each file.
       *
       * html + body.cb-dugout + #cbQuickDefense is what it takes to outrank
       * the rules this replaces, which are themselves !important.
       */
      @media(
        min-width:760px
      ) and (
        min-height:600px
      ) and (
        orientation:landscape
      ){
        html body.cb-dugout #cbQuickDefense .cb-qd-field{
          width:min(
            100%,
            690px,
            calc(50dvh * 1.28)
          )!important;
          min-height:0!important;
          aspect-ratio:1.28/1!important;
          margin:0 auto!important;
        }

        html body.cb-dugout #cbQuickDefense .cb-qd-spot{
          width:clamp(56px,17%,112px)!important;
          min-height:44px!important;
        }

        html body.cb-dugout #cbQuickDefense .cb-qd-head{
          padding:8px 12px 7px!important;
        }

        html body.cb-dugout #cbQuickDefense .cb-qd-help{
          font-size:var(--cb-text-xs)!important;
        }
      }
    `;

    document.head.appendChild(style);
  }

  async function api(method = 'GET', body = null) {
    let response;

    try {
      response = await fetch(
        `/api/live-game/${gameId}/next-inning-prep`,
        {
          method,
          headers: body
            ? {'Content-Type': 'application/json'}
            : undefined,
          body: body
            ? JSON.stringify(body)
            : undefined,
          cache: 'no-store',
        }
      );
    } catch (_) {
      // The browser's own text ("Failed to fetch") means nothing to a
      // coach. `retry` marks a failure worth trying again later.
      const error = new Error('No connection.');
      error.retry = true;
      throw error;
    }

    const data = await response.json().catch(() => ({}));

    if (!response.ok || data.status === 'error') {
      const error = new Error(
        data.message ||
        `Unable to save the Next Inning defense (${response.status}).`
      );
      error.code = data.code || '';
      error.retry = response.status >= 500;
      throw error;
    }

    return data;
  }

  function ensureSwitcher() {
    const shell = document.querySelector(
      '#live-game-overlay .coach-live-shell'
    );

    const now = $('cbQuickDefense');

    if (!shell || !now) {
      return null;
    }

    let switcher = $(SWITCH_ID);

    if (!switcher) {
      switcher = document.createElement('div');
      switcher.id = SWITCH_ID;
      switcher.setAttribute(
        'role',
        'group'
      );
      switcher.setAttribute(
        'aria-label',
        'Plan the next inning'
      );

      switcher.innerHTML = `
        <button
          type="button"
          class="btn btn-outline-secondary"
          data-now-next="next"
        ><i class="bi bi-calendar2-plus me-1"></i> Plan next inning</button>`;

      now.insertAdjacentElement(
        'beforebegin',
        switcher
      );

      switcher.addEventListener(
        'click',
        event => {
          const button = event.target.closest(
            '[data-now-next]'
          );

          if (!button) return;

          const requested = button.dataset.nowNext;

          activeView = requested === 'next' ? 'next' : 'now';
          applyView();
        }
      );
    }

    applyView();

    return switcher;
  }

  function ensureSurface() {
    const switcher = ensureSwitcher();
    const now = $('cbQuickDefense');

    if (!switcher || !now) {
      return null;
    }

    let card = $(CARD_ID);

    if (!card) {
      card = document.createElement('div');
      card.id = CARD_ID;

      now.insertAdjacentElement(
        'afterend',
        card
      );
    }

    if (!$(PLAN_CARD_ID)) {
      const planCard = document.createElement('div');
      planCard.id = PLAN_CARD_ID;
      card.insertAdjacentElement(
        'afterend',
        planCard
      );
    }

    $('live-up-next-v2')?.remove();
    $('next-inning-adjust-modal')?.remove();

    applyView();

    return card;
  }

  function upcomingInning() {
    return String(
      latest?.next_inning || ''
    ).trim();
  }

  // The inning the page shows everywhere -- header, tabs, End Inning -- is
  // the shared live state's (live_game_feedback_pass.js), which takes every
  // newer read the page makes. This board's own read can be a moment behind
  // or ahead of it; until they agree the labels follow the shared state.
  function sharedInning() {
    return String(window.CBLiveState?.current?.()?.current_inning || '').trim();
  }

  function readDisagrees(data = latest) {
    const shared = sharedInning();
    return Boolean(shared && data && String(data.current_inning || '') !== shared);
  }

  // This board read a different inning than the page shows: read the game
  // again (published if newer), at most every 2 s.
  let lastSharedAsk = 0;
  function askForSharedState() {
    if (Date.now() - lastSharedAsk < 2000) return;
    lastSharedAsk = Date.now();
    window.CBLiveState?.refresh?.('next-inning-read')?.catch?.(() => {});
  }

  function inningOrdinal(value) {
    const number = Number.parseInt(
      String(value || ''),
      10
    );

    if (!Number.isFinite(number)) {
      return String(value || '').trim();
    }

    const mod100 = number % 100;

    if (mod100 >= 11 && mod100 <= 13) {
      return `${number}th`;
    }

    switch (number % 10) {
      case 1:
        return `${number}st`;
      case 2:
        return `${number}nd`;
      case 3:
        return `${number}rd`;
      default:
        return `${number}th`;
    }
  }

  // Beside End Inning on every tab: which defense takes the field next, from
  // this board's own state (saved source, save state, a skipped plan).
  function endInningSource(inningLabel, currentLabel) {
    if (conflictPending || saveMode === 'conflict') return `Not saved — check the ${inningLabel}`;
    if (saveMode === 'error') return `${inningLabel} defense not saved`;
    if (saveMode === 'waiting') return `${inningLabel} defense not synced yet`;
    if (saveMode === 'saving' || dirty || activeSavePromise) return `Saving the ${inningLabel} defense…`;

    const source = boardSource();
    if (source === 'planned') {
      const carry = pitcherCarried();
      return carry
        ? `Plan for the ${inningLabel} · ${carry.pitcher} keeps pitching`
        : `Plan for the ${inningLabel}`;
    }
    if (source === 'current') {
      return skippedPlanByDefault()
        ? `Same as the ${currentLabel} · plan not used`
        : `Same as the ${currentLabel}`;
    }
    const changes = ownSave()
      ? `Your changes for the ${inningLabel}`
      : `Changes for the ${inningLabel}`;
    const carry = pitcherCarried();
    return carry ? `${changes} · ${carry.pitcher} keeps pitching` : changes;
  }

  function ownSave() {
    const revision = latest?.confirmed?.revision;
    return ownRevision !== null && revision !== undefined && revision === ownRevision;
  }

  // A separate plan for the next inning that the automatic defense is not
  // using, and that no coach has decided about yet.
  function skippedPlanByDefault() {
    const seed = plannedSeed();
    return Boolean(
      seed &&
      !localSource &&
      latest?.confirmed?.updated_by === 'Auto' &&
      !sameAlignment(seed, snapshot())
    );
  }

  function syncUpcomingInningLabels() {
    const behind = readDisagrees();
    const current = sharedInning() || String(latest?.current_inning || '');
    const inning = behind
      ? String(Number.parseInt(current, 10) + 1)
      : upcomingInning();
    const inningLabel = inningOrdinal(inning);
    const currentLabel = inningOrdinal(current);

    const nextTab = $(SWITCH_ID)
      ?.querySelector(
        '[data-now-next="next"]'
      );

    const tabText = inningLabel
      ? `Plan ${inningLabel} inning`
      : 'Plan next inning';

    if (nextTab && nextTab.textContent !== tabText) {
      nextTab.textContent = tabText;
    }

    if (!inningLabel) return;

    const endInning =
      $('liveEndInningBtn');

    if (!endInning) return;

    // This is the only code that writes End Inning's label. The attribute
    // tells the other live-screen scripts, which place and style the
    // button, to leave its text alone -- they used to reset it to
    // "End Inning" on their own refreshes, so the label flashed.
    if (endInning.dataset.cbLabelOwner !== 'next-inning') {
      endInning.dataset.cbLabelOwner = 'next-inning';
    }

    let title =
      endInning.querySelector(
        '.coach-action-title'
      );

    let note =
      endInning.querySelector(
        '.coach-action-note'
      );

    if (!title || !note) {
      endInning.innerHTML =
        '<span class="coach-action-title"></span>' +
        '<span class="coach-action-note"></span>';
      title = endInning.querySelector('.coach-action-title');
      note = endInning.querySelector('.coach-action-note');
    }

    const buttonTitle = currentLabel
      ? `End ${currentLabel} → Start ${inningLabel}`
      : `Start ${inningLabel}`;

    // While this board's read catches up, nothing from it is shown here.
    const noteText = behind
      ? `Checking the ${inningLabel} defense…`
      : endInningSource(inningLabel, currentLabel);

    // The inning this button ends, as the coach sees it: End Inning
    // refuses if the server's game has moved to another (contract.js).
    if (endInning.dataset.cbInning !== current) {
      endInning.dataset.cbInning = current;
    }

    if (title.textContent !== buttonTitle) {
      title.textContent = buttonTitle;
    }

    if (note.textContent !== noteText) {
      note.textContent = noteText;
    }

    const ariaLabel = currentLabel
      ? `End ${currentLabel} inning and start ${inningLabel}`
      : `Start ${inningLabel} inning`;

    if (endInning.getAttribute('aria-label') !== ariaLabel) {
      endInning.setAttribute('aria-label', ariaLabel);
    }
  }

  function syncLiveActions() {
    const changePitcher = $('liveChangePitcherBtn');
    const endInning = $('liveEndInningBtn');
    const undo = $('liveUndoBtn');
    const actionSlot = $('coach-action-slot');
    const planning = activeView !== 'now';

    syncUpcomingInningLabels();

    if (actionSlot) {
      actionSlot.removeAttribute('hidden');
      if (planning) {
        actionSlot.style.setProperty('display', 'none', 'important');
      } else {
        actionSlot.style.removeProperty('display');
      }
      actionSlot.classList.remove('cb-single-live-action');
    }

    if (endInning) {
      endInning.removeAttribute('hidden');
      endInning.classList.remove('d-none');
    }

    if (changePitcher) {
      if (planning) {
        changePitcher.style.setProperty('display', 'none', 'important');
      } else {
        changePitcher.style.removeProperty('display');
      }
    }

    // The canonical Undo always means the last committed LIVE action.
    // Next-inning planning gets its own Undo inside the sheet.
    if (undo) {
      if (undo.dataset.cbUndoScope !== 'live') {
        undo.dataset.cbUndoScope = 'live';
        document.dispatchEvent(
          new CustomEvent('coachboard:undo-scope', {detail: {scope: 'live'}})
        );
      }
      undo.disabled = false;
      if (planning) {
        undo.style.setProperty('display', 'none', 'important');
      } else {
        undo.style.removeProperty('display');
      }
    }

    syncOpenDefenseWarning(endInning);
  }

  // End Inning starts the next inning with the Next Inning defense, so an
  // open spot there is worth seeing before tapping it -- including on a
  // phone, where the card's own warning sits below the fixed action dock.
  // The field right now and the next inning are separate questions: a red
  // line for a spot empty now (this inning), an amber one for the next
  // inning's plan. Each opens the picker for its first open spot.
  function currentOpenPositions() {
    const field = latest?.current_alignment || {};
    return positions().filter(pos => !field[pos]);
  }

  function warningLine(id, endInning, text, onTap) {
    let line = $(id);
    if (!text) {
      line?.remove();
      return false;
    }
    if (!line) {
      line = document.createElement('div');
      line.id = id;
      line.setAttribute('role', 'status');
      line.tabIndex = 0;
      line.addEventListener('click', () => line._cbTap?.());
      line.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        line._cbTap?.();
      });
    }
    line._cbTap = onTap;
    if (line.nextElementSibling !== endInning) {
      endInning.parentNode.insertBefore(line, endInning);
    }
    if (line.textContent !== text) line.textContent = text;
    return true;
  }

  function syncOpenDefenseWarning(endInning) {
    const open = latest ? openPositions() : [];

    // An empty spot on the live field is visible state, not another workflow.
    $('cbNowOpenWarning')?.remove();

    if (!endInning) {
      $('cbNextOpenWarning')?.remove();
      document.body.classList.remove(
        'cb-next-open-warning',
        'cb-now-open-warning'
      );
      return;
    }

    const showsNext = warningLine(
      'cbNextOpenWarning',
      endInning,
      open.length
        ? `⚠ Next inning: ${open.join(', ')} ${open.length === 1 ? 'is' : 'are'} open`
        : '',
      () => {
        activeView = 'next';
        applyView();
      }
    );

    document.body.classList.toggle(
      'cb-next-open-warning',
      showsNext
    );
    document.body.classList.remove('cb-now-open-warning');
  }

  function applyView() {
    const switcher = $(SWITCH_ID);
    const now = $('cbQuickDefense');
    const next = $(CARD_ID);
    const plan = $(PLAN_CARD_ID);
    const planning = activeView === 'next';

    switcher
      ?.querySelectorAll('[data-now-next]')
      .forEach(button => {
        button.setAttribute(
          'aria-pressed',
          planning ? 'true' : 'false'
        );
      });

    // The live field remains the context. Planning opens over it.
    if (now) {
      now.hidden = false;
    }

    if (next) {
      next.hidden = !planning;
    }

    if (plan) {
      plan.hidden = true;
    }

    document.body.classList.toggle(
      'cb-next-sheet-open',
      planning
    );

    syncLiveActions();
  }

  /*
   * Pregame Plan: the plan the coach set before first pitch, next to what
   * the game actually has for that inning. Reference only -- nothing here
   * changes the game.
   *
   * Where the game's side comes from (all from this board's own data):
   *   - the inning being played: the field right now;
   *   - the next inning: this board's Next Inning defense -- saved edits,
   *     the coach's explicit choice, edits still waiting to save -- which is
   *     what End Inning sends;
   *   - an inning already played: how it ended (the plan plus the game's
   *     changes, the same record as the Game Report's "Defense by inning");
   *   - a played inning with nothing recorded: "No record", never "Empty";
   *   - later innings: nothing yet.
   */
  function planFor(key) {
    const alignment = latest?.pregame_rotation?.[key];

    return alignment && Object.values(alignment).some(Boolean)
      ? alignment
      : null;
  }

  // Every saved plan key with a defense, in order: whole innings ("3") and
  // planned changes during an inning ("3.5", shown as "3+").
  function planKeys() {
    return Object.keys(latest?.pregame_rotation || {})
      .filter(key => Number.isFinite(Number.parseFloat(key)) && planFor(key))
      .sort((a, b) => Number.parseFloat(a) - Number.parseFloat(b));
  }

  const isMidInning = key => String(key).includes('.');
  const wholeInning = key => String(Math.floor(Number.parseFloat(key)));

  // One button per scheduled inning: the game's inning count, widened to
  // the inning being played and to any planned inning beyond it.
  function scheduledInnings() {
    const playing = Number.parseInt(latest?.current_inning || '', 10) || 1;
    const planned = planKeys().map(key => Math.floor(Number.parseFloat(key)));

    return Math.max(Number(latest?.regulation_innings) || 0, playing, ...planned, 1);
  }

  // The scheduled innings, each followed by any change planned during it.
  function planNavKeys() {
    const total = scheduledInnings();
    const mid = planKeys().filter(isMidInning);
    const keys = [];

    for (let inning = 1; inning <= total; inning += 1) {
      keys.push(String(inning));
      mid.filter(key => wholeInning(key) === String(inning)).forEach(key => keys.push(key));
    }
    return keys;
  }

  function presentNames() {
    return new Set((latest?.roster || []).map(player => player.name));
  }

  // Who was here for an inning: for an inning already played, what the game
  // recorded for that inning (null when it has nothing); otherwise today.
  function hereFor(key) {
    const inning = Number.parseInt(key, 10);
    const playing = Number.parseInt(latest?.current_inning || '', 10);

    if (Number.isFinite(inning) && Number.isFinite(playing) && inning < playing) {
      const available = latest?.played_innings?.[String(inning)]?.available;
      return Array.isArray(available) ? new Set(available) : null;
    }
    return presentNames();
  }

  function gameDefenseFor(key) {
    const current = String(latest?.current_inning || '');
    const ordinal = inningOrdinal(key);
    const here = hereFor(key);

    // A change planned during an inning: the game keeps no record of its own
    // for it, so the plan is shown on its own.
    if (isMidInning(key)) {
      return {kind: 'midplan', label: '', alignment: null, here};
    }

    if (key === current) {
      return {kind: 'now', label: 'On the field now', alignment: latest?.current_alignment || {}, here};
    }

    if (key === String(latest?.next_inning || '')) {
      return {kind: 'next', label: 'Next inning', alignment: snapshot(), here};
    }

    const inning = Number.parseInt(key, 10);
    const playing = Number.parseInt(current, 10);

    if (Number.isFinite(inning) && Number.isFinite(playing) && inning < playing) {
      // Only what the game recorded (End Inning, or a later correction) --
      // never the plan, however untouched (live_game_ui._played_innings).
      const record = latest?.played_innings?.[key]?.alignment;

      return record && Object.values(record).some(Boolean)
        ? {kind: 'played', label: `How the ${ordinal} ended`, alignment: record, here}
        : {kind: 'norec', label: `How the ${ordinal} ended`, alignment: null, here};
    }

    return {kind: 'later', label: '', alignment: null, here};
  }

  function planRows(plan, game) {
    return positions().map(pos => {
      const planned = plan?.[pos] || '';
      const actual = game.alignment ? game.alignment[pos] || '' : '';

      return {
        pos,
        planned,
        actual,
        // The plan named someone and a different player is there.
        changed: Boolean(plan && game.alignment && planned && actual && planned !== actual),
        // Known to be empty -- never for a missing record.
        empty: Boolean(game.alignment) && !actual,
        // Anything not matching the plan, empty positions included.
        differs: Boolean(plan && game.alignment) && planned !== actual,
      };
    });
  }

  function planDiffers(key) {
    const plan = planFor(key);
    const game = gameDefenseFor(key);

    return Boolean(plan && game.alignment) &&
      planRows(plan, game).some(row => row.differs);
  }

  function shortName(name) {
    const parts = String(name || '').trim().split(/\s+/);

    return parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : parts[0] || '';
  }

  // "Not here": not available in that inning (unknown availability: no
  // label rather than a guess).
  function planName(name, here) {
    const number = String(playerByName(name)?.number ?? '').trim();

    return `<span class="cb-plan-nm">${esc(name)}${
      number ? `<small>#${esc(number)}</small>` : ''
    }${here && !here.has(name) ? '<small>Not here</small>' : ''}</span>`;
  }

  function gameCell(row, game) {
    if (game.kind === 'norec') return '<span class="cb-plan-norec">No record</span>';
    if (game.kind === 'later' || game.kind === 'midplan') return '<span class="cb-plan-norec">Not set yet</span>';
    if (row.empty) return '<span class="cb-plan-emp">Empty</span>';

    return `${planName(row.actual, game.here)}${row.changed ? '<span class="cb-plan-flag">Changed</span>' : ''}`;
  }

  function rowState(row, game) {
    if (game.kind === 'norec') return 'norec';
    if (game.kind === 'later' || game.kind === 'midplan') return 'later';
    return row.empty ? 'empty' : 'name';
  }

  function rowData(row, game) {
    return `data-plan-live-differs="${row.differs ? 'true' : 'false'}" data-plan-changed="${row.changed ? 'true' : 'false'}" data-plan-planned="${esc(row.planned)}" data-plan-actual="${esc(row.actual)}" data-plan-state="${rowState(row, game)}"`;
  }

  function plannedCell(row, game) {
    return row.planned ? planName(row.planned, game.here) : '<span class="cb-plan-na">Not in plan</span>';
  }

  // Who sits: the players here for that inning (game.here) less the
  // defense. An inning already played uses that inning's recorded
  // availability, never today's; with none recorded, no list is made up.
  function benchNames(names, here) {
    if (!here) return '<span class="cb-plan-na">Bench not recorded</span>';

    const used = new Set(names.filter(Boolean));
    const bench = [...here]
      .filter(name => !used.has(name))
      .sort((a, b) => a.localeCompare(b));

    return bench.length ? bench.map(name => esc(playerLabel(name))).join(', ') : 'Nobody';
  }

  // The plan stores no bench of its own: list who it leaves out only when it
  // places every position.
  function planBench(plan, here) {
    return positions().every(pos => plan[pos])
      ? benchNames(positions().map(pos => plan[pos]), here)
      : '<span class="cb-plan-na">Bench not specified</span>';
  }

  // Who sits, in one line ("Bench · 3 planned · 3 next inning"), with the
  // names one tap away. Honest when there is nothing to list: "Bench not
  // specified" (a partial plan) or "Bench not recorded" (no availability
  // recorded for that inning).
  function benchCount(names, here) {
    if (!here) return null;
    const used = new Set(names.filter(Boolean));
    return [...here].filter(name => !used.has(name)).length;
  }

  function benchLine(plan, game) {
    const parts = [];
    let listable = false;
    let unspecified = false;
    const short = game.kind === 'now'
      ? 'now'
      : game.kind === 'next'
        ? 'next inning'
        : `in the ${inningOrdinal(planChoice.inning)}`;

    if (plan) {
      if (!positions().every(pos => plan[pos])) {
        unspecified = true;
        parts.push('not specified in the plan');
      } else {
        const count = benchCount(positions().map(pos => plan[pos]), game.here);
        if (count === null) {
          parts.push('not recorded');
        } else {
          parts.push(`${count} planned`);
          listable = true;
        }
      }
    }

    if (game.alignment) {
      const count = benchCount(positions().map(pos => game.alignment[pos]), game.here);
      if (count === null) {
        parts.push('not recorded');
      } else {
        parts.push(`${count} ${short}`);
        listable = true;
      }
    }

    if (!parts.length) return '';

    const text = listable
      ? `Bench · ${[...new Set(parts)].join(' · ')}`
      : unspecified
        ? 'Bench not specified'
        : 'Bench not recorded';

    return `<div class="cb-plan-benchline" data-plan-bench-summary>
      <span>${esc(text)}</span>
      ${listable ? `<button type="button" class="cb-plan-linkbtn" data-plan-bench-toggle aria-expanded="${planBenchOpen ? 'true' : 'false'}">${planBenchOpen ? 'Hide bench' : 'Show bench'}</button>` : ''}
    </div>`;
  }

  function planList(key, plan, game, rows, onlyChanges) {
    const ordinal = inningOrdinal(key);

    if (!plan && !game.alignment) {
      return `<div class="cb-plan-note">${
        game.kind === 'norec'
          ? `No pregame plan and no record for the ${esc(ordinal)}.`
          : `No pregame plan and no defense set yet for the ${esc(ordinal)}.`
      }</div>`;
    }

    // Only one side to show: the plan alone, or the game alone.
    if (!plan || !game.alignment) {
      const heading = plan ? 'Pregame plan' : game.label;

      return `<div class="cb-plan-list single">
        <div class="cb-plan-row cb-plan-colhead"><span>Pos</span><span class="${plan ? 'cb-plan-planned' : 'cb-plan-game'}">${esc(heading)}</span></div>
        ${rows.map(row => `
          <div class="cb-plan-row" data-plan-row="${esc(row.pos)}" ${rowData(row, game)}>
            <span class="cb-plan-pos">${esc(row.pos)}</span>
            ${plan
              ? `<span class="cb-plan-planned">${plannedCell(row, game)}</span>`
              : `<span class="cb-plan-game">${gameCell(row, game)}</span>`}
          </div>`).join('')}
        ${planBenchOpen ? `<div class="cb-plan-row cb-plan-bench" data-plan-row="bench">
          <span class="cb-plan-pos">Bench</span>
          ${plan
            ? `<span class="cb-plan-planned">${planBench(plan, game.here)}</span>`
            : `<span class="cb-plan-game">${benchNames(positions().map(pos => game.alignment[pos]), game.here)}</span>`}
        </div>` : ''}
      </div>
      ${benchLine(plan, game)}`;
    }

    const shown = onlyChanges ? rows.filter(row => row.differs || row.empty) : rows;

    return `<div class="cb-plan-list">
      <div class="cb-plan-row cb-plan-colhead"><span>Pos</span><span class="cb-plan-planned">Pregame plan</span><span class="cb-plan-game">${esc(game.label)}</span></div>
      ${shown.map(row => `
        <div class="cb-plan-row" data-plan-row="${esc(row.pos)}" ${rowData(row, game)}>
          <span class="cb-plan-pos">${esc(row.pos)}</span>
          <span class="cb-plan-planned">${plannedCell(row, game)}</span>
          <span class="cb-plan-game">${gameCell(row, game)}</span>
        </div>`).join('')}
      ${shown.length ? '' : '<div class="cb-plan-row"><span></span><span class="cb-plan-note">No changes or empty positions.</span></div>'}
      ${planBenchOpen ? `<div class="cb-plan-row cb-plan-bench" data-plan-row="bench">
        <span class="cb-plan-pos">Bench</span>
        <span class="cb-plan-planned">${planBench(plan, game.here)}</span>
        <span class="cb-plan-game">${benchNames(positions().map(pos => game.alignment[pos]), game.here)}</span>
      </div>` : ''}
    </div>
    ${benchLine(plan, game)}`;
  }

  function planFieldPlaces() {
    return Number(latest?.outfielder_count) === 4
      ? {LF: [17, 27], LCF: [34, 10], RCF: [66, 10], RF: [83, 27], SS: [33, 44], '2B': [67, 44], '3B': [17, 66], P: [50, 63], '1B': [83, 66], C: [50, 87]}
      : {LF: [18, 25], CF: [50, 9], RF: [82, 25], SS: [33, 44], '2B': [67, 44], '3B': [17, 66], P: [50, 63], '1B': [83, 66], C: [50, 87]};
  }

  function planField(key, plan, game, rows) {
    const ordinal = inningOrdinal(key);

    if (!plan && !game.alignment) {
      return `<div class="cb-plan-note">${
        game.kind === 'norec' ? `No record of how the ${esc(ordinal)} ended.` : 'Nothing to show on the field yet.'
      }</div>`;
    }

    const places = planFieldPlaces();
    const spots = rows.map(row => {
      const [left, top] = places[row.pos] || [50, 50];
      const planned = plan
        ? `<span class="cb-plan-spot-plan">${row.planned ? esc(shortName(row.planned)) : '<span class="cb-plan-na">Not in plan</span>'}</span>`
        : '';
      const actual = game.kind === 'later' || game.kind === 'midplan'
        ? ''
        : `<span class="cb-plan-spot-game">${
            game.kind === 'norec'
              ? '<span class="cb-plan-norec">No record</span>'
              : row.empty
                ? '<span class="cb-plan-emp">Empty</span>'
                : esc(shortName(row.actual))
          }</span>`;
      const label = [
        row.pos,
        plan ? `plan: ${row.planned || 'not in plan'}` : '',
        game.kind === 'later' || game.kind === 'midplan' ? '' : `${game.label.toLowerCase()}: ${
          game.kind === 'norec' ? 'no record' : row.actual || 'empty'
        }`,
        row.changed ? 'changed' : '',
      ].filter(Boolean).join(', ');

      return `<div class="cb-plan-spot" style="left:${left}%;top:${top}%" data-plan-position="${esc(row.pos)}" ${rowData(row, game)} role="img" aria-label="${esc(label)}"><span class="cb-plan-spot-pos">${esc(row.pos)}</span>${planned}${actual}</div>`;
    }).join('');

    return `<div class="cb-plan-field"><div class="cb-plan-diamond"></div>${spots}</div>
      <div class="cb-plan-legend">${plan ? '<span><b class="ref">Violet</b> = pregame plan</span>' : ''}${
        game.alignment || game.kind === 'norec' ? `<span><b>Black</b> = ${esc(game.label.toLowerCase())}</span>` : ''
      }${plan && game.alignment ? '<span>Gold border = changed</span>' : ''}</div>`;
  }

  // Who takes the field next, from this board's Next Inning defense.
  function planNextPreview() {
    const next = String(latest?.next_inning || '');
    const number = Number.parseInt(next, 10);
    const current = inningOrdinal(latest?.current_inning || '');

    if (!next || !Number.isFinite(number) || number > scheduledInnings()) {
      return `<div class="cb-plan-next" data-plan-next="none"><span class="cb-plan-note">No more scheduled innings after the ${esc(current)}.</span></div>`;
    }

    const upcoming = snapshot();
    const field = latest?.current_alignment || {};
    const changes = positions().filter(pos => (upcoming[pos] || '') !== (field[pos] || ''));
    const summary = changes.length
      ? `${planStateText()} · ${changes.length} ${changes.length === 1 ? 'change' : 'changes'} from the field now`
      : `Same defense as the ${current}`;

    return `<div class="cb-plan-next" data-plan-next="${changes.length ? 'changed' : 'same'}">
      <div class="cb-plan-next-head">
        <div><strong>Next inning · ${esc(inningOrdinal(next))}</strong><span data-plan-next-summary>${esc(summary)}</span></div>
        <button type="button" class="cb-plan-linkbtn" data-plan-edit-next>Edit next inning</button>
      </div>
      ${changes.length ? `<ul class="cb-plan-next-list">${changes.map(pos => `<li data-plan-next-pos="${esc(pos)}"><b>${esc(pos)}</b>${
        upcoming[pos] ? esc(playerLabel(upcoming[pos])) : '<span class="cb-plan-emp">Empty</span>'
      }</li>`).join('')}</ul>` : ''}
    </div>`;
  }

  // "3" for an inning, "3+" for a change planned during it.
  function planKeyLabel(key) {
    return isMidInning(key) ? `${wholeInning(key)}+` : String(key);
  }

  // Plan against the plan's own inning before (unchanged wording).
  function planChangeLine(key, plan) {
    const earlier = planKeys()
      .filter(other => Number.parseFloat(other) < Number.parseFloat(key))
      .pop();

    if (!earlier) return '<div class="cb-plan-changes">First inning of the plan</div>';

    const before = planFor(earlier);
    // A partial plan only speaks for the positions it names.
    const changed = positions().filter(pos => plan[pos] && plan[pos] !== (before[pos] || ''));

    return `<div class="cb-plan-changes${changed.length ? ' has-changes' : ''}">${
      changed.length
        ? `Plan change from Inning ${esc(planKeyLabel(earlier))}: ${esc(changed.join(', '))}`
        : `Plan: same as Inning ${esc(planKeyLabel(earlier))}`
    }</div>`;
  }

  // One short line that answers "what changed?" for the inning chosen.
  function planStatement(key, plan, game, rows) {
    const ordinal = inningOrdinal(key);
    const count = positions().length;
    const planned = plan ? positions().filter(pos => plan[pos]).length : 0;
    const changed = rows.filter(row => row.planned && row.planned !== row.actual).map(row => row.pos);
    const changes = changed.length;
    const empty = rows.filter(row => row.empty).map(row => row.pos);
    let kind;
    let text;

    if (isMidInning(key)) {
      kind = 'midplan';
      text = `Change planned during the ${ordinal}`;
    } else if (!plan) {
      kind = 'noplan';
      text = `No pregame plan for the ${ordinal}`;
    } else if (game.kind === 'norec') {
      kind = 'norec';
      text = 'No recorded defense';
    } else if (!game.alignment) {
      kind = planned < count ? 'partial' : 'later';
      text = planned < count
        ? `Partial pregame plan · ${planned} of ${count} positions`
        : 'Not played yet';
    } else if (rows.every(row => !row.differs)) {
      // Every position the same, empty ones included.
      kind = 'match';
      text = 'Defense matches the pregame plan';
    } else if (planned < count) {
      kind = 'partial';
      text = `Partial pregame plan · ${changes ? `${changes} ${changes === 1 ? 'change' : 'changes'}: ${changed.join(', ')}` : 'no changes'}`;
    } else {
      kind = 'changes';
      text = `${changes} ${changes === 1 ? 'change' : 'changes'} from the pregame plan: ${changed.join(', ')}`;
    }

    if (game.alignment && empty.length) text += ` · ${empty.join(', ')} empty`;

    return `<p class="cb-plan-summary" data-kind="${kind}" data-plan-changes="${game.alignment ? changes : ''}">${esc(text)}</p>`;
  }

  function renderPlanCard() {
    const card = $(PLAN_CARD_ID);

    if (!card) return;

    const hasAnyPlan = planKeys().length > 0;
    let html;

    if (!hasAnyPlan) {
      html = `
        <div class="cb-plan-head">
          <h3 class="cb-plan-inning-title">Pregame plan</h3>
          <div class="cb-plan-readonly">Reference only</div>
        </div>
        <div class="cb-plan-empty">No pregame defensive plan was saved for this game.</div>
        ${planNextPreview()}`;
    } else {
      const currentInning = String(latest?.current_inning || '');
      const nextInning = String(latest?.next_inning || '');
      const keys = planNavKeys();

      // Open on the next inning -- usually what a coach wants between
      // innings -- and keep the coach's choice until the live inning moves.
      if (planChoice.during !== currentInning || !keys.includes(planChoice.inning)) {
        planChoice = {
          inning: [nextInning, currentInning].find(key => keys.includes(key)) || keys[0],
          during: currentInning,
        };
      }

      const key = planChoice.inning;
      const plan = planFor(key);
      const game = gameDefenseFor(key);
      const rows = planRows(plan, game);
      const comparable = Boolean(plan && game.alignment);
      const onlyChanges = comparable && planOnlyChanges;
      const nextNumber = Number.parseInt(nextInning, 10);
      const nextScheduled = Number.isFinite(nextNumber) && nextNumber <= scheduledInnings();
      const playing = Number.parseInt(currentInning, 10);
      const when = value => {
        const inning = wholeInning(value);
        if (inning === currentInning) return 'Now';
        if (inning === nextInning) return 'Next';
        return Number.isFinite(playing) && Number(inning) < playing ? 'Played' : 'Later';
      };
      const tag = isMidInning(key)
        ? 'Planned change'
        : key === currentInning
          ? 'On now'
          : key === nextInning
            ? 'Next inning'
            : when(key);

      const buttons = keys.map(value => {
        const has = Boolean(planFor(value));
        const differs = planDiffers(value);

        const label = isMidInning(value)
          ? `Change planned during the ${inningOrdinal(value)} inning, ${when(value).toLowerCase()}`
          : `${inningOrdinal(value)} inning, ${when(value).toLowerCase()}, ${has ? 'has a pregame plan' : 'no pregame plan'}${differs ? ', game differed from the plan' : ''}`;

        return `<button type="button" class="cb-plan-inning-btn" data-plan-inning="${esc(value)}" data-plan-has="${has ? 'true' : 'false'}" data-plan-live-differs="${differs ? 'true' : 'false'}" aria-pressed="${value === key ? 'true' : 'false'}" aria-label="${esc(label)}"><b>${esc(planKeyLabel(value))}</b><small>${esc(when(value))}</small></button>`;
      }).join('');

      html = `
        <div class="cb-plan-head">
          <h3 class="cb-plan-inning-title">Pregame plan · ${isMidInning(key) ? 'during the ' : ''}${esc(inningOrdinal(key))}<span class="cb-plan-inw"> inning</span><span class="cb-plan-tag">${esc(tag)}</span></h3>
          <div class="cb-plan-readonly">Reference only</div>
        </div>
        <div class="cb-plan-innings" role="group" aria-label="Choose inning" style="grid-template-columns:repeat(${Math.min(keys.length, 9)},minmax(0,1fr))">${buttons}</div>
        <div class="cb-plan-status">
          ${planStatement(key, plan, game, rows)}
          ${key === nextInning && nextScheduled ? '<button type="button" class="cb-plan-linkbtn" data-plan-edit-next>Edit next inning</button>' : ''}
        </div>
        ${plan ? planChangeLine(key, plan) : ''}
        <div class="cb-plan-toolbar" role="group" aria-label="Show">
          <button type="button" data-plan-view-btn="list" aria-pressed="${planView === 'list' ? 'true' : 'false'}">List</button>
          <button type="button" data-plan-view-btn="field" aria-pressed="${planView === 'field' ? 'true' : 'false'}">Field</button>
        </div>
        <div class="cb-plan-views" data-plan-view="${esc(planView)}">
          <div class="cb-plan-listwrap">
            ${comparable
              // A filter for the list only; the field always shows all nine.
              ? `<div class="cb-plan-listbar"><button type="button" class="cb-plan-linkbtn" data-plan-only aria-pressed="${onlyChanges ? 'true' : 'false'}">${onlyChanges ? 'Show all positions' : 'Show changes only'}</button></div>`
              : ''}
            ${planList(key, plan, game, rows, onlyChanges)}
          </div>
          <div class="cb-plan-fieldwrap">${planField(key, plan, game, rows)}</div>
        </div>
        ${key === nextInning ? '' : planNextPreview()}`;
    }

    // The board refreshes every few seconds; only touch the DOM when the
    // plan view would actually look different.
    if (card._cbPlanMarkup !== html) {
      card.innerHTML = html;
      card._cbPlanMarkup = html;
    }

    if (!card.dataset.cbPlanBound) {
      card.dataset.cbPlanBound = '1';
      card.addEventListener('click', event => {
        const inning = event.target.closest('[data-plan-inning]');
        const view = event.target.closest('[data-plan-view-btn]');
        const only = event.target.closest('[data-plan-only]');
        const bench = event.target.closest('[data-plan-bench-toggle]');

        if (inning) {
          planChoice = {
            inning: inning.dataset.planInning,
            during: String(latest?.current_inning || ''),
          };
        } else if (view) {
          planView = view.dataset.planViewBtn === 'field' ? 'field' : 'list';
        } else if (only) {
          planOnlyChanges = !planOnlyChanges;
        } else if (bench) {
          planBenchOpen = !planBenchOpen;
        } else if (event.target.closest('[data-plan-edit-next]')) {
          // The Next Inning tab itself, exactly as tapping it; nothing
          // changes here.
          $(SWITCH_ID)?.querySelector('[data-now-next="next"]')?.click();
          return;
        } else {
          return;
        }

        renderPlanCard();
      });
    }
  }

  function cancelMove() {
    selected = null;
    selectedPosition = '';
    renderCard();
  }

  function renderCard() {
    const card = ensureSurface();

    if (!card || !latest) return;

    renderPlanCard();

    const inning = String(
      latest.next_inning || ''
    );

    const inningLabel = inningOrdinal(inning);
    const currentLabel = inningOrdinal(
      latest.current_inning || ''
    );

    card.innerHTML = `
      <div class="cb-next-head">
        <div class="cb-next-head-main">
          <div class="cb-next-title">
            ${esc(inningLabel)} Inning Defense
          </div>
          <div
            class="cb-next-sub ${selected ? 'cb-next-hint' : ''}"
            data-next-hint
            role="status"
          >${esc(selected ? moveHint() : planStateText())}</div>
          ${pitcherStatusMarkup()}
        </div>

        <div
          class="cb-next-save ${esc(saveMode)}"
          data-next-save-state
          role="status"
        >${esc(saveMessage)}</div>
      </div>

      <div class="cb-next-body">
        <div class="d-flex justify-content-between align-items-center gap-2 mb-2">
          <button
            type="button"
            class="btn btn-outline-secondary btn-sm"
            data-next-close
          ><i class="bi bi-chevron-down me-1"></i> Back to live field</button>
          <button
            type="button"
            class="btn btn-outline-secondary btn-sm"
            data-next-undo-local
            ${canUndoNext() ? '' : 'disabled'}
          ><i class="bi bi-arrow-counterclockwise me-1"></i> Undo plan edit</button>
        </div>

        ${fieldMarkup()}

        ${benchMarkup()}

        <div class="cb-next-tools">
          ${
            skippedPlanText()
              ? `
                <div class="cb-next-plan-note" data-next-plan-note role="note">
                  ${esc(skippedPlanText())}
                </div>
                <button
                  type="button"
                  class="btn btn-outline-primary"
                  data-next-use-plan
                >Use ${esc(inningLabel)}-inning plan</button>
              `
              : ''
          }
          <button
            type="button"
            class="btn btn-outline-secondary"
            data-next-use-current
          >
            ${
              currentLabel
                ? `Use ${esc(currentLabel)} Inning Defense`
                : 'Use Current Defense'
            }
          </button>

        </div>

        <div class="cb-next-warnings">
          <div
            class="cb-next-notice"
            data-next-notice
            ${noticeMessage ? '' : 'hidden'}
          >${esc(noticeMessage)}</div>
          ${conflictPending && conflictLoaded
            ? '<button type="button" class="btn btn-outline-primary btn-sm cb-next-conflict-ack" data-next-conflict-ack>Use this defense</button>'
            : ''}
          ${conflictPending && !conflictLoaded
            ? '<button type="button" class="btn btn-outline-primary btn-sm cb-next-conflict-ack" data-next-conflict-retry>Try again</button>'
            : ''}
          ${
            undoNote
              ? `<div class="cb-next-undo-note" data-next-undo-note role="status">${esc(undoNote)}</div>`
              : ''
          }
          ${nextWarningsMarkup()}
        </div>

        ${
          errorMessage
            ? `
              <div class="cb-next-error">
                ${esc(errorMessage)}
              </div>
            `
            : ''
        }
      </div>`;

    card
      .querySelector('[data-next-close]')
      ?.addEventListener('click', () => {
        activeView = 'now';
        applyView();
      });

    card
      .querySelector('[data-next-undo-local]')
      ?.addEventListener('click', () => {
        undoNext();
      });

    card
      .querySelectorAll('[data-next-position]')
      .forEach(button => {
        button.addEventListener(
          'click',
          () => {
            const pos =
              button.dataset.nextPosition || '';

            const name =
              button.dataset.nextPlayer || '';

            if (selected) {
              // Tapping the moving player again cancels the move.
              if (selected.source === pos) {
                cancelMove();
                return;
              }

              movePlayer(
                selected.name,
                selected.source,
                pos
              );
              return;
            }

            if (name) {
              selected = {
                name,
                source: pos,
              };
              selectedPosition = '';
              renderCard();
              return;
            }

            selected = null;
            selectedPosition = '';
            askOpenPosition(pos);
          }
        );
      });

    card
      .querySelectorAll('[data-next-bench-player]')
      .forEach(button => {
        button.addEventListener(
          'click',
          event => {
            const name =
              button.dataset.nextBenchPlayer || '';

            if (!name) return;

            // Never a Bench destination: a chip names its own player.
            // Tapping it while someone else is moving switches the
            // selection to this bench player; nothing moves.
            event.stopPropagation();

            if (
              selected?.source === 'BENCH' &&
              selected.name === name
            ) {
              cancelMove();
              return;
            }

            selected = {
              name,
              source: 'BENCH',
            };
            selectedPosition = '';
            renderCard();
          }
        );
      });

    card
      .querySelector('[data-next-use-current]')
      ?.addEventListener(
        'click',
        useCurrentDefense
      );

    card
      .querySelector('[data-next-use-plan]')
      ?.addEventListener(
        'click',
        usePlannedDefense
      );

    card
      .querySelector('[data-next-conflict-ack]')
      ?.addEventListener(
        'click',
        acceptConflict
      );

    card
      .querySelector('[data-next-conflict-retry]')
      ?.addEventListener(
        'click',
        loadConflictDefense
      );

    const benchSelected = () => {
      if (!selected || selected.source === 'BENCH') return;

      movePlayerToBench(
        selected.name,
        selected.source
      );
    };

    card
      .querySelector('[data-next-bench-selected]')
      ?.addEventListener('click', event => {
        event.stopPropagation();
        benchSelected();
      });

    // The Bench's empty space is the same destination. Bench chips stop
    // their own taps, so they never reach here.
    card
      .querySelector('[data-next-bench-area]')
      ?.addEventListener('click', event => {
        if (event.target.closest('button')) return;
        benchSelected();
      });

    applyView();
  }

  // Update the save badge and notice in place. The queue finishes saves in
  // the background while the coach keeps tapping, so it must not rebuild
  // the board under a finger mid-tap just to change a status word.
  function renderSyncState() {
    const card = $(CARD_ID);
    const badge = card?.querySelector('[data-next-save-state]');
    const notice = card?.querySelector('[data-next-notice]');
    const hint = card?.querySelector('[data-next-hint]');

    // The plan line follows the saved source ("Changes saved for the 3rd"
    // after an edit), in place, like the badge.
    if (hint && !selected) {
      const text = planStateText();
      if (hint.textContent !== text) hint.textContent = text;
    }

    if (badge) {
      badge.className = `cb-next-save ${saveMode}`;
      if (badge.textContent !== saveMessage) {
        badge.textContent = saveMessage;
      }
    }

    if (notice) {
      notice.hidden = !noticeMessage;
      if (notice.textContent !== noticeMessage) {
        notice.textContent = noticeMessage;
      }
    }

    syncLiveActions();
  }

  function setSyncState(state) {
    if (state === 'saving') {
      saveMode = 'saving';
      saveMessage = 'Saving…';
    } else if (state === 'waiting') {
      saveMode = 'waiting';
      saveMessage = 'Not synced — retrying';
      noticeMessage =
        'No connection right now. Your changes are kept on this screen ' +
        'and will sync automatically when the connection is back.';
    } else if (state === 'error') {
      saveMode = 'error';
      saveMessage = 'Not saved';
    } else if (state === 'conflict') {
      saveMode = 'conflict';
      saveMessage = 'Not saved';
    } else {
      saveMode = 'saved';
      saveMessage = successMessage;
    }
  }

  // Apply a move to the board now and save it behind the coach's back.
  function commitLocalChange(
    next,
    {
      mode = 'custom',
      source = mode,
      message = 'Saved ✓',
    } = {}
  ) {
    const before = snapshot();
    const after = normalize(next);

    selected = null;
    selectedPosition = '';

    if (mode === 'custom' && sameAlignment(before, after)) {
      renderCard();
      return activeSavePromise || Promise.resolve();
    }

    draft = after;
    pendingMode = mode;
    localSource = source;
    conflictPending = false;
    conflictLoaded = false;
    undoNote = '';
    dirty = true;
    localRevision += 1;
    successMessage = message;
    errorMessage = '';
    noticeMessage = '';

    setSyncState('saving');
    renderCard();

    return saveQueued();
  }

  // Send the newest board, one request at a time. Moves made while a save
  // is in flight only mark the board dirty; the loop sends them together
  // next, so an older board can never be saved after a newer one.
  function saveQueued() {
    if (activeSavePromise) return activeSavePromise;
    if (!dirty) return Promise.resolve();

    const request = runSaveQueue();
    activeSavePromise = request;
    return request;
  }

  async function runSaveQueue() {
    try {
      while (dirty) {
        dirty = false;

        const mode = pendingMode;
        const sent = snapshot();

        setSyncState('saving');
        renderSyncState();

        let data;

        try {
          data = await api(
            'POST',
            {
              mode,
              ...(mode === 'current' ? {} : {alignment: sent}),
              // Always versioned. The board is only drawn from a live read,
              // which sets serverBase; if it is ever missing, `{}` fails
              // closed as a conflict (reload) rather than overwriting.
              base_alignment: serverBase || {},
              inning: String(latest?.next_inning || ''),
              // Undo names the save it takes back; a newer one from
              // another device makes it a conflict.
              ...(mode === 'undo' ? {base_revision: undoBaseRevision} : {}),
            }
          );
        } catch (error) {
          if (error.code === 'next_prep_conflict') {
            await resolveConflict();
          } else if (error.retry) {
            // Keep the coach's board. The poll (and the browser's online
            // event) retries once the server answers again.
            dirty = true;
            setSyncState('waiting');
            renderSyncState();
          } else {
            rejectLocalChange(error);
          }
          return;
        }

        latest = data;
        lastSignature = JSON.stringify(data);
        localRevision += 1;
        ownRevision = data?.confirmed?.revision ?? null;
        serverBase = normalize(data?.confirmed?.alignment || sent);
        if (!dirty) localSource = null;

        // Newer moves are still on the board and go out next; only adopt the
        // server's copy when nothing newer is waiting.
        if (!dirty && !sameAlignment(serverBase, draft)) {
          draft = normalize(serverBase);
          renderCard();
        }

        document.dispatchEvent(
          new CustomEvent(
            'coachboard:next-defense-set',
            {detail: {data}}
          )
        );
      }

      noticeMessage = '';
      setSyncState('saved');
      renderSyncState();
    } finally {
      activeSavePromise = null;
      // End Inning's line counts a save in the air as "Saving…": redraw it
      // now that none is, instead of at the next read (~0.8 s later).
      syncLiveActions();
    }
  }

  // The server's Next Inning defense moved on (another coach, a new inning)
  // while this board had changes waiting. Never overwrite it: drop the
  // waiting changes and show what the server has now.
  async function resolveConflict() {
    dirty = false;
    localSource = null;
    conflictCount += 1;
    conflictPending = true;
    conflictLoaded = false;
    // A read already in the air predates the other device's save.
    localRevision += 1;
    // A tap made while the read below is out is part of the replay being
    // stopped; the board is the server's.
    dragSurface?.cancel();
    setSyncState('conflict');
    await loadConflictDefense();
  }

  // Read the defense that replaced this board's change. Until that works
  // the board says so, rather than claiming the other device's defense is
  // shown, and keeps the conflict (and End Inning) held.
  async function loadConflictDefense() {
    if (!conflictPending) return;
    let data = null;

    try {
      data = await api('GET');
    } catch (_) {
      data = null;
    }

    if (!conflictPending) return;
    dirty = false;

    if (data && data.status !== 'inactive' && data.is_live !== false) {
      lastSignature = JSON.stringify(data);
      hydrate(data, {remote: false});        // marks the conflict loaded
    } else {
      // Keep the last defense the server confirmed; the poll (or Try
      // again) reads the new one.
      lastSignature = '';
      draft = normalize(serverBase || {});
      noticeMessage = "Couldn't load the latest defense. Try again.";
    }

    setSyncState('conflict');
    renderCard();
  }

  function conflictNotice() {
    const inning = inningOrdinal(latest?.next_inning || '');
    return `Your change wasn't saved. The ${inning || 'next'} inning defense was ` +
      'changed on another device, and that defense is shown now. Check it, ' +
      'then tap Use this defense or change it.';
  }

  // The coach has looked at the other device's defense and keeps it.
  function acceptConflict() {
    if (!conflictLoaded) return;
    conflictPending = false;
    conflictLoaded = false;
    noticeMessage = '';
    successMessage = 'Saved ✓';
    setSyncState('saved');
    renderCard();
  }

  // The server refused the change itself (for example, a player who is no
  // longer available). Put the board back to what the server has.
  function rejectLocalChange(error) {
    dirty = false;
    localSource = null;
    rejectCount += 1;
    draft = normalize(serverBase || {});
    noticeMessage = '';
    errorMessage =
      error?.message ||
      'Unable to save the Next Inning defense.';
    setSyncState('error');
    renderCard();
  }

  async function flushPendingSave() {
    const deadline = Date.now() + 10000;
    const timeoutMessage =
      'Next Inning defense is still saving. Check your connection, wait for Saved ✓, then try ending the inning again.';
    const conflictsBefore = conflictCount;
    const rejectsBefore = rejectCount;
    let retried = false;

    while (activeSavePromise || dirty) {
      if (!activeSavePromise) {
        // Changes waiting on a failed save get one more try now; End
        // Inning must not start the inning with an older defense.
        if (retried) {
          throw new Error(
            'The Next Inning defense has not synced yet. Check your connection, then try ending the inning again.'
          );
        }

        retried = true;
        saveQueued();
      }

      const pending = activeSavePromise;
      const remaining = deadline - Date.now();

      if (remaining <= 0) {
        throw new Error(timeoutMessage);
      }

      let timer = null;

      try {
        await Promise.race([
          pending.then(
            () => null,
            () => null
          ),
          new Promise((_, reject) => {
            timer = window.setTimeout(
              () => reject(
                new Error(timeoutMessage)
              ),
              remaining
            );
          }),
        ]);
      } finally {
        if (timer !== null) {
          window.clearTimeout(timer);
        }
      }
    }

    if (conflictPending && !conflictLoaded) {
      throw new Error(
        "Your change to the next inning wasn't saved, and the latest defense " +
        "couldn't be loaded. Tap Try again, then end the inning."
      );
    }

    if (conflictPending || conflictCount !== conflictsBefore) {
      const inning = inningOrdinal(latest?.next_inning || '');
      throw new Error(
        `Your change to the ${inning || 'next'} inning wasn't saved: another ` +
        'device changed that defense. Check it, tap Use this defense or ' +
        'change it, then end the inning.'
      );
    }

    if (rejectCount !== rejectsBefore) {
      throw new Error(
        errorMessage
          ? `${errorMessage} Fix the defense, then try ending the inning again.`
          : 'The defense was not saved. Fix it, then try ending the inning again.'
      );
    }

    return snapshot();
  }

  function isSaveInFlightOrQueued() {
    return dirty || Boolean(activeSavePromise);
  }

  function movePlayerToBench(
    name,
    source
  ) {
    if (
      !name ||
      !source ||
      source === 'BENCH'
    ) {
      selected = null;
      selectedPosition = '';
      renderCard();
      return;
    }

    const next = snapshot();
    next[source] = '';

    commitLocalChange(
      next,
      {
        message:
          `${playerLabel(name)} → BENCH`,
      }
    );
  }

  // A move to an open position: the old spot (if any) is left open. An
  // occupied target never reaches here -- askDisplaced asks the coach.
  function plainMove(board, name, source, target) {
    const next = {...board};

    if (source && source !== 'BENCH') {
      next[source] = '';
    }

    next[target] = name;
    return next;
  }

  // The displacement question that is open, if any: another coach's
  // change to the plan discards it (applyPrep).
  let openChain = null;

  function discardOpenChain() {
    if (!openChain) return false;
    const chain = openChain;
    openChain = null;
    chain.close();
    return true;
  }

  /*
   * "Graham is moving to SS next inning. Where should Rylan go?"
   *
   * The coach said where one player goes, not what happens to the player
   * already there. Offer Graham's vacated spot, open spots, "another
   * position…" and the bench; never choose. Choosing another occupied
   * spot asks about that player next. Players already placed are never
   * offered again (no loops), and P is never an ordinary spot.
   *
   * A plan stays fast: a one-question answer goes straight into the save
   * queue; only a longer chain (3+ players) is shown for a quick check.
   * Nothing enters the queue until the chain is resolved, and then as one
   * alignment.
   */
  function askDisplaced(board, name, source, target) {
    discardOpenChain();

    const modal = pitchingChangeModal();
    const instance = bootstrap.Modal.getOrCreateInstance(modal);
    const titleEl = modal.querySelector('[data-pitch-title]');
    const questionEl = modal.querySelector('[data-pitch-question]');
    const noteEl = modal.querySelector('[data-pitch-readiness]');
    const list = modal.querySelector('[data-pitch-choices]');
    const spots = positions().filter(pos => pos !== 'P');
    const fromLabel = pos => (!pos || pos === 'BENCH' ? 'Bench' : pos);

    const draftBoard = {...board};
    if (source && source !== 'BENCH') draftBoard[source] = '';
    const firstDisplaced = draftBoard[target];
    draftBoard[target] = name;
    const moves = [{name, from: source, to: target}];
    const placed = new Set([name]);

    const chain = {
      close: () => instance.hide(),
    };
    openChain = chain;
    modal.addEventListener('hidden.bs.modal', () => {
      if (openChain === chain) openChain = null;
      noteEl.style.whiteSpace = '';
    }, {once: true});

    const openSpots = () => [
      ...spots.filter(pos => !draftBoard[pos] && board[pos]),
      ...spots.filter(pos => !draftBoard[pos] && !board[pos]),
    ];
    const takenSpots = () => spots.filter(
      pos => draftBoard[pos] && !placed.has(draftBoard[pos])
    );

    const render = (title, question, buttons, lines = []) => {
      titleEl.textContent = title;
      questionEl.textContent = question;
      noteEl.textContent = lines.join('\n');
      noteEl.hidden = !lines.length;
      noteEl.className = 'small mb-2 fw-semibold';
      noteEl.style.whiteSpace = lines.length ? 'pre-line' : '';
      list.replaceChildren(...buttons.map(([label, className, onChoose]) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `btn ${className}`;
        button.textContent = label;
        button.addEventListener('click', () => {
          if (openChain === chain) onChoose();
        });
        return button;
      }));
    };

    const cancel = ['Cancel', 'btn-outline-secondary', () => instance.hide()];

    const commit = () => {
      openChain = null;
      instance.hide();
      // The plan moved on underneath the question: never apply it there.
      if (!sameAlignment(snapshot(), board)) {
        noticeMessage = 'Next inning defense updated.';
        renderSyncState();
        return;
      }
      commitLocalChange({...draftBoard}, {
        message: moves
          .map(move => `${playerLabel(move.name)} → ${move.to}`)
          .join(' · ') + ' ✓',
      });
    };

    const resolved = () => {
      if (moves.length < 3) {
        commit();
        return;
      }
      render(
        `${name} is moving to ${target} next inning`,
        'Next inning after this change:',
        [['Save plan', 'btn-primary', commit], cancel],
        [
          ...moves.map(move => `${move.name}: ${fromLabel(move.from)} → ${fromLabel(move.to)}`),
          ...openSpots().map(pos => `${pos}: open`),
        ],
      );
    };

    const place = (player, from, to) => {
      if (to !== 'BENCH') draftBoard[to] = player;
      placed.add(player);
      moves.push({name: player, from, to});
    };

    const ask = (player, from, mover) => {
      const buttons = openSpots().map(pos => [
        `Put ${player} at ${pos}`,
        'btn-outline-primary',
        () => {
          place(player, from, pos);
          resolved();
        },
      ]);
      if (takenSpots().length) {
        buttons.push([
          `Move ${player} to another position…`,
          'btn-outline-primary',
          () => choosePosition(player, from, mover),
        ]);
      }
      buttons.push([`Bench ${player}`, 'btn-outline-primary', () => {
        place(player, from, 'BENCH');
        resolved();
      }]);
      buttons.push(cancel);
      render(`${mover} is moving to ${from} next inning`, `Where should ${player} go?`, buttons);
    };

    const choosePosition = (player, from, mover) => {
      render(`${mover} is moving to ${from} next inning`, `Where should ${player} go?`, [
        ...takenSpots().map(pos => [
          `${pos} · ${draftBoard[pos]}`,
          'btn-outline-primary',
          () => {
            const next = draftBoard[pos];
            place(player, from, pos);
            ask(next, pos, player);
          },
        ]),
        ['Back', 'btn-outline-secondary', () => ask(player, from, mover)],
        cancel,
      ]);
    };

    ask(firstDisplaced, target, name);
    instance.show();
  }

  function movePlayer(
    name,
    source,
    target
  ) {
    selected = null;
    selectedPosition = '';

    if (
      !name ||
      !target ||
      source === target
    ) {
      renderCard();
      return;
    }

    const board = snapshot();
    const pitcher = board.P || '';

    // A flagged pitcher can still be planned at P: this is a plan, not the
    // official field. The board shows the status; End Inning re-evaluates
    // it and asks for the coach's decision when the pitcher goes in.

    // Moving a player on or off P is a pitching change, not a position
    // swap. The coach has only said who is moving; ask what happens to the
    // other pitcher before anything changes.
    if (target === 'P' && pitcher && pitcher !== name) {
      renderCard();
      askOutgoingPitcher(board, name, source, pitcher);
      return;
    }

    if (source === 'P' && name === pitcher) {
      renderCard();
      askIncomingPitcher(board, name, target);
      return;
    }

    // Moving onto an occupied position: the coach decides where that
    // player goes. Nothing is swapped or benched automatically.
    const occupant = board[target] || '';
    if (target !== 'P' && occupant && occupant !== name) {
      renderCard();
      askDisplaced(board, name, source, target);
      return;
    }

    const readyNote =
      target === 'P' && isPitchingChange(name)
        ? ` · ${pitchingReadiness(name).label}`
        : '';

    commitLocalChange(
      plainMove(board, name, source, target),
      {
        message:
          `${playerLabel(name)} → ${target} ✓${readyNote}`,
      }
    );
  }

  // Pitching readiness is the pitch_count_summary in the live state every
  // live-game module shares (coachboard:live-state): the same data the
  // Change Pitcher picker reads and End Inning checks on the server.
  // Nothing is calculated here; the labels match Change Pitcher's.
  function pitchingReadiness(name) {
    const summary = pitchSummary?.[name];
    const status = String(summary?.status || '')
      .trim()
      .replace(/^Unavailable — /, '');
    // The server classifies it (pitching_eligibility.py) and sends the
    // answer with the live state, so this screen, Change Pitcher and End
    // Inning agree. The fallback only covers a state without it.
    const kind =
      summary?.eligibility ||
      (summary?.status === 'Available'
        ? 'ready'
        : summary?.advisory
          ? 'advisory'
          : !summary || !status
            ? 'unknown'
            : 'rule_conflict');
    // One of four words, shown prominently, then the status.
    const word = {
      ready: 'Ready',
      advisory: 'Advisory',
      rule_conflict: 'Rule conflict',
      unknown: "Can't confirm",
    }[kind] || 'Rule conflict';
    const label =
      kind === 'ready'
        ? word
        : [word, status].filter(Boolean).join(' · ');
    const daily = summary?.daily;
    // This game's count is entered when it ends: say what is known.
    const earlier = Number(daily) > 0 ? ` · ${daily} game pitches earlier today` : '';
    const today =
      summary?.pitching_now
        ? `Pitching now${earlier}`
        : summary?.pitched_this_game
          ? `Pitched this game · count entered after the game${earlier}`
          : daily === null || daily === undefined
            ? ''
            : `${daily} ${Number(daily) === 1 ? 'pitch' : 'pitches'} today`;
    // The server's wording names the rule set and the reason.
    const detail = String(
      summary?.eligibility_message ||
      summary?.status_detail ||
      summary?.next_available ||
      ''
    ).trim();

    return {
      kind,
      ready: kind === 'ready',
      label,
      text: [
        summary?.eligibility_message ? word : label,
        today,
        detail,
      ].filter(Boolean).join(' · '),
    };
  }

  // As on the server, only a new pitcher is checked: the pitcher on the
  // mound now carrying into the next inning is not a pitching change.
  function isPitchingChange(name) {
    return Boolean(name) && name !== (latest?.current_alignment?.P || '');
  }

  function toneFor(name) {
    const kind = pitchingReadiness(name).kind;
    return kind === 'ready'
      ? 'ok'
      : kind === 'rule_conflict'
        ? 'danger'
        : 'warn';
  }

  // Planning a flagged pitcher asks nothing extra; the note says what End
  // Inning will ask when the pitcher actually goes in.
  function readinessNote(name) {
    const readiness = pitchingReadiness(name);

    if (readiness.ready) {
      return `${name}: ${readiness.text}`;
    }

    const ask = {
      advisory: 'End Inning will show this before the inning starts.',
      unknown:
        `End Inning will ask you to confirm you verified ${name} is ` +
        'eligible.',
      rule_conflict:
        `End Inning will ask whether to use ${name} anyway.`,
    }[readiness.kind] || '';

    const sentence = /[.!?]$/.test(readiness.text)
      ? readiness.text
      : `${readiness.text}.`;
    return `${name}: ${sentence} ${ask}`.trim();
  }

  // The planned next pitcher's readiness, shown on the board so a coach
  // sees it before End Inning. Informational only: it never opens a
  // question. Not shown until the live state has arrived.
  function pitcherStatus() {
    const name = draft?.P || '';

    if (!name || !pitchSummary) {
      return {tone: '', text: ''};
    }

    const readiness = pitchingReadiness(name);

    if (!isPitchingChange(name)) {
      // CoachBoard records this game's pitches when the game ends, so it
      // cannot say how many the pitcher on the mound has thrown today.
      return {
        tone: 'ready',
        text:
          `Pitcher: ${name} · pitching now · ` +
          "this game's pitches aren't counted until it ends",
      };
    }

    if (readiness.ready) {
      return {tone: 'ready', text: `Pitcher: ${name} · ${readiness.text}`};
    }

    // Advisory, Rule conflict or Can't confirm leads the line; End Inning
    // asks for the decision.
    return {
      tone: readiness.kind,
      text:
        `⚠ Pitcher: ${name} · ${readiness.text} · ` +
        'End Inning will ask you to decide',
    };
  }

  function pitcherStatusMarkup() {
    const {tone, text} = pitcherStatus();
    return `<div
      class="cb-next-pitcher-status ${esc(tone)}"
      data-next-pitcher-status
      ${text ? '' : 'hidden'}
    >${esc(text)}</div>`;
  }

  function renderPitcherStatus() {
    const line = $(CARD_ID)?.querySelector('[data-next-pitcher-status]');
    if (!line) return;

    const {tone, text} = pitcherStatus();
    line.className = `cb-next-pitcher-status ${tone}`;
    line.hidden = !text;
    if (line.textContent !== text) {
      line.textContent = text;
    }
  }

  // "Graham is going in to pitch. Where should Pat go?"
  function askOutgoingPitcher(board, incoming, source, pitcher) {
    const fromField = source && source !== 'BENCH';
    const base = {...board, P: incoming};

    if (fromField) {
      base[source] = '';
    }

    const choices = [];

    if (fromField) {
      choices.push({
        label: `Put ${pitcher} at ${source}`,
        alignment: {...base, [source]: pitcher},
        message: `${incoming} → P · ${pitcher} → ${source} ✓`,
      });
    }

    positions()
      .filter(pos => pos !== 'P' && !board[pos])
      .forEach(pos => {
        choices.push({
          label: `Put ${pitcher} at ${pos}`,
          alignment: {...base, [pos]: pitcher},
          message: `${incoming} → P · ${pitcher} → ${pos} ✓`,
        });
      });

    choices.push({
      label: fromField
        ? `Bench ${pitcher} · ${source} open`
        : `Bench ${pitcher}`,
      alignment: base,
      message: `${incoming} → P · ${pitcher} → BENCH`,
    });

    askPitchingChange(
      board,
      `${incoming} is going in to pitch`,
      `Where should ${pitcher} go?`,
      choices,
      {
        note: isPitchingChange(incoming) ? readinessNote(incoming) : '',
        noteTone: toneFor(incoming),
      }
    );
  }

  // "Pat is moving to SS. Who's pitching?"
  function askIncomingPitcher(board, pitcher, target) {
    const occupant = board[target] || '';
    const base = {...board, P: '', [target]: pitcher};
    const choices = [];

    const checked = occupant && isPitchingChange(occupant);

    if (occupant) {
      choices.push({
        label: `${occupant} pitches`,
        alignment: {...base, P: occupant},
        message: `${pitcher} → ${target} · ${occupant} → P ✓`,
      });
      choices.push({
        label: `Bench ${occupant} · P open`,
        alignment: base,
        message: `${pitcher} → ${target} · ${occupant} → BENCH`,
      });
    } else {
      choices.push({
        label: 'Leave P open — pick the pitcher next',
        alignment: base,
        message: `${pitcher} → ${target}`,
      });
    }

    askPitchingChange(
      board,
      `${pitcher} is moving to ${target}`,
      "Who's pitching next inning?",
      choices,
      {
        note: checked ? readinessNote(occupant) : '',
        noteTone: checked ? toneFor(occupant) : 'ok',
      }
    );
  }

  function pitchingChangeModal() {
    let modal = $(PITCH_MODAL_ID);

    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = PITCH_MODAL_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('aria-hidden', 'true');
    modal.setAttribute('aria-labelledby', `${PITCH_MODAL_ID}-title`);

    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5
              class="modal-title"
              id="${PITCH_MODAL_ID}-title"
              data-pitch-title
            ></h5>
            <button
              type="button"
              class="btn-close"
              data-bs-dismiss="modal"
              aria-label="Close"
            ></button>
          </div>
          <div class="modal-body">
            <div class="fw-semibold mb-2" data-pitch-question></div>
            <div class="small mb-2" data-pitch-readiness hidden></div>
            <div class="d-grid gap-2" data-pitch-choices></div>
          </div>
        </div>
      </div>`;

    document.body.appendChild(modal);

    return modal;
  }

  // Nothing is saved while the coach decides. Only the answer becomes the
  // board, as one change through the save queue (and one Undo).
  function askPitchingChange(
    board,
    title,
    question,
    choices,
    {note = '', noteTone = 'ok'} = {}
  ) {
    const modal = pitchingChangeModal();
    const instance = bootstrap.Modal.getOrCreateInstance(modal);
    const list = modal.querySelector('[data-pitch-choices]');
    const readiness = modal.querySelector('[data-pitch-readiness]');

    modal.querySelector('[data-pitch-title]').textContent = title;
    modal.querySelector('[data-pitch-question]').textContent = question;
    readiness.textContent = note;
    readiness.hidden = !note;
    readiness.className =
      `small mb-2 fw-semibold ${
        {danger: 'text-danger', warn: 'text-warning-emphasis'}[noteTone] || 'text-success'
      }`;
    list.replaceChildren();

    const addButton = (label, className, onChoose, disabled = false) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `btn ${className}`;
      button.textContent = label;
      button.disabled = disabled;
      button.addEventListener('click', () => {
        instance.hide();
        onChoose();
      });
      list.appendChild(button);
    };

    choices.forEach(choice => {
      addButton(choice.label, 'btn-outline-primary', () => {
        // The board moved on while the question was open (another
        // coach, a new inning): the answer no longer applies.
        if (!sameAlignment(snapshot(), board)) {
          noticeMessage =
            'The defense changed while you were choosing. Nothing was moved.';
          renderSyncState();
          return;
        }

        commitLocalChange(
          choice.alignment,
          {message: choice.message}
        );
      }, choice.disabled === true);
    });

    addButton('Cancel', 'btn-outline-secondary', () => {});

    instance.show();
  }

  /**
   * Next Inning's half of the shared drag contract.
   *
   * Deliberately different from On the Field: the pitcher IS a valid
   * source here, because the next inning's defense is a plan and the
   * coach edits the mound directly on the board. Drops go through the
   * same movePlayer()/movePlayerToBench() as taps -- so a drop on or off
   * P asks the same pitching-change question -- which is why the drop
   * semantics stay in this file rather than in the shared manager.
   */
  function registerDragSurface() {
    if (dragSurface || !window.CoachBoardDrag) return;

    dragSurface = window.CoachBoardDrag.registerSurface({
      id: 'next',
      root: () => $(CARD_ID),
      canStart: () => activeView === 'next',
      sourceSelector:
        `#${CARD_ID} [data-next-position], #${CARD_ID} [data-next-bench-player]`,
      targetSelector:
        `#${CARD_ID} [data-next-position], #${CARD_ID} .cb-next-bench`,

      resolveSource: node => {
        const benched = node.dataset.nextBenchPlayer;
        if (benched) {
          return {
            kind: 'chip',
            key: `BENCH:${benched}`,
            name: benched,
            from: 'BENCH',
            label: playerLabel(benched),
          };
        }
        const name = node.dataset.nextPlayer || '';
        const from = node.dataset.nextPosition || '';
        if (!name || !from) return null;
        return {
          kind: 'marker',
          key: from,
          name,
          from,
          label: playerLabel(name),
        };
      },

      findSource: source => (
        source.from === 'BENCH'
          ? document.querySelector(
              `#${CARD_ID} [data-next-bench-player="${CSS.escape(source.name)}"]`
            )
          : document.querySelector(
              `#${CARD_ID} [data-next-position="${CSS.escape(source.from)}"]`
            )
      ),

      resolveTarget: node => ({
        position: node.dataset.nextPosition || 'BENCH',
      }),

      onDrop: (source, target) => {
        selected = null;
        selectedPosition = '';
        if (target.position === 'BENCH') {
          movePlayerToBench(source.name, source.from);
          return;
        }
        movePlayer(source.name, source.from, target.position);
      },
    });
  }

  function useCurrentDefense() {
    if (!latest) return Promise.resolve();

    return commitLocalChange(
      latest.current_alignment || {},
      {
        mode: 'current',
        message: 'Saved ✓',
      }
    );
  }

  // The upcoming inning's saved plan, chosen by the coach. Saved as
  // 'planned' by the coach, so later live changes, redraws and reloads keep
  // it. A different pitcher in it is checked at End Inning, like any other.
  function usePlannedDefense() {
    const seed = plannedSeed();
    if (!seed) return Promise.resolve();

    return commitLocalChange(
      seed,
      {
        mode: 'planned',
        message: 'Saved ✓',
      }
    );
  }

  function canUndoNext() {
    return !conflictPending && Boolean(latest?.confirmed?.previous || dirty || activeSavePromise);
  }

  // Back to the defense as it was saved before the last save. A change
  // still saving goes out first, so Undo takes back that one.
  async function undoNext() {
    if (!canUndoNext()) return;
    if (dirty || activeSavePromise) {
      try {
        await flushPendingSave();
      } catch (error) {
        return;
      }
    }
    const previous = latest?.confirmed?.previous;
    if (!previous?.alignment || conflictPending) {
      renderCard();
      return;
    }

    undoBaseRevision = latest?.confirmed?.revision ?? null;
    const before = snapshot();
    const restored = normalize(previous.alignment);
    const back = positions()
      .filter(pos => (before[pos] || '') !== (restored[pos] || ''))
      .map(pos => (restored[pos] ? `${restored[pos]} back at ${pos}` : `${pos} open again`));
    const inning = inningOrdinal(latest?.next_inning || '');
    const saving = commitLocalChange(
      restored,
      {
        mode: 'undo',
        source: previous.source || 'custom',
        message: 'Restored ✓',
      }
    );
    // Say what came back, after commitLocalChange cleared the last note.
    undoNote =
      `Undid your last change to the ${inning}` +
      (back.length ? `: ${back.slice(0, 3).join('; ')}${back.length > 3 ? '; …' : ''}.` : '.');
    renderCard();
    return saving;
  }

  function showError(message) {
    errorMessage = String(
      message || ''
    );

    if (errorMessage) {
      activeView = 'next';
    }

    renderCard();
  }

  function clearError() {
    errorMessage = '';
    renderCard();
  }

  // End Inning stopped because the next inning has no pitcher: the Next
  // Inning board's own "Set a pitcher" line is the one message, and focus
  // goes to its P spot, where the pitcher is chosen.
  function requirePitcher() {
    activeView = 'next';
    errorMessage = '';
    renderCard();
    applyView();
    const spot = document.querySelector(`#${CARD_ID} [data-next-position="P"]`);
    if (!spot) return false;
    spot.scrollIntoView({block: 'center'});
    spot.focus({preventScroll: true});
    return true;
  }

  function hydrate(data, {remote = true} = {}) {
    const previousBase = serverBase;

    latest = data;

    if (
      !data ||
      data.status === 'inactive' ||
      data.is_live === false
    ) {
      serverBase = null;
      dirty = false;

      $(SWITCH_ID)?.remove();
      $(CARD_ID)?.remove();
      $(PLAN_CARD_ID)?.remove();
      $('cbNextOpenWarning')?.remove();

      const now = $('cbQuickDefense');

      if (now) {
        now.hidden = false;
      }

      return false;
    }

    const incoming = normalize(
      data?.confirmed?.alignment ||
      data?.current_alignment ||
      {}
    );

    serverBase = normalize(
      data?.confirmed?.alignment || {}
    );

    // Only a real change to the Next Inning defense clears a half-finished
    // selection; a refresh that brings the same board keeps it.
    if (!sameAlignment(incoming, draft)) {
      if (
        remote &&
        previousBase &&
        data?.confirmed?.source === 'custom'
      ) {
        noticeMessage = 'Next inning defense updated.';
      }

      // An unfinished displacement question was about the old plan.
      if (discardOpenChain()) {
        noticeMessage = 'Next inning defense updated.';
      }

      draft = incoming;
      selected = null;
      selectedPosition = '';
    }

    if (saveMode !== 'error' && !conflictPending) {
      successMessage = 'Saved ✓';
      setSyncState('saved');
    }

    // A conflict's replacement defense is on the board now: the coach can
    // check it and accept it.
    if (conflictPending) {
      conflictLoaded = true;
      noticeMessage = conflictNotice();
    }

    renderCard();

    return true;
  }

  // One read at a time. Start-up, building the tabs and the poll only need
  // the latest data, so they share a read already in the air instead of
  // sending the same request again (at start-up the tabs and the 140 ms
  // read used to ask twice, ~40 ms apart). A caller reporting a change
  // (`changed`) marks that read stale: its answer may predate the change,
  // so it is dropped and read again -- the change always shows, and an
  // older answer never lands on top of a newer one.
  function refresh({
    force = false,
    changed = false,
  } = {}) {
    // The queue owns the board while a save is in the air; its answer is
    // newer than anything this read could return.
    if (activeSavePromise) return Promise.resolve(null);

    readForce = readForce || force;

    if (readInFlight) {
      if (changed) readStale = true;
      return readInFlight;
    }

    readInFlight = readUntilCurrent().finally(() => {
      readInFlight = null;
    });

    return readInFlight;
  }

  async function readUntilCurrent() {
    for (;;) {
      readStale = false;

      const revision = localRevision;
      let data;

      try {
        data = await api('GET');
      } catch (_) {
        return null;
      }

      if (readStale && !activeSavePromise) continue;

      const force = readForce;
      readForce = false;

      return applyRead(data, revision, force);
    }
  }

  function applyRead(data, revision, force) {
    try {
      if (
        activeSavePromise ||
        revision !== localRevision
      ) {
        return null;
      }

      const signature = JSON.stringify(data);

      if (dirty) {
        // Changes are waiting on a failed save and the server answers
        // again: send them. The save carries the defense it was based on,
        // so if the server's Next Inning defense moved on meanwhile it is
        // refused (and shown) rather than overwritten.
        saveQueued();
        return data;
      }

      // Read another inning than the page shows: one of them is behind.
      if (readDisagrees(data)) askForSharedState();

      if (
        force ||
        signature !== lastSignature ||
        !$(CARD_ID)
      ) {
        // A changed/forced authoritative refresh makes any active drag
        // stale. Cancel it before hydrate() replaces the NEXT card DOM.
        dragSurface?.cancel();

        lastSignature = signature;
        hydrate(data);
      } else {
        ensureSurface();
      }

      return data;
    } catch (_) {
      return null;
    }
  }

  // A live change (from this device or another) moves what End Inning would
  // send and what the Pregame Plan note compares against. Re-read the
  // next-inning data once, shortly after, however many scripts announce the
  // same change -- instead of waiting for the 3.5 s poll.
  function onLiveChange() {
    window.clearTimeout(liveChangeTimer);
    liveChangeTimer = window.setTimeout(() => refresh({changed: true}), 150);
  }

  function afterAdvance() {
    activeView = 'now';
    selected = null;
    selectedPosition = '';
    undoNote = '';
    conflictPending = false;
    conflictLoaded = false;
    errorMessage = '';
    noticeMessage = '';
    serverBase = null;
    dirty = false;
    lastSignature = '';
    applyView();

    // A read already in the air is about the inning that just ended.
    if (readInFlight) readStale = true;

    window.setTimeout(
      () => refresh({force: true, changed: true}),
      120
    );
  }

  function bindSocket() {
    if (socketBound) return;

    const socket =
      window.__cbLiveGameSocket;

    if (
      !socket ||
      typeof socket.on !== 'function'
    ) {
      return;
    }

    socketBound = true;

    socket.on(
      'next_inning_prep_update',
      payload => {
        if (
          Number(payload?.game_id) === gameId
        ) {
          refresh({changed: true});
        }
      }
    );
  }

  window.CBNextDefense = {
    refresh: () => refresh({force: true, changed: true}),
    useSame: useCurrentDefense,
    usePlan: usePlannedDefense,
    undo: undoNext,
    getAlignment: () => snapshot(),
    flush: flushPendingSave,
    isSaveInFlightOrQueued,
    showError,
    clearError,
    requirePitcher,
    afterAdvance,
    showNext: () => {
      activeView = 'next';
      applyView();
    },
    showNow: () => {
      activeView = 'now';
      applyView();
    },
    // End Inning's "Finish ... Defense" and the next-inning warning open the
    // picker for that open position directly.
    fixOpen: pos => {
      activeView = 'next';
      applyView();
      askOpenPosition(pos);
    },
  };

  installStyles();

  // ensureSwitcher() needs the live shell and Quick Field, and both are
  // mounted by other modules -- live_game_dugout_mode in particular is loaded
  // dynamically, so #cbQuickDefense normally appears after this module has
  // started. ensureSwitcher() simply returns null when they are missing, and
  // the only thing that tried again was the 3500ms refresh interval, so the
  // tabs could sit invisible for several seconds while a coach had no way to
  // reach Next Inning or the pregame plan.
  function liveSurfaceReady() {
    const overlay = $('live-game-overlay');

    // A non-live game keeps the overlay in d-none and never grows a shell,
    // so this doubles as the liveness gate: no API round trip required, and
    // no chance of flashing a bogus switcher onto a game that is not live.
    return Boolean(
      overlay &&
      !overlay.classList.contains('d-none') &&
      overlay.querySelector('.coach-live-shell') &&
      $('cbQuickDefense')
    );
  }

  // The start-up request (140 ms) usually answers before the live shell
  // exists, so hydrate() keeps the data but has nowhere to draw the card.
  // Draw it the moment the tabs are built, from that same data -- otherwise
  // Next Inning stayed blank until the first 3.5 s poll. No extra request.
  function buildSurface() {
    const switcher = ensureSwitcher();

    if (switcher && !$(CARD_ID)) {
      // A game started from this page last answered "not live"; that
      // answer has no board (or saved defense) to draw, so read it now.
      if (latest && latest.status !== 'inactive' && latest.is_live !== false) {
        renderCard();
      } else if (latest) {
        refresh({changed: true});
      } else {
        // Nothing loaded yet: share the start-up read (in the air, or
        // started here) rather than asking a second time.
        refresh();
      }
    }

    return switcher;
  }

  function bootSurfaceWhenReady() {
    if ($(SWITCH_ID)) return;

    if (liveSurfaceReady()) {
      buildSurface();
      return;
    }

    if (!window.MutationObserver) return;

    const target = $('live-game-overlay') || document.body;

    const observer = new window.MutationObserver(() => {
      // Do nothing at all until the surface this needs actually exists. A
      // game that is never started simply leaves the observer armed, which
      // is what makes the tabs appear promptly when a coach starts a game
      // without reloading the page.
      if (!liveSurfaceReady()) return;

      // One shot: disconnect the moment the switcher is built, so this stops
      // running for the rest of the game.
      if (buildSurface()) observer.disconnect();
    });

    observer.observe(target, {childList: true, subtree: true});
  }

  const start = () => {
    $('next-inning-adjust-modal')?.remove();

    // Build the tabs from the DOM alone, without waiting on the first
    // next-inning response. NEXT and Pregame Plan hydrate afterwards.
    bootSurfaceWhenReady();

    // The start-up read -- unless building the tabs already asked.
    window.setTimeout(
      () => {
        if (!latest) refresh({force: true});
      },
      140
    );

    window.setInterval(
      () => refresh(),
      3500
    );

    window.setInterval(
      bindSocket,
      1500
    );

    document.addEventListener(
      'coachboard:test2-inning-started',
      afterAdvance
    );

    document.addEventListener(
      'coachboard:live-delta',
      onLiveChange
    );

    document.addEventListener('coachboard:live-state', event => {
      const detail = event.detail || {};
      if (
        Number(detail.game_id) === gameId &&
        detail.state?.pitch_count_summary
      ) {
        pitchSummary = detail.state.pitch_count_summary;
        renderPitcherStatus();
      }
      // The field right now, for the "Empty now" line and Pregame Plan's
      // "On the field now" -- updated with the live state (an Undo, a fill)
      // rather than at the next poll.
      if (
        Number(detail.game_id) === gameId &&
        latest &&
        detail.state?.current_alignment &&
        String(detail.state.current_inning || '') === String(latest.current_inning || '')
      ) {
        latest.current_alignment = detail.state.current_alignment;
        syncLiveActions();
        renderPlanCard();
      }
      // Another inning than this board read (an Undo, a remote End Inning
      // found by a poll or on reconnect): relabel now, read the next inning.
      if (
        Number(detail.game_id) === gameId &&
        latest &&
        detail.state?.current_inning &&
        String(detail.state.current_inning) !== String(latest.current_inning || '')
      ) {
        syncUpcomingInningLabels();
        onLiveChange();
      }
    });

    // Back online: read the server now instead of at the next poll, which
    // also sends any Next Inning changes still waiting to sync.
    window.addEventListener('online', () => refresh({changed: true}));

    registerDragSurface();

  };

  document.readyState === 'loading'
    ? document.addEventListener(
        'DOMContentLoaded',
        start,
        {once: true}
      )
    : start();
})();
