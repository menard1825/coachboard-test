(() => {
  'use strict';

  if (window.location.pathname !== '/') return;

  let traitOptions = [];
  const profiles = new Map();
  let loaded = false;
  let loading = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));

  function installStyles() {
    if (document.getElementById('roster-pitching-traits-styles')) return;
    const style = document.createElement('style');
    style.id = 'roster-pitching-traits-styles';
    style.textContent = `
      .roster-pitch-profile{border:1px solid #dfe5ec;background:#fff;border-radius:12px;padding:12px;margin-top:2px}
      .roster-pitch-profile-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:9px}
      .roster-pitch-profile-title{font-size:.78rem;font-weight:850;color:#1d2939}
      .roster-pitch-profile-help{font-size:.68rem;color:#667085;margin-top:1px}
      .roster-pitch-hand{font-size:.63rem;font-weight:800;border:1px solid #d7dde5;background:#f7f8fa;border-radius:999px;padding:4px 7px;white-space:nowrap;color:#475467}
      .roster-trait-grid{display:flex;flex-wrap:wrap;gap:6px}
      .roster-trait-grid .btn{border-radius:999px;font-size:.68rem;font-weight:700;padding:6px 9px;line-height:1.15}
      .roster-trait-status{font-size:.66rem;color:#667085;margin-top:8px;min-height:1em}
      .roster-trait-status.saved{color:#176b38;font-weight:750}
      .roster-trait-status.error{color:#b42318;font-weight:750}
      @media(max-width:575.98px){.roster-pitch-profile{padding:10px}.roster-trait-grid .btn{font-size:.64rem;padding:6px 8px}}
    `;
    document.head.appendChild(style);
  }

  async function loadProfiles() {
    if (loading) return;
    loading = true;
    try {
      const response = await fetch('/api/roster-pitching-profiles', {cache:'no-store'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to load pitching profiles.');
      traitOptions = Array.isArray(data.traits) ? data.traits : [];
      profiles.clear();
      Object.entries(data.profiles || {}).forEach(([playerId, traits]) => {
        profiles.set(Number(playerId), Array.isArray(traits) ? traits : []);
      });
      loaded = true;
      patchRoster();
    } catch (error) {
      console.error('Unable to load roster pitching profiles:', error);
    } finally {
      loading = false;
    }
  }

  function selectedTraits(section) {
    return [...section.querySelectorAll('.roster-pitch-trait:checked')].map(input => input.value);
  }

  async function saveTraits(section, playerId) {
    const status = section.querySelector('.roster-trait-status');
    const inputs = [...section.querySelectorAll('.roster-pitch-trait')];
    inputs.forEach(input => { input.disabled = true; });
    if (status) {
      status.className = 'roster-trait-status';
      status.textContent = 'Saving…';
    }

    try {
      const traits = selectedTraits(section);
      const response = await fetch(`/update_pitching_profile/${playerId}`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({traits}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unable to save pitching traits.');
      profiles.set(Number(playerId), Array.isArray(data.traits) ? data.traits : traits);
      if (status) {
        status.className = 'roster-trait-status saved';
        status.textContent = 'Saved — available in Game Day pitching plans.';
      }
    } catch (error) {
      if (status) {
        status.className = 'roster-trait-status error';
        status.textContent = error.message || 'Unable to save traits.';
      }
    } finally {
      inputs.forEach(input => { input.disabled = false; });
    }
  }

  function throwsLabel(cardBody) {
    const select = cardBody.querySelector('select[name="throws"]');
    const hand = select?.value || 'Not set';
    return hand === 'Left' ? 'Throws Left' : hand === 'Right' ? 'Throws Right' : `Throws ${hand}`;
  }

  function buildSection(playerId, cardBody) {
    const selected = new Set((profiles.get(Number(playerId)) || []).filter(trait => !['LHP','RHP'].includes(trait)));
    const section = document.createElement('div');
    section.className = 'col-12 roster-pitch-profile';
    section.dataset.playerId = String(playerId);
    section.innerHTML = `
      <div class="roster-pitch-profile-head">
        <div>
          <div class="roster-pitch-profile-title">Pitching Traits</div>
          <div class="roster-pitch-profile-help">Persistent scouting traits. These automatically carry into Game Day pitching decisions.</div>
        </div>
        <span class="roster-pitch-hand">${esc(throwsLabel(cardBody))}</span>
      </div>
      <div class="roster-trait-grid">
        ${traitOptions.map((trait, index) => {
          const id = `roster-trait-${playerId}-${index}`;
          return `<input type="checkbox" class="btn-check roster-pitch-trait" id="${id}" value="${esc(trait)}" ${selected.has(trait) ? 'checked' : ''}><label class="btn btn-outline-secondary" for="${id}">${esc(trait)}</label>`;
        }).join('')}
      </div>
      <div class="roster-trait-status">Tap traits to save them automatically.</div>`;

    section.querySelectorAll('.roster-pitch-trait').forEach(input => {
      input.addEventListener('change', () => saveTraits(section, playerId));
    });

    const throwsSelect = cardBody.querySelector('select[name="throws"]');
    throwsSelect?.addEventListener('change', () => {
      const badge = section.querySelector('.roster-pitch-hand');
      if (badge) badge.textContent = throwsLabel(cardBody);
    });
    return section;
  }

  function patchRoster() {
    if (!loaded || !traitOptions.length) return;
    document.querySelectorAll('#roster-cards-container .save-player-btn[data-player-id]').forEach(button => {
      const cardBody = button.closest('.card-body');
      if (!cardBody || cardBody.querySelector('.roster-pitch-profile')) return;
      const playerId = Number(button.dataset.playerId);
      if (!Number.isFinite(playerId)) return;
      const saveRow = button.closest('.col-12');
      const section = buildSection(playerId, cardBody);
      if (saveRow?.parentNode) saveRow.parentNode.insertBefore(section, saveRow);
      else cardBody.appendChild(section);
    });
  }

  installStyles();
  const observer = new MutationObserver(() => window.requestAnimationFrame(patchRoster));
  const start = () => {
    observer.observe(document.body, {childList:true, subtree:true});
    loadProfiles();
  };
  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', start, {once:true})
    : start();
})();
