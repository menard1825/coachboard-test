(() => {
  'use strict';
  if (window.location.pathname !== '/admin/users') return;

  function patch() {
    document.querySelectorAll('button').forEach(button => {
      const text = (button.textContent || '').trim();
      if (/^Reset Password$/i.test(text)) {
        button.classList.remove('btn-outline-warning');
        button.classList.add('btn-outline-primary');
        button.innerHTML = '<i class="bi bi-key me-1"></i>Password Help';
      }
    });

    document.querySelectorAll('[id^="resetPasswordModal-"]').forEach(modal => {
      const title = modal.querySelector('.modal-title');
      if (title && !/Password Help/i.test(title.textContent || '')) {
        title.textContent = (title.textContent || '').replace(/^Reset Password for/i, 'Password Help for');
      }
      const body = modal.querySelector('.modal-body');
      if (body) {
        body.innerHTML = '<p class="mb-2"><strong>Help this coach get back into CoachBoard.</strong></p><p class="text-muted small mb-0">CoachBoard will create a secure, one-hour reset link. The coach opens the link and chooses their own new password. You will not need to create or text them a temporary password.</p>';
      }
      const submit = modal.querySelector('form button[type="submit"]');
      if (submit) {
        submit.className = 'btn btn-primary';
        submit.innerHTML = '<i class="bi bi-link-45deg me-1"></i>Create Reset Link';
      }
    });

    document.querySelectorAll('.user-row').forEach(row => {
      const username = row.dataset.username;
      if (!username) return;
      const modal = document.getElementById(`resetPasswordModal-${username}`);
      const actionCell = row.querySelector('[data-label="Actions"]');
      if (!modal || !actionCell || actionCell.querySelector('.cb-password-help-row')) return;

      const editButton = actionCell.querySelector('button[data-bs-target^="#editUserModal-"]');
      if (!editButton) return;

      const help = document.createElement('button');
      help.type = 'button';
      help.className = 'btn btn-sm btn-outline-primary ms-1 cb-password-help-row';
      help.dataset.bsToggle = 'modal';
      help.dataset.bsTarget = `#resetPasswordModal-${username}`;
      help.innerHTML = '<i class="bi bi-key me-1"></i>Password Help';
      editButton.insertAdjacentElement('afterend', help);
    });
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', patch, {once:true})
    : patch();
})();
