// static/js/lineup_editor.js

let lineupEditorModal;

async function saveLineupTemplate() { // RENAMED FROM saveLineup
    const btn = document.getElementById('saveLineupBtn');
    const modal = btn.closest('.modal');
    const lineupId = modal.querySelector('#lineupId').value;
    const title = modal.querySelector('#lineupTitle').value;
    const lineup_positions = Array.from(modal.querySelectorAll('#lineup-order .list-group-item')).map(item => item.dataset.playerName);
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    const url = lineupId ? `/edit_lineup/${lineupId}` : '/add_lineup';
    const payload = {
        title: title,
        lineup_data: lineup_positions,
        // This modal is for creating unassigned lineup templates, so game ID is always null.
        // Lineups are associated with games from the game-specific management page.
        associated_game_id: null
    };

    btn.disabled = true;
    btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Saving...`;

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken
            },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.message);

        lineupEditorModal.hide();

    } catch (error) {
        alert('Error saving lineup: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = 'Save';
    }
}

function openLineupEditor(lineupData, rosterData) {
    const modal = document.getElementById('lineupEditorModal');
    const currentLineup = lineupData || { id: null, title: 'New Unassigned Lineup', lineup_positions: [] };

    modal.querySelector('#lineupId').value = currentLineup.id;
    modal.querySelector('#lineupTitle').value = currentLineup.title;

    initializeLineupEditor({
        roster: rosterData,
        lineup: currentLineup,
        benchEl: modal.querySelector('#lineup-bench'),
        orderEl: modal.querySelector('#lineup-order')
    });
}


// Using a global function for now, assuming this file is loaded via a script tag.
// A more robust solution might use ES6 modules.
function initializeLineupEditor(options) {
    const {
        roster,
        lineup,
        benchEl,
        orderEl
    } = options;

    if (typeof lineup.lineup_positions === 'string') {
        try {
            lineup.lineup_positions = JSON.parse(lineup.lineup_positions);
        } catch (e) {
            console.error("Error parsing lineup_positions JSON:", e);
            lineup.lineup_positions = []; // Default to empty array on failure
        }
    }
    // Ensure it's an array, even if it was null or undefined initially
    if (!Array.isArray(lineup.lineup_positions)) {
        lineup.lineup_positions = [];
    }

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
        // Remove existing placeholders
        benchEl.querySelector('.placeholder-text')?.remove();
        orderEl.querySelector('.placeholder-text')?.remove();

        // Add placeholder to order list if empty
        if (orderEl.children.length === 0) {
            orderEl.innerHTML = `<div class="text-center p-5 text-muted fst-italic placeholder-text"><i class="bi bi-people" style="font-size: 2rem;"></i><p class="mt-2 mb-0">Drag players from the bench to build the batting order.</p></div>`;
        }

        // Add placeholder to bench list if empty
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
                    // Update state
                    lineup.lineup_positions = lineup.lineup_positions.filter(p => p !== playerName);

                    // Manipulate DOM directly
                    const newBenchItem = createBenchPlayerItem(player);
                    benchEl.appendChild(newBenchItem);
                    playerItem.remove();

                    updatePlaceholders();
                }
            }
        });
    }

    // Initial render
    renderLineup();
    setupEventListeners();

    // Destroy existing sortable instances if they exist to prevent memory leaks
    if (benchEl.sortable) benchEl.sortable.destroy();
    if (orderEl.sortable) orderEl.sortable.destroy();

    let ghostPositionEl = null;

    const onDragStart = (evt) => {
        document.body.classList.add('dragging-lineup-player');
    };

    const onDragMove = (evt) => {
        const ghostEl = document.querySelector('.lineup-ghost');
        if (!ghostEl) return;

        // Check if we've already modified this ghost to add our number element
        if (!ghostEl.dataset.ghostModified) {
            ghostEl.dataset.ghostModified = 'true';

            // Find the main text span to insert our number before it
            const mainContainer = ghostEl.querySelector('.d-flex.align-items-center');
            if (mainContainer) {
                ghostPositionEl = document.createElement('span');
                ghostPositionEl.className = 'ghost-position-number';

                // Insert the position number as the first element in the container
                mainContainer.insertBefore(ghostPositionEl, mainContainer.firstChild);

                // Add a class to the ghost itself to hide the default CSS counter
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
                    // This case handles dragging over an empty lineup list that has a placeholder.
                    const isOrderEmpty = orderEl.children.length === 0 || orderEl.querySelector('.placeholder-text');
                    if (isOrderEmpty) {
                        ghostPositionEl.textContent = '1.\u00A0';
                    } else {
                        // If the index is invalid for any other reason, hide the number.
                        ghostPositionEl.textContent = '';
                    }
                }
            } else {
                // We are over the bench or somewhere else, so hide the position.
                ghostPositionEl.textContent = '';
            }
        }
    };

    const onSortEnd = (evt) => {
        document.body.classList.remove('dragging-lineup-player');
        ghostPositionEl = null; // Clear reference

        // Update the lineup from the DOM
        lineup.lineup_positions = Array.from(orderEl.querySelectorAll('.list-group-item')).map(item => item.dataset.playerName);

        // Full re-render to ensure consistency
        renderLineup();

        // Reset scroll positions
        benchEl.scrollTop = 0;
        orderEl.scrollTop = 0;
    };

    const sortableOptions = {
        group: 'lineup',
        animation: 150,
        ghostClass: 'lineup-ghost', // Custom ghost class
        onStart: onDragStart,
        onMove: onDragMove,
        onEnd: onSortEnd,
    };

    // Initialize SortableJS
    benchEl.sortable = new Sortable(benchEl, sortableOptions);

    orderEl.sortable = new Sortable(orderEl, {
        ...sortableOptions,
        handle: '.lineup-drag-handle',
    });
}

