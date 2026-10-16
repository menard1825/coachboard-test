// When two coaches change the same position of a game's defense.
//
// The shared save queue (pregame_rotation_sync.js) sends the plan each page
// started from; the server merges changes to different positions and
// refuses a save that would replace another coach's change to the same
// position (rotation_merge.py). This dialog -- the same in the Classic and
// Updated Prepare Game -- shows what clashed and lets the coach choose.
// Their own changes stay on screen, unsaved, until they do.
(() => {
  'use strict';

  const store = window.CBPregameRotation;
  if (!store || !store.gameId) return;

  const ID = 'cbRotationConflictModal';
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));

  function ordinal(value) {
    const number = Number(value);
    if (!Number.isInteger(number)) return `inning ${value}`;
    const tens = number % 100;
    const suffix = tens >= 11 && tens <= 13 ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[number % 10] || 'th');
    return `${number}${suffix} inning`;
  }

  function line(item) {
    const inning = ordinal(item.inning);
    if (item.kind === 'duplicate') {
      return `${esc(inning)}: together, your changes and theirs would put <strong>${esc(item.player)}</strong> in two positions.`;
    }
    if (!item.position) {
      return item.yours
        ? `${esc(inning)}: you changed it; the other coach removed it.`
        : `${esc(inning)}: you removed it; the other coach changed it.`;
    }
    const player = (name) => (name ? `<strong>${esc(name)}</strong>` : '<em>open</em>');
    return `${esc(inning)}, ${esc(item.position)}: you chose ${player(item.yours)}; the other coach saved ${player(item.theirs)}.`;
  }

  function modal() {
    let element = document.getElementById(ID);
    if (element) return element;
    element = document.createElement('div');
    element.id = ID;
    element.className = 'modal fade';
    element.tabIndex = -1;
    element.setAttribute('aria-labelledby', `${ID}Title`);
    element.setAttribute('aria-hidden', 'true');
    element.dataset.bsBackdrop = 'static';
    element.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="${ID}Title">Another coach changed this defense</h5>
          </div>
          <div class="modal-body">
            <p class="mb-2">While you were editing, another coach saved a different choice for the same spot. <strong>Your changes are still on your screen and haven't been saved.</strong></p>
            <ul class="mb-2 ps-3" data-cb-conflict-list></ul>
            <p class="small text-muted mb-0">Your other changes, and the other coach's, are kept either way. To decide later, tap the save status when you're ready.</p>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-link me-auto" data-cb-conflict="later">Decide Later</button>
            <button type="button" class="btn btn-outline-secondary" data-cb-conflict="mine">Keep My Change</button>
            <button type="button" class="btn btn-primary" data-cb-conflict="theirs">Use Their Change</button>
          </div>
        </div>
      </div>`;
    element.addEventListener('click', (event) => {
      const button = event.target.closest('[data-cb-conflict]');
      if (!button) return;
      window.bootstrap?.Modal.getOrCreateInstance(element).hide();
      // Decide Later: nothing is saved yet; the save status (tap to choose)
      // brings this question back.
      if (button.dataset.cbConflict !== 'later') store.resolveConflict(button.dataset.cbConflict);
    });
    document.body.appendChild(element);
    return element;
  }

  function show(conflict) {
    if (!conflict || !window.bootstrap) return;
    const element = modal();
    const items = conflict.conflicts?.length ? conflict.conflicts : [];
    element.querySelector('[data-cb-conflict-list]').innerHTML = items.length
      ? items.map((item) => `<li>${line(item)}</li>`).join('')
      : '<li>The same part of the plan was changed by both of you.</li>';
    const instance = window.bootstrap.Modal.getOrCreateInstance(element);
    if (!element.classList.contains('show')) instance.show();
  }

  store.onConflict(show);
})();
