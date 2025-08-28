// static/js/main.js
document.addEventListener('DOMContentLoaded', () => {

    window.switchTab = function(tabElement) {
        if (tabElement) {
            const tab = bootstrap.Tab.getOrCreateInstance(tabElement);
            tab.show();
        }
    };

    const AppState = {
        full_data: {},
        player_order: [],
        session: {},
        pitch_count_summary: {},
        roster_sort: { key: 'name', order: 'asc' },
        active_player_dev_name: null,
        dev_player_sort: { key: 'custom', order: 'asc' }
    };

    let sortableInstances = {};
    let lineupEditorModal;
    let confirmDeleteModal;
    
    // --- UTILITY FUNCTIONS ---
    const escapeHTML = str => String(str).replace(/[&<>'"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;',"'": '&#39;','"': '&quot;'}[tag] || tag));
    const canEdit = (author) => AppState.session.username === author || ['Head Coach', 'Super Admin'].includes(AppState.session.role);

    const formatDateTime = (s) => {
        if (!s || s === 'Never') return s;
        try {
            const dt = new Date(s.replace(' ', 'T'));
            if (isNaN(dt)) throw new Error('Invalid date');
            
            if (s.length <= 10) {
                 return dt.toLocaleDateString('en-US', { weekday: 'long', year: '2-digit', month: '2-digit', day: '2-digit' });
            }
            return dt.toLocaleDateString('en-US', { weekday: 'long', year: '2-digit', month: '2-digit', day: '2-digit' }) + ', ' + 
                   dt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
        } catch (e) {
            return s;
        }
    };

    const renderPositionSelect = (name, id, selectedVal = '', title = 'Select Position', classes = 'form-select form-select-sm') => {
        let positions = ['P', 'C', '1B', '2B', '3B', 'SS'];
        if (AppState.session.outfielder_count === 4) {
            positions.push('LF', 'LCF', 'RCF', 'RF');
        } else {
            positions.push('LF', 'CF', 'RF');
        }
        positions.push('DH', 'EH');
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
        const formattedTimestamp = p.notes_timestamp ? formatDateTime(p.notes_timestamp) : '';
        const deleteButtonHtml = `<button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_player/${p.id}" data-delete-name="${pNameSafe}">Delete</button>`;

        const positions = [p.position1, p.position2, p.position3].filter(Boolean).map(pos => `<span class="badge bg-secondary me-1">${pos}</span>`).join('') || '<span class="text-muted small">N/A</span>';
        const batsThrows = `B/T: ${p.bats?.[0] || 'N'}/${p.throws?.[0] || 'N'}`;

        return `
        <div class="col-12" data-player-name="${pNameSafe}">
            <div class="card player-card">
                <div class="card-header d-flex justify-content-between align-items-center" data-bs-toggle="collapse" href="#collapse-roster-${p.id}" style="cursor: pointer;">
                    <h6 class="mb-0">
                        <i class="bi bi-grip-vertical text-muted drag-handle" style="cursor: move;" title="Drag to reorder"></i>
                        <strong class="ms-2">${pNameSafe}</strong>
                    </h6>
                    <div class="d-flex align-items-center">
                        <div class="me-3 d-none d-sm-block">${positions}</div>
                        <span class="badge bg-primary rounded-pill">#${p.number || 'N/A'}</span>
                    </div>
                </div>
                <div id="collapse-roster-${p.id}" class="collapse">
                    <div class="card-body bg-light">
                        <div class="row g-3 align-items-end">
                            <div class="col-12"><h5>Player Notes</h5></div>
                            <div class="col-12"><textarea class="form-control" name="notes" rows="2" placeholder="Notes">${pNotesSafe}</textarea></div>
                            ${(p.notes_author && p.notes_author !== 'N/A') ? `<div class="col-12 text-end"><small class="text-muted fst-italic">Last saved: ${pNotesAuthorSafe} on ${formattedTimestamp}</small></div>` : ''}
                            <hr class="my-3">
                            <div class="col-12 col-md-4"><label class="form-label">Name</label><input type="text" class="form-control" name="name" value="${pNameSafe}"></div>
                            <div class="col-6 col-md-2"><label class="form-label">J#</label><input type="number" class="form-control" name="number" value="${p.number || ''}"></div>
                            <div class="col-6 col-md-3"><label class="form-label">Pos 1</label>${renderPositionSelect('position1', `position1_${p.id}`, p.position1, '', 'form-select')}</div>
                            <div class="col-6 col-md-3"><label class="form-label">Pos 2</label>${renderPositionSelect('position2', `position2_${p.id}`, p.position2, '', 'form-select')}</div>
                            <div class="col-6 col-md-3"><label class="form-label">Pos 3</label>${renderPositionSelect('position3', `position3_${p.id}`, p.position3, '', 'form-select')}</div>
                            <div class="col-6 col-md-3"><label class="form-label">Throws</label><select name="throws" class="form-select"><option value="Right" ${p.throws === 'Right' ? 'selected' : ''}>Right</option><option value="Left" ${p.throws === 'Left' ? 'selected' : ''}>Left</option></select></div>
                            <div class="col-6 col-md-3"><label class="form-label">Bats</label><select name="bats" class="form-select"><option value="Right" ${p.bats === 'Right' ? 'selected' : ''}>Right</option><option value="Left" ${p.bats === 'Left' ? 'selected' : ''}>Left</option></select></div>
                            <div class="col-6 col-md-3"><label class="form-label">Pitcher Role</label><select name="pitcher_role" class="form-select"><option value="Not a Pitcher" ${p.pitcher_role === "Not a Pitcher" ? 'selected' : ''}>Not a Pitcher</option><option value="Starter" ${p.pitcher_role === "Starter" ? 'selected' : ''}>Starter</option><option value="Reliever" ${p.pitcher_role === "Reliever" ? 'selected' : ''}>Reliever</option></select></div>
                            <div class="col-12 d-flex justify-content-end mt-3"><button type="button" class="btn btn-sm btn-primary me-2 save-player-btn" data-player-id="${p.id}">Save</button>${deleteButtonHtml}</div>
                            <div class="col-12 mt-2"><div class="save-feedback" style="display: none;"></div></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>`;
    }

    function renderRoster() {
        const container = document.getElementById('roster-cards-container');
        if (!container) return;
        const searchTerm = document.getElementById('rosterSearch').value.toLowerCase();
        
        let rosterToSort = [...(AppState.full_data.roster || [])];

        rosterToSort.sort((a, b) => {
            const indexA = AppState.player_order.indexOf(a.name);
            const indexB = AppState.player_order.indexOf(b.name);
            if (indexA === -1 && indexB === -1) return a.name.localeCompare(b.name);
            if (indexA === -1) return 1;
            if (indexB === -1) return -1;
            return indexA - indexB;
        });
        
        const filteredRoster = rosterToSort.filter(p => 
            !searchTerm || p.name.toLowerCase().includes(searchTerm) || (p.number || '').toString().includes(searchTerm)
        );

        container.innerHTML = filteredRoster.length > 0 ? filteredRoster.map(playerTemplate).join('') : `<div class="p-3 text-center text-muted">No players found.</div>`;
        attachRosterSaveListeners();
    }

    function renderPlayerDevelopmentList() {
        const container = document.getElementById('dev-player-list');
        if (!container) return;

        const playerDevData = AppState.full_data.player_development || {};
        const roster = [...(AppState.full_data.roster || [])];
        const searchTerm = document.getElementById('devPlayerSearch').value.toLowerCase();

        const filteredRoster = roster.filter(p => p.name.toLowerCase().includes(searchTerm));

        if (AppState.dev_player_sort.key === 'name') {
            filteredRoster.sort((a, b) => {
                if (AppState.dev_player_sort.order === 'asc') return a.name.localeCompare(b.name);
                return b.name.localeCompare(a.name);
            });
        } else {
             const customOrderedNames = AppState.player_order.filter(name => filteredRoster.some(p => p.name === name));
             filteredRoster.sort((a,b) => customOrderedNames.indexOf(a.name) - customOrderedNames.indexOf(b.name));
        }

        container.innerHTML = filteredRoster.map(p => {
            const pNameSafe = escapeHTML(p.name);
            const activeFocusCount = (playerDevData[p.name] || []).filter(log => log.type === 'Development' && log.status === 'active').length;
            const summaryText = activeFocusCount > 0 ? `${activeFocusCount} active focus${activeFocusCount > 1 ? 'es' : ''}` : 'No active focuses';

            return `<a href="#" class="list-group-item list-group-item-action" data-player-name="${pNameSafe}">
                        <div class="d-flex w-100 justify-content-between align-items-center">
                            <div>
                               <i class="bi bi-grip-vertical me-2 drag-handle"></i>
                               <span class="fw-bold">${pNameSafe}</span>
                            </div>
                            <small>${summaryText}</small>
                        </div>
                    </a>`;
        }).join('');

        container.querySelectorAll('.list-group-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.classList.contains('drag-handle')) return;
                e.preventDefault();
                AppState.active_player_dev_name = item.dataset.playerName;
                renderPlayerDevelopmentDetails();
                container.querySelector('.active')?.classList.remove('active');
                item.classList.add('active');

                // On mobile, scroll down to the details view automatically
                if (window.innerWidth < 992) { // Corresponds to Bootstrap's 'lg' breakpoint
                    const detailsContainer = document.getElementById('player-dev-content');
                    if (detailsContainer) {
                        detailsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                }
            });
        });

        document.querySelectorAll('#dev-sort-az, #dev-sort-za, #dev-sort-custom').forEach(btn => btn.classList.remove('active'));
        if(AppState.dev_player_sort.key === 'name' && AppState.dev_player_sort.order === 'asc') document.getElementById('dev-sort-az').classList.add('active');
        if(AppState.dev_player_sort.key === 'name' && AppState.dev_player_sort.order === 'desc') document.getElementById('dev-sort-za').classList.add('active');
        if(AppState.dev_player_sort.key === 'custom') document.getElementById('dev-sort-custom').classList.add('active');
    }

    function renderPlayerDevelopmentDetails() {
        const container = document.getElementById('player-dev-content');
        if (!container) return;

        const playerName = AppState.active_player_dev_name;
        if (!playerName) {
            container.innerHTML = `<div class="text-center p-5 text-muted"><i class="bi bi-arrow-left-circle-fill" style="font-size: 3rem;"></i><h4 class="mt-3">Select a player</h4><p>Select a player from the list to view their development log.</p></div>`;
            return;
        }

        const playerDevData = AppState.full_data.player_development || {};
        const activityLog = playerDevData[playerName] || [];
        const pNameSafe = escapeHTML(playerName);
        
        const getIconForType = (type) => ({'Development': '<i class="bi bi-graph-up-arrow text-primary"></i>', 'Coach Note': '<i class="bi bi-chat-left-text-fill text-info"></i>', 'Lessons': '<i class="bi bi-person-video3 text-success"></i>'}[type] || '<i class="bi bi-record-circle"></i>');
        const activityHtml = activityLog.length > 0 ? `<ul class="list-group">${activityLog.map(log => {
            let itemClass = '', statusText = '', mainText = escapeHTML(log.text || log.focus); // FIX: check for log.focus as well
            if (log.type === 'Development') {
                itemClass = log.status === 'completed' ? 'completed-focus' : 'active-focus';
                if (log.status === 'completed') {
                    statusText = `<span class="badge bg-success ms-2">Completed: ${formatDateTime(log.completed_date)}</span>`;
                }
            } else if (log.type === 'Lessons') {
                itemClass = 'lesson-entry';
            } else if (log.type === 'Coach Note') {
                itemClass = 'coach-note-entry';
            }
            
            let actions = '';
            if (canEdit(log.author) || log.type === 'Development') {
                if (log.type === 'Development') actions = `<button class="btn btn-sm btn-link text-secondary py-0" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-focus-id="${log.id}" data-player-name="${pNameSafe}">Edit</button><button type="button" class="btn btn-sm btn-link text-danger py-0" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_focus/${log.id}" data-delete-name="this focus">Delete</button>`;
                else if (log.type === 'Coach Note') actions = `<button class="btn btn-sm btn-link text-secondary py-0" data-bs-toggle="modal" data-bs-target="#editNoteModal" data-note-id="${log.id}" data-note-type="player_notes" data-note-text="${escapeHTML(log.text)}">Edit</button><button type="button" class="btn btn-sm btn-link text-danger py-0" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_note/player_notes/${log.id}" data-delete-name="this note">Delete</button>`;
            }
            return `<li class="list-group-item ${itemClass}"><div class="d-flex w-100 justify-content-between"><h6 class="mb-1">${getIconForType(log.type)} ${escapeHTML(log.subtype)}: <span class="text-muted fw-normal">${mainText}</span>${statusText}</h6><small>${formatDateTime(log.date)}</small></div>${log.notes ? `<p class="mb-1 text-muted small fst-italic">Notes: ${escapeHTML(log.notes)}</p>` : ''}${log.progress_notes ? `<p class="mb-1 text-muted small fst-italic">Progress: ${escapeHTML(log.progress_notes)}</p>` : ''}<small class="text-muted">By: ${escapeHTML(log.author)}</small>${actions ? `<div class="mt-2">${actions}</div>` : ''}</li>`;
        }).join('')}</ul>` : `<div class="text-center p-3 border rounded"><p class="mb-0">No activity logged.</p></div>`;
        container.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h4 class="mb-0">${pNameSafe} - Development Log</h4>
                <div class="btn-group">
                    <button class="btn btn-sm btn-success dropdown-toggle" type="button" data-bs-toggle="dropdown">Add New</button>
                    <ul class="dropdown-menu dropdown-menu-end">
                        <li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="hitting">Hitting Focus</a></li>
                        <li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="pitching">Pitching Focus</a></li>
                        <li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="fielding">Fielding Focus</a></li>
                        <li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#editFocusModal" data-player-name="${pNameSafe}" data-skill="baserunning">Baserunning Focus</a></li>
                        <li><hr class="dropdown-divider"></li>
                        <li><a class="dropdown-item" href="#collaboration" onclick="document.querySelector('#collab-player-select').value='${pNameSafe}'; window.switchTab(document.querySelector('a[href=\\'#collaboration\\']'));">Coach Note</a></li>
                    </ul>
                </div>
            </div>
            ${activityHtml}
        `;
    }

    function renderLineups() {
        const container = document.getElementById('lineupsAccordion');
        if (!container) return;
        const lineups = AppState.full_data.lineups.filter(l => !l.associated_game_id) || [];
        container.innerHTML = lineups.length === 0 
            ? `<div class="text-center p-4 border rounded"><p class="mb-0">No unassigned lineups saved yet.</p></div>` 
            : lineups.map((l) => {
                const lineupHtml = (l.lineup_positions && l.lineup_positions.length > 0)
                    ? `<ol class="list-group list-group-numbered">${l.lineup_positions.map(name => `<li class="list-group-item">${escapeHTML(name)}</li>`).join('')}</ol>`
                    : `<p class="text-center text-muted">This lineup is empty.</p>`;
                const editButtonHtml = `<button type="button" class="btn btn-sm btn-outline-secondary me-2" data-bs-toggle="modal" data-bs-target="#lineupEditorModal" data-lineup-id="${l.id}">Edit</button>`;
                const deleteButtonHtml = `<button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_lineup/${l.id}" data-delete-name="${escapeHTML(l.title)}">Delete</button>`;
                return `<div class="accordion-item" data-lineup-id="${l.id}">
                            <h2 class="accordion-header">
                                <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#lineup-collapse-${l.id}">
                                    <strong>${escapeHTML(l.title)}</strong>
                                </button>
                            </h2>
                            <div id="lineup-collapse-${l.id}" class="accordion-collapse collapse" data-bs-parent="#lineupsAccordion">
                                <div class="accordion-body">
                                    <div class="d-flex justify-content-end mb-3">
                                        ${editButtonHtml}
                                        ${deleteButtonHtml}
                                    </div>
                                    ${lineupHtml}
                                </div>
                            </div>
                        </div>`;
            }).join('');
    }
    
    function renderRotations() {
        const container = document.getElementById('rotationsAccordion');
        if (!container) return;
        const rotations = AppState.full_data.rotations.filter(r => !r.associated_game_id) || [];
        container.innerHTML = rotations.length === 0 ? `<div class="text-center p-4 border rounded"><p class="mb-0">No unassigned rotations saved.</p><p class="small text-muted">Create rotations from the 'Manage' screen of any game.</p></div>` : rotations.map((r) => {
            const inningsCount = r.innings ? Object.keys(r.innings).length : 0;
            const deleteButtonHtml = `<button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_rotation/${r.id}" data-delete-name="${escapeHTML(r.title)}">Delete</button>`;
            return `<div class="accordion-item" data-rotation-id="${r.id}"><h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#rotation-collapse-${r.id}"><strong>${escapeHTML(r.title)}</strong></button></h2><div id="rotation-collapse-${r.id}" class="accordion-collapse collapse" data-bs-parent="#rotationsAccordion"><div class="accordion-body"><div class="d-flex justify-content-end mb-3">${deleteButtonHtml}</div><p>This rotation has <strong>${inningsCount}</strong> inning(s) defined. You can manage this rotation by assigning it to a game.</p></div></div></div>`;
        }).join('');
    }

    function renderPitchingLog() {
        const summaryContainer = document.getElementById('pitch-count-summary-container');
        if (summaryContainer) {
            const summaryData = AppState.pitch_count_summary || {};
            const roster = AppState.full_data.roster || [];

            const pitchers = roster.filter(p => {
                const summary = summaryData[p.name];
                return p.pitcher_role !== 'Not a Pitcher' || (summary && (summary.daily > 0 || summary.weekly > 0));
            });

            const sortedPitchers = pitchers.sort((a, b) => {
                const indexA = AppState.player_order.indexOf(a.name);
                const indexB = AppState.player_order.indexOf(b.name);
                if (indexA === -1 && indexB === -1) return a.name.localeCompare(b.name);
                if (indexA === -1) return 1;
                if (indexB === -1) return -1;
                return indexA - indexB;
            });

            let summaryHtml = '<div class="table-responsive"><table class="table table-sm table-bordered table-striped"><thead class="table-light"><tr><th>Pitcher</th><th>Daily Max</th><th>Weekly</th><th>Status</th></tr></thead><tbody>';
            if (sortedPitchers.length > 0) {
                for (const pitcher of sortedPitchers) {
                    const name = pitcher.name;
                    const counts = summaryData[name];
                    if (counts) {
                        const dailyPct = Math.min((counts.daily / counts.max_daily * 100), 100);
                        const weeklyPct = Math.min((counts.weekly / 100 * 100), 100);
                        const dailyBg = dailyPct > 80 ? 'bg-danger' : dailyPct > 60 ? 'bg-warning' : 'bg-success';
                        const statusBadge = counts.status === 'Available' ? '<span class="badge bg-success">Available</span>' : '<span class="badge bg-danger">Resting</span>';
                        const nextAvailableText = counts.status === 'Resting' ? `<br><small class="text-muted">Next up: ${counts.next_available}</small>` : '';
                        summaryHtml += `<tr><td class="align-middle"><strong>${escapeHTML(name)}</strong></td><td class="align-middle"><div class="progress" style="height: 20px;"><div class="progress-bar ${dailyBg}" role="progressbar" style="width: ${dailyPct}%;" aria-valuenow="${counts.daily}">${counts.daily}</div></div><small class="text-muted">${counts.pitches_remaining_today} remaining</small></td><td class="align-middle"><div class="progress" style="height: 20px;"><div class="progress-bar" role="progressbar" style="width: ${weeklyPct}%;" aria-valuenow="${counts.weekly}">${counts.weekly}</div></div></td><td class="text-center align-middle">${statusBadge}${nextAvailableText}</td></tr>`;
                    }
                }
            } else { summaryHtml += '<tr><td colspan="4" class="text-center text-muted">No pitching data.</td></tr>'; }
            summaryHtml += '</tbody></table></div>';
            summaryContainer.innerHTML = summaryHtml;
        }

        const pitcherSelect = document.getElementById('pitching-log-pitcher-select');
        if (pitcherSelect) {
            pitcherSelect.innerHTML = '<option value="">Select Pitcher</option>' + AppState.full_data.roster.map(p => `<option value="${p.id}">${escapeHTML(p.name)}</option>`).join('');
        }

        const pitchDateInput = document.getElementById('pitch_date');
        if (pitchDateInput && !pitchDateInput.value) {
            pitchDateInput.value = new Date().toISOString().split('T')[0];
        }

        const outingsList = document.getElementById('recorded-outings-list');
        if (outingsList) {
            const outings = (AppState.full_data.pitching || []).sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, 10);
            outingsList.innerHTML = outings.map((o) => {
                const deleteButtonHtml = `<button type="button" class="btn btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_pitching/${o.id}" data-delete-name="this pitching outing for ${escapeHTML(o.player_name)}"><i class="bi bi-trash"></i></button>`;
                return `
                <li class="list-group-item d-flex justify-content-between align-items-center">
                    <span>${formatDateTime(o.date)}: <strong>${escapeHTML(o.player_name)}</strong> vs ${escapeHTML(o.opponent)} - ${o.pitches} pitches <span class="badge bg-info">${o.outing_type}</span></span>
                    <div class="btn-group btn-group-sm">
                        <button type="button" class="btn btn-outline-secondary" data-bs-toggle="modal" data-bs-target="#editPitchingOutingModal"
                            data-outing-id="${o.id}"
                            data-date="${o.date}"
                            data-pitcher="${escapeHTML(o.player_name)}"
                            data-opponent="${escapeHTML(o.opponent)}"
                            data-pitches="${o.pitches}"
                            data-innings="${o.innings}"
                            data-outing-type="${o.outing_type}"
                            data-pitcher-type="${o.pitcher_type}">
                            <i class="bi bi-pencil"></i>
                        </button>
                        ${deleteButtonHtml}
                    </div>
                </li>`;
            }).join('') || '<li class="list-group-item text-muted">No outings recorded.</li>';
        }
    }

    function renderSigns() {
        const container = document.getElementById('signs-list-container');
        if (!container) return;
        const signs = AppState.full_data.signs || [];
        container.innerHTML = signs.length > 0 ? signs.map((sign) => {
            const deleteButtonHtml = `<button type="button" class="btn btn-sm btn-danger ms-2" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_sign/${sign.id}" data-delete-name="the '${escapeHTML(sign.name)}' sign">Delete</button>`;
            const editButtonHtml = `<button class="btn btn-sm btn-info" data-bs-toggle="modal" data-bs-target="#editSignModal" data-sign-id="${sign.id}">Edit</button>`;
            return `<li class="list-group-item d-flex justify-content-between align-items-center">
                        <div><strong>${escapeHTML(sign.name)}:</strong> ${escapeHTML(sign.indicator)}</div>
                        <div>${editButtonHtml}${deleteButtonHtml}</div>
                    </li>`;
        }).join('') : `<li class="list-group-item text-center text-muted">No signs added.</li>`;
    }

    function renderScoutingList() {
        const scoutingData = AppState.full_data.scouting_list || {};
        
        const renderList = (key, containerId) => {
            const container = document.getElementById(containerId);
            if (!container) return;

            const players = scoutingData[key] || [];
            let playerHtml = players.length > 0 ? players.map(p => {
                let moveOptions = '';
                if (key === 'targets') {
                    moveOptions = `<li><form action="/move_scouted_player/targets/committed/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item">To Committed</button></form></li><li><form action="/move_scouted_player/targets/not_interested/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item">To Not Interested</button></form></li>`;
                } else if (key === 'committed') {
                    moveOptions = `<li><form action="/move_scouted_player_to_roster/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item fw-bold">To Roster</button></form></li><li><hr class="dropdown-divider"></li><li><form action="/move_scouted_player/committed/not_interested/${p.id}" method="POST" class="d-inline"><button type="submit" class="dropdown-item">To Not Interested</button></form></li>`;
                }
                const positions = [p.position1, p.position2].filter(Boolean).join(' / ') || 'N/A';
                const deleteButtonHtml = `<button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_scouted_player/${key}/${p.id}" data-delete-name="${escapeHTML(p.name)}"><i class="bi bi-trash"></i></button>`;
                return `<li class="list-group-item d-flex justify-content-between align-items-center"><div><div class="fw-bold">${escapeHTML(p.name)}</div><small class="text-muted">Pos: ${positions} | T/B: ${p.throws || 'N'}/${p.bats || 'N'}</small></div><div class="btn-group">${deleteButtonHtml}${moveOptions ? `<button type="button" class="btn btn-sm btn-outline-secondary dropdown-toggle dropdown-toggle-split" data-bs-toggle="dropdown"></button><ul class="dropdown-menu dropdown-menu-end">${moveOptions}</ul>` : ''}</div></li>`;
            }).join('') : `<li class="list-group-item text-center text-muted">No players in this list.</li>`;
            container.innerHTML = playerHtml;
        };

        renderList('targets', 'scouting-list-targets');
        renderList('committed', 'scouting-list-committed');
        renderList('not_interested', 'scouting-list-not_interested');
    }

    function renderGames() {
        const container = document.getElementById('games-list-container');
        if (!container) return;
        const games = (AppState.full_data.games || []).sort((a,b) => b.date.localeCompare(a.date));
        if (games.length === 0) { container.innerHTML = `<li class="list-group-item text-center text-muted">No games scheduled.</li>`; return; }
        container.innerHTML = games.map(game => {
            const lineup = AppState.full_data.lineups.find(l => l.associated_game_id === game.id);
            const rotation = AppState.full_data.rotations.find(r => r.associated_game_id === game.id);
            const lineupHTML = lineup && lineup.lineup_positions && lineup.lineup_positions.length > 0 ? `<span class="text-success"><i class="bi bi-check-circle-fill"></i> Set</span>` : `<span class="text-muted"><i class="bi bi-x-circle"></i> Not Set</span>`;
            const rotationHTML = rotation ? `<span class="text-success"><i class="bi bi-check-circle-fill"></i> Set</span>` : `<span class="text-muted"><i class="bi bi-x-circle"></i> Not Set</span>`;
            const deleteButtonHtml = `<button type="button" class="btn btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_game/${game.id}" data-delete-name="the game against ${escapeHTML(game.opponent)}"><i class="bi bi-trash"></i></button>`;
            return `<li class="list-group-item"><div class="d-flex justify-content-between align-items-center flex-wrap"><div class="me-auto"><h5 class="mb-1">vs ${escapeHTML(game.opponent)}</h5><p class="mb-1"><i class="bi bi-calendar-event"></i> ${formatDateTime(game.date)} <span class="text-muted mx-2">|</span> <i class="bi bi-geo-alt"></i> ${escapeHTML(game.location || 'TBD')}</p></div><div class="d-flex align-items-center mt-2 mt-md-0"><div class="text-end me-3"><div class="mb-1"><small>Lineup:</small> ${lineupHTML}</div><div><small>Rotation:</small> ${rotationHTML}</div></div><div class="btn-group-vertical btn-group-sm"><a href="/game/${game.id}" class="btn btn-primary"><i class="bi bi-tools"></i> Manage</a>${deleteButtonHtml}</div></div></div></li>`;
        }).join('');
    }
    
    function renderPracticePlans() {
        const container = document.getElementById('practicePlanAccordion');
        if (!container) return;
        const plans = (AppState.full_data.practice_plans || []).sort((a, b) => b.date.localeCompare(a.date));
        const roster = AppState.full_data.roster || [];

        if (plans.length === 0) {
            container.innerHTML = `<div class="text-center p-4 border rounded"><p class="mb-0">No practice plans saved.</p></div>`;
            return;
        }

        container.innerHTML = plans.map(plan => {
            const absentPlayerIds = new Set(plan.absent_player_ids || []);
            const attendanceHtml = roster.map(player => `<div class="form-check form-check-inline"><input class="form-check-input" type="checkbox" name="absent_players" value="${player.id}" id="attendance-${plan.id}-${player.id}" ${absentPlayerIds.has(player.id) ? 'checked' : ''}><label class="form-check-label" for="attendance-${plan.id}-${player.id}">${escapeHTML(player.name)}</label></div>`).join('');
            const tasksHtml = (plan.tasks || []).map(task => `<li class="list-group-item d-flex justify-content-between align-items-center task-item ${task.status === 'complete' ? 'complete' : ''}" data-task-id="${task.id}" data-plan-id="${plan.id}"><div class="form-check"><input class="form-check-input task-checkbox" type="checkbox" ${task.status === 'complete' ? 'checked' : ''} id="task-${task.id}"><label class="form-check-label" for="task-${task.id}">${escapeHTML(task.text)}<div class="text-muted small">By ${escapeHTML(task.author)}</div></label></div><button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_task/${plan.id}/${task.id}" data-delete-name="this task"><i class="bi bi-trash"></i></button></li>`).join('') || '<li class="list-group-item text-muted text-center">No tasks.</li>';
            return `<div class="accordion-item"><h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#plan-${plan.id}"><strong>${formatDateTime(plan.date)}</strong> - ${escapeHTML(plan.general_notes || 'No general notes')}</button></h2><div id="plan-${plan.id}" class="accordion-collapse collapse" data-bs-parent="#practicePlanAccordion"><div class="accordion-body"><form action="/edit_practice_plan/${plan.id}" method="POST" class="practice-plan-details-form"><div class="row g-3"><div class="col-md-4"><label class="form-label">Date</label><input type="date" name="plan_date" class="form-control" value="${plan.date.split('T')[0]}" required></div><div class="col-md-8"><label class="form-label">General Notes</label><input type="text" name="general_notes" class="form-control" value="${escapeHTML(plan.general_notes || '')}"></div><div class="col-12"><label class="form-label">Emphasis</label><textarea name="emphasis" class="form-control" rows="2">${escapeHTML(plan.emphasis || '')}</textarea></div><div class="col-md-6"><label class="form-label">Warm-up / Throwing</label><textarea name="warm_up" class="form-control" rows="3">${escapeHTML(plan.warm_up || '')}</textarea></div><div class="col-md-6"><label class="form-label">Infield / Outfield</label><textarea name="infield_outfield" class="form-control" rows="3">${escapeHTML(plan.infield_outfield || '')}</textarea></div><div class="col-md-6"><label class="form-label">Hitting</label><textarea name="hitting" class="form-control" rows="3">${escapeHTML(plan.hitting || '')}</textarea></div><div class="col-md-6"><label class="form-label">Pitching / Catching</label><textarea name="pitching_catching" class="form-control" rows="3">${escapeHTML(plan.pitching_catching || '')}</textarea></div><div class="col-12 d-flex justify-content-end gap-2"><button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_practice_plan/${plan.id}" data-delete-name="this practice plan">Delete Plan</button><button type="submit" class="btn btn-sm btn-primary">Save Plan Details</button></div></div></form><hr><div class="row mt-4"><div class="col-lg-6"><h5>Attendance</h5><p class="text-muted small">Check the box for any player who is absent.</p><form action="/update_practice_attendance/${plan.id}" method="POST"><div class="mb-3">${attendanceHtml}</div><button type="submit" class="btn btn-sm btn-primary">Save Attendance</button></form></div><div class="col-lg-6"><h5>Tasks / To-Do</h5><form action="/add_task_to_plan/${plan.id}" method="POST" class="mb-3 add-task-form"><div class="input-group"><input type="text" name="task_text" class="form-control" placeholder="Add task..." required><button type="submit" class="btn btn-primary">Add</button></div></form><ul class="list-group task-list">${tasksHtml}</ul></div></div></div></div></div>`;
        }).join('');
        attachTaskListeners();
    }
    
    function renderCollaborationNotes() {
        const teamNotesContainer = document.getElementById('team-notes-container');
        const playerNotesContainer = document.getElementById('player-notes-container');
        const collabPlayerSelect = document.getElementById('collab-player-select');

        if (!teamNotesContainer || !playerNotesContainer || !collabPlayerSelect) return;

        const notesData = AppState.full_data.collaboration_notes || { team_notes: [], player_notes: [] };
        const roster = AppState.full_data.roster || [];

        // Populate player dropdown
        collabPlayerSelect.innerHTML = '<option value="">Select Player...</option>' +
            roster.map(p => `<option value="${escapeHTML(p.name)}">${escapeHTML(p.name)}</option>`).join('');

        const renderNotesList = (notes, noteType) => {
            if (!notes || notes.length === 0) {
                return '<div class="text-center p-3 text-muted border rounded">No notes yet.</div>';
            }
            return notes.sort((a, b) => b.timestamp.localeCompare(a.timestamp)).map(note => {
                const canUserEdit = canEdit(note.author);
                const editButton = canUserEdit ? `<button class="btn btn-sm btn-link text-secondary py-0" data-bs-toggle="modal" data-bs-target="#editNoteModal" data-note-id="${note.id}" data-note-type="${noteType}" data-note-text="${escapeHTML(note.text)}">Edit</button>` : '';
                const deleteButton = canUserEdit ? `<button class="btn btn-sm btn-link text-danger py-0" data-bs-toggle="modal" data-bs-target="#confirmDeleteModal" data-delete-url="/delete_note/${noteType}/${note.id}" data-delete-name="this note">Delete</button>` : '';
                const playerTitle = noteType === 'player_notes' && note.player_name ? `<strong>${escapeHTML(note.player_name)}:</strong> ` : '';
                
                return `<div class="card mb-2">
                            <div class="card-body p-2">
                                <p class="card-text mb-1">${playerTitle}${escapeHTML(note.text)}</p>
                                <small class="text-muted d-block">By ${escapeHTML(note.author)} on ${formatDateTime(note.timestamp)}</small>
                                ${canUserEdit ? `<div class="mt-1">${editButton}${deleteButton}</div>` : ''}
                            </div>
                        </div>`;
            }).join('');
        };

        teamNotesContainer.innerHTML = renderNotesList(notesData.team_notes, 'team_notes');
        playerNotesContainer.innerHTML = renderNotesList(notesData.player_notes, 'player_notes');
    }

    function renderStats() {
        const container = document.getElementById('stats-content-container');
        if (!container) return;

        const {
            attendance_stats = {},
            roster = [],
            cumulative_pitching_data = {},
            cumulative_position_data = {}
        } = AppState.full_data;

        const attendanceTable = `
            <div class="col-12 mb-4">
                <div class="card">
                    <div class="card-header"><h5 class="mb-0">Attendance Statistics</h5></div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-striped table-hover">
                                <thead><tr><th>Player</th><th>Games Missed</th><th>Practices Missed</th></tr></thead>
                                <tbody>
                                    ${roster.map(player => `
                                        <tr>
                                            <td><strong>${escapeHTML(player.name)}</strong></td>
                                            <td>${attendance_stats[player.id] ? attendance_stats[player.id].games_missed : 0}</td>
                                            <td>${attendance_stats[player.id] ? attendance_stats[player.id].practices_missed : 0}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>`;

        const pitchingTable = `
            <div class="col-12 mb-4">
                <div class="card">
                    <div class="card-header"><h5 class="mb-0">Cumulative Pitching Statistics</h5></div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-striped table-hover">
                                <thead><tr><th>Pitcher</th><th>Total Innings Pitched</th><th>Total Pitches Thrown</th><th>Appearances</th></tr></thead>
                                <tbody>
        ${Object.keys(cumulative_pitching_data).sort().map(playerName => {
            const stats = cumulative_pitching_data[playerName] || { total_innings_pitched: 0, total_pitches_thrown: 0, appearances: 0 };
                                        return `<tr>
                <td><strong>${escapeHTML(playerName)}</strong></td>
                                            <td>${stats.total_innings_pitched}</td>
                                            <td>${stats.total_pitches_thrown}</td>
                                            <td>${stats.appearances}</td>
                                        </tr>`;
                                    }).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>`;
        
        const allPositions = [...new Set(Object.values(cumulative_position_data).flatMap(Object.keys))].sort();
        const positionTable = `
            <div class="col-12 mb-4">
                <div class="card">
                    <div class="card-header"><h5 class="mb-0">Cumulative Games Played by Position</h5></div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-striped table-hover">
                                <thead>
                                    <tr>
                                        <th>Player</th>
                                        ${allPositions.map(pos => `<th>${escapeHTML(pos)}</th>`).join('')}
                                    </tr>
                                </thead>
                                <tbody>
                                    ${roster.map(player => `
                                        <tr>
                                            <td><strong>${escapeHTML(player.name)}</strong></td>
                                            ${allPositions.map(pos => `<td>${(cumulative_position_data[player.name] && cumulative_position_data[player.name][pos]) || 0}</td>`).join('')}
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                        <p class="text-muted mt-3">* "Games Played by Position" counts the number of games a player appeared in a lineup at that specific position. It does not reflect actual innings played at that position within a game.</p>
                    </div>
                </div>
            </div>`;

        container.innerHTML = `<div class="row">${attendanceTable}${pitchingTable}${positionTable}</div>`;
    }

    function renderOverview() {
        const container = document.getElementById('overview-content-container');
        if (!container) return;

        // Since the data is already fetched in init(), we can access it from AppState
        const { next_game, pitchers_on_rest, recent_notes } = AppState.full_data.overview || {};

        if (!next_game && !pitchers_on_rest && !recent_notes) {
            container.innerHTML = `<div class="p-3 text-center text-muted">Loading overview data...</div>`;
            return;
        }

        let nextGameHtml = '<div class="card mb-4"><div class="card-header"><h5 class="mb-0">Next Game</h5></div><div class="card-body">';
        if (next_game) {
            nextGameHtml += `<h5 class="card-title">vs ${escapeHTML(next_game.opponent)}</h5>
                             <p class="card-text">${formatDateTime(next_game.date)} at ${escapeHTML(next_game.location || 'TBD')}</p>
                             <a href="/game/${next_game.id}" class="btn btn-primary">Manage Game</a>`;
        } else {
            nextGameHtml += '<p class="text-muted">No upcoming games scheduled.</p>';
        }
        nextGameHtml += '</div></div>';

        let pitchersOnRestHtml = '<div class="card mb-4"><div class="card-header"><h5 class="mb-0">Pitchers on Rest</h5></div><ul class="list-group list-group-flush">';
        if (pitchers_on_rest && Object.keys(pitchers_on_rest).length > 0) {
            for (const [name, data] of Object.entries(pitchers_on_rest)) {
                pitchersOnRestHtml += `<li class="list-group-item">${escapeHTML(name)} - Available on ${data.next_available}</li>`;
            }
        } else {
            pitchersOnRestHtml += '<li class="list-group-item text-muted">All pitchers are available.</li>';
        }
        pitchersOnRestHtml += '</ul></div>';

        let recentNotesHtml = '<div class="card"><div class="card-header"><h5 class="mb-0">Recent Coaches Log</h5></div><div class="card-body">';
        if (recent_notes && recent_notes.length > 0) {
            recentNotesHtml += recent_notes.map(note => `
                <div class="mb-2">
                    <p class="mb-0">${escapeHTML(note.text)}</p>
                    <small class="text-muted">-- ${escapeHTML(note.author)} on ${formatDateTime(note.timestamp)}</small>
                </div>
            `).join('<hr>');
        } else {
            recentNotesHtml += '<p class="text-muted">No recent notes.</p>';
        }
        recentNotesHtml += '</div></div>';

        container.innerHTML = `<div class="row"><div class="col-md-6">${nextGameHtml}${pitchersOnRestHtml}</div><div class="col-md-6">${recentNotesHtml}</div></div>`;
    }

    function renderAll() {
        renderOverview();
        renderRoster();
        renderPlayerDevelopmentList();
        renderPlayerDevelopmentDetails();
        renderLineups();
        renderRotations();
        renderPitchingLog();
        renderSigns();
        renderCollaborationNotes();
        renderScoutingList();
        renderGames();
        renderPracticePlans();
        renderStats();
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
        const cardBody = btn.closest('.card-body');
        const feedbackDiv = cardBody.querySelector('.save-feedback');
        const playerId = btn.dataset.playerId;
        const originalButtonText = btn.innerHTML;

        const formData = new FormData();
        cardBody.querySelectorAll('input, select, textarea').forEach(input => formData.append(input.name, input.value));
        
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Saving...`;
        feedbackDiv.style.display = 'none';

        try {
            const response = await fetch(`/update_player_inline/${playerId}`, { method: 'POST', body: formData });
            const result = await response.json();
            if (!response.ok) throw new Error(result.message);
            
            btn.innerHTML = `Saved!`;
            setTimeout(() => {
                btn.innerHTML = originalButtonText;
                btn.disabled = false;
            }, 2000);

        } catch (err) {
            feedbackDiv.textContent = `Error: ${err.message}`;
            feedbackDiv.className = 'save-feedback alert alert-danger';
            feedbackDiv.style.display = 'block';
            btn.innerHTML = originalButtonText;
            btn.disabled = false;
        }
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
        } catch (error) { 
            console.error('Error updating task:', error.message);
            event.target.checked = !event.target.checked;
        }
    }
    
    // --- INITIALIZATION ---
    async function fetchData() {
        const endpoints = {
            session_data: '/api/session_data',
            roster: '/api/roster',
            lineups: '/api/lineups',
            pitching_data: '/api/pitching_data',
            scouting_list: '/api/scouting_list',
            rotations: '/api/rotations',
            games: '/api/games',
            collaboration_notes: '/api/collaboration_notes',
            practice_plans: '/api/practice_plans',
            player_development: '/api/player_development',
            signs: '/api/signs',
            stats: '/api/stats',
            overview: '/api/overview_data'
        };

        const requests = Object.entries(endpoints).map(([key, url]) =>
            fetch(url).then(res => {
                if (!res.ok) throw new Error(`Failed to fetch ${key}`);
                return res.json();
            })
        );

        const results = await Promise.all(requests);
        const dataKeys = Object.keys(endpoints);

        const sessionData = results[dataKeys.indexOf('session_data')];
        const statsData = results[dataKeys.indexOf('stats')];
        const pitchingData = results[dataKeys.indexOf('pitching_data')];

        Object.assign(AppState, {
            session: sessionData.session,
            player_order: sessionData.player_order,
            pitch_count_summary: pitchingData.pitch_count_summary,
            full_data: {
                roster: results[dataKeys.indexOf('roster')],
                lineups: results[dataKeys.indexOf('lineups')],
                pitching: pitchingData.pitching,
                scouting_list: results[dataKeys.indexOf('scouting_list')],
                rotations: results[dataKeys.indexOf('rotations')],
                games: results[dataKeys.indexOf('games')],
                collaboration_notes: results[dataKeys.indexOf('collaboration_notes')],
                practice_plans: results[dataKeys.indexOf('practice_plans')],
                player_development: results[dataKeys.indexOf('player_development')],
                signs: results[dataKeys.indexOf('signs')],
                cumulative_pitching_data: statsData.cumulative_pitching_data,
                cumulative_position_data: statsData.cumulative_position_data,
                attendance_stats: statsData.attendance_stats,
                overview: results[dataKeys.indexOf('overview')]
            }
        });
    }

    async function init() {
        const mainContent = document.getElementById('mainTabContent');
        
        try {
            await fetchData();
        } catch (error) {
            console.error("Init Error:", error);
            if(mainContent) mainContent.innerHTML = `<div class="alert alert-danger">Could not load app data. Please refresh the page. Error: ${error.message}</div>`;
            return;
        }
        
        lineupEditorModal = new bootstrap.Modal(document.getElementById('lineupEditorModal'));
        confirmDeleteModal = new bootstrap.Modal(document.getElementById('confirmDeleteModal'));
        setupEventListeners();
        renderAll();
        initializeSortables();
        handleTabLogic();
        
        const socket = io();

        // --- Data Fetch Helpers for Sockets ---
        const fetchPitchingData = async () => {
            const data = await fetch('/api/pitching_data').then(res => res.json());
            AppState.full_data.pitching = data.pitching;
            AppState.pitch_count_summary = data.pitch_count_summary;
        };
        const fetchScoutingData = async () => {
            AppState.full_data.scouting_list = await fetch('/api/scouting_list').then(res => res.json());
        };
        const fetchNotesData = async () => {
            AppState.full_data.collaboration_notes = await fetch('/api/collaboration_notes').then(res => res.json());
        };
        const fetchPlansData = async () => {
            AppState.full_data.practice_plans = await fetch('/api/practice_plans').then(res => res.json());
        };
        const fetchSignsData = async () => {
            AppState.full_data.signs = await fetch('/api/signs').then(res => res.json());
        };
        const fetchStatsData = async () => {
            const statsData = await fetch('/api/stats').then(res => res.json());
            AppState.full_data.cumulative_pitching_data = statsData.cumulative_pitching_data;
            AppState.full_data.cumulative_position_data = statsData.cumulative_position_data;
            AppState.full_data.attendance_stats = statsData.attendance_stats;
        };

        // --- Roster Sockets ---
        socket.on('roster_add', (data) => {
            console.log('roster_add received', data);
            AppState.full_data.roster.push(data.player);
            if (!AppState.player_order.includes(data.player.name)) {
                AppState.player_order.push(data.player.name);
            }
            renderRoster();
            renderPlayerDevelopmentList();
        });
        socket.on('roster_update', (data) => {
            console.log('roster_update received', data);
            const index = AppState.full_data.roster.findIndex(p => p.id === data.player.id);
            if (index > -1) {
                AppState.full_data.roster[index] = data.player;
                renderRoster();
                renderPlayerDevelopmentList();
            }
        });
        socket.on('roster_delete', (data) => {
            console.log('roster_delete received', data);
            const playerToDelete = AppState.full_data.roster.find(p => p.id === data.player_id);
            if(playerToDelete) {
                AppState.player_order = AppState.player_order.filter(name => name !== playerToDelete.name);
            }
            AppState.full_data.roster = AppState.full_data.roster.filter(p => p.id !== data.player_id);
            renderRoster();
            renderPlayerDevelopmentList();
        });
        socket.on('player_order_update', (data) => {
            console.log('player_order_update received', data);
            AppState.player_order = data.order;
            renderRoster();
            renderPlayerDevelopmentList();
        });

        // --- Game, Lineup, Rotation Sockets ---
        socket.on('game_add', (data) => {
            console.log('game_add received', data);
            AppState.full_data.games.push(data.game);
            renderGames();
        });
        socket.on('game_update', (data) => {
            console.log('game_update received', data);
            const index = AppState.full_data.games.findIndex(g => g.id === data.game.id);
            if (index > -1) AppState.full_data.games[index] = data.game;
            renderGames();
        });
        socket.on('game_delete', (data) => {
            console.log('game_delete received', data);
            AppState.full_data.games = AppState.full_data.games.filter(g => g.id !== data.game_id);
            renderGames();
        });
        socket.on('lineup_add', (data) => {
            console.log('lineup_add received', data);
            AppState.full_data.lineups.push(data.lineup);
            renderLineups();
            renderGames();
        });
        socket.on('lineup_update', (data) => {
            console.log('lineup_update received', data);
            const index = AppState.full_data.lineups.findIndex(l => l.id === data.lineup.id);
            if (index > -1) AppState.full_data.lineups[index] = data.lineup;
            else AppState.full_data.lineups.push(data.lineup);
            renderLineups();
            renderGames();
        });
        socket.on('lineup_delete', (data) => {
            console.log('lineup_delete received', data);
            AppState.full_data.lineups = AppState.full_data.lineups.filter(l => l.id !== data.lineup_id);
            renderLineups();
            renderGames();
        });
        socket.on('rotation_save', (data) => {
            console.log('rotation_save received', data);
            const index = AppState.full_data.rotations.findIndex(r => r.id === data.rotation.id);
            if (index > -1) AppState.full_data.rotations[index] = data.rotation;
            else AppState.full_data.rotations.push(data.rotation);
            renderRotations();
            renderGames();
        });
        socket.on('rotation_delete', (data) => {
            console.log('rotation_delete received', data);
            AppState.full_data.rotations = AppState.full_data.rotations.filter(r => r.id !== data.rotation_id);
            renderRotations();
            renderGames();
        });

        // --- Player Development Sockets ---
        socket.on('dev_focus_add', (data) => {
            console.log('dev_focus_add received', data);
            const { player_name, focus } = data;
            if (!AppState.full_data.player_development[player_name]) {
                AppState.full_data.player_development[player_name] = [];
            }
            AppState.full_data.player_development[player_name].push(focus);
            renderPlayerDevelopmentList();
            if (AppState.active_player_dev_name === player_name) {
                renderPlayerDevelopmentDetails();
            }
        });
        socket.on('dev_focus_update', (data) => {
            console.log('dev_focus_update received', data);
            const { player_name, focus } = data;
            const playerDevList = AppState.full_data.player_development[player_name];
            if (playerDevList) {
                const index = playerDevList.findIndex(f => f.id === focus.id);
                if (index > -1) playerDevList[index] = focus;
                renderPlayerDevelopmentList();
                if (AppState.active_player_dev_name === player_name) renderPlayerDevelopmentDetails();
            }
        });
        socket.on('dev_focus_delete', (data) => {
            console.log('dev_focus_delete received', data);
            const { player_name, focus_id } = data;
            const playerDevList = AppState.full_data.player_development[player_name];
            if (playerDevList) {
                AppState.full_data.player_development[player_name] = playerDevList.filter(f => f.id !== focus_id);
                renderPlayerDevelopmentList();
                if (AppState.active_player_dev_name === player_name) renderPlayerDevelopmentDetails();
            }
        });

        // --- Other Data Sockets ---
        socket.on('pitching_update', async () => {
            console.log('pitching_update received');
            await fetchPitchingData();
            renderPitchingLog();
            renderStats();
        });
        socket.on('scouting_update', async () => {
            console.log('scouting_update received');
            await fetchScoutingData();
            renderScoutingList();
        });
        socket.on('notes_update', async () => {
            console.log('notes_update received');
            await fetchNotesData();
            renderCollaborationNotes();
        });
        socket.on('plans_update', async () => {
            console.log('plans_update received');
            await fetchPlansData();
            renderPracticePlans();
        });
        socket.on('signs_update', async () => {
            console.log('signs_update received');
            await fetchSignsData();
            renderSigns();
        });
        socket.on('stats_update', async () => {
            console.log('stats_update received');
            await fetchStatsData();
            renderStats();
        });
    }

    function initializeSortables() {
        Object.values(sortableInstances).forEach(s => s.destroy());
        sortableInstances = {};
        const savePlayerOrder = (evt) => {
            const newOrder = Array.from(evt.from.children).map(item => item.dataset.playerName);
            AppState.player_order = newOrder;
            fetch('/save_player_order', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ player_order: newOrder }) });
            AppState.dev_player_sort.key = 'custom';
            renderPlayerDevelopmentList();
        };
        ['roster-cards-container', 'dev-player-list'].forEach(id => {
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

    async function saveLineup() {
        const btn = document.getElementById('saveLineupBtn');
        const modal = btn.closest('.modal');
        const lineupId = modal.querySelector('#lineupId').value;
        const title = modal.querySelector('#lineupTitle').value;
        const lineup_positions = Array.from(modal.querySelectorAll('#lineup-order .list-group-item')).map(item => item.dataset.playerName);

        const url = lineupId ? `/edit_lineup/${lineupId}` : '/add_lineup';
        const payload = {
            title: title,
            lineup_data: lineup_positions,
            associated_game_id: null // Explicitly null for unassigned lineups
        };

        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Saving...`;

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.message);

        // MODIFICATION: The local state update is removed.
        // The websocket event will now solely handle updating the UI to prevent duplication.
            lineupEditorModal.hide();

        } catch (error) {
            alert('Error saving lineup: ' + error.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = 'Save';
        }
    }

    function setupEventListeners() {
        document.getElementById('saveLineupBtn')?.addEventListener('click', saveLineup);
        document.getElementById('rosterSearch').addEventListener('input', renderRoster);
        
        const addScoutedPlayerForm = document.getElementById('addScoutedPlayerForm');
        if (addScoutedPlayerForm) {
            addScoutedPlayerForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(addScoutedPlayerForm);
                const data = Object.fromEntries(formData.entries());
                const feedbackDiv = document.getElementById('addScoutedPlayerFeedback');
                try {
                    const response = await fetch('/add_scouted_player', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                    const result = await response.json();
                    if (response.ok) {
                        feedbackDiv.className = 'alert alert-success';
                        addScoutedPlayerForm.reset();
                    } else {
                        feedbackDiv.className = 'alert alert-danger';
                    }
                    feedbackDiv.textContent = result.message;
                } catch (error) {
                    feedbackDiv.className = 'alert alert-danger';
                    feedbackDiv.textContent = 'A network error occurred.';
                }
            });
        }

        document.getElementById('devPlayerSearch').addEventListener('input', renderPlayerDevelopmentList);
        document.getElementById('dev-sort-az').addEventListener('click', () => {
            AppState.dev_player_sort = { key: 'name', order: 'asc' };
            renderPlayerDevelopmentList();
        });
        document.getElementById('dev-sort-za').addEventListener('click', () => {
            AppState.dev_player_sort = { key: 'name', order: 'desc' };
            renderPlayerDevelopmentList();
        });
         document.getElementById('dev-sort-custom').addEventListener('click', () => {
            AppState.dev_player_sort = { key: 'custom', order: 'asc' };
            renderPlayerDevelopmentList();
        });

        document.getElementById('confirmDeleteModal')?.addEventListener('show.bs.modal', (e) => {
            const deleteButton = document.getElementById('confirmDeleteButton');
            const modalBody = e.target.querySelector('.modal-body');
            const url = e.relatedTarget.dataset.deleteUrl;
            const name = e.relatedTarget.dataset.deleteName;

            if (url) {
                deleteButton.href = url;
                modalBody.innerHTML = `Are you sure you want to delete <strong>${name || 'this item'}</strong>? This action cannot be undone.`;
            } else {
                console.error("Delete modal opened without a data-delete-url attribute on the trigger.");
                e.preventDefault();
            }
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
            const btn = e.relatedTarget;
            if (!btn) return;

            const form = e.target.querySelector('form');
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
                    form.querySelector('#focusProgressNotes').value = focusItem.progress_notes || '';
                }
            } else {
                e.target.querySelector('.modal-title').textContent = 'Add Focus';
                form.action = `/add_focus/${encodeURIComponent(btn.dataset.playerName)}`;
                if (btn.dataset.skill) {
                    form.querySelector('#focusSkill').value = btn.dataset.skill;
                }
            }
        });
        
        document.getElementById('editSignModal')?.addEventListener('show.bs.modal', (e) => {
            const sign = AppState.full_data.signs.find(s => s.id == e.relatedTarget.dataset.signId);
            const form = e.target.querySelector('form');
            form.action = `/update_sign/${sign.id}`;
            form.querySelector('#editSignName').value = sign.name;
            form.querySelector('#editSignIndicator').value = sign.indicator;
        });

        document.getElementById('editPitchingOutingModal')?.addEventListener('show.bs.modal', (e) => {
            const btn = e.relatedTarget;
            const modal = e.target;
            const form = modal.querySelector('form');
            
            const outingId = btn.dataset.outingId;
            form.action = `/edit_pitching/${outingId}`;

            const pitcherSelect = modal.querySelector('#edit_pitcher');
            pitcherSelect.innerHTML = AppState.full_data.roster
                .map(p => `<option value="${p.id}">${escapeHTML(p.name)}</option>`)
                .join('');
            
            const pitcherIdToSelect = AppState.full_data.roster.find(p => p.name === btn.dataset.pitcher)?.id;
            if (pitcherIdToSelect) {
                pitcherSelect.value = pitcherIdToSelect;
            }

            modal.querySelector('#edit_pitch_date').value = btn.dataset.date;
            modal.querySelector('#edit_opponent').value = btn.dataset.opponent;
            modal.querySelector('#edit_pitches').value = btn.dataset.pitches;
            modal.querySelector('#edit_innings').value = btn.dataset.innings;
            modal.querySelector('#edit_outing_type').value = btn.dataset.outingType;
            modal.querySelector('#edit_pitcher_type').value = btn.dataset.pitcherType;
        });
    }
    
    function openLineupEditor(lineup = null) {
        const modal = document.getElementById('lineupEditorModal');
        const currentLineup = lineup || { id: null, title: 'New Unassigned Lineup', lineup_positions: [] };

        modal.querySelector('#lineupId').value = currentLineup.id;
        modal.querySelector('#lineupTitle').value = currentLineup.title;

        initializeLineupEditor({
            roster: AppState.full_data.roster,
            lineup: currentLineup,
            benchEl: modal.querySelector('#lineup-bench'),
            orderEl: modal.querySelector('#lineup-order')
        });
    }

    function handleTabLogic() {
        if (!document.getElementById('mainTabContent')) return;

        const activateTab = (tabEl) => {
            if (!tabEl) return;
            // Manually deactivate all tabs first to prevent sticking
            document.querySelectorAll('#mainTabContent .tab-pane').forEach(pane => {
                pane.classList.remove('active', 'show');
            });
            document.querySelectorAll('.nav-tabs .nav-link').forEach(link => {
                link.classList.remove('active');
            });

            const targetPane = document.querySelector(tabEl.getAttribute('href'));
            if (targetPane) {
                tabEl.classList.add('active');
                targetPane.classList.add('active', 'show');
                if (history.pushState) {
                    history.pushState(null, null, tabEl.getAttribute('href'));
                } else {
                    window.location.hash = tabEl.getAttribute('href');
                }
            }
        };

        // Handle clicks on all tab links
        document.querySelectorAll('a[data-bs-toggle="tab"]').forEach(tabEl => {
            tabEl.addEventListener('click', (event) => {
                event.preventDefault();
                activateTab(tabEl);
            });
        });
    
        // On initial page load, check the URL hash and activate the correct tab.
        let hash = window.location.hash || '#roster';
        let tabToActivate = document.querySelector(`a[data-bs-toggle="tab"][href="${hash}"]`);
    
        // If the hash points to something inside a tab (like an accordion), find its parent tab.
        if (!tabToActivate) {
            const targetElement = document.getElementById(hash.substring(1));
            if (targetElement) {
                const parentTabPane = targetElement.closest('.tab-pane');
                if (parentTabPane) {
                    tabToActivate = document.querySelector(`a[data-bs-toggle="tab"][href="#${parentTabPane.id}"]`);
                }
            }
        }
        
        // If still no tab is found, default to the roster.
        if (!tabToActivate) {
            tabToActivate = document.querySelector('a[data-bs-toggle="tab"][href="#roster"]');
        }

        // Activate the initial tab
        if (tabToActivate) {
            // We need to make sure the content is visible on first load, so we'll activate it directly.
            // Using a small timeout allows the rest of the page to render first.
            setTimeout(() => activateTab(tabToActivate), 0);
        }
    }
    
    init(); // Start the app
});