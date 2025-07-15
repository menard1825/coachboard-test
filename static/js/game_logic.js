// =================================================================================
// Coach Planner - Game Management Client-Side Logic
// =================================================================================
function initializeGameManagement(gameData) {
    // --- Application State & Global Variables for this page ---

    // Safely initialize the game object first to prevent errors
    const game = gameData.game || {};
    const AppState = {
        roster: gameData.roster || [],
        lineup: gameData.lineup || { id: null, title: `Lineup for vs ${game.opponent}`, lineup_positions: [], associated_game_id: game.id },
        rotation: gameData.rotation || { id: null, title: `Rotation for vs ${game.opponent}`, innings: { '1': {} }, associated_game_id: game.id },
        game: game, // Use the safely defined game object
        currentInning: '1',
        copiedInningData: null
    };

    let sortableInstances = {};
    let assignPlayerModal;
    let addPlayerToLineupModal;

    // --- Utility Functions ---
    const escapeHTML = str => String(str).replace(/[&<>'"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;',"'": '&#39;','"': '&quot;'}[tag] || tag));
    const renderPositionSelect = (name, id, selectedVal = '', title = 'Pos', classes = 'form-select form-select-sm') => {
        const positions = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH', 'EH'];
        let optionsHtml = `<option value="" ${!selectedVal ? 'selected' : ''}>${title}</option>`;
        positions.forEach(pos => {
            optionsHtml += `<option value="${pos}" ${selectedVal === pos ? 'selected' : ''}>${pos}</option>`;
        });
        return `<select name="${name}" id="${id}" class="${classes}" title="${title}">${optionsHtml}</select>`;
    };
    const isMobile = () => window.innerWidth < 768;

    // --- Lineup Editor Functions ---
    function renderLineupEditor() {
        const bench = document.getElementById('lineup-bench');
        const order = document.getElementById('lineup-order');
        bench.innerHTML = '';
        order.innerHTML = '';

        const lineupPlayerNames = new Set((AppState.lineup.lineup_positions || []).map(p => p.name));
        
        (AppState.lineup.lineup_positions || []).forEach(spot => {
            const player = AppState.roster.find(p => p.name === spot.name);
            if (player) order.appendChild(createBattingOrderItem(player, spot.position));
        });

        if (!isMobile()) {
            AppState.roster.forEach(player => {
                if (!lineupPlayerNames.has(player.name)) {
                    const playerEl = createBenchPlayerItem(player);
                    bench.appendChild(playerEl);
                }
            });
        }
        
        initializeLineupSortables();
    }
    
    function initializeLineupSortables() {
        if(sortableInstances.lineupBench) sortableInstances.lineupBench.destroy();
        if(sortableInstances.lineupOrder) sortableInstances.lineupOrder.destroy();
        
        const order = document.getElementById('lineup-order');
        const bench = document.getElementById('lineup-bench');

        if (isMobile()) {
            sortableInstances.lineupOrder = new Sortable(order, {
                handle: '.lineup-drag-handle',
                animation: 150,
            });
        } else {
            sortableInstances.lineupBench = new Sortable(bench, {
                group: 'lineup',
                animation: 150,
            });
            sortableInstances.lineupOrder = new Sortable(order, {
                group: 'lineup',
                handle: '.lineup-drag-handle',
                animation: 150,
                onAdd: (evt) => {
                    const player = AppState.roster.find(p => p.name === evt.item.dataset.playerName);
                    if (player) evt.item.replaceWith(createBattingOrderItem(player));
                }
            });
        }
    }


    function createBenchPlayerItem(player) {
        const item = document.createElement('div');
        item.className = 'list-group-item';
        item.textContent = player.name;
        item.dataset.playerName = player.name;
        return item;
    }

    function createBattingOrderItem(player, selectedPosition = null) {
        const item = document.createElement('div');
        item.className = 'list-group-item';
        item.dataset.playerName = player.name;

        item.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <div class="d-flex align-items-center">
                    <i class="bi bi-grip-vertical lineup-drag-handle me-2" style="cursor: grab;"></i>
                    <span class="fw-bold">${escapeHTML(player.name)} (#${escapeHTML(player.number) || 'N/A'})</span>
                </div>
                <button type="button" class="btn btn-sm btn-link text-danger p-0 remove-player-btn" aria-label="Remove player">
                    <i class="bi bi-x-circle-fill" style="font-size: 1.1rem;"></i>
                </button>
            </div>
            <div class="mt-1 ps-4">
                ${renderPositionSelect('pos', '', selectedPosition || player.position1, 'Position')}
            </div>
        `;
        return item;
    };
    
    function openAddPlayerToLineupModal() {
        const modalList = document.getElementById('lineup-modal-bench-list');
        const lineupPlayerNames = new Set(
            Array.from(document.querySelectorAll('#lineup-order .list-group-item'))
                 .map(item => item.dataset.playerName)
        );

        const availablePlayers = AppState.roster.filter(p => !lineupPlayerNames.has(p.name));
        
        if (availablePlayers.length > 0) {
            modalList.innerHTML = availablePlayers.map(p => `
                <a href="#" class="list-group-item list-group-item-action" data-player-name="${escapeHTML(p.name)}">
                    ${escapeHTML(p.name)}
                </a>
            `).join('');
        } else {
            modalList.innerHTML = `<div class="list-group-item text-muted">All players are in the lineup.</div>`;
        }

        addPlayerToLineupModal.show();
    }

    // --- Rotation Editor Functions ---
    function renderRotationEditor() {
        if (!AppState.rotation) return;
        renderInningSelector();
        renderRotationDiamondAndBench();
        updatePlayingTimeSummary();
        initializeRotationSortables();
    }

    function renderInningSelector() {
        const container = document.getElementById('inning-btn-group');
        const innings = Object.keys(AppState.rotation.innings || {}).sort((a, b) => parseInt(a) - parseInt(b));
        if (innings.length === 0) { 
            AppState.rotation.innings['1'] = {};
            innings.push('1');
        }
        container.innerHTML = innings.map(inn => `
            <input type="radio" class="btn-check" name="inning-radio" id="inning-${inn}" value="${inn}" ${AppState.currentInning == inn ? 'checked' : ''}>
            <label class="btn btn-outline-primary" for="inning-${inn}">${inn}</label>
        `).join('');
        container.querySelectorAll('input[name="inning-radio"]').forEach(radio => {
            radio.addEventListener('change', (e) => {
                AppState.currentInning = e.target.value;
                renderRotationEditor();
            });
        });
    }

    function renderRotationDiamondAndBench() {
        if (!AppState.rotation) return;
        const currentInningData = AppState.rotation.innings[AppState.currentInning] || {};
        const createPlayerTag = (playerName) => `<div class="player-tag" data-player-name="${escapeHTML(playerName)}">${escapeHTML(playerName)}</div>`;

        document.querySelectorAll('.position-dropzone .player-tag').forEach(tag => tag.remove());
        for (const [pos, playerName] of Object.entries(currentInningData)) {
            const dropzoneDesktop = document.getElementById(`pos-desktop-${pos}`);
            const dropzoneMobile = document.getElementById(`pos-mobile-${pos}`);
            if (dropzoneDesktop) dropzoneDesktop.insertAdjacentHTML('beforeend', createPlayerTag(playerName));
            if (dropzoneMobile) dropzoneMobile.insertAdjacentHTML('beforeend', createPlayerTag(playerName));
        }

        const assignedPlayers = new Set(Object.values(currentInningData));
        const benchPlayers = AppState.roster.filter(p => !assignedPlayers.has(p.name));
        const benchDesktop = document.getElementById('bench-list-desktop');
        if(benchDesktop) {
            benchDesktop.innerHTML = benchPlayers.map(p => createPlayerTag(p.name)).join('');
        }
    }

    function updatePlayingTimeSummary() {
         if (!AppState.rotation) return;
        const summary = {};
        
        AppState.roster.forEach(player => {
            summary[player.name] = {
                name: player.name,
                inningsOnField: 0,
                inningsOnBench: 0,
                positions: new Set()
            };
        });

        const innings = Object.keys(AppState.rotation.innings || {});

        innings.forEach(inningNum => {
            const inningPositions = AppState.rotation.innings[inningNum] || {};
            const playersOnFieldThisInning = new Set(Object.values(inningPositions));

            AppState.roster.forEach(player => {
                if (playersOnFieldThisInning.has(player.name)) {
                    if (summary[player.name]) summary[player.name].inningsOnField++;
                } else {
                    if (summary[player.name]) summary[player.name].inningsOnBench++;
                }
            });

            for (const [position, playerName] of Object.entries(inningPositions)) {
                if (playerName && summary[playerName]) {
                    summary[playerName].positions.add(position);
                }
            }
        });

        let tableHtml = `<div class="table-responsive"><table class="table table-sm table-striped table-bordered"><thead class="table-light"><tr><th>Player</th><th>Field</th><th>Bench</th><th>Positions</th></tr></thead><tbody>`;
        const sortedPlayerNames = AppState.roster.map(p => p.name).sort();

        for (const playerName of sortedPlayerNames) {
            const data = summary[playerName];
            if (!data) continue;
            const positions = Array.from(data.positions).join(', ');
            tableHtml += `<tr><td><strong>${playerName}</strong></td><td>${data.inningsOnField}</td><td>${data.inningsOnBench}</td><td>${positions || 'N/A'}</td></tr>`;
        }

        tableHtml += `</tbody></table></div>`;
        
        document.getElementById('summary-desktop').innerHTML = tableHtml;
        document.getElementById('summary-mobile').innerHTML = tableHtml;
    }

    function initializeRotationSortables() {
        Object.values(sortableInstances).forEach(s => { if (s.destroy && s.el.id.includes('desktop')) s.destroy(); });

        const onEndHandler = () => {
            const inningData = AppState.rotation.innings[AppState.currentInning] = {};
            document.querySelectorAll('#diamond-parent-desktop .position-dropzone').forEach(dz => {
                const playerTag = dz.querySelector('.player-tag');
                if (playerTag) {
                    const position = dz.dataset.position;
                    const playerName = playerTag.dataset.playerName;
                    inningData[position] = playerName;
                }
            });
            renderRotationEditor();
        };

        const allContainers = [...document.querySelectorAll('#bench-list-desktop, #diamond-parent-desktop .position-dropzone')];
        allContainers.forEach(container => {
            sortableInstances[container.id] = new Sortable(container, {
                group: 'rotation',
                animation: 150,
                onEnd: onEndHandler,
                onMove: (evt) => {
                    if (evt.to.classList.contains('position-dropzone') && evt.to.children.length > 1 && evt.to !== evt.from) {
                        const displacedTag = evt.to.querySelector('.player-tag');
                        if (displacedTag) evt.from.appendChild(displacedTag);
                    }
                }
            });
        });
    }

    function exitCopyMode() {
        AppState.copiedInningData = null;
        const pasteControls = document.getElementById('inning-paste-controls');
        if (pasteControls) {
            pasteControls.classList.add('d-none');
            document.getElementById('inning-paste-checkboxes').innerHTML = '';
        }
        document.getElementById('rotation-board')?.classList.remove('copy-mode');
    }

    async function saveLineup() {
        AppState.lineup.title = document.getElementById('lineupTitle').value;
        AppState.lineup.lineup_positions = Array.from(document.querySelectorAll('#lineup-order .list-group-item')).map(item => ({
            name: item.dataset.playerName,
            position: item.querySelector('select')?.value || ''
        }));
        
        const url = AppState.lineup.id ? `/edit_lineup/${AppState.lineup.id}` : '/add_lineup';
        const payload = {
            title: AppState.lineup.title,
            lineup_data: AppState.lineup.lineup_positions,
            associated_game_id: AppState.game.id
        };

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if(!response.ok) throw new Error(result.message);
            
            window.location.reload();
        } catch (error) {
            alert('An error occurred while saving the lineup.');
            console.error(error);
        }
    }
    
    async function saveRotation() {
        const btn = document.getElementById('saveRotationBtn');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Saving...';
        
        const payload = {
            id: AppState.rotation.id,
            title: AppState.rotation.title || `Rotation for vs ${AppState.game.opponent}`,
            innings: AppState.rotation.innings,
            associated_game_id: AppState.game.id
        };

        try {
            const response = await fetch('/save_rotation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) throw new Error('Failed to save rotation.');
            const result = await response.json();
            if (result.status === 'success') {
                if (result.new_id) AppState.rotation.id = result.new_id;
                btn.textContent = 'Saved!';
                setTimeout(() => window.location.reload(), 1000);
            } else { throw new Error(result.message); }
        } catch (error) {
            alert('Error saving rotation: ' + error.message);
            btn.textContent = 'Save Failed';
        } finally {
            setTimeout(() => {
                btn.textContent = originalText;
                btn.disabled = false;
            }, 2000);
        }
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        assignPlayerModal = new bootstrap.Modal(document.getElementById('assignPlayerModal'));
        addPlayerToLineupModal = new bootstrap.Modal(document.getElementById('addPlayerToLineupModal'));
        
        document.getElementById('saveLineupBtn')?.addEventListener('click', saveLineup);
        document.getElementById('saveRotationBtn')?.addEventListener('click', saveRotation);

        document.getElementById('addPlayerToLineupBtn')?.addEventListener('click', openAddPlayerToLineupModal);
        
        document.getElementById('lineup-modal-bench-list')?.addEventListener('click', (event) => {
            event.preventDefault();
            const playerLink = event.target.closest('a');
            if (!playerLink) return;

            const playerName = playerLink.dataset.playerName;
            const player = AppState.roster.find(p => p.name === playerName);
            if (player) {
                const orderList = document.getElementById('lineup-order');
                orderList.appendChild(createBattingOrderItem(player));
                addPlayerToLineupModal.hide();
            }
        });
        
        document.getElementById('lineup-order')?.addEventListener('click', (event) => {
            const removeButton = event.target.closest('.remove-player-btn');
            if (removeButton) {
                const playerItem = removeButton.closest('.list-group-item');
                playerItem.remove();
            }
        });
        
        document.getElementById('syncRotationBtn')?.addEventListener('click', () => {
            const lineupPositions = Array.from(document.querySelectorAll('#lineup-order .list-group-item')).map(item => ({
                name: item.dataset.playerName,
                position: item.querySelector('select')?.value || ''
            }));
            const inning1Data = {};
            lineupPositions.forEach(item => {
                if(item.position && item.name) inning1Data[item.position] = item.name;
            });

            if (Object.keys(inning1Data).length > 0) {
                AppState.rotation.innings['1'] = inning1Data;
                alert('Inning 1 of the rotation has been updated with positions from the lineup. Please go to the Rotation tab and click Save to persist this change.');
                const rotationTab = new bootstrap.Tab(document.getElementById('rotation-tab'));
                rotationTab.show();
                renderRotationEditor();
            } else {
                alert('No positions set in the lineup to sync.');
            }
        });
        
        document.getElementById('deleteRotationBtn')?.addEventListener('click', () => {
            if (!AppState.rotation || !AppState.rotation.id) return;
            if (confirm(`Are you sure you want to delete this rotation? This cannot be undone.`)) {
                window.location.href = `/delete_rotation/${AppState.rotation.id}`;
            }
        });

        document.body.addEventListener('click', function(event){
            const mobileDropzone = event.target.closest('.d-lg-none .position-dropzone');
            if (mobileDropzone) {
                const position = mobileDropzone.dataset.position;
                const playerTag = mobileDropzone.querySelector('.player-tag');

                if (playerTag) { 
                    delete AppState.rotation.innings[AppState.currentInning][position];
                    renderRotationEditor();
                } else { 
                    const modalTitle = document.getElementById('assignPlayerModalTitle');
                    const modalList = document.getElementById('assignPlayerModalBenchList');

                    const assignedPlayers = new Set(Object.values(AppState.rotation.innings[AppState.currentInning] || {}));
                    const benchPlayers = AppState.roster.filter(p => !assignedPlayers.has(p.name));

                    modalTitle.textContent = `Assign to ${position}`;
                    document.getElementById('assignPlayerModal').dataset.targetPosition = position;

                    modalList.innerHTML = benchPlayers.length > 0 ? 
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
                    AppState.rotation.innings[AppState.currentInning][position] = playerName;
                    renderRotationEditor();
                    assignPlayerModal.hide();
                }
            }
        });
        
        document.getElementById('addInningBtn')?.addEventListener('click', () => {
            if(!AppState.rotation) return;
            const innings = Object.keys(AppState.rotation.innings);
            const nextInningNum = innings.length > 0 ? Math.max(...innings.map(Number)) + 1 : 1;
            AppState.rotation.innings[nextInningNum] = {};
            renderInningSelector();
        });
        document.getElementById('removeInningBtn')?.addEventListener('click', () => {
            if(!AppState.rotation) return;
            const innings = Object.keys(AppState.rotation.innings);
            if(innings.length <= 1) return alert("Cannot remove the last inning.");
            const lastInningNum = Math.max(...innings.map(Number));
            delete AppState.rotation.innings[lastInningNum];
            if(AppState.currentInning == lastInningNum) {
                AppState.currentInning = Math.max(...Object.keys(AppState.rotation.innings).map(Number));
            }
            renderRotationEditor();
        });
        document.getElementById('copyInningBtn')?.addEventListener('click', () => {
            if (!AppState.rotation || !AppState.currentInning) return;
            AppState.copiedInningData = { ...AppState.rotation.innings[AppState.currentInning] };
            document.getElementById('inning-paste-controls').classList.remove('d-none');
            document.getElementById('rotation-board').classList.add('copy-mode');
            const pasteCheckboxes = document.getElementById('inning-paste-checkboxes');
            const allInnings = Object.keys(AppState.rotation.innings);
            pasteCheckboxes.innerHTML = allInnings
                .filter(inn => inn != AppState.currentInning)
                .map(inn => `
                    <div class="form-check form-check-inline">
                        <input class="form-check-input" type="checkbox" value="${inn}" id="paste-check-${inn}">
                        <label class="form-check-label" for="paste-check-${inn}">${inn}</label>
                    </div>
                `).join('');
        });
        document.getElementById('pasteToSelectedBtn')?.addEventListener('click', () => {
            if (!AppState.copiedInningData) return;
            const selectedInnings = Array.from(document.querySelectorAll('#inning-paste-checkboxes input:checked')).map(cb => cb.value);
            if (selectedInnings.length === 0) return alert('Please select at least one inning to paste to.');
            selectedInnings.forEach(inn => {
                AppState.rotation.innings[inn] = { ...AppState.copiedInningData };
            });
            exitCopyMode();
            updatePlayingTimeSummary();
        });
        document.getElementById('cancelPasteBtn')?.addEventListener('click', exitCopyMode);
    }

    // --- Initial Page Render ---
    renderLineupEditor();
    renderRotationEditor();
    setupEventListeners();
}