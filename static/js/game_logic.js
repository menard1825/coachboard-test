// =================================================================================
// Coach Planner - Game Management Client-Side Logic (REFACTORED)
// =================================================================================

// This script is now fully self-contained and does not use a global AppState.
const escapeHTML = str => String(str).replace(/[&<>'"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;',"'": '&#39;','"': '&quot;'}[tag] || tag));

function initializeGameManagement(gameData) {

    // The rotation itself and its /save_rotation queue live in the shared
    // CBPregameRotation store, not in this file's own state — the
    // #pregame-defense-editor-v3 tap field (static/js/live_game_board_prep.js)
    // mutates the exact same object and shares the same queue, so a save
    // built by either module always reflects every edit made by both,
    // never a stale per-module snapshot.
    function defaultRotationTitle() {
        return `Rotation for vs ${gameData.game.opponent}`;
    }
    window.CBPregameRotation.setFromServer(gameData.rotation, defaultRotationTitle());

    // --- Page-Specific State ---
    // All data for this page is stored in a local 'state' object.
    const state = {
        roster: (gameData.roster || []).filter(p => !(gameData.absent_player_ids || []).includes(p.id)),
        lineup: gameData.lineup || { id: null, title: `Lineup for vs ${gameData.game.opponent}`, lineup_positions: [], associated_game_id: gameData.game.id },
        rotation: window.CBPregameRotation.getRotation(defaultRotationTitle()),
        game: gameData.game,
        lineup_templates: gameData.lineup_templates || [],
        previous_lineup: gameData.previous_lineup || null,
        batting_order_mode: gameData.batting_order_mode || 'bat_all',
        fixed_lineup_size: gameData.fixed_lineup_size || 9,
        // NEW: Add rotation_templates to the state
        rotation_templates: gameData.rotation_templates || [],
        outfielder_count: gameData.outfielder_count || 3,
        currentInning: '1',
        copiedInningData: null,
        sortableInstances: {}
    };

    // --- Live Mode Authoritative Syncing ---
    // The server API now provides actual_rotation fully computed.
    state.actual_rotation = gameData.actual_rotation || JSON.parse(JSON.stringify(state.rotation.innings || {}));
    state.rotation_events = gameData.rotation_events || [];
    state.pitch_count_summary = gameData.pitch_count_summary || {};
    state.pitching_plans = gameData.pitching_plans || [];
    state.pitching_profiles = gameData.pitching_profiles || [];

    state.liveMode = state.game.is_live || false;
    state.currentInning = state.liveMode ? state.game.live_current_inning || '1' : '1';

    let assignPlayerModal;
    let lineupEditorModal;
    let lineupEditorController;
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

    function getActiveInnings() {
        return state.liveMode ? state.actual_rotation : (state.rotation.innings || {});
    }

    function renderRotationDiamondAndBench() {
        const currentInningData = getActiveInnings()[state.currentInning] || {};

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
        const title = document.getElementById('lineupTitle').value.trim();
        const playerIds = lineupEditorController?.getPlayerIds() || [];
        const playerNames = lineupEditorController?.getPlayerNames() || [];
        if (!title) {
            document.getElementById('lineupTitle').focus();
            return;
        }
        if (!playerIds.length) {
            alert('Add at least one available player to the batting order.');
            return;
        }
        if (lineupEditorController?.getUnavailableEntries().length) {
            alert('Remove unavailable players before saving this Game Day lineup.');
            return;
        }
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Saving...`;
        const url = state.lineup.id ? `/edit_lineup/${state.lineup.id}` : '/add_lineup';
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title,
                    lineup_data: playerNames,
                    lineup_player_ids: playerIds,
                    associated_game_id: state.game.id
                })
            });
            const result = await response.json();
            if(!response.ok) throw new Error(result.message);
            state.lineup = result.lineup;
            lineupEditorModal.hide();
            window.location.reload();
        } catch (error) {
            alert('Error saving lineup: ' + error.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = 'Save Lineup';
        }
    }
    
    // --- Rotation save queue -----------------------------------------------
    // The rotation object and its /save_rotation queue live in the shared
    // CBPregameRotation store (static/js/pregame_rotation_sync.js), not
    // here: the #pregame-defense-editor-v3 tap field mutates the exact
    // same object and shares the same queue, so a payload built by either
    // module always reflects every edit made by both — never a stale
    // per-module snapshot that could overwrite the other's change.
    function setRotationSaveStatus(status, error, wasManual) {
        const btnDesktop = document.getElementById('saveRotationBtn');
        const btnMobile = document.getElementById('saveRotationBtnMobile');

        const setDisabled = (btn, disabled) => {
            if (!btn) return;
            if ('disabled' in btn) btn.disabled = disabled;
            btn.classList.toggle('disabled', disabled);
            btn.setAttribute('aria-disabled', disabled ? 'true' : 'false');
        };

        if (status === 'saving') {
            setDisabled(btnDesktop, true);
            setDisabled(btnMobile, true);
            if (btnDesktop) btnDesktop.innerHTML = '<span class="spinner-grow spinner-grow-sm" role="status" aria-hidden="true"></span> Saving...';
            if (btnMobile) btnMobile.innerHTML = '<span class="spinner-grow spinner-grow-sm" role="status" aria-hidden="true"></span>';
            return;
        }

        setDisabled(btnDesktop, false);
        setDisabled(btnMobile, false);

        if (status === 'failed') {
            // A failure stays visible and retryable instead of silently
            // resetting after two seconds.
            if (btnDesktop) btnDesktop.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i> Save Failed — Retry';
            if (btnMobile) btnMobile.innerHTML = '<i class="bi bi-exclamation-triangle"></i> Retry';
            if (wasManual) {
                alert('Error saving rotation: ' + (error?.message || 'Unknown error'));
            }
            return;
        }

        if (status === 'saved') {
            if (btnDesktop) btnDesktop.innerHTML = '<i class="bi bi-check"></i> Saved!';
            if (btnMobile) btnMobile.innerHTML = '<i class="bi bi-check"></i>';
            return;
        }

        // idle
        if (btnDesktop) btnDesktop.innerHTML = '<i class="bi bi-save me-1"></i> Save Rotation';
        if (btnMobile) btnMobile.innerHTML = '<i class="bi bi-save"></i> Save';
    }

    window.CBPregameRotation.onStatusChange(setRotationSaveStatus);

    // Keep state.rotation pointing at the shared store's current object at
    // all times. setFromServer() (triggered by either module's background
    // refresh) replaces that object outright rather than mutating it in
    // place, and this module's own toolbar handlers (Add/Remove/Clear
    // Inning, Copy Previous, Paste, ...) mutate state.rotation.innings[...]
    // directly. Without this resync, a refresh applied via the tap field
    // (live_game_board_prep.js) could leave those handlers mutating an
    // abandoned, detached snapshot that the shared save queue never reads
    // again — silently losing the structural change.
    window.CBPregameRotation.onChange(() => {
        state.rotation = window.CBPregameRotation.getRotation(defaultRotationTitle());
    });

    function triggerAutosave() {
        window.CBPregameRotation.commitLocalChange(defaultRotationTitle(), false);
    }

    function saveRotation(isAutosave = false) {
        window.CBPregameRotation.commitLocalChange(defaultRotationTitle(), !isAutosave);
    }

    async function fetchLatestGameData() {
        if (!state.game || !state.game.id) return;

        // Captured at request start, not response time. Several socket
        // events (data_updated, lineup_add/update, roster_update,
        // game_updated, pitching_update) call this unconditionally, so a
        // rotation save from either module can already be in flight when
        // the fetch below begins. Checking only at response time is not
        // enough: that in-flight save can complete successfully while this
        // request is still outstanding, so by the time the response
        // arrives every check available then (not in flight, revision
        // unchanged, nothing unsynced) looks perfectly safe even though
        // the snapshot was captured before that save landed and is now
        // stale relative to it.
        const rotationSafeAtStart = !window.CBPregameRotation.isSaveInFlightOrQueued()
            && !window.CBPregameRotation.hasUnsyncedLocalState();
        const rotationRevisionAtStart = window.CBPregameRotation.getLocalRevision();
        // A separate, later-started refresh (this module's own next call,
        // or live_game_board_prep.js's refresh()) can return and apply
        // before this one does. Local-edit revision checks alone don't
        // change when a SERVER snapshot is accepted, so they can't detect
        // that case; the shared token orders server refreshes against
        // each other — across both modules — regardless of arrival order.
        const rotationRefreshToken = window.CBPregameRotation.beginServerRefresh();

        try {
            const res = await fetch(`/api/game_data/${state.game.id}`);
            if (!res.ok) throw new Error("Failed to fetch game data.");
            const newData = await res.json();

            // Update state
            state.game = newData.game;
            state.roster = (newData.roster || []).filter(p => !(newData.absent_player_ids || []).includes(p.id));
            state.lineup = newData.lineup || { id: null, title: `Lineup for vs ${newData.game.opponent}`, lineup_positions: [], associated_game_id: newData.game.id };

            // Only apply the server's rotation snapshot when it was safe to
            // refresh both at request start AND still is right now (no
            // edit — from this module's own toolbar or the tap field —
            // landed or is still in flight in between), AND no later-started
            // refresh (from either module) has already applied a newer
            // snapshot. Everything else in newData is applied unconditionally
            // below; only the rotation portion is gated, so an edit in
            // progress never suppresses an otherwise-unrelated
            // roster/lineup/pitching refresh.
            if (rotationSafeAtStart && window.CBPregameRotation.canApplyRefresh(rotationRevisionAtStart, rotationRefreshToken)) {
                window.CBPregameRotation.setFromServer(newData.rotation, `Rotation for vs ${newData.game.opponent}`, rotationRefreshToken);
            }
            state.rotation = window.CBPregameRotation.getRotation(`Rotation for vs ${newData.game.opponent}`);

            state.lineup_templates = newData.lineup_templates || [];
            state.previous_lineup = newData.previous_lineup || null;
            state.batting_order_mode = newData.batting_order_mode || 'bat_all';
            state.fixed_lineup_size = newData.fixed_lineup_size || 9;
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

            // Check if we need to update the availability list UI
            const presentCount = newData.roster.length - newData.absent_player_ids.length;
            const absentCount = newData.absent_player_ids.length;
            const presentMetric = document.getElementById('availabilityPresentCount');
            const absentMetric = document.getElementById('availabilityAbsentCount');
            if (presentMetric) presentMetric.textContent = String(presentCount);
            if (absentMetric) absentMetric.textContent = `${absentCount} out`;

            // Keep the open availability editor synchronized when another
            // coach updates the same game. Dispatching change also refreshes
            // the OUT labels and counter added by the availability helper.
            newData.roster.forEach(player => {
                const checkbox = document.getElementById(`absent_${player.id}`);
                if (!checkbox) return;
                const checked = newData.absent_player_ids.includes(player.id);
                if (checkbox.checked !== checked) {
                    checkbox.checked = checked;
                    checkbox.dispatchEvent(new Event('change', {bubbles: true}));
                }
            });

            // Refresh the compact checklist metric without replacing the card
            // body (which previously removed its Edit Lineup button).
            const lineupCount = state.lineup?.lineup_positions?.length || 0;
            const lineupMetric = document.getElementById('lineupSummaryCount');
            const lineupTitle = document.getElementById('lineupSummaryTitle');
            if (lineupMetric) lineupMetric.textContent = String(lineupCount);
            if (lineupTitle) lineupTitle.textContent = lineupCount
                ? (state.lineup.title || 'Game lineup')
                : 'Not set';

        } catch (e) {
            console.error(e);
        }
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        const socket = typeof io === 'function' ? io() : null;

        if (socket) {
            socket.on('connect', () => {
                // Join the game-specific room to ensure we only get relevant live game broadcasts
                socket.emit('join_game_room', { game_id: state.game.id });
            });

            socket.on('data_updated', fetchLatestGameData);
            socket.on('lineup_add', fetchLatestGameData);
            socket.on('lineup_update', fetchLatestGameData);
            socket.on('rotation_save', () => {
                // Don't clobber a local edit (from this module's toolbar or
                // the tap field) that is still saving, queued, or failed to
                // save; refresh once local saving has settled.
                if (window.CBPregameRotation.isSaveInFlightOrQueued() || window.CBPregameRotation.hasUnsyncedLocalState()) {
                    return;
                }
                fetchLatestGameData();
            });
            socket.on('roster_update', fetchLatestGameData);
            socket.on('game_updated', fetchLatestGameData);
            socket.on('pitching_update', fetchLatestGameData);

            // Listen for authoritative state broadcasts specifically for the live game
            socket.on('game_state_update', (newState) => {
                console.log("Received server-authoritative live game state broadcast.", newState);

                // Re-apply essential parsed objects if needed
                if (newState.rotation && typeof newState.rotation.innings === 'string') {
                    newState.rotation.innings = JSON.parse(newState.rotation.innings);
                }

                state.actual_rotation = newState.actual_rotation;
                state.rotation_events = newState.rotation_events;
                state.pitch_count_summary = newState.pitch_count_summary;
                state.pitching_plans = newState.pitching_plans;
                state.game = newState.game;
                state.liveMode = newState.game.is_live;
                state.currentInning = state.liveMode ? state.game.live_current_inning || '1' : state.currentInning;

                renderRotationEditor();
                renderBenchReport();
            });
        }

        assignPlayerModal = new bootstrap.Modal(document.getElementById('assignPlayerModal'));
        lineupEditorModal = new bootstrap.Modal(document.getElementById('lineupEditorModal'));
        // NEW: Initialize the save template modal
        saveTemplateModal = new bootstrap.Modal(document.getElementById('saveRotationTemplateModal'));

        document.getElementById('saveLineupBtn')?.addEventListener('click', saveLineup);
        document.getElementById('rotateLineupBtn')?.addEventListener('click', () => lineupEditorController?.rotate());
        document.getElementById('applyLineupSourceBtn')?.addEventListener('click', () => {
            const select = document.getElementById('lineupTemplateSelect');
            let source = null;
            if (select.value === 'previous') source = state.previous_lineup;
            if (select.value.startsWith('template:')) {
                const id = Number(select.value.split(':')[1]);
                source = state.lineup_templates.find(template => template.id === id);
            }
            if (select.value === 'blank') source = { title: 'a blank lineup', lineup_entries: [], lineup_positions: [] };
            if (!source) return;

            const presentIds = new Set(state.roster.map(player => Number(player.id)));
            const presentNames = new Set(state.roster.map(player => player.name));
            const entries = Array.isArray(source.lineup_entries) && source.lineup_entries.length
                ? source.lineup_entries
                : (source.lineup_positions || []).map(name => ({ name, player_id: null }));
            const appliedEntries = [];
            const skippedNames = [];
            entries.forEach(entry => {
                const available = entry.player_id != null
                    ? presentIds.has(Number(entry.player_id))
                    : presentNames.has(entry.name || entry.player_name_snapshot);
                if (available) appliedEntries.push(entry);
                else skippedNames.push(entry.name || entry.player_name_snapshot || 'Unknown player');
            });
            lineupEditorController?.setLineup({ lineup_entries: appliedEntries });
            const benchCount = lineupEditorController?.getBenchPlayers().length || 0;
            const feedback = document.getElementById('lineupEditorFeedback');
            feedback.className = skippedNames.length ? 'alert alert-warning py-2' : 'alert alert-info py-2';
            feedback.textContent = `Applied ${source.title || 'lineup'}. ${skippedNames.length ? `Skipped unavailable: ${skippedNames.join(', ')}. ` : ''}${benchCount} available player${benchCount === 1 ? '' : 's'} remain on the bench.`;
        });
        document.getElementById('saveRotationBtn')?.addEventListener('click', (event) => {
            event.preventDefault();
            void saveRotation(false);
        });
        document.getElementById('saveRotationBtnMobile')?.addEventListener('click', (event) => {
            event.preventDefault();
            void saveRotation(false);
        });
        document.getElementById('printCardBtn')?.addEventListener('click', printLineupCard);

        // Live Game start/change/end actions are owned by live_game_v2.js so the
        // server remains authoritative. Do not bind the retired toggle endpoint
        // here; duplicate listeners can otherwise make a failed start look live.

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

        document.getElementById('liveUndoBtn')?.addEventListener('click', () => {
             if (state.rotation_events.length > 0) {
                 const unrevertedEvents = state.rotation_events.filter(e => !e.reverted);
                 if (unrevertedEvents.length === 0) {
                     alert("No live events to undo.");
                     return;
                 }
                 if (confirm("Undo the last live rotation event?")) {
                     const lastEvent = unrevertedEvents[unrevertedEvents.length - 1];
                     fetch('/api/undo_rotation_event', {
                         method: 'POST',
                         headers: { 'Content-Type': 'application/json' },
                         body: JSON.stringify({ event_id: lastEvent.id })
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
            templateSelect.innerHTML = '<option value="blank">Blank lineup</option>';
            state.lineup_templates.forEach(lt => {
                const label = `${lt.is_default ? 'Default — ' : ''}${lt.title} (${lt.lineup_positions.length} players)`;
                const option = new Option(label, `template:${lt.id}`);
                templateSelect.add(option);
            });
            if (state.previous_lineup) {
                templateSelect.add(new Option(`Previous game — ${state.previous_lineup.title}`, 'previous'));
            }
            const defaultTemplate = state.lineup_templates.find(template => template.is_default);
            templateSelect.value = defaultTemplate ? `template:${defaultTemplate.id}` : 'blank';
            document.getElementById('lineupId').value = state.lineup.id || '';
            document.getElementById('lineupTitle').value = state.lineup.title || `Lineup for vs ${state.game.opponent}`;
            document.getElementById('lineupDefaultWrap').classList.add('d-none');
            document.getElementById('lineupEditorFeedback').className = 'd-none';
            const rule = state.batting_order_mode === 'fixed'
                ? `Fixed Lineup: ${Math.min(state.fixed_lineup_size, state.roster.length)} batters are required with today's availability.`
                : `Bat Everyone: all ${state.roster.length} available players are required.`;
            document.getElementById('lineupEditorSubtitle').textContent = rule;
            lineupEditorController?.destroy();
            lineupEditorController = initializeLineupEditor({
                roster: state.roster,
                lineup: state.lineup,
                benchEl: document.getElementById('lineup-bench'),
                orderEl: document.getElementById('lineup-order'),
                statusEl: document.getElementById('lineupEditorStatus')
            });
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
             const afterAlign = { ...beforeAlign };
             afterAlign['P'] = playerName;
             logLiveEvent('Pitcher Change', beforeAlign, afterAlign, null, player.id);
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

         const afterAlign = { ...beforeAlign };

         // 1. Remove new pitcher from their old spot if they were on the field
         let oldSpotOfNewPitcher = null;
         for (const [pos, name] of Object.entries(afterAlign)) {
             if (name === newPitcherName) oldSpotOfNewPitcher = pos;
         }
         if (oldSpotOfNewPitcher) afterAlign[oldSpotOfNewPitcher] = null;

         // 2. Put new pitcher at P
         afterAlign['P'] = newPitcherName;

         // 3. Put old pitcher at destination
         if (destinationPos === 'BENCH') {
             // Just removed from P, so they are effectively benched.
         } else {
             afterAlign[destinationPos] = oldPitcherName;
         }

         const oldPId = state.roster.find(p => p.name === oldPitcherName)?.id;
         const newPId = state.roster.find(p => p.name === newPitcherName)?.id;

         logLiveEvent('Pitcher Change', beforeAlign, afterAlign, oldPId, newPId);
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
