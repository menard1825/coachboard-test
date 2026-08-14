(() => {
  'use strict';

  const STYLE_ID = 'coach-real-field-styles';

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .coach-field.coach-real-field {
        position: relative;
        overflow: hidden;
        isolation: isolate;
        border: 1px solid #b8c9b7;
        border-radius: 18px;
        background:
          repeating-linear-gradient(90deg, rgba(255,255,255,.035) 0 9%, rgba(0,0,0,.025) 9% 18%),
          linear-gradient(180deg, #3d8b52 0%, #4d965c 62%, #45864f 100%) !important;
        box-shadow: inset 0 -18px 35px rgba(24,65,35,.08), 0 1px 2px rgba(16,24,40,.05);
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
        left: 4%;
        right: 4%;
        top: 3%;
        height: 63%;
        border: 2px solid rgba(236,244,235,.55);
        border-bottom: 0;
        border-radius: 52% 52% 0 0 / 64% 64% 0 0;
        opacity: .7;
      }

      .coach-real-warning-track {
        position: absolute;
        left: 6.5%;
        right: 6.5%;
        top: 5.5%;
        height: 60%;
        border: 7px solid rgba(177,137,87,.34);
        border-bottom: 0;
        border-radius: 52% 52% 0 0 / 64% 64% 0 0;
      }

      .coach-real-infield-dirt {
        position: absolute;
        left: 23%;
        top: 36%;
        width: 54%;
        height: 55%;
        background: #c99d68;
        clip-path: polygon(50% 0%, 97% 48%, 50% 96%, 3% 48%);
        filter: drop-shadow(0 1px 0 rgba(91,65,36,.12));
      }

      .coach-real-infield-grass {
        position: absolute;
        left: 29.2%;
        top: 42.3%;
        width: 41.6%;
        height: 42.2%;
        background:
          repeating-linear-gradient(90deg, rgba(255,255,255,.028) 0 13%, rgba(0,0,0,.02) 13% 26%),
          #4b9258;
        clip-path: polygon(50% 0%, 96% 48%, 50% 96%, 4% 48%);
      }

      .coach-real-home-dirt {
        position: absolute;
        left: 41%;
        bottom: 2.5%;
        width: 18%;
        height: 16%;
        border-radius: 50% 50% 45% 45%;
        background: #c99d68;
      }

      .coach-real-foul-line {
        position: absolute;
        bottom: 9%;
        left: 50%;
        width: 62%;
        height: 1.5px;
        background: rgba(255,255,255,.86);
        transform-origin: 0 50%;
        box-shadow: 0 0 0 .3px rgba(255,255,255,.3);
      }
      .coach-real-foul-line.left { transform: rotate(-43deg); }
      .coach-real-foul-line.right { transform: rotate(-137deg); }

      .coach-real-mound {
        position: absolute;
        left: 50%;
        top: 61%;
        width: 9.5%;
        aspect-ratio: 1;
        transform: translate(-50%,-50%);
        border-radius: 50%;
        background: #c99d68;
        box-shadow: inset 0 0 0 1px rgba(122,85,46,.12);
      }
      .coach-real-mound::after {
        content: '';
        position: absolute;
        left: 28%;
        right: 28%;
        top: 46%;
        height: 2px;
        border-radius: 2px;
        background: rgba(250,248,241,.92);
      }

      .coach-real-base {
        position: absolute;
        width: 9px;
        height: 9px;
        background: #fffdf5;
        border: 1px solid rgba(105,92,68,.25);
        border-radius: 1px;
        transform: translate(-50%,-50%) rotate(45deg);
        box-shadow: 0 1px 1px rgba(0,0,0,.1);
      }
      .coach-real-base.first { left: 73%; top: 66%; }
      .coach-real-base.second { left: 50%; top: 43%; }
      .coach-real-base.third { left: 27%; top: 66%; }

      .coach-real-home-plate {
        position: absolute;
        left: 50%;
        top: 87.5%;
        width: 11px;
        height: 10px;
        transform: translate(-50%,-50%);
        background: #fffdf5;
        clip-path: polygon(12% 0,88% 0,100% 56%,50% 100%,0 56%);
        filter: drop-shadow(0 1px 1px rgba(0,0,0,.12));
      }

      .coach-field.coach-real-field .coach-field-spot {
        z-index: 4;
      }
      .coach-field.coach-real-field .coach-field-spot strong {
        color: rgba(255,255,255,.92) !important;
        text-shadow: 0 1px 2px rgba(0,0,0,.32);
        font-weight: 850;
      }
      .coach-field.coach-real-field .coach-field-spot span {
        background: rgba(255,255,255,.96) !important;
        border-color: rgba(255,255,255,.74) !important;
        box-shadow: 0 2px 5px rgba(18,49,26,.16) !important;
      }

      @media (max-width:575.98px) {
        .coach-field.coach-real-field { border-radius: 14px; }
        .coach-real-infield-dirt { left: 20%; width: 60%; }
        .coach-real-infield-grass { left: 27%; width: 46%; }
      }
    `;
    document.head.appendChild(style);
  }

  function decorateField() {
    const field = document.querySelector('#coach-current-defense .coach-field');
    if (!field || field.classList.contains('coach-real-field')) return;

    field.classList.add('coach-real-field');
    field.insertAdjacentHTML('afterbegin', `
      <div class="coach-real-field-skin" aria-hidden="true">
        <div class="coach-real-warning-track"></div>
        <div class="coach-real-outfield-fence"></div>
        <div class="coach-real-infield-dirt"></div>
        <div class="coach-real-infield-grass"></div>
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

  document.addEventListener('DOMContentLoaded', () => {
    installStyles();
    decorateField();
    document.addEventListener('click', event => {
      if (event.target.closest('[data-coach-defense-view="field"]')) {
        requestAnimationFrame(() => requestAnimationFrame(decorateField));
      }
    });
    setInterval(decorateField, 1000);
  });
})();
