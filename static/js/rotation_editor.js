// static/js/rotation_editor.js

function initializeRotationEditor(state, escapeHTML) {
 
    const POS_COORDS = {
        // Infield
        'P': { x: 50, y: 61 }, // Pitcher's Mound
        'C':  { x: 50, y: 85 },  // Catcher
        '1B': { x: 69, y: 65 },  // First Base
        '2B': { x: 50, y: 50 },  // Second Base
        '3B': { x: 30, y: 65 },  // Third Base
        'SS': { x: 38, y: 53 },  // Shortstop

        // 3-Outfielder Setup
        'LF': { x: 18, y: 30 },  // Left Field
        'CF': { x: 50, y: 20 },  // Center Field
        'RF': { x: 82, y: 30 },  // Right Field

        // 4-Outfielder Setup
        'LCF':{ x: 35, y: 25 },  // Left-Center Field
        'RCF':{ x: 65, y: 25 }   // Right-Center Field
    }

    function renderRotationEditor() {
        if (!state.rotation) return;
        renderInningSelector();
        renderPositionList();
        renderDiamond();
        renderBenchAndSummary();
        addDragDropListeners();
        updatePlayingTimeSummary();
    }

    function renderInningSelector() {
        const container = document.getElementById('inning-btn-group');
        const display = document.getElementById('current-inning-display');
        const innings = Object.keys(state.rotation.innings || {}).map(Number).sort((a, b) => a - b);
        if (innings.length === 0) {
            state.rotation.innings['1'] = {};
            innings.push(1);
        }
        if (!state.currentInning || !state.rotation.innings[state.currentInning]) {
             state.currentInning = innings[0];
        }

        container.innerHTML = innings.map(inn => `
            <input type="radio" class="btn-check" name="inning-radio" id="inning-${inn}" value="${inn}" ${state.currentInning == inn ? 'checked' : ''}>
            <label class="btn btn-outline-primary" for="inning-${inn}">${inn}</label>
        `).join('');

        if (display) display.textContent = state.currentInning;

        container.querySelectorAll('input[name="inning-radio"]').forEach(radio => {
            radio.addEventListener('change', (e) => {
                state.currentInning = e.target.value;
                renderRotationEditor();
            });
        });
    }

    function renderPositionList() {
        const container = document.getElementById('position-assignment-list');
        const currentInningData = state.rotation.innings[state.currentInning] || {};

        let positions = ['P', 'C', '1B', '2B', '3B', 'SS'];
        if (state.outfielder_count === 4) {
            positions.push('LF', 'LCF', 'RCF', 'RF');
        } else {
            positions.push('LF', 'CF', 'RF');
        }

        container.innerHTML = positions.map(pos => {
            const assignedPlayerName = currentInningData[pos];
            const playerTagHtml = assignedPlayerName
                ? `<div class="player-tag" data-player-name="${escapeHTML(assignedPlayerName)}" draggable="true">${escapeHTML(assignedPlayerName)}</div>`
                : '';

            return `
                <div class="list-group-item d-flex justify-content-between align-items-center ps-2 position-drop-item" data-position="${pos}">
                    <span class="fw-bold me-3">${pos}</span>
                    <div class="player-slot flex-grow-1">${playerTagHtml}</div>
                </div>
            `;
        }).join('');
    }

    function renderDiamond() {
        const svg = document.getElementById('baseball-diamond-svg');
        if (!svg) return;

        // Clear existing player tokens
        svg.querySelectorAll('.player-token').forEach(el => el.remove());

        const currentInningData = state.rotation.innings[state.currentInning] || {};

        for (const [pos, playerName] of Object.entries(currentInningData)) {
            const player = state.roster.find(p => p.name === playerName);
            if (!player || !POS_COORDS[pos]) continue;

            let posClass = 'other-pos';
            if (player.position1 === pos) posClass = 'natural-pos';
            else if (player.position2 === pos || player.position3 === pos) posClass = 'secondary-pos';

            const tokenGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            tokenGroup.setAttribute('class', `player-token ${posClass}`);
            tokenGroup.setAttribute('transform', `translate(${POS_COORDS[pos].x}, ${POS_COORDS[pos].y})`);

            const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            circle.setAttribute('r', '5');
            circle.setAttribute('class', 'player-token-circle');

            const numText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            numText.setAttribute('class', 'player-token-text-num');
            numText.setAttribute('y', '0.5');
            numText.textContent = `#${player.number || ''}`;

            const nameText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            nameText.setAttribute('class', 'player-token-text-name');
            nameText.setAttribute('y', '3');
            nameText.textContent = player.name.split(' ')[0]; // First name

            tokenGroup.appendChild(circle);
            tokenGroup.appendChild(numText);
            tokenGroup.appendChild(nameText);
            svg.appendChild(tokenGroup);
        }
    }

    function renderBenchAndSummary() {
        const benchContainer = document.getElementById('bench-list-visual');
        const currentInningData = state.rotation.innings[state.currentInning] || {};
        const assignedPlayers = new Set(Object.values(currentInningData));
        const benchPlayers = state.roster.filter(p => !assignedPlayers.has(p.name));

        if (benchPlayers.length > 0) {
            benchContainer.innerHTML = benchPlayers.map(p =>
                `<div class="player-tag" data-player-name="${escapeHTML(p.name)}" draggable="true">${escapeHTML(p.name)}</div>`
            ).join('');
        } else {
            benchContainer.innerHTML = `<p class="text-muted small p-2">All players are on the field.</p>`;
        }
        updatePlayingTimeSummary();
    }

    function updatePlayingTimeSummary() {
        const summaryContainer = document.getElementById('summary-visual');
        const summary = {};
        state.roster.forEach(player => {
            summary[player.name] = { name: player.name, inningsOnField: 0, positions: new Set() };
        });

        Object.values(state.rotation.innings || {}).forEach(inningData => {
            for (const [pos, playerName] of Object.entries(inningData)) {
                if (summary[playerName]) {
                    summary[playerName].inningsOnField++;
                    summary[playerName].positions.add(pos);
                }
            }
        });

        const sortedPlayerNames = state.roster.map(p => p.name).sort();
        let tableHtml = `<div class="table-responsive"><table class="table table-sm table-striped" style="font-size: 0.8rem;"><thead><tr><th>Player</th><th>Innings</th><th>Positions</th></tr></thead><tbody>`;

        if (sortedPlayerNames.length > 0) {
            for (const playerName of sortedPlayerNames) {
                const data = summary[playerName];
                if (!data) continue;
                tableHtml += `<tr><td><strong>${playerName}</strong></td><td>${data.inningsOnField}</td><td>${Array.from(data.positions).join(', ') || 'N/A'}</td></tr>`;
            }
        } else {
            tableHtml += '<tr><td colspan="3" class="text-center text-muted">No players.</td></tr>';
        }
        tableHtml += `</tbody></table></div>`;
        summaryContainer.innerHTML = tableHtml;
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
        renderRotationEditor();
    });

    document.getElementById('cancelPasteBtn')?.addEventListener('click', exitCopyMode);

    function addDragDropListeners() {
        const rotationBoard = document.getElementById('rotation-board');
        if (!rotationBoard || rotationBoard.dataset.listenersAttached) return;
        rotationBoard.dataset.listenersAttached = 'true';
        
        let draggedPlayerName = null;

        rotationBoard.addEventListener('dragstart', (e) => {
            if (e.target.classList.contains('player-tag')) {
                draggedPlayerName = e.target.dataset.playerName;
                e.dataTransfer.setData('text/plain', draggedPlayerName);
                setTimeout(() => e.target.classList.add('dragging'), 0);
            }
        });

        rotationBoard.addEventListener('dragend', (e) => {
            if (e.target.classList.contains('player-tag')) {
                e.target.classList.remove('dragging');
            }
            draggedPlayerName = null;
        });

        rotationBoard.addEventListener('dragover', (e) => {
            const dropZone = e.target.closest('.position-drop-item, #bench-list-visual');
            if (dropZone) {
                e.preventDefault();
                document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
                dropZone.classList.add('drag-over');
            }
        });

        rotationBoard.addEventListener('dragleave', (e) => {
            const dropZone = e.target.closest('.position-drop-item, #bench-list-visual');
            if (dropZone) {
                dropZone.classList.remove('drag-over');
            }
        });

        rotationBoard.addEventListener('drop', (e) => {
            e.preventDefault();
            document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
            const dropZone = e.target.closest('.position-drop-item, #bench-list-visual');
            
            if (dropZone && draggedPlayerName) {
                const currentInningData = state.rotation.innings[state.currentInning] || {};

                let oldPosition = null;
                for (const pos in currentInningData) {
                    if (currentInningData[pos] === draggedPlayerName) {
                        oldPosition = pos;
                        break;
                    }
                }
                if (oldPosition) {
                    delete currentInningData[oldPosition];
                }

                if (dropZone.id === 'bench-list-visual') {
                    // Player was dropped on the bench, we're done.
                } else {
                    const targetPosition = dropZone.dataset.position;
                    const displacedPlayer = currentInningData[targetPosition];
                    
                    currentInningData[targetPosition] = draggedPlayerName;
                    
                    if (displacedPlayer && oldPosition) {
                        currentInningData[oldPosition] = displacedPlayer;
                    }
                }
                renderRotationEditor();
            }
        });
    }

    renderRotationEditor();
    return renderRotationEditor;
}
