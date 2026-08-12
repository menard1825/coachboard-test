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
        lineup_templates: gameData.lineup_templates || [],
        // NEW: Add rotation_templates to the state
        rotation_templates: gameData.rotation_templates || [],
        outfielder_count: gameData.outfielder_count || 3,
        currentInning: '1',
        copiedInningData: null,
        sortableInstances: {}
    };

    // ADD THIS BLOCK TO FIX THE INNINGS BUG
    if (state.rotation && typeof state.rotation.innings === 'string') {
        try {
            state.rotation.innings = JSON.parse(state.rotation.innings);
        } catch (e) {
            console.error("Error parsing rotation.innings JSON:", e);
            state.rotation.innings = { '1': {} }; // Default to a valid object on failure
        }
    }

    // Add actual live rotation state which tracks events
    state.actual_rotation = JSON.parse(JSON.stringify(state.rotation.innings)); // Deep copy to prevent reference mutation
    state.rotation_events = gameData.rotation_events || [];
    state.pitch_count_summary = gameData.pitch_count_summary || {};
    state.liveMode = state.game.is_live || false;
    state.currentInning = state.liveMode ? state.game.live_current_inning || '1' : '1';

    // Process rotation events sequentially to build the live actual_rotation state
    if (state.rotation_events.length > 0) {
        state.rotation_events.forEach(evt => {
            if (!evt.reverted) {
                state.actual_rotation[evt.inning] = evt.after_alignment;
            }
        });
    }

    let assignPlayerModal;
    let lineupEditorModal;
    let saveTemplateModal;

    // --- Rotation Editor Functions ---
    function renderRotationEditor() {
        if (!state.rotation) return;
        renderInningSelector();
        renderRotationDiamondAndBench();
        updatePlayingTimeSummary();
        renderRotationMatrix(); // NEW: Render the matrix view
        renderBenchReportMobile(); // NEW: Render the mobile bench report
        renderBenchReportDesktop(); // NEW: Render the desktop bench report
        renderRotationSummaryMobile(); // NEW: Render mobile summary

        if (!state.liveMode) {
            initializeRotationSortables();
        }
    }

    function renderInningSelector() {
        const container = document.getElementById('inning-btn-group');
        const innings = Object.keys(state.rotation.innings || {}).sort((a, b) => parseFloat(a) - parseFloat(b));
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

        // Note: The original createPlayerTag is now modified to accept a player object
        // MODIFIED: Only show position if on bench (or general list). If on field, the position is implied by the dropzone.
        // We will pass an optional 'isOnField' flag.
        const createPlayerTag = (player, isOnField = false) => {
            let primaryPos = '';
            // Only show the primary position label if they are NOT on the field (i.e. on the bench or being dragged from bench)
            // Or if we just want to be explicit. The user request is to NOT show it when they are playing a different position.
            // Simplest logic: If isOnField is true, don't show the suffix.
            if (!isOnField && player.position1) {
                primaryPos = ` (${escapeHTML(player.position1)})`;
            }
            return `<div class="player-tag" data-player-name="${escapeHTML(player.name)}">${escapeHTML(player.name)}${primaryPos}</div>`;
        };

        // Modify the rendering of player tags on the diamond to pass the full player object
        document.querySelectorAll('.position-dropzone .player-tag').forEach(tag => tag.remove());
        for (const [pos, playerName] of Object.entries(currentInningData)) {
            const player = state.roster.find(p => p.name === playerName);
            if (player) {
                const dropzoneDesktop = document.getElementById(`pos-desktop-${pos}`);
                const dropzoneMobile = document.getElementById(`pos-mobile-${pos}`);
                // Pass true for isOnField
                if (dropzoneDesktop) dropzoneDesktop.insertAdjacentHTML('beforeend', createPlayerTag(player, true));
                if (dropzoneMobile) dropzoneMobile.insertAdjacentHTML('beforeend', createPlayerTag(player, true));
            }
        }

        // Update the bench rendering logic
        const assignedPlayers = new Set(Object.values(currentInningData));
        const benchPlayers = state.roster.filter(p => !assignedPlayers.has(p.name));
        const benchDesktop = document.getElementById('bench-list-desktop');
        if(benchDesktop) {
            // Pass the full player object to the updated createPlayerTag function
            // Pass false for isOnField (default)
            benchDesktop.innerHTML = benchPlayers.map(p => createPlayerTag(p, false)).join('');
        }

        // NEW: Update Mobile Bench View
        const benchMobile = document.getElementById('bench-list-mobile');
        if (benchMobile) {
            document.querySelectorAll('.current-inning-display').forEach(el => el.textContent = state.currentInning);

            if (benchPlayers.length > 0) {
                 benchMobile.innerHTML = benchPlayers.map(p =>
                    `<span class="badge bg-secondary fw-normal p-2 border">${escapeHTML(p.name)}</span>`
                 ).join('');
            } else {
                benchMobile.innerHTML = '<span class="text-muted fst-italic">No one on bench.</span>';
            }
        }

        applyOutOfPositionIndicators(); // Add this line at the end
    }

    // NEW: Function to render the Rotation Matrix
    function renderRotationMatrix() {
        const matrixContainer = document.getElementById('rotation-matrix-container');
        if (!matrixContainer) return;

        const inningsSource = state.liveMode ? state.actual_rotation : state.rotation.innings;
        const innings = Object.keys(inningsSource || {}).sort((a, b) => parseFloat(a) - parseFloat(b));
        if (innings.length === 0) {
             matrixContainer.innerHTML = '<p class="text-muted p-2">No innings added yet.</p>';
             return;
        }

        let html = '<table class="table table-bordered table-sm text-center mb-0" style="table-layout: fixed; min-width: 800px;">';

        // Header Row
        html += '<thead class="table-light"><tr><th style="width: 150px; text-align: left;">Player</th>';
        innings.forEach(inn => {
            const isCurrent = inn === state.currentInning;
            html += `<th class="${isCurrent ? 'table-primary border-primary' : ''}">Inning ${inn}</th>`;
        });
        html += '</tr></thead><tbody>';

        // Player Rows
        // Sort players alphabetically
        const sortedRoster = [...state.roster].sort((a, b) => a.name.localeCompare(b.name));

        sortedRoster.forEach(player => {
            html += `<tr><td style="text-align: left; font-weight: 500;">${escapeHTML(player.name)}</td>`;

            innings.forEach(inn => {
                const inningData = inningsSource[inn] || {};
                // Find position for this player in this inning
                // inningData format: { "P": "Player Name", "C": "Player Name", ... }
                let position = null;
                for (const [pos, name] of Object.entries(inningData)) {
                    if (name === player.name) {
                        position = pos;
                        break;
                    }
                }

                if (position) {
                    html += `<td><span class="badge bg-success bg-opacity-10 text-success border border-success w-100">${position}</span></td>`;
                } else {
                    html += `<td class="bg-light"><span class="text-muted small">BENCH</span></td>`;
                }
            });
            html += '</tr>';
        });

        html += '</tbody></table>';
        matrixContainer.innerHTML = html;
    }

    // NEW: Function to render the Bench Report for Mobile
    function renderBenchReportMobile() {
        const container = document.getElementById('bench-report-mobile-container');
        if (!container) return;
        renderBenchReportGeneric(container);
    }

    // NEW: Function to render the Bench Report for Desktop
    function renderBenchReportDesktop() {
        const container = document.getElementById('bench-report-desktop-container');
        if (!container) return;
        renderBenchReportGeneric(container);
    }

    // Shared logic for rendering bench reports
    function renderBenchReportGeneric(container) {
        const inningsSource = state.liveMode ? state.actual_rotation : state.rotation.innings;
        const innings = Object.keys(inningsSource || {}).sort((a, b) => parseFloat(a) - parseFloat(b));
        if (innings.length === 0) {
            container.innerHTML = '<div class="p-3 text-muted">No innings data available.</div>';
            return;
        }

        let html = '<div class="list-group list-group-flush">';

        innings.forEach(inn => {
            const inningData = inningsSource[inn] || {};
            const assignedPlayers = new Set(Object.values(inningData));
            const benchPlayers = state.roster.filter(p => !assignedPlayers.has(p.name));

            html += `<div class="list-group-item">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span class="fw-bold">Inning ${inn}</span>
                    <span class="badge bg-secondary rounded-pill">${benchPlayers.length} Sitting</span>
                </div>
                <div class="d-flex flex-wrap gap-1">`;

            if (benchPlayers.length > 0) {
                benchPlayers.forEach(p => {
                    html += `<span class="badge bg-light text-dark border">${escapeHTML(p.name)}</span>`;
                });
            } else {
                html += `<span class="text-muted small fst-italic">All players on field</span>`;
            }

            html += `</div></div>`;
        });

        html += '</div>';
        container.innerHTML = html;
    }

    // NEW: Function to render the Player Rotation Summary for Mobile
    function renderRotationSummaryMobile() {
        const container = document.getElementById('rotation-summary-mobile-container');
        if (!container) return;

        const innings = Object.keys(state.rotation.innings || {}).sort((a, b) => parseFloat(a) - parseFloat(b));
        const sortedRoster = [...state.roster].sort((a, b) => a.name.localeCompare(b.name));

        if (innings.length === 0) {
             container.innerHTML = '<div class="p-3 text-muted">No innings data available.</div>';
             return;
        }

        let html = '<div class="list-group list-group-flush">';

        sortedRoster.forEach(player => {
            html += `<div class="list-group-item">
                <div class="fw-bold mb-1">${escapeHTML(player.name)}</div>
                <div class="d-flex flex-wrap gap-1">`;

            innings.forEach(inn => {
                const inningData = state.rotation.innings[inn] || {};
                let position = null;
                for (const [pos, name] of Object.entries(inningData)) {
                    if (name === player.name) {
                        position = pos;
                        break;
                    }
                }

                if (position) {
                    html += `<span class="badge bg-success bg-opacity-10 text-success border border-success" title="Inning ${inn}: ${position}">${inn}: ${position}</span>`;
                } else {
                     html += `<span class="badge bg-light text-muted border" title="Inning ${inn}: Bench">${inn}: BN</span>`;
                }
            });

            html += `</div></div>`;
        });
        html += '</div>';
        container.innerHTML = html;
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
            triggerAutosave();
        };
        const allContainers = [...document.querySelectorAll('#bench-list-desktop, #diamond-parent-desktop .position-dropzone')];
        allContainers.forEach(container => {
            state.sortableInstances[container.id] = new Sortable(container, {
                group: 'rotation',
                animation: 150,
                delay: 150,
                delayOnTouchOnly: true,
                touchStartThreshold: 5,
                onEnd: onEndHandler,
                onMove: (evt) => {
                    if (evt.to.classList.contains('position-dropzone') && evt.to.children.length > 1 && evt.to !== evt.from) {
                        evt.from.appendChild(evt.to.querySelector('.player-tag'));
                    }
                }
            });
        });
    }

function applyOutOfPositionIndicators() {
    document.querySelectorAll('.position-dropzone .player-tag').forEach(tag => {
        const playerName = tag.dataset.playerName;
        const position = tag.closest('.position-dropzone').dataset.position;
        const player = state.roster.find(p => p.name === playerName);

        // First, remove any existing position classes to reset the state
        tag.classList.remove('natural-position', 'secondary-position');

        if (player && position) {
            const primaryPos = player.position1;
            const secondaryPositions = [player.position2, player.position3];

            if (position === primaryPos) {
                tag.classList.add('natural-position');
            } else if (secondaryPositions.includes(position)) {
                tag.classList.add('secondary-position');
            }
            // If it's not in any of the three, it will just have the default color
        }
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

    function printLineupCard() {
        const printWindow = window.open('', '_blank');
        const lineupRows = (state.lineup.lineup_positions || []).map((p, i) => `<tr><td>${i+1}</td><td style="text-align: left; padding-left: 10px;">${escapeHTML(p)}</td></tr>`).join('');

        // Rotation Grid
        const innings = Object.keys(state.rotation.innings || {}).sort((a,b) => parseFloat(a)-parseFloat(b));
        const header = innings.map(inn => `<th>${inn}</th>`).join('');

        const sortedRoster = [...state.roster].sort((a,b) => a.name.localeCompare(b.name));
        const rotationRows = sortedRoster.map(p => {
            const cells = innings.map(inn => {
                const innData = state.rotation.innings[inn] || {};
                let position = '';
                for(const [pos, name] of Object.entries(innData)) {
                    if(name === p.name) { position = pos; break; }
                }
                return position ? `<td><strong>${position}</strong></td>` : `<td style="color: #ccc;">-</td>`;
            }).join('');
            return `<tr><td style="text-align: left; padding-left: 10px;">${escapeHTML(p.name)}</td>${cells}</tr>`;
        }).join('');

        const html = `
            <!DOCTYPE html>
            <html>
            <head>
                <title>Lineup Card - vs ${escapeHTML(state.game.opponent)}</title>
                <style>
                    body { font-family: sans-serif; padding: 20px; }
                    h1 { text-align: center; margin-bottom: 5px; }
                    p { text-align: center; margin-top: 0; color: #555; }
                    table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 12px; }
                    th, td { border: 1px solid #000; padding: 4px; text-align: center; }
                    th { background: #f0f0f0; }
                    .container { display: flex; gap: 20px; }
                    .lineup-col { width: 35%; }
                    .rotation-col { width: 65%; }
                    @media print {
                        .no-print { display: none; }
                        body { padding: 0; }
                    }
                </style>
            </head>
            <body>
                <h1>vs ${escapeHTML(state.game.opponent)}</h1>
                <p>${(() => {
                    const parts = state.game.date.split(/[- :T]/);
                    if (parts.length >= 3) {
                        return new Date(parts[0], parts[1] - 1, parts[2]).toLocaleDateString();
                    }
                    return state.game.date;
                })()}</p>

                <div class="container">
                    <div class="lineup-col">
                        <h3>Batting Order</h3>
                        <table>
                            <thead><tr><th style="width: 30px;">#</th><th>Player</th></tr></thead>
                            <tbody>${lineupRows || '<tr><td colspan="2">No lineup set</td></tr>'}</tbody>
                        </table>
                    </div>
                    <div class="rotation-col">
                        <h3>Defense Rotation</h3>
                        <table>
                            <thead><tr><th>Player</th>${header}</tr></thead>
                            <tbody>${rotationRows}</tbody>
                        </table>
                    </div>
                </div>
                <div class="no-print" style="text-align: center; margin-top: 20px;">
                    <button onclick="window.print()" style="padding: 10px 20px; font-size: 16px; cursor: pointer;">Print Now</button>
                    <button onclick="window.close()" style="padding: 10px 20px; font-size: 16px; cursor: pointer; margin-left: 10px;">Close</button>
                </div>
            </body>
            </html>
        `;
        printWindow.document.write(html);
        printWindow.document.close();
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
    
    let autosaveTimer = null;
    function triggerAutosave() {
        if (autosaveTimer) clearTimeout(autosaveTimer);
        const btnDesktop = document.getElementById('saveRotationBtn');
        const btnMobile = document.getElementById('saveRotationBtnMobile');

        const indicatingHtml = '<span class="spinner-grow spinner-grow-sm" role="status" aria-hidden="true"></span>';
        if (btnDesktop && !btnDesktop.disabled) btnDesktop.innerHTML = indicatingHtml + ' Saving...';
        if (btnMobile && !btnMobile.disabled) btnMobile.innerHTML = indicatingHtml;

        autosaveTimer = setTimeout(() => {
            saveRotation(true);
        }, 2000);
    }

    async function saveRotation(isAutosave = false) {
        const btnDesktop = document.getElementById('saveRotationBtn');
        const btnMobile = document.getElementById('saveRotationBtnMobile');

        if (!isAutosave) {
            if (btnDesktop) { btnDesktop.disabled = true; btnDesktop.textContent = 'Saving...'; }
            if (btnMobile) { btnMobile.disabled = true; btnMobile.textContent = 'Saving...'; }
        }

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

                if (btnDesktop) btnDesktop.innerHTML = '<i class="bi bi-check"></i> Saved!';
                if (btnMobile) btnMobile.innerHTML = '<i class="bi bi-check"></i>';

                if (!isAutosave || !state.rotation.id) {
                     renderRotationEditor();
                }
            } else { throw new Error(result.message); }
        } catch (error) {
            if (!isAutosave) alert('Error saving rotation: ' + error.message);
            if (btnDesktop) btnDesktop.textContent = 'Save Failed';
            if (btnMobile) btnMobile.textContent = 'Error';
        } finally {
            setTimeout(() => {
                if (btnDesktop) { btnDesktop.disabled = false; btnDesktop.innerHTML = '<i class="bi bi-save me-1"></i> Save Rotation'; }
                if (btnMobile) { btnMobile.disabled = false; btnMobile.innerHTML = '<i class="bi bi-save"></i> Save'; }
            }, 2000);
        }
    }

    async function fetchLatestGameData() {
        if (!state.game || !state.game.id) return;
        try {
            const res = await fetch(`/api/game_data/${state.game.id}`);
            if (!res.ok) throw new Error("Failed to fetch game data.");
            const newData = await res.json();

            // Update state
            state.game = newData.game;
            state.roster = (newData.roster || []).filter(p => !(newData.absent_player_ids || []).includes(p.id));
            state.lineup = newData.lineup || { id: null, title: `Lineup for vs ${newData.game.opponent}`, lineup_positions: [], associated_game_id: newData.game.id };

            // Ensure rotation innings is an object
            let parsedRotation = newData.rotation || { id: null, title: `Rotation for vs ${newData.game.opponent}`, innings: { '1': {} }, associated_game_id: newData.game.id };
            if (typeof parsedRotation.innings === 'string') {
                try {
                    parsedRotation.innings = JSON.parse(parsedRotation.innings);
                } catch (e) {
                    parsedRotation.innings = { '1': {} };
                }
            }
            state.rotation = parsedRotation;

            state.lineup_templates = newData.lineup_templates || [];
            state.rotation_templates = newData.rotation_templates || [];
            state.pitch_count_summary = newData.pitch_count_summary || {};

            // Re-parse live rotation state
            state.rotation_events = newData.rotation_events || [];
            state.actual_rotation = JSON.parse(JSON.stringify(state.rotation.innings));

            if (state.rotation_events.length > 0) {
                state.rotation_events.forEach(evt => {
                    if (!evt.reverted) {
                        state.actual_rotation[evt.inning] = evt.after_alignment;
                    }
                });
            }

            // Update overlay toggle based on DB state
            const toggle = document.getElementById('liveGameModeToggle');
            if (toggle && toggle.checked !== state.game.is_live) {
                toggle.checked = state.game.is_live;
                state.liveMode = state.game.is_live;
                if (state.liveMode) {
                    document.getElementById('live-game-overlay')?.classList.remove('d-none');
                    document.querySelectorAll('.planner-controls').forEach(el => el.classList.add('d-none'));
                    document.getElementById('rotation-board')?.classList.add('bg-light');
                    state.currentInning = state.game.live_current_inning;
                } else {
                    document.getElementById('live-game-overlay')?.classList.add('d-none');
                    document.querySelectorAll('.planner-controls').forEach(el => el.classList.remove('d-none'));
                    document.getElementById('rotation-board')?.classList.remove('bg-light');
                }
            }

            // Re-render
            renderRotationEditor();

            // If lineup modal is open, re-render it
            if (document.getElementById('lineupEditorModal')?.classList.contains('show')) {
                 initializeLineupEditor({
                    roster: state.roster,
                    lineup: state.lineup,
                    benchEl: document.getElementById('lineup-bench'),
                    orderEl: document.getElementById('lineup-order')
                });
            }

            // Check if we need to update the availability list UI
            const presentCount = newData.roster.length - newData.absent_player_ids.length;
            const absentCount = newData.absent_player_ids.length;
            const cardBody = document.querySelector('#availabilityCollapse').closest('.card-body');
            if(cardBody) {
                 const pTag = cardBody.querySelector('p');
                 if(pTag) pTag.innerHTML = `<strong>${presentCount}</strong> players present, <strong>${absentCount}</strong> absent.`;

                 // Update checkboxes
                 newData.roster.forEach(player => {
                     const cb = document.getElementById(`player-${player.id}`);
                     if (cb) {
                         cb.checked = newData.absent_player_ids.includes(player.id);
                     }
                 });
            }

            // Update lineup text list on the main page
            const lineupCardBody = document.querySelector('.card:has(#lineupEditorModal) .card-body') || document.querySelector('.card:nth-child(2) .card-body');
            if (lineupCardBody && !lineupCardBody.closest('.modal')) {
                 if (state.lineup && state.lineup.lineup_positions && state.lineup.lineup_positions.length > 0) {
                      lineupCardBody.innerHTML = `<ol class="list-group list-group-numbered">${state.lineup.lineup_positions.map(p => `<li class="list-group-item">${escapeHTML(p)}</li>`).join('')}</ol>`;
                 } else {
                      lineupCardBody.innerHTML = `<div class="text-center p-3 text-muted"><p class="mb-1">No lineup has been set.</p></div>`;
                 }
            }

        } catch (e) {
            console.error(e);
        }
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        const socket = io();
        socket.on('data_updated', fetchLatestGameData);
        socket.on('lineup_add', fetchLatestGameData);
        socket.on('lineup_update', fetchLatestGameData);
        socket.on('rotation_save', fetchLatestGameData);
        socket.on('roster_update', fetchLatestGameData);
        socket.on('rotation_event', fetchLatestGameData);
        socket.on('rotation_event_undone', fetchLatestGameData);
        socket.on('game_updated', fetchLatestGameData);

        assignPlayerModal = new bootstrap.Modal(document.getElementById('assignPlayerModal'));
        lineupEditorModal = new bootstrap.Modal(document.getElementById('lineupEditorModal'));
        // NEW: Initialize the save template modal
        saveTemplateModal = new bootstrap.Modal(document.getElementById('saveRotationTemplateModal'));

        document.getElementById('saveLineupBtn')?.addEventListener('click', saveLineup);
        document.getElementById('saveRotationBtn')?.addEventListener('click', saveRotation);
        document.getElementById('saveRotationBtnMobile')?.addEventListener('click', saveRotation); // Add mobile listener
        document.getElementById('printCardBtn')?.addEventListener('click', printLineupCard);

        // Live Game Mode Toggle
        document.getElementById('liveGameModeToggle')?.addEventListener('change', (e) => {
            state.liveMode = e.target.checked;

            // Tell backend about the toggle
            fetch('/api/toggle_live_game', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ game_id: state.game.id, is_live: state.liveMode })
            });

            const liveOverlay = document.getElementById('live-game-overlay');
            const plannerControls = document.querySelectorAll('.planner-controls');

            if (state.liveMode) {
                liveOverlay.classList.remove('d-none');
                plannerControls.forEach(el => el.classList.add('d-none'));
                document.getElementById('rotation-board').classList.add('bg-light'); // slight visual diff
                state.currentInning = state.game.live_current_inning || '1';
            } else {
                liveOverlay.classList.add('d-none');
                plannerControls.forEach(el => el.classList.remove('d-none'));
                document.getElementById('rotation-board').classList.remove('bg-light');
            }

            // Re-render everything with the correct state (actual vs planned)
            renderRotationEditor();
        });

        // Initialize UI state if live on load
        if (state.liveMode) {
            const toggle = document.getElementById('liveGameModeToggle');
            if (toggle) toggle.checked = true;
            document.getElementById('live-game-overlay')?.classList.remove('d-none');
            document.querySelectorAll('.planner-controls').forEach(el => el.classList.add('d-none'));
            document.getElementById('rotation-board')?.classList.add('bg-light');
        }

        // Live Game Interactions
        document.getElementById('liveChangePitcherBtn')?.addEventListener('click', () => {
             // In a full implementation, this opens a Pitcher selection modal.
             // For this fast implementation, we can re-use assignPlayerModal logic but inject specific "live pitcher" UI.
             document.getElementById('assignPlayerModalLabel').textContent = 'Live Pitcher Change';
             const container = document.getElementById('player-list');

             let html = '<div class="list-group">';
             state.roster.forEach(p => {
                 const stats = state.pitch_count_summary[p.name];
                 const isResting = stats && stats.status === 'Resting';
                 const isTargetReached = stats && stats.status === 'Coach Target Reached';

                 html += `
                 <button class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                         onclick="handleLivePitcherChange('${escapeHTML(p.name)}')" ${isResting ? 'disabled' : ''}>
                    <div>
                        <span class="fw-bold">${escapeHTML(p.name)}</span>
                        <div class="small ${isResting ? 'text-danger' : isTargetReached ? 'text-warning' : 'text-muted'}">
                            ${stats ? `Today: ${stats.daily} | ${stats.status}` : 'No stats'}
                        </div>
                    </div>
                    <i class="bi bi-chevron-right"></i>
                 </button>`;
             });
             html += '</div>';
             container.innerHTML = html;
             assignPlayerModal.show();
        });

        document.getElementById('liveEndInningBtn')?.addEventListener('click', () => {
             if (confirm("End current inning and advance to the next?")) {
                 const beforeAlign = { ...state.actual_rotation[state.currentInning] };

                 const nextInning = Math.floor(parseFloat(state.currentInning)) + 1;
                 state.currentInning = String(nextInning);

                 // If the actual rotation doesn't have this inning yet, copy from planned if it exists
                 if (!state.actual_rotation[state.currentInning]) {
                     if (state.rotation.innings[state.currentInning]) {
                         state.actual_rotation[state.currentInning] = JSON.parse(JSON.stringify(state.rotation.innings[state.currentInning]));
                     } else {
                         // Or copy from previous actual inning
                         state.actual_rotation[state.currentInning] = JSON.parse(JSON.stringify(state.actual_rotation[String(nextInning - 1)] || {}));
                     }
                 }

                 // Log event
                 logLiveEvent('End Inning', beforeAlign, state.actual_rotation[state.currentInning], null, null);
                 renderRotationEditor();
             }
        });

        let swapPlayer1 = null;
        let liveDefSwapModalObj = null;

        document.getElementById('liveDefensiveChangeBtn')?.addEventListener('click', () => {
            liveDefSwapModalObj = new bootstrap.Modal(document.getElementById('liveDefensiveSwapModal'));
            swapPlayer1 = null;
            document.getElementById('swapInstructionText').innerHTML = 'Tap the <strong>first player</strong> to swap/move.';
            renderLiveDefensiveSwapList();
            liveDefSwapModalObj.show();
        });

        window.handleLiveSwapClick = (playerName) => {
            if (!swapPlayer1) {
                swapPlayer1 = playerName;
                document.getElementById('swapInstructionText').innerHTML = `Select position/player to swap <strong>${escapeHTML(playerName)}</strong> with.`;
                renderLiveDefensiveSwapList();
            } else {
                const swapPlayer2 = playerName;
                const beforeAlign = { ...state.actual_rotation[state.currentInning] };

                // Find positions
                let pos1 = null;
                let pos2 = null;
                for (const [pos, pName] of Object.entries(state.actual_rotation[state.currentInning] || {})) {
                    if (pName === swapPlayer1) pos1 = pos;
                    if (pName === swapPlayer2) pos2 = pos;
                }

                // Execute swap
                if (pos1) state.actual_rotation[state.currentInning][pos1] = swapPlayer2 !== 'BENCH' ? swapPlayer2 : null;
                if (pos2) state.actual_rotation[state.currentInning][pos2] = swapPlayer1 !== 'BENCH' ? swapPlayer1 : null;

                // If they were benched, assign them back.
                // This naive logic might leave nulls if moving to an empty bench.
                // If moving a bench player to an empty position (swapPlayer2 is an empty position name like "1B (Empty)"):
                if (!pos2 && state.roster.some(p => p.name === swapPlayer2)) {
                    // Not assigned to field? We actually need to pick positions, not just players.
                    // For a robust swap, we'll iterate through all positions.
                }

                logLiveEvent('Defensive Change', beforeAlign, state.actual_rotation[state.currentInning], null, null);
                renderRotationEditor();
                liveDefSwapModalObj.hide();
            }
        };

        function renderLiveDefensiveSwapList() {
            const container = document.getElementById('liveSwapPlayerList');
            const currentAlign = state.actual_rotation[state.currentInning] || {};

            // Build a list of all defined field positions + players on them
            const positions = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'LCF', 'RCF'];

            let html = '';

            // Fielders
            html += '<div class="list-group-item bg-light fw-bold text-muted small">ON FIELD</div>';
            positions.forEach(pos => {
                // If 3 OF, skip LCF/RCF. If 4 OF, skip CF.
                if (state.outfielder_count === 3 && (pos === 'LCF' || pos === 'RCF')) return;
                if (state.outfielder_count === 4 && pos === 'CF') return;

                const pName = currentAlign[pos];
                const isSelected = pName === swapPlayer1;
                const display = pName ? pName : '(Empty)';

                html += `
                <button type="button" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center ${isSelected ? 'active' : ''}"
                        onclick="handleLiveSwapClick('${pName || 'EMPTY_' + pos}')">
                    <span><strong>${pos}</strong>: ${escapeHTML(display)}</span>
                </button>`;
            });

            // Bench
            html += '<div class="list-group-item bg-light fw-bold text-muted small mt-2">BENCH</div>';
            const assignedPlayers = new Set(Object.values(currentAlign));
            state.roster.forEach(p => {
                if (!assignedPlayers.has(p.name)) {
                    const isSelected = p.name === swapPlayer1;
                    html += `
                    <button type="button" class="list-group-item list-group-item-action ${isSelected ? 'active' : ''}"
                            onclick="handleLiveSwapClick('${escapeHTML(p.name)}')">
                        ${escapeHTML(p.name)}
                    </button>`;
                }
            });

            container.innerHTML = html;
        }

        // Re-write handleLiveSwapClick to handle position-based swapping properly
        window.handleLiveSwapClick = (target) => {
            if (!swapPlayer1) {
                swapPlayer1 = target; // Target could be a player name, or 'EMPTY_1B'
                document.getElementById('swapInstructionText').innerHTML = `Select position/player to swap <strong>${escapeHTML(target.replace('EMPTY_', 'Empty '))}</strong> with.`;
                renderLiveDefensiveSwapList();
            } else {
                const target1 = swapPlayer1;
                const target2 = target;

                const beforeAlign = { ...state.actual_rotation[state.currentInning] };
                if (!state.actual_rotation[state.currentInning]) state.actual_rotation[state.currentInning] = {};

                // Helpers to find where a target is
                const getPos = (t) => {
                    if (t.startsWith('EMPTY_')) return t.replace('EMPTY_', '');
                    for (const [pos, name] of Object.entries(state.actual_rotation[state.currentInning])) {
                        if (name === t) return pos;
                    }
                    return null; // Means they are on bench
                };

                const pos1 = getPos(target1);
                const pos2 = getPos(target2);

                const name1 = target1.startsWith('EMPTY_') ? null : target1;
                const name2 = target2.startsWith('EMPTY_') ? null : target2;

                // Do the swap
                if (pos1) state.actual_rotation[state.currentInning][pos1] = name2;
                if (pos2) state.actual_rotation[state.currentInning][pos2] = name1;

                logLiveEvent('Defensive Change', beforeAlign, state.actual_rotation[state.currentInning], null, null);
                renderRotationEditor();
                liveDefSwapModalObj.hide();
            }
        };


        document.getElementById('liveUndoBtn')?.addEventListener('click', () => {
             if (state.rotation_events.length > 0) {
                 if (confirm("Undo the last live rotation event?")) {
                     const lastEvent = state.rotation_events[state.rotation_events.length - 1];
                     fetch('/api/undo_rotation_event', {
                         method: 'POST',
                         headers: { 'Content-Type': 'application/json' },
                         body: JSON.stringify({ event_id: lastEvent.id })
                     }).then(res => res.json()).then(data => {
                         if (data.status === 'success') {
                             // Temporarily update local state immediately
                             state.actual_rotation[lastEvent.inning] = lastEvent.before_alignment;
                             state.rotation_events.pop();
                             renderRotationEditor();
                         }
                     });
                 }
             } else {
                 alert("No live events to undo.");
             }
        });

        let finalCountsModalObj = null;

        document.getElementById('liveEndGameBtn')?.addEventListener('click', () => {
            const pitchedPlayers = new Set();
            for (let inn in state.actual_rotation) {
                if (state.actual_rotation[inn]['P']) {
                    pitchedPlayers.add(state.actual_rotation[inn]['P']);
                }
            }

            if (pitchedPlayers.size === 0) {
                alert("No pitchers have been recorded in this game yet.");
                return;
            }

            const container = document.getElementById('finalCountsFormContainer');
            let html = '';
            pitchedPlayers.forEach(pName => {
                const player = state.roster.find(p => p.name === pName);
                if (player) {
                    html += `
                    <div class="input-group mb-3 input-group-lg">
                      <span class="input-group-text fw-bold" style="width: 150px;">${escapeHTML(pName)}</span>
                      <input type="number" class="form-control text-center final-pitch-input" data-player-id="${player.id}" placeholder="Pitches">
                    </div>`;
                }
            });
            container.innerHTML = html;

            finalCountsModalObj = new bootstrap.Modal(document.getElementById('liveFinalCountsModal'));
            finalCountsModalObj.show();
        });

        document.getElementById('confirmFinalCountsBtn')?.addEventListener('click', () => {
            const inputs = document.querySelectorAll('.final-pitch-input');
            const counts = [];

            inputs.forEach(input => {
                const val = input.value.trim();
                if (val && !isNaN(parseInt(val))) {
                    counts.push({
                        player_id: input.dataset.playerId,
                        pitches: parseInt(val)
                    });
                }
            });

            if (counts.length > 0) {
                fetch('/api/save_final_pitch_counts', {
                     method: 'POST',
                     headers: { 'Content-Type': 'application/json' },
                     body: JSON.stringify({ game_id: state.game.id, counts: counts })
                 }).then(res => res.json()).then(data => {
                     if(data.status === 'success') {
                         finalCountsModalObj.hide();
                         alert('Final pitch counts saved successfully!');

                         // Drop out of live mode optionally? Let's stay in it unless they manually toggle off
                     } else {
                         alert('Error saving pitch counts.');
                     }
                 });
            } else {
                finalCountsModalObj.hide(); // Allow skipping
            }
        });

        // NEW: Populate and handle the rotation template dropdown
        const rotationTemplateSelect = document.getElementById('rotationTemplateSelect');
        if (rotationTemplateSelect) {
            state.rotation_templates.forEach(rt => {
                const inningsCount = rt.innings ? Object.keys(rt.innings).length : 0;
                const option = new Option(`${rt.title} (${inningsCount} innings)`, rt.id);
                rotationTemplateSelect.add(option);
            });

            rotationTemplateSelect.addEventListener('change', (e) => {
                const selectedTemplateId = e.target.value;
                if (selectedTemplateId) {
                    const selectedTemplate = state.rotation_templates.find(rt => rt.id == selectedTemplateId);
                    if (selectedTemplate && confirm(`This will overwrite the current rotation with the "${selectedTemplate.title}" template. Are you sure?`)) {
                        // Deep copy the innings data to avoid reference issues
                        state.rotation.innings = JSON.parse(JSON.stringify(selectedTemplate.innings));
                        // Ensure at least one inning exists
                        if (Object.keys(state.rotation.innings).length === 0) {
                            state.rotation.innings['1'] = {};
                        }
                        // Set the current inning to the first available inning from the template
                        state.currentInning = Object.keys(state.rotation.innings).sort((a,b) => parseFloat(a) - parseFloat(b))[0];
                        renderRotationEditor();
                        alert('Rotation template loaded successfully!');
                        triggerAutosave();
                    }
                    // Reset the select so you can re-apply the same template if needed
                    e.target.value = '';
                }
            });
        }

        // NEW: Add event listener for the "Save as Template" button
        document.getElementById('saveAsTemplateBtn')?.addEventListener('click', () => {
            // Pre-fill the input with a helpful suggestion
            const suggestedName = `Template from vs ${state.game.opponent}`;
            document.getElementById('rotationTemplateName').value = suggestedName;
            saveTemplateModal.show();
        });

        // NEW: Add event listener for the confirm button inside the modal
        document.getElementById('confirmSaveTemplateBtn')?.addEventListener('click', async () => {
            const templateNameInput = document.getElementById('rotationTemplateName');
            const templateName = templateNameInput.value.trim();

            if (!templateName) {
                templateNameInput.classList.add('is-invalid');
                return;
            }
            templateNameInput.classList.remove('is-invalid');

            const btn = document.getElementById('confirmSaveTemplateBtn');
            btn.disabled = true;
            btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Saving...`;

            const payload = {
                title: templateName,
                innings: state.rotation.innings
            };

            try {
                const response = await fetch('/save_rotation_as_template', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.message);

                // Add the new template to our dropdown without needing a page refresh
                const select = document.getElementById('rotationTemplateSelect');
                if (select && result.new_template) {
                     const newTemplate = result.new_template;
                     state.rotation_templates.push(newTemplate); // Update state
                     const inningsCount = newTemplate.innings ? Object.keys(newTemplate.innings).length : 0;
                     const option = new Option(`${newTemplate.title} (${inningsCount} innings)`, newTemplate.id);
                     select.add(option);
                }

                saveTemplateModal.hide();
                alert('Template saved successfully!');

            } catch (error) {
                alert('Error saving template: ' + error.message);
            } finally {
                btn.disabled = false;
                btn.innerHTML = 'Save Template';
            }
        });

        document.getElementById('lineupEditorModal')?.addEventListener('shown.bs.modal', () => {
            const templateSelect = document.getElementById('lineupTemplateSelect');
            templateSelect.innerHTML = '<option value="">-- Select a Template --</option>';
            state.lineup_templates.forEach(lt => {
                const option = new Option(`${lt.title} (${lt.lineup_positions.length} players)`, lt.id);
                templateSelect.add(option);
            });

            const renderLineup = () => {
                 initializeLineupEditor({
                    roster: state.roster,
                    lineup: state.lineup,
                    benchEl: document.getElementById('lineup-bench'),
                    orderEl: document.getElementById('lineup-order')
                });
            };

            templateSelect.addEventListener('change', (e) => {
                const selectedTemplateId = e.target.value;
                if (selectedTemplateId) {
                    const selectedTemplate = state.lineup_templates.find(lt => lt.id == selectedTemplateId);
                    if (selectedTemplate) {
                        state.lineup.lineup_positions = [...selectedTemplate.lineup_positions];
                        renderLineup();
                    }
                }
            });

            renderLineup();
        });

        document.getElementById('deleteRotationBtn')?.addEventListener('click', () => {
            if (state.rotation?.id && confirm(`Are you sure you want to delete this rotation?`)) {
                window.location.href = `/delete_rotation/${state.rotation.id}`;
            }
        });
        document.body.addEventListener('click', function(event){
            const dropzone = event.target.closest('.position-dropzone');
            if (dropzone) {
                const position = dropzone.dataset.position;
                if (dropzone.querySelector('.player-tag')) {
                    delete state.rotation.innings[state.currentInning][position];
                    renderRotationEditor();
                    triggerAutosave();
                } else { 
                    const assignedPlayers = new Set(Object.values(state.rotation.innings[state.currentInning] || {}));
                    const benchPlayers = state.roster.filter(p => !assignedPlayers.has(p.name));
                    document.getElementById('assignPlayerModalTitle').textContent = `Assign to ${position}`;
                    document.getElementById('assignPlayerModal').dataset.targetPosition = position;
                    document.getElementById('assignPlayerModalBenchList').innerHTML = benchPlayers.length > 0 ? 
                        benchPlayers.map(p => {
                            const positions = [p.position1, p.position2, p.position3].filter(pos => pos).join(', ');
                            const posString = positions ? ` (${positions})` : '';

                            return `<a href="#" class="list-group-item list-group-item-action" data-player-name="${escapeHTML(p.name)}">${escapeHTML(p.name)}${escapeHTML(posString)}</a>`;
                        }).join('') :
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
                    triggerAutosave();
                }
            }
        });
        document.getElementById('addInningBtn')?.addEventListener('click', () => {
            if(!state.rotation) return;
            const innings = Object.keys(state.rotation.innings);
            const nextInningNum = innings.length > 0 ? Math.floor(Math.max(...innings.map(parseFloat))) + 1 : 1;

            if (innings.length > 0) {
                // Auto-copy the previous inning's data (find the absolute highest inning value)
                const lastInningNum = Math.max(...innings.map(parseFloat));
                state.rotation.innings[nextInningNum] = { ...state.rotation.innings[String(lastInningNum)] };
            } else {
                state.rotation.innings[nextInningNum] = {};
            }

            renderInningSelector();
            // Optional: Switch to the new inning to let the user edit immediately
            state.currentInning = String(nextInningNum);
            renderRotationEditor();
            triggerAutosave();
        });

        document.getElementById('addSubInningBtn')?.addEventListener('click', () => {
            if(!state.rotation || !state.currentInning) return;

            // Get current base inning
            const baseInning = Math.floor(parseFloat(state.currentInning));

            // Find all sub-innings for this base inning
            const allInnings = Object.keys(state.rotation.innings).map(parseFloat);
            const subInnings = allInnings.filter(inn => Math.floor(inn) === baseInning);

            // Determine next sub-inning value (e.g. if 1 and 1.1 exist, next is 1.2)
            const maxSubInning = Math.max(...subInnings);
            // Precision issues with floats, so round to 1 decimal place
            const nextSubInningNum = Math.round((maxSubInning + 0.1) * 10) / 10;
            const nextSubInningStr = String(nextSubInningNum);

            // Auto-copy the data from the exact inning we were just on
            state.rotation.innings[nextSubInningStr] = { ...state.rotation.innings[state.currentInning] };

            renderInningSelector();
            state.currentInning = nextSubInningStr;
            renderRotationEditor();
            triggerAutosave();
        });

        document.getElementById('removeInningBtn')?.addEventListener('click', () => {
            if(!state.rotation) return;
            const innings = Object.keys(state.rotation.innings);
            if(innings.length <= 1) return alert("Cannot remove the last inning.");
            const lastInningNum = String(Math.max(...innings.map(parseFloat)));
            delete state.rotation.innings[lastInningNum];
            if(String(state.currentInning) === lastInningNum) {
                state.currentInning = String(Math.max(...Object.keys(state.rotation.innings).map(parseFloat)));
            }
            renderRotationEditor();
            triggerAutosave();
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
            triggerAutosave();
        });
        document.getElementById('cancelPasteBtn')?.addEventListener('click', exitCopyMode);

        document.getElementById('clearInningBtn')?.addEventListener('click', () => {
            if (!state.rotation || !state.currentInning) return;
            if (confirm(`Are you sure you want to clear all positions for inning ${state.currentInning}?`)) {
                state.rotation.innings[state.currentInning] = {};
                renderRotationEditor();
                triggerAutosave();
            }
        });

        document.getElementById('copyPreviousInningBtn')?.addEventListener('click', () => {
            if (!state.rotation) return;
            const currentInningNum = parseInt(state.currentInning);
            if (currentInningNum <= 1) {
                alert("There is no previous inning to copy.");
                return;
            }
            const previousInningNum = currentInningNum - 1;
            const previousInningData = state.rotation.innings[previousInningNum];
            if (previousInningData) {
                 if (confirm(`This will overwrite inning ${currentInningNum} with the positions from inning ${previousInningNum}. Continue?`)) {
                    state.rotation.innings[currentInningNum] = { ...previousInningData };
                    renderRotationEditor();
                    triggerAutosave();
                }
            } else {
                alert(`Inning ${previousInningNum} has no data to copy.`);
            }
        });
    }

    function logLiveEvent(eventType, beforeAlign, afterAlign, oldPitcherId, newPitcherId) {
         fetch('/api/save_rotation_event', {
             method: 'POST',
             headers: { 'Content-Type': 'application/json' },
             body: JSON.stringify({
                 game_id: state.game.id,
                 inning: state.currentInning,
                 sequence: state.rotation_events.length + 1,
                 event_type: eventType,
                 before_alignment: beforeAlign,
                 after_alignment: afterAlign,
                 old_pitcher_id: oldPitcherId,
                 new_pitcher_id: newPitcherId
             })
         }).then(res => res.json()).then(data => {
             // In a full implementation we'd append data.event to state.rotation_events
             if(data.status !== 'success') console.error('Failed to log event');
         });
    }

    // Must define this in scope for the inline onclick handler to reach it
    let pendingPitcherChange = null;
    let livePitcherDestModalObj = null;

    window.handleLivePitcherChange = (playerName) => {
         const player = state.roster.find(p => p.name === playerName);
         if (!player) return;

         const beforeAlign = { ...state.actual_rotation[state.currentInning] };
         let oldPitcherName = state.actual_rotation[state.currentInning]['P'];

         if (!oldPitcherName) {
             // No old pitcher to worry about, just assign
             state.actual_rotation[state.currentInning]['P'] = playerName;
             logLiveEvent('Pitcher Change', beforeAlign, state.actual_rotation[state.currentInning], null, player.id);
             renderRotationEditor();
             assignPlayerModal.hide();
             return;
         }

         // We have an old pitcher. Where should they go?
         pendingPitcherChange = { newPitcherName: playerName, beforeAlign: beforeAlign, oldPitcherName: oldPitcherName };
         assignPlayerModal.hide();

         document.getElementById('oldPitcherNameDisplay').textContent = oldPitcherName;

         const destContainer = document.getElementById('livePitcherDestinations');
         let html = `<div class="col-6"><button class="btn btn-secondary w-100 py-3" onclick="finalizePitcherChange('BENCH')">Bench</button></div>`;

         const positions = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'LCF', 'RCF'];
         positions.forEach(pos => {
            if (state.outfielder_count === 3 && (pos === 'LCF' || pos === 'RCF')) return;
            if (state.outfielder_count === 4 && pos === 'CF') return;
            html += `<div class="col-6"><button class="btn btn-outline-dark w-100 py-3" onclick="finalizePitcherChange('${pos}')">${pos}</button></div>`;
         });
         destContainer.innerHTML = html;

         livePitcherDestModalObj = new bootstrap.Modal(document.getElementById('livePitcherDestinationModal'));
         livePitcherDestModalObj.show();
    };

    window.finalizePitcherChange = (destinationPos) => {
         if (!pendingPitcherChange) return;
         const { newPitcherName, beforeAlign, oldPitcherName } = pendingPitcherChange;

         // 1. Remove new pitcher from their old spot if they were on the field
         let oldSpotOfNewPitcher = null;
         for (const [pos, name] of Object.entries(state.actual_rotation[state.currentInning] || {})) {
             if (name === newPitcherName) oldSpotOfNewPitcher = pos;
         }
         if (oldSpotOfNewPitcher) state.actual_rotation[state.currentInning][oldSpotOfNewPitcher] = null;

         // 2. Put new pitcher at P
         state.actual_rotation[state.currentInning]['P'] = newPitcherName;

         // 3. Put old pitcher at destination
         if (destinationPos === 'BENCH') {
             // Just removed from P, so they are effectively benched.
         } else {
             state.actual_rotation[state.currentInning][destinationPos] = oldPitcherName;
         }

         const oldPId = state.roster.find(p => p.name === oldPitcherName)?.id;
         const newPId = state.roster.find(p => p.name === newPitcherName)?.id;

         logLiveEvent('Pitcher Change', beforeAlign, state.actual_rotation[state.currentInning], oldPId, newPId);
         renderRotationEditor();
         livePitcherDestModalObj.hide();
         pendingPitcherChange = null;
    };

    // --- Initial Page Render ---
    if(state.game) {
        renderRotationEditor();
        setupEventListeners();
    } else {
        console.error("Game data was not provided to initialize the page.");
        document.getElementById('rotation-board').innerHTML = '<div class="alert alert-danger">Could not load game data. Please go back and try again.</div>';
    }
}