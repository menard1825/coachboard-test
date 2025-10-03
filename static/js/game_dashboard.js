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
        inning: gameData.game.inning || 1,
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
    const inningDisplay = document.getElementById('live-inning-display');


    // --- RENDER FUNCTIONS ---
    function render() {
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
        renderDefensiveView();
    }

    function renderDefensiveView() {
        const currentInningData = state.rotation.innings ? state.rotation.innings[state.inning] || {} : {};

        // Update inning display
        if(inningDisplay) inningDisplay.textContent = state.inning;

        // Clear existing player tags
        document.querySelectorAll('.diamond-container-interactive .player-tag').forEach(tag => tag.remove());

        // Add new player tags
        for (const [pos, playerName] of Object.entries(currentInningData)) {
            const dropzone = document.getElementById(`pos-live-${pos}`);
            if (dropzone) {
                const playerTag = document.createElement('div');
                playerTag.className = 'player-tag';
                playerTag.textContent = playerName;
                dropzone.appendChild(playerTag);
            }
        }

        renderSubstitutionPanel();
    }

    function renderSubstitutionPanel() {
        if (!subPositionSelect || !subPlayerInSelect || !subPlayerOutInfo) return;

        const currentInningData = state.rotation.innings ? state.rotation.innings[state.inning] || {} : {};
        const playersOnField = new Set(Object.values(currentInningData));
        const benchPlayers = state.roster.filter(p => !playersOnField.has(p.name));
        const fieldPlayers = state.roster.filter(p => playersOnField.has(p.name));
        const positions = Object.keys(currentInningData).sort();

        subPositionSelect.innerHTML = '<option value="">Select Position...</option>' +
            positions.map(pos => `<option value="${pos}">${pos}</option>`).join('');

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

        subPositionSelect.onchange = () => {
            const selectedPos = subPositionSelect.value;
            if (selectedPos && currentInningData[selectedPos]) {
                subPlayerOutInfo.textContent = `Player out: ${currentInningData[selectedPos]}`;
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
            socket.emit('swap_positions', {
                game_id: gameId,
                inning: state.inning,
                pos1: posToChange,
                player1_name: playerOutName,
                pos2: playerInCurrentPos,
                player2_name: playerInName
            });
        } else {
            socket.emit('substitution', {
                game_id: gameId,
                inning: state.inning,
                position: posToChange,
                player_name: playerInName
            });
        }
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

    socket.on('defensive_rotation_updated', (data) => {
        if (data.game_id === gameId) {
            state.rotation = data.rotation;
            // A swap or sub might change the current inning if not handled carefully
            // For now, we assume the inning stays the same unless a game_state_updated event says otherwise.
            renderDefensiveView();
        }
    });

    // --- INITIALIZATION ---
    function setupEventListeners() {
        liveModeToggle.addEventListener('change', handleToggleChange);
        if (subForm) {
            subForm.addEventListener('submit', handleSubstitutionSubmit);
        }
    }

    render();
    setupEventListeners();
}