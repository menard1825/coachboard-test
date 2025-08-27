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
            // Attempt to parse the string as JSON.
            lineup.lineup_positions = JSON.parse(lineup.lineup_positions);
            // Further check if the parsed result is actually an array.
            if (!Array.isArray(lineup.lineup_positions)) {
                lineup.lineup_positions = [];
            }
        } catch (e) {
            console.error("Error parsing lineup_positions JSON:", e);
            // If parsing fails, default to an empty array.
            lineup.lineup_positions = [];
        }
    } else if (!Array.isArray(lineup.lineup_positions)) {
        // If it's not a string and not an array (e.g., null, undefined), default to an empty array.
        lineup.lineup_positions = [];
    }

    // --- Utility Functions ---
    const escapeHTML = str => String(str).replace(/[&<>'"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;',"'": '&#39;','"': '&quot;'}[tag] || tag));

    function createBenchPlayerItem(player) {
        const item = document.createElement('div');
        item.className = 'list-group-item d-flex justify-content-between align-items-center';
        item.dataset.playerName = player.name;
        item.innerHTML = `
            <span>${escapeHTML(player.name)} (#${escapeHTML(player.number) || 'N/A'})</span>
            <button type="button" class="btn btn-sm btn-outline-primary add-to-lineup-btn" aria-label="Add to lineup">
                <i class="bi bi-plus-lg"></i>
            </button>
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
        // Remove existing placeholders
        benchEl.querySelector('.placeholder-text')?.remove();
        orderEl.querySelector('.placeholder-text')?.remove();

        // Add placeholder to order list if empty
        if (orderEl.children.length === 0) {
            orderEl.innerHTML = `<div class="text-center p-5 text-muted fst-italic placeholder-text"><i class="bi bi-arrow-left-square" style="font-size: 2rem;"></i><p class="mt-2 mb-0">Drag or tap players from the bench to build the batting order.</p></div>`;
        }

        // Add placeholder to bench list if empty
        if (benchEl.children.length === 0) {
            benchEl.innerHTML = `<div class="text-center p-5 text-muted fst-italic placeholder-text"><i class="bi bi-check-circle" style="font-size: 2rem;"></i><p class="mt-2 mb-0">All available players are in the lineup.</p></div>`;
        }
    }

    function setupEventListeners() {
        benchEl.addEventListener('click', (event) => {
            const addButton = event.target.closest('.add-to-lineup-btn');
            if (addButton) {
                const playerItem = addButton.closest('.list-group-item');
                const playerName = playerItem.dataset.playerName;

                if (!lineup.lineup_positions.includes(playerName)) {
                    lineup.lineup_positions.push(playerName);
                    renderLineup();
                }
            }
        });

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
                lineup.lineup_positions = lineup.lineup_positions.filter(p => p !== playerName);
                renderLineup();
            }
        });
    }

    // Initial render
    renderLineup();
    setupEventListeners();

    // Destroy existing sortable instances if they exist to prevent memory leaks
    if (benchEl.sortable) benchEl.sortable.destroy();
    if (orderEl.sortable) orderEl.sortable.destroy();

    // Initialize SortableJS
    benchEl.sortable = new Sortable(benchEl, {
        group: 'lineup',
        animation: 150,
        filter: '.add-to-lineup-btn', // Prevent drag from starting on this button
        preventOnFilter: true,      // Allow default click behavior on the button
        onEnd: () => {
            lineup.lineup_positions = Array.from(orderEl.querySelectorAll('.list-group-item')).map(item => item.dataset.playerName);
            renderLineup();
        }
    });

    orderEl.sortable = new Sortable(orderEl, {
        group: 'lineup',
        handle: '.lineup-drag-handle',
        animation: 150,
        onEnd: () => {
            lineup.lineup_positions = Array.from(orderEl.querySelectorAll('.list-group-item')).map(item => item.dataset.playerName);
            renderLineup();
        }
    });
}
