// static/js/rotation_editor.js

function initializeRotationEditor(state, escapeHTML) {

    const POS_COORDS = {
        // Infield
        'P':  { x: 50, y: 61 },  // Pitcher's Mound
        'C':  { x: 50, y: 88 },  // Catcher
        '1B': { x: 77, y: 69 },  // First Base
        '2B': { x: 50, y: 48 },  // Second Base
        'SS': { x: 32, y: 55 },  // Shortstop
        '3B': { x: 23, y: 69 },  // Third Base

        // 3-Outfielder Setup
        'LF': { x: 18, y: 30 },  // Left Field
        'CF': { x: 50, y: 20 },  // Center Field
        'RF': { x: 82, y: 30 },  // Right Field

        // 4-Outfielder Setup
        'LCF':{ x: 35, y: 25 },  // Left-Center Field
        'RCF':{ x: 65, y: 25 }   // Right-Center Field
    };

    function renderRotationEditor() {
        if (!state.rotation) return;
        renderInningSelector();
        renderPositionList();
        renderDiamond();
        renderBenchAndSummary();
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
        const assignedPlayerNames = new Set(Object.values(currentInningData));

        let positions = ['P', 'C', '1B', '2B', '3B', 'SS'];
        if (state.outfielder_count === 4) {
            positions.push('LF', 'LCF', 'RCF', 'RF');
        } else {
            positions.push('LF', 'CF', 'RF');
        }

        container.innerHTML = positions.map(pos => {
            const assignedPlayerName = currentInningData[pos];
            const availablePlayers = state.roster.filter(p => !assignedPlayerNames.has(p.name) || p.name === assignedPlayerName);

            let options = availablePlayers.map(p =>
                `<option value="${escapeHTML(p.name)}" ${assignedPlayerName === p.name ? 'selected' : ''}>${escapeHTML(p.name)}</option>`
            ).join('');

            return `
                <div class="list-group-item d-flex justify-content-between align-items-center ps-2">
                    <span class="fw-bold me-3">${pos}</span>
                    <select class="form-select form-select-sm position-select" data-position="${pos}">
                        <option value="">-- Empty --</option>
                        ${options}
                    </select>
                </div>
            `;
        }).join('');

        container.querySelectorAll('.position-select').forEach(select => {
            select.addEventListener('change', handlePositionChange);
        });
    }

    function handlePositionChange(e) {
        const position = e.target.dataset.position;
        const newPlayerName = e.target.value;
        const currentInningData = state.rotation.innings[state.currentInning] || {};

        const oldPlayerAtPos = currentInningData[position];

        // Find if the new player was assigned elsewhere and clear that spot
        for (const [pos, name] of Object.entries(currentInningData)) {
            if (name === newPlayerName) {
                delete currentInningData[pos];
            }
        }

        if (newPlayerName) {
            currentInningData[position] = newPlayerName;
        } else {
            delete currentInningData[position];
        }

        renderRotationEditor();
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
                `<span class="badge bg-secondary me-1 mb-1">${escapeHTML(p.name)}</span>`
            ).join('');
        } else {
            benchContainer.innerHTML = `<p class="text-muted small">All players are on the field.</p>`;
        }
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

    renderRotationEditor();
    return renderRotationEditor;
}
