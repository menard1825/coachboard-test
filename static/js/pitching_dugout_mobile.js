(() => {
  'use strict';

  if (window.location.pathname !== '/pitching') return;
  if (window.CoachBoardPitchingDugoutMobile?.initialized) return;

  const MOBILE_QUERY = '(max-width: 767.98px)';
  const mobileMedia = window.matchMedia(MOBILE_QUERY);
  const originalText = new WeakMap();
  let controlsBound = false;
  let attributeObserver = null;

  function isMobile() {
    return mobileMedia.matches;
  }

  function rememberText(el) {
    if (el && !originalText.has(el)) originalText.set(el, el.textContent);
  }

  function restoreText(el) {
    if (el && originalText.has(el)) el.textContent = originalText.get(el);
  }

  function cardGroup(card) {
    if (card.dataset.availabilityGroup) return card.dataset.availabilityGroup;
    const status = (card.querySelector('.cb-pitch-status')?.textContent || '').trim().toLowerCase();
    if (status.includes('eligible') || status.includes('ready')) return 'eligible';
    if (status.includes('verify') || status.includes('check') || status.includes('rules needed')) return 'review';
    return 'unavailable';
  }

  function setCardGroup(card) {
    const group = cardGroup(card);
    card.dataset.availabilityGroup = group;
    return group;
  }

  function setExpanded(card, expanded, options = {}) {
    if (!card) return;
    card.dataset.mobileExpanded = expanded ? 'true' : 'false';
    card.querySelectorAll('.cb-pitcher-details-toggle').forEach(button => {
      button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      const label = button.querySelector('.cb-pitcher-details-label');
      if (label) label.textContent = expanded ? 'Hide details' : 'More details';
      const icon = button.querySelector('i');
      if (icon) icon.className = expanded ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
    });
    card.querySelectorAll('.cb-pitcher-collapse-bottom').forEach(button => {
      button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    });

    if (!expanded && options.keepVisible !== false && isMobile()) {
      window.requestAnimationFrame(() => {
        const rect = card.getBoundingClientRect();
        if (rect.top < 72 || rect.top > window.innerHeight - 80) {
          card.scrollIntoView({behavior: options.smooth === false ? 'auto' : 'smooth', block: 'start'});
        }
      });
    }
  }

  function freshTopToggle(card) {
    const current = card.querySelector('.cb-pitcher-details-toggle');
    const button = current ? current.cloneNode(true) : document.createElement('button');
    button.type = 'button';
    button.className = 'cb-pitcher-details-toggle';
    button.removeAttribute('style');
    button.innerHTML = '<span class="cb-pitcher-details-label">More details</span><i class="bi bi-chevron-down" aria-hidden="true"></i>';
    button.setAttribute('aria-expanded', card.dataset.mobileExpanded === 'true' ? 'true' : 'false');
    button.setAttribute('aria-label', `Toggle details for ${card.dataset.playerName || 'pitcher'}`);

    if (current) current.replaceWith(button);
    else {
      const arm = card.querySelector('.pitch-arm-care-slot');
      if (arm) arm.insertAdjacentElement('afterend', button);
      else card.querySelector('.cb-pitcher-top')?.insertAdjacentElement('afterend', button);
    }
    return button;
  }

  function ensureBottomCollapse(card) {
    if (card.querySelector('.cb-pitcher-collapse-bottom')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'cb-pitcher-collapse-bottom';
    button.setAttribute('aria-expanded', 'false');
    button.innerHTML = '<span>Collapse details</span><i class="bi bi-chevron-up" aria-hidden="true"></i>';
    const target = card.querySelector('.cb-pitch-target');
    if (target) target.insertAdjacentElement('afterend', button);
    else card.appendChild(button);
  }

  function ensureQuickUsage(card) {
    if (card.querySelector('.cb-pitch-quick-usage')) return;
    const official = card.querySelector('.cb-pitch-metric:first-child .fw-bold');
    const text = official?.textContent?.trim();
    if (!text || text === '—') return;
    const quick = document.createElement('div');
    quick.className = 'cb-pitch-quick-usage';
    quick.innerHTML = `<span>Today</span><strong>${text}</strong>`;
    const arm = card.querySelector('.pitch-arm-care-slot');
    if (arm) arm.insertAdjacentElement('afterend', quick);
    else card.querySelector('.cb-pitcher-top')?.insertAdjacentElement('afterend', quick);
  }

  function simplifyArmCare(root = document) {
    root.querySelectorAll('.pitch-arm-care-slot').forEach(slot => {
      const title = slot.querySelector('.cb-pitch-arm-title');
      const value = slot.querySelector('.cb-pitch-arm-value');
      if (title) title.textContent = 'Arm care';
      if (value && /^No Rest Required$/i.test(value.textContent.trim())) value.textContent = 'OK';
    });
  }

  function compactStatus(card, mobile) {
    const badge = card.querySelector('.cb-pitch-status');
    if (!badge) return;
    rememberText(badge);
    if (!mobile) {
      restoreText(badge);
      return;
    }
    const group = setCardGroup(card);
    badge.textContent = group === 'eligible' ? 'READY' : group === 'unavailable' ? 'OUT' : 'CHECK';
  }

  function preparePitcherCards() {
    document.querySelectorAll('.cb-pitcher-card').forEach(card => {
      setCardGroup(card);
      ensureQuickUsage(card);
      freshTopToggle(card);
      ensureBottomCollapse(card);
      if (isMobile() && card.dataset.mobileExpanded !== 'true') setExpanded(card, false, {keepVisible: false});
      compactStatus(card, isMobile());
    });
    simplifyArmCare();
  }

  function reorderDecisionBoard() {
    const grid = document.querySelector('.cb-pitch-card-grid');
    if (!grid) return;
    const cards = [...grid.querySelectorAll(':scope > .cb-pitcher-card')];
    const rank = {unavailable: 0, review: 1, eligible: 2};
    cards.sort((a, b) => {
      const groupDelta = (rank[cardGroup(a)] ?? 9) - (rank[cardGroup(b)] ?? 9);
      if (groupDelta) return groupDelta;
      return (a.dataset.playerName || '').localeCompare(b.dataset.playerName || '');
    });
    cards.forEach(card => grid.appendChild(card));

    const summary = document.querySelector('.cb-pitch-summary');
    if (!summary) return;
    const summaryItems = [...summary.querySelectorAll(':scope > .cb-pitch-summary-item')];
    const itemRank = {unavailable: 0, review: 1, eligible: 2};
    summaryItems.sort((a, b) => (itemRank[a.dataset.cbPitchFilter] ?? 9) - (itemRank[b.dataset.cbPitchFilter] ?? 9));
    summaryItems.forEach(item => summary.appendChild(item));
  }

  function compactSummaryLabels(mobile) {
    document.querySelectorAll('.cb-pitch-summary-item').forEach(item => {
      const label = item.querySelector('span');
      if (!label) return;
      rememberText(label);
      if (!mobile) {
        restoreText(label);
        return;
      }
      const group = item.dataset.cbPitchFilter || (() => {
        const text = label.textContent.toLowerCase();
        if (text.includes('eligible')) return 'eligible';
        if (text.includes('unavailable')) return 'unavailable';
        return 'review';
      })();
      label.textContent = group === 'eligible' ? 'READY' : group === 'unavailable' ? 'OUT' : 'CHECK';
    });
  }

  function compactPageChrome(mobile) {
    const head = document.querySelector('.cb-pitch-page-head');
    const subtitle = head?.querySelector('p');
    const availabilityHeading = document.querySelector('#pitcherAvailabilityCard > .card-header h5');
    const rulesButton = [...document.querySelectorAll('.cb-pitch-page-actions .btn')]
      .find(button => /View Rules/i.test(originalText.get(button) || button.textContent));
    const settingsButton = [...document.querySelectorAll('.cb-pitch-page-actions .btn')]
      .find(button => /Pitching Settings/i.test(originalText.get(button) || button.textContent));

    [subtitle, availabilityHeading, rulesButton, settingsButton].forEach(rememberText);
    if (mobile) {
      if (subtitle) subtitle.textContent = 'Fast game-day pitching decisions.';
      if (availabilityHeading) availabilityHeading.textContent = 'Who can pitch today?';
      if (rulesButton) rulesButton.textContent = 'Rules';
      if (settingsButton) settingsButton.textContent = 'Settings';
    } else {
      [subtitle, availabilityHeading, rulesButton, settingsButton].forEach(restoreText);
    }
  }

  function syncControlsFromAttributes() {
    document.querySelectorAll('.cb-pitcher-card').forEach(card => {
      const expanded = card.dataset.mobileExpanded === 'true';
      card.querySelectorAll('.cb-pitcher-details-toggle').forEach(button => {
        button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        const label = button.querySelector('.cb-pitcher-details-label');
        if (label) label.textContent = expanded ? 'Hide details' : 'More details';
        const icon = button.querySelector('i');
        if (icon) icon.className = expanded ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
      });
    });
  }

  function bindStableControls() {
    if (controlsBound) return;
    controlsBound = true;
    document.addEventListener('click', event => {
      const button = event.target.closest('.cb-pitcher-details-toggle, .cb-pitcher-collapse-bottom');
      if (!button) return;
      const card = button.closest('.cb-pitcher-card');
      if (!card) return;
      event.preventDefault();
      event.stopPropagation();
      if (typeof event.stopImmediatePropagation === 'function') event.stopImmediatePropagation();
      const expanded = card.dataset.mobileExpanded === 'true';
      setExpanded(card, !expanded);
    }, true);
  }

  function watchExpansionState() {
    if (attributeObserver) attributeObserver.disconnect();
    const grid = document.querySelector('.cb-pitch-card-grid');
    if (!grid) return;
    attributeObserver = new MutationObserver(mutations => {
      if (mutations.some(mutation => mutation.type === 'attributes' && mutation.attributeName === 'data-mobile-expanded')) {
        syncControlsFromAttributes();
      }
    });
    attributeObserver.observe(grid, {
      subtree: true,
      attributes: true,
      attributeFilter: ['data-mobile-expanded'],
    });
  }

  function applyResponsiveMode() {
    const mobile = isMobile();
    document.body.classList.toggle('cb-pitch-dugout-mobile', mobile);
    const root = document.querySelector('.cb-pitching-v3');
    root?.classList.toggle('cb-pitch-dugout-mobile-root', mobile);

    compactPageChrome(mobile);
    compactSummaryLabels(mobile);
    document.querySelectorAll('.cb-pitcher-card').forEach(card => compactStatus(card, mobile));
    if (mobile) {
      reorderDecisionBoard();
      document.querySelectorAll('.cb-pitcher-card').forEach(card => {
        if (!card.dataset.mobileExpanded) setExpanded(card, false, {keepVisible: false});
      });
    }
  }

  function installStyles() {
    if (document.getElementById('cb-pitch-dugout-mobile-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-pitch-dugout-mobile-styles';
    style.textContent = `
      @media (max-width: 767.98px) {
        body.cb-pitch-dugout-mobile .cb-pitching-v3 { padding-left: 10px !important; padding-right: 10px !important; }
        body.cb-pitch-dugout-mobile .cb-pitch-page-head { gap: 6px; margin-bottom: 8px; }
        body.cb-pitch-dugout-mobile .cb-pitch-page-head .cb-kicker { display:none; }
        body.cb-pitch-dugout-mobile .cb-pitch-page-head h3 { margin:0; font-size:1.5rem; line-height:1.05; }
        body.cb-pitch-dugout-mobile .cb-pitch-page-head p { margin-top:3px; font-size:.72rem; line-height:1.25; }
        body.cb-pitch-dugout-mobile .cb-pitch-page-actions { gap:6px; }
        body.cb-pitch-dugout-mobile .cb-pitch-page-actions .btn { flex:0 0 auto; min-height:36px; padding:6px 13px; font-size:.76rem; border-radius:9px; }

        body.cb-pitch-dugout-mobile .cb-pitch-rule-strip { margin-bottom:8px; border-radius:10px; }
        body.cb-pitch-dugout-mobile .cb-pitch-rule-item { padding:7px 8px; }
        body.cb-pitch-dugout-mobile .cb-pitch-rule-icon { width:26px; height:26px; }
        body.cb-pitch-dugout-mobile .cb-pitch-rule-item strong { font-size:.66rem; }

        body.cb-pitch-dugout-mobile #pitcherAvailabilityCard { margin-bottom:10px !important; border-radius:12px !important; }
        body.cb-pitch-dugout-mobile #pitcherAvailabilityCard > .card-header { padding:10px 11px 8px; }
        body.cb-pitch-dugout-mobile #pitcherAvailabilityCard > .card-header h5 { font-size:1.02rem; }
        body.cb-pitch-dugout-mobile #pitcherAvailabilityCard > .card-header .small,
        body.cb-pitch-dugout-mobile #pitcherAvailabilityCard > .card-header > .badge { display:none !important; }

        body.cb-pitch-dugout-mobile .cb-pitch-summary { gap:6px; padding:8px; }
        body.cb-pitch-dugout-mobile .cb-pitch-summary-item { min-height:63px; padding:8px 9px; border-width:2px; border-radius:10px; }
        body.cb-pitch-dugout-mobile .cb-pitch-summary-item span { font-size:.62rem; letter-spacing:.06em; }
        body.cb-pitch-dugout-mobile .cb-pitch-summary-item strong { margin-top:2px; font-size:1.35rem; line-height:1; }
        body.cb-pitch-dugout-mobile .cb-pitch-summary-item[data-cb-pitch-filter="unavailable"] { border-color:#efb8b8; background:#fff5f5; }
        body.cb-pitch-dugout-mobile .cb-pitch-summary-item[data-cb-pitch-filter="review"] { border-color:#efd39d; background:#fffaf0; }
        body.cb-pitch-dugout-mobile .cb-pitch-summary-item[data-cb-pitch-filter="eligible"] { border-color:#b9dec4; background:#f3fbf5; }
        body.cb-pitch-dugout-mobile .cb-pitch-filter-state { padding:7px 9px; border-top:1px solid #e7ebf0; font-size:.72rem; }
        body.cb-pitch-dugout-mobile .cb-pitch-filter-state button { min-height:38px; font-size:.72rem; }

        body.cb-pitch-dugout-mobile .cb-pitch-card-grid { gap:7px; padding:8px; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card { border-radius:11px; box-shadow:none; border-left-width:5px; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-availability-group="eligible"] { border-left-color:#3a9b5f; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-availability-group="unavailable"] { border-left-color:#d64545; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-availability-group="review"] { border-left-color:#d99a24; }
        body.cb-pitch-dugout-mobile .cb-pitcher-top { padding:11px 11px 7px; }
        body.cb-pitch-dugout-mobile .cb-pitcher-name { font-size:1.08rem; line-height:1.1; }
        body.cb-pitch-dugout-mobile .cb-pitcher-last { margin-top:4px; font-size:.69rem; line-height:1.2; }
        body.cb-pitch-dugout-mobile .cb-pitch-status { padding:5px 8px; font-size:.66rem; letter-spacing:.04em; }

        body.cb-pitch-dugout-mobile .cb-pitch-decision { margin:0 11px 6px; padding:0; border:0; border-radius:0; background:transparent !important; }
        body.cb-pitch-dugout-mobile .cb-pitch-decision .cb-pitch-kicker { font-size:.55rem; letter-spacing:.08em; }
        body.cb-pitch-dugout-mobile .cb-pitch-decision strong { margin-top:2px; font-size:.94rem; line-height:1.2; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-availability-group="unavailable"] .cb-pitch-decision strong { color:#a62f2f; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-availability-group="review"] .cb-pitch-decision strong { color:#8a5a13; }
        body.cb-pitch-dugout-mobile .cb-pitch-detail { font-size:.7rem; line-height:1.3; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-availability-group="eligible"][data-mobile-expanded="false"] .cb-pitch-decision { display:none !important; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-availability-group="review"][data-mobile-expanded="false"] .cb-pitch-decision,
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-availability-group="unavailable"][data-mobile-expanded="false"] .cb-pitch-decision { display:block !important; }

        body.cb-pitch-dugout-mobile .pitch-arm-care-slot { margin:0 11px 4px; padding:5px 0; border:0; border-top:1px solid #eef1f4; border-radius:0; background:transparent; }
        body.cb-pitch-dugout-mobile .cb-pitch-arm-title { font-size:.56rem; }
        body.cb-pitch-dugout-mobile .cb-pitch-arm-value { font-size:.72rem; }
        body.cb-pitch-dugout-mobile .cb-pitch-arm-next { margin-top:2px; font-size:.68rem; text-align:left; }
        body.cb-pitch-dugout-mobile .cb-pitch-arm-detail { font-size:.67rem; }

        body.cb-pitch-dugout-mobile .cb-pitch-quick-usage { display:flex; align-items:center; justify-content:space-between; gap:10px; margin:0 11px 5px; padding:5px 0; border-top:1px solid #eef1f4; color:#667085; }
        body.cb-pitch-dugout-mobile .cb-pitch-quick-usage span { font-size:.56rem; font-weight:850; letter-spacing:.08em; text-transform:uppercase; }
        body.cb-pitch-dugout-mobile .cb-pitch-quick-usage strong { color:#344054; font-size:.76rem; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-mobile-expanded="true"] .cb-pitch-quick-usage { display:none; }

        body.cb-pitch-dugout-mobile .cb-pitcher-details-toggle { display:flex; width:100%; min-height:44px; margin:0; padding:9px 11px; border:0; border-top:1px solid #e8ecf0; border-radius:0; background:#fbfcfd; color:var(--primary-color,#344054); font-size:.73rem; font-weight:850; }
        body.cb-pitch-dugout-mobile .cb-pitcher-details-toggle i { color:inherit; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-mobile-expanded="true"] .cb-pitcher-details-toggle { background:#f6f8fa; }

        body.cb-pitch-dugout-mobile .cb-pitch-metrics { grid-template-columns:1fr 1fr; }
        body.cb-pitch-dugout-mobile .cb-pitch-metric { padding:10px 11px; }
        body.cb-pitch-dugout-mobile .cb-pitch-metric + .cb-pitch-metric { border-top:0; border-left:1px solid #edf0f3; }
        body.cb-pitch-dugout-mobile .cb-pitch-metric .cb-pitch-kicker { font-size:.57rem; }
        body.cb-pitch-dugout-mobile .cb-pitch-metric .fw-bold { font-size:.82rem; line-height:1.2; }
        body.cb-pitch-dugout-mobile .cb-pitch-metric .small { font-size:.67rem; line-height:1.3; }
        body.cb-pitch-dugout-mobile .cb-pitch-target { padding:10px 11px; }
        body.cb-pitch-dugout-mobile .cb-pitch-target-copy .fw-bold { font-size:.78rem; }
        body.cb-pitch-dugout-mobile .cb-pitch-target-copy .small { font-size:.67rem; }

        body.cb-pitch-dugout-mobile .cb-pitcher-collapse-bottom { display:none; align-items:center; justify-content:center; gap:7px; width:100%; min-height:46px; padding:9px 12px; border:0; border-top:1px solid #e4e8ed; background:#f6f8fa; color:var(--primary-color,#344054); font-size:.76rem; font-weight:850; }
        body.cb-pitch-dugout-mobile .cb-pitcher-card[data-mobile-expanded="true"] .cb-pitcher-collapse-bottom { display:flex; }

        body.cb-pitch-dugout-mobile .cb-pitch-section-card > .card-header .small { font-size:.66rem; }
        body.cb-pitch-dugout-mobile .cb-pitch-work-row { gap:8px !important; margin-bottom:8px !important; }
        body.cb-pitch-dugout-mobile #pitchTargetsCard > .card-header,
        body.cb-pitch-dugout-mobile .cb-pitch-record-card > .card-header,
        body.cb-pitch-dugout-mobile #pitchHistoryCard > .card-header { min-height:52px; padding:9px 11px; }
        body.cb-pitch-dugout-mobile #pitchTargetsCard > .card-header .small,
        body.cb-pitch-dugout-mobile .cb-pitch-record-card > .card-header .small,
        body.cb-pitch-dugout-mobile #pitchHistoryCard > .card-header .small { display:none; }
      }

      @media (max-width: 390px) {
        body.cb-pitch-dugout-mobile .cb-pitch-summary-item { padding-left:7px; padding-right:7px; }
        body.cb-pitch-dugout-mobile .cb-pitch-summary-item span { font-size:.58rem; }
        body.cb-pitch-dugout-mobile .cb-pitch-summary-item strong { font-size:1.25rem; }
        body.cb-pitch-dugout-mobile .cb-pitch-metrics { grid-template-columns:1fr 1fr; }
      }
    `;
    document.head.appendChild(style);
  }

  function init() {
    installStyles();
    preparePitcherCards();
    reorderDecisionBoard();
    bindStableControls();
    watchExpansionState();
    applyResponsiveMode();

    document.addEventListener('coachboard:pitching-preferences-ready', () => {
      simplifyArmCare();
      preparePitcherCards();
      reorderDecisionBoard();
      applyResponsiveMode();
    });

    const onMediaChange = () => applyResponsiveMode();
    if (typeof mobileMedia.addEventListener === 'function') mobileMedia.addEventListener('change', onMediaChange);
    else if (typeof mobileMedia.addListener === 'function') mobileMedia.addListener(onMediaChange);

    window.CoachBoardPitchingDugoutMobile = {
      initialized: true,
      setExpanded,
      applyResponsiveMode,
      reorderDecisionBoard,
    };
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true});
  else init();
})();
