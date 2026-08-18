(() => {
  'use strict';

  function normalize(data) {
    if (!data || typeof data !== 'object') return data;

    (data.pitching_usage || []).forEach((row) => {
      if (row.pitch_history_complete === false) {
        row.total_pitches = 'Incomplete';
        row.pitches_per_appearance = null;
      }
    });

    if (data.summary && data.summary.pitch_history_complete === false) {
      data.summary.team_pitching_pitches = 'Incomplete';
    }

    return data;
  }

  function install() {
    const renderer = window.CoachStatsV2Renderer;
    if (!renderer || renderer.__integrityWrapped) return false;

    const originalRender = renderer.render;
    const originalOpenPlayer = renderer.openPlayer;

    renderer.render = function(data, state) {
      return originalRender.call(this, normalize(data), state);
    };
    renderer.openPlayer = function(data, id) {
      return originalOpenPlayer.call(this, normalize(data), id);
    };
    renderer.__integrityWrapped = true;
    return true;
  }

  if (!install()) {
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (install() || attempts >= 100) window.clearInterval(timer);
    }, 25);
  }
})();
