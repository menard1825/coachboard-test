// Shared, draft-based batting lineup editor. It never mutates the source lineup.
function initializeLineupEditor(options) {
    const roster = Array.isArray(options.roster) ? options.roster : [];
    const benchEl = options.benchEl;
    const orderEl = options.orderEl;
    const statusEl = options.statusEl || null;
    const rosterById = new Map(roster.map(player => [Number(player.id), player]));
    const rosterByName = new Map(roster.map(player => [player.name, player]));
    const escapeHTML = value => String(value ?? '').replace(/[&<>'"]/g, tag => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[tag] || tag));

    let benchSortable = null;
    let orderSortable = null;
    let draft = [];

    function normalize(source) {
        const entries = Array.isArray(source?.lineup_entries) && source.lineup_entries.length
            ? source.lineup_entries
            : (Array.isArray(source?.lineup_positions) ? source.lineup_positions : []).map((name, index) => ({
                name,
                player_id: Array.isArray(source?.lineup_player_ids) ? source.lineup_player_ids[index] : null,
            }));

        const usedIds = new Set();
        return entries.map(entry => {
            const suppliedId = entry && typeof entry === 'object' ? entry.player_id : null;
            const suppliedName = entry && typeof entry === 'object' ? (entry.name || entry.player_name_snapshot) : entry;
            const player = (suppliedId != null ? rosterById.get(Number(suppliedId)) : null) || rosterByName.get(suppliedName);
            if (player && !usedIds.has(Number(player.id))) {
                usedIds.add(Number(player.id));
                return { playerId: Number(player.id), name: player.name, number: player.number, available: true };
            }
            return { playerId: null, name: String(suppliedName || 'Unknown player'), number: null, available: false };
        });
    }

    function playerLabel(entry) {
        const number = entry.number ? ` <span class="text-muted">#${escapeHTML(entry.number)}</span>` : '';
        return `${escapeHTML(entry.name)}${number}`;
    }

    function render() {
        const selectedIds = new Set(draft.map(entry => entry.playerId).filter(id => id !== null));
        const bench = roster.filter(player => !selectedIds.has(Number(player.id)));

        orderEl.innerHTML = draft.length ? draft.map((entry, index) => `
            <div class="list-group-item px-2 py-2" data-player-id="${entry.playerId ?? ''}" data-player-name="${escapeHTML(entry.name)}">
                <div class="d-flex align-items-center gap-2">
                    <button type="button" class="btn btn-sm btn-light lineup-drag-handle" aria-label="Drag ${escapeHTML(entry.name)}">
                        <i class="bi bi-grip-vertical"></i>
                    </button>
                    <span class="badge rounded-pill text-bg-primary lineup-order-number">${index + 1}</span>
                    <div class="flex-grow-1 text-truncate">
                        <span class="fw-semibold">${playerLabel(entry)}</span>
                        ${entry.available ? '' : '<span class="badge text-bg-warning ms-1">Unavailable</span>'}
                    </div>
                    <div class="btn-group btn-group-sm" role="group" aria-label="Reorder ${escapeHTML(entry.name)}">
                        <button type="button" class="btn btn-outline-secondary move-up-btn" ${index === 0 ? 'disabled' : ''} aria-label="Move up"><i class="bi bi-arrow-up"></i></button>
                        <button type="button" class="btn btn-outline-secondary move-down-btn" ${index === draft.length - 1 ? 'disabled' : ''} aria-label="Move down"><i class="bi bi-arrow-down"></i></button>
                        <button type="button" class="btn btn-outline-danger remove-player-btn" aria-label="Remove"><i class="bi bi-x-lg"></i></button>
                    </div>
                </div>
            </div>
        `).join('') : `
            <div class="text-center p-4 text-muted placeholder-text">
                <i class="bi bi-list-ol fs-2"></i>
                <p class="mt-2 mb-0">Tap Add beside a player to build the batting order.</p>
            </div>`;

        benchEl.innerHTML = bench.length ? bench.map(player => `
            <div class="list-group-item px-2 py-2" data-player-id="${player.id}" data-player-name="${escapeHTML(player.name)}">
                <div class="d-flex align-items-center gap-2">
                    <span class="lineup-drag-handle text-muted px-1" aria-hidden="true"><i class="bi bi-grip-vertical"></i></span>
                    <span class="flex-grow-1 text-truncate">${playerLabel({ name: player.name, number: player.number })}</span>
                    <button type="button" class="btn btn-sm btn-outline-primary add-player-btn"><i class="bi bi-plus-lg me-1"></i>Add</button>
                </div>
            </div>
        `).join('') : `
            <div class="text-center p-4 text-muted placeholder-text">
                <i class="bi bi-check-circle fs-2"></i>
                <p class="mt-2 mb-0">All available players are in the order.</p>
            </div>`;

        if (statusEl) {
            const unavailable = draft.filter(entry => !entry.available).length;
            statusEl.className = unavailable ? 'alert alert-warning py-2 mb-3' : 'alert alert-light border py-2 mb-3';
            statusEl.textContent = `${draft.length} batter${draft.length === 1 ? '' : 's'} in the order • ${bench.length} available on the bench${unavailable ? ` • ${unavailable} unavailable` : ''}`;
        }
        setupSortables();
        options.onChange?.(controller);
    }

    function syncFromOrderDom() {
        const currentByKey = new Map(draft.map(entry => [`${entry.playerId ?? 'missing'}:${entry.name}`, entry]));
        draft = Array.from(orderEl.querySelectorAll('.list-group-item')).map(item => {
            const rawId = item.dataset.playerId;
            const id = rawId ? Number(rawId) : null;
            const name = item.dataset.playerName;
            const existing = currentByKey.get(`${id ?? 'missing'}:${name}`);
            const player = id !== null ? rosterById.get(id) : null;
            return existing || (player
                ? { playerId: id, name: player.name, number: player.number, available: true }
                : { playerId: null, name, number: null, available: false });
        });
        render();
    }

    function setupSortables() {
        benchSortable?.destroy();
        orderSortable?.destroy();
        if (typeof Sortable === 'undefined') return;
        const shared = {
            group: 'lineup',
            animation: 150,
            handle: '.lineup-drag-handle',
            ghostClass: 'lineup-ghost',
            delay: 140,
            delayOnTouchOnly: true,
            onEnd: syncFromOrderDom,
        };
        benchSortable = new Sortable(benchEl, { ...shared, sort: false });
        orderSortable = new Sortable(orderEl, shared);
    }

    function move(index, offset) {
        const target = index + offset;
        if (index < 0 || target < 0 || target >= draft.length) return;
        [draft[index], draft[target]] = [draft[target], draft[index]];
        render();
    }

    function onOrderClick(event) {
        const item = event.target.closest('.list-group-item');
        if (!item) return;
        const index = Array.from(orderEl.querySelectorAll('.list-group-item')).indexOf(item);
        if (event.target.closest('.move-up-btn')) move(index, -1);
        if (event.target.closest('.move-down-btn')) move(index, 1);
        if (event.target.closest('.remove-player-btn')) {
            draft.splice(index, 1);
            render();
        }
    }

    function onBenchClick(event) {
        if (!event.target.closest('.add-player-btn')) return;
        const item = event.target.closest('.list-group-item');
        const player = rosterById.get(Number(item?.dataset.playerId));
        if (!player || draft.some(entry => entry.playerId === Number(player.id))) return;
        draft.push({ playerId: Number(player.id), name: player.name, number: player.number, available: true });
        render();
    }

    orderEl.addEventListener('click', onOrderClick);
    benchEl.addEventListener('click', onBenchClick);

    const controller = {
        getPlayerIds: () => draft.filter(entry => entry.available).map(entry => entry.playerId),
        getPlayerNames: () => draft.map(entry => entry.name),
        getCount: () => draft.length,
        getUnavailableEntries: () => draft.filter(entry => !entry.available).map(entry => ({ ...entry })),
        getBenchPlayers: () => {
            const used = new Set(draft.map(entry => entry.playerId));
            return roster.filter(player => !used.has(Number(player.id)));
        },
        setLineup: source => {
            draft = normalize(source || {});
            render();
        },
        rotate: () => {
            if (draft.length > 1) draft.push(draft.shift());
            render();
        },
        destroy: () => {
            benchSortable?.destroy();
            orderSortable?.destroy();
            orderEl.removeEventListener('click', onOrderClick);
            benchEl.removeEventListener('click', onBenchClick);
        },
    };

    draft = normalize(options.lineup || {});
    render();
    return controller;
}
