// static/js/lineup_editor.js

// Using a global function for now, assuming this file is loaded via a script tag.
// A more robust solution might use ES6 modules.
function initializeLineupEditor(options) {
    const {
        roster,
        lineup,
        benchEl,
        orderEl
    } = options;

    // FIX: Ensure lineup_positions is always a valid array, parsing from JSON if necessary.
    if (typeof lineup.lineup_positions === 'string') {
        try {
            lineup.lineup_positions = JSON.parse(lineup.lineup_positions);
            if (!Array.isArray(lineup.lineup_positions)) {
                lineup.lineup_positions = [];
            }
        } catch (e) {
            console.error("Error parsing lineup_positions JSON:", e);
            lineup.lineup_positions = [];
        }
    } else if (!Array.isArray(lineup.lineup_positions)) {
        lineup.lineup_positions = [];
    }

    const escapeHTML = str => String(str).replace(/[&<>'"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;',"'": '&#39;','"': '&quot;'}[tag] || tag));

    function createBenchPlayerItem(player) {
        const item = document.createElement('div');
        item.className = 'list-group-item';
        item.dataset.playerName = player.name;
        item.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="bi bi-grip-vertical me-2" style="cursor: grab;"></i>
                <span>${escapeHTML(player.name)} (#${escapeHTML(player.number) || 'N/A'})</span>
            </div>
        `;
        return item;
    }

    function createBattingOrderItem(player) {
        const item = document.createElement('div');
        item.className = 'list-group-item';
        item.dataset.playerName = player.name;
        item.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <div class="d-flex align-items-center">
                    <i class="bi bi-grip-vertical lineup-drag-handle me-2" style="cursor: grab;"></i>
                    <span class="fw-bold">${escapeHTML(player.name)} (#${escapeHTML(player.number) || 'N/A'})</span>
                </div>
                <div class="btn-group">
                    <button type="button" class="btn btn-sm btn-outline-secondary move-up-btn"><i class="bi bi-arrow-up"></i></button>
                    <button type="button" class="btn btn-sm btn-outline-secondary move-down-btn"><i class="bi bi-arrow-down"></i></button>
                    <button type="button" class="btn btn-sm btn-outline-danger remove-player-btn" aria-label="Remove player">
                        <i class="bi bi-x-lg"></i>
                    </button>
                </div>
            </div>`;
        return item;
    }

    function renderLineup() {
        benchEl.innerHTML = '';
        orderEl.innerHTML = '';

        const lineupPlayerNames = new Set(lineup.lineup_positions || []);

        roster.forEach(player => {
            if (!lineupPlayerNames.has(player.name)) {
                benchEl.appendChild(createBenchPlayerItem(player));
            }
        });

        (lineup.lineup_positions || []).forEach(playerName => {
            const player = roster.find(p => p.name === playerName);
            if (player) {
                orderEl.appendChild(createBattingOrderItem(player));
            }
        });
        updatePlaceholders();
    }

    function updatePlaceholders() {
        benchEl.querySelector('.placeholder-text')?.remove();
        orderEl.querySelector('.placeholder-text')?.remove();

        if (orderEl.children.length === 0) {
            orderEl.innerHTML = `<div class="text-center p-5 text-muted fst-italic placeholder-text"><i class="bi bi-people" style="font-size: 2rem;"></i><p class="mt-2 mb-0">Drag players from the bench to build the batting order.</p></div>`;
        }

        if (benchEl.children.length === 0) {
            benchEl.innerHTML = `<div class="text-center p-5 text-muted fst-italic placeholder-text"><i class="bi bi-check-circle" style="font-size: 2rem;"></i><p class="mt-2 mb-0">All available players are in the lineup.</p></div>`;
        }
    }

    function setupEventListeners() {
        orderEl.addEventListener('click', (event) => {
            const moveUpButton = event.target.closest('.move-up-btn');
            const moveDownButton = event.target.closest('.move-down-btn');
            const removeButton = event.target.closest('.remove-player-btn');
            const playerItem = event.target.closest('.list-group-item');

            if (!playerItem) return;

            const index = Array.from(orderEl.children).indexOf(playerItem);

            if (moveUpButton) {
                if (index > 0) {
                    [lineup.lineup_positions[index], lineup.lineup_positions[index - 1]] = [lineup.lineup_positions[index - 1], lineup.lineup_positions[index]];
                    renderLineup();
                }
            } else if (moveDownButton) {
                if (index < lineup.lineup_positions.length - 1) {
                    [lineup.lineup_positions[index], lineup.lineup_positions[index + 1]] = [lineup.lineup_positions[index + 1], lineup.lineup_positions[index]];
                    renderLineup();
                }
            } else if (removeButton) {
                const playerName = playerItem.dataset.playerName;
                const player = roster.find(p => p.name === playerName);

                if (player) {
                    lineup.lineup_positions = lineup.lineup_positions.filter(p => p !== playerName);
                    const newBenchItem = createBenchPlayerItem(player);
                    benchEl.appendChild(newBenchItem);
                    playerItem.remove();
                    updatePlaceholders();
                }
            }
        });
    }

    renderLineup();
    setupEventListeners();

    if (benchEl.sortable) benchEl.sortable.destroy();
    if (orderEl.sortable) orderEl.sortable.destroy();

    let ghostPositionEl = null;

    const onDragStart = () => {
        document.body.classList.add('dragging-lineup-player');
    };

    const onDragMove = (evt) => {
        const ghostEl = document.querySelector('.lineup-ghost');
        if (!ghostEl) return;

        if (!ghostEl.dataset.ghostModified) {
            ghostEl.dataset.ghostModified = 'true';
            const mainContainer = ghostEl.querySelector('.d-flex.align-items-center');
            if (mainContainer) {
                ghostPositionEl = document.createElement('span');
                ghostPositionEl.className = 'ghost-position-number';
                mainContainer.insertBefore(ghostPositionEl, mainContainer.firstChild);
                ghostEl.classList.add('sortable-ghost-custom');
            }
        }

        if (ghostPositionEl) {
            if (evt.to === orderEl) {
                const newIndex = evt.newIndex;
                if (typeof newIndex === 'number') {
                    const pos = newIndex + 1;
                    ghostPositionEl.textContent = `${pos}.\u00A0`;
                } else {
                    const isOrderEmpty = orderEl.children.length === 0 || orderEl.querySelector('.placeholder-text');
                    ghostPositionEl.textContent = isOrderEmpty ? '1.\u00A0' : '';
                }
            } else {
                ghostPositionEl.textContent = '';
            }
        }
    };

    const onSortEnd = () => {
        document.body.classList.remove('dragging-lineup-player');
        ghostPositionEl = null;
        lineup.lineup_positions = Array.from(orderEl.querySelectorAll('.list-group-item')).map(item => item.dataset.playerName);
        renderLineup();
        benchEl.scrollTop = 0;
        orderEl.scrollTop = 0;
    };

    const sortableOptions = {
        group: 'lineup',
        animation: 150,
        ghostClass: 'lineup-ghost',
        onStart: onDragStart,
        onMove: onDragMove,
        onEnd: onSortEnd,
    };

    benchEl.sortable = new Sortable(benchEl, sortableOptions);
    orderEl.sortable = new Sortable(orderEl, {
        ...sortableOptions,
        handle: '.lineup-drag-handle',
    });
}
