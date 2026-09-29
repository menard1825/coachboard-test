"""Active-team authorization shared by existing and new production routes."""
import hmac
import secrets
import json
from flask import g, request, session, redirect, url_for, jsonify, render_template
from db import db
from models import User, Team, TeamMembership

PUBLIC_ENDPOINTS = {'auth.login', 'auth.register', 'static', 'serve_manifest', 'auth.logout'}
# These legacy GET routes modify data. They get the same guards as POST requests.
LEGACY_WRITE_PREFIXES = ('delete_', 'complete_focus')
ARCHIVE_EXCEPTIONS = {'seasons.switch_team', 'seasons.rollover', 'seasons.archive_team', 'auth.change_password'}


def membership_for(user_id, team_id):
    return db.session.get(TeamMembership, (user_id, team_id))


def team_members(team_id):
    return TeamMembership.query.filter_by(team_id=team_id).all()


def role_for(user, membership):
    return 'Super Admin' if user.role == 'Super Admin' else membership.role


def activate_team(user, membership):
    # Keep the legacy team_id as the preferred team for the next login. Memberships
    # remain the authority for access and each browser session has its own context.
    user.team_id = membership.team_id
    if user.role != 'Super Admin':
        user.role = membership.role
    db.session.commit()
    session['team_id'] = membership.team_id
    session['role'] = role_for(user, membership)
    session['player_order'] = membership.player_order or []
    session.pop('rollover_nonce', None)


def install_team_access(app):
    @app.before_request
    def authorize_team():
        if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
            return
        user = User.query.filter_by(username=session.get('username')).first() if session.get('logged_in') else None
        if not user:
            if request.path.startswith('/api/') or request.is_json:
                return jsonify(error='Unauthorized', message='Please sign in again.'), 401
            return redirect(url_for('auth.login'))
        membership = membership_for(user.id, session.get('team_id'))
        if membership is None:
            # Revoked access must not silently move a pending save to another team.
            session.clear()
            return redirect(url_for('auth.login'))
        g.current_user, g.membership = user, membership
        g.current_team = membership.team
        effective_role = role_for(user, membership)
        if session.get('role') != effective_role:
            session['role'] = effective_role
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)

        action = request.endpoint.rsplit('.', 1)[-1]
        mutation = request.method not in ('GET', 'HEAD', 'OPTIONS') or action.startswith(LEGACY_WRITE_PREFIXES)
        supplied_team = request.headers.get('X-Team-ID') or request.form.get('_team_id') or request.args.get('_team_id')
        if supplied_team is not None and supplied_team != str(membership.team_id):
            return error('Your active team changed in another tab. Reload this page before continuing.', 409)
        if mutation:
            if supplied_team != str(membership.team_id):
                return error('Reload this page before saving so the active team can be verified.', 409)
            csrf = request.headers.get('X-CSRF-Token') or request.form.get('_csrf_token') or request.args.get('_csrf_token', '')
            if not hmac.compare_digest(csrf, session['csrf_token']):
                return error('This form expired. Reload the page and try again.', 400)
            if membership.team.is_archived and request.endpoint not in ARCHIVE_EXCEPTIONS:
                return error('This team is archived and read-only. Restore it from Teams & Seasons to make changes.', 403)

    @app.context_processor
    def team_context():
        return {'active_membership': getattr(g, 'membership', None),
                'team_csrf_token': session.get('csrf_token', ''),
                'team_context_id': session.get('team_id')}


def error(message, status):
    if request.is_json or request.path.startswith('/api/') or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(status='error', message=message, error=message), status
    return render_template('team_error.html', message=message), status


def player_order_for(membership):
    from models import Player
    order = membership.player_order or []
    if isinstance(order, str):
        try:
            order = json.loads(order)
        except (ValueError, TypeError):
            order = []
    if not isinstance(order, list):
        return []
    players = Player.query.filter_by(team_id=membership.team_id, is_active=True).all()
    names = {p.name for p in players}
    ids = {p.id: p.name for p in players}
    result = []
    for item in order:
        name = ids.get(item) if isinstance(item, int) else item
        if isinstance(name, str) and name in names and name not in result:
            result.append(name)
    return result
