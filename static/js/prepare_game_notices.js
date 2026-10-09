// Prepare Game notices: a few short, persistent, inline notices instead of
// pop-ups while the coach plans.
//
// * Game rules not selected: one notice beside the Pitching Plan (the P
//   picker says it once too). Planning continues; Start Game still asks
//   about the rules before first pitch, and every pitching-eligibility check
//   is unchanged.
// * A player marked Out who is still in the batting order or the defense:
//   one notice per player, saying exactly where, with two plain actions --
//   Mark Playing, or Remove from plan (the consequence is spelled out before
//   the tap). Nothing is moved on its own.
// * "Choose the starting pitcher": tapping it opens the defense editor's own
//   P picker for the 1st inning.
//
// Data: the coachboard:readiness event game_prep_readiness.js publishes (no
// poller of its own), /api/game_data for roster, availability and lineup, and
// the shared CBPregameRotation store for the plan. Writes go through the
// existing writers only: /edit_lineup, /game/<id>/update_absences, and the
// store's /save_rotation queue.
(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);
  const STYLE_ID = 'cb-prepare-game-notices-styles';
  const RULES_ID = 'gm-rules-notice';
  const OUT_ID = 'gm-out-conflicts';
  const RULES_TEXT = "Game rules haven't been selected. You can keep planning, but confirm the rules before starting.";
  const STARTER = /starting pitcher/i;
  const OUT_REASON = /marked Out (?:is|are) in the 1st inning\. Fix it below\./;

  let latest = null;
  let busy = false;
  let renderToken = 0;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
  const $ = (id) => document.getElementById(id);

  function installStyles() {
    if ($(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .gm-inline-notice{
        border:1px solid #ecd9b4;border-left:4px solid #c58a17;border-radius:12px;background:#fffaf1;
        padding:10px 12px;margin:0 0 10px;color:#5c3d07;font-size:.8rem;line-height:1.35
      }
      .gm-inline-notice strong{color:#4a3106}
      .gm-inline-notice.is-danger{border-color:#efc6c1;border-left-color:#c2413a;background:#fff6f5;color:#6e1f1b}
      .gm-inline-notice .gm-notice-row{display:flex;align-items:center;justify-content:space-between;gap:10px}
      .gm-inline-notice .gm-notice-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
      .gm-inline-notice .btn{min-height:44px;border-radius:9px;font-weight:800;font-size:.78rem}
      .gm-inline-notice .gm-notice-consequence{display:block;margin-top:6px;font-size:.72rem;color:#7a4f0c}
      .gm-inline-notice + .gm-inline-notice{margin-top:-2px}
      #${OUT_ID} .gm-out-item + .gm-out-item{margin-top:10px;padding-top:10px;border-top:1px solid #f1d3cf}
      .cb-tap-starter{cursor:pointer;min-height:44px;display:flex!important;align-items:center;gap:8px}
      .cb-tap-starter::after{content:'Choose ›';margin-left:auto;font-weight:850;text-decoration:underline;white-space:nowrap}
      .cb-tap-out{cursor:pointer;min-height:44px;display:flex!important;align-items:center;gap:8px}
      .cb-tap-out::after{content:'Fix ›';margin-left:auto;font-weight:850;text-decoration:underline;white-space:nowrap}
      @media(max-width:440px){
        .gm-inline-notice .gm-notice-row{flex-direction:column;align-items:stretch}
        .gm-inline-notice .gm-notice-actions .btn{flex:1 1 140px}
      }
    `;
    document.head.appendChild(style);
  }

  // --- Game rules -------------------------------------------------------------

  function renderRulesNotice(response) {
    const board = $('pitching-board-v2');
    let notice = $(RULES_ID);
    const needed = response?.pitching_rules_selected === false && !response?.readiness?.is_live;
    if (!needed || !board) {
      notice?.remove();
      return;
    }
    if (!notice) {
      notice = document.createElement('div');
      notice.id = RULES_ID;
      notice.className = 'gm-inline-notice';
      notice.setAttribute('role', 'note');
      notice.innerHTML = `
        <div class="gm-notice-row">
          <span>${esc(RULES_TEXT)}</span>
          <button type="button" class="btn btn-outline-warning" data-gm-choose-rules>Choose rules</button>
        </div>`;
      notice.querySelector('[data-gm-choose-rules]').addEventListener('click', openRules);
    }
    // Beside the Pitching Plan, outside the card it re-renders.
    if (board.previousElementSibling !== notice) board.insertAdjacentElement('beforebegin', notice);
  }

  function openRules() {
    const edit = $('game-pitch-rule-edit-v2');
    const strip = $('game-pitching-rules-v2');
    strip?.scrollIntoView({behavior: 'smooth', block: 'center'});
    if (edit && edit.getAttribute('aria-expanded') !== 'true') edit.click();
  }

  // --- Starting pitcher ------------------------------------------------------

  function syncStarterTargets() {
    ['gm-mobile-start-reason', 'start-live-blockers'].forEach((id) => {
      const node = $(id);
      if (!node) return;
      // "Fix it below" scrolls to the Out-player notice -- only when the
      // reason is that alone, so a tap never hides another reason.
      const outOnly = OUT_REASON.test(node.textContent || '') && !STARTER.test(node.textContent || '')
        && Boolean($(OUT_ID)) && !node.hidden && !node.classList.contains('d-none');
      node.classList.toggle('cb-tap-out', outOnly);
      const tappable = STARTER.test(node.textContent || '') && !node.hidden && !node.classList.contains('d-none');
      node.classList.toggle('cb-tap-starter', tappable);
      if (tappable) {
        if (node.getAttribute('role') !== 'button') node.setAttribute('role', 'button');
        if (node.tabIndex !== 0) node.tabIndex = 0;
        const label = 'Choose the starting pitcher for the 1st inning';
        if (node.getAttribute('aria-label') !== label) node.setAttribute('aria-label', label);
      } else if (node.getAttribute('role') === 'button') {
        node.removeAttribute('role');
        node.removeAttribute('tabindex');
        node.removeAttribute('aria-label');
      }
    });
  }

  function chooseStarter() {
    if (window.CBPregameDefense?.choosePosition?.('1', 'P')) return;
    (document.getElementById('pregame-defense-editor-v3') || $('rotation-card-container'))
      ?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  document.addEventListener('click', (event) => {
    if (event.target.closest('.cb-tap-starter')) chooseStarter();
    else if (event.target.closest('.cb-tap-out')) $(OUT_ID)?.scrollIntoView({behavior: 'smooth', block: 'center'});
  });
  document.addEventListener('keydown', (event) => {
    if ((event.key === 'Enter' || event.key === ' ') && event.target.closest?.('.cb-tap-starter')) {
      event.preventDefault();
      chooseStarter();
    }
  });

  // --- Out players still in the plan -------------------------------------------

  const ordinal = (key) => {
    const n = Number(key);
    if (!Number.isInteger(n)) return `inning ${key}`;
    const tail = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[n % 10] || 'th');
    return `${n}${tail}`;
  };

  function listed(items) {
    return items.length > 1 ? `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}` : items[0];
  }

  // Where `name` is placed in the plan: [{key, pos}], in inning order.
  function planSpots(name) {
    const innings = window.CBPregameRotation?.getRotation()?.innings || {};
    return Object.keys(innings)
      .sort((a, b) => parseFloat(a) - parseFloat(b))
      .flatMap((key) => Object.entries(innings[key] || {})
        .filter(([, who]) => String(who || '').trim() === name)
        .map(([pos]) => ({key, pos})));
  }

  function spotsPhrase(spots) {
    const byPos = new Map();
    spots.forEach(({key, pos}) => {
      if (!byPos.has(pos)) byPos.set(pos, []);
      byPos.get(pos).push(ordinal(key));
    });
    return listed([...byPos.entries()].map(([pos, keys]) => `${pos} in the ${listed(keys)}`));
  }

  function needsGameData(readiness) {
    if ((readiness?.lineup_unavailable_names || []).length) return true;
    return (readiness?.incomplete_innings || []).some((item) => (item?.unavailable || []).length);
  }

  async function renderOutConflicts(readiness) {
    const token = ++renderToken;
    const host = $('pregame-checklist-container');
    let box = $(OUT_ID);
    if (!host || readiness?.is_live || !needsGameData(readiness)) {
      if (!busy) box?.remove();
      return;
    }
    let data;
    try {
      const response = await fetch(`/api/game_data/${gameId}`, {cache: 'no-store'});
      if (!response.ok) return;
      data = await response.json();
    } catch (_) {
      return;
    }
    if (token !== renderToken || busy) return;

    const absent = new Set((data.absent_player_ids || []).map(Number));
    const byName = new Map((data.roster || []).map((player) => [String(player.name || '').trim(), player]));
    const lineupNames = new Set(readiness.lineup_unavailable_names || []);
    const defenseNames = new Set((readiness.incomplete_innings || []).flatMap((item) => item?.unavailable || []));
    const names = [...new Set([...lineupNames, ...defenseNames])].sort();
    const items = names.map((name) => {
      const player = byName.get(name);
      const spots = planSpots(name);
      const where = [];
      if (lineupNames.has(name)) where.push('the batting order');
      if (spots.length) where.push(`the defense (${spotsPhrase(spots)})`);
      const status = player && absent.has(Number(player.id)) ? 'is marked Out' : 'is no longer on the roster';
      const effects = [];
      if (lineupNames.has(name)) effects.push('comes out of the batting order');
      if (spots.length) effects.push(`leaves ${listed([...new Set(spots.map((spot) => spot.pos))])} open where they were placed`);
      return {name, player, where, status, effects, canPlay: Boolean(player && absent.has(Number(player.id)))};
    }).filter((item) => item.where.length);

    if (!items.length) {
      box?.remove();
      return;
    }
    if (!box) {
      box = document.createElement('div');
      box.id = OUT_ID;
      box.className = 'gm-inline-notice is-danger';
      box.setAttribute('role', 'alert');
      box.addEventListener('click', onConflictAction);
    }
    const anchor = $('coach-game-readiness-v2') || host.querySelector(':scope > .d-flex:first-child');
    if (anchor && anchor.nextElementSibling !== box) anchor.insertAdjacentElement('afterend', box);
    else if (!anchor && box.parentElement !== host) host.prepend(box);

    box.innerHTML = items.map((item) => `
      <div class="gm-out-item" data-gm-out-player="${esc(item.name)}">
        <div><strong>${esc(item.name)} ${esc(item.status)}</strong> but is still in ${esc(listed(item.where))}.</div>
        <div class="gm-notice-actions">
          ${item.canPlay ? `<button type="button" class="btn btn-outline-secondary" data-gm-out-action="play">Mark ${esc(item.name)} Playing</button>` : ''}
          <button type="button" class="btn btn-outline-danger" data-gm-out-action="remove">Remove from plan</button>
        </div>
        <span class="gm-notice-consequence">Remove from plan: ${esc(item.name)} ${esc(listed(item.effects))}. Nothing else changes.</span>
      </div>`).join('');
    box.dataset.gmGameData = '1';
    box._gameData = data;
  }

  function waitForRotationSave(store) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => finish(new Error('The defense is still saving. Check your connection.')), 20000);
      function finish(error) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        error ? reject(error) : resolve();
      }
      store.onStatusChange((status, error) => {
        if (status === 'saved') finish();
        else if (status === 'failed') finish(error || new Error('The defense was not saved.'));
      });
    });
  }

  async function removeFromPlan(name, data) {
    const done = [];
    const player = (data.roster || []).find((item) => String(item.name || '').trim() === name);
    const lineup = data.lineup;
    const entries = lineup?.lineup_entries || [];
    const keep = entries.filter((entry) => String(entry.name || '').trim() !== name && entry.player_id != null);
    if (lineup?.id && keep.length !== entries.length) {
      if (!keep.length) throw new Error(`${name} is the only batter, so the batting order wasn't changed.`);
      const response = await fetch(`/edit_lineup/${lineup.id}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          title: lineup.title,
          lineup_player_ids: keep.map((entry) => entry.player_id),
          associated_game_id: gameId,
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.status !== 'success') {
        throw new Error(`The batting order wasn't changed. ${result.message || ''}`.trim());
      }
      done.push('batting order');
    }

    const store = window.CBPregameRotation;
    const spots = planSpots(name);
    if (spots.length && store) {
      if (store.isSaveInFlightOrQueued() || store.hasUnsyncedLocalState()) {
        throw new Error(`${done.length ? 'The batting order was updated, but the' : 'The'} defense is still saving. Try again in a moment.`);
      }
      const rotation = store.getRotation();
      spots.forEach(({key, pos}) => {
        if (String(rotation.innings[key]?.[pos] || '').trim() === name) delete rotation.innings[key][pos];
      });
      const saved = waitForRotationSave(store);
      store.commitLocalChange(rotation.title, true);
      await saved;
      done.push('defense');
    }
    return {player, done};
  }

  async function markPlaying(name, data) {
    const player = (data.roster || []).find((item) => String(item.name || '').trim() === name);
    if (!player) throw new Error(`${name} isn't on the roster.`);
    const stillOut = (data.absent_player_ids || []).map(Number).filter((id) => id !== Number(player.id));
    const body = new URLSearchParams();
    stillOut.forEach((id) => body.append('absent_players', String(id)));
    const response = await fetch(`/game/${gameId}/update_absences`, {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body,
    });
    if (!response.ok) throw new Error('Availability was not changed. Refresh and try again.');
  }

  async function onConflictAction(event) {
    const button = event.target.closest('[data-gm-out-action]');
    if (!button || busy) return;
    const box = $(OUT_ID);
    const item = button.closest('[data-gm-out-player]');
    const name = item?.dataset.gmOutPlayer;
    const data = box?._gameData;
    if (!name || !data) return;
    busy = true;
    box.querySelectorAll('button').forEach((node) => { node.disabled = true; });
    const original = button.textContent;
    button.textContent = 'Saving…';
    try {
      if (button.dataset.gmOutAction === 'play') {
        await markPlaying(name, data);
      } else {
        await removeFromPlan(name, data);
      }
      window.location.reload();
    } catch (error) {
      busy = false;
      button.textContent = original;
      box.querySelectorAll('button').forEach((node) => { node.disabled = false; });
      let note = item.querySelector('.gm-notice-error');
      if (!note) {
        note = document.createElement('span');
        note.className = 'gm-notice-consequence gm-notice-error';
        note.setAttribute('role', 'status');
        item.appendChild(note);
      }
      note.textContent = error?.message || 'That change was not saved.';
    }
  }

  // --- Batting Order card ------------------------------------------------------

  function syncLineupIssue(readiness) {
    const card = $('gameBattingOrderCard');
    if (!card) return;
    const out = readiness?.lineup_unavailable_names || [];
    const missing = readiness?.lineup_missing_names || [];
    let issue = '';
    if (!readiness?.lineup_ready && Number(readiness?.lineup_count) > 0) {
      if (out.length) issue = out.length === 1 ? `${out[0]} is Out` : `${out.length} are Out`;
      else if (readiness.lineup_mode === 'bat_all' && missing.length) issue = `add ${missing.length}`;
      else issue = `${readiness.lineup_count} of ${readiness.lineup_expected_count}`;
    }
    if ((card.dataset.cbLineupIssue || '') !== issue) card.dataset.cbLineupIssue = issue;
    const subtitle = card.querySelector('.card-header .small.text-muted');
    const count = Number(readiness?.lineup_count) || 0;
    if (subtitle && count > 0) {
      // Same wording game_management_visual_polish.js writes, so they agree.
      const text = issue ? `${count} hitters · ${issue}` : `${count} hitters set`;
      if (subtitle.textContent.trim() !== text) subtitle.textContent = text;
    }
  }

  // --- Wiring -------------------------------------------------------------------

  document.addEventListener('coachboard:readiness', (event) => {
    if (Number(event.detail?.game_id) !== gameId) return;
    latest = event.detail?.response || null;
    const readiness = latest?.readiness || {};
    renderRulesNotice(latest);
    syncLineupIssue(readiness);
    syncStarterTargets();
    void renderOutConflicts(readiness);
  });

  function start() {
    installStyles();
    const observer = new MutationObserver(() => {
      syncStarterTargets();
      if (latest && !$(RULES_ID)) renderRulesNotice(latest);
    });
    observer.observe(document.body, {childList: true, subtree: true, characterData: true});
    syncStarterTargets();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
