(() => {
  'use strict';

  if (window.location.pathname !== '/') return;
  const role = document.body?.dataset?.coachRole || '';
  if (!['Head Coach', 'Super Admin'].includes(role)) return;

  let setup = null;
  let observer = null;
  let renderQueued = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function installStyles() {
    if (document.getElementById('cb-getting-started-home-styles')) return;
    const style = document.createElement('style');
    style.id = 'cb-getting-started-home-styles';
    style.textContent = `
      .cb-home-setup-card{position:relative;margin:0 0 22px;padding:20px;border:1px solid color-mix(in srgb,var(--primary-color,#1d4ed8) 18%,#dfe5ec);border-radius:18px;background:linear-gradient(135deg,color-mix(in srgb,var(--primary-color,#1d4ed8) 5%,#fff),#fff 62%);box-shadow:0 2px 9px rgba(16,24,40,.05)}
      .cb-home-setup-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
      .cb-home-setup-card .cb-home-eyebrow{display:block;margin-bottom:4px}
      .cb-home-setup-card h3{margin:0;color:#172033;font-size:1.25rem;font-weight:840;letter-spacing:-.02em}
      .cb-home-setup-progress-copy{color:#667085;font-size:.82rem;font-weight:750;white-space:nowrap}
      .cb-home-setup-progress{height:7px;margin:13px 0 15px;border-radius:999px;background:#e9eef4;overflow:hidden}
      .cb-home-setup-progress>span{display:block;height:100%;border-radius:inherit;background:var(--primary-color,#1d4ed8)}
      .cb-home-setup-next{display:flex;align-items:flex-start;gap:10px;padding:12px 13px;border:1px solid #e4e9ef;border-radius:13px;background:rgba(255,255,255,.84)}
      .cb-home-setup-next i{color:var(--primary-color,#1d4ed8);font-size:1.05rem;margin-top:1px}
      .cb-home-setup-next strong{display:block;color:#172033;font-size:.9rem}
      .cb-home-setup-next small{display:block;color:#667085;font-size:.78rem;line-height:1.35;margin-top:2px}
      .cb-home-setup-actions{display:flex;align-items:center;gap:9px;margin-top:14px}
      .cb-home-setup-actions form{margin:0}
      .cb-home-setup-actions .btn{min-height:40px}
      @media(max-width:575.98px){
        .cb-home-setup-card{padding:16px;margin-bottom:18px;border-radius:15px}
        .cb-home-setup-head{display:block}
        .cb-home-setup-progress-copy{display:block;margin-top:5px}
        .cb-home-setup-actions{align-items:stretch;flex-direction:column}
        .cb-home-setup-actions .btn,.cb-home-setup-actions form,.cb-home-setup-actions form .btn{width:100%}
      }
    `;
    document.head.appendChild(style);
  }

  function addGettingStartedLinks() {
    const mobileMore = document.querySelector('#more .cb-mobile-more-card');
    if (mobileMore && !mobileMore.querySelector('[data-cb-getting-started-link]')) {
      const link = document.createElement('a');
      link.className = 'cb-mobile-more-link';
      link.href = '/getting-started';
      link.dataset.cbGettingStartedLink = 'true';
      link.innerHTML = '<span class="cb-mobile-more-icon"><i class="bi bi-compass"></i></span><span class="cb-mobile-more-copy"><strong>Getting Started</strong><small>Team and season setup checklist.</small></span><span class="cb-mobile-more-arrow"><i class="bi bi-chevron-right"></i></span>';
      mobileMore.appendChild(link);
    }

    const desktopMenu = document.querySelector('.coach-primary-nav .dropdown-menu');
    if (desktopMenu && !desktopMenu.querySelector('[data-cb-getting-started-link]')) {
      const divider = document.createElement('li');
      divider.innerHTML = '<hr class="dropdown-divider">';
      const item = document.createElement('li');
      item.innerHTML = '<a class="dropdown-item" data-cb-getting-started-link="true" href="/getting-started"><i class="bi bi-compass me-2"></i>Getting Started</a>';
      desktopMenu.append(divider, item);
    }
  }

  function nextIncomplete() {
    return (setup?.steps || []).find(step => step.required !== false && !step.complete) || null;
  }

  function renderCard() {
    renderQueued = false;
    document.querySelectorAll('.cb-home-setup-card').forEach(node => node.remove());
    if (!setup?.show_home) return;

    const dashboard = document.querySelector('.cb-home-dashboard');
    if (!dashboard) return;
    const next = nextIncomplete();
    const card = document.createElement('section');
    card.className = 'cb-home-setup-card';
    card.innerHTML = `
      <div class="cb-home-setup-head">
        <div>
          <span class="cb-home-eyebrow">${setup.setup_type === 'season_rollover' ? 'New season' : 'Getting started'}</span>
          <h3>${esc(setup.title || 'Team Setup')}</h3>
        </div>
        <span class="cb-home-setup-progress-copy">${Number(setup.completed || 0)} of ${Number(setup.total || 0)} complete</span>
      </div>
      <div class="cb-home-setup-progress" aria-hidden="true"><span style="width:${Math.max(0, Math.min(100, Number(setup.percent || 0)))}%"></span></div>
      ${next ? `<div class="cb-home-setup-next"><i class="bi bi-arrow-right-circle"></i><span><strong>Next: ${esc(next.title)}</strong><small>${esc(next.detail)}</small></span></div>` : ''}
      <div class="cb-home-setup-actions">
        <a class="btn btn-primary" href="/getting-started">Continue Setup</a>
        <form method="post" action="/getting-started/dismiss"><button class="btn btn-outline-secondary" type="submit">Skip for now</button></form>
      </div>`;

    const live = dashboard.querySelector(':scope > .cb-home-live');
    const welcome = dashboard.querySelector(':scope > .cb-home-welcome');
    const anchor = live || welcome;
    if (anchor) anchor.insertAdjacentElement('afterend', card);
    else dashboard.prepend(card);
  }

  function queueRender() {
    if (renderQueued) return;
    renderQueued = true;
    requestAnimationFrame(renderCard);
  }

  async function loadSetup() {
    try {
      const response = await fetch('/api/getting-started', {cache: 'no-store'});
      if (!response.ok) return;
      setup = await response.json();
      queueRender();
    } catch (_) {}
  }

  function observeHome() {
    const container = document.getElementById('overview-content-container');
    if (!container || observer) return;
    observer = new MutationObserver(() => {
      addGettingStartedLinks();
      if (setup?.show_home && !container.querySelector('.cb-home-setup-card')) queueRender();
    });
    observer.observe(container, {childList: true, subtree: true});
  }

  function start() {
    installStyles();
    addGettingStartedLinks();
    observeHome();
    loadSetup();
    window.setTimeout(addGettingStartedLinks, 300);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
