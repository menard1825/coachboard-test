(() => {
  'use strict';

  const STYLE_ID = 'coach-real-field-styles';
  const FIELD_SELECTOR = '#coach-current-defense .coach-field';

  function loadPitcherChangeWizard() {
    if (document.querySelector('script[data-live-pitcher-change-complete]')) return;
    const script = document.createElement('script');
    script.src = '/static/js/live_game_pitcher_change_complete.js';
    script.dataset.livePitcherChangeComplete = 'true';
    document.head.appendChild(script);
  }

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .coach-field.coach-real-field {
        position: relative;
        overflow: hidden;
        isolation: isolate;
        width: 100%;
        max-width: 760px;
        aspect-ratio: 1.12 / 1;
        margin: 10px auto 0;
        border: 1px solid #aebfac;
        border-radius: 18px;
        background:
          repeating-linear-gradient(90deg, rgba(255,255,255,.032) 0 8.5%, rgba(15,66,28,.045) 8.5% 17%),
          linear-gradient(180deg, #38854b 0%, #4b965a 58%, #438a51 100%) !important;
        box-shadow: inset 0 -18px 36px rgba(20,64,32,.08), 0 1px 3px rgba(16,24,40,.06);
      }

      .coach-field.coach-real-field .coach-field-arc,
      .coach-field.coach-real-field .coach-field-infield {
        display: none !important;
      }

      .coach-real-field-skin {
        position: absolute;
        inset: 0;
        z-index: 0;
        pointer-events: none;
      }

      .coach-real-field-skin svg {
        display: block;
        width: 100%;
        height: 100%;
      }

      .coach-field.coach-real-field .coach-field-spot {
        z-index: 4;
        min-width: 62px;
        max-width: 98px;
      }

      .coach-field.coach-real-field .coach-field-spot strong {
        color: rgba(255,255,255,.94) !important;
        text-shadow: 0 1px 2px rgba(0,0,0,.36);
        font-size: .55rem !important;
        font-weight: 850;
        letter-spacing: .05em;
        margin-bottom: 2px !important;
      }

      .coach-field.coach-real-field .coach-field-spot span {
        background: rgba(255,255,255,.95) !important;
        border-color: rgba(255,255,255,.72) !important;
        box-shadow: 0 2px 5px rgba(18,49,26,.15) !important;
        font-size: .64rem !important;
        line-height: 1.15;
        padding: 5px 7px !important;
        border-radius: 7px !important;
      }

      @media (max-width: 575.98px) {
        .coach-field.coach-real-field {
          max-width: none;
          border-radius: 14px;
          aspect-ratio: 1.03 / 1;
        }
        .coach-field.coach-real-field .coach-field-spot {
          min-width: 48px !important;
          max-width: 72px !important;
        }
        .coach-field.coach-real-field .coach-field-spot strong {
          font-size: .49rem !important;
        }
        .coach-field.coach-real-field .coach-field-spot span {
          font-size: .55rem !important;
          padding: 4px 5px !important;
        }
      }

      @media (min-width: 576px) and (max-width: 899.98px) {
        .coach-live-shell { max-width: 860px !important; padding: 0 10px; }
        .coach-actions { grid-template-columns: repeat(3, minmax(0,1fr)) !important; gap:10px !important; }
        #liveSetDefenseBtnCoach { grid-column: auto !important; }
        .coach-actions .btn { min-height: 66px !important; padding: 10px 12px !important; }
        .coach-action-title { font-size: 1rem !important; }
        .coach-action-note { font-size: .72rem !important; }
        .coach-card { padding: 15px !important; }
        .coach-view-toggle .btn { padding: 7px 14px !important; }
        .coach-field.coach-real-field { max-width: 680px; }
        .coach-field.coach-real-field .coach-field-spot { min-width: 68px !important; max-width: 102px !important; }
        .coach-field.coach-real-field .coach-field-spot span { font-size: .68rem !important; }
      }

      @media (min-width: 900px) and (max-width: 1180px) {
        .coach-live-shell { max-width: 1040px !important; padding: 0 14px; }
        .coach-actions { grid-template-columns: repeat(5, minmax(0,1fr)) !important; gap:10px !important; }
        #liveSetDefenseBtnCoach { grid-column:auto !important; }
        .coach-actions .btn { min-height:64px !important; }
        .coach-field.coach-real-field { max-width: 720px; }
      }

      @media (min-width: 1181px) and (max-width: 1440px) {
        .coach-live-shell { max-width: 1080px !important; padding: 0 14px; }
        .coach-actions { grid-template-columns: repeat(5, minmax(0,1fr)) !important; gap:10px !important; }
        #liveSetDefenseBtnCoach { grid-column:auto !important; }
        .coach-field.coach-real-field { max-width: 735px; }
      }

      @media (min-width: 1441px) {
        .coach-live-shell { max-width: 1120px !important; }
        .coach-actions { grid-template-columns: repeat(5, minmax(0,1fr)) !important; gap:10px !important; }
        #liveSetDefenseBtnCoach { grid-column:auto !important; }
        .coach-card:has(#coach-current-defense) { padding: 14px 18px 16px !important; }
        .coach-field.coach-real-field {
          width: min(100%, 720px);
          max-width: 720px;
          aspect-ratio: 1.12 / 1;
        }
        .coach-field.coach-real-field .coach-field-spot {
          min-width: 66px !important;
          max-width: 100px !important;
        }
        .coach-field.coach-real-field .coach-field-spot span {
          font-size: .65rem !important;
        }
      }

      @media (min-width: 576px) and (max-width: 1366px) {
        #live-defense-v2 .modal-dialog,
        #live-pitcher-picker-v2 .modal-dialog,
        #live-defense-destination-v2 .modal-dialog,
        #live-pitcher-destination-v2 .modal-dialog,
        #live-bulk-defense-coach .modal-dialog {
          max-width: 700px !important;
          width: calc(100% - 48px) !important;
          margin: 1.75rem auto !important;
        }
        #live-defense-v2 .list-group-item,
        #live-pitcher-picker-v2 .pitcher-choice-v2 {
          padding: 14px !important;
        }
        .coach-game-header { gap:20px !important; }
        .coach-game-header h3 { max-width:720px; }
        .coach-game-header-actions .btn { min-width:82px; min-height:42px; }
      }
    `;
    document.head.appendChild(style);
  }

  function fieldSvg() {
    return `
      <svg viewBox="0 0 1000 890" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="coachGrassFade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#57a565" stop-opacity=".10" />
            <stop offset="100%" stop-color="#1e5d32" stop-opacity=".08" />
          </linearGradient>
          <filter id="coachSoftShadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="1" stdDeviation="1.2" flood-color="#17351f" flood-opacity=".18"/>
          </filter>
        </defs>
        <path d="M78,598 Q70,210 500,55 Q930,210 922,598" fill="none" stroke="#edf5ec" stroke-opacity=".38" stroke-width="3" />
        <path d="M98,598 Q92,232 500,82 Q908,232 902,598" fill="none" stroke="#a77b49" stroke-opacity=".28" stroke-width="10" />
        <path d="M110,610 Q105,250 500,105 Q895,250 890,610 L890,760 L110,760 Z" fill="url(#coachGrassFade)" opacity=".36" />
        <line x1="500" y1="792" x2="104" y2="392" stroke="#fff" stroke-opacity=".78" stroke-width="2" />
        <line x1="500" y1="792" x2="896" y2="392" stroke="#fff" stroke-opacity=".78" stroke-width="2" />
        <path d="M500,735 L745,555 Q758,545 744,532 L515,318 Q500,304 485,318 L256,532 Q242,545 255,557 Z" fill="#c99a62" filter="url(#coachSoftShadow)" />
        <path d="M500,676 L682,548 Q692,540 682,531 L511,374 Q500,364 489,374 L318,531 Q308,540 318,548 Z" fill="#4a9358" />
        <ellipse cx="500" cy="788" rx="70" ry="55" fill="#c99a62" />
        <circle cx="500" cy="590" r="35" fill="#c99a62" />
        <rect x="485" y="587" width="30" height="4" rx="2" fill="#faf8f1" />
        <rect x="704" y="541" width="15" height="15" rx="1.5" fill="#fffdf5" stroke="#8f7c5e" stroke-opacity=".28" transform="rotate(45 711.5 548.5)" />
        <rect x="492.5" y="333" width="15" height="15" rx="1.5" fill="#fffdf5" stroke="#8f7c5e" stroke-opacity=".28" transform="rotate(45 500 340.5)" />
        <rect x="281" y="541" width="15" height="15" rx="1.5" fill="#fffdf5" stroke="#8f7c5e" stroke-opacity=".28" transform="rotate(45 288.5 548.5)" />
        <path d="M488,779 L512,779 L516,790 L500,805 L484,790 Z" fill="#fffdf5" stroke="#8f7c5e" stroke-opacity=".25" />
      </svg>`;
  }

  function playerCoordinates(field) {
    const labels = [...field.querySelectorAll('.coach-field-spot strong')].map(el => el.textContent.trim());
    const fourOutfielders = labels.includes('LCF');
    const phone = window.matchMedia('(max-width:575.98px)').matches;
    const desktop = window.matchMedia('(min-width:1181px)').matches;

    const common = phone
      ? {'3B':[18,56],'SS':[36,42],'2B':[64,42],'1B':[82,56],'P':[50,62],'C':[50,91]}
      : desktop
        ? {'3B':[23,58],'SS':[37,45],'2B':[63,45],'1B':[77,58],'P':[50,63],'C':[50,91]}
        : {'3B':[21,57],'SS':[36,44],'2B':[64,44],'1B':[79,57],'P':[50,62],'C':[50,91]};

    const outfield = fourOutfielders
      ? (phone
          ? {'LF':[12,22],'LCF':[36,13],'RCF':[64,13],'RF':[88,22]}
          : {'LF':[16,25],'LCF':[37,15],'RCF':[63,15],'RF':[84,25]})
      : (phone
          ? {'LF':[14,22],'CF':[50,10],'RF':[86,22]}
          : desktop
            ? {'LF':[18,26],'CF':[50,14],'RF':[82,26]}
            : {'LF':[16,24],'CF':[50,13],'RF':[84,24]});

    return {...common,...outfield};
  }

  function positionPlayers(field) {
    if (!field) return;
    const coordinates = playerCoordinates(field);
    field.querySelectorAll('.coach-field-spot').forEach(spot => {
      const pos = spot.querySelector('strong')?.textContent?.trim();
      const xy = coordinates[pos];
      if (!xy) return;
      spot.style.left = `${xy[0]}%`;
      spot.style.top = `${xy[1]}%`;
    });
  }

  function decorateField() {
    const field = document.querySelector(FIELD_SELECTOR);
    if (!field) return;
    if (!field.classList.contains('coach-real-field')) {
      field.classList.add('coach-real-field');
      field.insertAdjacentHTML('afterbegin', `<div class="coach-real-field-skin">${fieldSvg()}</div>`);
    }
    positionPlayers(field);
  }

  function scheduleDecorate() {
    requestAnimationFrame(() => requestAnimationFrame(decorateField));
  }

  loadPitcherChangeWizard();

  document.addEventListener('DOMContentLoaded', () => {
    installStyles();
    scheduleDecorate();
    document.addEventListener('click', event => {
      if (event.target.closest('[data-coach-defense-view="field"]')) scheduleDecorate();
    });
    window.addEventListener('resize', scheduleDecorate, {passive:true});
    window.addEventListener('orientationchange', scheduleDecorate, {passive:true});
    setInterval(decorateField, 1200);
  });
})();
