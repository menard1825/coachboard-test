/* Bind every request to the team displayed when this page was rendered. */
(() => {
    const context = window.coachboardTeam;
    if (!context || !context.id) return;
    const nativeFetch = window.fetch.bind(window);
    const isWriteLink = path => /\/(delete_[^/]+|complete_focus)\//.test(path);
    function fields(form) {
        for (const [name, value] of Object.entries({_team_id: context.id, _csrf_token: context.csrf})) {
            let input = form.querySelector(`input[name="${name}"]`);
            if (!input) { input = document.createElement('input'); input.type = 'hidden'; input.name = name; form.append(input); }
            input.value = value;
        }
    }
    window.fetch = async (input, init = {}) => {
        const url = new URL(input instanceof Request ? input.url : input, location.href);
        if (url.origin !== location.origin) return nativeFetch(input, init);
        const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
        headers.set('X-Team-ID', context.id);
        headers.set('X-CSRF-Token', context.csrf);
        headers.set('X-Requested-With', 'XMLHttpRequest');
        const response = await nativeFetch(input, {...init, headers});
        if (response.status === 409) {
            const data = await response.clone().json().catch(() => ({}));
            alert(data.message || 'Your active team changed. Reload this page.');
        }
        return response;
    };
    // Capture runs before existing listeners construct FormData or submit forms.
    document.addEventListener('submit', event => {
        if (new URL(event.target.action, location.href).origin === location.origin) fields(event.target);
    }, true);
    document.addEventListener('click', event => {
        const link = event.target.closest('a[href]');
        if (!link) return;
        const url = new URL(link.href, location.href);
        if (url.origin !== location.origin || !isWriteLink(url.pathname)) return;
        event.preventDefault();
        const form = document.createElement('form'); form.method = 'POST'; form.action = url.pathname + url.search;
        fields(form); document.body.append(form); form.submit();
    }, true);
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('form').forEach(fields);
        const rollover = document.getElementById('rollover-form');
        rollover?.addEventListener('submit', () => {
            const button = rollover.querySelector('button[type="submit"]');
            button.disabled = true; button.textContent = 'Creating team…';
        });
    });
})();
