import re
from copy import deepcopy

from flask import Blueprint, jsonify, request

from db import db
from models import Player, PlayerGameAbsence
from blueprints.live_game_api import _authorized_context, get_authoritative_live_state


live_game_safety_bp = Blueprint('live_game_safety', __name__)


def _required_positions(team):
    positions = ['P', 'C', '1B', '2B', '3B', 'SS']
    if int(team.outfielder_count or 3) == 4:
        positions += ['LF', 'LCF', 'RCF', 'RF']
    else:
        positions += ['LF', 'CF', 'RF']
    return positions


def _present_names(game, team_id):
    absent_ids = {
        row.player_id
        for row in db.session.query(PlayerGameAbsence).filter_by(
            game_id=game.id,
            team_id=team_id,
        ).all()
    }
    return {
        player.name
        for player in db.session.query(Player).filter_by(team_id=team_id).all()
        if player.id not in absent_ids
    }


def _alignment_problem(alignment, game, team):
    alignment = alignment or {}
    required = _required_positions(team)
    missing = [pos for pos in required if not alignment.get(pos)]
    if missing:
        return f"Defense would leave {', '.join(missing)} open. Use Set New Defense to finish the whole alignment."

    names = [alignment.get(pos) for pos in required if alignment.get(pos)]
    if len(names) != len(set(names)):
        return 'A player cannot occupy more than one defensive position.'

    present_names = _present_names(game, team.id)
    unavailable = [name for name in names if name not in present_names]
    if unavailable:
        return f"{unavailable[0]} is not available for this game."

    return None


def _game_id_from_request():
    try:
        return int((request.view_args or {}).get('game_id'))
    except (TypeError, ValueError):
        return None


def _guard_quick_change(game, team, data):
    state = get_authoritative_live_state(game.id, team.id) or {}
    before = deepcopy(state.get('current_alignment') or {})
    if not before:
        return jsonify({
            'status': 'error',
            'message': 'No complete current defense exists. Use Set New Defense before making a Quick Change.'
        }), 409

    try:
        player_id = int(data.get('player_id'))
    except (TypeError, ValueError):
        return None

    player = db.session.query(Player).filter_by(id=player_id, team_id=team.id).first()
    if not player:
        return None

    destination = str(data.get('destination_position') or 'BENCH').upper()
    source = next((pos for pos, name in before.items() if name == player.name), None)

    if source == 'P' or destination == 'P':
        return jsonify({
            'status': 'error',
            'message': 'Use Change Pitcher for any move involving P.'
        }), 409

    after = deepcopy(before)
    if destination == 'BENCH':
        if source:
            after.pop(source, None)
    else:
        occupant = after.get(destination)
        if source:
            after.pop(source, None)
        after[destination] = player.name
        if occupant and occupant != player.name and source:
            after[source] = occupant

    problem = _alignment_problem(after, game, team)
    if problem:
        return jsonify({
            'status': 'error',
            'message': problem
        }), 409
    return None


def _guard_legacy_pitcher_change(game, team, data):
    state = get_authoritative_live_state(game.id, team.id) or {}
    before = deepcopy(state.get('current_alignment') or {})
    if not before:
        return jsonify({
            'status': 'error',
            'message': 'No complete current defense exists. Use Set New Defense first.'
        }), 409

    try:
        new_pitcher_id = int(data.get('new_pitcher_id'))
    except (TypeError, ValueError):
        return None

    new_pitcher = db.session.query(Player).filter_by(id=new_pitcher_id, team_id=team.id).first()
    if not new_pitcher:
        return None

    after = deepcopy(before)
    old_pitcher = before.get('P')
    incoming_source = next((pos for pos, name in before.items() if name == new_pitcher.name), None)
    if incoming_source:
        after.pop(incoming_source, None)
    after['P'] = new_pitcher.name

    destination = str(data.get('outgoing_destination') or 'BENCH').upper()
    if old_pitcher and destination != 'BENCH':
        after[destination] = old_pitcher

    problem = _alignment_problem(after, game, team)
    if problem:
        return jsonify({
            'status': 'error',
            'message': f'{problem} Finish the pitching change by explicitly filling every position.'
        }), 409
    return None


@live_game_safety_bp.before_app_request
def protect_complete_live_defense():
    if request.method != 'POST':
        return None

    # Starting Live Game has one owner: live_game_api.start, which calls the
    # shared can_start_game() contract. Keep this safety layer focused on live
    # defensive mutations so it cannot return a competing start-readiness 409.
    endpoint = request.endpoint
    if endpoint not in {
        'live_game_api.defensive_change',
        'live_game_api.change_pitcher',
    }:
        return None

    game_id = _game_id_from_request()
    if not game_id:
        return None

    user, team, game = _authorized_context(game_id)
    if not game:
        return None

    if not game.is_live:
        return None

    data = request.get_json(silent=True) or {}
    if endpoint == 'live_game_api.defensive_change':
        return _guard_quick_change(game, team, data)
    if endpoint == 'live_game_api.change_pitcher':
        return _guard_legacy_pitcher_change(game, team, data)

    return None


@live_game_safety_bp.after_app_request
def stabilize_live_game_first_paint(response):
    """Render an already-live game in live mode from the very first browser paint.

    The legacy Game Management markup still exists for compatibility, but an
    already-live request must not briefly show the pregame page or old live
    buttons while the authoritative controller boots.
    """
    if response.mimetype != 'text/html' or not re.fullmatch(r'/game/\d+/?', request.path):
        return response

    match = re.fullmatch(r'/game/(\d+)/?', request.path)
    if not match:
        return response

    try:
        game_id = int(match.group(1))
    except (TypeError, ValueError):
        return response

    user, team, game = _authorized_context(game_id)
    if not game or not game.is_live:
        return response

    html = response.get_data(as_text=True)

    # Hide the pregame checklist before the browser can paint it.
    html = html.replace(
        'id="pregame-checklist-container" class="planner-controls"',
        'id="pregame-checklist-container" class="planner-controls d-none"',
        1,
    )

    # The rotation card must remain mounted because it owns the live overlay,
    # but the old planner surface should never be the first thing coaches see.
    overlay_pattern = re.compile(r'(<div id="live-game-overlay" class=")([^"]*)(">)')

    def _activate_overlay(m):
        classes = [c for c in m.group(2).split() if c != 'd-none']
        if 'coach-live-server-active' not in classes:
            classes.append('coach-live-server-active')
        return m.group(1) + ' '.join(classes) + m.group(3)

    html = overlay_pattern.sub(_activate_overlay, html, count=1)

    loading = '''
<div class="coach-live-server-loading" role="status" aria-live="polite">
  <div class="coach-live-server-spinner"></div>
  <strong>Loading Live Dugout…</strong>
  <span>Syncing the current inning and defense</span>
</div>
'''
    html = re.sub(
        r'(<div id="live-game-overlay" class="[^"]*">)',
        r'\1' + loading,
        html,
        count=1,
    )

    first_paint = '''
<style id="coach-live-server-paint">
  #pregame-checklist-container.d-none { display:none !important; }
  #pitching-log-container { display:none !important; }
  #rotation-card-container > .card > .card-header { display:none !important; }
  #rotation-board { display:none !important; }
  #live-game-overlay.coach-live-server-active:not(.coach-live-polished):not(.coach-live-boot-fallback) {
    visibility:visible !important;
    display:block !important;
    min-height:320px;
    background:#f5f6f8 !important;
  }
  #live-game-overlay.coach-live-server-active:not(.coach-live-polished):not(.coach-live-boot-fallback) > :not(.coach-live-server-loading) {
    display:none !important;
  }
  .coach-live-server-loading {
    min-height:290px;
    display:flex;
    flex-direction:column;
    align-items:center;
    justify-content:center;
    text-align:center;
    gap:7px;
    color:#344054;
  }
  .coach-live-server-loading strong { font-size:.95rem; }
  .coach-live-server-loading span { color:#98a2b3; font-size:.72rem; }
  .coach-live-server-spinner {
    width:24px;
    height:24px;
    border-radius:50%;
    border:3px solid #d9dee7;
    border-top-color:var(--primary-color,#102a66);
    animation:coachLiveBootSpin .8s linear infinite;
  }
  #live-game-overlay.coach-live-polished > .coach-live-server-loading,
  #live-game-overlay.coach-live-boot-fallback > .coach-live-server-loading {
    display:none !important;
  }
  @keyframes coachLiveBootSpin { to { transform:rotate(360deg); } }
</style>
'''
    if '</head>' in html:
        html = html.replace('</head>', first_paint + '</head>', 1)
    else:
        html = first_paint + html

    response.set_data(html)
    return response
