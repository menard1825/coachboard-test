(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);

  // Idempotent: older enhancement loaders may request this file more
  // than once. Only one two-tap pitcher-change controller may exist.
  if (window.CBPitcherChangeComplete?.version === 5) {
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
      'pitcher-change-toast-v5'
    );

    if (!host) {
      host = document.createElement('div');
      host.id = 'pitcher-change-toast-v5';
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
        data.message ||
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

  async function open(playerId) {
    if (busy) return;

    busy = true;

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
       * Two-tap contract:
       *
       * 1. Coach taps Change Pitcher.
       * 2. Coach taps the new pitcher.
       *
       * That player becomes P immediately.
       * The outgoing pitcher becomes unassigned (Bench).
       * If the incoming pitcher was in the field, that non-P
       * position becomes OPEN.
       *
       * On the Field owns every defensive move after that.
       */
      const alignment = {...before};

      if (incomingPosition) {
        delete alignment[incomingPosition];
      }

      alignment.P = incoming.name;

      const messageParts = [
        `${incoming.name} is pitching`,
      ];

      if (oldPitcher) {
        messageParts.push(
          `${oldPitcher} to Bench`
        );
      }

      if (incomingPosition) {
        messageParts.push(
          `${incomingPosition} Open`
        );
      }

      await save(
        incoming,
        alignment,
        messageParts.join(' · '),
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
      version: 5,
      open,
    });
})();
