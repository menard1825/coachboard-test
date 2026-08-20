import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse
import zoneinfo

from flask import Blueprint, current_app, flash, has_request_context, jsonify, redirect, render_template, request, session, url_for

from db import db
from models import (
    CollaborationNote,
    Game,
    GamePitchingPlan,
    GameRotationEvent,
    Lineup,
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
from permissions import (
    ASSISTANT_COACH,
    DELETE_GAME,
    DELETE_PLAYER,
    GAME_CHANGER,
    HEAD_COACH,
    SUPER_ADMIN,
    has_permission,
)

security_guard_bp = Blueprint('security_guard', __name__)


class ActivityLog(db.Model):
    """Small, durable audit trail for account/session activity.

    Snapshot fields intentionally preserve who/what the event referred to even
    if a coach later changes their name, role, or loses team access.
    """

    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, index=True)
    username_snapshot = db.Column(db.String(120), nullable=False)
    full_name_snapshot = db.Column(db.String(160), nullable=True)
    role_snapshot = db.Column(db.String(64), nullable=True)
    action = db.Column(db.String(64), nullable=False, index=True)
    detail = db.Column(db.String(500), nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)
    client_timezone = db.Column(db.String(80), nullable=True)
    client_utc_offset_minutes = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)


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

ASSISTANT_HEAD_COACH_ONLY_ENDPOINTS = {
    'roster.delete_player': DELETE_PLAYER,
    'gameday.delete_game': DELETE_GAME,
    'game_day.delete_game': DELETE_GAME,
}


def normalize_timezone_name(value):
    """Return a valid IANA timezone name reported by a browser, or None."""
    candidate = str(value or '').strip()
    if not candidate or len(candidate) > 80:
        return None
    try:
        zoneinfo.ZoneInfo(candidate)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return None
    return candidate


def normalize_utc_offset_minutes(value):
    try:
        offset = int(value)
    except (TypeError, ValueError):
        return None
    return offset if -840 <= offset <= 840 else None


def record_activity(
    action,
    *,
    user=None,
    team_id=None,
    role=None,
    detail=None,
    username=None,
    full_name=None,
    client_timezone=None,
    client_utc_offset_minutes=None,
):
    """Record account activity without allowing an audit failure to break login.

    Callers should commit their business change first. This helper uses a small
    independent commit so a logging problem never rolls back a successful login,
    password change, or team switch.
    """
    if user is not None:
        username = user.username
        full_name = user.full_name
    username = str(username or session.get('username') or 'Unknown').strip() or 'Unknown'
    full_name = full_name if full_name is not None else session.get('full_name')
    role = role if role is not None else session.get('role')
    if team_id is None:
        team_id = session.get('team_id')

    client_timezone = normalize_timezone_name(
        client_timezone if client_timezone is not None else session.get('client_timezone')
    )
    client_utc_offset_minutes = normalize_utc_offset_minutes(
        client_utc_offset_minutes if client_utc_offset_minutes is not None else session.get('client_utc_offset_minutes')
    )

    ip_address = None
    user_agent = None
    if has_request_context():
        forwarded = str(request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
        ip_address = forwarded or request.remote_addr
        user_agent = str(request.headers.get('User-Agent') or '')[:300] or None

    try:
        row = ActivityLog(
            user_id=getattr(user, 'id', None),
            team_id=team_id,
            username_snapshot=username[:120],
            full_name_snapshot=(str(full_name)[:160] if full_name else None),
            role_snapshot=(str(role)[:64] if role else None),
            action=str(action or 'activity')[:64],
            detail=(str(detail)[:500] if detail else None),
            ip_address=(str(ip_address)[:64] if ip_address else None),
            user_agent=user_agent,
            client_timezone=client_timezone,
            client_utc_offset_minutes=client_utc_offset_minutes,
        )
        db.session.add(row)
        db.session.commit()
        return row
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Unable to write CoachBoard activity log entry for %s', username)
        return None


def _team_timezone_name():
    team_id = session.get('team_id')
    if not team_id:
        return 'UTC'
    team = db.session.get(Team, team_id)
    return (team.timezone if team and team.timezone else 'UTC')


def _format_datetime_for_timezone(value, timezone_name):
    if not value or not isinstance(value, datetime):
        return 'Never' if not value else value
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    try:
        local = aware.astimezone(zoneinfo.ZoneInfo(timezone_name or 'UTC'))
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        local = aware
    return local.strftime('%a %m/%d/%y, %I:%M %p %Z')


@security_guard_bp.app_template_filter('format_audit_datetime')
def format_audit_datetime(value):
    """Display stored UTC audit/last-login values in the active team's timezone."""
    return _format_datetime_for_timezone(value, _team_timezone_name())


@security_guard_bp.app_template_filter('format_audit_datetime_in_timezone')
def format_audit_datetime_in_timezone(value, timezone_name):
    """Display the same UTC audit timestamp in the coach/browser timezone."""
    return _format_datetime_for_timezone(value, normalize_timezone_name(timezone_name) or 'UTC')


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


def _permission_denied(message):
    if _api_request() or request.method != 'GET':
        return jsonify({'status': 'error', 'message': message}), 403
    flash(message, 'warning')
    return redirect(url_for('game_day.game_day_home'))


def _rotation_sort_key(value):
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _game_changer_setup_response(game_id):
    """Render the read-only pregame sheet used to enter data into GameChanger."""
    team_id = session.get('team_id')
    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if not game:
        flash('Game not found.', 'danger')
        return redirect(url_for('game_day.game_day_home'))

    # Once a game is complete, the actual report is more useful than the old
    # pregame plan.
    has_end_game = db.session.query(GameRotationEvent.id).filter_by(
        game_id=game.id,
        team_id=team_id,
        event_type='End Game',
        reverted=False,
    ).first() is not None
    if has_end_game:
        return redirect(url_for('game_day.game_report', game_id=game.id))

    roster = db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
    roster_by_id = {player.id: player for player in roster}
    roster_by_name = {player.name: player for player in roster}
    absence_rows = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team_id).all()
    absent_ids = {row.player_id for row in absence_rows}
    available_roster = [player for player in roster if player.id not in absent_ids]
    absent_roster = [player for player in roster if player.id in absent_ids]

    lineup = db.session.query(Lineup).filter_by(associated_game_id=game.id, team_id=team_id).first()
    lineup_rows = []
    if lineup:
        if lineup.entries:
            for entry in sorted(lineup.entries, key=lambda item: item.batting_order):
                player = roster_by_id.get(entry.player_id)
                lineup_rows.append({
                    'order': entry.batting_order,
                    'name': player.name if player else entry.player_name_snapshot,
                    'number': player.number if player else None,
                    'available': bool(player and player.id not in absent_ids),
                })
        else:
            legacy_names = lineup.lineup_positions or []
            if isinstance(legacy_names, list):
                for index, name in enumerate(legacy_names, start=1):
                    player = roster_by_name.get(name)
                    lineup_rows.append({
                        'order': index,
                        'name': name,
                        'number': player.number if player else None,
                        'available': bool(player and player.id not in absent_ids),
                    })

    rotation = db.session.query(Rotation).filter_by(associated_game_id=game.id, team_id=team_id).first()
    raw_innings = rotation.innings if rotation and isinstance(rotation.innings, dict) else {}
    positions = ['P', 'C', '1B', '2B', '3B', 'SS']
    if int(getattr(db.session.get(Team, team_id), 'outfielder_count', 3) or 3) == 4:
        positions += ['LF', 'LCF', 'RCF', 'RF']
    else:
        positions += ['LF', 'CF', 'RF']

    rotation_rows = []
    available_names = {player.name for player in available_roster}
    for inning in sorted(raw_innings.keys(), key=_rotation_sort_key):
        assignments = raw_innings.get(inning) or {}
        assigned_names = {name for name in assignments.values() if name}
        rotation_rows.append({
            'inning': inning,
            'assignments': assignments,
            'bench': [player for player in available_roster if player.name not in assigned_names],
            'has_unavailable_assignment': any(name not in available_names for name in assigned_names),
        })

    return render_template(
        'game_changer_setup.html',
        current_team=db.session.get(Team, team_id),
        game=game,
        lineup_rows=lineup_rows,
        rotation_rows=rotation_rows,
        positions=positions,
        available_roster=available_roster,
        absent_roster=absent_roster,
    )


@security_guard_bp.route('/api/client-context', methods=['POST'])
def client_context():
    """Keep the signed-in session aware of this browser's timezone.

    Browsers expose an IANA timezone without requiring GPS/geolocation permission.
    This endpoint does not change the team's official timezone.
    """
    payload = request.get_json(silent=True) or {}
    timezone_name = normalize_timezone_name(payload.get('timezone'))
    offset_minutes = normalize_utc_offset_minutes(payload.get('utc_offset_minutes'))
    if timezone_name:
        session['client_timezone'] = timezone_name
    if offset_minutes is not None:
        session['client_utc_offset_minutes'] = offset_minutes
    return jsonify({
        'status': 'ok',
        'timezone': session.get('client_timezone'),
        'utc_offset_minutes': session.get('client_utc_offset_minutes'),
    })


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


@security_guard_bp.route('/admin/activity')
def activity_log():
    if session.get('role') not in {HEAD_COACH, SUPER_ADMIN}:
        return _permission_denied('Only a Head Coach or Super Admin can view coach activity.')

    team_id = session.get('team_id')
    team = db.session.get(Team, team_id)
    logs = db.session.query(ActivityLog).filter_by(team_id=team_id).order_by(
        ActivityLog.created_at.desc(), ActivityLog.id.desc()
    ).limit(300).all()

    memberships = db.session.query(TeamMembership).filter_by(team_id=team_id).all()
    coaches = []
    for membership in memberships:
        user = membership.user
        latest_login = next(
            (row for row in logs if row.action == 'login' and row.user_id == user.id),
            None,
        )
        coaches.append({
            'user': user,
            'role': membership.role,
            'latest_login': latest_login,
        })
    coaches.sort(key=lambda item: ((item['user'].full_name or item['user'].username).lower()))

    return render_template(
        'activity_log.html',
        current_team=team,
        logs=logs,
        coaches=coaches,
        timezone_name=_team_timezone_name(),
    )


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

    role = session.get('role')

    # Game Changer is a read-only pregame scorekeeper role. Do not maintain a
    # growing list of writable blueprints: deny CoachBoard mutations by default.
    if role == GAME_CHANGER and not endpoint.startswith('auth.') and endpoint != 'security_guard.client_context':
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} or endpoint in DESTRUCTIVE_GET_ENDPOINTS:
            return _permission_denied('Game Changer access is read-only. Use the pregame setup view to enter the lineup and defense into GameChanger.')
        if endpoint == 'home':
            return redirect(url_for('game_day.game_day_home'))
        if endpoint == 'gameday.game_management':
            game_id = (request.view_args or {}).get('game_id')
            return _game_changer_setup_response(game_id)

    # Assistant Coaches are full coaching collaborators but permanent player or
    # game deletion stays with the Head Coach/Super Admin.
    required_capability = ASSISTANT_HEAD_COACH_ONLY_ENDPOINTS.get(endpoint)
    if role == ASSISTANT_COACH and required_capability and not has_permission(role, required_capability):
        label = 'players' if required_capability == DELETE_PLAYER else 'games'
        return _permission_denied(f'Only a Head Coach or Super Admin can permanently delete {label}.')

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