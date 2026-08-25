(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game-day\/(\d+)\/correct\/?$/);
  if (!match) return;
  const gameId = Number(match[1]);
  const dataEl = document.getElementById('pgcCorrectionData');
  if (!dataEl) return;

  let data = {};
  try { data = JSON.parse(dataEl.textContent || '{}'); } catch (_) { return; }

  const players = Array.isArray(data.players) ? data.players : [];
  const playerMap = new Map(players.map(player => [Number(player.id), player]));
  const playerNameMap = new Map(players.map(player => [String(player.name || ''), player]));
  let lineup = (Array.isArray(data.lineup) ? data.lineup : [])
    .map(item => Number(item.player_id))
    .filter(id => playerMap.has(id));
  let activeInning = '';
  let defenseDraft = {};
  let busy = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function labelFor(player) {
    if (!player) return 'Unknown';
    const number = String(player.number ?? '').trim();
    return number ? `#${number} ${player.name}` : String(player.name || 'Unknown');
  }

  function message(text, kind = 'success') {
    const el = document.getElementById('pgcMessage');
    if (!el) return;
    el.textContent = text;
    el.className = `pgc-message show ${kind}`;
    el.scrollIntoView({behavior:'smooth', block:'nearest'});
  }

  function renderLineup() {
    const list = document.getElementById('pgcLineupList');
    const addSelect = document.getElementById('pgcAddPlayer');
    const saveButton = document.getElementById('pgcSaveLineup');
    if (!list || !addSelect || !saveButton) return;

    list.innerHTML = lineup.length
      ? lineup.map((id, index) => {
          const player = playerMap.get(id);
          return `<div class="pgc-lineup-row" data-pgc-lineup-index="${index}"><span class="pgc-order">${index + 1}</span><span class="pgc-player">${esc(labelFor(player))}</span><span class="pgc-row-actions"><button type="button" class="btn btn-sm btn-outline-secondary" data-pgc-up aria-label="Move ${esc(player?.name || 'player')} up" ${index === 0 ? 'disabled' : ''}><i class="bi bi-arrow-up"></i></button><button type="button" class="btn btn-sm btn-outline-secondary" data-pgc-down aria-label="Move ${esc(player?.name || 'player')} down" ${index === lineup.length - 1 ? 'disabled' : ''}><i class="bi bi-arrow-down"></i></button><button type="button" class="btn btn-sm btn-outline-danger" data-pgc-remove aria-label="Remove ${esc(player?.name || 'player')} from batting order"><i class="bi bi-x-lg"></i></button></span></div>`;
        }).join('')
      : '<div class="small text-muted">No batting order is recorded yet.</div>';

    const used = new Set(lineup);
    const available = players.filter(player => !used.has(Number(player.id)));
    addSelect.innerHTML = `<option value="">${available.length ? 'Add a player…' : 'All available players are listed'}</option>${available.map(player => `<option value="${player.id}">${esc(labelFor(player))}</option>`).join('')}`;
    addSelect.disabled = !available.length;
    document.getElementById('pgcAddPlayerBtn').disabled = !available.length;
    saveButton.disabled = !lineup.length || busy;
  }

  function moveLineup(index, delta) {
    const target = index + delta;
    if (index < 0 || target < 0 || index >= lineup.length || target >= lineup.length) return;
    [lineup[index], lineup[target]] = [lineup[target], lineup[index]];
    renderLineup();
  }

  async function saveLineup() {
    if (busy || !lineup.length) return;
    busy = true;
    const button = document.getElementById('pgcSaveLineup');
    const original = button?.textContent || 'Save Batting Order';
    if (button) { button.disabled = true; button.textContent = 'Saving…'; }
    try {
      const response = await fetch(`/api/game-day/${gameId}/corrections/lineup`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({player_ids:lineup}),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.status === 'error') throw new Error(result.message || 'Unable to save batting order.');
      message('Batting order corrected.');
    } catch (error) {
      message(error.message || 'Unable to save batting order.', 'error');
    } finally {
      busy = false;
      if (button) { button.disabled = false; button.textContent = original; }
      renderLineup();
    }
  }

  function inningData(inning) {
    return (data.innings || []).find(item => String(item.inning) === String(inning)) || null;
  }

  function validateDefenseDraft() {
    const positions = Array.isArray(data.positions) ? data.positions : [];
    const missing = positions.filter(pos => !String(defenseDraft[pos] || '').trim());
    const names = positions.map(pos => String(defenseDraft[pos] || '').trim()).filter(Boolean);
    const duplicate = names.find((name, index) => names.indexOf(name) !== index) || '';
    const warning = document.getElementById('pgcDefenseWarning');
    const save = document.getElementById('pgcSaveDefense');

    if (warning) {
      warning.textContent = missing.length
        ? `Fill ${missing.join(', ')} before saving.`
        : duplicate
          ? `${duplicate} is assigned to more than one position.`
          : '';
    }
    if (save) save.disabled = busy || Boolean(missing.length || duplicate);
    return !missing.length && !duplicate;
  }

  function renderDefenseEditor() {
    const list = document.getElementById('pgcDefenseList');
    if (!list) return;
    const positions = Array.isArray(data.positions) ? data.positions : [];
    list.innerHTML = positions.map(pos => {
      const current = String(defenseDraft[pos] || '');
      return `<div class="pgc-defense-row"><label for="pgc-defense-${esc(pos)}">${esc(pos)}</label><select class="form-select" id="pgc-defense-${esc(pos)}" data-pgc-defense-pos="${esc(pos)}"><option value="">Choose player…</option>${players.map(player => `<option value="${esc(player.name)}" ${player.name === current ? 'selected' : ''}>${esc(labelFor(player))}</option>`).join('')}</select></div>`;
    }).join('');
    list.querySelectorAll('[data-pgc-defense-pos]').forEach(select => {
      select.addEventListener('change', () => {
        defenseDraft[select.dataset.pgcDefensePos] = select.value;
        validateDefenseDraft();
      });
    });
    validateDefenseDraft();
  }

  function openDefense(inning) {
    const row = inningData(inning);
    if (!row) return;
    activeInning = String(inning);
    defenseDraft = {};
    (data.positions || []).forEach(pos => { defenseDraft[pos] = row.alignment?.[pos] || ''; });
    const title = document.getElementById('pgcDefenseTitle');
    const subtitle = document.getElementById('pgcDefenseSubtitle');
    if (title) title.textContent = `Edit Inning ${activeInning} Defense`;
    if (subtitle) subtitle.textContent = row.recorded
      ? 'Correct the defense that was actually on the field.'
      : 'This inning was not recorded. Add the defense only if it was actually played.';
    renderDefenseEditor();
    bootstrap.Modal.getOrCreateInstance(document.getElementById('pgcDefenseModal')).show();
  }

  async function saveDefense() {
    if (busy || !activeInning || !validateDefenseDraft()) return;
    busy = true;
    const button = document.getElementById('pgcSaveDefense');
    const original = button?.textContent || 'Save Correction';
    if (button) { button.disabled = true; button.textContent = 'Saving…'; }
    try {
      const response = await fetch(`/api/game-day/${gameId}/corrections/defense`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({inning:activeInning, alignment:defenseDraft}),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.status === 'error') throw new Error(result.message || 'Unable to save defense correction.');
      bootstrap.Modal.getOrCreateInstance(document.getElementById('pgcDefenseModal')).hide();
      window.location.reload();
    } catch (error) {
      const warning = document.getElementById('pgcDefenseWarning');
      if (warning) warning.textContent = error.message || 'Unable to save defense correction.';
      if (button) { button.disabled = false; button.textContent = original; }
    } finally {
      busy = false;
    }
  }

  document.addEventListener('click', event => {
    const row = event.target.closest('[data-pgc-lineup-index]');
    if (row) {
      const index = Number(row.dataset.pgcLineupIndex);
      if (event.target.closest('[data-pgc-up]')) moveLineup(index, -1);
      if (event.target.closest('[data-pgc-down]')) moveLineup(index, 1);
      if (event.target.closest('[data-pgc-remove]')) {
        lineup.splice(index, 1);
        renderLineup();
      }
    }
    const edit = event.target.closest('[data-pgc-edit-defense]');
    if (edit) openDefense(edit.dataset.pgcEditDefense);
  });

  document.getElementById('pgcAddPlayerBtn')?.addEventListener('click', () => {
    const select = document.getElementById('pgcAddPlayer');
    const id = Number(select?.value);
    if (!id || !playerMap.has(id) || lineup.includes(id)) return;
    lineup.push(id);
    renderLineup();
  });
  document.getElementById('pgcSaveLineup')?.addEventListener('click', saveLineup);
  document.getElementById('pgcSaveDefense')?.addEventListener('click', saveDefense);

  document.getElementById('pgcDefenseModal')?.addEventListener('hide.bs.modal', event => {
    const active = document.activeElement;
    if (event.target.contains(active) && typeof active.blur === 'function') active.blur();
  });

  renderLineup();
})();
