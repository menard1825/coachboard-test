(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const PREFIX = 'DEFENSE PRESET — ';
  const PANEL_ID = 'pregame-defense-editor-v3';
  const STYLE_ID = 'pregame-defense-editor-v3-styles';
  const $ = (id) => document.getElementById(id);

  let state = null;
  let inning = '1';
  let busy = false;
  let refreshTimer = null;

  // The rotation itself (id/title/innings/associated_game_id) and its save
  // queue live in the shared CBPregameRotation store, not here — game_logic.js
  // (Add/Remove/Clear Inning, Copy Previous, Paste, templates, the manual
  // Save Rotation buttons) mutates the exact same object and shares the
  // same queue, so a /save_rotation payload built by either module always
  // reflects every edit made by both, never a stale per-module snapshot.
  function defaultRotationTitle() {
    return `Rotation for vs ${state?.game?.opponent || 'Opponent'}`;
  }

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function positions() {
    return Number(state?.outfielder_count) === 4
      ? ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'LCF', 'RCF', 'RF']
      : ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'];
  }

  function presentPlayers() {
    const absent = new Set((state?.absent_player_ids || []).map(Number));
    return (state?.roster || []).filter((player) => !absent.has(Number(player.id)));
  }

  function presetName(template) {
    const title = String(template?.title || '');
    return title.startsWith(PREFIX) ? title.slice(PREFIX.length).trim() : null;
  }

  function presets() {
    return (state?.rotation_templates || [])
      .filter((template) => presetName(template))
      .sort((a, b) => presetName(a).localeCompare(presetName(b)));
  }

  // Reads the canonical rotation and keeps the locally-selected `inning`
  // pointed at a real key — but never mutates the canonical structure to
  // make that true. `notifyChange()` (from either module's edits, or from
  // a fresh server snapshot) can fire, and this render path run, at any
  // point relative to an inning having just been removed elsewhere; a
  // stale `inning` here must be re-pointed at an existing inning, never
  // used as an excuse to silently recreate the one that was removed.
  // Creating a new inning key is exclusively an explicit user action
  // (Add Inning/Sub-Inning in game_logic.js, or a real tap-to-assign edit
  // once `inning` already names an existing key).
  function ensureRotation() {
    state.rotation = window.CBPregameRotation.getRotation(defaultRotationTitle());
    reconcileInningSelection();
  }

  function reconcileInningSelection() {
    const keys = Object.keys(state.rotation.innings || {});
    if (!keys.length || keys.includes(inning)) return;

    const checked = document.querySelector('input[name="inning-radio"]:checked')?.value;
    if (checked && keys.includes(checked)) {
      inning = checked;
      return;
    }

    // Prefer the nearest remaining inning at or below the one that
    // disappeared (e.g. Remove Last Inning should land one inning back),
    // falling back to the earliest remaining inning.
    const numericKeys = keys
      .map(Number)
      .filter((value) => Number.isFinite(value))
      .sort((a, b) => a - b);
    const target = Number(inning);
    const atOrBelow = numericKeys.filter((value) => value <= target);
    if (atOrBelow.length) {
      inning = String(atOrBelow[atOrBelow.length - 1]);
    } else if (numericKeys.length) {
      inning = String(numericKeys[0]);
    } else {
      inning = keys[0];
    }
  }

  function alignment() {
    ensureRotation();
    return state.rotation.innings[inning];
  }

  function playerPosition(name, source = alignment()) {
    return Object.entries(source).find(([, playerName]) => playerName === name)?.[0] || null;
  }

  // Each planned inning with its planned mid-inning changes ("Plan a
  // change during Inning 2" saves as inning "2.1"): [{inning, segments}],
  // segments in order. An inning with no one placed in any segment is an
  // empty future slot, not a coaching plan, and is left out.
  function plannedInnings() {
    ensureRotation();
    const innings = state.rotation.innings || {};
    const groups = new Map();

    Object.keys(innings)
      .filter((key) => Number.isFinite(Number.parseFloat(key)))
      .sort((a, b) => Number.parseFloat(a) - Number.parseFloat(b))
      .forEach((key) => {
        const base = String(Math.floor(Number.parseFloat(key)));
        if (!groups.has(base)) groups.set(base, []);
        groups.get(base).push(innings[key] || {});
      });

    return [...groups.entries()]
      .map(([inningKey, segments]) => ({inning: inningKey, segments}))
      .filter(({segments}) => segments.some((source) => (
        Object.values(source).some((name) => String(name || '').trim())
      )));
  }

  function inningOrdinal(value) {
    const n = Number(value);
    const tail = n % 100 >= 11 && n % 100 <= 13
      ? 'th'
      : ({1: 'st', 2: 'nd', 3: 'rd'}[n % 10] || 'th');
    return `${n}${tail}`;
  }

  // A player marked absent for this game who is still placed in the plan is
  // a planning problem for the coach to fix; nothing is moved for them.
  function absentInPlanWarnings(planned) {
    const absent = new Set((state?.absent_player_ids || []).map(Number));
    const listed = (labels) => (
      labels.length > 1
        ? `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`
        : labels[0]
    );

    return (state?.roster || [])
      .filter((player) => absent.has(Number(player.id)))
      .map((player) => {
        // Position -> the innings it is planned in, in plan order.
        const where = new Map();

        planned.forEach(({inning: key, segments}) => {
          const first = playerPosition(player.name, segments[0]);
          const places = [...new Set(
            segments.map((source) => playerPosition(player.name, source)).filter(Boolean)
          )];
          places.forEach((pos) => {
            const label = inningOrdinal(key) +
              (pos === first ? '' : ' (mid-inning change)');
            if (!where.has(pos)) where.set(pos, []);
            where.get(pos).push(label);
          });
        });

        const spots = [...where.entries()].map(([pos, labels]) => (
          `${pos === 'P' ? 'pitching' : pos} in the ${listed(labels)}`
        ));

        return spots.length
          ? `${player.name} is marked absent but is still in the plan: ${spots.join(', ')}.`
          : '';
      })
      .filter(Boolean);
  }

  function positionChip(position, full, part) {
    // Partial innings stay visibly partial: "SS × 1 + 1 part", never "SS × 2".
    const text = full && part
      ? `${position} × ${full} + ${part} part`
      : part
        ? `${position} × ${part} part`
        : `${position} × ${full}`;
    return `<span class="pde-time-chip${position === 'P' ? ' pitch' : ''}">${esc(text)}</span>`;
  }

  function playingTimeSummary() {
    const planned = plannedInnings();
    if (!planned.length) return '';

    const positionOrder = positions();
    const openSpots = (source) => positionOrder.filter((pos) => !String(source[pos] || '').trim());

    // An inning with an open spot is not finished: a player not placed in
    // it is unassigned ("–"), never counted as sitting on the bench.
    const incomplete = planned
      .map(({inning: key, segments}) => {
        const open = [...new Set(segments.flatMap(openSpots))];
        return open.length ? {inning: key, open} : null;
      })
      .filter(Boolean);
    const incompleteInnings = new Set(incomplete.map(({inning: key}) => key));

    const rows = presentPlayers().map((player) => {
      const fullAt = new Map();
      const partAt = new Map();
      let fullInnings = 0;
      let partialInnings = 0;
      let benchInnings = 0;
      const timeline = [];

      planned.forEach(({inning: key, segments}) => {
        const spots = segments.map((source) => playerPosition(player.name, source));
        const unset = incompleteInnings.has(key);
        const label = spots
          .map((pos) => pos || (unset ? '–' : 'BN'))
          .filter((pos, index, all) => index === 0 || pos !== all[index - 1])
          .join('→');

        timeline.push(`${key} ${label}`);

        if (spots.every(Boolean)) {
          // On the field for the whole inning, even if the position changes.
          fullInnings += 1;
        } else if (spots.some(Boolean)) {
          // Enters or leaves during the inning.
          partialInnings += 1;
        } else if (!unset) {
          benchInnings += 1;
        }

        [...new Set(spots.filter(Boolean))].forEach((pos) => {
          const target = spots.every((spot) => spot === pos) ? fullAt : partAt;
          target.set(pos, (target.get(pos) || 0) + 1);
        });
      });

      const chips = positionOrder
        .filter((position) => fullAt.get(position) || partAt.get(position))
        .map((position) => positionChip(
          position,
          fullAt.get(position) || 0,
          partAt.get(position) || 0
        ));

      if (benchInnings) {
        chips.push(
          `<span class="pde-time-chip bench">BN × ${benchInnings}</span>`
        );
      }

      const playing = fullInnings + partialInnings;
      const total = [
        `${fullInnings} full`,
        partialInnings ? `${partialInnings} partial` : '',
        `${benchInnings} bench`,
      ].filter(Boolean).join(' · ');

      return `
        <div class="pde-time-row${playing ? '' : ' no-time'}"
          data-player-name="${esc(player.name)}"
          data-full="${fullInnings}"
          data-partial="${partialInnings}"
          data-bench="${benchInnings}"
          data-innings="${esc(timeline.join(' · '))}">
          <div class="pde-time-main">
            <strong class="pde-time-name">${esc(player.name)}</strong>
            <span class="pde-time-total">${playing ? esc(total) : 'No field time planned'}</span>
          </div>
          <div class="pde-time-chips">${chips.join('')}</div>
          <div class="pde-time-innings">${esc(timeline.join(' · '))}</div>
        </div>`;
    }).join('');

    // Who is planned to pitch, and when. A change in the middle of an
    // inning is shown as part of that inning, not as a whole one.
    const pitching = new Map();
    planned.forEach(({inning: key, segments}) => {
      const names = segments.map((source) => String(source.P || '').trim());
      [...new Set(names.filter(Boolean))].forEach((name) => {
        const whole = names.every((entry) => entry === name);
        if (!pitching.has(name)) pitching.set(name, []);
        pitching.get(name).push(whole ? key : `${key} (part)`);
      });
    });
    const pitchingLine = pitching.size
      ? [...pitching.entries()]
        .map(([name, innings]) => `${name}: ${innings.join(', ')}`)
        .join(' · ')
      : 'No pitcher planned yet';

    const absentLines = absentInPlanWarnings(planned)
      .map((line) => `<div class="pde-playing-time-absent" data-absent-warning>⚠ ${esc(line)}</div>`)
      .join('');

    const incompleteLine = incomplete.length
      ? `<div class="pde-playing-time-open">Not finished: ${incomplete
        .map(({inning: key, open}) => `Inning ${key} (${open.join(', ')} open)`)
        .join(' · ')}. Players not placed there show – and don't count as bench.</div>`
      : '';

    return `
      <section class="pde-playing-time" id="pde-playing-time-summary">
        <div class="pde-playing-time-head">
          <div>
            <strong>Playing Time Summary</strong>
            <span>${planned.length} planned inning${planned.length === 1 ? '' : 's'} · updates as you move players</span>
          </div>
        </div>
        ${absentLines}
        <div class="pde-playing-time-pitching" data-pitching-plan>Pitching: ${esc(pitchingLine)}</div>
        ${incompleteLine}
        <div class="pde-time-rows">${rows}</div>
      </section>`;
  }

  function installStyles() {
    if ($(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${PANEL_ID}{border:1px solid #dfe4ea;border-radius:16px;background:#fff;box-shadow:0 1px 4px rgba(16,24,40,.06);overflow:hidden;margin-bottom:18px}
      #${PANEL_ID} .pde-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:14px 16px 11px;border-bottom:1px solid #edf0f3;background:#fff}
      #${PANEL_ID} .pde-kicker{font-size:var(--cb-text-2xs);text-transform:uppercase;letter-spacing:.1em;font-weight:850;color:#667085}
      #${PANEL_ID} .pde-title{font-size:1.05rem;font-weight:850;color:#172033;margin-top:2px}
      #${PANEL_ID} .pde-help{font-size:.73rem;color:var(--cb-muted);margin-top:2px;max-width:620px}
      #${PANEL_ID} .pde-inning{background:#172033;color:#fff;border-radius:10px;min-width:68px;text-align:center;padding:7px 9px;flex:0 0 auto}
      #${PANEL_ID} .pde-inning small{display:block;font-size:.53rem;letter-spacing:.08em;opacity:.75;font-weight:750}
      #${PANEL_ID} .pde-inning strong{display:block;font-size:1.4rem;line-height:1.05}
      #${PANEL_ID} .pde-save-status{display:none;align-items:center;font-size:.65rem;font-weight:800;margin-top:6px;color:#667085}
      #${PANEL_ID} .pde-save-status[data-status="saving"],
      #${PANEL_ID} .pde-save-status[data-status="saved"],
      #${PANEL_ID} .pde-save-status[data-status="failed"]{display:flex}
      #${PANEL_ID} .pde-save-status[data-status="saved"]{color:#176b38}
      #${PANEL_ID} .pde-save-status[data-status="failed"]{color:#a63d3d;cursor:pointer;text-decoration:underline}
      #${PANEL_ID} .pde-body{padding:13px 16px 15px;background:#fff}
      #${PANEL_ID} .pde-tools{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px;margin-bottom:12px}
      #${PANEL_ID} .pde-tools .btn,#${PANEL_ID} .pde-tools .form-select{min-height:42px;border-radius:9px}
      #${PANEL_ID} .pde-field-card{border:1px solid #d6e2d4;border-radius:14px;overflow:hidden;background:#fff}
      #${PANEL_ID} .pde-field-caption{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:8px 10px;border-bottom:1px solid #e4e9e4;background:#fff}
      #${PANEL_ID} .pde-field-caption strong{font-size:.72rem;color:#344054}
      #${PANEL_ID} .pde-field-caption span{font-size:var(--cb-text-xs);color:var(--cb-muted)}
      #${PANEL_ID} .pde-field{position:relative;height:clamp(330px,52vw,500px);overflow:hidden;background:repeating-linear-gradient(90deg,#3c8a50 0,#3c8a50 12.5%,#438f56 12.5%,#438f56 25%)}
      #${PANEL_ID} .pde-field-art{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
      #${PANEL_ID} .pde-spot{position:absolute;transform:translate(-50%,-50%);width:clamp(72px,13vw,118px);min-height:45px;border:1px solid rgba(220,225,229,.98);border-radius:9px;background:rgba(255,255,255,.96);box-shadow:0 2px 5px rgba(16,24,40,.12);padding:5px 6px;text-align:center;z-index:2;cursor:pointer;color:#172033}
      #${PANEL_ID} .pde-spot:hover,#${PANEL_ID} .pde-spot:focus-visible{border-color:#667f9e;box-shadow:0 0 0 3px rgba(55,91,135,.14);outline:0}
      #${PANEL_ID} .pde-spot.open{background:#fff5f5;border-color:#d99a9a}
      #${PANEL_ID} .pde-pos{display:block;font-size:.52rem;line-height:1;font-weight:900;letter-spacing:.04em;color:#667085;margin-bottom:3px}
      #${PANEL_ID} .pde-name{display:block;font-size:.68rem;line-height:1.08;font-weight:800;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere}
      #${PANEL_ID} .pde-spot.open .pde-name{color:#a63d3d}
      #${PANEL_ID} .pde-bench{padding:9px 10px 10px;background:#fff;border-top:1px solid #e4e9e4}
      #${PANEL_ID} .pde-label{font-size:var(--cb-text-2xs);text-transform:uppercase;letter-spacing:.08em;font-weight:850;color:#667085;margin-bottom:6px}
      #${PANEL_ID} .pde-chips{display:flex;gap:5px;flex-wrap:wrap}
      #${PANEL_ID} .pde-chips span{font-size:var(--cb-text-xs);border:1px solid #dde2e7;background:#f8f9fb;border-radius:999px;padding:4px 7px;color:#475467;font-weight:650}
      #${PANEL_ID} .pde-playing-time{margin-top:12px;border:1px solid #dfe4ea;border-radius:12px;background:#fff;overflow:hidden}
      #${PANEL_ID} .pde-playing-time-head{padding:9px 10px;background:#f8fafc;border-bottom:1px solid #e7ebef}
      #${PANEL_ID} .pde-playing-time-head strong{display:block;font-size:.76rem;color:#172033;font-weight:900}
      #${PANEL_ID} .pde-playing-time-head span{display:block;margin-top:1px;font-size:.62rem;color:#667085}
      #${PANEL_ID} .pde-time-row{padding:8px 10px;border-top:1px solid #eef1f4}
      #${PANEL_ID} .pde-time-row:first-child{border-top:0}
      #${PANEL_ID} .pde-time-main{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
      #${PANEL_ID} .pde-time-name{font-size:.72rem;color:#172033;min-width:0}
      #${PANEL_ID} .pde-time-total{font-size:.61rem;color:#667085;white-space:nowrap;font-weight:700}
      #${PANEL_ID} .pde-time-chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}
      #${PANEL_ID} .pde-time-chip{display:inline-flex;align-items:center;border:1px solid #4aae72;background:#f4fbf6;color:#176b38;border-radius:6px;padding:3px 6px;font-size:.59rem;font-weight:800;line-height:1}
      #${PANEL_ID} .pde-time-chip.bench{border-color:#d6dbe1;background:#f4f5f7;color:#667085}
      #${PANEL_ID} .pde-time-chip.pitch{border-color:#6f8fc7;background:#f2f6fc;color:#264f8f}
      #${PANEL_ID} .pde-time-innings{margin-top:4px;font-size:.6rem;color:#667085;font-weight:650;line-height:1.35}
      #${PANEL_ID} .pde-time-row.no-time .pde-time-total{color:#a12d26}
      #${PANEL_ID} .pde-playing-time-pitching{padding:6px 10px;border-bottom:1px solid #e7ebef;color:#264f8f;font-size:.64rem;font-weight:750}
      #${PANEL_ID} .pde-playing-time-absent{padding:7px 10px;border-bottom:1px solid #efb5ae;background:#fff1ef;color:#912d28;font-size:.66rem;font-weight:800}
      #${PANEL_ID} .pde-playing-time-open{padding:6px 10px;border-bottom:1px solid #e7ebef;background:#fff8e6;color:#775a10;font-size:.62rem;font-weight:750}
      #${PANEL_ID} .pde-status{display:flex;align-items:center;gap:10px;text-align:left;font-size:.72rem;margin-top:10px;border:2px solid #a66500;border-radius:11px;background:#fff4d8;color:#3f2b00;padding:9px 10px;box-shadow:0 2px 5px rgba(75,48,0,.08)}
      #${PANEL_ID} .pde-status.complete{border-color:#176b38;background:#edf8f1;color:#123d23}
      #${PANEL_ID} .pde-status-icon{font-size:1.05rem;line-height:1;flex:0 0 auto}
      #${PANEL_ID} .pde-status-copy{min-width:0;flex:1}
      #${PANEL_ID} .pde-status-copy strong{display:block;font-size:.76rem;font-weight:900;color:inherit}
      #${PANEL_ID} .pde-status-copy span{display:block;font-size:var(--cb-text-xs);font-weight:700;color:inherit;margin-top:1px;line-height:1.25}
      #${PANEL_ID} .pde-status-badge{flex:0 0 auto;background:#694200;color:#fff;border-radius:999px;padding:4px 8px;font-size:var(--cb-text-2xs);font-weight:900;letter-spacing:.05em}
      #${PANEL_ID} .pde-status.complete .pde-status-badge{background:#176b38}
      #pde-player-modal .modal-content,#pde-preset-modal .modal-content{border:0;border-radius:16px;overflow:hidden}
      #pde-player-modal .pde-choice{padding:14px;min-height:56px}
      #pde-player-modal .pde-choice small{display:block;color:#667085;margin-top:2px}

      @media (max-width:575.98px){
        #${PANEL_ID} .pde-head{padding:12px}
        #${PANEL_ID} .pde-body{padding:11px 12px 13px}
        #${PANEL_ID} .pde-tools{grid-template-columns:1fr 1fr}
        #${PANEL_ID} .pde-tools select{grid-column:1/-1}
        #${PANEL_ID} .pde-status{align-items:flex-start}
        #${PANEL_ID} .pde-status-badge{display:none}
        #${PANEL_ID} .pde-field{height:300px}
        #${PANEL_ID} .pde-spot{width:66px;min-height:41px;padding:4px}
        #${PANEL_ID} .pde-name{font-size:.58rem}
        #${PANEL_ID} .pde-pos{font-size:.45rem}
      }

      @media (min-width:576px) and (orientation:portrait){
        #${PANEL_ID} .pde-field{height:clamp(360px,58vw,485px)}
        #${PANEL_ID} .pde-spot{width:clamp(78px,14vw,112px)}
      }

      @media (min-width:768px) and (orientation:landscape){
        #${PANEL_ID} .pde-body{padding:12px 14px 14px}
        #${PANEL_ID} .pde-field{height:clamp(330px,39vw,455px)}
        #${PANEL_ID} .pde-spot{width:clamp(80px,10vw,112px)}
        #${PANEL_ID} .pde-tools{grid-template-columns:minmax(260px,1fr) auto auto}
      }
    `;
    document.head.appendChild(style);
  }

  function toast(message, kind = 'success') {
    let holder = $('pde-toast');
    if (!holder) {
      holder = document.createElement('div');
      holder.id = 'pde-toast';
      holder.className = 'toast-container position-fixed top-0 end-0 p-3';
      holder.style.zIndex = '5000';
      document.body.appendChild(holder);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    holder.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el, {delay: 3000});
    el.addEventListener('hidden.bs.toast', () => el.remove(), {once: true});
    instance.show();
  }

  function legacyDesktopRow() {
    return $('diamond-parent-desktop')?.closest('.row') || null;
  }

  function legacyMobileBlock() {
    return $('diamond-parent-mobile')?.closest('.d-lg-none') || null;
  }

  function restoreLegacy() {
    legacyDesktopRow()?.style.removeProperty('display');
    legacyMobileBlock()?.style.removeProperty('display');
  }

  function isLiveNow() {
    return Boolean(
      state?.game?.is_live ||
      $('liveGameModeToggle')?.checked ||
      !$('live-game-overlay')?.classList.contains('d-none')
    );
  }

  function syncLegacyVisibility() {
    const panel = $(PANEL_ID);
    if (isLiveNow()) {
      panel?.remove();
      restoreLegacy();
      return;
    }
    legacyDesktopRow()?.style.setProperty('display', 'none', 'important');
    legacyMobileBlock()?.style.setProperty('display', 'none', 'important');
  }

  function filterWholeGameTemplates() {
    const select = $('rotationTemplateSelect');
    if (!select) return;
    const presetIds = new Set(presets().map((preset) => String(preset.id)));
    [...select.options].forEach((option) => {
      if (presetIds.has(String(option.value))) option.remove();
    });
  }

  function fieldSpot(pos, source, left, top) {
    const name = source?.[pos] || '';
    return `<button type="button" class="pde-spot ${name ? '' : 'open'}" data-pde-pos="${esc(pos)}" style="left:${left}%;top:${top}%"><span class="pde-pos">${esc(pos)}</span><span class="pde-name">${esc(name || 'OPEN')}</span></button>`;
  }

  function baseballField(source) {
    const fourOutfielders = Number(state?.outfielder_count) === 4;
    const outfield = fourOutfielders
      ? [['LF', 11, 23], ['LCF', 38, 13], ['RCF', 62, 13], ['RF', 89, 23]]
      : [['LF', 15, 22], ['CF', 50, 11], ['RF', 85, 22]];
    const spots = [
      ...outfield,
      ['3B', 18, 57], ['SS', 38, 43], ['2B', 62, 43], ['1B', 82, 57],
      ['P', 50, 62], ['C', 50, 85],
    ];

    const assigned = new Set(Object.values(source || {}).filter(Boolean));
    const bench = presentPlayers().filter((player) => !assigned.has(player.name));

    return `
      <div class="pde-field-card">
        <div class="pde-field-caption"><strong>Defense — Inning ${esc(inning)}</strong><span>Tap any position to change it</span></div>
        <div class="pde-field">
          <svg class="pde-field-art" viewBox="0 0 100 88" preserveAspectRatio="none" aria-hidden="true">
            <path d="M7 58 Q9 13 50 5 Q91 13 93 58" fill="none" stroke="rgba(245,245,220,.38)" stroke-width="1.2"/>
            <path d="M50 85 L7 38 M50 85 L93 38" fill="none" stroke="rgba(255,255,255,.9)" stroke-width=".72"/>
            <polygon points="50,76 27,54 50,32 73,54" fill="#cda26b" opacity=".97"/>
            <polygon points="50,69 34,54 50,40 66,54" fill="#438f56"/>
            <circle cx="50" cy="62" r="4.6" fill="#cda26b"/>
            <circle cx="50" cy="82" r="6.4" fill="#cda26b"/>
            <rect x="49" y="31" width="2" height="2" fill="#fff" transform="rotate(45 50 32)"/>
            <rect x="72" y="53" width="2" height="2" fill="#fff" transform="rotate(45 73 54)"/>
            <rect x="26" y="53" width="2" height="2" fill="#fff" transform="rotate(45 27 54)"/>
            <path d="M48.7 82 L50 80.8 L51.3 82 L50.8 83.6 L49.2 83.6 Z" fill="#fff"/>
          </svg>
          ${spots.map(([pos, left, top]) => fieldSpot(pos, source, left, top)).join('')}
        </div>
        <div class="pde-bench">
          <div class="pde-label">Bench — Inning ${esc(inning)}</div>
          <div class="pde-chips">${bench.length ? bench.map((player) => `<span>${esc(player.name)}</span>`).join('') : '<span>None</span>'}</div>
        </div>
      </div>`;
  }

  function render() {
    const board = $('rotation-board');
    if (!board || !state) return;

    let panel = $(PANEL_ID);
    if (isLiveNow()) {
      panel?.remove();
      restoreLegacy();
      return;
    }

    syncLegacyVisibility();
    if (!panel) {
      panel = document.createElement('section');
      panel.id = PANEL_ID;
      const controls = board.querySelector(':scope > .mb-3.planner-controls');
      controls ? controls.insertAdjacentElement('afterend', panel) : board.prepend(panel);
    }

    const source = alignment();
    const open = positions().filter((pos) => !source[pos]);
    const savedPresets = presets();

    panel.innerHTML = `
      <div class="pde-head">
        <div>
          <div class="pde-kicker">Pregame Defense</div>
          <div class="pde-title">Set Inning ${esc(inning)}</div>
          <div class="pde-help">Tap a position to assign a player.</div>
          <div class="pde-save-status" id="pde-save-status" data-status="idle"></div>
        </div>
        <div class="pde-inning"><small>INNING</small><strong>${esc(inning)}</strong></div>
      </div>
      <div class="pde-body">
        <div class="pde-tools">
          <select class="form-select" id="pde-preset">
            <option value="">Choose a saved defense…</option>
            ${savedPresets.map((preset) => `<option value="${preset.id}">${esc(presetName(preset))}</option>`).join('')}
          </select>
          <button class="btn btn-outline-primary" id="pde-apply" disabled>This inning</button>
          <button class="btn btn-outline-secondary" id="pde-save">Save this defense</button>
        </div>
        ${baseballField(source)}
        ${playingTimeSummary()}
        <div class="pde-status ${open.length ? 'needs' : 'complete'}">
          <i class="bi ${open.length ? 'bi-exclamation-triangle-fill' : 'bi-check-circle-fill'} pde-status-icon" aria-hidden="true"></i>
          <div class="pde-status-copy">
            <strong>${open.length ? `${open.length} open position${open.length === 1 ? '' : 's'}` : 'Defense complete'}</strong>
            <span class="pde-status-detail">${open.length ? esc(open.join(', ')) : 'Every field position has a player.'}</span>
            <span class="pde-status-note">Changes save to this inning only.</span>
          </div>
          <span class="pde-status-badge">${open.length ? 'ACTION NEEDED' : 'READY'}</span>
        </div>
      </div>`;

    panel.querySelectorAll('[data-pde-pos]').forEach((button) => {
      button.addEventListener('click', () => choosePlayer(button.dataset.pdePos));
    });

    const presetSelect = $('pde-preset');
    const applyButton = $('pde-apply');
    presetSelect.addEventListener('change', () => { applyButton.disabled = !presetSelect.value; });
    applyButton.addEventListener('click', applyPreset);
    $('pde-save').addEventListener('click', openPresetModal);

    $('pde-save-status')?.addEventListener('click', () => {
      if (window.CBPregameRotation.getStatus() === 'failed') retryRotationSave();
    });
    applySaveStatusToDom();
  }

  function playerModal() {
    let modal = $('pde-player-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'pde-player-modal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered modal-dialog-scrollable modal-fullscreen-sm-down">
        <div class="modal-content">
          <div class="modal-header">
            <div><h5 class="modal-title mb-0"></h5><div class="small text-muted" id="pde-help"></div></div>
            <button class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body p-0"><div class="list-group list-group-flush" id="pde-list"></div></div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    // Bootstrap ignores hide() while the modal is still animating open, so a
    // quick pick (within ~0.4s) used to leave the picker stuck on screen.
    modal.addEventListener('shown.bs.modal', () => { modal.dataset.pdeOpen = '1'; });
    modal.addEventListener('hide.bs.modal', () => { delete modal.dataset.pdeOpen; });
    return modal;
  }

  function closePlayerModal(modal) {
    const instance = bootstrap.Modal.getOrCreateInstance(modal);
    if (modal.dataset.pdeOpen === '1') {
      instance.hide();
    } else {
      modal.addEventListener('shown.bs.modal', () => instance.hide(), {once: true});
    }
  }

  function choosePlayer(pos) {
    const modal = playerModal();
    const source = alignment() || {};
    const occupant = source[pos] || '';
    const pitcher = source.P || '';
    modal.querySelector('.modal-title').textContent = `${pos} — Choose Player`;
    $('pde-help').textContent = pos === 'P'
      ? (pitcher ? `Current pitcher: ${pitcher}.` : 'Choose the pitcher.')
      : occupant
        ? `Current: ${occupant}. Choosing a bench player moves ${occupant} to the bench.`
        : 'Choose a player for this position.';

    const choices = presentPlayers()
      .map((player) => ({player, position: playerPosition(player.name, source)}))
      .sort((a, b) => {
        if (a.player.name === occupant) return -1;
        if (b.player.name === occupant) return 1;
        if (!a.position && b.position) return -1;
        if (!b.position && a.position) return 1;
        return a.player.name.localeCompare(b.player.name);
      });

    const detail = (position) => {
      if (position === pos) return `Currently at ${esc(pos)}`;
      if (!position) return 'On bench this inning';
      // Moves involving P ask the coach; they are never a one-tap swap.
      if (pos === 'P' && pitcher) return `Currently at ${esc(position)} — you'll choose where ${esc(pitcher)} goes`;
      if (position === 'P') return "Currently at P — you'll choose who pitches";
      return occupant
        ? `Currently at ${esc(position)} — swaps with ${esc(occupant)}`
        : `Currently at ${esc(position)} — ${esc(position)} will become open`;
    };

    const list = $('pde-list');
    list.dataset.pdePosition = pos;
    list.innerHTML = `
      ${occupant ? (pos === 'P'
        ? `<button class="list-group-item list-group-item-action pde-choice text-danger" data-clear="1"><strong>Take ${esc(occupant)} off P</strong><small>Choose who pitches instead.</small></button>`
        : `<button class="list-group-item list-group-item-action pde-choice text-danger" data-clear="1"><strong>Move ${esc(occupant)} to Bench</strong><small>Leave ${esc(pos)} open.</small></button>`) : ''}
      ${choices.map(({player, position}) => `
        <button class="list-group-item list-group-item-action pde-choice" data-player="${esc(player.name)}">
          <strong>${esc(player.name)}</strong>
          <small>${detail(position)}</small>
        </button>`).join('')}`;

    list.onclick = (event) => {
      const choice = event.target.closest('.pde-choice');
      if (!choice) return;
      const playerName = choice.dataset.player;
      // A snapshot of the inning as the coach saw it when the move began.
      const start = {...(alignment() || {})};

      if (pos === 'P' && choice.dataset.clear) {
        list.onclick = null;
        void takeOffP(modal, start);
        return;
      }
      if (pos === 'P' && pitcher && playerName && playerName !== pitcher) {
        list.onclick = null;
        void chooseNewPitcher(modal, start, playerName);
        return;
      }
      if (pos !== 'P' && pitcher && playerName === pitcher) {
        list.onclick = null;
        void moveCurrentPitcher(modal, start, pos);
        return;
      }

      const next = {...alignment()};
      let message = '';
      if (choice.dataset.clear) {
        const old = next[pos];
        delete next[pos];
        message = `${old} moved to the bench. ${pos} is open.`;
      } else {
        const sourcePos = playerPosition(playerName, next);
        const displaced = next[pos];

        if (sourcePos && sourcePos !== pos) {
          if (displaced && displaced !== playerName) {
            next[sourcePos] = displaced;
          } else {
            delete next[sourcePos];
          }
        }

        next[pos] = playerName;

        if (
          sourcePos &&
          sourcePos !== pos &&
          displaced &&
          displaced !== playerName
        ) {
          message = `${playerName} swapped ${sourcePos} ↔ ${pos} with ${displaced}.`;
        } else if (sourcePos && sourcePos !== pos) {
          message = `${playerName}: ${sourcePos} → ${pos}. ${sourcePos} is now open.`;
        } else if (displaced && displaced !== playerName) {
          message = `${playerName} → ${pos}. ${displaced} is now on the bench.`;
        } else {
          message = `${playerName} set at ${pos}.`;
        }
      }

      state.rotation.innings[inning] = next;
      closePlayerModal(modal);
      render();
      // Optimistic: describe the local change now rather than waiting on the
      // network. Save outcome (including failure) is reported by the
      // persistent save-status indicator, not by this toast.
      toast(message);
      saveRotation();
    };

    bootstrap.Modal.getOrCreateInstance(modal).show();
  }

  // ---- Moves involving P are the coach's decision ------------------------
  //
  // Non-P planning swaps stay one tap (the picker says so). A move that
  // changes who pitches, or where the pitcher goes, asks instead: CoachBoard
  // never sends the old pitcher to a vacated spot or makes a fielder the
  // pitcher on its own. Each answer only changes a local draft of this
  // inning. Nothing is saved until the move is fully resolved, then the
  // resolved inning is saved once; closing the sheet at any step (Cancel,
  // the X, Escape) changes nothing.

  const TBD = {tbd: true};

  function pitcherRole() {
    return String(inning) === '1' ? 'starting pitcher' : `pitcher for ${inningsPhrase([inning])}`;
  }

  function openFieldPositions(draft) {
    return positions().filter((position) => position !== 'P' && !draft[position]);
  }

  function modalStillOpen(modal) {
    return modal.classList.contains('show');
  }

  // One question in the open picker sheet. Resolves with the chosen value,
  // or null when the coach cancels or closes the sheet.
  function ask(modal, {title, help, options}) {
    return new Promise((resolve) => {
      if (!modalStillOpen(modal)) {
        resolve(null);
        return;
      }
      const list = $('pde-list');
      modal.querySelector('.modal-title').textContent = title;
      $('pde-help').textContent = help || '';
      list.innerHTML = options.map((option, index) => `
        <button type="button" class="list-group-item list-group-item-action pde-question-choice${option.danger ? ' text-danger' : ''}" data-answer="${index}">
          <strong>${esc(option.label)}</strong>${option.detail ? `<small class="d-block">${esc(option.detail)}</small>` : ''}
        </button>`).join('') + `
        <button type="button" class="list-group-item list-group-item-action pde-question-choice" data-answer="cancel">
          <strong>Cancel</strong><small class="d-block">Keep the plan as it was.</small>
        </button>`;
      const onHidden = () => resolve(null);
      modal.addEventListener('hidden.bs.modal', onHidden, {once: true});
      list.onclick = (event) => {
        const button = event.target.closest('[data-answer]');
        if (!button) return;
        list.onclick = null;
        modal.removeEventListener('hidden.bs.modal', onHidden);
        if (button.dataset.answer === 'cancel') {
          closePlayerModal(modal);
          resolve(null);
          return;
        }
        resolve(options[Number(button.dataset.answer)].value);
      };
    });
  }

  async function pitchingSummary(modal) {
    $('pde-help').textContent = 'Checking pitchers…';
    try {
      const response = await fetch(`/api/live-game/${gameId}/state`, {cache: 'no-store'});
      if (!response.ok) return {};
      const data = await response.json();
      return data?.pitch_count_summary || {};
    } catch (_) {
      return {};
    }
  }

  // The server's own classification (pitching_eligibility.py), shown as the
  // same four words the live game uses. Nothing is decided from it here.
  const ELIGIBILITY_WORD = {
    ready: 'Ready',
    advisory: 'Advisory',
    rule_conflict: 'Rule conflict',
    unknown: "Can't confirm",
  };

  function eligibilityText(summary) {
    const word = ELIGIBILITY_WORD[summary?.eligibility];
    if (!word) return '';
    if (summary.eligibility === 'ready') return word;
    const reason = String(summary.eligibility_message || summary.status_detail || summary.status || '').trim();
    return reason ? `${word} · ${reason}` : word;
  }

  // Who pitches instead of `leaving`? Resolves with a player name, TBD (later
  // innings only), or null (cancelled).
  async function askWhoPitches(modal, draft, leaving, title) {
    const summary = await pitchingSummary(modal);
    const rank = {ready: 0, advisory: 1, unknown: 2, rule_conflict: 3};
    const candidates = presentPlayers()
      .map((player) => player.name)
      .filter((name) => name !== leaving)
      .sort((a, b) => (
        (rank[summary[a]?.eligibility] ?? 2) - (rank[summary[b]?.eligibility] ?? 2) || a.localeCompare(b)
      ));
    const options = candidates.map((name) => {
      const at = playerPosition(name, draft);
      const where = at ? `Currently at ${at} — ${at} will become open` : 'On bench';
      return {
        label: `${name} pitches`,
        detail: [eligibilityText(summary[name]), where].filter(Boolean).join(' · '),
        value: name,
      };
    });
    if (String(inning) !== '1') {
      options.push({label: 'Decide later — Pitcher TBD', detail: `No pitcher planned yet for ${inningsPhrase([inning])}.`, value: TBD});
    }
    return ask(modal, {title, help: 'Who pitches instead?', options});
  }

  // Where does `player` go now? Offered: the spot this move opened (first),
  // any other open position, another position -- whose player is then asked
  // about in turn -- or the bench. `locked` holds positions already decided
  // in this move, so a chain can't loop. Resolves true, or null (cancelled).
  async function placePlayer(modal, draft, player, {title, vacated, locked, moves}) {
    const open = openFieldPositions(draft)
      .sort((a, b) => (a === vacated ? -1 : b === vacated ? 1 : 0));
    const taken = positions().filter((position) => (
      position !== 'P' && draft[position] && !locked.has(position)
    ));
    const options = open.map((position) => ({
      label: `Put ${player} at ${position}`,
      detail: position === vacated ? 'The spot this move opened.' : 'Open position.',
      value: {to: position},
    }));
    if (taken.length) {
      options.push({label: `Move ${player} to another position…`, detail: "You'll decide where that player goes.", value: {another: true}});
    }
    const stillOpen = open.length ? ` · leave ${open.join(', ')} open` : '';
    options.push({label: `Bench ${player}${stillOpen}`, value: {bench: true}, danger: true});

    const answer = await ask(modal, {title, help: `Where should ${player} go?`, options});
    if (!answer) return null;
    if (answer.bench) {
      moves.push(`${player} → Bench`);
      return true;
    }
    if (answer.to) {
      draft[answer.to] = player;
      locked.add(answer.to);
      moves.push(`${player} → ${answer.to}`);
      return true;
    }

    const target = await ask(modal, {
      title: `Move ${player} to…`,
      help: 'That player will need a new spot.',
      options: taken.map((position) => ({
        label: `${position} — ${draft[position]}`,
        detail: `${draft[position]} will need a new spot.`,
        value: position,
      })),
    });
    if (!target) return null;
    const displaced = draft[target];
    draft[target] = player;
    locked.add(target);
    moves.push(`${player} → ${target}`);
    moves.chained = true;
    return placePlayer(modal, draft, displaced, {title: `${player} plays ${target}`, vacated, locked, moves});
  }

  // Save the resolved inning once, unless the plan changed underneath the
  // coach while they were answering.
  async function finishPitchingMove(modal, start, draft, moves) {
    // One light review when the coach moved players along a chain; a direct
    // answer to one or two questions saves as answered.
    if (moves.chained) {
      const ok = await ask(modal, {
        title: 'Review this change',
        help: moves.join(' · '),
        options: [{label: 'Save plan', value: true}],
      });
      if (!ok) return;
    }
    if (JSON.stringify(alignment() || {}) !== JSON.stringify(start)) {
      closePlayerModal(modal);
      toast('The plan changed while you were deciding. Nothing was changed; try again.', 'warning');
      return;
    }
    const nowOpen = openFieldPositions(draft).filter((position) => start[position]);
    state.rotation.innings[inning] = draft;
    closePlayerModal(modal);
    render();
    toast(`${moves.join(' · ')}.${nowOpen.length ? ` ${nowOpen.join(', ')} ${nowOpen.length === 1 ? 'is' : 'are'} open.` : ''}`);
    saveRotation();
  }

  // P: the coach chose `newPitcher` while `start.P` is pitching.
  async function chooseNewPitcher(modal, start, newPitcher) {
    const draft = {...start};
    const oldPitcher = draft.P;
    const vacated = playerPosition(newPitcher, draft);
    if (vacated) delete draft[vacated];
    draft.P = newPitcher;
    const moves = [`${newPitcher} → P`];
    const placed = await placePlayer(modal, draft, oldPitcher, {
      title: `${newPitcher} is your ${pitcherRole()}`,
      vacated,
      locked: new Set(['P']),
      moves,
    });
    if (placed) await finishPitchingMove(modal, start, draft, moves);
  }

  // A fielding position: the coach chose the current pitcher to play `pos`.
  async function moveCurrentPitcher(modal, start, pos) {
    const draft = {...start};
    const oldPitcher = draft.P;
    const displaced = draft[pos] || '';
    delete draft.P;
    draft[pos] = oldPitcher;
    const moves = [`${oldPitcher} → ${pos}`];
    const newPitcher = await askWhoPitches(modal, draft, oldPitcher, `${oldPitcher} moves to ${pos}`);
    if (!newPitcher) return;
    let vacated = '';
    if (newPitcher !== TBD) {
      vacated = playerPosition(newPitcher, draft) || '';
      if (vacated) delete draft[vacated];
      draft.P = newPitcher;
      moves.push(`${newPitcher} → P`);
    }
    if (displaced && displaced !== newPitcher) {
      const placed = await placePlayer(modal, draft, displaced, {
        title: `${oldPitcher} plays ${pos}`,
        vacated,
        locked: new Set(['P', pos]),
        moves,
      });
      if (!placed) return;
    }
    await finishPitchingMove(modal, start, draft, moves);
  }

  // P: "Take Tom off P" -- Tom goes to the bench and the coach picks who pitches.
  async function takeOffP(modal, start) {
    const draft = {...start};
    const oldPitcher = draft.P;
    delete draft.P;
    const moves = [`${oldPitcher} → Bench`];
    const newPitcher = await askWhoPitches(modal, draft, oldPitcher, `Take ${oldPitcher} off P`);
    if (!newPitcher) return;
    if (newPitcher !== TBD) {
      const vacated = playerPosition(newPitcher, draft);
      if (vacated) delete draft[vacated];
      draft.P = newPitcher;
      moves.push(`${newPitcher} → P`);
    }
    await finishPitchingMove(modal, start, draft, moves);
  }

  function applySaveStatusToDom() {
    const el = $('pde-save-status');
    if (!el) return;
    const status = window.CBPregameRotation.getStatus();
    const error = window.CBPregameRotation.getLastError();
    el.dataset.status = status;
    if (status === 'saving') {
      el.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Saving…';
    } else if (status === 'saved') {
      el.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i>Saved';
    } else if (status === 'failed') {
      const detail = error?.message ? `: ${esc(error.message)}` : '';
      el.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-1"></i>Save failed${detail} — tap to retry`;
    } else {
      el.innerHTML = '';
    }
  }

  // saveRotation()/retryRotationSave() both delegate to the shared store so
  // the payload they send is always built from the one canonical rotation
  // object game_logic.js's inning-structure toolbar mutates too — never a
  // stale per-module snapshot.
  function saveRotation() {
    window.CBPregameRotation.commitLocalChange(defaultRotationTitle(), false);
  }

  function retryRotationSave() {
    window.CBPregameRotation.retry(defaultRotationTitle(), false);
  }

  function applyPreset() {
    const select = $('pde-preset');
    if (select?.value) useSavedDefense('inning', select.value);
  }

  // ---- Saved Defense: fielders only ------------------------------------
  //
  // One rule for "This inning" and "Whole game". A saved defense fills the
  // fielding positions; it never sets, removes or moves the pitcher. Every
  // target inning keeps exactly the P it already has -- a filled P, an open
  // P, even a P marked Out (the absent-in-plan warning covers that) -- and a
  // P stored in an older saved defense is ignored. A saved fielder who can't
  // be placed (marked Out, pitching that inning, or already placed) leaves
  // that position Open, and the confirmation says why, so the result can
  // never hold one player twice.
  let usingSavedDefense = false;

  function fieldersOnly(source) {
    const fielders = {...(source || {})};
    delete fielders.P;
    return fielders;
  }

  function savedDefenseSource(preset) {
    let innings = preset?.innings;
    if (typeof innings === 'string') {
      try { innings = JSON.parse(innings); } catch (_) { innings = {}; }
    }
    if (!innings || typeof innings !== 'object') innings = {};
    const source = innings['1'] || Object.values(innings).find((value) => value && typeof value === 'object') || {};
    return source && typeof source === 'object' ? source : {};
  }

  function planSavedDefense(source, innings, targetKeys, available, rostered, fieldPositions) {
    const proposed = {};
    const openings = [];
    targetKeys.forEach((key) => {
      const existing = innings[key] && typeof innings[key] === 'object' ? innings[key] : {};
      const next = {};
      const placed = new Set();
      if (existing.P) {
        next.P = existing.P;
        placed.add(existing.P);
      }
      fieldPositions.forEach((pos) => {
        if (pos === 'P') return;
        const player = String(source[pos] || '').trim();
        if (!player) return;
        let reason = '';
        if (!rostered.has(player)) reason = 'roster';
        else if (!available.has(player)) reason = 'out';
        else if (player === next.P) reason = 'pitching';
        else if (placed.has(player)) reason = 'placed';
        if (reason) {
          openings.push({key, pos, player, reason});
          return;
        }
        next[pos] = player;
        placed.add(player);
      });
      proposed[key] = next;
    });
    return {proposed, openings};
  }

  function inningLabel(key) {
    return /^\d+$/.test(String(key)) ? inningOrdinal(key) : `Inning ${key}`;
  }

  // "the 2nd", "the 1st–3rd", "the 1st, 3rd and 5th"
  function inningsPhrase(keys) {
    const whole = keys.every((key) => /^\d+$/.test(String(key)));
    if (!whole) return keys.map(inningLabel).join(', ');
    const numbers = [...new Set(keys.map(Number))].sort((a, b) => a - b);
    const runs = [];
    numbers.forEach((n) => {
      const run = runs[runs.length - 1];
      if (run && n === run[1] + 1) run[1] = n;
      else runs.push([n, n]);
    });
    const parts = runs.map(([a, b]) => (a === b ? inningOrdinal(a) : `${inningOrdinal(a)}–${inningOrdinal(b)}`));
    const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0];
    return `the ${list}`;
  }

  function scopePhrase(scope, keys) {
    if (scope === 'game') {
      return keys.length === 1 ? `${inningsPhrase(keys)} inning` : `innings ${keys[0]}–${keys[keys.length - 1]}`;
    }
    return /^\d+$/.test(String(keys[0])) ? `${inningsPhrase(keys)} inning` : inningLabel(keys[0]);
  }

  function groupByInnings(items, keyOf) {
    const groups = new Map();
    items.forEach((item) => {
      const id = keyOf(item);
      if (!groups.has(id)) groups.set(id, {item, keys: []});
      groups.get(id).keys.push(item.key);
    });
    return [...groups.values()];
  }

  function savedDefenseSummary(scope, label, source, innings, targetKeys, openings) {
    const lines = [];
    const pitchers = groupByInnings(
      targetKeys.map((key) => ({key, name: String(innings[key]?.P || '')})),
      (item) => item.name
    );
    if (pitchers.length === 1 && !pitchers[0].item.name) {
      lines.push('No pitcher is planned yet. Saved defenses never set the pitcher.');
    } else if (scope !== 'game') {
      lines.push(`${pitchers[0].item.name} stays at P.`);
    } else {
      lines.push(`Pitchers stay as planned: ${pitchers.map(({item, keys}) => (
        `${item.name || 'no pitcher yet'} (${inningsPhrase(keys).replace(/^the /, '')})`
      )).join(' · ')}.`);
    }

    const savedPitcher = String(source.P || '').trim();
    if (savedPitcher && targetKeys.some((key) => innings[key]?.P !== savedPitcher)) {
      lines.push(`“${label}” was saved with ${savedPitcher} at P. Saved defenses set fielders only, so ${savedPitcher} isn't placed by it.`);
    }

    const why = {
      roster: (player) => `${player} isn't on the roster`,
      out: (player) => `${player} is marked Out for this game`,
      pitching: (player) => `${player} is pitching`,
      placed: (player) => `${player} is already placed`,
    };
    groupByInnings(openings, (item) => `${item.pos}|${item.player}|${item.reason}`)
      .forEach(({item, keys}) => {
        const where = scope === 'game' ? ` in ${inningsPhrase(keys)}` : '';
        lines.push(`${item.pos} is left Open${where}: ${why[item.reason](item.player)}.`);
      });
    return lines;
  }

  async function confirmSavedDefense(title, intro, lines) {
    let modal = $('pde-use-confirm');
    // Still closing from a previous answer: let it finish before reopening.
    if (modal && modal.style.display === 'block' && !modal.classList.contains('show')) {
      await new Promise((resolve) => modal.addEventListener('hidden.bs.modal', resolve, {once: true}));
    }
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'pde-use-confirm';
      modal.className = 'modal fade';
      modal.tabIndex = -1;
      modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title mb-0"></h5>
              <button type="button" class="btn-close" data-use-cancel aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <p class="mb-2 fw-semibold" data-use-intro></p>
              <ul class="mb-0 ps-3 small" data-use-lines></ul>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-outline-secondary" data-use-cancel>Cancel</button>
              <button type="button" class="btn btn-primary" data-use-confirm>Use Saved Defense</button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(modal);
    }
    modal.querySelector('.modal-title').textContent = title;
    modal.querySelector('[data-use-intro]').textContent = intro;
    modal.querySelector('[data-use-lines]').innerHTML = lines.map((line) => `<li>${esc(line)}</li>`).join('');

    // The coach's answer counts the moment it is tapped. Bootstrap ignores
    // hide() while the sheet is still opening, so a quick tap also closes
    // the sheet once it has finished opening.
    return new Promise((resolve) => {
      let answer = null;
      const instance = bootstrap.Modal.getOrCreateInstance(modal);
      const decide = (value) => {
        if (answer === null) {
          answer = value;
          resolve(value);
        }
        instance.hide();
      };
      const closeIfDecided = () => {
        if (answer !== null) instance.hide();
      };
      modal.querySelector('[data-use-confirm]').onclick = () => decide(true);
      modal.querySelectorAll('[data-use-cancel]').forEach((button) => {
        button.onclick = () => decide(false);
      });
      modal.addEventListener('shown.bs.modal', closeIfDecided);
      modal.addEventListener('hidden.bs.modal', () => {
        modal.removeEventListener('shown.bs.modal', closeIfDecided);
        if (answer === null) {
          answer = false;
          resolve(false);
        }
      }, {once: true});
      instance.show();
    });
  }

  async function useSavedDefense(scope, presetId) {
    if (usingSavedDefense || !presetId) return;
    usingSavedDefense = true;
    try {
      const response = await fetch(`/api/game_data/${gameId}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`Unable to load game defense (${response.status}).`);
      const data = await response.json();
      const preset = (data.rotation_templates || []).find((item) => (
        String(item.id) === String(presetId) && presetName(item)
      ));
      if (!preset) throw new Error('That saved defense is no longer available.');
      const label = presetName(preset);

      // Built on a DETACHED copy of the one canonical rotation, so Cancel
      // leaves shared state (and the next unrelated save) untouched.
      const rotation = window.CBPregameRotation.getRotation(defaultRotationTitle());
      const innings = JSON.parse(JSON.stringify(rotation.innings || {}));
      let targetKeys = [inning];
      if (scope === 'game') {
        targetKeys = Object.keys(innings).filter((key) => /^\d+$/.test(key)).sort((a, b) => Number(a) - Number(b));
        if (!targetKeys.length) targetKeys = ['1'];
      }

      const absent = new Set((data.absent_player_ids || []).map(Number));
      const names = (players) => new Set(
        players.map((player) => String(player.name || '').trim()).filter(Boolean)
      );
      const rostered = names(data.roster || []);
      const available = names((data.roster || []).filter((player) => !absent.has(Number(player.id))));
      const fieldPositions = Number(data.outfielder_count) === 4
        ? ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'LCF', 'RCF', 'RF']
        : ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'];
      const source = savedDefenseSource(preset);
      const plan = (from) => planSavedDefense(source, from, targetKeys, available, rostered, fieldPositions);
      const {proposed, openings} = plan(innings);

      const where = scopePhrase(scope, targetKeys);
      const confirmed = await confirmSavedDefense(
        `Use “${label}” for ${where}?`,
        `Fielders in ${where} will be replaced.`,
        savedDefenseSummary(scope, label, source, innings, targetKeys, openings)
      );
      if (!confirmed) return;

      // Apply only what the coach was shown: if the plan changed while the
      // sheet was open (another coach, a refresh), ask again instead.
      const current = window.CBPregameRotation.getRotation(defaultRotationTitle());
      if (JSON.stringify(plan(current.innings || {}).proposed) !== JSON.stringify(proposed)) {
        toast('The plan changed while you were deciding. Review it and use the saved defense again.', 'warning');
        return;
      }
      targetKeys.forEach((key) => { current.innings[key] = proposed[key]; });
      window.CBPregameRotation.commitLocalChange(current.title, false);
      const openCount = new Set(openings.map((item) => `${item.key}|${item.pos}`)).size;
      toast(
        openCount
          ? `${label} used for ${where}. ${openCount} position${openCount === 1 ? '' : 's'} left Open.`
          : `${label} used for ${where}.`,
        openCount ? 'warning' : 'success'
      );
    } catch (error) {
      toast(error.message || 'Unable to use the saved defense.', 'danger');
    } finally {
      usingSavedDefense = false;
    }
  }

  window.CBSavedDefense = {use: useSavedDefense};

  function presetModal() {
    let modal = $('pde-preset-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'pde-preset-modal';
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <div><h5 class="modal-title mb-0">Save this defense</h5><div class="small text-muted">Save the field as a Saved Defense you can use in any game.</div></div>
            <button class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <label class="form-label fw-semibold">Name</label>
            <input id="pde-name" class="form-control form-control-lg" maxlength="60" placeholder="e.g. #1 Defense">
            <div class="form-text">Saved defenses set fielders only. The pitcher isn't saved; choose the pitcher for each game.</div>
            <div class="d-grid mt-3"><button class="btn btn-primary btn-lg" id="pde-confirm">Save defense</button></div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function openPresetModal() {
    const open = positions().filter((pos) => pos !== 'P' && !alignment()[pos]);
    if (open.length) {
      toast(`Fill ${open.join(', ')} before saving. The pitcher isn't saved.`, 'warning');
      return;
    }
    const modal = presetModal();
    $('pde-name').value = '';
    $('pde-confirm').onclick = savePreset;
    bootstrap.Modal.getOrCreateInstance(modal).show();
    setTimeout(() => $('pde-name')?.focus(), 200);
  }

  async function savePreset() {
    if (busy) return;
    const input = $('pde-name');
    const name = input.value.trim();
    if (!name) {
      input.classList.add('is-invalid');
      return;
    }
    input.classList.remove('is-invalid');
    if (presets().some((preset) => presetName(preset).toLowerCase() === name.toLowerCase())) {
      toast(`A Saved Defense named “${name}” already exists.`, 'warning');
      return;
    }

    busy = true;
    const button = $('pde-confirm');
    button.disabled = true;
    button.textContent = 'Saving…';
    try {
      const response = await fetch('/api/starting-defense-template/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        // Fielders only: the pitcher is a per-game decision.
        body: JSON.stringify({title: name, innings: {'1': fieldersOnly(alignment())}}),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.status === 'error') throw new Error(result.message || 'Unable to save preset.');
      if (result.new_template) state.rotation_templates.push(result.new_template);
      bootstrap.Modal.getOrCreateInstance($('pde-preset-modal')).hide();
      filterWholeGameTemplates();
      render();
      toast(`${name} saved as a Saved Defense.`);
    } catch (error) {
      toast(error.message, 'danger');
    } finally {
      busy = false;
      button.disabled = false;
      button.textContent = 'Save defense';
    }
  }

  async function refresh() {
    if (window.CBPregameRotation.isSaveInFlightOrQueued()) {
      // A local defensive/structural edit (from either module) is still
      // saving or queued to save; a stale server refresh right now would
      // clobber it. Try again shortly once local saving has settled.
      scheduleRefresh(300);
      return;
    }
    if (window.CBPregameRotation.hasUnsyncedLocalState()) {
      // The last edit failed to save. Stay put rather than discarding it —
      // and do NOT reschedule ourselves here, or a permanently-failed save
      // would poll forever. The save-status "tap to retry" control (or a
      // further edit, which re-enters the queue above) is what moves this
      // forward next, not this refresh.
      return;
    }

    const revisionAtStart = window.CBPregameRotation.getLocalRevision();
    // A separate, later-started refresh (from either module — a second
    // scheduleRefresh() here, or game_logic.js's fetchLatestGameData())
    // can return and apply before this one does. Local-edit revision
    // checks alone don't change when a SERVER snapshot is accepted, so
    // they can't detect that case; the shared token orders server
    // refreshes against each other regardless of arrival order.
    const refreshToken = window.CBPregameRotation.beginServerRefresh();

    try {
      const response = await fetch(`/api/game_data/${gameId}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`Unable to load defense (${response.status})`);
      const freshState = await response.json();

      // Re-validate right before applying: a save can have started, queued,
      // failed, or a further edit (from either module) can have landed
      // while this request was in flight. Any of those makes this response
      // stale — discard it rather than clobbering whatever local state
      // exists now. canApplyRefresh() also rejects this response if a
      // refresh that started later has already been applied.
      if (!window.CBPregameRotation.canApplyRefresh(revisionAtStart, refreshToken)) {
        return;
      }

      state = freshState;
      window.CBPregameRotation.setFromServer(freshState.rotation, defaultRotationTitle(), refreshToken);

      if (isLiveNow()) {
        $(PANEL_ID)?.remove();
        restoreLegacy();
        return;
      }

      // ensureRotation() (via reconcileInningSelection()) moves `inning` to
      // a valid remaining key if the server's rotation no longer has the
      // one this panel was viewing — without recreating it.
      ensureRotation();
      filterWholeGameTemplates();
      render();
    } catch (error) {
      console.error('Pregame defense editor:', error);
    }
  }

  function scheduleRefresh(ms = 650) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refresh, ms);
  }

  function wire() {
    // The shared rotation store notifies on every local edit from EITHER
    // module (e.g. game_logic.js's Add Inning) and on every save-status
    // change, so this panel stays in sync without waiting on a network
    // refresh for either.
    window.CBPregameRotation.onChange(() => {
      if (!isLiveNow()) render();
    });
    window.CBPregameRotation.onStatusChange(() => applySaveStatusToDom());

    document.addEventListener('change', (event) => {
      const radio = event.target.closest?.('input[name="inning-radio"]');
      if (radio && !isLiveNow()) {
        inning = radio.value;
        ensureRotation();
        render();
      }
    }, true);

    ['addInningBtn', 'addSubInningBtn', 'removeInningBtn', 'pasteToSelectedBtn', 'clearInningBtn', 'copyPreviousInningBtn']
      .forEach((id) => $(id)?.addEventListener('click', () => scheduleRefresh()));

    $('rotationTemplateSelect')?.addEventListener('change', () => scheduleRefresh());
    $('startLiveGameBtnAction')?.addEventListener('click', () => scheduleRefresh(500));
    $('liveGameModeToggle')?.addEventListener('change', () => scheduleRefresh(500));

    window.addEventListener('orientationchange', () => setTimeout(syncLegacyVisibility, 150));
    window.addEventListener('resize', () => syncLegacyVisibility(), {passive: true});

    const liveOverlay = $('live-game-overlay');
    if (liveOverlay) {
      const liveObserver = new MutationObserver(syncLegacyVisibility);
      liveObserver.observe(liveOverlay, {attributes:true, attributeFilter:['class']});
    }
  }

  async function init() {
    installStyles();
    await refresh();
    wire();
    syncLegacyVisibility();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(init, 0), {once: true});
  } else {
    setTimeout(init, 0);
  }
})();