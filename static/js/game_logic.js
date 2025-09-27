// static/js/game_logic.js
// =================================================================================
// Coach Planner - Game Management Client-Side Logic (REFACTORED)
// =================================================================================

// This script is now fully self-contained and does not use a global AppState.
const escapeHTML = str => String(str).replace(/[&<>'"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;',"'": '&#39;','"': '&quot;'}[tag] || tag));

/**
 * NEW: A debounce function to delay execution.
 * This prevents the save function from being called on every single little change,
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


function initializeGameManagement(gameData) {

    // --- Page-Specific State ---
    // All data for this page is stored in a local 'state' object.
    const state = {
        roster: (gameData.roster || []).filter(p => !(gameData.absent_player_ids || []).includes(p.id)),
        lineup: gameData.lineup || { id: null, title: `Lineup for vs ${gameData.game.opponent}`, lineup_positions: [], associated_game_id: gameData.game.id },
        rotation: gameData.rotation || { id: null, title: `Rotation for vs ${gameData.game.opponent}`, innings: { '1': {} }, associated_game_id: gameData.game.id },
        game: gameData.game,
        lineup_templates: gameData.lineup_templates || [],
        rotation_templates: gameData.rotation_templates || [],
        outfielder_count: gameData.outfielder_count || 3,
        currentInning: '1',
        copiedInningData: null,
        sortableInstances: {},
        hasUnsavedChanges: false // NEW: Track unsaved changes for the rotation
    };

    if (state.rotation && typeof state.rotation.innings === 'string') {
        try {
            state.rotation.innings = JSON.parse(state.rotation.innings);
        } catch (e) {
            console.error("Error parsing rotation.innings JSON:", e);
            state.rotation.innings = { '1': {} };
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

        const createPlayerTag = (player) => {
            return `<div class="player-tag" data-player-name="${escapeHTML(player.name)}">${escapeHTML(player.name)}</div>`;
        };

        const createMobileBenchPlayerItem = (player) => {
            const primaryPos = player.position1 || 'N/A';
            const secondaryPos = player.position2 || 'N/A';
            return `<div class="list-group-item d-flex justify-content-between align-items-center">
                    <span>${escapeHTML(player.name)}</span>
                    <small class="text-muted">Pos: ${escapeHTML(primaryPos)} / ${escapeHTML(secondaryPos)}</small>
                </div>`;
        };

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

        const assignedPlayers = new Set(Object.values(currentInningData));
        const benchPlayers = state.roster.filter(p => !assignedPlayers.has(p.name));

        const benchDesktop = document.getElementById('bench-list-desktop');
        if(benchDesktop) {
            benchDesktop.innerHTML = benchPlayers.map(p => createPlayerTag(p)).join('');
        }

        const benchMobile = document.getElementById('bench-list-mobile');
        if (benchMobile) {
            benchMobile.innerHTML = benchPlayers.length > 0 ? benchPlayers.map(p => createMobileBenchPlayerItem(p)).join('') : '<div class="list-group-item text-muted">All players are on the field.</div>';
        }
        const mobileInningNumber = document.getElementById('mobile-bench-inning-number');
        if(mobileInningNumber){
            mobileInningNumber.textContent = state.currentInning;
        }

        applyOutOfPositionIndicators();
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

    // MODIFIED: Create a debounced save function that will be called after 2 seconds of inactivity
    const debouncedSave = debounce(() => saveRotation(), 2000);

    function initializeRotationSortables() {
        Object.values(state.sortableInstances).forEach(s => { if (s.destroy) s.destroy(); });
        state.sortableInstances = {};

        // MODIFIED: This handler now updates state and triggers the auto-save
        const onEndHandler = () => {
            const inningData = state.rotation.innings[state.currentInning] = {};
            document.querySelectorAll('#diamond-parent-desktop .position-dropzone').forEach(dz => {
                const playerTag = dz.querySelector('.player-tag');
                if (playerTag) {
                    inningData[dz.dataset.position] = playerTag.dataset.playerName;
                }
            });

            // Mark that we have changes and trigger the debounced save
            state.hasUnsavedChanges = true;
            const saveBtn = document.getElementById('saveRotationBtn');
            if (saveBtn) {
                saveBtn.innerHTML = '<i class="bi bi-save me-1"></i> Save Rotation'; // Reset button text on new change
                saveBtn.classList.remove('btn-success');
            }
            debouncedSave();

            renderRotationEditor(); // Re-render immediately for UI responsiveness
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
            tag.classList.remove('natural-position', 'secondary-position');

            if (player && position) {
                const primaryPos = player.position1;
                const secondaryPositions = [player.position2, player.position3];

                if (position === primaryPos) {
                    tag.classList.add('natural-position');
                } else if (secondaryPositions.includes(position)) {
                    tag.classList.add('secondary-position');
                }
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
    
    // MODIFIED: This function now provides visual feedback
    async function saveRotation() {
        const btn = document.getElementById('saveRotationBtn');
        if (!btn) return;

        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Saving...';
        btn.classList.remove('btn-success');

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

                // Success feedback
                btn.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i> Saved';
                btn.classList.add('btn-success');
                state.hasUnsavedChanges = false;

                // Re-enable the delete button if a rotation was just created
                document.getElementById('deleteRotationBtn')?.removeAttribute('disabled');

            } else { throw new Error(result.message); }
        } catch (error) {
            // Error feedback
            btn.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-1"></i> Save Failed';
            alert('Error saving rotation: ' + error.message);
        } finally {
            btn.disabled = false;
            // The button text will be reset to normal when a new change is made.
        }
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        assignPlayerModal = new bootstrap.Modal(document.getElementById('assignPlayerModal'));
        lineupEditorModal = new bootstrap.Modal(document.getElementById('lineupEditorModal'));
        saveTemplateModal = new bootstrap.Modal(document.getElementById('saveRotationTemplateModal'));

        // The manual save button still works if a user wants to save immediately
        document.getElementById('saveRotationBtn')?.addEventListener('click', saveRotation);

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
                        state.rotation.innings = JSON.parse(JSON.stringify(selectedTemplate.innings));
                        if (Object.keys(state.rotation.innings).length === 0) {
                            state.rotation.innings['1'] = {};
                        }
                        state.currentInning = Object.keys(state.rotation.innings).sort((a,b) => parseInt(a) - parseInt(b))[0];

                        state.hasUnsavedChanges = true; // Mark as changed and save
                        debouncedSave();

                        renderRotationEditor();
                        alert('Rotation template loaded successfully!');
                    }
                    e.target.value = '';
                }
            });
        }

        document.getElementById('saveAsTemplateBtn')?.addEventListener('click', () => {
            const suggestedName = `Template from vs ${state.game.opponent}`;
            document.getElementById('rotationTemplateName').value = suggestedName;
            saveTemplateModal.show();
        });

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

                const select = document.getElementById('rotationTemplateSelect');
                if (select && result.new_template) {
                     const newTemplate = result.new_template;
                     state.rotation_templates.push(newTemplate);
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

                state.hasUnsavedChanges = true;
                debouncedSave();
                renderRotationEditor();
            }
            const modalPlayerLink = event.target.closest('#assignPlayerModalBenchList a');
            if (modalPlayerLink) {
                event.preventDefault();
                const playerName = modalPlayerLink.dataset.playerName;
                const position = document.getElementById('assignPlayerModal').dataset.targetPosition;
                if (playerName && position) {
                    state.rotation.innings[state.currentInning][position] = playerName;
                    state.hasUnsavedChanges = true;
                    debouncedSave();
                    renderRotationEditor();
                    assignPlayerModal.hide();
                }
            }
        });

        const changeInningCount = (amount) => {
            if (!state.rotation) return;
            const innings = Object.keys(state.rotation.innings);
            if (amount < 0 && innings.length <= 1) {
                alert("Cannot remove the last inning.");
                return;
            }
            const nextInningNum = innings.length > 0 ? Math.max(...innings.map(Number)) + 1 : 1;
            if (amount > 0) {
                 state.rotation.innings[nextInningNum] = {};
            } else {
                 const lastInningNum = Math.max(...innings.map(Number));
                 delete state.rotation.innings[lastInningNum];
                 if (state.currentInning == lastInningNum) {
                     state.currentInning = Math.max(...Object.keys(state.rotation.innings).map(Number));
                 }
            }
             state.hasUnsavedChanges = true;
             debouncedSave();
             renderRotationEditor();
        };

        document.getElementById('addInningBtn')?.addEventListener('click', () => changeInningCount(1));
        document.getElementById('removeInningBtn')?.addEventListener('click', () => changeInningCount(-1));

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
            state.hasUnsavedChanges = true;
            debouncedSave();
            exitCopyMode();
            updatePlayingTimeSummary();
        });
        document.getElementById('cancelPasteBtn')?.addEventListener('click', exitCopyMode);

        document.getElementById('clearInningBtn')?.addEventListener('click', () => {
            if (!state.rotation || !state.currentInning) return;
            if (confirm(`Are you sure you want to clear all positions for inning ${state.currentInning}?`)) {
                state.rotation.innings[state.currentInning] = {};
                state.hasUnsavedChanges = true;
                debouncedSave();
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
                    state.hasUnsavedChanges = true;
                    debouncedSave();
                    renderRotationEditor();
                }
            } else {
                alert(`Inning ${previousInningNum} has no data to copy.`);
            }
        });

        // NEW: Add beforeunload event listener as a safeguard
        window.addEventListener('beforeunload', (event) => {
            if (state.hasUnsavedChanges) {
                // Standard way to trigger the browser's confirmation dialog
                event.preventDefault();
                event.returnValue = ''; // This is required for older browsers
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