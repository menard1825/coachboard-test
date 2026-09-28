(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);

  // Idempotent: older enhancement loaders may request this file more
  // than once. Only one two-tap pitcher-change controller may exist.
  if (window.CBPitcherChangeComplete?.version === 6) {
    return;
  }

  let state = null;
  let busy = false;

  const esc = value => String(value ?? '').replace(
    /[&<>"']/g,
    ch => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[ch]),
  );

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

  function toast(message, kind = 'success') {
    let host = document.getElementById(
      'pitcher-change-toast-v6'
    );

    if (!host) {
      host = document.createElement('div');
      host.id = 'pitcher-change-toast-v6';
      host.className =
        'toast-container position-fixed top-0 end-0 p-3';
      host.style.zIndex = '5000';
      document.body.appendChild(host);
    }

    const el = document.createElement('div');
    el.className =
      `toast text-bg-${kind} border-0`;

    el.innerHTML = `
      <div class="d-flex">
        <div class="toast-body fw-semibold">
          ${esc(message)}
        </div>
        <button
          type="button"
          class="btn-close btn-close-white me-2 m-auto"
          data-bs-dismiss="toast"
        ></button>
      </div>`;

    host.appendChild(el);

    const instance =
      bootstrap.Toast.getOrCreateInstance(
        el,
        {delay: 2600},
      );

    el.addEventListener(
      'hidden.bs.toast',
      () => el.remove(),
      {once: true},
    );

    instance.show();
  }

  async function loadState() {
    const response = await fetch(
      `/api/live-game/${gameId}/state`,
      {cache: 'no-store'},
    );

    const data =
      await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(
        data.message ||
        `Unable to load game (${response.status}).`
      );
    }

    return data;
  }

  async function save(
    incoming,
    alignment,
    successMessage,
    pitchingDecision = null,
  ) {
    const response = await fetch(
      `/api/live-game/${gameId}/complete-pitcher-change`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          new_pitcher_id: Number(incoming.id),
          alignment,
          base_sequence: sequenceFromState(),
          fast: true,
          // The coach's explicit decision on a flagged pitcher, for the
          // status they were shown (see pitching_eligibility.py).
          ...(pitchingDecision?.type
            ? {
                pitching_decision: pitchingDecision.type,
                pitching_decision_status: pitchingDecision.status || '',
              }
            : {}),
        }),
      },
    );

    const data =
      await response.json().catch(() => ({}));

    if (
      !response.ok ||
      data.status === 'error'
    ) {
      if (
        data.code === 'stale_live_state' ||
        data.code === 'missing_live_state_version'
      ) {
        try {
          state = await loadState();
        } catch (_) {}
      }

      throw new Error(
        data.code === 'stale_live_state'
          ? STALE_MESSAGE
          : data.message ||
            `Unable to change pitcher (${response.status}).`
      );
    }

    // Apply the same authoritative delta sent to every other
    // connected coach so this device updates immediately.
    if (data.delta) {
      document.dispatchEvent(
        new CustomEvent(
          'coachboard:live-delta',
          {
            detail: data.delta,
          },
        ),
      );
    }

    toast(successMessage);

    return data;
  }

  const STALE_MESSAGE =
    'Defense changed on another device. Check the field and try the pitching change again.';
  const QUESTION_ID = 'live-pitcher-destination-v7';

  function filled(alignment) {
    return Object.fromEntries(
      Object.entries(alignment || {}).filter(([, name]) => name)
    );
  }

  function sameField(a, b) {
    const key = alignment => JSON.stringify(
      Object.entries(filled(alignment)).sort(([x], [y]) => (x < y ? -1 : 1))
    );
    return key(a) === key(b);
  }

  function questionModal() {
    let modal = document.getElementById(QUESTION_ID);
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = QUESTION_ID;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('aria-hidden', 'true');
    modal.setAttribute('aria-labelledby', `${QUESTION_ID}-title`);
    modal.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="${QUESTION_ID}-title" data-pc-title></h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="fw-semibold mb-2" data-pc-question></div>
            <div class="d-grid gap-2" data-pc-choices></div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);
    return modal;
  }

  /*
   * "Graham is going in to pitch. Where should Pat go?"
   *
   * Resolves with the chosen alignment and message, or null for Cancel
   * or when the field changed underneath the question. Nothing is saved
   * while it is open.
   */
  function askOutgoingDestination({incoming, oldPitcher, incomingPosition, before, sequence, positions}) {
    const modal = questionModal();
    const instance = bootstrap.Modal.getOrCreateInstance(modal);
    const list = modal.querySelector('[data-pc-choices]');

    const base = {...before, P: incoming.name};
    if (incomingPosition) delete base[incomingPosition];

    const choices = [];

    if (incomingPosition) {
      choices.push({
        label: `Put ${oldPitcher} at ${incomingPosition}`,
        alignment: {...base, [incomingPosition]: oldPitcher},
        message: `${incoming.name} is pitching · ${oldPitcher} to ${incomingPosition}`,
      });
    }

    positions
      .filter(pos => pos !== 'P' && pos !== incomingPosition && !before[pos])
      .forEach(pos => {
        choices.push({
          label: `Put ${oldPitcher} at ${pos}`,
          alignment: {...base, [pos]: oldPitcher},
          message: `${incoming.name} is pitching · ${oldPitcher} to ${pos}` +
            (incomingPosition ? ` · ${incomingPosition} is open` : ''),
        });
      });

    choices.push({
      label: incomingPosition
        ? `Bench ${oldPitcher} · ${incomingPosition} open`
        : `Bench ${oldPitcher}`,
      alignment: base,
      message: `${incoming.name} is pitching · ${oldPitcher} to Bench` +
        (incomingPosition ? ` · ${incomingPosition} is open` : ''),
    });

    modal.querySelector('[data-pc-title]').textContent =
      `${incoming.name} is going in to pitch`;
    modal.querySelector('[data-pc-question]').textContent =
      `Where should ${oldPitcher} go?`;
    list.replaceChildren();

    return new Promise(resolve => {
      let answer = null;
      let stale = false;

      // Bootstrap ignores hide() while the modal is still fading in.
      modal.addEventListener('shown.bs.modal', () => {
        if (stale) instance.hide();
      }, {once: true});

      // The official field moved on (another coach, an Undo) while the
      // coach was deciding: this answer no longer applies to it.
      const onLiveChange = event => {
        const detail = event.detail || {};
        if (Number(detail.game_id) !== gameId) return;
        const next = detail.state || detail;
        const nextSequence = detail.state
          ? sequenceFromState(detail.state)
          : Number(detail.sequence);
        if (
          !sameField(next.current_alignment, before) ||
          (Number.isFinite(nextSequence) && nextSequence !== sequence)
        ) {
          stale = true;
          answer = {stale: true};
          instance.hide();
        }
      };

      document.addEventListener('coachboard:live-delta', onLiveChange);
      document.addEventListener('coachboard:live-state', onLiveChange);

      modal.addEventListener('hidden.bs.modal', () => {
        document.removeEventListener('coachboard:live-delta', onLiveChange);
        document.removeEventListener('coachboard:live-state', onLiveChange);
        resolve(answer);
      }, {once: true});

      const addButton = (label, className, onChoose) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `btn ${className}`;
        button.textContent = label;
        button.addEventListener('click', () => {
          // An answer given after the field changed is not applied.
          if (!stale) onChoose();
          instance.hide();
        });
        list.appendChild(button);
      };

      choices.forEach(choice => {
        addButton(choice.label, 'btn-outline-primary', () => {
          answer = choice;
        });
      });
      addButton('Cancel', 'btn-outline-secondary', () => {
        answer = null;
      });

      instance.show();
    });
  }

  function fieldPositions() {
    return Number(state?.outfielder_count) === 4
      ? ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'LCF', 'RCF', 'RF']
      : ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'];
  }

  async function open(playerId, options = {}) {
    if (busy) return;

    busy = true;

    const pitchingDecision =
      options?.pitchingDecision || null;

    try {
      state = await loadState();

      if (!state?.game?.is_live) {
        throw new Error('Game is not live.');
      }

      const incoming =
        (state.roster || []).find(
          player =>
            Number(player.id) === Number(playerId)
        );

      if (!incoming) {
        throw new Error(
          'Pitcher is not available.'
        );
      }

      const before = {
        ...(state.current_alignment || {}),
      };

      const oldPitcher =
        before.P || '';

      const incomingPosition =
        Object.entries(before).find(
          ([position, name]) =>
            position !== 'P' &&
            name === incoming.name
        )?.[0] || null;

      /*
       * The coach has said who is going in to pitch -- not where the
       * pitcher coming out goes. Ask that before anything is saved, then
       * save the whole decision as one pitching change (one Undo).
       * With nobody on the mound there is nothing more to ask.
       */
      let decision;

      if (oldPitcher) {
        decision = await askOutgoingDestination({
          incoming,
          oldPitcher,
          incomingPosition,
          before,
          sequence: sequenceFromState(),
          positions: fieldPositions(),
        });

        if (!decision) return;

        if (decision.stale) {
          throw new Error(STALE_MESSAGE);
        }
      } else {
        const alignment = {...before, P: incoming.name};
        if (incomingPosition) delete alignment[incomingPosition];
        decision = {
          alignment,
          message: `${incoming.name} is pitching` +
            (incomingPosition ? ` · ${incomingPosition} is open` : ''),
        };
      }

      await save(
        incoming,
        decision.alignment,
        decision.message,
        pitchingDecision,
      );
    } catch (err) {
      toast(
        err.message ||
        'Unable to change pitcher.',
        'danger',
      );
    } finally {
      busy = false;
    }
  }

  window.CBPitcherChangeComplete =
    Object.freeze({
      version: 6,
      open,
    });
})();
