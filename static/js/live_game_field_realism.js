(() => {
  'use strict';

  const STYLE_ID = 'coach-real-field-styles';
  const FIELD_SELECTOR = '#coach-current-defense .coach-field';

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
        max-width: 820px;
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

      .coach-real-outfield-fence {
        position: absolute;
        left: 5%;
        right: 5%;
        top: 4%;
        height: 58%;
        border: 1.5px solid rgba(242,247,241,.42);
        border-bottom: 0;
        border-radius: 52% 52% 0 0 / 68% 68% 0 0;
      }

      .coach-real-warning-track {
        position: absolute;
        left: 7%;
        right: 7%;
        top: 6%;
        height: 56%;
        border: 4px solid rgba(171,129,79,.22);
        border-bottom: 0;
        border-radius: 52% 52% 0 0 / 68% 68% 0 0;
      }

      .coach-real-basepath {
        position: absolute;
        height: 4.8%;
        min-height: 12px;
        background: #c99c67;
        border-radius: 999px;
        transform-origin: 0 50%;
        box-shadow: inset 0 0 0 1px rgba(126,86,43,.05);
      }
      .coach-real-basepath.home-first { left:50%; top:84.5%; width:32.8%; transform:rotate(-45deg); }
      .coach-real-basepath.first-second { left:73.2%; top:61.3%; width:32.8%; transform:rotate(-135deg); }
      .coach-real-basepath.second-third { left:50%; top:38.1%; width:32.8%; transform:rotate(135deg); }
      .coach-real-basepath.third-home { left:26.8%; top:61.3%; width:32.8%; transform:rotate(45deg); }

      .coach-real-home-dirt {
        position: absolute;
        left: 50%;
        top: 87%;
        width: 15%;
        aspect-ratio: 1.15 / 1;
        transform: translate(-50%,-50%);
        border-radius: 48% 48% 54% 54%;
        background: #c99c67;
      }

      .coach-real-mound {
        position: absolute;
        left: 50%;
        top: 57%;
        width: 8.4%;
        aspect-ratio: 1;
        transform: translate(-50%,-50%);
        border-radius: 50%;
        background: #c99c67;
        box-shadow: inset 0 0 0 1px rgba(122,85,46,.10);
      }
      .coach-real-mound::after {
        content: '';
        position: absolute;
        left: 29%;
        right: 29%;
        top: 47%;
        height: 2px;
        border-radius: 2px;
        background: rgba(252,250,244,.94);
      }

      .coach-real-foul-line {
        position: absolute;
        bottom: 11%;
        left: 50%;
        width: 61%;
        height: 1.4px;
        background: rgba(255,255,255,.76);
        transform-origin: 0 50%;
      }
      .coach-real-foul-line.left { transform: rotate(-43.5deg); }
      .coach-real-foul-line.right { transform: rotate(-136.5deg); }

      .coach-real-base {
        position: absolute;
        width: 9px;
        height: 9px;
        background: #fffef7;
        border: 1px solid rgba(93,83,65,.18);
        border-radius: 1px;
        transform: translate(-50%,-50%) rotate(45deg);
        box-shadow: 0 1px 1px rgba(0,0,0,.10);
      }
      .coach-real-base.first { left:73.2%; top:61.4%; }
      .coach-real-base.second { left:50%; top:38.1%; }
      .coach-real-base.third { left:26.8%; top:61.4%; }

      .coach-real-home-plate {
        position: absolute;
        left: 50%;
        top: 86.8%;
        width: 12px;
        height: 11px;
        transform: translate(-50%,-50%);
        background: #fffef7;
        clip-path: polygon(12% 0,88% 0,100% 55%,50% 100%,0 55%);
        filter: drop-shadow(0 1px 1px rgba(0,0,0,.12));
      }

      .coach-field.coach-real-field .coach-field-spot {
        z-index: 4;
      }
      .coach-field.coach-real-field .coach-field-spot strong {
        color: rgba(255,255,255,.94) !important;
        text-shadow: 0 1px 2px rgba(0,0,0,.34);
        font-weight: 850;
        letter-spacing: .05em;
      }
      .coach-field.coach-real-field .coach-field-spot span {
        background: rgba(255,255,255,.95) !important;
        border-color: rgba(255,255,255,.72) !important;
        box-shadow: 0 2px 5px rgba(18,49,26,.15) !important;
      }

      @media (max-width: 575.98px) {
        .coach-field.coach-real-field {
          border-radius: 14px;
          aspect-ratio: 1.03 / 1;
        }
        .coach-field.coach-real-field .coach-field-spot {
          min-width: 50px !important;
          max-width: 74px !important;
        }
        .coach-field.coach-real-field .coach-field-spot strong {
          font-size: .52rem !important;
          margin-bottom: 2px !important;
        }
        .coach-field.coach-real-field .coach-field-spot span {
          font-size: .57rem !important;
          padding: 4px 5px !important;
          border-radius: 7px !important;
        }
        .coach-real-warning-track { border-width: 3px; opacity:.8; }
        .coach-real-outfield-fence { opacity:.78; }
        .coach-real-basepath { height: 4.2%; min-height: 10px; }
        .coach-real-base { width:8px; height:8px; }
        .coach-real-home-plate { width:10px; height:9px; }
      }

      @media (min-width: 576px) and (max-width: 1023.98px) {
        .coach-live-shell { max-width: 900px !important; padding: 0 10px; }
        .coach-actions { grid-template-columns: repeat(3, minmax(0,1fr)) !important; gap:10px !important; }
        #liveSetDefenseBtnCoach { grid-column: auto !important; }
        .coach-actions .btn { min-height: 66px !important; padding: 10px 12px !important; }
        .coach-action-title { font-size: 1rem !important; }
        .coach-action-note { font-size: .72rem !important; }
        .coach-card { padding: 15px !important; }
        .coach-view-toggle .btn { padding: 7px 14px !important; }
        .coach-field.coach-real-field { max-width: 720px; }
        .coach-field.coach-real-field .coach-field-spot { min-width: 72px !important; max-width: 108px !important; }
        .coach-field.coach-real-field .coach-field-spot span { font-size: .7rem !important; padding: 5px 7px !important; }
        #live-defense-v2 .modal-dialog,
        #live-pitcher-picker-v2 .modal-dialog,
        #live-defense-destination-v2 .modal-dialog,
        #live-pitcher-destination-v2 .modal-dialog,
        #live-bulk-defense-coach .modal-dialog {
          max-width: 680px !important;
          width: calc(100% - 40px) !important;
          margin: 1.75rem auto !important;
        }
        #live-defense-v2 .list-group-item,
        #live-pitcher-picker-v2 .pitcher-choice-v2 { padding: 14px !important; }
      }

      @media (min-width: 1024px) and (max-width: 1366px) {
        .coach-live-shell { max-width: 1080px !important; padding: 0 14px; }
        .coach-actions { grid-template-columns: repeat(5, minmax(0,1fr)) !important; gap:10px !important; }
        #liveSetDefenseBtnCoach { grid-column: auto !important; }
        .coach-actions .btn { min-height: 64px !important; }
        .coach-field.coach-real-field { max-width: 790px; }
        #live-defense-v2 .modal-dialog,
        #live-pitcher-picker-v2 .modal-dialog,
        #live-defense-destination-v2 .modal-dialog,
        #live-pitcher-destination-v2 .modal-dialog,
        #live-bulk-defense-coach .modal-dialog {
          max-width: 760px !important;
          width: calc(100% - 60px) !important;
          margin: 2rem auto !important;
        }
      }

      @media (min-width: 768px) and (max-width: 1366px) {
        .coach-game-header { gap: 20px !important; }
        .coach-game-header h3 { max-width: 720px; }
        .coach-game-header-actions .btn { min-width: 82px; min-height: 42px; }
      }
    `;
    document.head.appendChild(style);
  }

  function playerCoordinates(field) {
    const fourOutfielders = Boolean(field.querySelector('.coach-field-spot strong') &&
      [...field.querySelectorAll('.coach-field-spot strong')].some(el => el.textContent.trim() === 'LCF'));
    const phone = window.matchMedia('(max-width: 575.98px)').matches;

    const common = phone
      ? {
          '3B': [17, 53], 'SS': [35, 38], '2B': [65, 38], '1B': [83, 53],
          'P': [50, 55], 'C': [50, 93]
        }
      : {
          '3B': [19, 54], 'SS': [36, 39], '2B': [64, 39], '1B': [81, 54],
          'P': [50, 56], 'C': [50, 92]
        };

    const outfield = fourOutfielders
      ? (phone
          ? { 'LF':[11,21], 'LCF':[36,12], 'RCF':[64,12], 'RF':[89,21] }
          : { 'LF':[13,22], 'LCF':[37,13], 'RCF':[63,13], 'RF':[87,22] })
      : (phone
          ? { 'LF':[13,21], 'CF':[50,9], 'RF':[87,21] }
          : { 'LF':[15,22], 'CF':[50,10], 'RF':[85,22] });

    return { ...common, ...outfield };
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
      field.insertAdjacentHTML('afterbegin', `
        <div class="coach-real-field-skin" aria-hidden="true">
          <div class="coach-real-warning-track"></div>
          <div class="coach-real-outfield-fence"></div>
          <div class="coach-real-basepath home-first"></div>
          <div class="coach-real-basepath first-second"></div>
          <div class="coach-real-basepath second-third"></div>
          <div class="coach-real-basepath third-home"></div>
          <div class="coach-real-home-dirt"></div>
          <div class="coach-real-foul-line left"></div>
          <div class="coach-real-foul-line right"></div>
          <div class="coach-real-mound"></div>
          <span class="coach-real-base first"></span>
          <span class="coach-real-base second"></span>
          <span class="coach-real-base third"></span>
          <span class="coach-real-home-plate"></span>
        </div>
      `);
    }
    positionPlayers(field);
  }

  function scheduleDecorate() {
    requestAnimationFrame(() => requestAnimationFrame(decorateField));
  }

  document.addEventListener('DOMContentLoaded', () => {
    installStyles();
    scheduleDecorate();

    document.addEventListener('click', event => {
      if (event.target.closest('[data-coach-defense-view="field"]')) scheduleDecorate();
    });

    window.addEventListener('resize', scheduleDecorate, { passive: true });
    window.addEventListener('orientationchange', scheduleDecorate, { passive: true });

    setInterval(decorateField, 1200);
  });
})();
