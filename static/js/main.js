// static/js/main.js
document.addEventListener('DOMContentLoaded', () => {

    const AppState = {
        full_data: {},
        player_order: [],
        session: {},
        pitch_count_summary: {},
        roster_sort: { key: 'name', order: 'asc' }
    };

    let sortableInstances = {};
    let lineupEditorModal;
    
    // --- UTILITY FUNCTIONS ---
    const escapeHTML = str => String(str).replace(/[&<>'"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;',"'": '&#39;','"': '&quot;'}[tag] || tag));
    const canEdit = (author) => AppState.session.username === author || ['Head Coach', 'Super Admin'].includes(AppState.session.role);

    const renderPositionSelect = (name, id, selectedVal = '', title = 'Select Position', classes = 'form-select form-select-sm') => {
        const positions = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH', 'EH'];
        let optionsHtml = `<option value="" ${!selectedVal ? 'selected' : ''}>${title}</option>`;
        positions.forEach(pos => {
            optionsHtml += `<option value="${pos}" ${selectedVal === pos ? 'selected' : ''}>${pos}</option>`;
        });
        return `<select name="${name}" id="${id}" class="${classes}" title="${title}">${optionsHtml}</select>`;
    };

    // --- RENDER FUNCTIONS ---
    function playerTemplate(p) {
        const pNameSafe = escapeHTML(p.name);
        const pNotesSafe = escapeHTML(p.notes || '');
        const pNotesAuthorSafe = escapeHTML(p.notes_author || '');
        return `
        <div class="accordion-item" data-player-name="${pNameSafe}">
            <h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-roster-${p.id}"><i class="bi bi-grip-vertical me-2 drag-handle"></i><strong>${pNameSafe}</strong>&nbsp;(#${p.number || 'N/A'})<span class="ms-auto text-muted small d-none d-sm-inline">${[p.position1, p.position2, p.position3].filter(Boolean).join(', ') || 'N/A'} | ${p.bats || 'N/A'} / ${p.throws || 'N/A'}</span></button></h2>
            <div id="collapse-roster-${p.id}" class="accordion-collapse collapse" data-bs-parent="#rosterAccordion"><div class="accordion-body">
                <div class="row g-3 align-items-end">
                    <div class="col-12"><h5>Player Notes</h5></div>
                    <div class="col-12"><textarea class="form-control" name="notes" rows="2" placeholder="Notes">${pNotesSafe}</textarea></div>
                    ${(p.notes_author && p.notes_author !== 'N/A') ? `<div class="col-12 text-end"><small class="text-muted fst-italic">Last saved: ${pNotesAuthorSafe} on ${p.notes_timestamp || ''}</small></div>` : ''}
                    <hr class="my-3">
                    <div class="col-12 col-md-4"><label class="form-label">Name</label><input type="text" class="form-control" name="name" value="${pNameSafe}"></div>
                    <div class="col-6 col-md-2"><label class="form-label">J#</label><input type="number" class="form-control" name="number" value="${p.number || ''}"></div>
                    <div class="col-6 col-md-3"><label class="form-label">Pos 1</label>${renderPositionSelect('position1', `position1_${p.id}`, p.position1, '', 'form-select')}</div>
                    <div class="col-6 col-md-3"><label class="form-label">Pos 2</label>${renderPositionSelect('position2', `position2_${p.id}`, p.position2, '', 'form-select')}</div>
                    <div class="col-6 col-md-3"><label class="form-label">Pos 3</label>${renderPositionSelect('position3', `position3_${p.id}`, p.position3, '', 'form-select')}</div>
                    <div class="col-6 col-md-3"><label class="form-label">Throws</label><select name="throws" class="form-select"><option value="Right" ${p.throws === 'Right' ? 'selected' : ''}>Right</option><option value="Left" ${p.throws === 'Left' ? 'selected' : ''}>Left</option></select></div>
                    <div class="col-6 col-md-3"><label class="form-label">Bats</label><select name="bats" class="form-select"><option value="Right" ${p.bats === 'Right' ? 'selected' : ''}>Right</option><option value="Left" ${p.bats === 'Left' ? 'selected' : ''}>Left</option></select></div>
                    <div class="col-6 col-md-3"><label class="form-label">Pitcher Role</label><select name="pitcher_role" class="form-select"><option value="Not a Pitcher" ${p.pitcher_role === "Not a Pitcher" ? 'selected' : ''}>Not a Pitcher</option><option value="Starter" ${p.pitcher_role === "Starter" ? 'selected' : ''}>Starter</option><option value="Reliever" ${p.pitcher_role === "Reliever" ? 'selected' : ''}>Reliever</option></select></div>
                    <div class="col-12 d-flex justify-content-end mt-3"><button type="button" class="btn btn-sm btn-primary me-2 save-player-btn" data-player-id="${p.id}">Save</button><button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-player-id="${p.id}" data-player-name="${pNameSafe}">Delete</button></div>
                </div>
            </div></div>
        </div>`;
    }

    function renderRoster() {
        const container = document.getElementById('rosterAccordion');
        if (!container) return;
        const searchTerm = document.getElementById('rosterSearch').value.toLowerCase();
        const filteredRoster = (AppState.full_data.roster || []).filter(p => 
            !searchTerm || p.name.toLowerCase().includes(searchTerm) || (p.number || '').toString().includes(searchTerm)
        );
        container.innerHTML = filteredRoster.length > 0 ? filteredRoster.map(playerTemplate).join('') : `<div class="p-3 text-center text-muted">No players found.</div>`;
        attachRosterSaveListeners();
    }

    function renderPlayerDevelopment() {
        const container = document.getElementById('player-dev-accordion');
        if (!container) return;
        const playerDevData = AppState.full_data.player_development || {};
        const roster = AppState.full_data.roster || [];
        const getIconForType = (type) => ({'Development': '<i class="bi bi-graph-up-arrow text-primary"></i>', 'Coach Note': '<i class="bi bi-chat-left-text-fill text-info"></i>', 'Lessons': '<i class="bi bi-person-video3 text-success"></i>'}[type] || '<i class="bi bi-record-circle"></i>');

        if (!AppState.player_order || AppState.player_order.length === 0) {
            AppState.player_order = roster.map(p => p.name);
        }

        container.innerHTML = AppState.player_order.map((playerName) => {
            const p = roster.find(player => player.name === playerName);
            if (!p) return '';
            const activityLog = playerDevData[p.name] || [];
            const pNameSafe = escapeHTML(p.name);
            const activeFocusCount = activityLog.filter(log => log.type === 'Development' && log.status === 'active').length;
            const summaryText = activeFocusCount > 0 ? `${activeFocusCount} active focus${activeFocusCount > 1 ? 'es' : ''}` : 'No active focuses';
            const activityHtml = activityLog.length > 0 ? `<ul class="list-group">${activityLog.map(log => {
                log.player_name = pNameSafe;
                let itemClass = '', statusText = '', mainText = escapeHTML(log.text);
                if (log.type === 'Development') itemClass = log.status === 'completed' ? (statusText=`<span class="badge bg-success ms-2">Completed: ${log.completed_date}</span>`, 'completed-focus') : 'active-focus';
                else if (log.type === 'Lessons') itemClass = 'lesson-entry'; else if (log.type === 'Coach Note') itemClass = 'coach-note-entry';
                let actions = '';
                if (canEdit(log.author) || log.type === 'Development') {
                    if (log.type === 'Development') actions = `<button class="btn btn-sm btn-link text-secondary py-0" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-focus-id="${log.id}" data-player-name="${pNameSafe}">Edit</button><a href="/delete_focus/${log.id}" class="btn btn-sm btn-link text-danger py-0" onclick="return confirm('Are you sure?');">Delete</a>`;
                    else if (log.type === 'Coach Note') actions = `<button class="btn btn-sm btn-link text-secondary py-0" data-bs-toggle="modal" data-bs-target="#editNoteModal" data-note-id="${log.id}" data-note-type="player_notes" data-note-text="${escapeHTML(log.text)}">Edit</button><a href="/delete_note/player_notes/${log.id}" class="btn btn-sm btn-link text-danger py-0" onclick="return confirm('Are you sure?');">Delete</a>`;
                }
                return `<li class="list-group-item ${itemClass}"><div class="d-flex w-100 justify-content-between"><h6 class="mb-1">${getIconForType(log.type)} ${escapeHTML(log.subtype)}: <span class="text-muted fw-normal">${mainText}</span>${statusText}</h6><small>${log.date}</small></div>${log.notes ? `<p class="mb-1 text-muted small fst-italic">Notes: ${escapeHTML(log.notes)}</p>` : ''}<small class="text-muted">By: ${escapeHTML(log.author)}</small>${actions ? `<div class="mt-2">${actions}</div>` : ''}</li>`;
            }).join('')}</ul>` : `<div class="text-center p-3 border rounded"><p class="mb-0">No activity logged.</p></div>`;
            return `<div class="accordion-item" data-player-name="${pNameSafe}"><h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-dev-${p.id}"><i class="bi bi-grip-vertical me-2 drag-handle"></i><strong>${pNameSafe}</strong><span class="ms-auto text-muted small">${summaryText}</span></button></h2><div id="collapse-dev-${p.id}" class="accordion-collapse collapse" data-bs-parent="#player-dev-accordion"><div class="accordion-body"><div class="d-flex justify-content-between align-items-center mb-3"><h5 class="mb-0">Activity Log</h5><div class="btn-group"><button class="btn btn-sm btn-success dropdown-toggle" type="button" data-bs-toggle="dropdown">Add New</button><ul class="dropdown-menu dropdown-menu-end"><li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="hitting">Hitting Focus</a></li><li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="pitching">Pitching Focus</a></li><li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="fielding">Fielding Focus</a></li><li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="baserunning">Baserunning Focus</a></li><li><hr class="dropdown-divider"></li><li><a class="dropdown-item" href="#collaboration" onclick="document.querySelector('#collab-player-select').value='${pNameSafe}'; switchTab(document.querySelector('a[href=\\'#collaboration\\']'));">Coach Note</a></li></ul></div></div>${activityHtml}</div></div></div>`;
        }).join('');
    }

    function renderLineups() {
        const container = document.getElementById('lineupsAccordion');
        if (!container) return;
        const lineups = AppState.full_data.lineups.filter(l => !l.associated_game_id) || [];
        container.innerHTML = lineups.length === 0 ? `<div class="text-center p-4 border rounded"><p class="mb-0">No unassigned lineups saved yet.</p></div>` : lineups.map((l) => `<div class="accordion-item" data-lineup-id="${l.id}"><h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#lineup-collapse-${l.id}"><strong>${escapeHTML(l.title)}</strong></button></h2><div id="lineup-collapse-${l.id}" class="accordion-collapse collapse" data-bs-parent="#lineupsAccordion"><div class="accordion-body"><div class="d-flex justify-content-end mb-3"><button class="btn btn-sm btn-info me-2 edit-lineup-btn" data-bs-toggle="modal" data-bs-target="#lineupEditorModal" data-lineup-id="${l.id}">Edit</button><a href="/delete_lineup/${l.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');">Delete</a></div><table class="table table-striped table-sm"><thead><tr><th style="width: 5%;">#</th><th>Player</th><th style="width: 15%;">Position</th></tr></thead><tbody>${(l.lineup_positions || []).map((spot, i) => `<tr><td><strong>${i + 1}</strong></td><td>${escapeHTML(spot.name)}</td><td>${spot.position}</td></tr>`).join('') || `<tr><td colspan="3" class="text-center text-muted">This lineup is empty.</td></tr>`}</tbody></table></div></div></div>`).join('');
    }
    
    // ADDED: renderRotations function
    function renderRotations() {
        const container = document.getElementById('rotationsAccordion');
        if (!container) return;
        const rotations = AppState.full_data.rotations.filter(r => !r.associated_game_id) || [];
        container.innerHTML = rotations.length === 0 ? `<div class="text-center p-4 border rounded"><p class="mb-0">No unassigned rotations saved.</p><p class="small text-muted">Create rotations from the 'Manage' screen of any game.</p></div>` : rotations.map((r) => {
            const inningsCount = r.innings ? Object.keys(r.innings).length : 0;
            return `<div class="accordion-item" data-rotation-id="${r.id}">
                <h2 class="accordion-header">
                    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#rotation-collapse-${r.id}">
                        <strong>${escapeHTML(r.title)}</strong>
                    </button>
                </h2>
                <div id="rotation-collapse-${r.id}" class="accordion-collapse collapse" data-bs-parent="#rotationsAccordion">
                    <div class="accordion-body">
                        <div class="d-flex justify-content-end mb-3">
                            <a href="/delete_rotation/${r.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');">Delete</a>
                        </div>
                        <p>This rotation has <strong>${inningsCount}</strong> inning(s) defined. You can manage this rotation by assigning it to a game.</p>
                    </div>
                </div>
            </div>`;
        }).join('');
    }

    function renderPitchingLog() {
        const summaryContainer = document.getElementById('pitch-count-summary-container');
        if (summaryContainer) {
            const summaryData = AppState.pitch_count_summary || {};
            const firstPitcher = Object.values(summaryData)[0];
            const maxDaily = firstPitcher ? firstPitcher.max_daily : 85;
            let summaryHtml = `<table class="table table-sm table-bordered table-striped"><thead class="table-light"><tr><th>Pitcher</th><th>Daily (${maxDaily} max)</th><th>Weekly</th><th>Status</th></tr></thead><tbody>`;
            if (Object.keys(summaryData).length > 0) {
                const sortedPitchers = AppState.player_order.filter(name => summaryData[name]);
                for (const name of sortedPitchers) {
                    const counts = summaryData[name];
                    const dailyPct = Math.min((counts.daily / counts.max_daily * 100), 100);
                    const weeklyPct = Math.min((counts.weekly / 100 * 100), 100);
                    const dailyBg = dailyPct > 80 ? 'bg-danger' : dailyPct > 60 ? 'bg-warning' : 'bg-success';
                    const statusBadge = counts.status === 'Available' ? `<span class="badge bg-success">Available</span>` : `<span class="badge bg-danger">Resting</span>`;
                    const nextAvailableText = counts.status === 'Resting' ? `<br><small class="text-muted">Next up: ${counts.next_available}</small>` : '';
                    summaryHtml += `<tr><td class="align-middle"><strong>${escapeHTML(name)}</strong></td><td class="align-middle"><div class="progress" style="height: 20px;"><div class="progress-bar ${dailyBg}" role="progressbar" style="width: ${dailyPct}%;" aria-valuenow="${counts.daily}">${counts.daily}</div></div><small class="text-muted">${counts.pitches_remaining_today} remaining</small></td><td class="align-middle"><div class="progress" style="height: 20px;"><div class="progress-bar" role="progressbar" style="width: ${weeklyPct}%;" aria-valuenow="${counts.weekly}">${counts.weekly}</div></div></td><td class="text-center align-middle">${statusBadge}${nextAvailableText}</td></tr>`;
                }
            } else { summaryHtml += `<tr><td colspan="4" class="text-center text-muted">No pitching data.</td></tr>`; }
            summaryHtml += `</tbody></table>`;
            summaryContainer.innerHTML = summaryHtml;
        }
        const pitcherSelect = document.getElementById('pitching-log-pitcher-select');
        if (pitcherSelect) pitcherSelect.innerHTML = `<option value="">Select Pitcher</option>` + AppState.full_data.roster.filter(p => p.pitcher_role !== 'Not a Pitcher').map(p => `<option value="${escapeHTML(p.name)}">${escapeHTML(p.name)}</option>`).join('');
        const outingsList = document.getElementById('recorded-outings-list');
        if (outingsList) {
            const outings = (AppState.full_data.pitching || []).sort((a,b) => b.date.localeCompare(a.date)).slice(0, 10);
            outingsList.innerHTML = outings.map((o) => `<li class="list-group-item d-flex justify-content-between align-items-center"><span>${o.date}: <strong>${escapeHTML(o.pitcher)}</strong> vs ${escapeHTML(o.opponent)} - ${o.pitches} pitches <span class="badge bg-info">${o.outing_type}</span></span><a href="/delete_pitching/${o.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');"><i class="bi bi-trash"></i></a></li>`).join('') || `<li class="list-group-item text-muted">No outings recorded.</li>`;
        }
    }

    function renderSigns() {
        const container = document.getElementById('signs-list-container');
        if (!container) return;
        const signs = AppState.full_data.signs || [];
        container.innerHTML = signs.length > 0 ? signs.map((sign) => `<li class="list-group-item d-flex justify-content-between align-items-center"><div><strong>${escapeHTML(sign.name)}:</strong> ${escapeHTML(sign.indicator)}</div><div><button class="btn btn-sm btn-info" data-bs-toggle="modal" data-bs-target="#editSignModal" data-sign-id="${sign.id}">Edit</button><a href="/delete_sign/${sign.id}" class="btn btn-sm btn-danger ms-2" onclick="return confirm('Are you sure?')">Delete</a></div></li>`).join('') : `<li class="list-group-item">No signs added.</li>`;
    }

    function renderCollaborationNotes() {
        const teamContainer = document.getElementById('team-notes-container');
        const playerContainer = document.getElementById('player-notes-container');
        if (!teamContainer || !playerContainer) return;
        const collabData = AppState.full_data.collaboration_notes || {};
        const createNoteHTML = (note, note_type) => {
            const noteText = escapeHTML(note.text);
            const author = escapeHTML(note.author);
            let actions = '';
            if (canEdit(note.author)) {
                actions = `<button class="btn btn-sm btn-link text-secondary" data-bs-toggle="modal" data-bs-target="#editNoteModal" data-note-id="${note.id}" data-note-type="${note_type}" data-note-text="${noteText}">Edit</button><a href="/move_note_to_practice_plan/${note_type}/${note.id}" class="btn btn-sm btn-link text-secondary">Move</a><a href="/delete_note/${note_type}/${note.id}" class="btn btn-sm btn-link text-danger" onclick="return confirm('Are you sure?')">Delete</a>`;
            }
            return `<div class="card mb-2"><div class="card-body pb-2"><p class="card-text" style="white-space: pre-wrap;">${noteText}</p><small class="text-muted">By ${author} on ${note.timestamp}${note.player_name ? ` for <strong>${escapeHTML(note.player_name)}</strong>` : ''}</small></div>${actions ? `<div class="card-footer bg-white border-top-0 text-end py-2">${actions}</div>` : ''}</div>`;
        };
        const teamNotes = (collabData.team_notes || []).sort((a,b) => b.timestamp.localeCompare(a.timestamp));
        teamContainer.innerHTML = teamNotes.map(note => createNoteHTML(note, 'team_notes')).join('') || '<div class="text-center p-3 border rounded text-muted">No team notes.</div>';
        const playerNotes = (collabData.player_notes || []).sort((a,b) => b.timestamp.localeCompare(a.timestamp));
        playerContainer.innerHTML = playerNotes.map(note => createNoteHTML(note, 'player_notes')).join('') || '<div class="text-center p-3 border rounded text-muted">No player notes.</div>';
        document.getElementById('collab-player-select').innerHTML = '<option value="">Select a player...</option>' + AppState.player_order.map(name => `<option value="${escapeHTML(name)}">${escapeHTML(name)}</option>`).join('');
    }

    function renderScoutingList() {
        const container = document.getElementById('scouting-list-container');
        if (!container) return;
        const scoutingData = AppState.full_data.scouting_list || {};
        container.innerHTML = Object.entries({'targets': 'Targets', 'committed': 'Committed', 'not_interested': 'Not Interested'}).map(([key, title]) => {
            const players = scoutingData[key] || [];
            let playerHtml = players.length > 0 ? players.map(p => {
                let moveOptions = '';
                if (key === 'targets') moveOptions = `<li><form action="/move_scouted_player/targets/committed/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item">To Committed</button></form></li><li><form action="/move_scouted_player/targets/not_interested/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item">To Not Interested</button></form></li>`;
                else if (key === 'committed') moveOptions = `<li><form action="/move_scouted_player_to_roster/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item fw-bold">To Roster</button></form></li><li><hr class="dropdown-divider"></li><li><form action="/move_scouted_player/committed/not_interested/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item">To Not Interested</button></form></li>`;
                const positions = [p.position1, p.position2].filter(Boolean).join(' / ') || 'N/A';
                return `<li class="list-group-item d-flex justify-content-between align-items-center"><div><div class="fw-bold">${escapeHTML(p.name)}</div><small class="text-muted">Pos: ${positions} | T/B: ${p.throws || 'N'}/${p.bats || 'N'}</small></div><div class="btn-group"><a href="/delete_scouted_player/${key}/${p.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');"><i class="bi bi-trash"></i></a>${moveOptions ? `<button type="button" class="btn btn-sm btn-outline-secondary dropdown-toggle dropdown-toggle-split" data-bs-toggle="dropdown"></button><ul class="dropdown-menu dropdown-menu-end">${moveOptions}</ul>` : ''}</div></li>`;
            }).join('') : `<li class="list-group-item text-center text-muted">No players.</li>`;
            return `<div class="col-md-4 mb-3"><div class="card h-100"><div class="card-header fw-bold">${title}</div><ul class="list-group list-group-flush">${playerHtml}</ul></div></div>`;
        }).join('');
    }

    function renderGames() {
        const container = document.getElementById('games-list-container');
        if (!container) return;
        const games = (AppState.full_data.games || []).sort((a,b) => b.date.localeCompare(a.date));
        if (games.length === 0) { container.innerHTML = `<li class="list-group-item text-center text-muted">No games scheduled.</li>`; return; }
        container.innerHTML = games.map(game => {
            const lineup = AppState.full_data.lineups.find(l => l.associated_game_id === game.id);
            const rotation = AppState.full_data.rotations.find(r => r.associated_game_id === game.id);
            const lineupHTML = lineup ? `<span class="text-success"><i class="bi bi-check-circle-fill"></i> Set</span>` : `<span class="text-muted"><i class="bi bi-x-circle"></i> Not Set</span>`;
            const rotationHTML = rotation ? `<span class="text-success"><i class="bi bi-check-circle-fill"></i> Set</span>` : `<span class="text-muted"><i class="bi bi-x-circle"></i> Not Set</span>`;
            return `<li class="list-group-item"><div class="d-flex justify-content-between align-items-center flex-wrap"><div class="me-auto"><h5 class="mb-1">vs ${escapeHTML(game.opponent)}</h5><p class="mb-1"><i class="bi bi-calendar-event"></i> ${game.date} <span class="text-muted mx-2">|</span> <i class="bi bi-geo-alt"></i> ${escapeHTML(game.location || 'TBD')}</p></div><div class="d-flex align-items-center mt-2 mt-md-0"><div class="text-end me-3"><div class="mb-1"><small>Lineup:</small> ${lineupHTML}</div><div><small>Rotation:</small> ${rotationHTML}</div></div><div class="btn-group-vertical btn-group-sm"><a href="/game/${game.id}" class="btn btn-primary"><i class="bi bi-tools"></i> Manage</a><a href="/delete_game/${game.id}" class="btn btn-outline-danger" onclick="return confirm('Are you sure?');"><i class="bi bi-trash"></i></a></div></div></div></li>`;
        }).join('');
    }

    function renderPracticePlans() {
        const container = document.getElementById('practicePlanAccordion');
        if (!container) return;
        const plans = (AppState.full_data.practice_plans || []).sort((a,b) => b.date.localeCompare(a.date));
        if (plans.length === 0) { container.innerHTML = `<div class="text-center p-4 border rounded"><p class="mb-0">No practice plans saved.</p></div>`; return; }
        container.innerHTML = plans.map(plan => `<div class="accordion-item"><h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#plan-${plan.id}"><strong>${plan.date}</strong> - ${escapeHTML(plan.general_notes || 'No notes')}</button></h2><div id="plan-${plan.id}" class="accordion-collapse collapse" data-bs-parent="#practicePlanAccordion"><div class="accordion-body practice-plan"><form action="/edit_practice_plan/${plan.id}" method="POST" class="row g-3 mb-3 align-items-end"><div class="col-md-3"><label class="form-label">Date:</label><input type="date" name="plan_date" class="form-control" value="${plan.date}" required></div><div class="col-md-7"><label class="form-label">Notes:</label><input type="text" name="general_notes" class="form-control" value="${escapeHTML(plan.general_notes || '')}"></div><div class="col-md-2 d-flex"><button type="submit" class="btn btn-sm btn-primary me-2">Save</button><a href="/delete_practice_plan/${plan.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');">Delete</a></a></div></form><hr><h5>Tasks</h5><form action="/add_task_to_plan/${plan.id}" method="POST" class="mb-3 add-task-form"><div class="input-group"><input type="text" name="task_text" class="form-control" placeholder="Add task..." required><button type="submit" class="btn btn-primary">Add</button></div></form><ul class="list-group task-list">${(plan.tasks || []).map(task => `<li class="list-group-item d-flex justify-content-between align-items-center task-item ${task.status === 'complete' ? 'complete' : ''}" data-task-id="${task.id}" data-plan-id="${plan.id}"><div class="form-check"><input class="form-check-input task-checkbox" type="checkbox" ${task.status === 'complete' ? 'checked' : ''} id="task-${task.id}"><label class="form-check-label" for="task-${task.id}">${escapeHTML(task.text)}<div class="text-muted small">By ${escapeHTML(task.author)}</div></label></div><a href="/delete_task/${plan.id}/${task.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');"><i class="bi bi-trash"></i></a></li>`).join('') || '<li class="list-group-item text-muted text-center">No tasks.</li>'}</ul></div></div></div>`).join('');
        attachTaskListeners();
    }

    function renderAll() {
        renderRoster();
        renderPlayerDevelopment();
        renderLineups();
        renderRotations(); // ADDED
        renderPitchingLog();
        renderSigns();
        renderCollaborationNotes();
        renderScoutingList();
        renderGames();
        renderPracticePlans();
    }

    // --- EVENT HANDLERS & LISTENERS ---
    function attachRosterSaveListeners() {
        document.querySelectorAll('.save-player-btn').forEach(button => {
            button.removeEventListener('click', handleRosterSave);
            button.addEventListener('click', handleRosterSave);
        });
    }

    async function handleRosterSave(event) {
        const btn = event.target.closest('button');
        const playerId = btn.dataset.playerId;
        const accordionBody = btn.closest('.accordion-body');
        const formData = new FormData();
        accordionBody.querySelectorAll('input, select, textarea').forEach(input => formData.append(input.name, input.value));
        btn.disabled = true;
        try {
            const response = await fetch(`/update_player_inline/${playerId}`, { method: 'POST', body: formData });
            if (!response.ok) throw new Error((await response.json()).message);
        } catch (err) { alert(`Error: ${err.message}`); } finally { btn.disabled = false; }
    }

    function attachTaskListeners() {
        document.querySelectorAll('.task-checkbox').forEach(cb => {
            cb.removeEventListener('change', handleTaskCheckboxChange);
            cb.addEventListener('change', handleTaskCheckboxChange);
        });
    }

    async function handleTaskCheckboxChange(event) {
        const listItem = event.target.closest('.task-item');
        const taskId = listItem.dataset.taskId;
        const planId = listItem.dataset.planId;
        const newStatus = event.target.checked ? 'complete' : 'pending';
        try {
            const response = await fetch(`/update_task_status/${planId}/${taskId}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: newStatus }) });
            if (!response.ok) throw new Error((await response.json()).message);
        } catch (error) { alert('Error: ' + error.message); event.target.checked = !event.target.checked; }
    }
    
    // --- INITIALIZATION ---
    async function init() {
        try {
            const response = await fetch('/get_app_data');
            if (!response.ok) throw new Error(`Failed to fetch: ${response.statusText}`);
            const serverData = await response.json();
            Object.assign(AppState, serverData);
        } catch (error) {
            console.error("Init Error:", error);
            document.querySelector('main').innerHTML = `<div class="alert alert-danger">Could not load app data. Refresh page.</div>`;
            return;
        }
        lineupEditorModal = new bootstrap.Modal(document.getElementById('lineupEditorModal'));
        setupEventListeners();
        renderAll();
        initializeSortables();
        handleTabLogic();
        
        const socket = io();
        socket.on('data_updated', async (msg) => {
            console.log('Update received:', msg.message);
            try {
                const response = await fetch('/get_app_data');
                const serverData = await response.json();
                Object.assign(AppState, serverData);
                renderAll();
            } catch (error) { console.error("Error refreshing data:", error); }
        });
    }

    function initializeSortables() {
        Object.values(sortableInstances).forEach(s => s.destroy());
        sortableInstances = {};
        const savePlayerOrder = (evt) => {
            const newOrder = Array.from(evt.from.children).map(item => item.dataset.playerName);
            AppState.player_order = newOrder;
            fetch('/save_player_order', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ player_order: newOrder }) });
        };
        ['rosterAccordion', 'player-dev-accordion'].forEach(id => {
            const el = document.getElementById(id);
            if(el) sortableInstances[id] = new Sortable(el, { handle: '.drag-handle', animation: 150, onEnd: savePlayerOrder });
        });
        const desktopTabEl = document.getElementById('mainTabsDesktop');
        if (desktopTabEl) {
            sortableInstances.desktopTabs = new Sortable(desktopTabEl, {
                handle: '.drag-handle', animation: 150,
                onEnd: () => {
                    const newOrder = Array.from(desktopTabEl.querySelectorAll('a[data-bs-toggle="tab"]')).map(a => a.getAttribute('href').substring(1)).filter(id => id !== 'stats_tab');
                    fetch('/save_tab_order', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order: newOrder }) });
                }
            });
        }
    }

    function setupEventListeners() {
        document.getElementById('rosterSearch').addEventListener('input', renderRoster);
        
        // Modal population listeners
        document.getElementById('confirmDeleteModal')?.addEventListener('show.bs.modal', (e) => {
            document.getElementById('playerNameToDelete').textContent = e.relatedTarget.dataset.playerName;
            document.getElementById('confirmDeleteButton').href = `/delete_player/${e.relatedTarget.dataset.playerId}`;
        });
        document.getElementById('lineupEditorModal')?.addEventListener('show.bs.modal', (e) => {
            const lineupId = e.relatedTarget ? e.relatedTarget.dataset.lineupId : null;
            openLineupEditor(lineupId ? AppState.full_data.lineups.find(l => l.id == lineupId) : null);
        });
        document.getElementById('editNoteModal')?.addEventListener('show.bs.modal', (e) => {
            e.target.querySelector('#editNoteId').value = e.relatedTarget.dataset.noteId;
            e.target.querySelector('#editNoteType').value = e.relatedTarget.dataset.noteType;
            e.target.querySelector('#editNoteText').value = e.relatedTarget.dataset.noteText;
        });
        document.getElementById('editFocusModal')?.addEventListener('show.bs.modal', (e) => {
            const btn = e.relatedTarget, form = e.target.querySelector('form');
            form.reset();
            const focusId = btn.dataset.focusId;
            if (focusId) {
                e.target.querySelector('.modal-title').textContent = 'Edit Focus';
                form.action = `/update_focus/${focusId}`;
                const focusItem = AppState.full_data.player_development[btn.dataset.playerName]?.find(item => item.id == focusId);
                if (focusItem) {
                    form.querySelector('#focusSkill').value = focusItem.subtype;
                    form.querySelector('#focusText').value = focusItem.text;
                    form.querySelector('#focusNotes').value = focusItem.notes || '';
                }
            } else {
                e.target.querySelector('.modal-title').textContent = 'Add Focus';
                form.action = `/add_focus/${encodeURIComponent(btn.dataset.playerName)}`;
                form.querySelector('#focusSkill').value = btn.dataset.skill;
            }
        });
        document.getElementById('editSignModal')?.addEventListener('show.bs.modal', (e) => {
            const sign = AppState.full_data.signs.find(s => s.id == e.relatedTarget.dataset.signId);
            const form = e.target.querySelector('form');
            form.action = `/update_sign/${sign.id}`;
            form.querySelector('#editSignName').value = sign.name;
            form.querySelector('#editSignIndicator').value = sign.indicator;
        });
    }
    
    function openLineupEditor(lineup = null) {
        const modal = document.getElementById('lineupEditorModal');
        modal.querySelector('#lineupId').value = lineup ? lineup.id : '';
        modal.querySelector('#lineupTitle').value = lineup ? lineup.title : 'New Unassigned Lineup';
        const bench = modal.querySelector('#lineup-bench'), order = modal.querySelector('#lineup-order');
        const lineupPlayerNames = new Set((lineup?.lineup_positions || []).map(p => p.name));
        bench.innerHTML = AppState.full_data.roster.filter(p => !lineupPlayerNames.has(p.name)).map(p => `<div class="list-group-item" data-player-name="${p.name}">${p.name}</div>`).join('');
        order.innerHTML = (lineup?.lineup_positions || []).map(spot => `<div class="list-group-item" data-player-name="${spot.name}">${spot.name}</div>`).join('');
        if(sortableInstances.lineupBench) sortableInstances.lineupBench.destroy();
        if(sortableInstances.lineupOrder) sortableInstances.lineupOrder.destroy();
        sortableInstances.lineupBench = new Sortable(bench, { group: 'lineup', animation: 150 });
        sortableInstances.lineupOrder = new Sortable(order, { group: 'lineup', animation: 150 });
    }

    function handleTabLogic() {
        const allTabs = document.querySelectorAll('a[data-bs-toggle="tab"]');
        allTabs.forEach(tab => {
            tab.addEventListener('shown.bs.tab', e => {
                const newTabId = e.target.getAttribute('href').substring(1);

                // Update URL hash
                if (history.pushState) {
                    history.pushState(null, null, '#' + newTabId);
                } else {
                    window.location.hash = '#' + newTabId;
                }

                // Handle active states on mobile bottom nav
                const mainNavItems = document.querySelectorAll('.bottom-nav > .nav-item[data-tab-id]');
                const moreMenuButton = document.querySelector('.bottom-nav > .nav-item[data-bs-toggle="offcanvas"]');
                const moreMenuTabIds = Array.from(document.querySelectorAll('#mobileMoreMenu a[data-tab-id]')).map(a => a.dataset.tabId);

                let isMoreTabActive = moreMenuTabIds.includes(newTabId);

                mainNavItems.forEach(item => {
                    item.classList.toggle('active', item.dataset.tabId === newTabId);
                });

                if (moreMenuButton) {
                    moreMenuButton.classList.toggle('active', isMoreTabActive);
                    if (isMoreTabActive) {
                        mainNavItems.forEach(item => item.classList.remove('active'));
                    }
                }

                // Close offcanvas if a tab inside it was clicked
                const offcanvasEl = document.getElementById('mobileMoreMenu');
                if (offcanvasEl) {
                    const offcanvas = bootstrap.Offcanvas.getInstance(offcanvasEl);
                    if (offcanvas && offcanvas._isShown && e.target.closest('#mobileMoreMenu')) {
                        offcanvas.hide();
                    }
                }
            });
        });

        // Activate tab from URL hash on page load
        const hash = window.location.hash || '#roster';
        const tabEl = document.querySelector(`a[data-bs-toggle="tab"][href="${hash}"]`);
        if (tabEl) {
            new bootstrap.Tab(tabEl).show();
        } else {
            const defaultTab = document.querySelector('a[href="#roster"]');
            if (defaultTab) new bootstrap.Tab(defaultTab).show();
        }
    }
    
    init(); // Start the app
});