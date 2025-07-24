// static/js/main.js
// This file contains all the client-side JavaScript for the main dashboard (index.html)

document.addEventListener('DOMContentLoaded', () => {

    // Central application state on the client-side
    const AppState = {
        full_data: {},
        player_order: [],
        session: {},
        pitch_count_summary: {},
        roster_sort: { key: 'name', order: 'asc' }
    };

    // MODIFIED: Changed from const to let to allow reassignment
    let sortableInstances = {};
    let lineupEditorModal;

    // --- UTILITY FUNCTIONS ---
    const escapeHTML = str => String(str).replace(/[&<>'"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;',"'": '&#39;','"': '&quot;'}[tag] || tag));
    const canEdit = (author) => AppState.session.username === author || AppState.session.role === 'Head Coach' || AppState.session.role === 'Super Admin';

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
            <h2 class="accordion-header">
                <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-roster-${p.id}">
                    <i class="bi bi-grip-vertical me-2 drag-handle" title="Drag to reorder"></i>
                    <strong>${pNameSafe}</strong>&nbsp;(#${p.number || 'N/A'})
                    <span class="ms-auto text-muted small d-none d-sm-inline">
                        ${[p.position1, p.position2, p.position3].filter(Boolean).join(', ') || 'N/A'} | ${p.bats || 'N/A'} / ${p.throws || 'N/A'}
                    </span>
                </button>
            </h2>
            <div id="collapse-roster-${p.id}" class="accordion-collapse collapse" data-bs-parent="#rosterAccordion">
                <div class="accordion-body">
                    <div class="row g-3 align-items-end">
                        <div class="col-12"><h5 class="mb-0">Player Profile Notes</h5></div>
                        <div class="col-12"><textarea class="form-control" name="notes" rows="2" placeholder="General Player Notes">${pNotesSafe}</textarea></div>
                        ${(p.notes_author && p.notes_author !== 'N/A') ? `<div class="col-12 text-end"><small class="text-muted fst-italic">Last saved: ${pNotesAuthorSafe} on ${p.notes_timestamp || ''}</small></div>` : ''}
                        <hr class="my-3">
                        <div class="col-12 col-md-4"><label class="form-label">Player Name</label><input type="text" class="form-control" name="name" value="${pNameSafe}" placeholder="Name"></div>
                        <div class="col-6 col-md-2"><label class="form-label">Jersey #</label><input type="number" class="form-control" name="number" value="${p.number || ''}" placeholder="J#"></div>
                        <div class="col-6 col-md-3"><label class="form-label">Primary Pos</label>${renderPositionSelect('position1', `position1_${p.id}`, p.position1, 'Pos1', 'form-select')}</div>
                        <div class="col-6 col-md-3"><label class="form-label">Secondary Pos</label>${renderPositionSelect('position2', `position2_${p.id}`, p.position2, 'Pos2', 'form-select')}</div>
                        <div class="col-6 col-md-3"><label class="form-label">Tertiary Pos</label>${renderPositionSelect('position3', `position3_${p.id}`, p.position3, 'Pos3', 'form-select')}</div>
                        <div class="col-6 col-md-3"><label class="form-label">Throws</label><select name="throws" class="form-select" title="Throws"><option value="Right" ${p.throws === 'Right' ? 'selected' : ''}>Right</option><option value="Left" ${p.throws === 'Left' ? 'selected' : ''}>Left</option></select></div>
                        <div class="col-6 col-md-3"><label class="form-label">Bats</label><select name="bats" class="form-select" title="Bats"><option value="Right" ${p.bats === 'Right' ? 'selected' : ''}>Right</option><option value="Left" ${p.bats === 'Left' ? 'selected' : ''}>Left</option></select></div>
                        <div class="col-6 col-md-3"><label class="form-label">Pitcher Role</label><select name="pitcher_role" class="form-select" title="Pitcher Role"><option value="Not a Pitcher" ${p.pitcher_role === "Not a Pitcher" ? 'selected' : ''}>Not a Pitcher</option><option value="Starter" ${p.pitcher_role === "Starter" ? 'selected' : ''}>Starter</option><option value="Reliever" ${p.pitcher_role === "Reliever" ? 'selected' : ''}>Reliever</option></select></div>
                        <div class="col-12 d-flex justify-content-end mt-3">
                            <button type="button" class="btn btn-sm btn-primary me-2 save-player-btn" data-player-id="${p.id}">Save Changes</button>
                            <button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-player-id="${p.id}" data-player-name="${pNameSafe}">Delete Player</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>`;
    }

    function renderRoster() {
        const container = document.getElementById('rosterAccordion');
        if (!container) return;
        
        const searchTerm = document.getElementById('rosterSearch').value.toLowerCase();
        const sortedRoster = [...(AppState.full_data.roster || [])].sort((a, b) => {
            const key = AppState.roster_sort.key;
            const order = AppState.roster_sort.order;
            let valA = a[key] || '';
            let valB = b[key] || '';
            if (key === 'number') {
                valA = parseInt(a.number || '9999', 10);
                valB = parseInt(b.number || '9999', 10);
            } else {
                valA = valA.toLowerCase();
                valB = valB.toLowerCase();
            }
            if (valA < valB) return order === 'asc' ? -1 : 1;
            if (valA > valB) return order === 'asc' ? 1 : -1;
            return 0;
        });

        const filteredRoster = sortedRoster.filter(p => 
            !searchTerm || p.name.toLowerCase().includes(searchTerm) || (p.number || '').toString().includes(searchTerm)
        );

        if (filteredRoster.length > 0) {
            container.innerHTML = filteredRoster.map(playerTemplate).join('');
        } else {
            container.innerHTML = `<div class="p-3 text-center text-muted">No players found.</div>`;
        }
        
        attachRosterSaveListeners();
    }

    function renderPlayerDevelopment() {
        const container = document.getElementById('player-dev-accordion');
        if (!container) return;

        const playerDevData = AppState.full_data.player_development || {};
        const roster = AppState.full_data.roster || [];
        
        const getIconForType = (type) => ({
            'Development': '<i class="bi bi-graph-up-arrow text-primary"></i>',
            'Coach Note': '<i class="bi bi-chat-left-text-fill text-info"></i>',
            'Lessons': '<i class="bi bi-person-video3 text-success"></i>'
        }[type] || '<i class="bi bi-record-circle"></i>');

        const createActionButtons = (log) => {
            if (!canEdit(log.author)) return '';
            let editButton = '', deleteLink = '';

            if (log.type === 'Development') {
                editButton = `<button class="btn btn-sm btn-link text-secondary py-0" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-focus-id="${log.id}" data-player-name="${log.player_name}">Edit</button>`;
                deleteLink = `<a href="/delete_focus/${log.id}" class="btn btn-sm btn-link text-danger py-0" onclick="return confirm('Are you sure?');">Delete</a>`;
            } else if (log.type === 'Coach Note') {
                const noteText = escapeHTML(log.text);
                editButton = `<button class="btn btn-sm btn-link text-secondary py-0" data-bs-toggle="modal" data-bs-target="#editNoteModal" data-note-id="${log.id}" data-note-type="player_notes" data-note-text="${noteText}">Edit</button>`;
                deleteLink = `<a href="/delete_note/player_notes/${log.id}" class="btn btn-sm btn-link text-danger py-0" onclick="return confirm('Are you sure?');">Delete</a>`;
            }
            return `<div class="mt-2">${editButton}${deleteLink}</div>`;
        };
        
        container.innerHTML = AppState.player_order.map((playerName) => {
            const p = roster.find(player => player.name === playerName);
            if (!p) return '';
            
            const activityLog = playerDevData[p.name] || [];
            const pNameSafe = escapeHTML(p.name);
            const activeFocusCount = activityLog.filter(log => log.type === 'Development' && log.status === 'active').length;
            const summaryText = activeFocusCount > 0 ? `${activeFocusCount} active focus${activeFocusCount > 1 ? 'es' : ''}` : 'No active focuses';

            const activityHtml = activityLog.length > 0 ? `
                <ul class="list-group">
                    ${activityLog.map(log => {
                        log.player_name = pNameSafe;
                        let itemClass = '';
                        if (log.type === 'Development') itemClass = log.status === 'completed' ? 'completed-focus' : 'active-focus';
                        else if (log.type === 'Lessons') itemClass = 'lesson-entry';
                        else if (log.type === 'Coach Note') itemClass = 'coach-note-entry';
                        
                        return `
                        <li class="list-group-item ${itemClass}">
                            <div class="d-flex w-100 justify-content-between">
                                <h6 class="mb-1">${getIconForType(log.type)} ${escapeHTML(log.subtype)}: <span class="text-muted fw-normal">${escapeHTML(log.text)}</span></h6>
                                <small>${log.date}</small>
                            </div>
                            ${log.notes ? `<p class="mb-1 text-muted small fst-italic">Notes: ${escapeHTML(log.notes)}</p>` : ''}
                            <small class="text-muted">By: ${escapeHTML(log.author)}</small>
                            ${createActionButtons(log)}
                        </li>`;
                    }).join('')}
                </ul>` : `<div class="text-center p-3 border rounded"><p>No activity logged for this player yet.</p></div>`;

            return `
            <div class="accordion-item" data-player-name="${pNameSafe}">
                <h2 class="accordion-header">
                    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-dev-${p.id}">
                        <i class="bi bi-grip-vertical me-2 drag-handle"></i>
                        <strong>${pNameSafe}</strong>
                        <span class="ms-auto text-muted small">${summaryText}</span>
                    </button>
                </h2>
                <div id="collapse-dev-${p.id}" class="accordion-collapse collapse" data-bs-parent="#player-dev-accordion">
                    <div class="accordion-body">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h5 class="mb-0">Activity Log</h5>
                            <div class="btn-group">
                                <button class="btn btn-sm btn-success dropdown-toggle" type="button" data-bs-toggle="dropdown">Add New Entry</button>
                                <ul class="dropdown-menu dropdown-menu-end">
                                    <li><a class="dropdown-item add-focus-btn" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="hitting">New Hitting Focus</a></li>
                                    <li><a class="dropdown-item add-focus-btn" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="pitching">New Pitching Focus</a></li>
                                    <li><a class="dropdown-item add-focus-btn" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="fielding">New Fielding Focus</a></li>
                                    <li><a class="dropdown-item add-focus-btn" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="baserunning">New Baserunning Focus</a></li>
                                    <li><hr class="dropdown-divider"></li>
                                    <li><a class="dropdown-item" href="#collaboration" onclick="document.querySelector('#collab-player-select').value='${pNameSafe}'; switchTab('#collaboration');">New Coach Note</a></li>
                                </ul>
                            </div>
                        </div>
                        ${activityHtml}
                    </div>
                </div>
            </div>`;
        }).join('');
    }

    function renderLineups() {
        const container = document.getElementById('lineupsAccordion');
        if (!container) return;
        const lineups = AppState.full_data.lineups.filter(l => !l.associated_game_id) || [];
        
        if (lineups.length === 0) {
            container.innerHTML = `<div class="text-center p-4 border rounded"><p class="mb-0">No unassigned lineups saved yet.</p></div>`;
        } else {
            container.innerHTML = lineups.map((l) => `
            <div class="accordion-item" data-lineup-id="${l.id}"><h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#lineup-collapse-${l.id}"><strong>${escapeHTML(l.title)}</strong></button></h2>
                <div id="lineup-collapse-${l.id}" class="accordion-collapse collapse" data-bs-parent="#lineupsAccordion"><div class="accordion-body">
                    <div class="d-flex justify-content-end mb-3"><button class="btn btn-sm btn-info me-2 edit-lineup-btn" data-bs-toggle="modal" data-bs-target="#lineupEditorModal" data-lineup-id="${l.id}">Edit</button><a href="/delete_lineup/${l.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');">Delete</a></div>
                    <table class="table table-striped table-sm"><thead><tr><th style="width: 5%;">#</th><th>Player</th><th style="width: 15%;">Position</th></tr></thead>
                        <tbody>${(l.lineup_positions || []).map((spot, i) => `<tr><td><strong>${i + 1}</strong></td><td>${escapeHTML(spot.name)}</td><td>${spot.position}</td></tr>`).join('') || `<tr><td colspan="3" class="text-center text-muted">This lineup is empty.</td></tr>`}</tbody>
                    </table>
                </div></div>
            </div>`).join('');
        }
    }

    function renderPitchingLog() {
        const summaryContainer = document.getElementById('pitch-count-summary-container');
        if (summaryContainer) {
            let summaryHtml = `<table class="table table-sm table-bordered"><thead class="table-light"><tr><th>Pitcher</th><th>Daily (Limit: 85)</th><th>Weekly (Limit: 100)</th><th>Cumulative (Yearly)</th></tr></thead><tbody>`;
            const summaryData = AppState.pitch_count_summary || {};
            if (Object.keys(summaryData).length > 0) {
                for (const [name, counts] of Object.entries(summaryData)) {
                    const dailyPct = Math.min((counts.daily / 85 * 100), 100);
                    const weeklyPct = Math.min((counts.weekly / 100 * 100), 100);
                    const dailyBg = dailyPct > 80 ? 'bg-danger' : dailyPct > 60 ? 'bg-warning' : 'bg-success';
                    const weeklyBg = weeklyPct > 80 ? 'bg-danger' : weeklyPct > 60 ? 'bg-warning' : 'bg-success';
                    summaryHtml += `
                    <tr><td><strong>${escapeHTML(name)}</strong></td>
                        <td><div class="progress" style="height: 20px;"><div class="progress-bar ${dailyBg}" role="progressbar" style="width: ${dailyPct}%;" aria-valuenow="${counts.daily}">${counts.daily}</div></div></td>
                        <td><div class="progress" style="height: 20px;"><div class="progress-bar ${weeklyBg}" role="progressbar" style="width: ${weeklyPct}%;" aria-valuenow="${counts.weekly}">${counts.weekly}</div></div></td>
                        <td class="text-center align-middle"><strong>${counts.cumulative_year || 0}</strong></td>
                    </tr>`;
                }
            } else {
                summaryHtml += `<tr><td colspan="4" class="text-center">No pitching outings recorded yet.</td></tr>`;
            }
            summaryHtml += `</tbody></table>`;
            summaryContainer.innerHTML = summaryHtml;
        }

        const pitcherSelect = document.getElementById('pitching-log-pitcher-select');
        if (pitcherSelect) {
            pitcherSelect.innerHTML = `<option value="">Select Pitcher</option>` + AppState.full_data.roster.filter(p=>p.pitcher_role !== 'Not a Pitcher').map(p => `<option value="${escapeHTML(p.name)}">${escapeHTML(p.name)}</option>`).join('');
        }

        const outingsList = document.getElementById('recorded-outings-list');
        if (outingsList) {
            const outings = (AppState.full_data.pitching || []).sort((a,b) => b.date.localeCompare(a.date)).slice(0, 10);
            outingsList.innerHTML = outings.map((o) => `
                <li class="list-group-item d-flex justify-content-between align-items-center"><span>${o.date}: <strong>${escapeHTML(o.pitcher)}</strong> vs ${escapeHTML(o.opponent)} - ${o.pitches} pitches <span class="badge bg-info">${o.outing_type}</span></span>
                <a href="/delete_pitching/${o.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');"><i class="bi bi-trash"></i></a></li>`).join('') || `<li class="list-group-item text-muted">No outings recorded.</li>`;
        }
    }

    function renderSigns() {
        const container = document.getElementById('signs-list-container');
        if (!container) return;
        const signs = AppState.full_data.signs || [];
        container.innerHTML = signs.length > 0 ? signs.map((sign) => `
            <li class="list-group-item d-flex justify-content-between align-items-center"><div><strong>${escapeHTML(sign.name)}:</strong> ${escapeHTML(sign.indicator)}</div>
            <div><button class="btn btn-sm btn-info edit-sign-btn" data-bs-toggle="modal" data-bs-target="#editSignModal" data-sign-id="${sign.id}">Edit</button><a href="/delete_sign/${sign.id}" class="btn btn-sm btn-danger" onclick="return confirm('Are you sure?')">Delete</a></div></li>`).join('') : `<li class="list-group-item">No signs have been added.</li>`;
    }

    function renderCollaborationNotes() {
        const teamContainer = document.getElementById('team-notes-container');
        const playerContainer = document.getElementById('player-notes-container');
        if (!teamContainer || !playerContainer) return;
        const collabData = AppState.full_data.collaboration_notes || {};

        const createNoteHTML = (note, note_type) => {
            const noteText = escapeHTML(note.text);
            const author = escapeHTML(note.author);
            return `<div class="card mb-2"><div class="card-body pb-2"><p class="card-text" style="white-space: pre-wrap;">${noteText}</p><small class="text-muted">By ${author} on ${note.timestamp}${note.player_name ? ` for <strong>${escapeHTML(note.player_name)}</strong>` : ''}</small></div>
                <div class="card-footer bg-white border-top-0 text-end py-2">
                    ${canEdit(note.author) ? `<button class="btn btn-sm btn-link text-secondary" data-bs-toggle="modal" data-bs-target="#editNoteModal" data-note-id="${note.id}" data-note-type="${note_type}" data-note-text="${noteText}">Edit</button>` : ''}
                    <a href="/move_note_to_practice_plan/${note_type}/${note.id}" class="btn btn-sm btn-link text-secondary">Move to Plan</a>
                    ${canEdit(note.author) ? `<a href="/delete_note/${note_type}/${note.id}" class="btn btn-sm btn-link text-danger" onclick="return confirm('Are you sure?')">Delete</a>` : ''}
                </div></div>`;
        };

        const teamNotes = (collabData.team_notes || []).sort((a,b) => b.timestamp.localeCompare(a.timestamp));
        teamContainer.innerHTML = teamNotes.map(note => createNoteHTML(note, 'team_notes')).join('') || '<div class="text-center p-3 border rounded text-muted">No team notes yet.</div>';
        const playerNotes = (collabData.player_notes || []).sort((a,b) => b.timestamp.localeCompare(a.timestamp));
        playerContainer.innerHTML = playerNotes.map(note => createNoteHTML(note, 'player_notes')).join('') || '<div class="text-center p-3 border rounded text-muted">No player notes yet.</div>';
        document.getElementById('collab-player-select').innerHTML = '<option value="">Select a player...</option>' + AppState.player_order.map(name => `<option value="${escapeHTML(name)}">${escapeHTML(name)}</option>`).join('');
    }

    function renderScoutingList() {
        const container = document.getElementById('scouting-list-container');
        if (!container) return;
        const scoutingData = AppState.full_data.scouting_list || {};
        const listTypes = {'targets': 'Targets', 'committed': 'Committed', 'not_interested': 'Not Interested'};
        let html = '';
        for (const [key, title] of Object.entries(listTypes)) {
            html += `<div class="col-md-4 mb-3"><div class="card h-100"><div class="card-header fw-bold">${title}</div><div class="card-body p-0"><ul class="list-group list-group-flush">`;
            const players = scoutingData[key] || [];
            if (players.length > 0) {
                players.forEach((p) => {
                    let moveOptions = '';
                    if (key === 'targets') moveOptions = `<li><form action="/move_scouted_player/targets/committed/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item">Move to Committed</button></form></li><li><form action="/move_scouted_player/targets/not_interested/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item">Move to Not Interested</button></form></li>`;
                    else if (key === 'committed') moveOptions = `<li><form action="/move_scouted_player_to_roster/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item fw-bold">Move to Roster</button></form></li><li><hr class="dropdown-divider"></li><li><form action="/move_scouted_player/committed/not_interested/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item">Move to Not Interested</button></form></li>`;

                    const positions = [p.position1, p.position2].filter(Boolean);
                    const positionsDisplay = positions.length > 0 ? `Pos: ${positions.join(' / ')}` : 'Pos: N/A';

                    html += `<li class="list-group-item d-flex justify-content-between align-items-center"><div><div class="fw-bold">${escapeHTML(p.name)}</div><small class="text-muted">${positionsDisplay} | Throws: ${p.throws || 'N/A'} | Bats: ${p.bats || 'N/A'}</small></div>
                        <div class="btn-group"><a href="/delete_scouted_player/${key}/${p.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');" title="Remove Player"><i class="bi bi-trash"></i></a>
                        ${moveOptions ? `<button type="button" class="btn btn-sm btn-outline-secondary dropdown-toggle dropdown-toggle-split" data-bs-toggle="dropdown" aria-expanded="false"><span class="visually-hidden">Toggle Dropdown</span></button><ul class="dropdown-menu dropdown-menu-end">${moveOptions}</ul>` : ''}</div></li>`;
                });
            } else html += `<li class="list-group-item text-center text-muted">No players on this list.</li>`;
            html += `</ul></div></div></div>`;
        }
        container.innerHTML = html;
    }

    function renderGames() {
        const container = document.getElementById('games-list-container');
        if (!container) return;
        const games = (AppState.full_data.games || []).sort((a,b) => b.date.localeCompare(a.date));
        if (games.length === 0) {
            container.innerHTML = `<li class="list-group-item text-center text-muted">No games scheduled. Add one above!</li>`;
            return;
        }
        container.innerHTML = games.map(game => {
            const lineup = AppState.full_data.lineups.find(l => l.associated_game_id === game.id);
            const rotation = AppState.full_data.rotations.find(r => r.associated_game_id === game.id);
            const lineupHTML = lineup ? `<span class="text-success"><i class="bi bi-check-circle-fill"></i> Set</span>` : `<span class="text-muted"><i class="bi bi-x-circle"></i> Not Set</span>`;
            const rotationHTML = rotation ? `<span class="text-success"><i class="bi bi-check-circle-fill"></i> Set</span>` : `<span class="text-muted"><i class="bi bi-x-circle"></i> Not Set</span>`;
            return `<li class="list-group-item" data-game-id="${game.id}">
                <div class="d-flex justify-content-between align-items-center flex-wrap">
                    <div class="me-auto">
                        <h5 class="mb-1">vs ${escapeHTML(game.opponent)}</h5>
                        <p class="mb-1"><i class="bi bi-calendar-event"></i> ${game.date} <span class="text-muted mx-2">|</span> <i class="bi bi-geo-alt"></i> ${escapeHTML(game.location || 'TBD')}</p>
                    </div>
                    <div class="d-flex align-items-center mt-2 mt-md-0">
                        <div class="text-end me-3"><div class="mb-1"><strong>Lineup:</strong> ${lineupHTML}</div><div><strong>Rotation:</strong> ${rotationHTML}</div></div>
                        <div class="btn-group-vertical btn-group-sm">
                            <a href="/game/${game.id}" class="btn btn-primary"><i class="bi bi-tools"></i> Manage</a>
                            <a href="/delete_game/${game.id}" class="btn btn-outline-danger" onclick="return confirm('Are you sure you want to delete this game?');"><i class="bi bi-trash"></i> Delete</a>
                        </div>
                    </div>
                </div></li>`;
        }).join('');
    }

    function renderPracticePlans() {
        const container = document.getElementById('practicePlanAccordion');
        if (!container) return;
        const plans = (AppState.full_data.practice_plans || []).sort((a,b) => b.date.localeCompare(a.date));
        if (plans.length === 0) {
            container.innerHTML = `<div class="text-center p-4 border rounded"><p class="mb-0">No practice plans saved yet. Create one above!</p></div>`;
            return;
        }
        container.innerHTML = plans.map(plan => `
            <div class="accordion-item" data-plan-id="${plan.id}"><h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#practice-plan-collapse-${plan.id}"><strong>${plan.date}</strong> - ${escapeHTML(plan.general_notes || 'No general notes')}</button></h2>
                <div id="practice-plan-collapse-${plan.id}" class="accordion-collapse collapse" data-bs-parent="#practicePlanAccordion"><div class="accordion-body practice-plan">
                    <form action="/edit_practice_plan/${plan.id}" method="POST" class="row g-3 mb-3 align-items-end">
                        <div class="col-md-3"><label class="form-label">Date:</label><input type="date" name="plan_date" class="form-control" value="${plan.date}" required></div>
                        <div class="col-md-7"><label class="form-label">General Notes:</label><input type="text" name="general_notes" class="form-control" value="${escapeHTML(plan.general_notes || '')}" placeholder="General theme or focus"></div>
                        <div class="col-md-2 d-flex justify-content-end"><button type="submit" class="btn btn-sm btn-primary me-2">Save</button><a href="/delete_practice_plan/${plan.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');">Delete</a></a></div>
                    </form><hr><h5>Tasks</h5>
                    <form action="/add_task_to_plan/${plan.id}" method="POST" class="mb-3 add-task-form"><div class="input-group"><input type="text" name="task_text" class="form-control" placeholder="Add a new task..." required><button type="submit" class="btn btn-primary">Add Task</button></div></form>
                    <ul class="list-group task-list">${(plan.tasks || []).map(task => `<li class="list-group-item d-flex justify-content-between align-items-center task-item ${task.status === 'complete' ? 'complete' : ''}" data-task-id="${task.id}" data-plan-id="${plan.id}">
                        <div class="form-check"><input class="form-check-input task-checkbox" type="checkbox" value="" ${task.status === 'complete' ? 'checked' : ''} id="task-${task.id}"><label class="form-check-label" for="task-${task.id}">${escapeHTML(task.text)}<div class="text-muted small">By ${escapeHTML(task.author)} on ${task.timestamp}</div></label></div>
                        <a href="/delete_task/${plan.id}/${task.id}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure?');"><i class="bi bi-trash"></i></a></li>`).join('') || '<li class="list-group-item text-muted text-center">No tasks for this plan yet.</li>'}</ul>
                </div></div>
            </div>`).join('');
        attachTaskListeners();
    }

    function renderAll() {
        renderRoster();
        renderPlayerDevelopment();
        renderLineups();
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
        const savePlayerBtn = event.target.closest('button');
        const playerId = savePlayerBtn.dataset.playerId;
        const accordionBody = savePlayerBtn.closest('.accordion-body');
        const formData = new FormData();
        accordionBody.querySelectorAll('input, select, textarea').forEach(input => formData.append(input.name, input.value));

        const originalText = savePlayerBtn.textContent;
        savePlayerBtn.disabled = true;
        savePlayerBtn.textContent = 'Saving...';

        try {
            const response = await fetch(`/update_player_inline/${playerId}`, {
                method: 'POST',
                body: formData
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.message);
            
            savePlayerBtn.textContent = 'Saved!';
            savePlayerBtn.classList.replace('btn-primary', 'btn-success');
        } catch (err) {
            alert(`Error: ${err.message}`);
            savePlayerBtn.textContent = 'Save Failed';
            savePlayerBtn.classList.replace('btn-primary', 'btn-danger');
        } finally {
            setTimeout(() => {
                savePlayerBtn.textContent = originalText;
                savePlayerBtn.classList.remove('btn-success', 'btn-danger');
                savePlayerBtn.classList.add('btn-primary');
                savePlayerBtn.disabled = false;
            }, 2000);
        }
    }

    function attachTaskListeners() {
        document.querySelectorAll('.task-checkbox').forEach(checkbox => {
            checkbox.removeEventListener('change', handleTaskCheckboxChange);
            checkbox.addEventListener('change', handleTaskCheckboxChange);
        });
    }

    async function handleTaskCheckboxChange(event) {
        const listItem = event.target.closest('.task-item');
        const taskId = listItem.dataset.taskId;
        const planId = listItem.dataset.planId;
        const newStatus = event.target.checked ? 'complete' : 'pending';

        try {
            const response = await fetch(`/update_task_status/${planId}/${taskId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: newStatus })
            });
            const result = await response.json();
            if (result.status === 'success') {
                listItem.classList.toggle('complete', event.target.checked);
            } else {
                alert('Error updating task status: ' + result.message);
                event.target.checked = !event.target.checked;
            }
        } catch (error) {
            alert('An error occurred while updating task status.');
            event.target.checked = !event.target.checked;
        }
    }

    // --- INITIALIZATION ---

    async function init() {
        try {
            const response = await fetch('/get_app_data');
            if (!response.ok) throw new Error(`Failed to fetch app data: ${response.statusText}`);
            const serverData = await response.json();
            Object.assign(AppState, serverData);
        } catch (error) {
            console.error("Initialization Error: Failed to fetch app data.", error);
            document.body.innerHTML = `<div class="alert alert-danger m-3">Could not load application data. Please try refreshing.</div>`;
            return;
        }

        renderAll();
        lineupEditorModal = new bootstrap.Modal(document.getElementById('lineupEditorModal'));
        initializeSortables();
        setupEventListeners();
        
        const hash = window.location.hash || '#roster';
        switchTab(hash.split('?')[0]);

        const socket = io();
        socket.on('data_updated', async (msg) => {
            console.log('Data update received:', msg.message);
            const openPlanItem = document.querySelector('#practicePlanAccordion .accordion-collapse.show');
            const openPlanId = openPlanItem ? openPlanItem.closest('.accordion-item').dataset.planId : null;

            try {
                const response = await fetch('/get_app_data');
                const serverData = await response.json();
                Object.assign(AppState, serverData);
                renderAll(); 

                if (openPlanId) {
                    const newCollapseElement = document.getElementById(`practice-plan-collapse-${openPlanId}`);
                    const newButtonElement = document.querySelector(`button[data-bs-target="#practice-plan-collapse-${openPlanId}"]`);
                    if (newCollapseElement && newButtonElement) {
                        newCollapseElement.classList.add('show');
                        newButtonElement.classList.remove('collapsed');
                    }
                }
            } catch (error) {
                console.error("Error refreshing data after update:", error);
            }
        });
    }

    function initializeSortables() {
        Object.values(sortableInstances).forEach(s => { if (s.destroy) s.destroy(); });
        sortableInstances = {}; // Clear out old instances
        
        const createSortable = (id, handleClass, onEndCallback) => {
            const el = document.getElementById(id);
            if(el) {
                sortableInstances[id] = new Sortable(el, {
                    handle: handleClass,
                    animation: 150,
                    onEnd: onEndCallback
                });
            }
        };
        
        const savePlayerOrder = () => {
            const newPlayerOrder = Array.from(document.getElementById('rosterAccordion').children).map(item => item.dataset.playerName);
            AppState.player_order = newPlayerOrder;
            fetch('/save_player_order', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ player_order: newPlayerOrder })
            });
        };

        createSortable('rosterAccordion', '.drag-handle', savePlayerOrder);
        createSortable('player-dev-accordion', '.drag-handle', savePlayerOrder);
    }

    function setupEventListeners() {
        document.getElementById('rosterSearch').addEventListener('input', renderRoster);
        
        document.body.addEventListener('click', (event) => {
            const tabLink = event.target.closest('a[data-bs-toggle="tab"]');
            if (tabLink) {
                event.preventDefault();
                switchTab(tabLink.getAttribute('href'));
            }

            if(event.target.closest('[data-bs-target="#editSignModal"]')) {
                 const signId = parseInt(event.target.closest('button').dataset.signId, 10);
                const sign = (AppState.full_data.signs || []).find(s => s.id === signId);
                const form = document.getElementById('editSignForm');
                form.action = `/update_sign/${sign.id}`;
                form.querySelector('#editSignName').value = sign.name;
                form.querySelector('#editSignIndicator').value = sign.indicator;
            }
        });

        const moreMenuButton = document.getElementById('mobile-more-button');
        const moreMenuOverlay = document.getElementById('more');
        const moreMenuCloseButton = document.getElementById('more-menu-close-btn');

        if (moreMenuButton) {
            moreMenuButton.addEventListener('click', (e) => {
                e.preventDefault();
                moreMenuOverlay.classList.remove('hidden');
                document.querySelectorAll('.bottom-nav .nav-item').forEach(link => link.classList.remove('active'));
                moreMenuButton.classList.add('active');
            });
        }
        if (moreMenuCloseButton) {
            moreMenuCloseButton.addEventListener('click', (e) => {
                e.preventDefault();
                moreMenuOverlay.classList.add('hidden');
                switchTab(currentActiveTabId);
            });
        }
        
        // Modal Event Listeners
        document.getElementById('addPlayerModal')?.addEventListener('show.bs.modal', (e) => e.target.querySelector('form').reset());
        document.getElementById('confirmDeleteModal')?.addEventListener('show.bs.modal', (e) => {
            document.getElementById('playerNameToDelete').textContent = e.relatedTarget.dataset.playerName;
            document.getElementById('confirmDeleteButton').href = `/delete_player/${e.relatedTarget.dataset.playerId}`;
        });
        document.getElementById('lineupEditorModal')?.addEventListener('show.bs.modal', (e) => {
            const lineupId = e.relatedTarget ? e.relatedTarget.dataset.lineupId : null;
            const lineup = lineupId ? AppState.full_data.lineups.find(l => l.id == lineupId) : null;
            openLineupEditor(lineup);
        });
        document.getElementById('editNoteModal')?.addEventListener('show.bs.modal', (e) => {
            e.target.querySelector('#editNoteId').value = e.relatedTarget.dataset.noteId;
            e.target.querySelector('#editNoteType').value = e.relatedTarget.dataset.noteType;
            e.target.querySelector('#editNoteText').value = e.relatedTarget.dataset.noteText;
        });
        document.getElementById('editFocusModal')?.addEventListener('show.bs.modal', (e) => {
            const btn = e.relatedTarget;
            const form = e.target.querySelector('form');
            form.reset();
            const focusId = btn.dataset.focusId;
            if (focusId) {
                e.target.querySelector('.modal-title').textContent = 'Edit Development Focus';
                form.action = `/update_focus/${focusId}`;
                const playerName = btn.dataset.playerName;
                const focusItem = AppState.full_data.player_development[playerName]?.find(item => item.id == focusId && item.type === 'Development');
                if (focusItem) {
                    form.querySelector('#focusSkill').value = focusItem.subtype;
                    form.querySelector('#focusText').value = focusItem.text.replace(/^(New Focus|Completed): /i, '');
                    form.querySelector('#focusNotes').value = focusItem.notes || '';
                }
            } else {
                e.target.querySelector('.modal-title').textContent = 'Add Development Focus';
                form.action = `/add_focus/${encodeURIComponent(btn.dataset.playerName)}`;
                form.querySelector('#focusSkill').value = btn.dataset.skill;
            }
        });

        // Form Submissions
        document.getElementById('saveLineupBtn')?.addEventListener('click', async () => {
            const modal = document.getElementById('lineupEditorModal');
            const id = modal.querySelector('#lineupId').value;
            const title = modal.querySelector('#lineupTitle').value;
            if (!title) return alert('Lineup Title is required.');
            const lineup_data = Array.from(modal.querySelectorAll('#lineup-order .list-group-item')).map(item => ({
                name: item.dataset.playerName, position: '' }));
            const payload = { title, lineup_data, associated_game_id: null };
            const url = id ? `/edit_lineup/${id}` : '/add_lineup';
            try {
                const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                if(!response.ok) throw new Error((await response.json()).message);
                lineupEditorModal.hide();
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        });
    }
    
    function openLineupEditor(lineup = null) {
        const modal = document.getElementById('lineupEditorModal');
        modal.querySelector('#lineupId').value = lineup ? lineup.id : '';
        modal.querySelector('#lineupTitle').value = lineup ? lineup.title : 'New Unassigned Lineup';
        const bench = modal.querySelector('#lineup-bench'), order = modal.querySelector('#lineup-order');
        bench.innerHTML = '', order.innerHTML = '';

        const lineupPlayerNames = new Set((lineup ? lineup.lineup_positions : []).map(p => p.name));
        AppState.full_data.roster.forEach(player => {
            if (!lineupPlayerNames.has(player.name)) {
                bench.insertAdjacentHTML('beforeend', `<div class="list-group-item" data-player-name="${player.name}">${player.name}</div>`);
            }
        });
        
        const createBattingOrderItem = (player) => {
            return `<div class="list-group-item d-flex justify-content-between align-items-center" data-player-name="${player.name}">
                        <span>${player.name} (#${player.number || 'N/A'})</span>
                    </div>`;
        };
        (lineup ? lineup.lineup_positions : []).forEach(spot => {
            const player = AppState.full_data.roster.find(p => p.name === spot.name);
            if (player) order.insertAdjacentHTML('beforeend', createBattingOrderItem(player));
        });

        if(sortableInstances.lineupBench) sortableInstances.lineupBench.destroy();
        if(sortableInstances.lineupOrder) sortableInstances.lineupOrder.destroy();
        
        sortableInstances.lineupBench = new Sortable(bench, { group: 'lineup', animation: 150 });
        sortableInstances.lineupOrder = new Sortable(order, { 
            group: 'lineup', 
            animation: 150,
            onAdd: (evt) => {
                const player = AppState.full_data.roster.find(p => p.name === evt.item.dataset.playerName);
                if (player) evt.item.outerHTML = createBattingOrderItem(player);
            }
        });
    }

    // --- TAB SWITCHING LOGIC ---
    let currentActiveTabId = '#roster';

    function switchTab(targetTabSelector) {
        if (!targetTabSelector || targetTabSelector === '#') return;
        
        document.querySelectorAll('.tab-content > .tab-pane').forEach(p => p.classList.remove('show', 'active'));
        document.querySelectorAll('.navbar-nav .nav-link, .bottom-nav .nav-item').forEach(l => {
            l.classList.remove('active');
            if(l.dataset.iconInactive) l.querySelector('i').className = l.dataset.iconInactive;
        });
        
        document.querySelector(targetTabSelector)?.classList.add('show', 'active');
        document.querySelector(`.desktop-nav a[href="${targetTabSelector}"]`)?.classList.add('active');
        
        const mobileTabLink = document.querySelector(`.bottom-nav a[href="${targetTabSelector}"]`);
        if (mobileTabLink) {
            mobileTabLink.classList.add('active');
            if(mobileTabLink.dataset.iconActive) mobileTabLink.querySelector('i').className = mobileTabLink.dataset.iconActive;
        } else {
            const moreBtn = document.getElementById('mobile-more-button');
            if(moreBtn) {
                moreBtn.classList.add('active');
                if(moreBtn.dataset.iconActive) moreBtn.querySelector('i').className = moreBtn.dataset.iconActive;
            }
        }

        document.getElementById('more')?.classList.add('hidden');
        if (history.pushState) {
            history.pushState(null, null, targetTabSelector);
        } else {
            window.location.hash = targetTabSelector;
        }
        currentActiveTabId = targetTabSelector;
        window.scrollTo(0, 0);
    }

    // Start the application
    init();
});
