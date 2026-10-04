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
  const QUESTION_ID = 'live-pitcher-destination-v8';

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
            <ul class="list-unstyled mb-3" data-pc-summary hidden></ul>
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
   * Then, only if the coach sends Pat to an occupied position:
   * "Pat is moving to 1B. Riggins is at 1B. Where should Riggins go?" --
   * and so on until every displaced player has a place the coach chose.
   *
   * The pending change is built locally; nothing is saved while the
   * question is open. CoachBoard offers open positions, "another
   * position…" and the bench, but never decides for the coach: an
   * occupied position is only taken when the coach picks it, and its
   * player is always asked about next -- never benched or swapped
   * automatically.
   *
   * No loops: a player the chain has already placed (the new pitcher, or
   * anyone moved in this change) is never offered as a target again, so
   * every step either ends the chain or brings in a player not yet moved.
   * A chain of more than one move is shown as its resulting field before
   * it is made.
   *
   * Resolves with the chosen alignment and message, or null for Cancel,
   * or {stale: true} when the field changed underneath the question.
   */
  function askOutgoingDestination({
    incoming,
    oldPitcher,
    incomingPosition,
    before,
    sequence,
    positions,
  }) {
    const modal = questionModal();
    const instance = bootstrap.Modal.getOrCreateInstance(modal);
    const list = modal.querySelector('[data-pc-choices]');
    const titleEl = modal.querySelector('[data-pc-title]');
    const questionEl = modal.querySelector('[data-pc-question]');
    const summaryEl = modal.querySelector('[data-pc-summary]');

    const spots = positions.filter(pos => pos !== 'P');
    const base = {...before, P: incoming.name};

    if (incomingPosition) {
      delete base[incomingPosition];
    }

    const openSpots = spots.filter(pos => !base[pos]);
    const occupiedSpots = spots.filter(pos => base[pos]);

    return new Promise(resolve => {
      let answer = null;
      let stale = false;
      let decided = false;
      let closed;
      const whenClosed = new Promise(done => { closed = done; });

      modal.addEventListener(
        'shown.bs.modal',
        () => {
          if (stale || decided) instance.hide();
        },
        {once: true},
      );

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

      modal.addEventListener(
        'hidden.bs.modal',
        () => {
          document.removeEventListener('coachboard:live-delta', onLiveChange);
          document.removeEventListener('coachboard:live-state', onLiveChange);
          closed();
          resolve(answer);
        },
        {once: true},
      );

      const finish = value => {
        if (decided) return;
        answer = value;

        if (value) {
          decided = true;
          list.querySelectorAll('button').forEach(button => {
            button.disabled = true;
          });
          resolve({...value, closed: whenClosed});
        }

        instance.hide();
      };

      const choose = (label, build) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-outline-primary';
        button.textContent = label;
        button.addEventListener('click', () => {
          if (stale || decided) return;
          finish(build());
        });
        return button;
      };

      titleEl.textContent = `${incoming.name} is going in to pitch`;
      questionEl.textContent = `Where should ${oldPitcher} go?`;
      summaryEl.hidden = true;
      summaryEl.replaceChildren();

      const buttons = [];

      // Bench is always valid. The new pitcher's former position, if any,
      // simply stays open.
      buttons.push(
        choose(`Bench ${oldPitcher}`, () => {
          const alignment = {...base};
          const opened = incomingPosition ? ` · ${incomingPosition} open` : '';
          return {
            alignment,
            message: `${incoming.name} is pitching · ${oldPitcher} to Bench${opened}`,
          };
        }),
      );

      // Open spots are direct destinations, including the position vacated
      // by a fielder who just became the pitcher.
      openSpots.forEach(pos => {
        buttons.push(
          choose(`${oldPitcher} → ${pos}`, () => ({
            alignment: {...base, [pos]: oldPitcher},
            message: `${incoming.name} is pitching · ${oldPitcher} to ${pos}`,
          })),
        );
      });

      // An occupied destination means "swap" in one decision. If the incoming
      // pitcher vacated a field position, the displaced fielder fills it;
      // otherwise the displaced fielder goes to the bench.
      occupiedSpots.forEach(pos => {
        const displaced = base[pos];

        buttons.push(
          choose(`Swap with ${displaced} at ${pos}`, () => {
            const alignment = {...base, [pos]: oldPitcher};
            let tail = `${displaced} to Bench`;

            if (
              incomingPosition &&
              incomingPosition !== pos &&
              !alignment[incomingPosition]
            ) {
              alignment[incomingPosition] = displaced;
              tail = `${displaced} to ${incomingPosition}`;
            }

            return {
              alignment,
              message:
                `${incoming.name} is pitching · ${oldPitcher} to ${pos} · ${tail}`,
            };
          }),
        );
      });

      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'btn btn-outline-secondary';
      cancel.textContent = 'Cancel';
      cancel.addEventListener('click', () => finish(null));
      buttons.push(cancel);

      list.replaceChildren(...buttons);
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

    let decision;

    try {
      // Read while the pitcher list is still closing (options.afterClose),
      // then ask once it has gone.
      const reading = loadState();
      reading.catch(() => {});
      await options?.afterClose;
      state = await reading;

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
      // Not done until the question has gone: Change Pitcher cannot open
      // again over a closing dialog.
      await decision?.closed;
      busy = false;
    }
  }

  window.CBPitcherChangeComplete =
    Object.freeze({
      version: 7,
      open,
    });
})();
