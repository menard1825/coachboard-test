// static/js/lineup_editor.js

/**
 * NEW: A debounce function to delay execution.
 * This prevents the save function from being called on every single change,
 * instead waiting for a pause in user activity.
 * @param {Function} func The function to debounce.
 * @param {number} delay The delay in milliseconds.
 * @returns {Function} The debounced function.
 */
function debounce(func, delay) {
    let timeout;
    return function(...args) {
        const context = this;
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(context, args), delay);
    };
}


function initializeLineupEditor(options) {
    const {
        roster,
        lineup,
        benchEl,
        orderEl
    } = options;

    // NEW: State object to manage lineup data and save status
    const state = {
        lineupData: lineup,
        hasUnsavedChanges: false
    };

    if (typeof state.lineupData.lineup_positions === 'string') {
        try {
            state.lineupData.lineup_positions = JSON.parse(state.lineupData.lineup_positions);
            if (!Array.isArray(state.lineupData.lineup_positions)) {
                state.lineupData.lineup_positions = [];
            }
        } catch (e) {
            console.error("Error parsing lineup_positions JSON:", e);
            state.lineupData.lineup_positions = [];
        }
    } else if (!Array.isArray(state.lineupData.lineup_positions)) {
        state.lineupData.lineup_positions = [];
    }

    // --- Utility Functions ---
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

    // NEW: Auto-saving logic
    const saveLineup = async (isManualSave = false) => {
        const btn = document.getElementById('saveLineupBtn');
        if (!btn) return;

        const timestampEl = document.getElementById('lineup-save-timestamp');
        if (timestampEl) timestampEl.textContent = ''; // Clear timestamp on new save attempt

        // If this is a manual save from a "Save Failed" state, allow it. Otherwise, if there are no changes, do nothing.
        if (!state.hasUnsavedChanges && !btn.classList.contains('btn-danger')) return;

        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span>Saving...`;
        btn.classList.remove('btn-success', 'btn-danger');

        const lineupId = document.getElementById('lineupId').value;
        const title = document.getElementById('lineupTitle').value;
        const lineup_positions = Array.from(orderEl.querySelectorAll('.list-group-item')).map(item => item.dataset.playerName);

        state.lineupData.title = title;
        state.lineupData.lineup_positions = lineup_positions;

        const url = lineupId ? `/edit_lineup/${lineupId}` : '/add_lineup';
        const payload = {
            title: title,
            lineup_data: lineup_positions,
            // Determine if it's for a game or a template
            associated_game_id: new URL(window.location.href).pathname.startsWith('/game/') ? state.lineupData.associated_game_id : null
        };

        try {
            const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            const result = await response.json();
            if (!response.ok) throw new Error(result.message);

            if (result.new_id) {
                state.lineupData.id = result.new_id;
                document.getElementById('lineupId').value = result.new_id;
            }

            state.hasUnsavedChanges = false;
            btn.innerHTML = `<i class="bi bi-check-circle-fill me-1"></i> Saved`;
            btn.classList.add('btn-success');

            if (timestampEl && result.last_updated) {
                timestampEl.textContent = `Last saved: ${result.last_updated}`;
            }

            // If it was a manual save, close the modal after success
            if(isManualSave) {
                setTimeout(() => bootstrap.Modal.getInstance(document.getElementById('lineupEditorModal')).hide(), 1000);
            }

        } catch (error) {
            state.hasUnsavedChanges = true;
            btn.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-1"></i> Save Failed`;
            btn.classList.add('btn-danger');
            alert(`Error saving lineup: ${error.message}. Your changes are still here. Please try saving again.`);
        } finally {
            btn.disabled = false;
        }
    };

    const debouncedSave = debounce(() => saveLineup(false), 2000);

    // NEW: Function to trigger a change
    function handleContentChange() {
        state.hasUnsavedChanges = true;
        const saveBtn = document.getElementById('saveLineupBtn');
        saveBtn.innerHTML = 'Save Lineup';
        saveBtn.classList.remove('btn-success', 'btn-danger');
        debouncedSave();
    }

    function renderLineup() {
        benchEl.innerHTML = '';
        orderEl.innerHTML = '';

        const lineupPlayerNames = new Set(state.lineupData.lineup_positions || []);

        roster.forEach(player => {
            if (!lineupPlayerNames.has(player.name)) {
                benchEl.appendChild(createBenchPlayerItem(player));
            }
        });

        (state.lineupData.lineup_positions || []).forEach(playerName => {
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
        // Listen for changes on the title input
        document.getElementById('lineupTitle').addEventListener('input', handleContentChange);

        orderEl.addEventListener('click', (event) => {
            const playerItem = event.target.closest('.list-group-item');
            if (!playerItem) return;

            const index = Array.from(orderEl.children).indexOf(playerItem);

            if (event.target.closest('.move-up-btn')) {
                if (index > 0) {
                    [state.lineupData.lineup_positions[index], state.lineupData.lineup_positions[index - 1]] = [state.lineupData.lineup_positions[index - 1], state.lineupData.lineup_positions[index]];
                }
            } else if (event.target.closest('.move-down-btn')) {
                if (index < state.lineupData.lineup_positions.length - 1) {
                    [state.lineupData.lineup_positions[index], state.lineupData.lineup_positions[index + 1]] = [state.lineupData.lineup_positions[index + 1], state.lineupData.lineup_positions[index]];
                }
            } else if (event.target.closest('.remove-player-btn')) {
                state.lineupData.lineup_positions.splice(index, 1);
            } else {
                return; // No relevant button was clicked
            }

            handleContentChange();
            renderLineup();
        });

        // Manual save button
        document.getElementById('saveLineupBtn').addEventListener('click', () => saveLineup(true));

        // Safeguard for leaving the page
        const modal = document.getElementById('lineupEditorModal');
        modal.addEventListener('hide.bs.modal', (event) => {
            if (state.hasUnsavedChanges) {
                if (!confirm('You have unsaved changes. Are you sure you want to close?')) {
                    event.preventDefault();
                }
            }
        });
    }

    renderLineup();
    setupEventListeners();

    if (benchEl.sortable) benchEl.sortable.destroy();
    if (orderEl.sortable) orderEl.sortable.destroy();

    let ghostPositionEl = null;

    const onSortEnd = (evt) => {
        handleContentChange();
        renderLineup();
        benchEl.scrollTop = 0;
        orderEl.scrollTop = 0;
    };

    const sortableOptions = {
        group: 'lineup',
        animation: 150,
        ghostClass: 'lineup-ghost',
        onEnd: onSortEnd,
    };

    benchEl.sortable = new Sortable(benchEl, sortableOptions);
    orderEl.sortable = new Sortable(orderEl, { ...sortableOptions, handle: '.lineup-drag-handle' });
}