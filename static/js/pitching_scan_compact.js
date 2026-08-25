(() => {
  'use strict';

  if (window.location.pathname !== '/pitching') return;
  if (window.CoachBoardPitchingScanCompact?.initialized) return;

  const mobile = window.matchMedia('(max-width: 767.98px)');
  let readyExpanded = false;
  let observer = null;
  let lastRollupSignature = '';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

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
      mobile: mobile.matches,
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
    const cards = eligibleCards();
    const rollup = ensureRollup(cards);
    if (!mobile.matches) {
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

  function start(attempt = 0) {
    const cards = document.querySelectorAll('.cb-pitcher-card');
    const classified = [...cards].some(card => card.dataset.availabilityGroup);
    if (!cards.length || !classified) {
      if (attempt < 100) window.setTimeout(() => start(attempt + 1), 30);
      return;
    }
    apply();
    watch();
    mobile.addEventListener?.('change', () => {
      lastRollupSignature = '';
      apply();
    });
  }

  window.CoachBoardPitchingScanCompact = {initialized:true, apply};
  start();
})();