(() => {
  'use strict';
  if (window.location.pathname !== '/admin/users') return;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  function activeTeamName() {
    return (document.querySelector('.navbar-brand-text')?.textContent || '').trim();
  }

  function roleBadge(role) {
    const styles = {
      'Super Admin': 'text-bg-dark',
      'Head Coach': 'text-bg-primary',
      'Assistant Coach': 'text-bg-secondary',
      'Game Changer': 'text-bg-light border text-dark',
    };
    return `<span class="badge ${styles[role] || 'text-bg-light border text-dark'}">${esc(role)}</span>`;
  }

  function injectStyles() {
    if (document.getElementById('cb-user-cleanup-style')) return;
    const style = document.createElement('style');
    style.id = 'cb-user-cleanup-style';
    style.textContent = `
      .cb-user-admin-card{border:0;box-shadow:0 8px 24px rgba(15,23,42,.08);border-radius:16px;overflow:hidden}
      .cb-user-admin-card .card-header{background:#fff;border-bottom:1px solid #e9ecef;padding:1rem 1.15rem}
      .cb-user-admin-heading{gap:1rem;flex-wrap:wrap}
      .cb-user-admin-toolbar{display:grid;grid-template-columns:minmax(210px,1fr) minmax(150px,190px) minmax(180px,240px) auto;gap:.65rem;align-items:center;flex:1;max-width:860px}
      .cb-user-admin-toolbar .form-control,.cb-user-admin-toolbar .form-select{min-height:42px}
      .cb-user-admin-table th{font-size:.74rem;text-transform:uppercase;letter-spacing:.035em;color:#64748b;background:#f8fafc;white-space:nowrap}
      .cb-user-admin-table td{padding:.78rem .75rem;vertical-align:middle}
      .cb-user-name{font-weight:700;color:#0f172a;line-height:1.15}
      .cb-user-handle{font-size:.78rem;color:#64748b;margin-top:.18rem}
      .cb-current-team-pill{display:inline-flex;align-items:center;gap:.3rem;font-size:.78rem;border:1px solid #dbe3ec;border-radius:999px;padding:.25rem .55rem;background:#f8fafc;white-space:nowrap}
      .cb-manage-user{min-width:92px}
      .cb-user-empty{padding:2.5rem 1rem;text-align:center;color:#64748b}
      .cb-switch-team-note{font-size:.72rem;color:#64748b;line-height:1.2;display:inline-block;max-width:130px}
      @media (max-width: 1100px){
        .cb-user-admin-toolbar{max-width:none;width:100%;flex-basis:100%}
      }
      @media (max-width: 900px){
        .cb-user-admin-toolbar{grid-template-columns:1fr 1fr}
        .cb-user-admin-toolbar .cb-add-user{grid-column:1/-1;width:100%}
      }
      @media (max-width: 600px){
        .cb-user-admin-toolbar{grid-template-columns:1fr}
        .cb-user-admin-toolbar .cb-add-user{grid-column:auto}
        .cb-user-admin-card .card-header{padding:.85rem}
        .cb-user-admin-table thead{display:none}
        .cb-user-admin-table,.cb-user-admin-table tbody,.cb-user-admin-table tr,.cb-user-admin-table td{display:block;width:100%}
        .cb-user-admin-table tr{padding:.8rem;border-bottom:1px solid #e5e7eb}
        .cb-user-admin-table td{padding:.25rem 0;border:0!important;text-align:left!important}
        .cb-user-admin-table td[data-label="Actions"]{padding-top:.6rem}
        .cb-manage-user{width:100%}
        .cb-switch-team-note{max-width:none}
      }
    `;
    document.head.appendChild(style);
  }

  function setup() {
    injectStyles();

    const currentTeam = activeTeamName();
    const card = document.querySelector('.card');
    const table = document.querySelector('table');
    const tbody = table?.querySelector('tbody');
    const search = document.getElementById('user-search');
    const roleFilter = document.getElementById('role-filter');
    const addButton = document.querySelector('[data-bs-target="#addUserModal"]');
    if (!card || !table || !tbody || !search || !roleFilter) return;

    card.classList.add('cb-user-admin-card');
    table.classList.add('cb-user-admin-table');
    table.classList.remove('table-striped');

    const headerLayout = card.querySelector('.card-header > .d-flex');
    headerLayout?.classList.add('cb-user-admin-heading');

    const headerTitle = card.querySelector('.card-header h5');
    if (headerTitle) {
      headerTitle.innerHTML = '<span class="d-block">Coaches & Access</span><small class="text-muted fw-normal">Manage who can access CoachBoard and what they can do.</small>';
    }

    search.placeholder = 'Search coach or username…';
    if (addButton) {
      addButton.classList.add('cb-add-user');
      addButton.innerHTML = '<i class="bi bi-person-plus me-1"></i>Add Coach';
    }

    const headerCells = [...table.querySelectorAll('thead th')];
    const teamColumnIndex = headerCells.findIndex(th => th.textContent.trim() === 'Team');
    const fullNameIndex = headerCells.findIndex(th => th.textContent.trim() === 'Full Name');
    const usernameIndex = headerCells.findIndex(th => th.textContent.trim() === 'Username');
    const roleIndex = headerCells.findIndex(th => th.textContent.trim() === 'Role');
    const actionsIndex = headerCells.findIndex(th => th.textContent.trim() === 'Actions');

    if (usernameIndex >= 0) headerCells[usernameIndex].textContent = 'Coach';
    if (fullNameIndex >= 0) headerCells[fullNameIndex].style.display = 'none';
    if (actionsIndex >= 0) headerCells[actionsIndex].textContent = '';

    const rows = [...tbody.querySelectorAll('.user-row')];
    rows.forEach(row => {
      const cells = [...row.children];
      const username = row.dataset.username || '';
      const fullName = fullNameIndex >= 0 ? (cells[fullNameIndex]?.textContent || '').trim() : '';
      const role = row.dataset.role || (roleIndex >= 0 ? cells[roleIndex]?.textContent.trim() : '');
      const team = teamColumnIndex >= 0 ? (cells[teamColumnIndex]?.textContent || '').trim() : currentTeam;

      row.dataset.fullName = fullName;
      row.dataset.teamName = team;
      row.dataset.searchText = `${username} ${fullName} ${team} ${role}`.toLowerCase();

      if (usernameIndex >= 0 && cells[usernameIndex]) {
        cells[usernameIndex].innerHTML = `<div class="cb-user-name">${esc(fullName && fullName !== 'N/A' ? fullName : username)}</div><div class="cb-user-handle">@${esc(username)}</div>`;
      }
      if (fullNameIndex >= 0 && cells[fullNameIndex]) cells[fullNameIndex].style.display = 'none';
      if (roleIndex >= 0 && cells[roleIndex]) cells[roleIndex].innerHTML = roleBadge(role);
      if (teamColumnIndex >= 0 && cells[teamColumnIndex]) {
        const active = team === currentTeam ? ' <span class="text-success fw-semibold">· Current</span>' : '';
        cells[teamColumnIndex].innerHTML = `<span class="cb-current-team-pill"><i class="bi bi-people"></i>${esc(team)}${active}</span>`;
      }

      const actionCell = row.querySelector('[data-label="Actions"]');
      const edit = actionCell?.querySelector('button[data-bs-target^="#editUserModal-"]');
      actionCell?.querySelectorAll('.cb-password-help-row').forEach(button => button.remove());

      if (edit && (teamColumnIndex < 0 || team === currentTeam)) {
        edit.className = 'btn btn-sm btn-outline-primary cb-manage-user';
        edit.innerHTML = '<i class="bi bi-sliders me-1"></i>Manage';
      } else if (edit && teamColumnIndex >= 0 && team !== currentTeam && actionCell) {
        actionCell.innerHTML = '<span class="cb-switch-team-note">Switch to this team to manage access.</span>';
      } else if (actionCell) {
        actionCell.innerHTML = '<span class="badge text-bg-light border text-muted">You</span>';
      }
    });

    const toolbarHost = card.querySelector('.card-header > .d-flex > .d-flex.align-items-center');
    if (toolbarHost) {
      toolbarHost.classList.remove('d-flex', 'align-items-center');
      toolbarHost.classList.add('cb-user-admin-toolbar');
      [...toolbarHost.children].forEach(el => el.classList.remove('me-2'));
    }

    let teamFilter = null;
    if (teamColumnIndex >= 0 && toolbarHost) {
      teamFilter = document.createElement('select');
      teamFilter.id = 'team-filter';
      teamFilter.className = 'form-select form-select-sm';
      teamFilter.setAttribute('aria-label', 'Filter by team');
      const teams = [...new Set(rows.map(row => row.dataset.teamName).filter(Boolean))].sort((a,b) => a.localeCompare(b));
      teamFilter.innerHTML = '<option value="">All Teams</option>' + teams.map(team => `<option value="${esc(team)}">${esc(team)}</option>`).join('');
      if (teams.includes(currentTeam)) teamFilter.value = currentTeam;
      roleFilter.insertAdjacentElement('afterend', teamFilter);
    }

    let empty = document.getElementById('cbUserEmpty');
    if (!empty) {
      empty = document.createElement('div');
      empty.id = 'cbUserEmpty';
      empty.className = 'cb-user-empty d-none';
      empty.innerHTML = '<i class="bi bi-person-x fs-3 d-block mb-2"></i>No coaches match those filters.';
      table.parentElement?.appendChild(empty);
    }

    function applyFilters() {
      const query = (search.value || '').trim().toLowerCase();
      const role = roleFilter.value || '';
      const team = teamFilter?.value || '';
      let visible = 0;

      rows.forEach(row => {
        const matchesSearch = !query || (row.dataset.searchText || '').includes(query);
        const matchesRole = !role || row.dataset.role === role;
        const matchesTeam = !team || row.dataset.teamName === team;
        const show = matchesSearch && matchesRole && matchesTeam;
        row.style.display = show ? '' : 'none';
        if (show) visible += 1;
      });

      empty.classList.toggle('d-none', visible !== 0);
      table.classList.toggle('d-none', visible === 0);
    }

    [search, roleFilter, teamFilter].filter(Boolean).forEach(control => {
      const eventName = control === search ? 'input' : 'change';
      control.addEventListener(eventName, () => setTimeout(applyFilters, 0));
    });

    applyFilters();
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', setup, {once: true})
    : setup();
})();
