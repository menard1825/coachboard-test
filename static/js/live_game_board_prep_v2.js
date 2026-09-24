(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);

  const CARD_ID = 'live-board-prep-v3';
  const PLAN_CARD_ID = 'live-board-pregame-plan';
  const SWITCH_ID = 'cb-now-next-switch';
  const STYLE_ID = 'live-next-defense-styles';

  let latest = null;
  let draft = {};
  let activeView = 'now';
  let selected = null;
  let selectedPosition = '';
  let busy = false;
  let activeSavePromise = null;
  let lastSignature = '';
  let saveMode = 'saved';
  let saveMessage = 'Saved ✓';
  let errorMessage = '';
  let undoStack = [];
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

      #${PLAN_CARD_ID} .cb-plan-inning{
        margin-bottom:9px;
        padding:9px 10px 10px;
        border:1px solid #e3e7ec;
        border-radius:10px;
        background:#fafbfc;
      }

      #${PLAN_CARD_ID} .cb-plan-inning:last-child{
        margin-bottom:0;
      }

      #${PLAN_CARD_ID} .cb-plan-inning.current{
        border:2px solid #315d98;
        background:#f3f7fd;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-head{
        display:flex;
        align-items:baseline;
        gap:8px;
        margin-bottom:7px;
      }

      #${PLAN_CARD_ID} .cb-plan-inning-no{
        color:#172033;
        font-size:.86rem;
        font-weight:900;
      }

      #${PLAN_CARD_ID} .cb-plan-now{
        padding:2px 7px;
        border-radius:999px;
        background:#172033;
        color:#fff;
        font-size:.56rem;
        font-weight:900;
        letter-spacing:.07em;
        text-transform:uppercase;
      }

      #${PLAN_CARD_ID} .cb-plan-grid{
        display:grid;
        grid-template-columns:repeat(auto-fill,minmax(94px,1fr));
        gap:6px;
      }

      #${PLAN_CARD_ID} .cb-plan-slot{
        padding:5px 7px;
        border:1px solid #dce1e5;
        border-radius:8px;
        background:#fff;
        min-width:0;
      }

      #${PLAN_CARD_ID} .cb-plan-pos{
        display:block;
        color:var(--cb-muted);
        font-size:.55rem;
        font-weight:900;
        letter-spacing:.06em;
      }

      #${PLAN_CARD_ID} .cb-plan-name{
        display:block;
        margin-top:1px;
        color:#172033;
        font-size:.68rem;
        font-weight:800;
        line-height:1.12;
        overflow-wrap:anywhere;
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
          // already in `latest`, so opening it must never fetch or save.
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

    if (nextTab) {
      nextTab.textContent = inningLabel
        ? `${inningLabel} Inning`
        : 'Next Inning';
    }

    if (!inningLabel) return;

    const endInning =
      $('liveEndInningBtn');

    if (!endInning) return;

    const title =
      endInning.querySelector(
        '.coach-action-title'
      );

    const note =
      endInning.querySelector(
        '.coach-action-note'
      );

    const buttonTitle = currentLabel
      ? `End ${currentLabel} → Start ${inningLabel}`
      : `Start ${inningLabel}`;

    if (title) {
      title.textContent = buttonTitle;
    } else {
      endInning.textContent = buttonTitle;
    }

    if (note) {
      note.textContent =
        `${inningLabel} inning defense`;
    }

    endInning.setAttribute(
      'aria-label',
      currentLabel
        ? `End ${currentLabel} inning and start ${inningLabel}`
        : `Start ${inningLabel} inning`
    );
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
      endInning.classList.remove('d-none');
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
            ? busy || !undoStack.length
            : false;
      }
    }
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

  function renderPlanCard() {
    const card = $(PLAN_CARD_ID);

    if (!card) return;

    const innings = planInnings();

    if (!innings.length) {
      card.innerHTML = `
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

      return;
    }

    const currentInning = String(latest?.current_inning || '');
    const order = positions(latest?.outfielder_count);

    const blocks = innings.map(entry => {
      const isCurrent = entry.key === currentInning;

      const slots = order.map(pos => {
        const name = entry.alignment[pos] || '';

        return `
          <div class="cb-plan-slot">
            <span class="cb-plan-pos">${esc(pos)}</span>
            <span class="cb-plan-name">${
              esc(name ? playerLabel(name) : '—')
            }</span>
          </div>`;
      }).join('');

      return `
        <section class="cb-plan-inning${isCurrent ? ' current' : ''}">
          <div class="cb-plan-inning-head">
            <span class="cb-plan-inning-no">Inning ${esc(entry.key)}</span>
            ${isCurrent ? '<span class="cb-plan-now">On now</span>' : ''}
          </div>
          <div class="cb-plan-grid">${slots}</div>
        </section>`;
    }).join('');

    card.innerHTML = `
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
      <div class="cb-plan-body">${blocks}</div>`;
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
            ${
              currentLabel
                ? `Use ${esc(currentLabel)} Inning Defense`
                : 'Use Current Defense'
            }
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

          movePlayerToBench(
            selected.name,
            selected.source
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
      successMessage = 'Saved ✓',
    } = {}
  ) {
    // NEXT currently blocks board interaction while a save is running, so
    // there should only be one writer from this surface at a time. Keep the
    // actual promise, though, so End Inning can wait for the exact write
    // instead of merely waiting for live-game event state to look stable.
    if (busy) return activeSavePromise;

    const before = snapshot();

    busy = true;
    saveMode = 'saving';
    saveMessage = 'Saving…';
    errorMessage = '';
    draft = normalize(next);

    renderCard();

    const request = api(
      'POST',
      mode === 'current'
        ? {mode: 'current'}
        : {
            mode: 'custom',
            alignment: snapshot(),
          }
    );

    activeSavePromise = request;

    try {
      const data = await request;

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
        'Unable to save defense.';

      renderCard();

      return null;
    } finally {
      if (activeSavePromise === request) {
        activeSavePromise = null;
      }

      busy = false;
      renderCard();
    }
  }

  async function flushPendingSave() {
    const deadline = Date.now() + 10000;
    const timeoutMessage =
      'Defense is still saving. Check your connection, wait for Saved ✓, then try ending the inning again.';

    while (busy || activeSavePromise) {
      const pending = activeSavePromise;
      const remaining = deadline - Date.now();

      if (remaining <= 0) {
        throw new Error(timeoutMessage);
      }

      if (pending) {
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
      } else {
        await new Promise(resolve =>
          window.setTimeout(
            resolve,
            Math.min(25, remaining)
          )
        );
      }
    }

    if (saveMode === 'error') {
      throw new Error(
        errorMessage
          ? `${errorMessage} Save the defense again, then try ending the inning.`
          : 'The defense was not saved. Save it again, then try ending the inning.'
      );
    }

    return snapshot();
  }

  function isSaveInFlightOrQueued() {
    return busy || Boolean(activeSavePromise);
  }

  function movePlayerToBench(
    name,
    source
  ) {
    if (
      busy ||
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

    saveAlignment(
      next,
      {
        successMessage:
          `${playerLabel(name)} → BENCH`,
      }
    );
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

  /**
   * Next Inning's half of the shared drag contract.
   *
   * Deliberately different from On the Field: the pitcher IS a valid
   * source here, because the next inning's defense is a plan and the
   * coach edits the mound directly on the board. movePlayer() keeps its
   * asymmetric handling of a move onto P (the outgoing pitcher is
   * benched rather than swapped back), which is why the drop semantics
   * stay in this file rather than in the shared manager.
   */
  function registerDragSurface() {
    if (dragSurface || !window.CoachBoardDrag) return;

    dragSurface = window.CoachBoardDrag.registerSurface({
      id: 'next',
      root: () => $(CARD_ID),
      canStart: () => activeView === 'next' && !busy,
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
          'Saved ✓',
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
      saveMessage = 'Restored ✓';
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
        'Unable to undo change.';

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
      $(PLAN_CARD_ID)?.remove();

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

  function bootSurfaceWhenReady() {
    if ($(SWITCH_ID)) return;

    if (liveSurfaceReady()) {
      ensureSwitcher();
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
      if (ensureSwitcher()) observer.disconnect();
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
