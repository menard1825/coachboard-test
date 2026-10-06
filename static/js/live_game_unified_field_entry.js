(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  let dragSurface = null;

  function installStyles() {
    if (document.getElementById('cb-main-field-drag-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-main-field-drag-styles';
    style.textContent = `
      #cbQuickDefense .cb-qd-spot:not(.pitcher),
      #cbQuickDefense .cb-qd-bench-player{touch-action:manipulation;cursor:grab}
      #cbQuickDefense .cb-qd-spot:not(.pitcher):active,
      #cbQuickDefense .cb-qd-bench-player:active{cursor:grabbing}
      #cbQuickDefense .cb-qd-spot.cb-drag-over .cb-qd-name{outline:4px solid color-mix(in srgb,var(--cb-primary,#102a66) 25%,transparent);border-color:var(--cb-primary-text,#102a66);background:color-mix(in srgb,var(--cb-primary,#102a66) 5%,#fff)}
      #cbQuickDefense .cb-qd-bench-wrap.cb-drag-over{outline:4px solid rgba(22,107,56,.22);border-color:#5b9b70;background:#f0f8f2}
      #cbQuickDefense .cb-authoritative-open .cb-qd-name{border:2px dashed #d49a22;background:#fff8e7;color:#8b5c00;font-weight:850}
    `;
    document.head.appendChild(style);
  }

  /**
   * On the Field's half of the shared drag contract.
   *
   * The manager (live_game_drag_controller.js) owns every gesture
   * mechanic. What stays here is what only this board can answer:
   * who may be picked up, and what a drop point means. What a drop
   * does is not decided here: it is a normal live defensive move, and
   * live_game_dugout_mode.js has the one writer for those
   * (CBQuickFieldMoves.commit) -- the same one tapping uses, with the
   * same rules, refusals, Retry and one-move-at-a-time guard.
   *
   * A drag is decided against the field the coach picked the player up
   * from: the move context is captured at the start of the gesture and
   * travels with the source to the drop. If another device changes the
   * field in between, the writer refuses the drop instead of applying it
   * to the newer field.
   *
   * The P and Open refusals below are live-game rules -- the pitcher
   * changes through Change Pitcher, and an empty position is a
   * destination, not a thing to carry -- and they deliberately do not
   * match Next Inning's.
   */
  function registerDragSurface() {
    if (dragSurface || !window.CoachBoardDrag) return;

    const moves = () => window.CBQuickFieldMoves;

    dragSurface = window.CoachBoardDrag.registerSurface({
      id: 'on-field',
      root: () => document.getElementById('cbQuickDefense'),
      canStart: () => Boolean(moves()) && !moves().busy(),
      sourceSelector: '#cbQuickDefense [data-cb-move-player]',
      targetSelector: '#cbQuickDefense [data-cb-position], #cbQuickDefense .cb-qd-bench-wrap',

      resolveSource: node => {
        if (node.disabled) return null;
        const name = node.dataset.cbMovePlayer;
        if (!name || name === 'Open') return null;
        if (String(node.dataset.cbPosition || '').toUpperCase() === 'P') return null;
        return {
          kind: node.classList.contains('cb-qd-bench-player') ? 'chip' : 'marker',
          key: name,
          name,
          label: (node.querySelector('.cb-qd-name') || node.querySelector('span'))?.textContent?.trim() || name,
          context: moves().context(),
        };
      },

      // Called fresh on every move and never cached, so the manager can
      // tell a live source from one a rerender has already replaced
      // without knowing anything about how this board marks players.
      findSource: source => document.querySelector(
        `#cbQuickDefense [data-cb-move-player="${CSS.escape(source.name)}"]`
      ),

      resolveTarget: node => ({
        position: node.dataset.cbPosition
          ? String(node.dataset.cbPosition).toUpperCase()
          : 'BENCH',
      }),

      onDrop: (source, target) => moves()?.commit(source.name, target.position, source.context),
    });
  }

  document.addEventListener(
    'coachboard:live-state',
    event => {
      if (Number(event?.detail?.game_id) !== gameId) return;
      dragSurface?.cancel();
    }
  );

  document.addEventListener('DOMContentLoaded', () => {
    installStyles();
    registerDragSurface();
  });
})();
