// Use Previous Game Setup (Prepare Game).
//
// Shows exactly what the most recent earlier game's batting order and
// starting defense would give today's game, lets the coach pick either or
// both, then applies them through the paths Prepare Game already uses:
//
// * Batting order: /add_lineup or /edit_lineup, as Save Lineup does
//   (validate_lineup_payload + sync_lineup on the server).
// * Starting defense: the shared CBPregameRotation store and its single
//   /save_rotation queue (duplicate check + game write lock on the server),
//   so it can't race the tap field or the inning tools.
//
// The preview comes from /api/game/<id>/previous-setup, which only reads.
// The earlier game is never written. The pitcher is never copied. Anything
// already planned for today is replaced only when the coach turns it on.
(() => {
  'use strict';

  const launch = document.getElementById('previousSetupLaunch');
  const modalEl = document.getElementById('previousSetupModal');
  if (!launch || !modalEl || !window.bootstrap) return;

  const gameId = Number(launch.dataset.gameId);
  const STYLE_ID = 'cb-previous-setup-styles';
  const body = document.getElementById('previousSetupBody');
  const sourceEl = document.getElementById('previousSetupSource');
  const applyBtn = document.getElementById('previousSetupApplyBtn');
  const cancelBtn = document.getElementById('previousSetupCancelBtn');
  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  const store = window.CBPregameRotation;

  let preview = null;
  let applying = false;
  let saveWaiter = null;
  let finished = false;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #previousSetupLaunch{
        display:flex;align-items:center;justify-content:space-between;gap:12px;
        border:1px solid #cfdae9;border-left:4px solid #2f6fd6;border-radius:13px;
        background:#fff;padding:11px 12px;margin:0 0 10px;box-shadow:0 2px 8px rgba(16,24,40,.04)
      }
      #previousSetupLaunch .cb-psl-copy{min-width:0}
      #previousSetupLaunch .cb-psl-title{font-size:.84rem;font-weight:900;color:#172033}
      #previousSetupLaunch .cb-psl-help{font-size:.7rem;line-height:1.35;color:#667085;margin-top:2px}
      #previousSetupLaunch .cb-psl-button{flex:0 0 auto;min-height:44px;border-radius:9px;font-size:.78rem;font-weight:850;white-space:nowrap}
      #previousSetupLaunch.is-used{border-left-color:#1f8a4c;background:#f6fbf8}
      #previousSetupLaunch.is-used .cb-psl-title{color:#176b38}
      #previousSetupLaunch[data-state="partial"]{border-left-color:#c58a17;background:#fffaf1}
      #previousSetupLaunch[data-state="partial"] .cb-psl-title{color:#8a5a13}
      #previousSetupLaunch .cb-psl-parts{list-style:none;margin:3px 0 0;padding:0;font-size:.74rem;line-height:1.4;color:#344054}
      #previousSetupLaunch .cb-psl-parts .is-not-copied{color:#8a5a13;font-weight:750}
      #previousSetupLaunch .cb-psl-result{
        margin:0 0 6px;padding:7px 9px;border-radius:8px;background:#e5f5ea;color:#145c30;
        font-size:.8rem;font-weight:850;line-height:1.3
      }
      #previousSetupLaunch .cb-psl-result[hidden]{display:none!important}
      #previousSetupModal .modal-content{border:0;border-radius:16px;overflow:hidden}
      #previousSetupModal .cb-ps-kicker{font-size:.6rem;text-transform:uppercase;letter-spacing:.09em;color:#667085;font-weight:900}
      #previousSetupModal .modal-title{font-size:1.08rem;font-weight:900;color:#172033}
      #previousSetupModal .cb-ps-subtitle{font-size:.74rem;color:#667085;margin-top:2px}
      #previousSetupModal .modal-body{background:#f7f9fb;padding:12px}
      #previousSetupModal .cb-ps-section-title{font-size:.66rem;text-transform:uppercase;letter-spacing:.08em;color:#667085;font-weight:900;margin:2px 2px 6px}
      #previousSetupModal .cb-ps-choices{display:grid;gap:8px;margin-bottom:14px}
      #previousSetupModal .cb-ps-choice{
        display:grid;grid-template-columns:28px minmax(0,1fr);gap:10px;align-items:start;
        min-height:56px;border:1.5px solid #dfe4ea;border-radius:12px;background:#fff;padding:11px 12px;cursor:pointer;margin:0;text-align:left
      }
      #previousSetupModal .cb-ps-choice:has(input:checked){border-color:#2f6fd6;background:#f3f7ff}
      #previousSetupModal .cb-ps-choice.is-disabled{opacity:.6;cursor:default}
      #previousSetupModal .cb-ps-choice input{width:24px;height:24px;margin:1px 0 0}
      #previousSetupModal .cb-ps-choice-name{font-size:.9rem;font-weight:850;color:#172033}
      #previousSetupModal .cb-ps-choice-detail{font-size:.74rem;color:#526176;line-height:1.35;margin-top:1px}
      #previousSetupModal .cb-ps-replace{font-size:.74rem;color:#8a4b00;font-weight:750;line-height:1.35;margin-top:4px}
      #previousSetupModal .cb-ps-preview{display:grid;gap:10px}
      #previousSetupModal .cb-ps-card{border:1px solid #dfe4ea;border-radius:12px;background:#fff;padding:10px 12px}
      #previousSetupModal .cb-ps-card[hidden]{display:none!important}
      #previousSetupModal .cb-ps-card h6{font-size:.82rem;font-weight:900;margin:0 0 6px;color:#172033}
      #previousSetupModal .cb-ps-order{list-style:none;margin:0;padding:0;display:grid;gap:2px}
      #previousSetupModal .cb-ps-order li,#previousSetupModal .cb-ps-field li{display:flex;align-items:center;gap:8px;min-height:30px;font-size:.84rem}
      #previousSetupModal .cb-ps-num,#previousSetupModal .cb-ps-pos{
        flex:0 0 34px;height:26px;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;
        background:#edf2f8;color:#294a84;font-weight:900;font-size:.74rem
      }
      #previousSetupModal .cb-ps-field{list-style:none;margin:0;padding:0;display:grid;gap:2px}
      #previousSetupModal .cb-ps-open .cb-ps-pos{background:#fff0d0;color:#8a5a13}
      #previousSetupModal .cb-ps-open .cb-ps-name{color:#8a5a13;font-weight:750}
      #previousSetupModal .cb-ps-keep .cb-ps-pos{background:#e5f5ea;color:#176b38}
      #previousSetupModal .cb-ps-tag{font-size:.66rem;font-weight:800;border-radius:999px;padding:1px 7px;background:#e8f0ff;color:#294a84;white-space:nowrap}
      #previousSetupModal .cb-ps-note{font-size:.74rem;color:#526176;line-height:1.35;margin:6px 0 0}
      #previousSetupModal .cb-ps-note.warn{color:#8a4b00}
      #previousSetupModal .cb-ps-footer{
        position:sticky;bottom:0;background:#fff;border-top:1px solid #e5e9ef;
        padding:10px 12px calc(10px + env(safe-area-inset-bottom));
        display:grid;grid-template-columns:auto 1fr;gap:8px;flex-wrap:nowrap
      }
      #previousSetupModal .cb-ps-footer .btn{min-height:48px;border-radius:10px;font-weight:850;margin:0}
      @media(min-width:768px){
        #previousSetupModal .modal-dialog{max-width:720px}
        #previousSetupModal .cb-ps-preview{grid-template-columns:1fr 1fr;align-items:start}
      }
      @media(max-width:575.98px){
        #previousSetupLaunch{display:grid;grid-template-columns:1fr;padding:10px}
        #previousSetupLaunch .cb-psl-button{width:100%}
      }
    `;
    document.head.appendChild(style);
  }

  function setBody(html) {
    body.innerHTML = html;
  }

  function message(kind, text) {
    return `<div class="alert alert-${kind} py-2 mb-3" role="status">${esc(text)}</div>`;
  }

  // --- Choices --------------------------------------------------------------

  function lineupChoice(lineup) {
    const usable = lineup.available && lineup.player_ids.length > 0;
    let detail = 'Last game has no batting order.';
    if (lineup.available && !usable) detail = "No one from last game's batting order is playing today.";
    if (usable) {
      detail = plural(lineup.player_ids.length, 'batter');
      if (lineup.added.length) detail += ` · ${lineup.added.length} new at the bottom`;
      if (lineup.skipped.length) detail += ` · ${lineup.skipped.length} not copied`;
    }
    return {
      key: 'lineup',
      usable,
      name: lineup.replaces_current ? "Replace today's batting order" : 'Batting order',
      detail,
      replace: usable && lineup.replaces_current
        ? `Today's batting order (${plural(lineup.current_count, 'batter')}) will be replaced.`
        : '',
      checked: usable && !lineup.replaces_current,
    };
  }

  function defenseChoice(defense) {
    const usable = defense.available && defense.copied_count > 0;
    let detail = 'Last game has no starting defense.';
    if (defense.available && !usable) detail = "None of last game's starting fielders are available today.";
    if (usable) {
      const total = defense.copied_count + defense.open_count;
      detail = `1st inning · ${defense.copied_count} of ${total} fielders · pitcher not copied`;
    }
    return {
      key: 'defense',
      usable,
      name: defense.replaces_current ? "Replace today's starting defense" : 'Starting defense',
      detail,
      replace: usable && defense.replaces_current
        ? `Today's 1st-inning fielders (${defense.current_fielder_count}) will be replaced. Later innings stay as they are.`
        : '',
      checked: usable && !defense.replaces_current,
    };
  }

  function choiceHtml(choice) {
    return `
      <label class="cb-ps-choice${choice.usable ? '' : ' is-disabled'}" for="previousSetupUse-${choice.key}">
        <input class="form-check-input" type="checkbox" id="previousSetupUse-${choice.key}" data-ps-choice="${choice.key}"
          ${choice.checked ? 'checked' : ''} ${choice.usable ? '' : 'disabled'}>
        <span>
          <span class="cb-ps-choice-name d-block">${esc(choice.name)}</span>
          <span class="cb-ps-choice-detail d-block">${esc(choice.detail)}</span>
          ${choice.replace ? `<span class="cb-ps-replace d-block"><i class="bi bi-exclamation-triangle-fill me-1" aria-hidden="true"></i>${esc(choice.replace)}</span>` : ''}
        </span>
      </label>`;
  }

  // --- Preview --------------------------------------------------------------

  function lineupPreview(lineup) {
    const rows = lineup.batters.map((batter) => `
      <li><span class="cb-ps-num">${batter.order}</span><span class="flex-grow-1">${esc(batter.name)}</span>
        ${batter.added ? '<span class="cb-ps-tag">New today</span>' : ''}</li>`).join('');
    const notes = [];
    if (lineup.added.length) {
      notes.push(`<p class="cb-ps-note">Bat Everyone: ${esc(lineup.added.map((p) => p.name).join(', '))} ${lineup.added.length === 1 ? "wasn't" : "weren't"} in last game's order, so they bat at the bottom. You can move them in Edit Lineup.</p>`);
    }
    if (lineup.skipped.length) {
      notes.push(`<p class="cb-ps-note warn">Not copied: ${esc(lineup.skipped.map((p) => `${p.name} (${p.label})`).join(', '))}.</p>`);
    }
    if (lineup.trimmed.length) {
      notes.push(`<p class="cb-ps-note warn">Fixed Lineup is ${lineup.expected_count} batters, so ${esc(lineup.trimmed.map((p) => p.name).join(', '))} ${lineup.trimmed.length === 1 ? 'is' : 'are'} left off.</p>`);
    }
    if (lineup.short_by > 0) {
      notes.push(`<p class="cb-ps-note warn">Add ${plural(lineup.short_by, 'more batter')} in Edit Lineup after copying.</p>`);
    }
    return `
      <section class="cb-ps-card" data-ps-preview="lineup">
        <h6><i class="bi bi-card-list me-1" aria-hidden="true"></i>Batting order</h6>
        <ol class="cb-ps-order">${rows}</ol>
        ${notes.join('')}
      </section>`;
  }

  function defensePreview(defense) {
    const pitcherRow = defense.today_pitcher
      ? `<li class="cb-ps-keep"><span class="cb-ps-pos">P</span><span class="cb-ps-name flex-grow-1">${esc(defense.today_pitcher)}</span><span class="cb-ps-tag">Stays</span></li>`
      : '<li class="cb-ps-open"><span class="cb-ps-pos">P</span><span class="cb-ps-name flex-grow-1">Choose today\'s pitcher</span></li>';
    const rows = defense.positions.map((row) => {
      if (row.status === 'copy') {
        return `<li><span class="cb-ps-pos">${esc(row.position)}</span><span class="cb-ps-name flex-grow-1">${esc(row.player)}</span></li>`;
      }
      const why = row.player ? `Open · ${row.player} — ${row.label}` : 'Open';
      return `<li class="cb-ps-open"><span class="cb-ps-pos">${esc(row.position)}</span><span class="cb-ps-name flex-grow-1">${esc(why)}</span></li>`;
    }).join('');
    const notes = [];
    if (defense.previous_pitcher) {
      notes.push(`<p class="cb-ps-note">Last game's pitcher (${esc(defense.previous_pitcher)}) isn't copied. The pitcher is chosen for each game.</p>`);
    }
    if (defense.unused_positions.length) {
      notes.push(`<p class="cb-ps-note warn">Not used with today's outfield: ${esc(defense.unused_positions.map((p) => `${p.position} (${p.player})`).join(', '))}.</p>`);
    }
    if (defense.open_count) {
      notes.push(`<p class="cb-ps-note warn">${plural(defense.open_count, 'position')} will be left Open for you to fill.</p>`);
    }
    return `
      <section class="cb-ps-card" data-ps-preview="defense">
        <h6><i class="bi bi-shield-shaded me-1" aria-hidden="true"></i>Starting defense · 1st inning</h6>
        <ul class="cb-ps-field">${pitcherRow}${rows}</ul>
        ${notes.join('')}
      </section>`;
  }

  function selected() {
    return {
      lineup: Boolean(body.querySelector('[data-ps-choice="lineup"]')?.checked),
      defense: Boolean(body.querySelector('[data-ps-choice="defense"]')?.checked),
    };
  }

  function syncSelection() {
    const pick = selected();
    body.querySelectorAll('[data-ps-preview]').forEach((card) => {
      card.hidden = !pick[card.dataset.psPreview];
    });
    const empty = body.querySelector('[data-ps-empty]');
    if (empty) empty.hidden = pick.lineup || pick.defense;
    applyBtn.disabled = applying || !(pick.lineup || pick.defense);
    applyBtn.textContent = pick.lineup && pick.defense
      ? 'Copy lineup & defense'
      : pick.lineup ? 'Copy batting order'
        : pick.defense ? 'Copy starting defense' : 'Choose what to copy';
  }

  function render(data) {
    preview = data;
    sourceEl.textContent = `From vs ${data.source.opponent} · ${data.source.date_label}`;
    const choices = [lineupChoice(data.lineup), defenseChoice(data.defense)];
    setBody(`
      <div id="previousSetupFeedback"></div>
      <div class="cb-ps-section-title">What to copy</div>
      <div class="cb-ps-choices">${choices.map(choiceHtml).join('')}</div>
      <div class="cb-ps-section-title">What will be copied</div>
      <p class="cb-ps-note mb-2" data-ps-empty hidden>Choose the batting order, the starting defense, or both.</p>
      <div class="cb-ps-preview">
        ${choices[0].usable ? lineupPreview(data.lineup) : ''}
        ${choices[1].usable ? defensePreview(data.defense) : ''}
      </div>`);
    body.querySelectorAll('[data-ps-choice]').forEach((input) => input.addEventListener('change', syncSelection));
    syncSelection();
  }

  async function fetchPreview() {
    const response = await fetch(`/api/game/${gameId}/previous-setup`, {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.status !== 'success') throw new Error(data.message || 'Unable to load last game.');
    return data;
  }

  async function loadPreview() {
    preview = null;
    applyBtn.disabled = true;
    applyBtn.textContent = 'Copy';
    sourceEl.textContent = '';
    setBody('<div class="text-center text-muted py-4"><span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Loading last game…</div>');
    try {
      const data = await fetchPreview();
      if (!data.available) {
        setBody(message('info', data.message || 'There is nothing to copy.'));
        return;
      }
      render(data);
    } catch (error) {
      setBody(message('danger', error.message || 'Unable to load last game.'));
    }
  }

  // --- Apply ----------------------------------------------------------------

  function feedback(kind, text) {
    const host = document.getElementById('previousSetupFeedback');
    if (host) host.innerHTML = message(kind, text);
    body.scrollTop = 0;
  }

  function cleanAlignment(alignment) {
    const clean = {};
    Object.keys(alignment || {}).sort().forEach((pos) => {
      const name = String(alignment[pos] || '').trim();
      if (name) clean[pos] = name;
    });
    return clean;
  }

  if (store) {
    store.onStatusChange((status, error) => {
      if (!saveWaiter) return;
      if (status === 'saved') saveWaiter.resolve();
      else if (status === 'failed') saveWaiter.reject(error || new Error('The defense was not saved.'));
    });
  }

  function waitForRotationSave() {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        saveWaiter = null;
        reject(new Error('The defense is still saving. Check your connection and try again.'));
      }, 20000);
      saveWaiter = {
        resolve: () => { clearTimeout(timer); saveWaiter = null; resolve(); },
        reject: (error) => { clearTimeout(timer); saveWaiter = null; reject(error); },
      };
    });
  }

  function staleError(text) {
    const error = new Error(text);
    error.stale = true;
    return error;
  }

  // What the coach approved must still be what would be copied: today's
  // lineup and 1st inning unchanged (another coach, another device) and the
  // same players available.
  function shownPart(data, pick) {
    return JSON.stringify({
      source: data.source?.game_id,
      lineup: pick.lineup ? [data.lineup.current_id, data.lineup.current_count, data.lineup.player_ids] : null,
      defense: pick.defense ? [cleanAlignment(data.defense.current_alignment), cleanAlignment(data.defense.proposed)] : null,
    });
  }

  async function confirmStillCurrent(pick) {
    const latest = await fetchPreview();
    if (!latest.available || shownPart(latest, pick) !== shownPart(preview, pick)) {
      throw staleError('Today\'s setup changed while you were reviewing (on this or another device). Refresh to see the latest, then copy again.');
    }
  }

  async function applyDefense(defense) {
    if (!store) throw new Error('Refresh the page and try again.');
    if (store.isSaveInFlightOrQueued() || store.hasUnsyncedLocalState()) {
      throw new Error('Your last defense change is still saving. Try again in a moment.');
    }
    const rotation = store.getRotation(`Rotation for vs ${preview.game_opponent}`);
    const before = rotation.innings['1'] && typeof rotation.innings['1'] === 'object' ? {...rotation.innings['1']} : {};
    // Apply only what the coach was shown.
    if (JSON.stringify(cleanAlignment(before)) !== JSON.stringify(cleanAlignment(defense.current_alignment))) {
      throw staleError("This page's 1st inning doesn't match the saved plan. Refresh to see the latest, then copy again.");
    }
    rotation.innings['1'] = {...defense.proposed};
    const saved = waitForRotationSave();
    store.commitLocalChange(rotation.title, true);
    try {
      await saved;
    } catch (error) {
      // Put today's 1st inning back as it was; nothing else was touched.
      rotation.innings['1'] = before;
      store.commitLocalChange(rotation.title, false);
      throw error instanceof Error ? error : new Error('The defense was not saved.');
    }
  }

  async function applyLineup(lineup) {
    const url = lineup.current_id ? `/edit_lineup/${lineup.current_id}` : '/add_lineup';
    const response = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: lineup.current_title || `Lineup for vs ${preview.game_opponent}`,
        lineup_player_ids: lineup.player_ids,
        lineup_data: lineup.batters.map((batter) => batter.name),
        associated_game_id: gameId,
      }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.status !== 'success') {
      throw new Error(result.message || `Save failed (${response.status}).`);
    }
  }

  // Each part saves on its own and reports for itself, so the coach is told
  // exactly what saved and what didn't -- never "copied" for a part that
  // failed. The starting defense goes first; the batting order is still
  // tried if the defense fails, since the two are independent.
  async function savePart(label, save) {
    try {
      await save();
      return {label, ok: true};
    } catch (error) {
      if (error?.stale) throw error;
      const reason = error instanceof TypeError
        ? 'No connection to CoachBoard.'
        : (error?.message || 'It was not saved.');
      return {label, ok: false, reason};
    }
  }

  function resultHtml(results) {
    const saved = results.filter((item) => item.ok);
    const failed = results.filter((item) => !item.ok);
    const kind = failed.length === 0 ? 'success' : saved.length ? 'warning' : 'danger';
    let lead = 'Nothing was copied.';
    if (!failed.length) lead = 'Copied. Updating Prepare Game…';
    else if (saved.length) lead = 'Only part of the setup was copied.';
    const rows = results.map((item) => (item.ok
      ? `<li data-ps-result="saved"><strong>Saved:</strong> ${esc(item.label)}</li>`
      : `<li data-ps-result="failed"><strong>Not saved:</strong> ${esc(item.label)} — ${esc(item.reason)}</li>`
    )).join('');
    const next = failed.length ? '<div class="mt-1">Refresh to see what is saved now, then copy again if needed.</div>' : '';
    return `<div class="alert alert-${kind} py-2 mb-3" role="status"><div class="fw-semibold">${esc(lead)}</div><ul class="mb-0 ps-3">${rows}</ul>${next}</div>`;
  }

  async function apply() {
    if (applying || !preview) return;
    const pick = selected();
    if (!pick.lineup && !pick.defense) return;
    applying = true;
    applyBtn.disabled = true;
    cancelBtn.disabled = true;
    applyBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Copying…';
    const results = [];
    try {
      await confirmStillCurrent(pick);
      if (pick.defense) results.push(await savePart('Starting defense', () => applyDefense(preview.defense)));
      if (pick.lineup) results.push(await savePart('Batting order', () => applyLineup(preview.lineup)));
    } catch (error) {
      results.length = 0;
      feedback('warning', error?.message || 'Unable to copy the setup.');
    }
    applying = false;
    cancelBtn.disabled = false;
    if (results.length) {
      const host = document.getElementById('previousSetupFeedback');
      if (host) host.innerHTML = resultHtml(results);
      body.scrollTop = 0;
      if (results.every((item) => item.ok)) {
        const sentence = copiedSentence(pick);
        feedback('success', `${sentence} Updating Prepare Game…`);
        rememberCopied(sentence);
        setTimeout(() => window.location.reload(), 700);
        return;
      }
    }
    // Something wasn't saved (or the page is behind): reload to show what is
    // saved now rather than re-running a half-applied copy.
    finished = true;
    applyBtn.textContent = 'Refresh';
    applyBtn.disabled = false;
  }

  // A full copy reloads the page; the card then says what was copied, once.
  const FLASH_KEY = `cb-previous-setup-copied:${gameId}`;

  function copiedSentence(pick) {
    const parts = [];
    if (pick.lineup) parts.push(plural(preview.lineup.player_ids.length, 'batter'));
    if (pick.defense) parts.push(plural(preview.defense.copied_count, 'fielder'));
    return `Copied ${parts.join(' and ')} from ${preview.source.short_date}.`;
  }

  function rememberCopied(text) {
    try { window.sessionStorage.setItem(FLASH_KEY, text); } catch (_) { /* best effort */ }
  }

  function showCopiedFlash() {
    let text = null;
    try {
      text = window.sessionStorage.getItem(FLASH_KEY);
      window.sessionStorage.removeItem(FLASH_KEY);
    } catch (_) { return; }
    const host = document.getElementById('previousSetupResult');
    if (!text || !host) return;
    host.textContent = text;
    host.hidden = false;
  }

  installStyles();
  showCopiedFlash();
  applyBtn.addEventListener('click', () => {
    if (finished) window.location.reload();
    else void apply();
  });
  document.getElementById('previousSetupOpenBtn')?.addEventListener('click', () => {
    modal.show();
    void loadPreview();
  });
})();
