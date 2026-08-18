from urllib.parse import urlparse

from flask import Blueprint, flash, jsonify, redirect, request, session, url_for

from db import db
from models import (
    CollaborationNote,
    GamePitchingPlan,
    GameRotationEvent,
    Lineup,
    PitchingOuting,
    Player,
    PlayerDevelopmentFocus,
    PlayerGameAbsence,
    PlayerPracticeAbsence,
    Rotation,
)

security_guard_bp = Blueprint('security_guard', __name__)

SUPER_ADMIN = 'Super Admin'
GAME_CHANGER = 'Game Changer'

LEGACY_LIVE_MUTATIONS = {
    'gameday.save_rotation_event',
    'gameday.toggle_live_game',
    'gameday.undo_rotation_event',
    'gameday.save_pitching_plan',
    'gameday.delete_pitching_plan',
    'gameday.save_final_pitch_counts',
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

    origin = request.headers.get('Origin')
    if origin:
        try:
            if urlparse(origin).netloc and urlparse(origin).netloc != request.host:
                return True
        except ValueError:
            return True

    return False


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

    for lineup in db.session.query(Lineup).filter_by(team_id=team_id).all():
        if _contains_player_name(lineup.lineup_positions or [], name):
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


@security_guard_bp.before_app_request
def enforce_security_guards():
    endpoint = request.endpoint or ''

    # Transitional CSRF protection that works without breaking every existing
    # form. Same-origin requests continue to work; explicit cross-site writes
    # are rejected. We can move to per-form tokens after legacy forms are retired.
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and _cross_site_request():
        return jsonify({'status': 'error', 'message': 'Cross-site request blocked.'}), 403

    # Old Live Game mutation routes are intentionally retired. They accepted
    # client-authored state and could bypass the authoritative workflow.
    if endpoint in LEGACY_LIVE_MUTATIONS:
        return jsonify({
            'status': 'error',
            'message': 'This Live Game action is from an older CoachBoard client. Refresh the page and try again.',
        }), 410

    # Never trust a hidden HTML option for authorization. A Head Coach must not
    # be able to forge a request that grants Super Admin.
    if endpoint in {'admin.add_user', 'admin.edit_user'} and request.method == 'POST':
        requested_role = str(request.form.get('role') or '').strip()
        if requested_role == SUPER_ADMIN and session.get('role') != SUPER_ADMIN:
            flash('Only a Super Admin can assign the Super Admin role.', 'danger')
            return redirect(url_for('admin.user_management'))

    # Game Changer is an operational game-day role, not a team-management role.
    if session.get('role') == GAME_CHANGER and request.method != 'GET':
        if endpoint.startswith(GAME_CHANGER_BLOCKED_PREFIXES):
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
