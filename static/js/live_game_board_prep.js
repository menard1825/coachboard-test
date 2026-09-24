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

  function wholeInningKeys() {
    ensureRotation();
    return Object.keys(state.rotation.innings || {})
      .filter((key) => /^\d+$/.test(String(key)))
      .sort((a, b) => Number(a) - Number(b));
  }

  function playingTimeSummary() {
    // Regulation inning slots are created ahead of time, but an entirely empty
    // inning is not yet a coaching plan. Do not turn those empty future slots
    // into artificial bench innings in the playing-time totals.
    const inningKeys = wholeInningKeys().filter((key) => {
      const source = state.rotation.innings[key];
      return source &&
        typeof source === 'object' &&
        Object.values(source).some((name) => String(name || '').trim());
    });
    if (!inningKeys.length) return '';

    const positionOrder = positions();

    const rows = presentPlayers().map((player) => {
      const counts = new Map();
      let fieldInnings = 0;
      let benchInnings = 0;

      inningKeys.forEach((key) => {
        const source = state.rotation.innings[key] || {};
        const position = playerPosition(player.name, source);

        if (position) {
          fieldInnings += 1;
          counts.set(
            position,
            (counts.get(position) || 0) + 1
          );
        } else {
          benchInnings += 1;
        }
      });

      const chips = positionOrder
        .filter((position) => counts.get(position))
        .map((position) => (
          `<span class="pde-time-chip">${esc(position)} × ${counts.get(position)}</span>`
        ));

      if (benchInnings) {
        chips.push(
          `<span class="pde-time-chip bench">BN × ${benchInnings}</span>`
        );
      }

      return `
        <div class="pde-time-row" data-player-name="${esc(player.name)}">
          <div class="pde-time-main">
            <strong class="pde-time-name">${esc(player.name)}</strong>
            <span class="pde-time-total">${fieldInnings} field · ${benchInnings} bench</span>
          </div>
          <div class="pde-time-chips">${chips.join('')}</div>
        </div>`;
    }).join('');

    return `
      <section class="pde-playing-time" id="pde-playing-time-summary">
        <div class="pde-playing-time-head">
          <div>
            <strong>Playing Time Summary</strong>
            <span>${inningKeys.length} planned inning${inningKeys.length === 1 ? '' : 's'} · updates as you move players</span>
          </div>
        </div>
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
    return modal;
  }

  function choosePlayer(pos) {
    const modal = playerModal();
    const source = alignment();
    const occupant = source[pos] || '';
    modal.querySelector('.modal-title').textContent = `${pos} — Choose Player`;
    $('pde-help').textContent = occupant
      ? `Current: ${occupant}. Replacing him moves him to the bench.`
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

    const list = $('pde-list');
    list.innerHTML = `
      ${occupant ? `<button class="list-group-item list-group-item-action pde-choice text-danger" data-clear="1"><strong>Move ${esc(occupant)} to Bench</strong><small>Leave ${esc(pos)} open.</small></button>` : ''}
      ${choices.map(({player, position}) => `
        <button class="list-group-item list-group-item-action pde-choice" data-player="${esc(player.name)}">
          <strong>${esc(player.name)}</strong>
          <small>${position === pos
            ? `Currently at ${esc(pos)}`
            : position
              ? (occupant && occupant !== player.name
                  ? `Currently at ${esc(position)} — swaps with ${esc(occupant)}`
                  : `Currently at ${esc(position)} — ${esc(position)} will become open`)
              : 'On bench this inning'}</small>
        </button>`).join('')}`;

    list.onclick = (event) => {
      const choice = event.target.closest('.pde-choice');
      if (!choice) return;

      const next = {...alignment()};
      let message = '';
      if (choice.dataset.clear) {
        const old = next[pos];
        delete next[pos];
        message = `${old} moved to the bench. ${pos} is open.`;
      } else {
        const playerName = choice.dataset.player;
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
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      render();
      // Optimistic: describe the local change now rather than waiting on the
      // network. Save outcome (including failure) is reported by the
      // persistent save-status indicator, not by this toast.
      toast(message);
      saveRotation();
    };

    bootstrap.Modal.getOrCreateInstance(modal).show();
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
    if (!select?.value) return;
    const preset = presets().find((item) => String(item.id) === String(select.value));
    const name = presetName(preset);
    if (!preset || !confirm(`Apply “${name}” to Inning ${inning}? Only this inning will be replaced.`)) return;

    const source = preset.innings?.['1'] || Object.values(preset.innings || {})[0] || {};
    const available = new Set(presentPlayers().map((player) => player.name));
    const next = {};
    const unavailable = [];

    positions().forEach((pos) => {
      const playerName = source[pos];
      if (!playerName) return;
      if (available.has(playerName)) next[pos] = playerName;
      else unavailable.push(playerName);
    });

    state.rotation.innings[inning] = next;
    render();
    toast(
      unavailable.length
        ? `Saved defense used. Open spots remain because ${[...new Set(unavailable)].join(', ')} is unavailable.`
        : next.P ? `${name} applied to Inning ${inning}.` : `${name} applied. Choose the pitcher for Inning ${inning}.`,
      unavailable.length ? 'warning' : 'success'
    );
    saveRotation();
  }

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
            <div class="form-text">Pitcher may remain open so you can choose him for each game.</div>
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
      toast(`Fill ${open.join(', ')} before saving. Pitcher may remain open.`, 'warning');
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
        body: JSON.stringify({title: name, innings: {'1': {...alignment()}}}),
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