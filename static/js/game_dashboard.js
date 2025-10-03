// static/js/game_dashboard.js
// =================================================================================
// Coach Planner - Live Game Dashboard Client-Side Logic
// =================================================================================

function initializeLiveDashboard(gameData) {
    const socket = io();
    const gameId = gameData.game.id;

    // --- STATE ---
    const state = {
        isLive: gameData.game.game_status === 'live',
        score: {
            our_score: gameData.game.our_score || 0,
            opponent_score: gameData.game.opponent_score || 0
        },
        inning: gameData.game.inning || 1,
        outs: gameData.game.outs || 0,
        base_runners: {
            first: false,
            second: false,
            third: false
        },
        rotation: gameData.rotation || {},
        roster: gameData.roster || []
    };

    // --- DOM ELEMENTS ---
    const liveModeToggle = document.getElementById('live-mode-toggle');
    const planningContainer = document.getElementById('planning-mode-container');
    const liveContainer = document.getElementById('live-mode-container');
    const statusBadge = document.getElementById('game-status-badge');
    const subForm = document.getElementById('substitution-form');
    const subPositionSelect = document.getElementById('sub-position-select');
    const subPlayerInSelect = document.getElementById('sub-player-in-select');
    const subPlayerOutInfo = document.getElementById('sub-player-out-info');


    // --- RENDER FUNCTIONS ---
    function render() {
        // Show/hide containers based on live status
        if (state.isLive) {
            planningContainer.classList.add('d-none');
            liveContainer.classList.remove('d-none');
            liveModeToggle.checked = true;
            statusBadge.textContent = 'Live';
            statusBadge.classList.remove('bg-primary', 'bg-secondary');
            statusBadge.classList.add('bg-danger');
        } else {
            planningContainer.classList.remove('d-none');
            liveContainer.classList.add('d-none');
            liveModeToggle.checked = false;
            statusBadge.textContent = 'Pre-Game';
            statusBadge.classList.remove('bg-danger', 'bg-secondary');
            statusBadge.classList.add('bg-primary');
        }
        renderScoreboard();
        renderDefensiveView();
    }

    function renderScoreboard() {
        document.getElementById('live-our-score').textContent = state.score.our_score;
        document.getElementById('live-opponent-score').textContent = state.score.opponent_score;
        document.getElementById('live-inning').textContent = `Inning: ${state.inning}`;
        document.getElementById('live-outs').textContent = `Outs: ${state.outs}`;
        // Add logic for base runners if UI elements exist
    }

    function renderDefensiveView() {
        const defensiveViewContainer = document.getElementById('live-defensive-view');
        if (!defensiveViewContainer) return;

        const currentInningData = state.rotation.innings ? state.rotation.innings[state.inning] || {} : {};
        let html = '<ul class="list-group">';
        // Sort positions for consistent order
        const sortedPositions = Object.keys(currentInningData).sort();

        for (const pos of sortedPositions) {
            const playerName = currentInningData[pos];
            html += `<li class="list-group-item"><strong>${pos}:</strong> ${playerName}</li>`;
        }
        html += '</ul>';
        defensiveViewContainer.innerHTML = html;

        // Render the substitution panel after the defensive view is updated
        renderSubstitutionPanel();
    }

    function renderSubstitutionPanel() {
        if (!subPositionSelect || !subPlayerInSelect || !subPlayerOutInfo) return;

        const currentInningData = state.rotation.innings ? state.rotation.innings[state.inning] || {} : {};
        const playersOnField = new Set(Object.values(currentInningData));
        const benchPlayers = state.roster.filter(p => !playersOnField.has(p.name));
        const fieldPlayers = state.roster.filter(p => playersOnField.has(p.name));
        const positions = Object.keys(currentInningData).sort();

        // Populate positions dropdown
        subPositionSelect.innerHTML = '<option value="">Select Position...</option>' +
            positions.map(pos => `<option value="${pos}">${pos}</option>`).join('');

        // Populate players-in dropdown with groups
        const benchOptions = benchPlayers.map(p => `<option value="${p.name}">${p.name}</option>`).join('');
        const fieldOptions = fieldPlayers.map(p => {
            const currentPos = Object.keys(currentInningData).find(pos => currentInningData[pos] === p.name);
            return `<option value="${p.name}" data-current-pos="${currentPos}">${p.name} (at ${currentPos})</option>`;
        }).join('');

        subPlayerInSelect.innerHTML = `
            <option value="">Select Player...</option>
            ${benchOptions.length > 0 ? `<optgroup label="On the Bench">${benchOptions}</optgroup>` : ''}
            ${fieldOptions.length > 0 ? `<optgroup label="On the Field">${fieldOptions}</optgroup>` : ''}
        `;

        // Update player-out info when a position is selected
        subPositionSelect.onchange = () => {
            const selectedPos = subPositionSelect.value;
            if (selectedPos && currentInningData[selectedPos]) {
                subPlayerOutInfo.textContent = `Player out: ${currentInningData[selectedPos]}`;
                 // Don't allow selecting the same player you're subbing out
                for (const opt of subPlayerInSelect.options) {
                    opt.disabled = (opt.value === currentInningData[selectedPos]);
                }
            } else {
                subPlayerOutInfo.textContent = '';
                for (const opt of subPlayerInSelect.options) {
                    opt.disabled = false;
                }
            }
        };
        // Reset the player-out info initially
        subPlayerOutInfo.textContent = '';
    }


    // --- EVENT HANDLERS ---
    function handleToggleChange(event) {
        const newStatus = event.target.checked ? 'live' : 'pre-game';
        state.isLive = event.target.checked;
        render();
        fetch(`/game/${gameId}/status?status=${newStatus}`)
            .then(response => {
                if (!response.ok) {
                    state.isLive = !event.target.checked;
                    render();
                    alert('Failed to update game status.');
                }
            });
    }

    function handleScoreUpdate(field, delta) {
        if (field === 'our_score') {
            state.score.our_score = Math.max(0, state.score.our_score + delta);
        } else if (field === 'opponent_score') {
            state.score.opponent_score = Math.max(0, state.score.opponent_score + delta);
        } else if (field === 'inning') {
            state.inning = Math.max(1, state.inning + delta);
        } else if (field === 'outs') {
            state.outs += delta;
            if (state.outs > 2) {
                state.outs = 0;
                state.inning += 1;
            } else if (state.outs < 0) {
                state.outs = 0;
            }
        }
        renderScoreboard();
        socket.emit('game_update', { game_id: gameId, ...state });
    }

    function handleSubstitutionSubmit(event) {
        event.preventDefault();
        const posToChange = subPositionSelect.value;
        const selectedPlayerInOption = subPlayerInSelect.options[subPlayerInSelect.selectedIndex];
        const playerInName = selectedPlayerInOption.value;

        if (!posToChange || !playerInName) {
            alert('Please select a position and a player.');
            return;
        }

        const playerOutName = state.rotation.innings[state.inning][posToChange];
        const playerInCurrentPos = selectedPlayerInOption.dataset.currentPos;

        if (playerInCurrentPos) {
            // This is a SWAP between two players on the field
            socket.emit('swap_positions', {
                game_id: gameId,
                inning: state.inning,
                pos1: posToChange,
                player1_name: playerOutName,
                pos2: playerInCurrentPos,
                player2_name: playerInName
            });
        } else {
            // This is a standard SUBSTITUTION from the bench
            socket.emit('substitution', {
                game_id: gameId,
                inning: state.inning,
                position: posToChange,
                player_name: playerInName
            });
        }

        // Reset the form
        subForm.reset();
        subPlayerOutInfo.textContent = '';
    }

    // --- SOCKET.IO LISTENERS ---
    socket.on('connect', () => {
        console.log('Live dashboard connected to server.');
        socket.emit('join_game', { game_id: gameId });
    });

    socket.on('status_changed', (data) => {
        if (data.game_id === gameId) {
            state.isLive = data.status === 'live';
            render();
        }
    });

    socket.on('game_state_updated', (data) => {
        if (data.game_id === gameId) {
            state.score = data.score;
            state.inning = data.inning;
            state.outs = data.outs;
            renderScoreboard();
        }
    });

    socket.on('defensive_rotation_updated', (data) => {
        if (data.game_id === gameId) {
            state.rotation = data.rotation;
            renderDefensiveView();
        }
    });

    // --- INITIALIZATION ---
    function setupEventListeners() {
        liveModeToggle.addEventListener('change', handleToggleChange);

        // Scoreboard controls
        document.getElementById('our-score-plus').addEventListener('click', () => handleScoreUpdate('our_score', 1));
        document.getElementById('our-score-minus').addEventListener('click', () => handleScoreUpdate('our_score', -1));
        document.getElementById('opponent-score-plus').addEventListener('click', () => handleScoreUpdate('opponent_score', 1));
        document.getElementById('opponent-score-minus').addEventListener('click', () => handleScoreUpdate('opponent_score', -1));
        document.getElementById('inning-plus').addEventListener('click', () => handleScoreUpdate('inning', 1));
        document.getElementById('inning-minus').addEventListener('click', () => handleScoreUpdate('inning', -1));
        document.getElementById('outs-plus').addEventListener('click', () => handleScoreUpdate('outs', 1));

        // Add listener for the substitution form
        if (subForm) {
            subForm.addEventListener('submit', handleSubstitutionSubmit);
        }
    }

    render(); // Initial render
    setupEventListeners(); // Set up event listeners
}