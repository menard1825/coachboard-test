// =================================================================================
// Coach Planner - Game Management Client-Side Logic (REFACTORED)
// =================================================================================

// This script is now fully self-contained and does not use a global AppState.

window.fetchWeatherForGame = async function(location, gameDate) {
    const weatherWidget = document.getElementById('weather-widget-content');
    if (!weatherWidget) return;

    weatherWidget.innerHTML = '<p><em>Fetching weather...</em></p>';

    if (!location) {
        weatherWidget.innerHTML = '<p class="text-muted">No location set for this game.</p>';
        return;
    }

    if (!gameDate) {
        weatherWidget.innerHTML = '<p class="text-danger">Error: Game date is missing.</p>';
        return;
    }

    const today = new Date().toISOString().split('T')[0];
    const isToday = gameDate.startsWith(today);
    const url = isToday
        ? `/api/weather/${encodeURIComponent(location)}`
        : `/api/weather/${encodeURIComponent(location)}?date=${gameDate}`;

    try {
        const response = await fetch(url);
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Failed to fetch weather. Status: ${response.status}. Details: ${errorText}`);
        }

        const weather = await response.json();
        if (!weather) {
            throw new Error("Received empty weather data.");
        }

        const tempDisplay = isToday ? weather.current_temp : `High/Low: ${weather.high_temp} / ${weather.low_temp}`;

        weatherWidget.innerHTML = `
            <p>
                <strong>${isToday ? 'Current' : 'Forecast'}:</strong> ${tempDisplay || 'N/A'}, ${weather.condition || 'N/A'} <br>
                <strong>Wind:</strong> ${weather.wind || 'N/A'} <br>
                <strong>Precipitation:</strong> ${weather.precipitation || 'N/A'}
            </p>
        `;
    } catch (error) {
        weatherWidget.innerHTML = `<p class="text-danger">Could not load weather data.</p><p class="text-muted small">${error.message}</p>`;
        console.error('Weather fetch error:', error);
    }
}

window.initializeGameManagement = function(gameData) {

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
        pitch_count_summary: gameData.pitch_count_summary,
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
    let editQuickNoteModal;
    let renderRotationEditor; // ADD THIS LINE TO DECLARE THE FUNCTION

    async function saveLineup() {
        const btn = document.getElementById('saveLineupBtn');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Saving...`;
        state.lineup.title = document.getElementById('lineupTitle').value;
        state.lineup.lineup_positions = Array.from(document.querySelectorAll('#lineup-order .list-group-item')).map(item => item.dataset.playerName);
        const url = state.lineup.id ? `/edit_lineup/${state.lineup.id}` : '/add_lineup';
        const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content'); // Added CSRF Token
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken // Added CSRF Token
                },
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

    // *** MODIFICATION START ***
    // Retrieve the CSRF token from the meta tag in the page's <head>
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    // *** MODIFICATION END ***

        const payload = {
            id: state.rotation.id,
            title: state.rotation.title || `Rotation for vs ${state.game.opponent}`,
            innings: state.rotation.innings,
            associated_game_id: state.game.id
        };
        try {
            const response = await fetch('/save_rotation', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: JSON.stringify(payload)
            });
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
        saveTemplateModal = new bootstrap.Modal(document.getElementById('saveRotationTemplateModal'));
        editQuickNoteModal = new bootstrap.Modal(document.getElementById('editQuickNoteModal'));

        document.getElementById('saveLineupBtn')?.addEventListener('click', saveLineup);
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
            renderRotationEditor();
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

        const quickNotesList = document.getElementById('quickNotesList');
        const editQuickNoteForm = document.getElementById('editQuickNoteForm');

        if (quickNotesList) {
            quickNotesList.addEventListener('click', (e) => {
                const editBtn = e.target.closest('.edit-quick-note-btn');
                if (editBtn) {
                    const noteItem = editBtn.closest('.list-group-item');
                    const noteId = noteItem.dataset.noteId;
                    const noteText = noteItem.querySelector('.note-text').textContent;

                    editQuickNoteForm.action = `/game/quick_note/${noteId}`;
                    editQuickNoteForm.querySelector('#editQuickNoteText').value = noteText;
                }
            });
        }

        if (editQuickNoteForm) {
            editQuickNoteForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const form = e.target;
                const btn = form.querySelector('button[type="submit"]');
                const originalBtnHtml = btn.innerHTML;
                const noteId = form.action.split('/').pop();

                btn.disabled = true;
                btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Saving...`;

                const formData = new FormData(form);

                try {
                    const response = await fetch(form.action, { method: 'POST', body: formData });
                    const result = await response.json();
                    if (!response.ok) throw new Error(result.message);

                    const noteItem = quickNotesList.querySelector(`.list-group-item[data-note-id='${noteId}']`);
                    if (noteItem) {
                        noteItem.querySelector('.note-text').textContent = result.note.text;
                    }
                    editQuickNoteModal.hide();
                } catch (error) {
                    alert(`Error: ${error.message}`);
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = originalBtnHtml;
                }
            });
        }
    }

    // --- Initial Page Render ---
    if(state.game) {
        // MODIFIED: Capture the function returned by initializeRotationEditor
        renderRotationEditor = initializeRotationEditor(state, escapeHTML);
        setupEventListeners();
        fetchWeatherForGame(state.game.location, gameData.game_date_for_input);

        const editGameModal = document.getElementById('editGameModal');
        if (editGameModal) {
            const gameLocationInputModal = editGameModal.querySelector('#game_location');
            if (gameLocationInputModal) {
                editGameModal.addEventListener('shown.bs.modal', () => {
                    setupAutocomplete(gameLocationInputModal);
                });
            }
        }

    } else {
        console.error("Game data was not provided to initialize the page.");
        document.getElementById('rotation-board').innerHTML = '<div class="alert alert-danger">Could not load game data. Please go back and try again.</div>';
    }
}