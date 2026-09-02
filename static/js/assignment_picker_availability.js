(() => {
  'use strict';

  const SELECT_GROUPS = [
    { selector: '.ni-select', container: '#next-inning-adjust-body' },
    { selector: '.bulk-defense-select', container: '#live-defense-bulk-v2, #live-defense-v2, .modal.show' },
  ];

  let queued = false;
  const optionCache = new WeakMap();

  function schedule() {
    if (queued) return;
    queued = true;
    window.setTimeout(() => {
      queued = false;
      applyAll();
    }, 0);
  }

  function detailText(button, selector) {
    return button.querySelector(selector)?.textContent?.trim() || '';
  }

  function ensureEmptyMessage(host, selector, message) {
    const existing = host.querySelector(selector);
    const hasPlayerChoice = host.querySelector('[data-rte-choice]:not([data-rte-choice=""]), .pde-choice[data-player]');
    if (hasPlayerChoice) {
      existing?.remove();
      return;
    }
    if (existing) return;
    const empty = document.createElement('div');
    empty.className = selector.replace(/^\./, '');
    empty.style.padding = '14px';
    empty.style.color = '#667085';
    empty.style.fontSize = '.78rem';
    empty.textContent = message;
    host.appendChild(empty);
  }

  function filterRotationTemplatePicker() {
    const list = document.getElementById('rtePlayerChoices');
    if (!list) return;

    let changed = false;
    [...list.querySelectorAll('[data-rte-choice]')].forEach((button) => {
      const name = String(button.dataset.rteChoice || '');
      if (!name) return; // Keep the explicit Open/Bench action.
      const detail = detailText(button, '.rte-choice-detail');
      if (/^Currently at\b/i.test(detail)) {
        button.remove();
        changed = true;
      }
    });

    const help = document.getElementById('rtePlayerHelp');
    if (help) {
      help.textContent = 'Only unassigned players are shown. To move someone already on the field, open that player’s current position first.';
    }

    ensureEmptyMessage(
      list,
      '.cb-assignment-empty-rte',
      'No unassigned players remain. Open another position first if you need to move someone.'
    );

    if (changed) list.dataset.cbAssignmentFiltered = '1';
  }

  function filterPregameDefensePicker() {
    const list = document.getElementById('pde-list');
    if (!list) return;

    // The older clarity helper tucked already-fielded players behind a secondary
    // toggle. The new rule is simpler: they are not choices in a unique-position
    // picker at all.
    list.querySelectorAll('.pde-field-move-toggle, .pde-field-move-wrap').forEach((node) => node.remove());

    [...list.querySelectorAll('.pde-choice[data-player]')].forEach((button) => {
      const detail = detailText(button, 'small');
      if (/^Currently at\b/i.test(detail)) button.remove();
    });

    const help = document.getElementById('pde-help');
    if (help) {
      help.textContent = 'Only players still on the bench are shown. To move a fielder, open that player’s current position first.';
    }

    const existingClarityEmpty = list.querySelector('.pde-picker-empty');
    if (!existingClarityEmpty) {
      ensureEmptyMessage(
        list,
        '.cb-assignment-empty-pde',
        'No unassigned players remain this inning.'
      );
    }
  }

  function cacheOptions(select) {
    let cached = optionCache.get(select);
    if (!cached) {
      cached = {
        blankText: select.querySelector('option[value=""]')?.textContent || 'Open position',
        options: new Map(),
      };
      optionCache.set(select, cached);
    }

    [...select.options].forEach((option) => {
      if (!option.value) {
        cached.blankText = option.textContent || cached.blankText;
        return;
      }
      if (!cached.options.has(option.value)) {
        cached.options.set(option.value, option.textContent);
      }
    });
    return cached;
  }

  function filterSelectGroup(selector) {
    const selects = [...document.querySelectorAll(selector)];
    if (selects.length < 2) return;

    const selectedValues = new Set(selects.map((select) => select.value).filter(Boolean));

    selects.forEach((select) => {
      const own = select.value || '';
      const cache = cacheOptions(select);
      const desired = [];

      desired.push({ value: '', text: cache.blankText });
      cache.options.forEach((text, value) => {
        if (value === own || !selectedValues.has(value)) desired.push({ value, text });
      });

      const current = [...select.options].map((option) => `${option.value}\u0000${option.textContent}`);
      const next = desired.map((option) => `${option.value}\u0000${option.text}`);
      if (current.length === next.length && current.every((value, index) => value === next[index])) return;

      select.replaceChildren(...desired.map(({value, text}) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = text;
        option.selected = value === own;
        return option;
      }));
    });
  }

  function applyAll() {
    filterRotationTemplatePicker();
    filterPregameDefensePicker();
    SELECT_GROUPS.forEach(({selector}) => filterSelectGroup(selector));
  }

  document.addEventListener('change', (event) => {
    if (event.target.matches('.ni-select, .bulk-defense-select')) schedule();
  }, true);

  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyAll, { once: true });
  } else {
    applyAll();
  }
})();
