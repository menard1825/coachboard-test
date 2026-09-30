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

    // "Cancel change" at "Has the 4th inning started?"
    // (live_game_inning_clarity.js): nothing was saved and the pitcher is
    // unchanged.
    if (data.code === 'inning_start_cancelled') {
      toast('Pitching change cancelled.');
      return null;
    }

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
  function askOutgoingDestination({incoming, oldPitcher, incomingPosition, before, sequence, positions}) {
    const modal = questionModal();
    const instance = bootstrap.Modal.getOrCreateInstance(modal);
    const list = modal.querySelector('[data-pc-choices]');
    const titleEl = modal.querySelector('[data-pc-title]');
    const questionEl = modal.querySelector('[data-pc-question]');
    const summaryEl = modal.querySelector('[data-pc-summary]');

    const spots = positions.filter(pos => pos !== 'P');
    const draft = {...before, P: incoming.name};
    if (incomingPosition) delete draft[incomingPosition];

    // Moves the coach has decided, in order: {name, to} (to = a position
    // or 'Bench'). Players placed by this change are never moved again.
    const moves = [];
    const placed = new Set([incoming.name]);

    const openSpots = () => spots.filter(pos => !draft[pos]);
    const openNote = () => {
      const open = openSpots();
      if (!open.length) return '';
      return ` · ${open.join(', ')} ${open.length === 1 ? 'is' : 'are'} open`;
    };
    // Occupied positions whose player this change has not moved yet.
    const takenSpots = () => spots.filter(
      pos => draft[pos] && !placed.has(draft[pos])
    );

    const message = () =>
      `${incoming.name} is pitching · ` +
      moves.map(move => `${move.name} to ${move.to}`).join(' · ') +
      openNote();

    const lines = () => [
      `${incoming.name} → P` +
        (incomingPosition ? ` (from ${incomingPosition})` : ' (from Bench)'),
      ...moves.map(move => {
        const from = Object.entries(before).find(
          ([pos, name]) => name === move.name
        )?.[0] || 'Bench';
        return `${move.name}: ${from} → ${move.to}`;
      }),
      ...openSpots().map(pos => `${pos}: open`),
    ];

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

      const finish = value => {
        answer = value;
        instance.hide();
      };

      // One step of the conversation: a title, a question, buttons.
      const render = (title, question, buttons, summary = []) => {
        titleEl.textContent = title;
        questionEl.textContent = question;
        summaryEl.replaceChildren(...summary.map(text => {
          const item = document.createElement('li');
          item.textContent = text;
          return item;
        }));
        summaryEl.hidden = !summary.length;
        list.replaceChildren(...buttons.map(([label, className, onChoose]) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = `btn ${className}`;
          button.textContent = label;
          button.addEventListener('click', () => {
            // An answer given after the field changed is not applied.
            if (stale) {
              instance.hide();
              return;
            }
            onChoose();
          });
          return button;
        }));
      };

      const cancel = ['Cancel', 'btn-outline-secondary', () => finish(null)];

      const resolved = () => {
        const result = {alignment: {...draft}, message: message()};
        // One move is the tap the coach just made; a chain is shown as
        // the field it produces before anything is changed.
        if (moves.length === 1) {
          finish(result);
          return;
        }
        render(
          'Check the pitching change',
          'This is the field after the change:',
          [
            ['Make this change', 'btn-primary', () => finish(result)],
            cancel,
          ],
          lines(),
        );
      };

      const place = (name, to) => {
        if (to !== 'Bench') draft[to] = name;
        placed.add(name);
        moves.push({name, to});
      };

      // "Where should <name> go?"
      const ask = (name, title, question) => {
        const buttons = openSpots().map(pos => [
          `Put ${name} at ${pos}`,
          'btn-outline-primary',
          () => {
            place(name, pos);
            resolved();
          },
        ]);
        if (takenSpots().length) {
          buttons.push([
            `Move ${name} to another position…`,
            'btn-outline-primary',
            () => choosePosition(name, title, question),
          ]);
        }
        // Name only the spots this change opens (e.g. the new pitcher's).
        const opened = openSpots().filter(pos => before[pos]);
        buttons.push([
          `Bench ${name}` + (opened.length ? ` · ${opened.join(', ')} open` : ''),
          'btn-outline-primary',
          () => {
            place(name, 'Bench');
            resolved();
          },
        ]);
        buttons.push(cancel);
        render(title, question, buttons);
      };

      // Every position with a player this change hasn't moved, by name.
      const choosePosition = (name, title, question) => {
        render(
          title,
          `Where should ${name} go?`,
          [
            ...takenSpots().map(pos => [
              `${pos} · ${draft[pos]}`,
              'btn-outline-primary',
              () => {
                const occupant = draft[pos];
                place(name, pos);
                ask(
                  occupant,
                  `${name} is moving to ${pos}`,
                  `${occupant} is at ${pos}. Where should ${occupant} go?`,
                );
              },
            ]),
            ['Back', 'btn-outline-secondary', () => ask(name, title, question)],
            cancel,
          ],
        );
      };

      ask(
        oldPitcher,
        `${incoming.name} is going in to pitch`,
        `Where should ${oldPitcher} go?`,
      );

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
