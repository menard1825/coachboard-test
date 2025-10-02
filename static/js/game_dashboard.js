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
        for (const [pos, playerName] of Object.entries(currentInningData)) {
            html += `<li class="list-group-item"><strong>${pos}:</strong> ${playerName}</li>`;
        }
        html += '</ul>';
        defensiveViewContainer.innerHTML = html;
    }

    // --- EVENT HANDLERS ---
    function handleToggleChange(event) {
        const newStatus = event.target.checked ? 'live' : 'pre-game';
        // Optimistically update UI
        state.isLive = event.target.checked;
        render();
        // Notify server
        fetch(`/game/${gameId}/status?status=${newStatus}`)
            .then(response => {
                if (!response.ok) {
                    // Revert on failure
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

    // --- SOCKET.IO LISTENERS ---
    socket.on('connect', () => {
        console.log('Live dashboard connected to server.');
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
    }

    render(); // Initial render
    setupEventListeners(); // Set up event listeners
}