(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);

  const CARD_ID = 'live-board-prep-v3';
  const SWITCH_ID = 'cb-now-next-switch';
  const STYLE_ID = 'live-next-defense-styles';

  let latest = null;
  let draft = {};
  let activeView = 'now';
  let selected = null;
  let selectedPosition = '';
  let busy = false;
  let lastSignature = '';
  let saveMode = 'saved';
  let saveMessage = 'Saved ✓';
  let errorMessage = '';
  let undoStack = [];
  let socketBound = false;

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

    if (!items.length) {
      items.push(
        '<div class="cb-next-ready">✓ NEXT is ready</div>'
      );
    }

    return items.join('');
  }

  function planStateText() {
    const source = latest?.confirmed?.source || '';

    if (source === 'planned') {
      return 'Loaded from your pregame plan';
    }

    if (source === 'current') {
      return 'Matches current defense';
    }

    return 'NEXT edited';
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

    if (selectedPosition) {
      return `
        <div class="cb-next-selection active" role="status" aria-live="polite">
          <div class="cb-next-step">STEP 2 · CHOOSE PLAYER</div>
          <div class="cb-next-selection-main">
            Who should play <strong>${esc(selectedPosition)}</strong>?
          </div>
          <div class="cb-next-selection-sub">
            Tap a player on the field or bench.
          </div>
          <button
            type="button"
            class="btn btn-sm btn-outline-secondary mt-2"
            data-next-cancel
          >Cancel move</button>
        </div>`;
    }

    return `
      <div class="cb-next-selection quiet">
        <div class="cb-next-step">STEP 1</div>
        <div class="cb-next-selection-main">
          Tap the player you want to move.
        </div>
      </div>`;
  }

  function fieldSpot(pos, left, top) {
    const name = draft?.[pos] || '';
    const isOpen = !name;

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
        <span class="cb-qd-pos">${esc(pos)}</span>
        <span class="cb-qd-name">
          ${esc(isOpen ? 'OPEN' : playerLabel(name))}
        </span>
      </button>`;
  }

  function fieldMarkup() {
    return `
      <div class="cb-qd-field cb-next-field">
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
        </svg>

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

  function installStyles() {
    if ($(STYLE_ID)) return;

    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${SWITCH_ID}{
        display:grid;
        grid-template-columns:1fr 1fr;
        gap:4px;
        padding:4px;
        margin:0 0 8px;
        border:1px solid #d7dde5;
        border-radius:12px;
        background:#e9edf2;
      }

      #${SWITCH_ID} .btn{
        min-height:42px;
        border:0!important;
        border-radius:9px!important;
        background:transparent;
        color:#475467;
        font-weight:900;
        box-shadow:none!important;
      }

      #${SWITCH_ID} .btn.active{
        background:#172033!important;
        color:#fff!important;
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

      #${CARD_ID} .cb-next-kicker{
        color:#667085;
        font-size:.6rem;
        font-weight:900;
        text-transform:uppercase;
        letter-spacing:.09em;
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
        font-size:.67rem;
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
        font-size:.62rem;
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
        color:#7b8492;
        font-size:.59rem;
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
        font-size:.68rem;
        font-weight:820;
      }

      #${CARD_ID} .cb-next-warnings{
        margin-top:8px;
        display:grid;
        gap:5px;
      }

      #${CARD_ID} .cb-next-warning,
      #${CARD_ID} .cb-next-ready{
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

      #${CARD_ID} .cb-next-ready{
        border:1px solid #b8ddc4;
        background:#edf8f1;
        color:#176b38;
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
        }

        #${CARD_ID} .cb-qd-name{
          font-size:.56rem!important;
          padding:3px 4px!important;
        }

        #${CARD_ID} .cb-next-bench-player{
          min-height:36px;
          padding:5px 7px;
          font-size:.64rem;
        }

        #${CARD_ID} .cb-next-selection{
          margin-bottom:6px;
        }
      }

      @media(min-width:576px) and (max-width:899.98px){
        #${CARD_ID} .cb-next-field{
          width:min(100%,680px);
        }
      }

      @media(
        min-width:700px
      ) and (
        min-height:500px
      ) and (
        orientation:landscape
      ){
        #${CARD_ID} .cb-next-field{
          width:min(
            100%,
            760px,
            calc(60dvh * 1.28)
          );
        }

        #${CARD_ID} .cb-next-head{
          padding-top:8px;
          padding-bottom:7px;
        }

        #${CARD_ID} .cb-next-selection{
          min-height:38px;
          padding:7px 9px;
        }

        #${CARD_ID} .cb-next-bench{
          margin-top:6px;
          padding:7px;
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
    `;

    document.head.appendChild(style);
  }

  async function api(method = 'GET', body = null) {
    const response = await fetch(
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

    const data = await response.json().catch(() => ({}));

    if (!response.ok || data.status === 'error') {
      throw new Error(
        data.message ||
        `Unable to save NEXT (${response.status}).`
      );
    }

    return data;
  }

  function ensureSurface() {
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
        'Defense on the field and next inning'
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
        >Next Inning</button>`;

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

          activeView =
            button.dataset.nowNext === 'next'
              ? 'next'
              : 'now';

          applyView();
        }
      );
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

    $('live-up-next-v2')?.remove();
    $('next-inning-adjust-modal')?.remove();

    applyView();

    return card;
  }

  function syncLiveActions() {
    const changePitcher = $('liveChangePitcherBtn');
    const undo = $('liveUndoBtn');

    // NEXT edits pitcher directly on the defensive board.
    if (changePitcher) {
      if (activeView === 'next') {
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
    // NEXT only controls whether that button can currently be used.
    if (undo) {
      undo.disabled =
        activeView === 'next'
          ? busy || !undoStack.length
          : false;
    }
  }

  function applyView() {
    const switcher = $(SWITCH_ID);
    const now = $('cbQuickDefense');
    const next = $(CARD_ID);

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

    syncLiveActions();
  }

  function renderCard() {
    const card = ensureSurface();

    if (!card || !latest) return;

    const inning = String(
      latest.next_inning || ''
    );

    card.innerHTML = `
      <div class="cb-next-head">
        <div>
          <div class="cb-next-kicker">
            NEXT INNING · ${esc(inning)}
          </div>
          <div class="cb-next-title">
            Next Defense
          </div>
          <div class="cb-next-sub">
            ${esc(planStateText())}
          </div>
        </div>

        <div class="cb-next-save ${esc(saveMode)}">
          ${esc(saveMessage)}
        </div>
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
            ${busy ? 'disabled' : ''}
          >
            Use current defense
          </button>

        </div>

        <div class="cb-next-warnings">
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

            if (busy) return;

            if (selected) {
              movePlayer(
                selected.name,
                selected.source,
                pos
              );
              return;
            }

            if (selectedPosition && name) {
              movePlayer(
                name,
                pos,
                selectedPosition
              );
              return;
            }

            if (name) {
              selected = {
                name,
                source: pos,
              };
              selectedPosition = '';
            } else {
              selected = null;
              selectedPosition = pos;
            }

            renderCard();
          }
        );
      });

    card
      .querySelectorAll('[data-next-bench-player]')
      .forEach(button => {
        button.addEventListener(
          'click',
          () => {
            if (busy) return;

            const name =
              button.dataset.nextBenchPlayer || '';

            if (!name) return;

            if (selectedPosition) {
              movePlayer(
                name,
                'BENCH',
                selectedPosition
              );
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

          const next = snapshot();

          if (
            selected.source !== 'BENCH'
          ) {
            next[selected.source] = '';
          }

          saveAlignment(
            next,
            {
              successMessage:
                `${playerLabel(selected.name)} → BENCH`,
            }
          );
        }
      );

    applyView();
  }

  async function saveAlignment(
    next,
    {
      mode = 'custom',
      pushUndo = true,
      successMessage = 'NEXT saved ✓',
    } = {}
  ) {
    if (busy) return null;

    const before = snapshot();

    busy = true;
    saveMode = 'saving';
    saveMessage = 'Saving…';
    errorMessage = '';
    draft = normalize(next);

    renderCard();

    try {
      const data = await api(
        'POST',
        mode === 'current'
          ? {mode: 'current'}
          : {
              mode: 'custom',
              alignment: draft,
            }
      );

      if (pushUndo) {
        undoStack.push(before);

        if (undoStack.length > 12) {
          undoStack.shift();
        }
      }

      latest = data;
      draft = normalize(
        data?.confirmed?.alignment ||
        draft
      );

      selected = null;
      selectedPosition = '';

      saveMode = 'saved';
      saveMessage = successMessage;
      errorMessage = '';
      lastSignature = JSON.stringify(data);

      renderCard();

      document.dispatchEvent(
        new CustomEvent(
          'coachboard:next-defense-set',
          {detail: {data}}
        )
      );

      return data;
    } catch (error) {
      draft = before;

      selected = null;
      selectedPosition = '';

      saveMode = 'error';
      saveMessage = 'Not saved';
      errorMessage =
        error.message ||
        'Unable to save NEXT.';

      renderCard();

      return null;
    } finally {
      busy = false;
      renderCard();
    }
  }

  function movePlayer(
    name,
    source,
    target
  ) {
    if (
      busy ||
      !name ||
      !target ||
      source === target
    ) {
      selected = null;
      selectedPosition = '';
      renderCard();
      return;
    }

    const next = snapshot();
    const occupant = next[target] || '';

    if (
      source &&
      source !== 'BENCH'
    ) {
      next[source] = '';
    }

    next[target] = name;

    if (
      occupant &&
      occupant !== name
    ) {
      if (
        target !== 'P' &&
        source &&
        source !== 'BENCH'
      ) {
        // Normal field-to-field move:
        // true two-player swap.
        next[source] = occupant;
      }

      // Bench -> field sends the old occupant to the bench.
      // Moving someone to P also sends the old pitcher to the bench.
    }

    saveAlignment(
      next,
      {
        successMessage:
          `${playerLabel(name)} → ${target} ✓`,
      }
    );
  }

  async function useCurrentDefense() {
    if (busy || !latest) return;

    const next = normalize(
      latest.current_alignment || {}
    );

    await saveAlignment(
      next,
      {
        mode: 'current',
        successMessage:
          'Current defense copied to NEXT ✓',
      }
    );
  }

  async function undoNext() {
    if (busy || !undoStack.length) return;

    const previous = undoStack.pop();
    const current = snapshot();

    busy = true;
    saveMode = 'saving';
    saveMessage = 'Undoing…';
    errorMessage = '';
    draft = normalize(previous);

    renderCard();

    try {
      const data = await api(
        'POST',
        {
          mode: 'custom',
          alignment: draft,
        }
      );

      latest = data;
      draft = normalize(
        data?.confirmed?.alignment ||
        draft
      );

      selected = null;
      selectedPosition = '';

      saveMode = 'saved';
      saveMessage = 'NEXT restored ✓';
      lastSignature = JSON.stringify(data);

      renderCard();

      document.dispatchEvent(
        new CustomEvent(
          'coachboard:next-defense-set',
          {detail: {data}}
        )
      );
    } catch (error) {
      undoStack.push(previous);
      draft = current;

      saveMode = 'error';
      saveMessage = 'Undo failed';
      errorMessage =
        error.message ||
        'Unable to undo NEXT.';

      renderCard();
    } finally {
      busy = false;
      renderCard();
    }
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

  function hydrate(data) {
    latest = data;

    if (
      !data ||
      data.status === 'inactive' ||
      data.is_live === false
    ) {
      $(SWITCH_ID)?.remove();
      $(CARD_ID)?.remove();

      const now = $('cbQuickDefense');

      if (now) {
        now.hidden = false;
      }

      return false;
    }

    draft = normalize(
      data?.confirmed?.alignment ||
      data?.current_alignment ||
      {}
    );

    selected = null;
    selectedPosition = '';

    if (saveMode !== 'error') {
      saveMode = 'saved';
      saveMessage = 'Saved ✓';
    }

    renderCard();

    return true;
  }

  async function refresh({
    force = false,
  } = {}) {
    if (busy) return null;

    try {
      const data = await api('GET');
      const signature = JSON.stringify(data);

      if (
        force ||
        signature !== lastSignature ||
        !$(CARD_ID)
      ) {
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

  function afterAdvance() {
    activeView = 'now';
    selected = null;
    selectedPosition = '';
    undoStack = [];
    errorMessage = '';
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
          lastSignature = '';
          refresh({force: true});
        }
      }
    );
  }

  window.CBNextDefense = {
    refresh: () => refresh({force: true}),
    useSame: useCurrentDefense,
    undo: undoNext,
    getAlignment: () => snapshot(),
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

  const start = () => {
    $('next-inning-adjust-modal')?.remove();

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

        if (!busy && undoStack.length) {
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
