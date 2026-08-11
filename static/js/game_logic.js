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
        initializeRotationSortables();
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

        const innings = Object.keys(state.rotation.innings || {}).sort((a, b) => parseFloat(a) - parseFloat(b));
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
                const inningData = state.rotation.innings[inn] || {};
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
        const innings = Object.keys(state.rotation.innings || {}).sort((a, b) => parseFloat(a) - parseFloat(b));
        if (innings.length === 0) {
            container.innerHTML = '<div class="p-3 text-muted">No innings data available.</div>';
            return;
        }

        let html = '<div class="list-group list-group-flush">';

        innings.forEach(inn => {
            const inningData = state.rotation.innings[inn] || {};
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
                <p>${new Date(state.game.date).toLocaleDateString()}</p>

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

        assignPlayerModal = new bootstrap.Modal(document.getElementById('assignPlayerModal'));
        lineupEditorModal = new bootstrap.Modal(document.getElementById('lineupEditorModal'));
        // NEW: Initialize the save template modal
        saveTemplateModal = new bootstrap.Modal(document.getElementById('saveRotationTemplateModal'));

        document.getElementById('saveLineupBtn')?.addEventListener('click', saveLineup);
        document.getElementById('saveRotationBtn')?.addEventListener('click', saveRotation);
        document.getElementById('saveRotationBtnMobile')?.addEventListener('click', saveRotation); // Add mobile listener
        document.getElementById('printCardBtn')?.addEventListener('click', printLineupCard);

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

    // --- Initial Page Render ---
    if(state.game) {
        renderRotationEditor();
        setupEventListeners();
    } else {
        console.error("Game data was not provided to initialize the page.");
        document.getElementById('rotation-board').innerHTML = '<div class="alert alert-danger">Could not load game data. Please go back and try again.</div>';
    }
}