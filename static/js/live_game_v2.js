(() => {
    'use strict';

    const gameMatch = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
    if (!gameMatch) return;

    const gameId = Number(gameMatch[1]);
    let liveState = null;
    let socket = null;
    let connected = false;
    let actionBusy = false;

    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));

    const byId = (id) => document.getElementById(id);

    function isLiveActionTarget(target) {
        return target?.closest?.([
            '#startLiveGameBtnAction', '#liveGameModeToggle', '#liveChangePitcherBtn',
            '#liveUndoBtn', '#liveEndGameBtn', '#confirmFinalCountsBtn'
        ].join(','));
    }

    function setSyncStatus(mode) {
        let badge = byId('live-sync-status-v2');
        if (!badge) {
            const overlay = byId('live-game-overlay');
            if (!overlay) return;
            badge = document.createElement('div');
            badge.id = 'live-sync-status-v2';
            badge.className = 'text-center mb-3';
            overlay.prepend(badge);
        }
        if (mode === 'synced') {
            badge.innerHTML = '<span class="badge rounded-pill text-bg-success px-3 py-2">● LIVE • SYNCED</span>';
        } else if (mode === 'reconnecting') {
            badge.innerHTML = '<span class="badge rounded-pill text-bg-warning px-3 py-2">⚠ RECONNECTING…</span>';
        } else {
            badge.innerHTML = '<span class="badge rounded-pill text-bg-danger px-3 py-2">⚠ NOT SYNCED</span>';
        }
    }

    function toast(message, kind = 'success') {
        let container = byId('live-toast-container-v2');
        if (!container) {
            container = document.createElement('div');
            container.id = 'live-toast-container-v2';
            container.className = 'toast-container position-fixed top-0 end-0 p-3';
            container.style.zIndex = '2000';
            document.body.appendChild(container);
        }
        const el = document.createElement('div');
        el.className = `toast align-items-center text-bg-${kind} border-0`;
        el.setAttribute('role', 'status');
        el.innerHTML = `<div class="d-flex"><div class="toast-body fw-semibold">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
        container.appendChild(el);
        const instance = bootstrap.Toast.getOrCreateInstance(el, { delay: 2800 });
        el.addEventListener('hidden.bs.toast', () => el.remove(), { once: true });
        instance.show();
    }

    async function api(path, options = {}) {
        const response = await fetch(`/api/live-game/${gameId}${path}`, {
            headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
            ...options,
        });
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok || data.status === 'error') {
            throw new Error(data.message || `Request failed (${response.status})`);
        }
        if (data.state) applyState(data.state);
        return data;
    }

    async function fetchState() {
        const response = await fetch(`/api/live-game/${gameId}/state`, { cache: 'no-store' });
        if (!response.ok) throw new Error(`Unable to load live game state (${response.status}).`);
        applyState(await response.json());
    }

    function roleRank(role) {
        const order = {
            'Starter': 1,
            'First Relief': 2,
            'Secondary Relief': 3,
            'Late / High Leverage': 4,
            'Emergency Only': 5,
            'Avoid Today': 6,
        };
        return order[role] || 50;
    }

    function profileFor(playerId) {
        return (liveState?.pitching_profiles || []).find(p => Number(p.player_id) === Number(playerId));
    }

    function planFor(playerId) {
        return (liveState?.pitching_plans || []).find(p => Number(p.player_id) === Number(playerId));
    }

    function summaryFor(player) {
        return liveState?.pitch_count_summary?.[player.name] || {};
    }

    function officialUnavailable(summary) {
        const status = String(summary?.status || '').toLowerCase();
        return status.includes('rest') || status.includes('unavailable') || status.includes('ineligible');
    }

    function todayText(summary) {
        const value = summary?.daily;
        return value === null || value === undefined ? 'Today: unknown' : `Today: ${value}`;
    }

    function currentAlignment() {
        return liveState?.current_alignment || {};
    }

    function renderDiamondAndBench() {
        if (!liveState?.game?.is_live) return;
        const alignment = currentAlignment();
        document.querySelectorAll('.position-dropzone .player-tag').forEach(tag => tag.remove());
        Object.entries(alignment).forEach(([pos, name]) => {
            if (!name) return;
            ['desktop', 'mobile'].forEach(mode => {
                const zone = byId(`pos-${mode}-${pos}`);
                if (zone) zone.insertAdjacentHTML('beforeend', `<div class="player-tag" data-player-name="${esc(name)}">${esc(name)}</div>`);
            });
        });
        const assigned = new Set(Object.values(alignment).filter(Boolean));
        const bench = (liveState.roster || []).filter(p => !assigned.has(p.name));
        const desktop = byId('bench-list-desktop');
        if (desktop) desktop.innerHTML = bench.map(p => `<div class="player-tag">${esc(p.name)}</div>`).join('') || '<span class="text-muted">No one on bench.</span>';
        const mobile = byId('bench-list-mobile');
        if (mobile) mobile.innerHTML = bench.map(p => `<span class="badge bg-secondary fw-normal p-2 border">${esc(p.name)}</span>`).join('') || '<span class="text-muted">No one on bench.</span>';
    }

    function renderUpNext() {
        const overlay = byId('live-game-overlay');
        if (!overlay) return;
        let card = byId('live-up-next-v2');
        if (!card) {
            card = document.createElement('div');
            card.id = 'live-up-next-v2';
            const pitcherCard = byId('live-current-pitcher')?.closest('.card');
            if (pitcherCard) pitcherCard.insertAdjacentElement('afterend', card);
            else overlay.appendChild(card);
        }
        const next = liveState?.planned_next_inning;
        const alignment = liveState?.planned_next_alignment || {};
        const rows = Object.entries(alignment).map(([pos, name]) => `<span class="badge text-bg-light border me-1 mb-1"><strong>${esc(pos)}</strong> ${esc(name || '—')}</span>`).join('');
        card.className = 'card border-0 shadow-sm mb-3';
        card.innerHTML = `<div class="card-body p-3"><div class="small text-uppercase text-muted fw-bold mb-2">Up Next — Inning ${esc(next)}</div>${rows || '<span class="text-muted small">No planned next inning. Current defense will carry forward.</span>'}</div>`;
    }

    function renderPitcherSummary() {
        const name = liveState?.current_pitcher || 'None';
        const nameEl = byId('live-current-pitcher');
        if (nameEl) nameEl.textContent = name;
        const statsEl = byId('live-pitcher-stats');
        if (!statsEl) return;
        const player = (liveState?.roster || []).find(p => p.name === name);
        if (!player) {
            statsEl.textContent = 'No pitcher assigned.';
            return;
        }
        const s = summaryFor(player);
        const plan = planFor(player.id);
        const target = s.coach_target ?? s.target ?? null;
        const parts = [
            s.status || 'Eligibility unknown',
            todayText(s),
            target !== null ? `Coach target: ${target}` : null,
            plan?.role ? `Role: ${plan.role}` : null,
        ].filter(Boolean);
        statsEl.textContent = parts.join(' • ');
    }

    function renderLifecycle() {
        if (!liveState) return;
        const isLive = Boolean(liveState.game?.is_live);
        const overlay = byId('live-game-overlay');
        const pregame = byId('pregame-checklist-container');
        const rotationContainer = byId('rotation-card-container');
        const lineupContainer = byId('lineup-card-container');
        const pitchingContainer = byId('pitching-log-container');
        const row = rotationContainer?.closest('.row');
        const toggle = byId('liveGameModeToggle');

        if (toggle) toggle.checked = isLive;
        if (pregame) pregame.classList.toggle('d-none', isLive);
        if (lineupContainer) lineupContainer.classList.toggle('d-none', isLive);
        if (pitchingContainer) pitchingContainer.classList.toggle('d-none', isLive);
        if (row) {
            row.classList.remove('d-none');
            row.style.display = '';
        }
        if (rotationContainer) {
            rotationContainer.classList.remove('d-none');
            rotationContainer.style.display = '';
        }
        if (overlay) overlay.classList.toggle('d-none', !isLive);

        document.querySelectorAll('#rotation-board .planner-controls, #rotation-card-container > .card > .card-header .planner-controls').forEach(el => {
            el.classList.toggle('d-none', isLive);
        });

        if (isLive) {
            const inning = byId('live-inning-display');
            if (inning) inning.textContent = liveState.current_inning || '1';
            renderPitcherSummary();
            renderUpNext();
            renderDiamondAndBench();
            setSyncStatus(connected ? 'synced' : 'reconnecting');
        }
        renderPitchingBoard();
    }

    function applyState(state) {
        liveState = state;
        renderLifecycle();
    }

    function modalShell(id, title) {
        let el = byId(id);
        if (!el) {
            el = document.createElement('div');
            el.id = id;
            el.className = 'modal fade';
            el.tabIndex = -1;
            el.innerHTML = `<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content"><div class="modal-header"><h5 class="modal-title">${esc(title)}</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"></div></div></div>`;
            document.body.appendChild(el);
        }
        el.querySelector('.modal-title').textContent = title;
        return el;
    }

    function showPitcherPicker() {
        if (!liveState) return;
        const modal = modalShell('live-pitcher-picker-v2', 'Change Pitcher');
        const body = modal.querySelector('.modal-body');
        const currentPitcher = liveState.current_pitcher;
        const players = [...(liveState.roster || [])]
            .filter(p => p.name !== currentPitcher)
            .sort((a, b) => {
                const sa = summaryFor(a), sb = summaryFor(b);
                const ua = officialUnavailable(sa), ub = officialUnavailable(sb);
                if (ua !== ub) return ua ? 1 : -1;
                return roleRank(planFor(a.id)?.role) - roleRank(planFor(b.id)?.role) || a.name.localeCompare(b.name);
            });
        body.innerHTML = `<div class="mb-3"><div class="small text-uppercase text-muted fw-bold mb-2">What do we need?</div><div class="d-flex flex-wrap gap-2" id="pitcher-need-v2">${['Show All','Need Strikes','Velocity','Change of Pace','Different Look','Miss Bats','Ground Ball','Hold Runners','Protect Lead'].map(x => `<button type="button" class="btn btn-sm btn-outline-secondary" data-need="${esc(x)}">${esc(x)}</button>`).join('')}</div></div><div id="pitcher-list-v2"></div>`;

        const renderList = (need = 'Show All') => {
            const list = byId('pitcher-list-v2');
            const normalizedNeed = need.toLowerCase();
            const ranked = [...players].sort((a, b) => {
                if (need === 'Show All') return 0;
                const ta = (profileFor(a.id)?.traits || []).join(' ').toLowerCase();
                const tb = (profileFor(b.id)?.traits || []).join(' ').toLowerCase();
                const aliases = normalizedNeed === 'need strikes' ? ['strike', 'command'] : [normalizedNeed.replace('need ', '')];
                const ma = aliases.some(term => ta.includes(term));
                const mb = aliases.some(term => tb.includes(term));
                return Number(mb) - Number(ma);
            });
            list.innerHTML = ranked.map(p => {
                const s = summaryFor(p), plan = planFor(p.id), profile = profileFor(p.id);
                const unavailable = officialUnavailable(s);
                const traits = (profile?.traits || []).slice(0, 4).join(' • ');
                return `<button type="button" class="list-group-item list-group-item-action mb-2 border rounded p-3 pitcher-choice-v2" data-player-id="${p.id}" ${unavailable ? 'disabled' : ''}><div class="d-flex justify-content-between"><strong>${esc(p.name)}</strong><span class="${unavailable ? 'text-danger' : 'text-success'}">${esc(s.status || 'Available')}</span></div><div class="small text-muted mt-1">${esc(todayText(s))}${s.coach_target != null ? ` • Coach target: ${esc(s.coach_target)}` : ''}${plan?.role ? ` • ${esc(plan.role)}` : ''}</div>${traits ? `<div class="small mt-1">${esc(traits)}</div>` : ''}${plan?.coach_note ? `<div class="small fst-italic mt-1">${esc(plan.coach_note)}</div>` : ''}</button>`;
            }).join('');
        };
        renderList();
        body.querySelector('#pitcher-need-v2').addEventListener('click', e => {
            const btn = e.target.closest('[data-need]');
            if (btn) renderList(btn.dataset.need);
        });
        body.querySelector('#pitcher-list-v2').addEventListener('click', e => {
            const btn = e.target.closest('.pitcher-choice-v2');
            if (btn && !btn.disabled) {
                bootstrap.Modal.getOrCreateInstance(modal).hide();
                showPitcherDestination(Number(btn.dataset.playerId));
            }
        });
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    function showPitcherDestination(newPitcherId) {
        const incoming = (liveState.roster || []).find(p => Number(p.id) === Number(newPitcherId));
        if (!incoming) return;
        const alignment = currentAlignment();
        const oldPitcher = alignment.P || 'current pitcher';
        const incomingPosition = Object.entries(alignment).find(([, name]) => name === incoming.name)?.[0] || null;
        const positions = ['BENCH','C','1B','2B','3B','SS','LF', ...(liveState.outfielder_count === 4 ? ['LCF','RCF'] : ['CF']), 'RF'];
        const modal = modalShell('live-pitcher-destination-v2', `${incoming.name} → P`);
        const body = modal.querySelector('.modal-body');
        body.innerHTML = `<p class="fw-semibold">Where does ${esc(oldPitcher)} go?</p><div class="row g-2">${positions.map(pos => {
            const occupant = alignment[pos];
            const usable = pos === 'BENCH' || !occupant || pos === incomingPosition;
            return `<div class="col-6 col-md-4"><button type="button" class="btn ${usable ? 'btn-outline-primary' : 'btn-outline-secondary'} w-100 py-3 destination-v2" data-destination="${pos}" ${usable ? '' : 'disabled'}>${esc(pos)}${occupant && pos !== incomingPosition ? `<div class="small">${esc(occupant)}</div>` : ''}</button></div>`;
        }).join('')}</div>`;
        body.addEventListener('click', async e => {
            const btn = e.target.closest('.destination-v2');
            if (!btn || btn.disabled || actionBusy) return;
            actionBusy = true;
            try {
                await api('/change-pitcher', { method: 'POST', body: JSON.stringify({ new_pitcher_id: newPitcherId, outgoing_destination: btn.dataset.destination }) });
                bootstrap.Modal.getOrCreateInstance(modal).hide();
                toast(`✓ ${incoming.name} → P • Saved & Synced`);
            } catch (err) {
                toast(err.message, 'danger');
            } finally { actionBusy = false; }
        }, { once: false });
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    function renderPitchingBoard() {
        const pregame = byId('pregame-checklist-container');
        if (!pregame || liveState?.game?.is_live) return;
        let board = byId('pitching-board-v2');
        if (!board) {
            board = document.createElement('div');
            board.id = 'pitching-board-v2';
            const start = byId('startLiveGameBtnAction')?.parentElement;
            if (start) start.insertAdjacentElement('beforebegin', board);
            else pregame.appendChild(board);
        }
        const plans = [...(liveState?.pitching_plans || [])].sort((a,b) => roleRank(a.role)-roleRank(b.role));
        board.innerHTML = `<div class="card shadow-sm border-0 mb-4"><div class="card-header bg-white d-flex justify-content-between align-items-center"><div><h5 class="mb-0">Today's Pitching Board</h5><div class="small text-muted">Plan the staff before first pitch.</div></div><button type="button" class="btn btn-primary" id="add-pitcher-plan-v2"><i class="bi bi-plus-lg me-1"></i>Add Pitcher</button></div><div class="card-body">${plans.length ? plans.map(plan => {
            const player = liveState.roster.find(p => Number(p.id) === Number(plan.player_id));
            if (!player) return '';
            const s = summaryFor(player); const profile = profileFor(player.id);
            return `<div class="border rounded p-3 mb-2"><div class="d-flex justify-content-between gap-2"><div><div class="fw-bold">${esc(player.name)} <span class="badge text-bg-light border">${esc(plan.role || 'Planned')}</span></div><div class="small text-muted">${esc(s.status || 'Eligibility unknown')} • ${esc(todayText(s))}${s.coach_target != null ? ` • Target ${esc(s.coach_target)}` : ''}</div>${plan.expected_innings ? `<div class="small">Expected: ${esc(plan.expected_innings)} innings</div>` : ''}${profile?.traits?.length ? `<div class="small mt-1">${esc(profile.traits.join(' • '))}</div>` : ''}${plan.coach_note ? `<div class="small fst-italic mt-1">${esc(plan.coach_note)}</div>` : ''}${plan.situational_note ? `<div class="small text-muted mt-1">Use: ${esc(plan.situational_note)}</div>` : ''}</div><button type="button" class="btn btn-sm btn-outline-primary edit-plan-v2" data-player-id="${player.id}">Edit</button></div></div>`;
        }).join('') : '<div class="text-muted text-center py-3">No pitching plan yet. Add your starter and relief options.</div>'}</div></div>`;
        byId('add-pitcher-plan-v2')?.addEventListener('click', showAddPitcherPlan);
        board.querySelectorAll('.edit-plan-v2').forEach(btn => btn.addEventListener('click', () => showPlanEditor(Number(btn.dataset.playerId))));
    }

    function showAddPitcherPlan() {
        const modal = modalShell('add-pitching-plan-v2', 'Add Pitcher to Plan');
        const body = modal.querySelector('.modal-body');
        const plannedIds = new Set((liveState.pitching_plans || []).map(p => Number(p.player_id)));
        body.innerHTML = `<div class="list-group">${(liveState.roster || []).filter(p => !plannedIds.has(Number(p.id))).map(p => `<button type="button" class="list-group-item list-group-item-action add-plan-player-v2" data-player-id="${p.id}">${esc(p.name)}</button>`).join('') || '<div class="text-muted">Every player is already on the pitching board.</div>'}</div>`;
        body.addEventListener('click', e => {
            const btn = e.target.closest('.add-plan-player-v2');
            if (!btn) return;
            bootstrap.Modal.getOrCreateInstance(modal).hide();
            showPlanEditor(Number(btn.dataset.playerId));
        });
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    function showPlanEditor(playerId) {
        const player = liveState.roster.find(p => Number(p.id) === Number(playerId));
        if (!player) return;
        const plan = planFor(playerId) || {};
        const profile = profileFor(playerId) || {};
        const traits = ['Power / Velocity','Change of Pace','Changes Speeds','Command / Strike Thrower','Breaking Ball','Ground Ball','Swing & Miss','Deception','LHP','RHP','Composed Under Pressure','Holds Runners Well','Gets Out of Trouble'];
        const selected = new Set(profile.traits || []);
        const roles = ['Starter','First Relief','Secondary Relief','Late / High Leverage','Emergency Only','Avoid Today'];
        const modal = modalShell('edit-pitching-plan-v2', `Pitching Plan — ${player.name}`);
        const body = modal.querySelector('.modal-body');
        body.innerHTML = `<div class="mb-3"><label class="form-label fw-semibold">Role</label><select class="form-select" id="plan-role-v2"><option value="">Not set</option>${roles.map(r => `<option ${plan.role===r?'selected':''}>${esc(r)}</option>`).join('')}</select></div><div class="mb-3"><label class="form-label fw-semibold">Expected innings</label><input class="form-control" id="plan-innings-v2" value="${esc(plan.expected_innings || '')}" placeholder="e.g. 2–3"></div><div class="mb-3"><label class="form-label fw-semibold">Coach note / future use</label><textarea class="form-control" id="plan-note-v2" rows="2" placeholder="e.g. Save some availability for Sunday">${esc(plan.coach_note || '')}</textarea></div><div class="mb-3"><label class="form-label fw-semibold">Use when…</label><textarea class="form-control" id="plan-situation-v2" rows="2" placeholder="e.g. Need a different look">${esc(plan.situational_note || '')}</textarea></div><div class="mb-3"><label class="form-label fw-semibold">Persistent pitcher traits</label><div class="d-flex flex-wrap gap-2">${traits.map((t,i) => `<input class="btn-check trait-v2" type="checkbox" id="trait-v2-${i}" value="${esc(t)}" ${selected.has(t)?'checked':''}><label class="btn btn-outline-secondary btn-sm" for="trait-v2-${i}">${esc(t)}</label>`).join('')}</div></div><div class="d-grid gap-2"><button type="button" class="btn btn-primary btn-lg" id="save-plan-v2">Save Pitching Plan</button>${plan.id ? '<button type="button" class="btn btn-outline-danger" id="delete-plan-v2">Remove from Today\'s Plan</button>' : ''}</div>`;
        byId('save-plan-v2').addEventListener('click', async () => {
            if (actionBusy) return; actionBusy = true;
            try {
                const chosenTraits = [...body.querySelectorAll('.trait-v2:checked')].map(x => x.value);
                await api('/pitching-profile/' + playerId, { method: 'POST', body: JSON.stringify({ traits: chosenTraits }) });
                await api('/pitching-plan', { method: 'POST', body: JSON.stringify({ player_id: playerId, role: byId('plan-role-v2').value, expected_innings: byId('plan-innings-v2').value, coach_note: byId('plan-note-v2').value, situational_note: byId('plan-situation-v2').value }) });
                bootstrap.Modal.getOrCreateInstance(modal).hide();
                toast('Pitching plan saved.');
            } catch (err) { toast(err.message, 'danger'); }
            finally { actionBusy = false; }
        });
        byId('delete-plan-v2')?.addEventListener('click', async () => {
            try {
                await api('/pitching-plan/' + playerId, { method: 'DELETE' });
                bootstrap.Modal.getOrCreateInstance(modal).hide();
                toast('Pitcher removed from today\'s plan.');
            } catch (err) { toast(err.message, 'danger'); }
        });
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    async function handleCapturedEvent(event) {
        const hit = isLiveActionTarget(event.target);
        if (!hit) return;
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        const id = hit.id;
        if (id === 'liveGameModeToggle') {
            if (liveState?.game?.is_live) hit.checked = true;
            else hit.checked = false;
            return;
        }
        if (actionBusy && id !== 'liveChangePitcherBtn') return;

        try {
            if (id === 'startLiveGameBtnAction') {
                actionBusy = true;
                await api('/start', { method: 'POST', body: '{}' });
                toast('✓ Live Game started • Saved & Synced');
            } else if (id === 'liveChangePitcherBtn') {
                showPitcherPicker();
            } else if (id === 'liveUndoBtn') {
                actionBusy = true;
                await api('/undo', { method: 'POST', body: '{}' });
                toast('✓ Last live change undone • Saved & Synced');
            } else if (id === 'liveEndGameBtn') {
                const pitched = new Set();
                Object.values(liveState.actual_rotation || {}).forEach(inn => { if (inn?.P) pitched.add(inn.P); });
                const container = byId('finalCountsFormContainer');
                if (container) container.innerHTML = [...pitched].map(name => {
                    const p = liveState.roster.find(x => x.name === name);
                    return p ? `<div class="input-group mb-3 input-group-lg"><span class="input-group-text fw-bold" style="width:150px">${esc(name)}</span><input type="number" min="0" class="form-control text-center final-pitch-input" data-player-id="${p.id}" placeholder="Pitches"></div>` : '';
                }).join('') || '<p class="text-muted">No pitchers recorded. You can still end the game.</p>';
                bootstrap.Modal.getOrCreateInstance(byId('liveFinalCountsModal')).show();
            } else if (id === 'confirmFinalCountsBtn') {
                actionBusy = true;
                const counts = [...document.querySelectorAll('.final-pitch-input')].map(input => ({ player_id: Number(input.dataset.playerId), pitches: input.value.trim() === '' ? null : Number(input.value) }));
                await api('/end', { method: 'POST', body: JSON.stringify({ counts }) });
                bootstrap.Modal.getOrCreateInstance(byId('liveFinalCountsModal')).hide();
                toast('Game ended and saved.');
            }
        } catch (err) {
            toast(err.message, 'danger');
        } finally {
            actionBusy = false;
        }
    }

    function connectSocket() {
        if (typeof io !== 'function') {
            connected = false;
            setSyncStatus(liveState?.game?.is_live ? 'offline' : 'synced');
            return;
        }
        socket = io();
        socket.on('connect', async () => {
            connected = true;
            setSyncStatus(liveState?.game?.is_live ? 'synced' : 'synced');
            socket.emit('join_game_room', { game_id: gameId }, async (ack) => {
                if (ack?.status === 'error') {
                    connected = false;
                    setSyncStatus('offline');
                    return;
                }
                try { await fetchState(); } catch (err) { toast(err.message, 'danger'); }
            });
        });
        socket.on('disconnect', () => {
            connected = false;
            if (liveState?.game?.is_live) setSyncStatus('reconnecting');
        });
        socket.on('connect_error', () => {
            connected = false;
            if (liveState?.game?.is_live) setSyncStatus('offline');
        });
        socket.on('game_state_update', state => applyState(state));
        window.addEventListener('beforeunload', () => socket?.emit('leave_game_room', { game_id: gameId }));
    }

    document.addEventListener('click', handleCapturedEvent, true);
    document.addEventListener('change', event => {
        if (event.target?.id === 'liveGameModeToggle') handleCapturedEvent(event);
    }, true);

    document.addEventListener('DOMContentLoaded', async () => {
        connectSocket();
        try { await fetchState(); } catch (err) { toast(err.message, 'danger'); }
    });
})();