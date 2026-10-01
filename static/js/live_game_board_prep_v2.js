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
  let liveChangeTimer = null;
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
  let activeSavePromise = null;
  let conflictCount = 0;
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
  let undoStack = [];
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
        '<div class="cb-next-warning danger">' +
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
    const source = latest?.confirmed?.source || '';
    const nextLabel = inningOrdinal(
      latest?.next_inning || ''
    );
    const currentLabel = inningOrdinal(
      latest?.current_inning || ''
    );

    if (source === 'planned') {
      return nextLabel
        ? `Pregame plan for the ${nextLabel}`
        : 'Pregame defensive plan';
    }

    if (source === 'current') {
      return currentLabel
        ? `Same defense as the ${currentLabel}`
        : 'Same defense as this inning';
    }

    return nextLabel
      ? `Changes saved for the ${nextLabel}`
      : 'Changes saved';
  }

  function selectionHelp() {
    if (selected) {
      return `
        <div class="cb-next-selection active" role="status" aria-live="polite">
          <div class="cb-next-step">STEP 2 · CHOOSE DESTINATION</div>
          <div class="cb-next-selection-main">
            Moving <strong>${esc(playerLabel(selected.name))}</strong>
          </div>
          <div class="cb-next-selection-sub">
            Tap the position where this player should go.
          </div>
          <button
            type="button"
            class="btn btn-sm btn-outline-secondary mt-2"
            data-next-cancel
          >Cancel move</button>
        </div>`;
    }

    return '';
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

    return `
      <div class="cb-next-bench ${selected ? 'destination-active' : ''}">
        <div class="cb-next-bench-head">
          <strong>Bench · ${bench.length}</strong>
          <span>
            ${
              selected
                ? 'Bench is also a destination'
                : 'Tap a bench player to move them'
            }
          </span>
        </div>

        ${
          selected && selected.source !== 'BENCH'
            ? `
              <button
                type="button"
                class="cb-next-send-bench"
                data-next-bench-selected
              >
                SEND ${esc(playerLabel(selected.name))} TO BENCH
              </button>
            `
            : ''
        }

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

    help.textContent =
      'Choose a player. If they are already on the field, their current spot will be left open.';

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
        display:grid;
        grid-template-columns:1fr 1fr 1fr;
        gap:4px;
        padding:4px;
        margin:0 0 8px;
        border:1px solid #d7dde5;
        border-radius:12px;
        background:#e9edf2;
      }

      /* Three labelled tabs are much tighter than the old two, so the
         buttons give back some horizontal padding and a little type size
         to keep "On the Field" on one line at phone width. */
      #${SWITCH_ID} .btn{
        min-height:42px;
        padding:6px 6px;
        border:0!important;
        border-radius:9px!important;
        background:transparent;
        color:#475467;
        font-size:.85rem;
        font-weight:900;
        line-height:1.2;
        box-shadow:none!important;
      }

      #${SWITCH_ID} .btn.active{
        background:#172033!important;
        color:#fff!important;
      }

      #${SWITCH_ID} [data-now-next="next"]{
        font-size:.8rem;
        white-space:nowrap;
        letter-spacing:-.01em;
      }

      @media(max-width:390px){
        #${SWITCH_ID} [data-now-next="next"]{
          font-size:.73rem;
          padding-left:3px;
          padding-right:3px;
        }
      }

      #${PLAN_CARD_ID}{
        border:1.5px solid #cfd6df;
        border-radius:14px;
        background:#fff;
        overflow:hidden;
        margin:0 0 10px;
        box-shadow:0 2px 7px rgba(16,24,40,.08);
      }

      #${PLAN_CARD_ID}[hidden]{
        display:none!important;
      }

      #${PLAN_CARD_ID} .cb-plan-head{
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:10px;
        padding:11px 12px 9px;
        border-bottom:1px solid #e7ebef;
      }

      #${PLAN_CARD_ID} .cb-plan-kicker{
        color:#667085;
        font-size:.6rem;
        font-weight:900;
        text-transform:uppercase;
        letter-spacing:.09em;
      }

      #${PLAN_CARD_ID} .cb-plan-title{
        color:#172033;
        font-size:1.05rem;
        line-height:1.15;
        font-weight:900;
      }

      #${PLAN_CARD_ID} .cb-plan-sub{
        margin-top:2px;
        color:#667085;
        font-size:.67rem;
      }

      #${PLAN_CARD_ID} .cb-plan-readonly{
        flex:0 0 auto;
        padding:5px 9px;
        border:1px solid #e4c46d;
        border-radius:999px;
        background:#fff8e7;
        color:#8b5c00;
        font-size:.62rem;
        font-weight:850;
        white-space:nowrap;
      }

      #${PLAN_CARD_ID} .cb-plan-body{
        padding:10px 11px 11px;
      }

      #${PLAN_CARD_ID} .cb-plan-empty{
        padding:18px 12px;
        border:1px dashed #d6dce4;
        border-radius:10px;
        background:#fafbfc;
        color:#667085;
        font-size:.8rem;
        text-align:center;
      }

      #${PLAN_CARD_ID} .cb-plan-innings{
        display:flex;
        gap:6px;
        overflow-x:auto;
        padding:1px 1px 3px;
        margin-bottom:9px;
        scrollbar-width:thin;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-btn{
        position:relative;
        flex:0 0 auto;
        min-width:48px;
        min-height:44px;
        padding:4px 10px;
        border:1.5px solid #cfd6df;
        border-radius:10px;
        background:#fff;
        color:#172033;
        font-size:1rem;
        font-weight:900;
        line-height:1.05;
        transition:none;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-btn[aria-pressed="true"]{
        border-color:#172033;
        background:#172033;
        color:#fff;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-btn small{
        display:block;
        font-size:var(--cb-text-2xs, 11px);
        font-weight:850;
        letter-spacing:.03em;
        text-transform:uppercase;
        color:#315d98;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-btn[aria-pressed="true"] small{
        color:#c9d7ef;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-title{
        color:#172033;
        font-size:.95rem;
        font-weight:900;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-title span{
        margin-left:6px;
        padding:2px 8px;
        border-radius:999px;
        background:#e8eef8;
        color:#1f3f6e;
        font-size:var(--cb-text-2xs, 11px);
        font-weight:900;
        letter-spacing:.05em;
        text-transform:uppercase;
        vertical-align:2px;
      }

      #${PLAN_CARD_ID} .cb-plan-changes{
        margin:3px 0 8px;
        color:#475467;
        font-size:var(--cb-text-xs, 12px);
        font-weight:750;
      }

      #${PLAN_CARD_ID} .cb-plan-changes.has-changes{
        color:#7a4b00;
      }

      #${PLAN_CARD_ID} .cb-plan-field{
        width:min(100%,640px);
        min-height:0;
        margin-inline:auto;
        aspect-ratio:1.28/1;
      }

      #${PLAN_CARD_ID} .cb-plan-spot{
        cursor:default;
        width:clamp(58px,17%,112px);
        min-height:40px;
      }

      /* A position that changed from the inning before: amber ring and dot. */
      #${PLAN_CARD_ID} .cb-plan-spot[data-plan-changed="true"] .cb-qd-name{
        border-color:#d18a00!important;
        box-shadow:0 0 0 2.5px #f5b83d, 0 2px 6px rgba(16,24,40,.22)!important;
      }

      #${PLAN_CARD_ID} .cb-plan-spot[data-plan-changed="true"] .cb-qd-pos::after{
        content:'';
        display:inline-block;
        width:7px;
        height:7px;
        margin-left:4px;
        border-radius:50%;
        background:#f5b83d;
        box-shadow:0 0 0 1.5px #fff;
        vertical-align:1px;
      }

      /* Where the game has gone its own way from the plan: a quiet
         team-colored dashed outline, and a small dot on the inning button.
         Amber stays reserved for changes inside the original plan. */
      #${PLAN_CARD_ID} .cb-plan-spot[data-plan-live-differs="true"] .cb-qd-name{
        outline:2px dashed var(--cb-primary-text, #1f3f6e);
        outline-offset:2px;
      }

      #${PLAN_CARD_ID} .cb-plan-live{
        margin:0 0 9px;
        padding:6px 10px 7px;
        border-left:3px solid var(--cb-primary-text, #1f3f6e);
        background:#f5f7fa;
        color:#172033;
        font-size:var(--cb-text-xs, 12px);
      }

      #${PLAN_CARD_ID} .cb-plan-live strong{
        display:block;
        margin-bottom:2px;
        color:var(--cb-primary-text, #1f3f6e);
        font-size:var(--cb-text-xs, 12px);
        font-weight:900;
      }

      #${PLAN_CARD_ID} .cb-plan-live ul{
        margin:0;
        padding:0;
        list-style:none;
      }

      #${PLAN_CARD_ID} .cb-plan-live li{
        font-weight:750;
        line-height:1.35;
      }

      #${PLAN_CARD_ID} .cb-plan-live li + li{
        margin-top:3px;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-btn[data-plan-live-differs="true"]::after{
        content:'';
        position:absolute;
        top:5px;
        right:5px;
        width:7px;
        height:7px;
        border-radius:50%;
        background:var(--cb-primary-text, #1f3f6e);
        box-shadow:0 0 0 1.5px #fff;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-btn[aria-pressed="true"][data-plan-live-differs="true"]::after{
        background:#fff;
        box-shadow:0 0 0 1.5px var(--cb-primary-text, #1f3f6e);
      }

      #${PLAN_CARD_ID} .cb-plan-bench{
        margin-top:9px;
        padding:8px 10px;
        border:1px solid #e3e7ec;
        border-radius:10px;
        background:#fafbfc;
      }

      #${PLAN_CARD_ID} .cb-plan-bench strong{
        display:block;
        margin-bottom:5px;
        color:#344054;
        font-size:var(--cb-text-xs, 12px);
        font-weight:900;
      }

      #${PLAN_CARD_ID} .cb-plan-bench-chips{
        display:flex;
        flex-wrap:wrap;
        gap:5px;
      }

      #${PLAN_CARD_ID} .cb-plan-bench-chips span{
        padding:4px 8px;
        border:1px solid #dce1e5;
        border-radius:999px;
        background:#fff;
        color:#172033;
        font-size:var(--cb-text-xs, 12px);
        font-weight:800;
      }

      @media(max-width:575.98px){
        #${PLAN_CARD_ID} .cb-plan-field{
          width:100%;
        }

        /* Wider than the live board's markers, and never narrower than the
           longest word in the name: the plan is not sharing the screen with
           End Inning, so names wrap between words, not inside them. */
        #${PLAN_CARD_ID} .cb-plan-spot{
          width:min-content!important;
          min-width:clamp(60px,21vw,84px);
          min-height:30px!important;
        }

        #${PLAN_CARD_ID} .cb-plan-spot .cb-qd-name{
          overflow-wrap:normal;
          word-break:normal;
        }

        #${PLAN_CARD_ID} .cb-plan-spot .cb-qd-name{
          font-size:var(--cb-marker-name)!important;
        }
      }

      #${CARD_ID}{
        border:1.5px solid #cfd6df;
        border-radius:14px;
        background:#fff;
        overflow:hidden;
        margin:0 0 10px;
        box-shadow:0 2px 7px rgba(16,24,40,.08);
      }

      #${CARD_ID}[hidden]{
        display:none!important;
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

      #${CARD_ID} .cb-next-sub{
        margin-top:2px;
        color:#667085;
        font-size:var(--cb-text-xs);
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

      #${CARD_ID} .cb-next-save.error{
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

      #cbNextOpenWarning{
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
      }

      #${CARD_ID} .cb-next-body{
        padding:10px 11px 11px;
      }

      #${CARD_ID} .cb-next-selection{
        min-height:42px;
        margin-bottom:8px;
        padding:9px 10px;
        border:1px solid #b9cbea;
        border-radius:10px;
        background:#f3f7fd;
        color:#344054;
        font-size:.72rem;
      }

      #${CARD_ID} .cb-next-selection.active{
        border:2px solid #315d98;
        background:#eef4ff;
        box-shadow:0 0 0 3px rgba(49,93,152,.12);
      }

      #${CARD_ID} .cb-next-selection.quiet{
        border-color:#e3e7ec;
        background:#fafbfc;
        color:#667085;
      }

      #${CARD_ID} .cb-next-step{
        color:#315d98;
        font-size:.59rem;
        font-weight:950;
        letter-spacing:.08em;
        text-transform:uppercase;
      }

      #${CARD_ID} .cb-next-selection-main{
        margin-top:2px;
        color:#172033;
        font-size:.79rem;
        font-weight:850;
      }

      #${CARD_ID} .cb-next-selection-sub{
        margin-top:2px;
        color:#667085;
        font-size:.66rem;
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
        background:#eaf1ff!important;
      }

      #${CARD_ID} .cb-next-destination .cb-qd-name{
        border:2px solid #4d75b3!important;
        box-shadow:
          0 0 0 3px rgba(77,117,179,.15),
          0 2px 5px rgba(16,24,40,.12)!important;
      }

      #${CARD_ID} .cb-next-destination .cb-qd-num{
        display:none;
      }

      #${CARD_ID} .cb-next-destination .cb-qd-pos::after{
        content:" · TAP HERE";
        color:#fff;
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

      #${CARD_ID} .cb-next-bench.destination-active{
        border:2px solid #4d75b3;
        background:#f3f7fd;
      }

      #${CARD_ID} .cb-next-send-bench{
        width:100%;
        min-height:44px;
        margin:0 0 8px;
        border:2px dashed #b5473d;
        border-radius:9px;
        background:#fff3f1;
        color:#912d28;
        font-size:.68rem;
        font-weight:900;
        letter-spacing:.02em;
        touch-action:manipulation;
      }

      #${CARD_ID} .cb-next-tools{
        display:flex;
        flex-wrap:wrap;
        gap:6px;
        align-items:center;
        margin-top:8px;
      }

      #${CARD_ID} .cb-next-tools .btn{
        min-height:38px;
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

        #${CARD_ID} .cb-next-selection{
          margin-bottom:6px;
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
       * carries its own heading, save chip and STEP instruction above the
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
            "selection selection"
            "field bench"
            "field tools"
            "field warnings"
            "error error";
          gap:8px 12px;
          align-items:start;
          padding:9px 11px 11px;
        }

        #${CARD_ID} .cb-next-selection{
          grid-area:selection;
          min-height:38px;
          margin-bottom:0;
          padding:7px 9px;
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
       * Short landscape screens (a 1024x768 iPad): the STEP 2 guidance spans
       * the full width above the field, and its Cancel button on a row of its
       * own pushed End Inning below the fold mid-move. Put Cancel beside the
       * text instead; the text itself keeps its size.
       */
      @media(
        min-width:700px
      ) and (
        min-height:500px
      ) and (
        max-height:800px
      ) and (
        orientation:landscape
      ){
        #${CARD_ID} .cb-next-selection.active{
          display:grid;
          grid-template-columns:minmax(0,1fr) auto;
          column-gap:12px;
          align-items:center;
        }

        #${CARD_ID} .cb-next-selection.active > :not([data-next-cancel]){
          grid-column:1;
        }

        #${CARD_ID} .cb-next-selection.active [data-next-cancel]{
          grid-column:2;
          grid-row:1 / span 3;
          margin-top:0!important;
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
        'Defense on the field, next inning, and the pregame plan'
      );

      switcher.innerHTML = `
        <button
          type="button"
          class="btn"
          data-now-next="now"
        >On the Field</button>
        <button
          type="button"
          class="btn"
          data-now-next="next"
        >Next Inning</button>
        <button
          type="button"
          class="btn"
          data-now-next="plan"
        >Pregame Plan</button>`;

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

          activeView =
            requested === 'next' || requested === 'plan'
              ? requested
              : 'now';

          // Only toggles visibility. Pregame Plan is reference data that is
          // already in `latest`, so opening it must never fetch or save --
          // but it is drawn now rather than on the next background refresh.
          applyView();

          if (activeView === 'plan' && latest) {
            ensureSurface();
            renderPlanCard();
          }
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

  function syncUpcomingInningLabels() {
    const inning = upcomingInning();
    const inningLabel = inningOrdinal(inning);
    const currentLabel = inningOrdinal(
      latest?.current_inning || ''
    );

    const nextTab = $(SWITCH_ID)
      ?.querySelector(
        '[data-now-next="next"]'
      );

    const tabText = inningLabel
      ? `${inningLabel} Inning`
      : 'Next Inning';

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

    const noteText = `${inningLabel} inning defense`;

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

    syncUpcomingInningLabels();

    if (actionSlot) {
      actionSlot.removeAttribute('hidden');
    }

    if (endInning) {
      endInning.removeAttribute('hidden');
      if (endInning.classList.contains('d-none')) {
        endInning.classList.remove('d-none');
      }
    }

    // On the Field owns two live actions. NEXT and Pregame Plan hide
    // Change Pitcher, so their phone dock should become one full-width
    // End Inning action instead of leaving an empty grid column.
    actionSlot?.classList.toggle(
      'cb-single-live-action',
      activeView === 'next' || activeView === 'plan'
    );

    // NEXT edits pitcher directly on the defensive board, and Pregame Plan
    // is a reference view that must offer no way to change anything.
    if (changePitcher) {
      if (activeView === 'next' || activeView === 'plan') {
        changePitcher.style.setProperty(
          'display',
          'none',
          'important'
        );
      } else {
        changePitcher.style.removeProperty('display');
      }
    }

    // Keep the canonical Undo button in its original DOM location.
    // NEXT only controls whether that button can currently be used;
    // Pregame Plan has nothing of its own to undo.
    if (undo) {
      if (activeView === 'plan') {
        undo.disabled = true;
      } else {
        undo.disabled =
          activeView === 'next'
            ? !undoStack.length
            : false;
      }
    }

    syncOpenDefenseWarning(endInning);
  }

  // End Inning starts the next inning with the Next Inning defense, so an
  // open spot there is worth seeing before tapping it -- including on a
  // phone, where the card's own warning sits below the fixed action dock.
  function syncOpenDefenseWarning(endInning) {
    const open = latest ? openPositions() : [];
    let warning = $('cbNextOpenWarning');

    if (!endInning || !open.length) {
      warning?.remove();
      document.body.classList.remove('cb-next-open-warning');
      return;
    }

    if (!warning) {
      warning = document.createElement('div');
      warning.id = 'cbNextOpenWarning';
      warning.setAttribute('role', 'status');
    }

    if (warning.nextElementSibling !== endInning) {
      endInning.parentNode.insertBefore(warning, endInning);
    }

    const text =
      `⚠ Next inning: ${open.join(', ')} ` +
      `${open.length === 1 ? 'is' : 'are'} open`;

    if (warning.textContent !== text) {
      warning.textContent = text;
    }

    document.body.classList.add('cb-next-open-warning');
  }

  function applyView() {
    const switcher = $(SWITCH_ID);
    const now = $('cbQuickDefense');
    const next = $(CARD_ID);
    const plan = $(PLAN_CARD_ID);

    switcher
      ?.querySelectorAll('[data-now-next]')
      .forEach(button => {
        const isActive =
          button.dataset.nowNext === activeView;

        button.classList.toggle(
          'active',
          isActive
        );

        button.setAttribute(
          'aria-pressed',
          isActive ? 'true' : 'false'
        );
      });

    if (now) {
      now.hidden = activeView !== 'now';
    }

    if (next) {
      next.hidden = activeView !== 'next';
    }

    if (plan) {
      plan.hidden = activeView !== 'plan';
    }

    syncLiveActions();
  }

  function planInnings() {
    const plan = latest?.pregame_rotation || {};

    return Object.keys(plan)
      .map(key => ({
        key,
        sort: Number.parseFloat(key),
        alignment: plan[key] || {},
      }))
      .filter(entry =>
        Number.isFinite(entry.sort) &&
        Object.values(entry.alignment).some(name => name)
      )
      .sort((a, b) => a.sort - b.sort);
  }

  function planSpot(pos, left, top, name, changed, live) {
    const number = name
      ? String(playerByName(name)?.number ?? '').trim()
      : '';

    return `
      <div
        class="cb-qd-spot cb-plan-spot ${pos === 'P' ? 'pitcher' : ''}"
        style="left:${left}%;top:${top}%"
        data-plan-position="${esc(pos)}"
        data-plan-changed="${changed ? 'true' : 'false'}"
        data-plan-live-differs="${live ? 'true' : 'false'}"
        role="img"
        aria-label="${esc(
          `${pos}: ${name ? playerLabel(name) : 'open'}`
          + `${changed ? ', changed from the inning before' : ''}`
          + `${live ? `, in the game: ${live.name ? playerLabel(live.name) : 'open'}` : ''}`
        )}"
      >
        <span class="cb-qd-pos">${esc(pos)}${number ? ` <span class="cb-qd-num">#${esc(number)}</span>` : ''}</span>
        <span class="cb-qd-name">${esc(name || 'OPEN')}</span>
      </div>`;
  }

  /*
   * The defense the live game is actually using for a planned inning:
   *   - the inning being played: the field right now;
   *   - the next inning: what End Inning would put out (the carried-forward
   *     field, the plan, or the coach's own Next Inning edit);
   *   - an inning already played: the defense it ended with.
   * Later innings and planned mid-inning changes have none yet.
   */
  function liveAlignmentFor(key) {
    if (!latest || String(key).includes('.')) return null;

    const current = String(latest.current_inning || '');

    if (key === current) return latest.current_alignment || null;
    if (key === String(latest.next_inning || '')) {
      return latest.confirmed?.alignment || null;
    }

    const inning = Number.parseFloat(key);
    const playing = Number.parseFloat(current);

    return Number.isFinite(inning) && Number.isFinite(playing) && inning < playing
      ? latest.actual_rotation?.[key] || null
      : null;
  }

  function liveDeviations(entry, order) {
    const live = liveAlignmentFor(entry.key);

    if (!live) return [];

    return order
      .filter(pos => (entry.alignment[pos] || '') !== (live[pos] || ''))
      .map(pos => ({pos, name: live[pos] || '', planned: entry.alignment[pos] || ''}));
  }

  /*
   * One line per position, in plain baseball terms. These compare the plan
   * with the defense on the field (or the one End Inning would put out) --
   * they do not know the order moves were made in, so they state what is,
   * not a story of how it happened ("came in", "moved", "switched").
   */
  function deviationLine(item, kind) {
    const spot = item.pos === 'P'
      ? 'on the mound'
      : ['LF', 'CF', 'RF', 'LCF', 'RCF'].includes(item.pos)
        ? `in ${item.pos}`
        : `at ${item.pos}`;

    if (!item.name) {
      return `${item.pos} open (plan: ${item.planned || 'open'})`;
    }

    if (!item.planned) {
      return `${item.name} ${spot} (plan: open)`;
    }

    if (item.pos === 'P') {
      return `${item.name} ${kind === 'done' ? 'pitched' : 'pitching'} instead of ${item.planned}`;
    }

    return `${item.name} ${spot} instead of ${item.planned}`;
  }

  function deviationHeading(key) {
    if (key === String(latest?.current_inning || '')) {
      // Edits the coach said were made before the inning began are setup,
      // not in-game adjustments (live_history.py).
      return latest?.current_inning_setup_only
        ? `Defense for the ${inningOrdinal(key)}`
        : 'In-game adjustments';
    }
    if (key === String(latest?.next_inning || '')) return `Heading into the ${inningOrdinal(key)}`;
    return `How the ${inningOrdinal(key)} finished`;
  }

  function planInningLabel(key) {
    return String(key).includes('.')
      ? `Change during Inning ${Math.floor(Number.parseFloat(key))}`
      : `Inning ${key}`;
  }

  function renderPlanCard() {
    const card = $(PLAN_CARD_ID);

    if (!card) return;

    const innings = planInnings();
    let html;

    if (!innings.length) {
      html = `
        <div class="cb-plan-head">
          <div>
            <div class="cb-plan-kicker">PREGAME PLAN</div>
            <div class="cb-plan-title">Pregame Defense</div>
          </div>
          <div class="cb-plan-readonly">Reference only</div>
        </div>
        <div class="cb-plan-body">
          <div class="cb-plan-empty">
            No pregame defensive plan was saved for this game.
          </div>
        </div>`;
    } else {
      const currentInning = String(latest?.current_inning || '');
      const nextInning = String(latest?.next_inning || '');
      const keys = innings.map(entry => entry.key);

      // Open on the next inning -- usually what a coach wants mid-game --
      // and keep the coach's choice until the live inning moves on.
      if (
        planChoice.during !== currentInning ||
        !keys.includes(planChoice.inning)
      ) {
        planChoice = {
          inning:
            [nextInning, currentInning].find(key => keys.includes(key)) ||
            keys[0],
          during: currentInning,
        };
      }

      const index = keys.indexOf(planChoice.inning);
      const entry = innings[index];
      const previous = index > 0 ? innings[index - 1] : null;
      const order = positions(latest?.outfielder_count);
      const changed = previous
        ? order.filter(pos =>
            (entry.alignment[pos] || '') !== (previous.alignment[pos] || '')
          )
        : [];

      const deviations = liveDeviations(entry, order);
      const liveAt = pos => deviations.find(item => item.pos === pos) || null;

      const assigned = new Set(
        order.map(pos => entry.alignment[pos]).filter(Boolean)
      );
      const bench = (latest?.roster || [])
        .filter(player => !assigned.has(player.name))
        .sort((a, b) => a.name.localeCompare(b.name));

      const tag = entry.key === currentInning
        ? 'On now'
        : entry.key === nextInning
          ? 'Next inning'
          : '';

      const buttons = innings.map(item => `
        <button
          type="button"
          class="cb-plan-inning-btn"
          data-plan-inning="${esc(item.key)}"
          data-plan-live-differs="${liveDeviations(item, order).length ? 'true' : 'false'}"
          aria-pressed="${item.key === entry.key ? 'true' : 'false'}"
          aria-label="${esc(planInningLabel(item.key))}${item.key === currentInning ? ' (on now)' : ''}"
        >${esc(item.key.includes('.') ? `${Math.floor(Number.parseFloat(item.key))}+` : item.key)}${
          item.key === currentInning ? '<small>Now</small>' : ''
        }</button>`).join('');

      const field = `
        <div class="cb-qd-field cb-plan-field">
          ${fieldArt()}
          ${spots().map(([pos, left, top]) =>
            planSpot(pos, left, top, entry.alignment[pos] || '', changed.includes(pos), liveAt(pos))
          ).join('')}
        </div>`;

      html = `
        <div class="cb-plan-head">
          <div>
            <div class="cb-plan-kicker">
              PREGAME PLAN · ${esc(String(innings.length))} ${
                innings.length === 1 ? 'INNING' : 'INNINGS'
              }
            </div>
            <div class="cb-plan-title">Pregame Defense</div>
            <div class="cb-plan-sub">
              What you set before first pitch. Nothing here changes the live game.
            </div>
          </div>
          <div class="cb-plan-readonly">Reference only</div>
        </div>
        <div class="cb-plan-body">
          <div class="cb-plan-innings" aria-label="Planned innings">${buttons}</div>
          <div class="cb-plan-inning-title">
            ${esc(planInningLabel(entry.key))}${tag ? `<span>${esc(tag)}</span>` : ''}
          </div>
          <div class="cb-plan-changes${changed.length ? ' has-changes' : ''}">${
            previous
              ? changed.length
                ? `Changed from ${esc(planInningLabel(previous.key))}: ${esc(changed.join(', '))}`
                : `Same as ${esc(planInningLabel(previous.key))}`
              : 'First inning of the plan'
          }</div>
          ${
            deviations.length
              ? `<div class="cb-plan-live">
                  <strong>${esc(deviationHeading(entry.key))}</strong>
                  <ul>${deviations.map(item => `<li>${esc(deviationLine(
                    item,
                    entry.key === String(latest?.current_inning || '') ||
                      entry.key === String(latest?.next_inning || '')
                      ? 'live'
                      : 'done'
                  ))}</li>`).join('')}</ul>
                </div>`
              : ''
          }
          ${field}
          <div class="cb-plan-bench">
            <strong>Bench · ${bench.length}</strong>
            <div class="cb-plan-bench-chips">${
              bench.length
                ? bench.map(player => `<span>${esc(playerLabel(player.name))}</span>`).join('')
                : '<span>Nobody</span>'
            }</div>
          </div>
        </div>`;
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
        const button = event.target.closest('[data-plan-inning]');

        if (!button) return;

        planChoice = {
          inning: button.dataset.planInning,
          during: String(latest?.current_inning || ''),
        };
        renderPlanCard();
      });
    }
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
        <div>
          <div class="cb-next-title">
            ${esc(inningLabel)} Inning Defense
          </div>
          <div class="cb-next-sub">
            ${esc(planStateText())}
          </div>
          ${pitcherStatusMarkup()}
        </div>

        <div
          class="cb-next-save ${esc(saveMode)}"
          data-next-save-state
          role="status"
        >${esc(saveMessage)}</div>
      </div>

      <div class="cb-next-body">
        ${selectionHelp()}

        ${fieldMarkup()}

        ${benchMarkup()}

        <div class="cb-next-tools">
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
          () => {
            const name =
              button.dataset.nextBenchPlayer || '';

            if (!name) return;

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
      .querySelector('[data-next-cancel]')
      ?.addEventListener(
        'click',
        () => {
          selected = null;
          selectedPosition = '';
          renderCard();
        }
      );

    card
      .querySelector('[data-next-use-current]')
      ?.addEventListener(
        'click',
        useCurrentDefense
      );

    card
      .querySelector('[data-next-bench-selected]')
      ?.addEventListener(
        'click',
        () => {
          if (!selected) return;

          movePlayerToBench(
            selected.name,
            selected.source
          );
        }
      );

    applyView();
  }

  // Update the save badge and notice in place. The queue finishes saves in
  // the background while the coach keeps tapping, so it must not rebuild
  // the board under a finger mid-tap just to change a status word.
  function renderSyncState() {
    const card = $(CARD_ID);
    const badge = card?.querySelector('[data-next-save-state]');
    const notice = card?.querySelector('[data-next-notice]');

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
      pushUndo = true,
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

    if (pushUndo) {
      undoStack.push(before);

      if (undoStack.length > 12) {
        undoStack.shift();
      }
    }

    draft = after;
    pendingMode = mode;
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
        serverBase = normalize(data?.confirmed?.alignment || sent);

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
    }
  }

  // The server's Next Inning defense moved on (another coach, a new inning)
  // while this board had changes waiting. Never overwrite it: drop the
  // waiting changes and show what the server has now.
  async function resolveConflict() {
    dirty = false;
    undoStack = [];
    conflictCount += 1;

    let data = null;

    try {
      data = await api('GET');
    } catch (_) {
      data = null;
    }

    // A tap made while that read was out is part of the replay being
    // stopped; the board below is the server's.
    dirty = false;
    dragSurface?.cancel();

    if (data) {
      lastSignature = JSON.stringify(data);
      hydrate(data, {remote: false});
    } else {
      // Show the last defense the server confirmed until the poll can
      // read the new one.
      lastSignature = '';
      draft = normalize(serverBase || {});
      renderCard();
    }

    noticeMessage =
      'The Next Inning defense changed on another device before your ' +
      'change could sync. Showing the latest defense — check it before ' +
      'ending the inning.';
    successMessage = 'Saved ✓';
    setSyncState('saved');
    renderSyncState();
  }

  // The server refused the change itself (for example, a player who is no
  // longer available). Put the board back to what the server has.
  function rejectLocalChange(error) {
    dirty = false;
    undoStack = [];
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

    if (conflictCount !== conflictsBefore) {
      throw new Error(
        'The Next Inning defense changed on another device. Check it, then try ending the inning again.'
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
        noticeMessage = 'Defense updated by another coach.';
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
    const today =
      daily === null || daily === undefined
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

  function undoNext() {
    if (!undoStack.length) return Promise.resolve();

    return commitLocalChange(
      undoStack.pop(),
      {
        pushUndo: false,
        message: 'Restored ✓',
      }
    );
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
        noticeMessage = 'Defense updated by another coach.';
      }

      // An unfinished displacement question was about the old plan.
      if (discardOpenChain()) {
        noticeMessage = 'Defense updated by another coach.';
      }

      draft = incoming;
      undoStack = [];
      selected = null;
      selectedPosition = '';
    }

    if (saveMode !== 'error') {
      successMessage = 'Saved ✓';
      setSyncState('saved');
    }

    renderCard();

    return true;
  }

  async function refresh({
    force = false,
  } = {}) {
    // The queue owns the board while a save is in the air; its answer is
    // newer than anything this read could return.
    if (activeSavePromise) return null;

    const revision = localRevision;

    try {
      const data = await api('GET');

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
    liveChangeTimer = window.setTimeout(() => refresh(), 150);
  }

  function afterAdvance() {
    activeView = 'now';
    selected = null;
    selectedPosition = '';
    undoStack = [];
    errorMessage = '';
    noticeMessage = '';
    serverBase = null;
    dirty = false;
    lastSignature = '';
    applyView();

    window.setTimeout(
      () => refresh({force: true}),
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
          refresh();
        }
      }
    );
  }

  window.CBNextDefense = {
    refresh: () => refresh({force: true}),
    useSame: useCurrentDefense,
    undo: undoNext,
    getAlignment: () => snapshot(),
    flush: flushPendingSave,
    isSaveInFlightOrQueued,
    showError,
    clearError,
    afterAdvance,
    showNext: () => {
      activeView = 'next';
      applyView();
    },
    showNow: () => {
      activeView = 'now';
      applyView();
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
      } else {
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

    window.setTimeout(
      () => refresh({force: true}),
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
    });

    // Back online: read the server now instead of at the next poll, which
    // also sends any Next Inning changes still waiting to sync.
    window.addEventListener('online', () => refresh());

    registerDragSurface();

    window.addEventListener(
      'click',
      event => {
        const undo = event.target.closest?.(
          '#liveUndoBtn'
        );

        if (
          !undo ||
          activeView !== 'next'
        ) {
          return;
        }

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        if (undoStack.length) {
          undoNext();
        }
      },
      true
    );
  };

  document.readyState === 'loading'
    ? document.addEventListener(
        'DOMContentLoaded',
        start,
        {once: true}
      )
    : start();
})();
