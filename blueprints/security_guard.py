import secrets
from urllib.parse import urlparse

from flask import Blueprint, flash, jsonify, redirect, request, session, url_for

from db import db
from models import (
    CollaborationNote,
    GamePitchingPlan,
    GameRotationEvent,
    PitchingOuting,
    Player,
    PlayerDevelopmentFocus,
    PlayerGameAbsence,
    PlayerPracticeAbsence,
    Rotation,
    Team,
    TeamMembership,
    User,
)

security_guard_bp = Blueprint('security_guard', __name__)

SUPER_ADMIN = 'Super Admin'
HEAD_COACH = 'Head Coach'
GAME_CHANGER = 'Game Changer'

LEGACY_LIVE_MUTATIONS = {
    'gameday.save_rotation_event',
    'gameday.toggle_live_game',
    'gameday.undo_rotation_event',
    'gameday.save_pitching_plan',
    'gameday.delete_pitching_plan',
    'gameday.save_final_pitch_counts',
}

DESTRUCTIVE_GET_ENDPOINTS = {
    'gameday.delete_game',
    'gameday.delete_lineup',
    'gameday.delete_rotation',
    'roster.delete_player',
    'pitching.delete_pitching',
    'development.complete_focus',
    'development.delete_focus',
    'development.delete_lesson_info',
    'scouting.delete_scouted_player',
    'team_management.delete_note',
    'team_management.delete_practice_plan',
    'team_management.delete_task',
    'team_management.delete_sign',
    'admin.delete_team',
}

GAME_CHANGER_BLOCKED_PREFIXES = (
    'admin.',
    'roster.',
    'development.',
    'scouting.',
    'team_management.',
    'rotation_templates.',
)


def _cross_site_request():
    fetch_site = str(request.headers.get('Sec-Fetch-Site') or '').lower()
    if fetch_site == 'cross-site':
        return True

    for header in ('Origin', 'Referer'):
        value = request.headers.get(header)
        if not value:
            continue
        try:
            parsed = urlparse(value)
            if parsed.netloc and parsed.netloc != request.host:
                return True
        except ValueError:
            return True

    return False


def _api_request():
    return request.path.startswith('/api/') or request.is_json


def _contains_player_name(value, player_name):
    if isinstance(value, str):
        return value == player_name
    if isinstance(value, dict):
        return any(_contains_player_name(item, player_name) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_player_name(item, player_name) for item in value)
    return False


def _name_has_history(player):
    team_id = player.team_id
    name = player.name

    for rotation in db.session.query(Rotation).filter_by(team_id=team_id).all():
        if _contains_player_name(rotation.innings or {}, name):
            return True

    for event in db.session.query(GameRotationEvent).filter_by(team_id=team_id).all():
        if _contains_player_name(event.before_alignment or {}, name) or _contains_player_name(event.after_alignment or {}, name):
            return True

    if db.session.query(CollaborationNote.id).filter_by(team_id=team_id, player_name=name).first():
        return True

    return False


def _player_has_linked_history(player):
    if _name_has_history(player):
        return True

    linked = (
        db.session.query(PitchingOuting.id).filter_by(team_id=player.team_id, player_id=player.id).first(),
        db.session.query(PlayerGameAbsence.id).filter_by(team_id=player.team_id, player_id=player.id).first(),
        db.session.query(PlayerPracticeAbsence.id).filter_by(team_id=player.team_id, player_id=player.id).first(),
        db.session.query(PlayerDevelopmentFocus.id).filter_by(team_id=player.team_id, player_id=player.id).first(),
        db.session.query(GamePitchingPlan.id).filter_by(team_id=player.team_id, player_id=player.id).first(),
    )
    return any(linked)


def _validate_session_membership():
    username = session.get('username')
    team_id = session.get('team_id')
    if not username or not team_id:
        return False

    user = db.session.query(User).filter(db.func.lower(User.username) == str(username).lower()).first()
    if not user:
        return False

    membership = db.session.query(TeamMembership).filter_by(user_id=user.id, team_id=team_id).first()
    if not membership:
        return False

    # Keep permissions current without marking every read-only request as a
    # session write. Reissuing stale signed cookies from concurrent API calls
    # can otherwise undo a just-completed team switch in the browser.
    if session.get('role') != membership.role:
        session['role'] = membership.role
    return True


def _new_registration_code():
    """Return a short, unguessable code that is not already assigned."""
    for _ in range(20):
        code = secrets.token_urlsafe(9)
        if not db.session.query(Team.id).filter_by(registration_code=code).first():
            return code
    raise RuntimeError('Unable to generate a unique team registration code.')


@security_guard_bp.route('/admin/settings/rotate-registration-code', methods=['POST'])
def rotate_registration_code():
    if session.get('role') not in {HEAD_COACH, SUPER_ADMIN}:
        flash('You must be a Head Coach or Super Admin to rotate the team join code.', 'danger')
        return redirect(url_for('home'))

    team = db.session.get(Team, session.get('team_id'))
    if not team:
        flash('Team not found.', 'danger')
        return redirect(url_for('admin.admin_settings'))

    team.registration_code = _new_registration_code()
    db.session.commit()
    flash('Team join code rotated. The previous code no longer works.', 'success')
    return redirect(url_for('admin.admin_settings'))


@security_guard_bp.before_app_request
def enforce_security_guards():
    endpoint = request.endpoint or ''

    # Flask-SocketIO owns this path outside normal page authorization.
    if request.path.startswith('/socket.io'):
        return None

    public = endpoint == 'static' or endpoint == 'serve_manifest' or endpoint.startswith('auth.')
    if not public:
        if not session.get('logged_in'):
            if _api_request():
                return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401
            return redirect(url_for('auth.login'))
        if not _validate_session_membership():
            session.clear()
            if _api_request():
                return jsonify({'status': 'error', 'message': 'Your team access is no longer active.'}), 401
            flash('Your team access changed. Please sign in again.', 'warning')
            return redirect(url_for('auth.login'))

    cross_site = _cross_site_request()

    # Transitional CSRF protection that does not break the many existing forms.
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and cross_site:
        return jsonify({'status': 'error', 'message': 'Cross-site request blocked.'}), 403

    if request.method == 'GET' and endpoint in DESTRUCTIVE_GET_ENDPOINTS and cross_site:
        return jsonify({'status': 'error', 'message': 'Cross-site destructive request blocked.'}), 403

    if endpoint in LEGACY_LIVE_MUTATIONS:
        return jsonify({
            'status': 'error',
            'message': 'This Live Game action is from an older CoachBoard client. Refresh the page and try again.',
        }), 410

    if endpoint in {'admin.add_user', 'admin.edit_user'} and request.method == 'POST':
        requested_role = str(request.form.get('role') or '').strip()
        if requested_role == SUPER_ADMIN and session.get('role') != SUPER_ADMIN:
            flash('Only a Super Admin can assign the Super Admin role.', 'danger')
            return redirect(url_for('admin.user_management'))

    if session.get('role') == GAME_CHANGER:
        blocked_prefix = endpoint.startswith(GAME_CHANGER_BLOCKED_PREFIXES)
        if blocked_prefix and (request.method != 'GET' or endpoint in DESTRUCTIVE_GET_ENDPOINTS):
            return jsonify({'status': 'error', 'message': 'This account does not have permission to change team setup.'}), 403

    # Current defensive history is still name-based. Until that schema is
    # migrated to stable player IDs, prevent renames/deletes that would orphan
    # historical lineup/rotation/stat references.
    if endpoint == 'roster.update_player_inline' and request.method == 'POST':
        player_id = (request.view_args or {}).get('player_id')
        player = db.session.query(Player).filter_by(id=player_id, team_id=session.get('team_id')).first()
        if player:
            requested_name = str(request.form.get('name') or player.name).strip()
            if requested_name and requested_name != player.name and _name_has_history(player):
                return jsonify({
                    'status': 'error',
                    'message': 'This player already has lineup/game history. Renaming is temporarily locked so historical stats are not disconnected.',
                }), 409

    if endpoint == 'roster.delete_player' and request.method == 'GET':
        player_id = (request.view_args or {}).get('player_id')
        player = db.session.query(Player).filter_by(id=player_id, team_id=session.get('team_id')).first()
        if player and _player_has_linked_history(player):
            flash('This player has season history and cannot be permanently deleted. Historical records were preserved.', 'warning')
            return redirect(url_for('home', _anchor='roster'))

    return None


@security_guard_bp.after_app_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    return response
