(() => {
  'use strict';

  if (window.location.pathname !== '/pitching') return;
  if (window.CoachBoardPitchingScanCompact?.initialized) return;

  const mobile = window.matchMedia('(max-width: 767.98px)');
  const tabletWidth = window.matchMedia('(min-width: 768px) and (max-width: 1366px)');
  const noHover = window.matchMedia('(hover: none)');
  let readyExpanded = false;
  let observer = null;
  let lastRollupSignature = '';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function isTabletTouch() {
    if (!tabletWidth.matches || mobile.matches) return false;
    return Number(navigator.maxTouchPoints || 0) > 0 || noHover.matches;
  }

  function isCompactMode() {
    return mobile.matches || isTabletTouch();
  }

  function syncModeClasses() {
    const tablet = isTabletTouch();
    document.body.classList.toggle('cb-pitch-dugout-tablet', tablet);
    if (!isCompactMode()) return;
    document.querySelectorAll('.cb-pitcher-card').forEach(card => {
      if (!card.dataset.mobileExpanded) card.dataset.mobileExpanded = 'false';
    });
  }

  function installStyles() {
    if (document.getElementById('cb-pitch-scan-compact-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-pitch-scan-compact-styles';
    style.textContent = `
      @media(max-width:767.98px){
        body.cb-pitch-dugout-mobile #pitcherAvailabilityCard .cb-pitch-card-grid{padding-top:0}
        body.cb-pitch-dugout-mobile .cb-ready-rollup{margin:0 8px 8px;border:1px solid #b9dec4;border-radius:11px;background:#f3fbf5;overflow:hidden}
        body.cb-pitch-dugout-mobile .cb-ready-rollup-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 11px 8px}
        body.cb-pitch-dugout-mobile .cb-ready-rollup-head strong{display:block;color:#176b38;font-size:.84rem}
        body.cb-pitch-dugout-mobile .cb-ready-rollup-head small{display:block;color:#667085;font-size:.62rem;margin-top:1px}
        body.cb-pitch-dugout-mobile .cb-ready-rollup-toggle{border:1px solid #a7cfb4;background:#fff;color:#176b38;border-radius:8px;min-height:34px;padding:5px 9px;font-size:.67rem;font-weight:850;white-space:nowrap}
        body.cb-pitch-dugout-mobile .cb-ready-rollup-names{display:grid;grid-template-columns:1fr 1fr;gap:5px;padding:0 9px 9px}
        body.cb-pitch-dugout-mobile .cb-ready-rollup-name{display:flex;align-items:center;justify-content:space-between;gap:6px;min-width:0;border:1px solid #d6eadc;border-radius:8px;background:#fff;padding:6px 7px}
        body.cb-pitch-dugout-mobile .cb-ready-rollup-name span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#253047;font-size:.68rem;font-weight:780}
        body.cb-pitch-dugout-mobile .cb-ready-rollup-name small{flex:0 0 auto;color:#667085;font-size:.58rem;font-weight:700}
        body.cb-pitch-dugout-mobile .cb-pitcher-card.cb-ready-rollup-hidden{display:none!important}
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-availability-group="review"],
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-availability-group="unavailable"]{box-shadow:0 1px 4px rgba(16,24,40,.06)}
        body.cb-pitch-dugout-mobile #pitcherAvailabilityCard>.card-header{padding-bottom:6px}
        body.cb-pitch-dugout-mobile #pitcherAvailabilityCard>.card-header h5{margin-bottom:0}
      }
      @media(max-width:360px){
        body.cb-pitch-dugout-mobile .cb-ready-rollup-names{grid-template-columns:1fr}
      }

      @media(min-width:768px) and (max-width:1366px){
        body.cb-pitch-dugout-tablet .cb-pitching-v3{max-width:1120px;margin:0 auto;padding-left:14px!important;padding-right:14px!important}
        body.cb-pitch-dugout-tablet .cb-pitch-page-head{margin-bottom:10px;align-items:center}
        body.cb-pitch-dugout-tablet .cb-pitch-page-head h3{font-size:1.45rem}
        body.cb-pitch-dugout-tablet .cb-pitch-page-head p{font-size:.74rem}
        body.cb-pitch-dugout-tablet .cb-pitch-rule-strip{margin-bottom:10px}
        body.cb-pitch-dugout-tablet .cb-pitch-rule-item{padding:9px 11px}
        body.cb-pitch-dugout-tablet .cb-pitch-rule-item small{display:none}
        body.cb-pitch-dugout-tablet #pitcherAvailabilityCard{border-radius:13px!important}
        body.cb-pitch-dugout-tablet #pitcherAvailabilityCard>.card-header{padding:10px 13px}
        body.cb-pitch-dugout-tablet #pitcherAvailabilityCard>.card-header .small{display:none}
        body.cb-pitch-dugout-tablet .cb-pitch-summary{gap:8px;padding:10px 12px 8px}
        body.cb-pitch-dugout-tablet .cb-pitch-summary-item{min-height:58px;padding:8px 10px;border-width:2px}
        body.cb-pitch-dugout-tablet .cb-pitch-summary-item[data-cb-pitch-filter="unavailable"]{border-color:#efb8b8;background:#fff5f5}
        body.cb-pitch-dugout-tablet .cb-pitch-summary-item[data-cb-pitch-filter="review"]{border-color:#efd39d;background:#fffaf0}
        body.cb-pitch-dugout-tablet .cb-pitch-summary-item[data-cb-pitch-filter="eligible"]{border-color:#b9dec4;background:#f3fbf5}

        body.cb-pitch-dugout-tablet .cb-ready-rollup{margin:0 12px 10px;border:1px solid #b9dec4;border-radius:11px;background:#f3fbf5;overflow:hidden}
        body.cb-pitch-dugout-tablet .cb-ready-rollup-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 11px 7px}
        body.cb-pitch-dugout-tablet .cb-ready-rollup-head strong{display:block;color:#176b38;font-size:.8rem}
        body.cb-pitch-dugout-tablet .cb-ready-rollup-head small{display:block;color:#667085;font-size:.61rem;margin-top:1px}
        body.cb-pitch-dugout-tablet .cb-ready-rollup-toggle{border:1px solid #a7cfb4;background:#fff;color:#176b38;border-radius:8px;min-height:34px;padding:5px 10px;font-size:.67rem;font-weight:850;white-space:nowrap}
        body.cb-pitch-dugout-tablet .cb-ready-rollup-names{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;padding:0 9px 9px}
        body.cb-pitch-dugout-tablet .cb-ready-rollup-name{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0;border:1px solid #d6eadc;border-radius:8px;background:#fff;padding:6px 8px}
        body.cb-pitch-dugout-tablet .cb-ready-rollup-name span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#253047;font-size:.67rem;font-weight:780}
        body.cb-pitch-dugout-tablet .cb-ready-rollup-name small{flex:0 0 auto;color:#667085;font-size:.57rem;font-weight:700}

        body.cb-pitch-dugout-tablet .cb-pitch-card-grid{grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;gap:10px;padding:0 12px 12px}
        body.cb-pitch-dugout-tablet .cb-pitcher-card{border-left-width:5px;border-radius:11px;box-shadow:0 1px 4px rgba(16,24,40,.05)}
        body.cb-pitch-dugout-tablet .cb-pitcher-card[data-availability-group="eligible"]{border-left-color:#3a9b5f}
        body.cb-pitch-dugout-tablet .cb-pitcher-card[data-availability-group="review"]{border-left-color:#d99a24}
        body.cb-pitch-dugout-tablet .cb-pitcher-card[data-availability-group="unavailable"]{border-left-color:#d64545}
        body.cb-pitch-dugout-tablet .cb-pitcher-card.cb-ready-rollup-hidden{display:none!important}
        body.cb-pitch-dugout-tablet .cb-pitcher-top{padding:10px 11px 7px}
        body.cb-pitch-dugout-tablet .cb-pitcher-name{font-size:1rem}
        body.cb-pitch-dugout-tablet .cb-pitcher-last{font-size:.62rem}
        body.cb-pitch-dugout-tablet .cb-pitch-decision{margin:0 10px 7px;padding:7px 8px}
        body.cb-pitch-dugout-tablet .pitch-arm-care-slot{margin:0 10px 4px;padding:6px 8px}
        body.cb-pitch-dugout-tablet .cb-pitcher-card[data-mobile-expanded="false"] .cb-pitch-arm-detail{display:none}
        body.cb-pitch-dugout-tablet .cb-pitcher-card[data-mobile-expanded="false"] .cb-pitch-metrics,
        body.cb-pitch-dugout-tablet .cb-pitcher-card[data-mobile-expanded="false"] .cb-pitch-target{display:none!important}
        body.cb-pitch-dugout-tablet .cb-pitcher-card[data-availability-group="eligible"][data-mobile-expanded="false"] .cb-pitch-decision{display:none!important}

        body.cb-pitch-dugout-tablet .cb-pitch-quick-usage{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 10px 5px;padding:6px 0;border-top:1px solid #eef1f4;color:#667085}
        body.cb-pitch-dugout-tablet .cb-pitch-quick-usage span{font-size:.56rem;font-weight:850;letter-spacing:.08em;text-transform:uppercase}
        body.cb-pitch-dugout-tablet .cb-pitch-quick-usage strong{color:#344054;font-size:.75rem}
        body.cb-pitch-dugout-tablet .cb-pitcher-card[data-mobile-expanded="true"] .cb-pitch-quick-usage{display:none}

        body.cb-pitch-dugout-tablet .cb-pitcher-details-toggle{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;min-height:42px;margin:0;padding:8px 10px;border:0;border-top:1px solid #e8ecf0;border-radius:0;background:#fbfcfd;color:var(--primary-color,#344054);font-size:.69rem;font-weight:850;text-align:left}
        body.cb-pitch-dugout-tablet .cb-pitcher-details-toggle i{color:inherit}
        body.cb-pitch-dugout-tablet .cb-pitcher-collapse-bottom{display:none;align-items:center;justify-content:center;gap:7px;width:100%;min-height:44px;padding:8px 10px;border:0;border-top:1px solid #e4e8ed;background:#f6f8fa;color:var(--primary-color,#344054);font-size:.71rem;font-weight:850}
        body.cb-pitch-dugout-tablet .cb-pitcher-card[data-mobile-expanded="true"] .cb-pitcher-collapse-bottom{display:flex}
        body.cb-pitch-dugout-tablet .cb-pitcher-card[data-mobile-expanded="true"] .cb-pitcher-details-toggle{background:#f6f8fa}
      }
      @media(min-width:768px) and (max-width:940px){
        body.cb-pitch-dugout-tablet .cb-ready-rollup-names{grid-template-columns:repeat(2,minmax(0,1fr))}
      }
    `;
    document.head.appendChild(style);
  }

  function todayUsage(card) {
    const quick = card.querySelector('.cb-pitch-quick-usage strong')?.textContent?.trim();
    if (quick) return quick.replace(/\s+pitches?$/i, '');
    const official = card.querySelector('.cb-pitch-metric:first-child .fw-bold')?.textContent?.trim();
    if (!official) return '';
    return official.replace(/\s+pitches?$/i, '');
  }

  function eligibleCards() {
    return [...document.querySelectorAll('.cb-pitcher-card')]
      .filter(card => card.dataset.availabilityGroup === 'eligible');
  }

  function rollupSignature(cards) {
    return JSON.stringify({
      expanded: readyExpanded,
      compact: isCompactMode(),
      tablet: isTabletTouch(),
      pitchers: cards.map(card => [
        card.dataset.playerName || card.querySelector('.cb-pitcher-name')?.textContent || '',
        todayUsage(card),
      ]),
    });
  }

  function ensureRollup(cards) {
    const grid = document.querySelector('#pitcherAvailabilityCard .cb-pitch-card-grid');
    if (!grid || !cards.length) {
      document.getElementById('cb-ready-pitcher-rollup')?.remove();
      lastRollupSignature = '';
      return null;
    }

    let rollup = document.getElementById('cb-ready-pitcher-rollup');
    if (!rollup) {
      rollup = document.createElement('section');
      rollup.id = 'cb-ready-pitcher-rollup';
      rollup.className = 'cb-ready-rollup';
      grid.insertAdjacentElement('beforebegin', rollup);
      lastRollupSignature = '';
    }

    const signature = rollupSignature(cards);
    if (signature !== lastRollupSignature) {
      lastRollupSignature = signature;
      rollup.innerHTML = `
        <div class="cb-ready-rollup-head">
          <div><strong>Ready to pitch</strong><small>${cards.length} pitcher${cards.length === 1 ? '' : 's'} available today</small></div>
          <button type="button" class="cb-ready-rollup-toggle" aria-expanded="${readyExpanded ? 'true' : 'false'}">${readyExpanded ? 'Hide details' : 'Show details'}</button>
        </div>
        <div class="cb-ready-rollup-names">
          ${cards.map(card => `<div class="cb-ready-rollup-name"><span>${esc(card.dataset.playerName || card.querySelector('.cb-pitcher-name')?.textContent || 'Pitcher')}</span>${todayUsage(card) ? `<small>${esc(todayUsage(card))}</small>` : ''}</div>`).join('')}
        </div>`;

      rollup.querySelector('.cb-ready-rollup-toggle')?.addEventListener('click', () => {
        readyExpanded = !readyExpanded;
        lastRollupSignature = '';
        apply();
        if (readyExpanded) {
          window.requestAnimationFrame(() => cards[0]?.scrollIntoView({behavior:'smooth', block:'nearest'}));
        }
      });
    }
    return rollup;
  }

  function apply() {
    installStyles();
    syncModeClasses();
    const cards = eligibleCards();
    const rollup = ensureRollup(cards);
    if (!isCompactMode()) {
      rollup?.classList.add('d-none');
      cards.forEach(card => card.classList.remove('cb-ready-rollup-hidden'));
      return;
    }

    rollup?.classList.remove('d-none');
    cards.forEach(card => card.classList.toggle('cb-ready-rollup-hidden', !readyExpanded));
  }

  function watch() {
    observer?.disconnect();
    const root = document.getElementById('pitcherAvailabilityCard');
    if (!root) return;
    observer = new MutationObserver(mutations => {
      if (mutations.some(mutation => mutation.type === 'attributes' && mutation.attributeName === 'data-availability-group')) {
        lastRollupSignature = '';
        window.requestAnimationFrame(apply);
      }
    });
    observer.observe(root, {
      subtree:true,
      attributes:true,
      attributeFilter:['data-availability-group'],
    });
  }

  function handleViewportChange() {
    lastRollupSignature = '';
    apply();
  }

  function start(attempt = 0) {
    const cards = document.querySelectorAll('.cb-pitcher-card');
    const classified = [...cards].some(card => card.dataset.availabilityGroup);
    if (!cards.length || !classified) {
      if (attempt < 100) window.setTimeout(() => start(attempt + 1), 30);
      return;
    }
    apply();
    watch();
    mobile.addEventListener?.('change', handleViewportChange);
    tabletWidth.addEventListener?.('change', handleViewportChange);
    noHover.addEventListener?.('change', handleViewportChange);
    window.addEventListener('orientationchange', handleViewportChange);
  }

  window.CoachBoardPitchingScanCompact = {initialized:true, apply};
  start();
})();