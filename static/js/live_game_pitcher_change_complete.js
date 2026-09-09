(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const MODAL_ID = 'live-pitcher-finish-v3';
  let state = null;
  let incoming = null;
  let before = null;
  let oldPitcher = '';
  let incomingPosition = null;
  let busy = false;

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function sequenceFromState(value = state) {
    return (value?.rotation_events || []).reduce(
      (max, event) => {
        if (event?.reverted) return max;
        return Math.max(
          max,
          Number(event?.sequence) || 0,
        );
      },
      0,
    );
  }

  function installStyles() {
    if ($('pitcher-change-simple-styles')) return;
    const style = document.createElement('style');
    style.id = 'pitcher-change-simple-styles';
    style.textContent = `
      #${MODAL_ID} .modal-content{border:0;border-radius:15px;overflow:hidden}
      #${MODAL_ID} .pc-summary{border:1px solid #dfe4ea;background:#f8fafc;border-radius:10px;padding:10px 11px;margin-bottom:12px;color:#344054;font-size:.8rem}
      #${MODAL_ID} .pc-actions{display:grid;gap:9px}
      #${MODAL_ID} .pc-action{min-height:58px;border-radius:11px;font-weight:850;text-align:left;padding:9px 11px}
      #${MODAL_ID} .pc-action small{display:block;margin-top:2px;font-size:.67rem;font-weight:550;opacity:.78}
      #${MODAL_ID} .pc-replacements{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}
      #${MODAL_ID} .pc-replacements .btn{min-height:52px;border-radius:9px;font-weight:750;text-align:left}
      #${MODAL_ID} .pc-replacements .btn small{display:block;margin-top:3px;font-size:.64rem;font-weight:550;opacity:.72}
      #${MODAL_ID} .pc-label{font-size:.65rem;text-transform:uppercase;letter-spacing:.08em;font-weight:850;color:#667085;margin:12px 0 6px}
      #${MODAL_ID} .pc-vacancy-note{border:1px solid #dfe4ea;background:#f8fafc;border-radius:10px;padding:9px 10px;margin-bottom:9px;font-size:.75rem;color:#475467}
      @media(max-width:575.98px){#${MODAL_ID} .modal-dialog{margin:.5rem}}
    `;
    document.head.appendChild(style);
  }

  function toast(message, kind='success') {
    let host = $('pitcher-change-toast-v3');
    if (!host) {
      host = document.createElement('div');
      host.id = 'pitcher-change-toast-v3';
      host.className = 'toast-container position-fixed top-0 end-0 p-3';
      host.style.zIndex = '5000';
      document.body.appendChild(host);
    }
    const el = document.createElement('div');
    el.className = `toast text-bg-${kind} border-0`;
    el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
    host.appendChild(el);
    const instance = bootstrap.Toast.getOrCreateInstance(el,{delay:2400});
    el.addEventListener('hidden.bs.toast',()=>el.remove(),{once:true});
    instance.show();
  }

  async function loadState() {
    const response = await fetch(`/api/live-game/${gameId}/state`,{cache:'no-store'});
    const data = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(data.message || `Unable to load game (${response.status}).`);
    return data;
  }

  function ensureModal() {
    let modal = $(MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><div><h5 class="modal-title mb-0">Pitching Change</h5><div class="small text-muted">Who’s coming in, and where does the old pitcher go?</div></div><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body" data-pc-body></div></div></div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function playerPositionInDraft(draft, name) {
    return Object.entries(draft || {})
      .find(([, assigned]) => assigned === name)?.[0] || 'BENCH';
  }

  function baseDraft() {
    const draft = {...(before || {})};
    if (incomingPosition) delete draft[incomingPosition];
    draft.P = incoming.name;
    return draft;
  }

  function renderVacancy(draft, vacancy, lockedNames) {
    const modal = ensureModal();
    const body = modal.querySelector('[data-pc-body]');
    if (!body || !incoming || !vacancy) return;

    const choices = (state?.roster || [])
      .filter(player => (
        player?.name &&
        !lockedNames.has(player.name)
      ))
      .map(player => ({
        ...player,
        currentPosition: playerPositionInDraft(
          draft,
          player.name
        ),
      }))
      .filter(player => player.currentPosition !== 'P');

    const fieldChoices = choices
      .filter(player => player.currentPosition !== 'BENCH')
      .sort((a, b) => (
        a.currentPosition.localeCompare(b.currentPosition) ||
        a.name.localeCompare(b.name)
      ));

    const benchChoices = choices
      .filter(player => player.currentPosition === 'BENCH')
      .sort((a, b) => a.name.localeCompare(b.name));

    const choiceButton = player => {
      const number = String(player.number ?? '').trim();
      const label = number
        ? `#${number} ${player.name}`
        : player.name;

      return `
        <button
          type="button"
          class="btn btn-outline-primary"
          data-pc-chain-player="${esc(player.name)}"
          data-pc-chain-from="${esc(player.currentPosition)}"
        >
          <span>${esc(label)}</span>
          <small>
            ${esc(player.currentPosition)} → ${esc(vacancy)}
          </small>
        </button>`;
    };

    body.innerHTML = `
      <div class="pc-summary">
        <strong>${esc(incoming.name)}</strong> → P<br>
        <span class="text-muted">
          ${esc(oldPitcher)} → Bench
        </span>
      </div>

      <div class="pc-vacancy-note">
        <strong>Who takes ${esc(vacancy)}?</strong><br>
        Pick a fielder or bench player.
        If you move a fielder, CoachBoard will follow
        the open position automatically.
      </div>

      ${fieldChoices.length ? `
        <div class="pc-label">On the field</div>
        <div class="pc-replacements">
          ${fieldChoices.map(choiceButton).join('')}
        </div>
      ` : ''}

      <div class="pc-label">On the bench</div>
      <div class="pc-replacements">
        ${
          benchChoices.length
            ? benchChoices.map(choiceButton).join('')
            : '<div class="small text-muted">No bench player is available.</div>'
        }
      </div>`;

    body.querySelectorAll('[data-pc-chain-player]')
      .forEach(button => {
        button.addEventListener('click', () => {
          const replacementName =
            button.dataset.pcChainPlayer || '';
          const fromPosition =
            button.dataset.pcChainFrom || 'BENCH';

          const replacement = choices.find(
            player => player.name === replacementName
          );

          if (!replacement) return;

          if (fromPosition !== 'BENCH') {
            delete draft[fromPosition];
          }

          draft[vacancy] = replacement.name;

          // A bench player closes the final vacancy. Save the whole
          // defensive alignment plus pitcher change as one transaction.
          if (fromPosition === 'BENCH') {
            save(
              draft,
              `${incoming.name} in at P · ${oldPitcher} to bench`
            );
            return;
          }

          // A fielder moved into the vacancy. Their old position is now
          // open, so keep walking the coach through the chain.
          lockedNames.add(replacement.name);

          renderVacancy(
            draft,
            fromPosition,
            lockedNames
          );
        });
      });
  }

  function render() {
    const modal = ensureModal();
    const body = modal.querySelector('[data-pc-body]');
    if (!body || !incoming) return;

    const oldName = oldPitcher || 'Current pitcher';
    let actions = '';

    if (incomingPosition && oldPitcher) {
      actions = `
        <div class="pc-actions">
          <button type="button" class="btn btn-primary pc-action" data-pc-swap>
            ${esc(oldPitcher)} → ${esc(incomingPosition)}
            <small>Straight swap. Everyone else stays put.</small>
          </button>
          <button type="button" class="btn btn-outline-secondary pc-action" data-pc-bench-old>
            ${esc(oldPitcher)} → Bench
            <small>Choose who fills ${esc(incomingPosition)}.</small>
          </button>
        </div>`;
    } else {
      actions = `
        <div class="pc-actions">
          <button type="button" class="btn btn-primary pc-action" data-pc-bench-old>
            ${oldPitcher ? `${esc(oldPitcher)} → Bench` : 'Make Pitching Change'}
            <small>Everyone else stays put.</small>
          </button>
        </div>`;
    }

    body.innerHTML = `<div class="pc-summary"><strong>${esc(incoming.name)}</strong> → P<br><span class="text-muted">Where does ${esc(oldName)} go?</span></div>${actions}`;

    body.querySelector('[data-pc-swap]')?.addEventListener('click', () => {
      const draft = baseDraft();
      draft[incomingPosition] = oldPitcher;
      save(draft, `${incoming.name} in at P · ${oldPitcher} to ${incomingPosition}`);
    });

    body.querySelector('[data-pc-bench-old]')?.addEventListener('click', () => {
      if (incomingPosition && oldPitcher) {
        const draft = baseDraft();

        renderVacancy(
          draft,
          incomingPosition,
          new Set([
            incoming.name,
            oldPitcher,
          ]),
        );
        return;
      }

      save(baseDraft(), `${incoming.name} in at P`);
    });
  }

  async function save(alignment, successMessage) {
    if (busy) return;
    busy = true;
    const modal = ensureModal();
    modal.querySelectorAll('button').forEach(button => { if (!button.classList.contains('btn-close')) button.disabled = true; });
    try {
      const response = await fetch(`/api/live-game/${gameId}/complete-pitcher-change`,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          new_pitcher_id:Number(incoming.id),
          alignment,
          base_sequence:sequenceFromState(),
          fast:true,
        })
      });
      const data = await response.json().catch(()=>({}));
      if (!response.ok || data.status === 'error') {
        if (
          data.code === 'stale_live_state' ||
          data.code === 'missing_live_state_version'
        ) {
          try {
            state = await loadState();
          } catch (_) {}

          bootstrap.Modal
            .getOrCreateInstance(modal)
            .hide();
        }

        throw new Error(
          data.message ||
          `Unable to change pitcher (${response.status}).`
        );
      }

      // The fast pitcher-change response contains the same
      // authoritative live delta broadcast to the other coaches.
      // Apply it locally immediately so the coach who made the
      // change sees the header AND Quick Field update together.
      if (data.delta) {
        document.dispatchEvent(
          new CustomEvent('coachboard:live-delta', {
            detail: data.delta,
          })
        );
      }

      bootstrap.Modal.getOrCreateInstance(modal).hide();
      toast(successMessage);
    } catch (err) {
      toast(err.message,'danger');
      modal.querySelectorAll('button').forEach(button => { button.disabled = false; });
    } finally {
      busy = false;
    }
  }

  async function open(playerId) {
    try {
      state = await loadState();
      if (!state?.game?.is_live) throw new Error('Game is not live.');
      incoming = (state.roster || []).find(player => Number(player.id) === Number(playerId));
      if (!incoming) throw new Error('Pitcher is not available.');
      before = {...(state.current_alignment || {})};
      oldPitcher = before.P || '';
      incomingPosition = Object.entries(before).find(([pos,name]) => pos !== 'P' && name === incoming.name)?.[0] || null;
      render();
      bootstrap.Modal.getOrCreateInstance(ensureModal()).show();
    } catch (err) {
      toast(err.message,'danger');
    }
  }

  function intercept(event) {
    const choice = event.target.closest?.('.pitcher-choice-v2');
    if (!choice || choice.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    const playerId = Number(choice.dataset.playerId);
    if (!Number.isFinite(playerId)) return;
    const picker = $('live-pitcher-picker-v2');
    if (picker?.classList.contains('show')) {
      const instance = bootstrap.Modal.getOrCreateInstance(picker);
      picker.addEventListener('hidden.bs.modal',()=>open(playerId),{once:true});
      instance.hide();
    } else {
      open(playerId);
    }
  }

  installStyles();
  document.addEventListener('click',intercept,true);
})();