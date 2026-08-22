(() => {
  'use strict';

  if (window.location.pathname !== '/') return;

  const metrics = document.querySelector('#roster .cb-roster-metrics');
  if (!metrics || metrics.dataset.cbMetricsClarity === '1') return;
  metrics.dataset.cbMetricsClarity = '1';
  metrics.classList.add('cb-roster-metrics-v2');

  const totalEl = document.getElementById('rosterPlayerCount');
  const pitcherEl = document.getElementById('rosterPitcherCount');
  const profileEl = document.getElementById('rosterProfileStatus');
  if (!totalEl || !pitcherEl || !profileEl) return;

  const totalChip = totalEl.closest('span');
  const pitcherChip = pitcherEl.closest('span');
  if (!totalChip || !pitcherChip) return;

  totalChip.classList.add('cb-roster-total');
  pitcherChip.classList.add('cb-roster-submetric');
  profileEl.classList.add('cb-roster-submetric', 'cb-roster-profile-metric');

  function numberFrom(element) {
    const value = Number.parseInt((element?.textContent || '').trim(), 10);
    return Number.isFinite(value) ? value : 0;
  }

  function replaceMetricCopy(container, strong, copy) {
    [...container.childNodes].forEach((node) => {
      if (node !== strong) node.remove();
    });
    const label = document.createElement('span');
    label.className = 'cb-roster-metric-copy';
    label.textContent = copy;
    container.appendChild(label);
  }

  let rendering = false;
  function render() {
    if (rendering) return;
    rendering = true;

    const total = numberFrom(totalEl);
    const pitchers = numberFrom(pitcherEl);
    const profileStrong = profileEl.querySelector('strong');
    const profilesComplete = profileEl.classList.contains('is-complete') || /all/i.test(profileStrong?.textContent || '');
    const incomplete = profilesComplete ? 0 : numberFrom(profileStrong);

    replaceMetricCopy(totalChip, totalEl, total === 1 ? ' total player' : ' total players');
    replaceMetricCopy(
      pitcherChip,
      pitcherEl,
      total === 1 ? ' of 1 is a pitcher' : ` of ${total} are pitchers`,
    );

    if (profilesComplete) {
      if (profileStrong) {
        profileStrong.textContent = 'All';
        replaceMetricCopy(profileEl, profileStrong, ` ${total} profiles complete`);
      }
    } else if (profileStrong) {
      replaceMetricCopy(
        profileEl,
        profileStrong,
        ` of ${total} profile${total === 1 ? '' : 's'} incomplete`,
      );
    }

    totalChip.title = `${total} total player${total === 1 ? '' : 's'} on the roster`;
    pitcherChip.title = `${pitchers} of ${total} player${total === 1 ? '' : 's'} are designated pitchers`;
    profileEl.title = profilesComplete
      ? `All ${total} player profiles are complete`
      : `${incomplete} of ${total} player profiles are incomplete`;

    metrics.setAttribute(
      'aria-label',
      profilesComplete
        ? `${total} total players. ${pitchers} are pitchers. All profiles complete.`
        : `${total} total players. ${pitchers} are pitchers. ${incomplete} profiles are incomplete.`,
    );

    rendering = false;
  }

  const style = document.createElement('style');
  style.id = 'cb-roster-metrics-v2-styles';
  style.textContent = `
    #roster .cb-roster-metrics-v2{align-items:stretch}
    #roster .cb-roster-metrics-v2>span{display:flex;align-items:baseline;gap:4px}
    #roster .cb-roster-metrics-v2 .cb-roster-total{border-color:color-mix(in srgb,var(--cb-primary,#102a66) 28%,#dfe5ec);background:color-mix(in srgb,var(--cb-primary,#102a66) 5%,#fff)}
    #roster .cb-roster-metrics-v2 .cb-roster-total strong{color:var(--cb-primary,#102a66)}
    #roster .cb-roster-metrics-v2 .cb-roster-profile-metric:not(.is-complete){border-color:#ecd7a7;background:#fff8e8;color:#795000}
    #roster .cb-roster-metrics-v2 .cb-roster-metric-copy{font-weight:650}
    @media(max-width:767.98px){
      #roster .cb-roster-metrics-v2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%;gap:8px}
      #roster .cb-roster-metrics-v2>span{justify-content:center;min-width:0;white-space:normal;text-align:center;line-height:1.2}
      #roster .cb-roster-metrics-v2 .cb-roster-total{grid-column:1/-1;min-height:46px;font-size:.82rem}
      #roster .cb-roster-metrics-v2 .cb-roster-submetric{min-height:54px;flex-direction:column;justify-content:center;align-items:center;gap:2px;padding:8px}
      #roster .cb-roster-metrics-v2 .cb-roster-submetric strong{font-size:1rem;line-height:1}
      #roster .cb-roster-metrics-v2 .cb-roster-submetric .cb-roster-metric-copy{font-size:.66rem;line-height:1.2;color:inherit}
    }
  `;
  document.head.appendChild(style);

  const observer = new MutationObserver(() => window.requestAnimationFrame(render));
  observer.observe(metrics, {subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['class']});
  render();
})();