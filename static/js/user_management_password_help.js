(() => {
  'use strict';
  if (window.location.pathname !== '/admin/users') return;

  function bindPasswordHelpHandoff(button) {
    if (!button || button.dataset.cbPasswordHelpHandoff === '1') return;

    const targetSelector = button.getAttribute('data-bs-target') || '';
    if (!targetSelector.startsWith('#resetPasswordModal-')) return;

    button.dataset.cbPasswordHelpHandoff = '1';

    // Opening one Bootstrap modal while another is still fading out can leave
    // the old backdrop above the new dialog on iOS/WebKit. Own the transition
    // explicitly instead of dismissing and toggling two modals in one tap.
    button.removeAttribute('data-bs-dismiss');
    button.removeAttribute('data-bs-toggle');

    let handoffPending = false;
    button.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      if (handoffPending) return;

      const targetModal = document.querySelector(targetSelector);
      if (!targetModal || !window.bootstrap?.Modal) return;

      handoffPending = true;

      // Bootstrap appends backdrops to <body>. Keeping the target modal there as
      // a sibling avoids ancestor stacking contexts that can trap a modal below
      // its own backdrop on Safari/Chrome for iOS.
      if (targetModal.parentElement !== document.body) {
        document.body.appendChild(targetModal);
      }

      const showTarget = () => {
        const targetInstance = bootstrap.Modal.getOrCreateInstance(targetModal);
        const finish = () => {
          handoffPending = false;
          targetModal.removeEventListener('shown.bs.modal', finish);
        };
        targetModal.addEventListener('shown.bs.modal', finish, {once: true});
        targetInstance.show();
        window.setTimeout(() => { handoffPending = false; }, 1000);
      };

      const sourceModal = button.closest('.modal.show');
      if (!sourceModal) {
        showTarget();
        return;
      }

      sourceModal.addEventListener('hidden.bs.modal', showTarget, {once: true});
      bootstrap.Modal.getOrCreateInstance(sourceModal).hide();
    });
  }

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

    document.querySelectorAll('button[data-bs-target^="#resetPasswordModal-"]').forEach(bindPasswordHelpHandoff);

    // Password Help now lives inside the Manage dialog. Keeping it out of every
    // table row makes the user list much easier to scan, especially on phones.
    document.querySelectorAll('.cb-password-help-row').forEach(button => button.remove());
  }

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', patch, {once:true})
    : patch();
})();
