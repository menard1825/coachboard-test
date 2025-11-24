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

        // Note: The original createPlayerTag is now modified to accept a player object
        const createPlayerTag = (player) => {
            const primaryPos = player.position1 ? ` (${escapeHTML(player.position1)})` : '';
            return `<div class="player-tag" data-player-name="${escapeHTML(player.name)}">${escapeHTML(player.name)}${primaryPos}</div>`;
        };

        // Modify the rendering of player tags on the diamond to pass the full player object
        document.querySelectorAll('.position-dropzone .player-tag').forEach(tag => tag.remove());
        for (const [pos, playerName] of Object.entries(currentInningData)) {
            const player = state.roster.find(p => p.name === playerName);
            if (player) {
                const dropzoneDesktop = document.getElementById(`pos-desktop-${pos}`);
                const dropzoneMobile = document.getElementById(`pos-mobile-${pos}`);
                if (dropzoneDesktop) dropzoneDesktop.insertAdjacentHTML('beforeend', createPlayerTag(player));
                if (dropzoneMobile) dropzoneMobile.insertAdjacentHTML('beforeend', createPlayerTag(player));
            }
        }

        // Update the bench rendering logic
        const assignedPlayers = new Set(Object.values(currentInningData));
        const benchPlayers = state.roster.filter(p => !assignedPlayers.has(p.name));
        const benchDesktop = document.getElementById('bench-list-desktop');
        if(benchDesktop) {
            // Pass the full player object to the updated createPlayerTag function
            benchDesktop.innerHTML = benchPlayers.map(p => createPlayerTag(p)).join('');
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

        const innings = Object.keys(state.rotation.innings || {}).sort((a, b) => parseInt(a) - parseInt(b));
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
        // NEW: Initialize the save template modal
        saveTemplateModal = new bootstrap.Modal(document.getElementById('saveRotationTemplateModal'));

        document.getElementById('saveLineupBtn')?.addEventListener('click', saveLineup);
        document.getElementById('saveRotationBtn')?.addEventListener('click', saveRotation);

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
                        state.currentInning = Object.keys(state.rotation.innings).sort((a,b) => parseInt(a) - parseInt(b))[0];
                        renderRotationEditor();
                        alert('Rotation template loaded successfully!');
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

        document.getElementById('clearInningBtn')?.addEventListener('click', () => {
            if (!state.rotation || !state.currentInning) return;
            if (confirm(`Are you sure you want to clear all positions for inning ${state.currentInning}?`)) {
                state.rotation.innings[state.currentInning] = {};
                renderRotationEditor();
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