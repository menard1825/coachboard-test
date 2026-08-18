(() => {
  'use strict';

  const dataNode = document.getElementById('rteEditorData');
  if (!dataNode) return;

  let data;
  try {
    data = JSON.parse(dataNode.textContent || '{}');
  } catch (error) {
    console.error('Unable to load rotation template editor data.', error);
    return;
  }

  const state = {
    rotation: data.rotation || {id:null, title:'', innings:{}},
    roster: Array.isArray(data.roster) ? data.roster : [],
    outfielderCount: Number(data.outfielder_count || 3),
    regulationInnings: Math.max(1, Number(data.regulation_innings || 6)),
    presets: Array.isArray(data.defense_presets) ? data.defense_presets : [],
    presetPrefix: String(data.preset_prefix || 'DEFENSE PRESET — '),
    templateKind: String(data.template_kind || 'rotation'),
    saveUrl: String(data.save_url || '/api/rotation-template/save'),
    editUrlBase: String(data.edit_url_base || '/rotation-template'),
    saveButtonLabel: String(data.save_button_label || 'Save Template'),
    inning: '1',
    dirty: false,
    saving: false,
  };
  state.isStartingDefense = state.templateKind === 'starting_defense';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function positions() {
    return state.outfielderCount === 4
      ? ['P','C','1B','2B','3B','SS','LF','LCF','RCF','RF']
      : ['P','C','1B','2B','3B','SS','LF','CF','RF'];
  }

  function regulationKeys() {
    return Array.from({length: state.regulationInnings}, (_, index) => String(index + 1));
  }

  function normalizeState() {
    if (!state.rotation || typeof state.rotation !== 'object') {
      state.rotation = {id:null, title:'', innings:{}};
    }
    if (!state.rotation.innings || typeof state.rotation.innings !== 'object') {
      state.rotation.innings = {};
    }

    regulationKeys().forEach((key) => {
      if (!state.rotation.innings[key] || typeof state.rotation.innings[key] !== 'object') {
        state.rotation.innings[key] = {};
      }
    });

    if (!regulationKeys().includes(state.inning)) state.inning = '1';
  }

  function alignment(inning = state.inning) {
    normalizeState();
    return state.rotation.innings[inning];
  }

  function markDirty() {
    state.dirty = true;
    const label = $('rteSaveState');
    if (label) label.textContent = 'Unsaved changes';
  }

  function openPositions(source = alignment()) {
    return positions().filter((position) => !source?.[position]);
  }

  function requiredOpenPositions(source = alignment()) {
    return openPositions(source).filter((position) => !state.isStartingDefense || position !== 'P');
  }

  function playerPosition(name, source = alignment()) {
    return Object.entries(source || {}).find(([, playerName]) => playerName === name)?.[0] || null;
  }

  function playerDetail(player) {
    const preferred = [player.position1, player.position2, player.position3].filter(Boolean).join(' / ');
    const pieces = [];
    if (player.number) pieces.push(`#${player.number}`);
    if (preferred) pieces.push(preferred);
    return pieces.join(' · ') || 'Roster player';
  }

  function fieldSpot(position, source, left, top) {
    const name = source?.[position] || '';
    const openClass = name ? '' : state.isStartingDefense && position === 'P' ? 'optional' : 'open';
    const openLabel = state.isStartingDefense && position === 'P' ? 'GAME DAY' : 'OPEN';
    return `<button type="button" class="rte-spot ${openClass}" data-rte-position="${esc(position)}" style="left:${left}%;top:${top}%"><span class="rte-pos">${esc(position)}</span><span class="rte-player">${esc(name || openLabel)}</span></button>`;
  }

  function fieldMarkup() {
    const source = alignment();
    const outfield = state.outfielderCount === 4
      ? [['LF',11,23],['LCF',38,13],['RCF',62,13],['RF',89,23]]
      : [['LF',15,22],['CF',50,11],['RF',85,22]];
    const spots = [
      ...outfield,
      ['3B',18,57],['SS',38,43],['2B',62,43],['1B',82,57],
      ['P',50,62],['C',50,85],
    ];
    const assigned = new Set(Object.values(source || {}).filter(Boolean));
    const bench = state.roster.filter((player) => !assigned.has(player.name));
    const opens = requiredOpenPositions(source);
    const pitcherStatus = state.isStartingDefense
      ? source.P ? `Pitcher saved: ${esc(source.P)}` : 'Pitcher will be chosen on Game Day'
      : '';

    return `
      <div class="rte-field-card">
        <div class="rte-field-cap"><strong>${state.isStartingDefense ? 'Starting Defense' : `Defense — Inning ${esc(state.inning)}`}</strong><span>Tap a position to choose the player</span></div>
        <div class="rte-field">
          <svg class="rte-field-art" viewBox="0 0 100 88" preserveAspectRatio="none" aria-hidden="true">
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
          ${spots.map(([pos,left,top]) => fieldSpot(pos, source, left, top)).join('')}
        </div>
        <div class="rte-bench">
          <div class="rte-label">Bench — Inning ${esc(state.inning)}</div>
          <div class="rte-chips">${bench.length ? bench.map((player) => `<span>${esc(player.name)}</span>`).join('') : '<span>None</span>'}</div>
        </div>
        <div class="rte-status">
          <span>${opens.length ? `<span class="bad"><strong>${opens.length}</strong> required position${opens.length === 1 ? '' : 's'} open: ${esc(opens.join(', '))}</span>` : `<strong>${state.isStartingDefense ? 'Starting defense ready' : 'Defense complete'}</strong>`}</span>
          <span>${pitcherStatus || `${assigned.size} on field · ${bench.length} bench`}</span>
        </div>
      </div>`;
  }

  function renderTabs() {
    const host = $('rteInningTabs');
    if (!host) return;
    host.innerHTML = regulationKeys().map((inning) => {
      const incomplete = requiredOpenPositions(alignment(inning)).length > 0;
      return `<button type="button" class="rte-tab ${inning === state.inning ? 'active' : ''} ${incomplete ? 'incomplete' : ''}" data-rte-inning="${inning}" aria-label="Inning ${inning}">${inning}</button>`;
    }).join('');
    const copy = $('rteCopyPrevious');
    if (copy) copy.disabled = Number(state.inning) <= 1;
  }

  function renderField() {
    const host = $('rteFieldHost');
    if (host) host.innerHTML = fieldMarkup();
  }

  function renderSummary() {
    const grid = $('rteSummaryGrid');
    if (!grid) return;
    const keys = regulationKeys();
    const rows = state.roster.map((player) => {
      let benchCount = 0;
      const positionCounts = {};
      keys.forEach((inning) => {
        const source = alignment(inning);
        const pos = playerPosition(player.name, source);
        if (pos) positionCounts[pos] = (positionCounts[pos] || 0) + 1;
        else benchCount += 1;
      });
      const positionsText = Object.entries(positionCounts)
        .sort(([a],[b]) => a.localeCompare(b))
        .map(([pos,count]) => `${pos} ${count}`)
        .join(' · ') || 'No field assignments';
      return `<div class="rte-summary-player"><strong>${esc(player.name)}</strong><div>Bench: ${benchCount} of ${keys.length} innings</div><div>${esc(positionsText)}</div></div>`;
    });
    grid.innerHTML = rows.join('');
  }

  function renderPresetOptions() {
    const select = $('rtePresetSelect');
    if (!select) return;
    const current = select.value;
    const options = state.presets.map((preset) => {
      const label = String(preset.title || '').startsWith(state.presetPrefix)
        ? String(preset.title).slice(state.presetPrefix.length).trim()
        : String(preset.title || 'Starting Defense');
      return `<option value="${preset.id}">${esc(label)}</option>`;
    }).join('');
    select.innerHTML = `<option value="">Starting Defense Template…</option>${options}`;
    if ([...select.options].some((option) => option.value === current)) select.value = current;
    const apply = $('rteApplyPreset');
    if (apply) apply.disabled = !select.value;
  }

  function renderAll() {
    normalizeState();
    renderTabs();
    renderField();
    renderSummary();
    renderPresetOptions();
  }

  function choosePlayer(position) {
    const source = alignment();
    const current = source[position] || '';
    const title = $('rtePlayerTitle');
    const choices = $('rtePlayerChoices');
    if (!choices) return;
    if (title) title.textContent = `${position} — Choose Player`;

    const rows = [];
    if (current) {
      rows.push(`<button type="button" class="list-group-item list-group-item-action text-danger" data-rte-choice="" data-rte-position-choice="${esc(position)}"><span class="rte-choice-name">Open ${esc(position)}</span><span class="rte-choice-detail d-block">Move ${esc(current)} to the bench</span></button>`);
    }

    state.roster.forEach((player) => {
      const oldPos = playerPosition(player.name, source);
      let detail = playerDetail(player);
      if (oldPos === position) detail = `Currently at ${position}`;
      else if (oldPos) detail = `Currently at ${oldPos} · ${detail}`;
      else detail = `Bench · ${detail}`;
      rows.push(`<button type="button" class="list-group-item list-group-item-action" data-rte-choice="${esc(player.name)}" data-rte-position-choice="${esc(position)}"><span class="rte-choice-name">${esc(player.name)}</span><span class="rte-choice-detail d-block">${esc(detail)}</span></button>`);
    });
    choices.innerHTML = rows.join('');
    bootstrap.Modal.getOrCreateInstance($('rtePlayerModal')).show();
  }

  function assign(position, playerName) {
    const source = alignment();
    if (!playerName) {
      delete source[position];
    } else {
      const oldPosition = playerPosition(playerName, source);
      if (oldPosition && oldPosition !== position) delete source[oldPosition];
      source[position] = playerName;
    }
    markDirty();
    bootstrap.Modal.getOrCreateInstance($('rtePlayerModal')).hide();
    renderAll();
  }

  function copyPrevious() {
    const previous = String(Number(state.inning) - 1);
    if (!state.rotation.innings[previous]) return;
    state.rotation.innings[state.inning] = {...state.rotation.innings[previous]};
    markDirty();
    renderAll();
  }

  function presetAlignment(preset) {
    const innings = preset?.innings;
    if (!innings || typeof innings !== 'object') return null;
    const keys = Object.keys(innings).sort((a,b) => Number(a) - Number(b));
    for (const key of keys) {
      if (innings[key] && typeof innings[key] === 'object' && Object.keys(innings[key]).length) return {...innings[key]};
    }
    return keys.length ? {...(innings[keys[0]] || {})} : null;
  }

  function applyPreset() {
    const id = Number($('rtePresetSelect')?.value || 0);
    if (!id) return;
    const preset = state.presets.find((item) => Number(item.id) === id);
    const source = presetAlignment(preset);
    if (!source) {
      window.alert('That Starting Defense template does not contain a defensive alignment.');
      return;
    }
    const allowed = new Set(positions());
    const rosterNames = new Set(state.roster.map((player) => player.name));
    const cleaned = {};
    const used = new Set();
    Object.entries(source).forEach(([position,name]) => {
      if (!allowed.has(position) || !rosterNames.has(name) || used.has(name)) return;
      cleaned[position] = name;
      used.add(name);
    });
    state.rotation.innings[state.inning] = cleaned;
    markDirty();
    renderAll();
  }

  async function saveTemplate() {
    if (state.saving) return;
    const name = String($('rteTemplateName')?.value || '').trim();
    if (!name) {
      $('rteTemplateName')?.focus();
      window.alert('Give this rotation template a name first.');
      return;
    }

    const missingRequired = requiredOpenPositions(alignment('1'));
    if (state.isStartingDefense && missingRequired.length) {
      window.alert(`Fill ${missingRequired.join(', ')} before saving. Pitcher may remain open.`);
      return;
    }

    const incomplete = regulationKeys().filter((inning) => requiredOpenPositions(alignment(inning)).length > 0);
    if (!state.isStartingDefense && incomplete.length) {
      const okay = window.confirm(`This template still has open defensive positions in inning${incomplete.length === 1 ? '' : 's'} ${incomplete.join(', ')}.\n\nSave it anyway?`);
      if (!okay) return;
    }

    state.saving = true;
    const button = $('rteSaveTop');
    if (button) { button.disabled = true; button.textContent = 'Saving…'; }
    if ($('rteSaveState')) $('rteSaveState').textContent = 'Saving…';

    try {
      const response = await fetch(state.saveUrl, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          id: state.rotation.id || null,
          title: name,
          innings: state.isStartingDefense ? {'1': {...alignment('1')}} : state.rotation.innings,
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.status === 'error') {
        throw new Error(result.message || (state.isStartingDefense ? 'Unable to save starting defense.' : 'Unable to save rotation template.'));
      }

      state.rotation.id = result.id;
      state.rotation.title = name;
      state.dirty = false;
      if ($('rteSaveState')) $('rteSaveState').textContent = 'Saved';
      if ($('rtePageTitle')) $('rtePageTitle').textContent = state.isStartingDefense ? 'Edit Starting Defense' : 'Edit Rotation Template';
      window.history.replaceState({}, '', `${state.editUrlBase}/${result.id}`);
    } catch (error) {
      window.alert(error.message || (state.isStartingDefense ? 'Unable to save starting defense.' : 'Unable to save rotation template.'));
      if ($('rteSaveState')) $('rteSaveState').textContent = 'Save failed';
    } finally {
      state.saving = false;
      if (button) { button.disabled = false; button.textContent = state.saveButtonLabel; }
    }
  }

  function bindEvents() {
    const nameInput = $('rteTemplateName');
    if (nameInput) {
      nameInput.value = state.rotation.title || '';
      nameInput.addEventListener('input', markDirty);
    }
    $('rteSaveTop')?.addEventListener('click', saveTemplate);
    $('rteCopyPrevious')?.addEventListener('click', copyPrevious);
    $('rtePresetSelect')?.addEventListener('change', () => {
      if ($('rteApplyPreset')) $('rteApplyPreset').disabled = !$('rtePresetSelect').value;
    });
    $('rteApplyPreset')?.addEventListener('click', applyPreset);

    document.addEventListener('click', (event) => {
      const tab = event.target.closest('[data-rte-inning]');
      if (tab) {
        state.inning = String(tab.dataset.rteInning);
        renderAll();
        return;
      }
      const spot = event.target.closest('[data-rte-position]');
      if (spot) {
        choosePlayer(String(spot.dataset.rtePosition));
        return;
      }
      const choice = event.target.closest('[data-rte-position-choice]');
      if (choice) {
        assign(String(choice.dataset.rtePositionChoice), String(choice.dataset.rteChoice || ''));
      }
    });

    window.addEventListener('beforeunload', (event) => {
      if (!state.dirty || state.saving) return;
      event.preventDefault();
      event.returnValue = '';
    });
  }

  normalizeState();
  bindEvents();
  renderAll();
})();
