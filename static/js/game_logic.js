// =================================================================================
// Coach Planner - Game Management Client-Side Logic (REFACTORED)
// =================================================================================

// This script is now fully self-contained and does not use a global AppState.
const escapeHTML = str => String(str).replace(/[&<>'"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;',"'": '&#39;','"': '&quot;'}[tag] || tag));

function initializeGameManagement(gameData) {

    // --- Page-Specific State ---
    // All data for this page is stored in a local 'state' object.
    const state = {
        roster: (gameData.roster || []).filter(p => !(gameData.absent_player_ids || []).includes(p.id)),
        lineup: gameData.lineup || { id: null, title: `Lineup for vs ${gameData.game.opponent}`, lineup_positions: [], associated_game_id: gameData.game.id },
        rotation: gameData.rotation || { id: null, title: `Rotation for vs ${gameData.game.opponent}`, innings: { '1': {} }, associated_game_id: gameData.game.id },
        game: gameData.game,
        currentInning: '1',
        copiedInningData: null,
        sortableInstances: {}
    };

    let assignPlayerModal;
    let lineupEditorModal;

    // --- Utility Functions ---
    function updateLineupPlaceholders() {
        const bench = document.getElementById('lineup-bench');
        const order = document.getElementById('lineup-order');
        if (!bench || !order) return;
        bench.querySelector('.placeholder-text')?.remove();
        order.querySelector('.placeholder-text')?.remove();
        if (order.children.length === 0) {
            order.innerHTML = `<div class="text-center p-5 text-muted fst-italic placeholder-text"><i class="bi bi-arrow-left-square" style="font-size: 2rem;"></i><p class="mt-2 mb-0">Drag players from the bench to build your batting order.</p></div>`;
        }
        if (bench.children.length === 0) {
            bench.innerHTML = `<div class="text-center p-5 text-muted fst-italic placeholder-text"><i class="bi bi-check-circle" style="font-size: 2rem;"></i><p class="mt-2 mb-0">All available players are in the lineup.</p></div>`;
        }
    }

    // --- Lineup Editor Functions ---
    function renderLineupEditor() {
        const bench = document.getElementById('lineup-bench');
        const order = document.getElementById('lineup-order');
        if (!bench || !order) return;
        bench.innerHTML = '';
        order.innerHTML = '';
        const lineupPlayerNames = new Set(state.lineup.lineup_positions || []);
        (state.lineup.lineup_positions || []).forEach(playerName => {
            const player = state.roster.find(p => p.name === playerName);
            if (player) order.appendChild(createBattingOrderItem(player));
        });
        state.roster.forEach(player => {
            if (!lineupPlayerNames.has(player.name)) {
                bench.appendChild(createBenchPlayerItem(player));
            }
        });
        initializeLineupSortables();
        updateLineupPlaceholders();
    }
    
    function initializeLineupSortables() {
        if(state.sortableInstances.lineupBench) state.sortableInstances.lineupBench.destroy();
        if(state.sortableInstances.lineupOrder) state.sortableInstances.lineupOrder.destroy();
        const order = document.getElementById('lineup-order');
        const bench = document.getElementById('lineup-bench');
        if (!bench || !order) return;
        const onEndHandler = () => updateLineupPlaceholders();
        state.sortableInstances.lineupBench = new Sortable(bench, {
            group: 'lineup', animation: 150,
            onAdd: (evt) => {
                bench.querySelector('.placeholder-text')?.remove();
                const player = state.roster.find(p => p.name === evt.item.dataset.playerName);
                if (player) evt.item.replaceWith(createBenchPlayerItem(player));
            },
            onEnd: onEndHandler
        });
        state.sortableInstances.lineupOrder = new Sortable(order, {
            group: 'lineup', handle: '.lineup-drag-handle', animation: 150,
            onAdd: (evt) => {
                order.querySelector('.placeholder-text')?.remove();
                const player = state.roster.find(p => p.name === evt.item.dataset.playerName);
                if (player) evt.item.replaceWith(createBattingOrderItem(player));
            },
            onEnd: onEndHandler
        });
    }

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
    };
    
    // --- Rotation Editor Functions ---
    function renderRotationEditor() {
        if (!state.rotation) return;
        renderInningSelector();
        renderRotationDiamondAndBench();
        updatePlayingTimeSummary();
        initializeRotationSortables();
    }

    function renderInningSelector() {
        const container = document.getElementById('inning-btn-group');
        const innings = Object.keys(state.rotation.innings || {}).sort((a, b) => parseInt(a) - parseInt(b));
        if (innings.length === 0) { 
            state.rotation.innings['1'] = {};
            innings.push('1');
        }
        container.innerHTML = innings.map(inn => `
            <input type="radio" class="btn-check" name="inning-radio" id="inning-${inn}" value="${inn}" ${state.currentInning == inn ? 'checked' : ''}>
            <label class="btn btn-outline-primary" for="inning-${inn}">${inn}</label>
        `).join('');
        container.querySelectorAll('input[name="inning-radio"]').forEach(radio => {
            radio.addEventListener('change', (e) => {
                state.currentInning = e.target.value;
                renderRotationEditor();
            });
        });
    }

    function renderRotationDiamondAndBench() {
        const currentInningData = state.rotation.innings[state.currentInning] || {};
        const createPlayerTag = (playerName) => `<div class="player-tag" data-player-name="${escapeHTML(playerName)}">${escapeHTML(playerName)}</div>`;
        document.querySelectorAll('.position-dropzone .player-tag').forEach(tag => tag.remove());
        for (const [pos, playerName] of Object.entries(currentInningData)) {
            const dropzoneDesktop = document.getElementById(`pos-desktop-${pos}`);
            const dropzoneMobile = document.getElementById(`pos-mobile-${pos}`);
            if (dropzoneDesktop) dropzoneDesktop.insertAdjacentHTML('beforeend', createPlayerTag(playerName));
            if (dropzoneMobile) dropzoneMobile.insertAdjacentHTML('beforeend', createPlayerTag(playerName));
        }
        const assignedPlayers = new Set(Object.values(currentInningData));
        const benchPlayers = state.roster.filter(p => !assignedPlayers.has(p.name));
        const benchDesktop = document.getElementById('bench-list-desktop');
        if(benchDesktop) {
            benchDesktop.innerHTML = benchPlayers.map(p => createPlayerTag(p.name)).join('');
        }
    }

    function updatePlayingTimeSummary() {
        const summary = {};
        state.roster.forEach(player => {
            summary[player.name] = { name: player.name, inningsOnField: 0, inningsOnBench: 0, positions: new Set() };
        });
        const innings = Object.keys(state.rotation.innings || {});
        innings.forEach(inningNum => {
            const inningPositions = state.rotation.innings[inningNum] || {};
            const playersOnFieldThisInning = new Set(Object.values(inningPositions));
            state.roster.forEach(player => {
                if (summary[player.name]) {
                    playersOnFieldThisInning.has(player.name) ? summary[player.name].inningsOnField++ : summary[player.name].inningsOnBench++;
                }
            });
            for (const [position, playerName] of Object.entries(inningPositions)) {
                if (playerName && summary[playerName]) summary[playerName].positions.add(position);
            }
        });
        let tableHtml = `<div class="table-responsive"><table class="table table-sm table-striped table-bordered"><thead class="table-light"><tr><th>Player</th><th>Field</th><th>Bench</th><th>Positions</th></tr></thead><tbody>`;
        const sortedPlayerNames = state.roster.map(p => p.name).sort();
        for (const playerName of sortedPlayerNames) {
            const data = summary[playerName];
            if (!data) continue;
            tableHtml += `<tr><td><strong>${playerName}</strong></td><td>${data.inningsOnField}</td><td>${data.inningsOnBench}</td><td>${Array.from(data.positions).join(', ') || 'N/A'}</td></tr>`;
        }
        tableHtml += `</tbody></table></div>`;
        const summaryDesktop = document.getElementById('summary-desktop');
        const summaryMobile = document.getElementById('summary-mobile');
        if (summaryDesktop) summaryDesktop.innerHTML = tableHtml;
        if (summaryMobile) summaryMobile.innerHTML = tableHtml;
    }

    function initializeRotationSortables() {
        Object.values(state.sortableInstances).forEach(s => { if (s.destroy) s.destroy(); });
        state.sortableInstances = {};
        const onEndHandler = () => {
            const inningData = state.rotation.innings[state.currentInning] = {};
            document.querySelectorAll('#diamond-parent-desktop .position-dropzone').forEach(dz => {
                const playerTag = dz.querySelector('.player-tag');
                if (playerTag) {
                    inningData[dz.dataset.position] = playerTag.dataset.playerName;
                }
            });
            renderRotationEditor();
        };
        const allContainers = [...document.querySelectorAll('#bench-list-desktop, #diamond-parent-desktop .position-dropzone')];
        allContainers.forEach(container => {
            state.sortableInstances[container.id] = new Sortable(container, {
                group: 'rotation', animation: 150, onEnd: onEndHandler,
                onMove: (evt) => {
                    if (evt.to.classList.contains('position-dropzone') && evt.to.children.length > 1 && evt.to !== evt.from) {
                        evt.from.appendChild(evt.to.querySelector('.player-tag'));
                    }
                }
            });
        });
    }

    function exitCopyMode() {
        state.copiedInningData = null;
        const pasteControls = document.getElementById('inning-paste-controls');
        if (pasteControls) {
            pasteControls.classList.add('d-none');
            document.getElementById('inning-paste-checkboxes').innerHTML = '';
        }
        document.getElementById('rotation-board')?.classList.remove('copy-mode');
    }

    async function saveLineup() {
        const btn = document.getElementById('saveLineupBtn');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Saving...`;
        state.lineup.title = document.getElementById('lineupTitle').value;
        state.lineup.lineup_positions = Array.from(document.querySelectorAll('#lineup-order .list-group-item')).map(item => item.dataset.playerName);
        const url = state.lineup.id ? `/edit_lineup/${state.lineup.id}` : '/add_lineup';
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: state.lineup.title,
                    lineup_data: state.lineup.lineup_positions,
                    associated_game_id: state.game.id
                })
            });
            const result = await response.json();
            if(!response.ok) throw new Error(result.message);
            if (result.new_id) state.lineup.id = result.new_id;
            lineupEditorModal.hide();
            window.location.reload();
        } catch (error) {
            alert('Error saving lineup: ' + error.message);
            btn.disabled = false;
            btn.innerHTML = 'Save Lineup';
        }
    }
    
    async function saveRotation() {
        const btn = document.getElementById('saveRotationBtn');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Saving...';
        const payload = {
            id: state.rotation.id,
            title: state.rotation.title || `Rotation for vs ${state.game.opponent}`,
            innings: state.rotation.innings,
            associated_game_id: state.game.id
        };
        try {
            const response = await fetch('/save_rotation', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            if (!response.ok) throw new Error('Failed to save rotation.');
            const result = await response.json();
            if (result.status === 'success') {
                if (result.new_id) state.rotation.id = result.new_id;
                btn.textContent = 'Saved!';
                renderRotationEditor();
            } else { throw new Error(result.message); }
        } catch (error) {
            alert('Error saving rotation: ' + error.message);
            btn.textContent = 'Save Failed';
        } finally {
            setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 2000);
        }
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        assignPlayerModal = new bootstrap.Modal(document.getElementById('assignPlayerModal'));
        lineupEditorModal = new bootstrap.Modal(document.getElementById('lineupEditorModal'));
        document.getElementById('saveLineupBtn')?.addEventListener('click', saveLineup);
        document.getElementById('saveRotationBtn')?.addEventListener('click', saveRotation);
        document.getElementById('lineupEditorModal')?.addEventListener('shown.bs.modal', renderLineupEditor);

        document.getElementById('lineup-bench')?.addEventListener('click', (event) => {
            const addButton = event.target.closest('.add-to-lineup-btn');
            if (addButton) {
                const playerItem = addButton.closest('.list-group-item');
                const playerName = playerItem.dataset.playerName;
                const player = state.roster.find(p => p.name === playerName);

                if (player) {
                    // Add to state
                    state.lineup.lineup_positions.push(player.name);

                    // Remove from bench view
                    playerItem.remove();

                    // Add to lineup view
                    const lineupOrder = document.getElementById('lineup-order');
                    lineupOrder.appendChild(createBattingOrderItem(player));

                    // Update placeholders
                    updateLineupPlaceholders();
                }
            }
        });

        document.getElementById('lineup-order')?.addEventListener('click', (event) => {
            const moveUpButton = event.target.closest('.move-up-btn');
            const moveDownButton = event.target.closest('.move-down-btn');
            const removeButton = event.target.closest('.remove-player-btn');

            if (moveUpButton) {
                const playerItem = moveUpButton.closest('.list-group-item');
                if (playerItem.previousElementSibling) {
                    playerItem.parentNode.insertBefore(playerItem, playerItem.previousElementSibling);
                }
            } else if (moveDownButton) {
                const playerItem = moveDownButton.closest('.list-group-item');
                if (playerItem.nextElementSibling) {
                    playerItem.parentNode.insertBefore(playerItem.nextElementSibling, playerItem);
                }
            } else if (removeButton) {
                const playerItem = removeButton.closest('.list-group-item');
                playerItem.remove();
                const player = state.roster.find(p => p.name === playerItem.dataset.playerName);
                if(player) document.getElementById('lineup-bench').appendChild(createBenchPlayerItem(player));
                updateLineupPlaceholders();
            }
        });
        document.getElementById('deleteRotationBtn')?.addEventListener('click', () => {
            if (state.rotation?.id && confirm(`Are you sure you want to delete this rotation?`)) {
                window.location.href = `/delete_rotation/${state.rotation.id}`;
            }
        });
        document.body.addEventListener('click', function(event){
            const mobileDropzone = event.target.closest('.d-lg-none .position-dropzone');
            if (mobileDropzone) {
                const position = mobileDropzone.dataset.position;
                if (mobileDropzone.querySelector('.player-tag')) { 
                    delete state.rotation.innings[state.currentInning][position];
                    renderRotationEditor();
                } else { 
                    const assignedPlayers = new Set(Object.values(state.rotation.innings[state.currentInning] || {}));
                    const benchPlayers = state.roster.filter(p => !assignedPlayers.has(p.name));
                    document.getElementById('assignPlayerModalTitle').textContent = `Assign to ${position}`;
                    document.getElementById('assignPlayerModal').dataset.targetPosition = position;
                    document.getElementById('assignPlayerModalBenchList').innerHTML = benchPlayers.length > 0 ? 
                        benchPlayers.map(p => `<a href="#" class="list-group-item list-group-item-action" data-player-name="${escapeHTML(p.name)}">${escapeHTML(p.name)}</a>`).join('') :
                        `<div class="list-group-item">No players on the bench.</div>`;
                    assignPlayerModal.show();
                }
            }
            const modalPlayerLink = event.target.closest('#assignPlayerModalBenchList a');
            if (modalPlayerLink) {
                event.preventDefault();
                const playerName = modalPlayerLink.dataset.playerName;
                const position = document.getElementById('assignPlayerModal').dataset.targetPosition;
                if (playerName && position) {
                    state.rotation.innings[state.currentInning][position] = playerName;
                    renderRotationEditor();
                    assignPlayerModal.hide();
                }
            }
        });
        document.getElementById('addInningBtn')?.addEventListener('click', () => {
            if(!state.rotation) return;
            const innings = Object.keys(state.rotation.innings);
            const nextInningNum = innings.length > 0 ? Math.max(...innings.map(Number)) + 1 : 1;
            state.rotation.innings[nextInningNum] = {};
            renderInningSelector();
        });
        document.getElementById('removeInningBtn')?.addEventListener('click', () => {
            if(!state.rotation) return;
            const innings = Object.keys(state.rotation.innings);
            if(innings.length <= 1) return alert("Cannot remove the last inning.");
            const lastInningNum = Math.max(...innings.map(Number));
            delete state.rotation.innings[lastInningNum];
            if(state.currentInning == lastInningNum) {
                state.currentInning = Math.max(...Object.keys(state.rotation.innings).map(Number));
            }
            renderRotationEditor();
        });
        document.getElementById('copyInningBtn')?.addEventListener('click', () => {
            if (!state.rotation || !state.currentInning) return;
            state.copiedInningData = { ...state.rotation.innings[state.currentInning] };
            document.getElementById('inning-paste-controls').classList.remove('d-none');
            document.getElementById('rotation-board').classList.add('copy-mode');
            const pasteCheckboxes = document.getElementById('inning-paste-checkboxes');
            pasteCheckboxes.innerHTML = Object.keys(state.rotation.innings)
                .filter(inn => inn != state.currentInning)
                .map(inn => `<div class="form-check form-check-inline"><input class="form-check-input" type="checkbox" value="${inn}" id="paste-check-${inn}"><label class="form-check-label" for="paste-check-${inn}">${inn}</label></div>`).join('');
        });
        document.getElementById('pasteToSelectedBtn')?.addEventListener('click', () => {
            if (!state.copiedInningData) return;
            const selectedInnings = Array.from(document.querySelectorAll('#inning-paste-checkboxes input:checked')).map(cb => cb.value);
            if (selectedInnings.length === 0) return alert('Please select at least one inning to paste to.');
            selectedInnings.forEach(inn => {
                state.rotation.innings[inn] = { ...state.copiedInningData };
            });
            exitCopyMode();
            updatePlayingTimeSummary();
        });
        document.getElementById('cancelPasteBtn')?.addEventListener('click', exitCopyMode);
    }

    // --- Initial Page Render ---
    if(state.game) {
        renderRotationEditor();
        setupEventListeners();
    } else {
        console.error("Game data was not provided to initialize the page.");
        document.getElementById('rotation-board').innerHTML = '<div class="alert alert-danger">Could not load game data. Please go back and try again.</div>';
    }
}