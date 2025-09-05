// static/js/rotation_editor.js

function initializeRotationEditor(state, escapeHTML) {

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
            const primaryPos = player.position1 ? ` (${escapeHTML(player.position1)})` : '';
            // MODIFIED: Add a check for pitcher status
            const pitchingSummary = (state.pitch_count_summary || {})[player.name];
            const isPitcherOnRest = (pitchingSummary && pitchingSummary.status === 'Resting');
            const pitcherClass = isPitcherOnRest ? 'pitcher-on-rest' : '';
            return `<div class="player-tag ${pitcherClass}" data-player-name="${escapeHTML(player.name)}">${escapeHTML(player.name)}${primaryPos}</div>`;
        };

        document.querySelectorAll('.position-dropzone').forEach(dz => {
            const desktopId = `pos-desktop-${dz.dataset.position}`;
            const mobileId = `pos-mobile-${dz.dataset.position}`;
            const desktopDz = document.getElementById(desktopId);
            const mobileDz = document.getElementById(mobileId);

            if (currentInningData[dz.dataset.position]) {
                // Player is assigned, add the player tag and 'has-player' class
                const player = state.roster.find(p => p.name === currentInningData[dz.dataset.position]);
                if (player) {
                    if (desktopDz) {
                        desktopDz.innerHTML = `<span class="pos-abbr d-none">${dz.dataset.position}</span>${createPlayerTag(player)}`;
                        desktopDz.classList.add('has-player');
                    }
                    if (mobileDz) {
                        mobileDz.innerHTML = `<span class="pos-abbr d-none">${dz.dataset.position}</span>${createPlayerTag(player)}`;
                        mobileDz.classList.add('has-player');
                    }
                }
            } else {
                // No player assigned, show the abbreviation and remove the class
                if (desktopDz) {
                    desktopDz.innerHTML = `<span class="pos-abbr">${dz.dataset.position}</span>`;
                    desktopDz.classList.remove('has-player');
                }
                if (mobileDz) {
                    mobileDz.innerHTML = `<span class="pos-abbr">${dz.dataset.position}</span>`;
                    mobileDz.classList.remove('has-player');
                }
            }
        });

        const assignedPlayers = new Set(Object.values(currentInningData));
        const benchPlayers = state.roster.filter(p => !assignedPlayers.has(p.name));
        const benchDesktop = document.getElementById('bench-list-desktop');
        if(benchDesktop) {
            benchDesktop.innerHTML = benchPlayers.length > 0
                ? benchPlayers.map(p => createPlayerTag(p)).join('')
                : '<div class="list-group-item text-muted text-center">Bench is empty</div>';
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
        if (sortedPlayerNames.length > 0) {
            for (const playerName of sortedPlayerNames) {
                const data = summary[playerName];
                if (!data) continue;
                tableHtml += `<tr><td><strong>${playerName}</strong></td><td>${data.inningsOnField}</td><td>${data.inningsOnBench}</td><td>${Array.from(data.positions).join(', ') || 'N/A'}</td></tr>`;
            }
        } else {
            tableHtml += '<tr><td colspan="4" class="text-center text-muted">No players on roster.</td></tr>';
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

    renderRotationEditor();
    // NEW: Return the main function so game_logic.js can call it later
    return renderRotationEditor;
}
