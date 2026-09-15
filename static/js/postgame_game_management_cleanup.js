(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const gameId = Number(match[1]);
  const params = new URLSearchParams(window.location.search);
  const pitchingMode = params.get('pitching') === '1';
  const editMode = params.get('edit') === '1';
  if (!pitchingMode && !editMode) return;

  function injectStyles() {
    if (document.getElementById('cb-postgame-management-style')) return;
    const style = document.createElement('style');
    style.id = 'cb-postgame-management-style';
    style.textContent = `
      .cb-postgame-shell{max-width:900px;margin:18px auto;border:1px solid #dce3ec;border-radius:14px;background:#fff;padding:18px 20px;box-shadow:0 5px 18px rgba(15,23,42,.05)}
      .cb-postgame-shell h2{font-size:1.05rem;font-weight:850;color:#172033;margin:0 0 4px}.cb-postgame-shell p{font-size:.76rem;color:#667085;margin:0}.cb-postgame-shell .btn{font-weight:750}
      body.cb-postgame-pitching #pregame-checklist-container,body.cb-postgame-pitching #game-management-planner-row{display:none!important}
      body.cb-postgame-edit #pitching-log-container{display:none!important}
      @media(max-width:575.98px){.cb-postgame-shell{margin:10px 0;padding:14px}.cb-postgame-shell .d-flex{display:block!important}.cb-postgame-shell .btn{width:100%;margin-top:10px}}
    `;
    document.head.appendChild(style);
  }

  function shell(message, label) {
    let el = document.getElementById('cbPostgameManagementShell');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'cbPostgameManagementShell';
    el.className = 'cb-postgame-shell';
    el.innerHTML = `
      <div class="d-flex justify-content-between align-items-center gap-3">
        <div><h2>${label}</h2><p>${message}</p></div>
        <a class="btn btn-outline-primary btn-sm" href="/game-day/${gameId}/report"><i class="bi bi-arrow-left me-1"></i>Back to Game Report</a>
      </div>`;
    const main = document.querySelector('main') || document.querySelector('.container-fluid') || document.body;
    main.prepend(el);
    return el;
  }

  function setup() {
    injectStyles();

    if (pitchingMode) {
      document.body.classList.add('cb-postgame-pitching');
      shell('This game is complete. Enter or update the final GameChanger pitching line, then CoachBoard will return you to the Actual Game Report.', 'GameChanger Pitching');

      const modal = document.getElementById('liveFinalCountsModal');
      if (modal && modal.dataset.cbPostgameReturn !== '1') {
        modal.dataset.cbPostgameReturn = '1';
        modal.addEventListener('hidden.bs.modal', () => {
          if (window.location.pathname === `/game/${gameId}` && new URLSearchParams(window.location.search).get('pitching') === '1') {
            window.location.assign(`/game-day/${gameId}/report`);
          }
        });
      }
    }

    if (editMode) {
      document.body.classList.add('cb-postgame-edit');
      shell('This is the saved setup for a completed game. Final pitches and innings are managed from the Actual Game Report, so the old Pitching Log is hidden here.', 'Review / Edit Completed Game');
    }
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', setup, {once:true})
    : setup();
})();
