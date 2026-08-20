// Optional Fair Play Assistant for rec / younger travel teams.
// This MVP is intentionally client-side only so it cannot affect saved rotations,
// live-game state, pitching rules, or database migrations.
(function () {
    'use strict';

    const DEFAULTS = {
        enabled: false,
        minInfieldInnings: 1,
        maxConsecutiveBench: 1,
        infieldPositions: ['1B', '2B', '3B', 'SS']
    };

    let settings = { ...DEFAULTS };
    let storageKey = 'coachboard-fair-play-assistant';
    let matrixObserver = null;
    let renderTimer = null;

    function getTeamKey() {
        const heading = document.querySelector('#pregame-checklist-container h3');
        const headingText = heading ? heading.textContent.trim() : 'team';
        const teamName = headingText.split(/\s+vs\s+/i)[0] || 'team';
        return teamName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'team';
    }

    function loadSettings() {
        storageKey = `coachboard-fair-play-assistant:${getTeamKey()}`;
        try {
            const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
            settings = {
                ...DEFAULTS,
                ...saved,
                infieldPositions: Array.isArray(saved.infieldPositions)
                    ? saved.infieldPositions
                    : [...DEFAULTS.infieldPositions]
            };
        } catch (error) {
            console.warn('Could not load Fair Play Assistant settings:', error);
            settings = { ...DEFAULTS, infieldPositions: [...DEFAULTS.infieldPositions] };
        }
    }

    function saveSettings() {
        try {
            localStorage.setItem(storageKey, JSON.stringify(settings));
        } catch (error) {
            console.warn('Could not save Fair Play Assistant settings:', error);
        }
    }

    function ensureModal() {
        if (document.getElementById('fairPlayAssistantModal')) return;

        document.body.insertAdjacentHTML('beforeend', `
            <div class="modal fade" id="fairPlayAssistantModal" tabindex="-1" aria-labelledby="fairPlayAssistantModalLabel" aria-hidden="true">
                <div class="modal-dialog modal-dialog-scrollable">
                    <div class="modal-content">
                        <div class="modal-header">
                            <div>
                                <h5 class="modal-title" id="fairPlayAssistantModalLabel">
                                    <i class="bi bi-people-fill me-2"></i>Fair Play Assistant
                                </h5>
                                <div class="small text-muted">Optional playing-time help for rec and younger teams.</div>
                            </div>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div class="alert alert-light border small mb-3">
                                This assistant only reviews the defensive rotation you already built. It never changes a position, blocks a save, or changes live-game data.
                            </div>

                            <div class="form-check form-switch border rounded p-3 ps-5 mb-3">
                                <input class="form-check-input" type="checkbox" id="fairPlayEnabled">
                                <label class="form-check-label fw-semibold" for="fairPlayEnabled">Enable Fair Play Assistant</label>
                                <div class="small text-muted">When off, CoachBoard shows no fair-play alerts.</div>
                            </div>

                            <div id="fairPlaySettingsFields">
                                <div class="mb-3">
                                    <label for="fairPlayMinInfield" class="form-label fw-semibold">Minimum infield innings per player</label>
                                    <input type="number" class="form-control" id="fairPlayMinInfield" min="0" max="9" step="1">
                                    <div class="form-text">Set to 0 to turn off the infield requirement.</div>
                                </div>

                                <div class="mb-3">
                                    <label for="fairPlayMaxBench" class="form-label fw-semibold">Maximum consecutive bench innings</label>
                                    <select class="form-select" id="fairPlayMaxBench">
                                        <option value="0">Do not check this</option>
                                        <option value="1">1 inning</option>
                                        <option value="2">2 innings</option>
                                        <option value="3">3 innings</option>
                                    </select>
                                </div>

                                <div class="mb-2">
                                    <div class="form-label fw-semibold mb-1">Positions that count as infield</div>
                                    <div class="small text-muted mb-2">League rules vary, so choose what counts for your team.</div>
                                    <div class="d-flex flex-wrap gap-2" id="fairPlayPositionChoices">
                                        ${['P', 'C', '1B', '2B', '3B', 'SS'].map(pos => `
                                            <div class="form-check border rounded px-3 py-2">
                                                <input class="form-check-input fair-play-pos" type="checkbox" value="${pos}" id="fairPlayPos${pos.replace(/[^A-Z0-9]/g, '')}">
                                                <label class="form-check-label" for="fairPlayPos${pos.replace(/[^A-Z0-9]/g, '')}">${pos}</label>
                                            </div>
                                        `).join('')}
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                            <button type="button" class="btn btn-primary" id="fairPlaySaveSettings">Save Settings</button>
                        </div>
                    </div>
                </div>
            </div>
        `);

        document.getElementById('fairPlayEnabled').addEventListener('change', updateSettingsFieldState);
        document.getElementById('fairPlaySaveSettings').addEventListener('click', handleSaveSettings);

        document.getElementById('fairPlayAssistantModal').addEventListener('show.bs.modal', populateModalFromSettings);
    }

    function ensureMenuItem() {
        if (document.getElementById('fairPlayMenuItem')) return;

        const rotationCard = document.querySelector('#rotation-card-container .card');
        const menu = rotationCard ? rotationCard.querySelector('.card-header .dropdown-menu') : null;
        if (!menu) return;

        const item = document.createElement('li');
        item.id = 'fairPlayMenuItem';
        item.innerHTML = `
            <a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#fairPlayAssistantModal">
                <i class="bi bi-people me-1"></i> Fair Play Assistant
                <span class="badge text-bg-light border ms-1">Optional</span>
            </a>
        `;
        menu.appendChild(item);
    }

    function ensureStatusBar() {
        if (document.getElementById('fairPlayStatusBar')) return;

        const rotationBoard = document.getElementById('rotation-board');
        if (!rotationBoard || !rotationBoard.parentElement) return;

        rotationBoard.insertAdjacentHTML('beforebegin', `
            <div id="fairPlayStatusBar" class="px-3 pt-3 d-none">
                <div class="alert alert-light border shadow-sm mb-0" role="status">
                    <div class="d-flex flex-column flex-md-row gap-2 justify-content-between align-items-md-center">
                        <div>
                            <div class="fw-semibold"><i class="bi bi-people-fill me-1"></i> Fair Play</div>
                            <div class="small" id="fairPlayStatusText">Reviewing rotation...</div>
                        </div>
                        <button type="button" class="btn btn-sm btn-outline-primary flex-shrink-0" data-bs-toggle="modal" data-bs-target="#fairPlayAssistantModal">Settings</button>
                    </div>
                    <div id="fairPlayDetails" class="mt-2"></div>
                </div>
            </div>
        `);
    }

    function populateModalFromSettings() {
        const enabled = document.getElementById('fairPlayEnabled');
        const minInfield = document.getElementById('fairPlayMinInfield');
        const maxBench = document.getElementById('fairPlayMaxBench');
        if (!enabled || !minInfield || !maxBench) return;

        enabled.checked = Boolean(settings.enabled);
        minInfield.value = Number.isFinite(Number(settings.minInfieldInnings)) ? Number(settings.minInfieldInnings) : 1;
        maxBench.value = String(Number.isFinite(Number(settings.maxConsecutiveBench)) ? Number(settings.maxConsecutiveBench) : 1);

        document.querySelectorAll('.fair-play-pos').forEach(input => {
            input.checked = settings.infieldPositions.includes(input.value);
        });

        updateSettingsFieldState();
    }

    function updateSettingsFieldState() {
        const enabled = document.getElementById('fairPlayEnabled');
        const fields = document.getElementById('fairPlaySettingsFields');
        if (!enabled || !fields) return;
        fields.classList.toggle('opacity-50', !enabled.checked);
        fields.querySelectorAll('input, select').forEach(input => {
            if (input.id !== 'fairPlayEnabled') input.disabled = !enabled.checked;
        });
    }

    function handleSaveSettings() {
        const selectedPositions = Array.from(document.querySelectorAll('.fair-play-pos:checked')).map(input => input.value);
        settings = {
            enabled: Boolean(document.getElementById('fairPlayEnabled')?.checked),
            minInfieldInnings: Math.max(0, parseInt(document.getElementById('fairPlayMinInfield')?.value || '0', 10) || 0),
            maxConsecutiveBench: Math.max(0, parseInt(document.getElementById('fairPlayMaxBench')?.value || '0', 10) || 0),
            infieldPositions: selectedPositions
        };
        saveSettings();
        renderStatus();

        const modalElement = document.getElementById('fairPlayAssistantModal');
        if (modalElement && window.bootstrap?.Modal) {
            const modal = window.bootstrap.Modal.getOrCreateInstance(modalElement);
            modal.hide();
        }
    }

    function parseRotationMatrix() {
        const table = document.querySelector('#rotation-matrix-container table');
        if (!table) return [];

        const rows = Array.from(table.querySelectorAll('tbody tr'));
        return rows.map(row => {
            const cells = Array.from(row.querySelectorAll('td'));
            if (cells.length < 2) return null;

            const player = cells[0].textContent.trim();
            const assignments = cells.slice(1).map(cell => {
                const badge = cell.querySelector('.badge');
                if (badge) return badge.textContent.trim().toUpperCase();
                return cell.textContent.toUpperCase().includes('BENCH') ? 'BENCH' : '';
            });

            return { player, assignments };
        }).filter(Boolean);
    }

    function calculatePlayerStatus(playerRow) {
        const infieldSet = new Set(settings.infieldPositions || []);
        let infieldInnings = 0;
        let currentBenchStreak = 0;
        let maxBenchStreak = 0;
        let fieldInnings = 0;

        playerRow.assignments.forEach(position => {
            if (position === 'BENCH' || position === '') {
                currentBenchStreak += 1;
                maxBenchStreak = Math.max(maxBenchStreak, currentBenchStreak);
                return;
            }

            fieldInnings += 1;
            currentBenchStreak = 0;
            if (infieldSet.has(position)) infieldInnings += 1;
        });

        return {
            player: playerRow.player,
            infieldInnings,
            fieldInnings,
            benchInnings: playerRow.assignments.length - fieldInnings,
            maxBenchStreak,
            needsInfield: settings.minInfieldInnings > 0 && infieldInnings < settings.minInfieldInnings,
            benchWarning: settings.maxConsecutiveBench > 0 && maxBenchStreak > settings.maxConsecutiveBench
        };
    }

    function renderStatus() {
        const bar = document.getElementById('fairPlayStatusBar');
        const statusText = document.getElementById('fairPlayStatusText');
        const details = document.getElementById('fairPlayDetails');
        if (!bar || !statusText || !details) return;

        if (!settings.enabled) {
            bar.classList.add('d-none');
            details.innerHTML = '';
            return;
        }

        bar.classList.remove('d-none');
        const rows = parseRotationMatrix();
        if (!rows.length) {
            statusText.textContent = 'Add defensive innings to see fair-play status.';
            details.innerHTML = '';
            return;
        }

        const playerStatuses = rows.map(calculatePlayerStatus);
        const needsInfield = playerStatuses.filter(player => player.needsInfield);
        const benchWarnings = playerStatuses.filter(player => player.benchWarning);
        const metCount = playerStatuses.length - needsInfield.length;

        const messages = [];
        if (settings.minInfieldInnings > 0) {
            messages.push(`${metCount}/${playerStatuses.length} have met the ${settings.minInfieldInnings}-inning infield goal`);
        }
        if (settings.maxConsecutiveBench > 0) {
            messages.push(`${benchWarnings.length} bench-streak warning${benchWarnings.length === 1 ? '' : 's'}`);
        }
        if (!messages.length) messages.push('Tracking is on; no rules are currently enabled.');
        statusText.textContent = messages.join(' · ');

        const issueNames = new Set([...needsInfield.map(player => player.player), ...benchWarnings.map(player => player.player)]);
        const issueRows = playerStatuses.filter(player => issueNames.has(player.player));

        if (!issueRows.length) {
            details.innerHTML = '<div class="small text-success mt-1"><i class="bi bi-check-circle-fill me-1"></i>No fair-play issues in the current planned rotation.</div>';
            return;
        }

        details.innerHTML = `
            <div class="table-responsive mt-2">
                <table class="table table-sm align-middle mb-0">
                    <thead>
                        <tr>
                            <th>Player</th>
                            <th class="text-center">IF</th>
                            <th class="text-center">Bench</th>
                            <th>Needs attention</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${issueRows.map(player => {
                            const issues = [];
                            if (player.needsInfield) issues.push(`Needs ${Math.max(0, settings.minInfieldInnings - player.infieldInnings)} more IF inning${Math.max(0, settings.minInfieldInnings - player.infieldInnings) === 1 ? '' : 's'}`);
                            if (player.benchWarning) issues.push(`Sits ${player.maxBenchStreak} straight`);
                            return `
                                <tr>
                                    <td class="fw-semibold">${escapeHtml(player.player)}</td>
                                    <td class="text-center">${player.infieldInnings}</td>
                                    <td class="text-center">${player.benchInnings}</td>
                                    <td class="small text-warning-emphasis">${issues.map(escapeHtml).join(' · ')}</td>
                                </tr>
                            `;
                        }).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    function escapeHtml(value) {
        return String(value).replace(/[&<>'"]/g, character => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;'
        }[character]));
    }

    function observeMatrix() {
        const container = document.getElementById('rotation-matrix-container');
        if (!container || matrixObserver) return;

        matrixObserver = new MutationObserver(() => {
            window.clearTimeout(renderTimer);
            renderTimer = window.setTimeout(renderStatus, 75);
        });
        matrixObserver.observe(container, { childList: true, subtree: true, characterData: true });
    }

    function init() {
        if (!document.getElementById('rotation-card-container')) return;
        loadSettings();
        ensureModal();
        ensureMenuItem();
        ensureStatusBar();
        observeMatrix();
        renderStatus();

        // The rotation editor is initialized after DOMContentLoaded on this page.
        // Re-check shortly so the assistant sees the first rendered matrix.
        window.setTimeout(renderStatus, 250);
        window.setTimeout(renderStatus, 750);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
