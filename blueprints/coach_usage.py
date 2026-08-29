import os
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func

from db import db
from models import Team, TeamMembership, User
from blueprints.security_guard import (
    ActivityLog,
    normalize_timezone_name,
    normalize_utc_offset_minutes,
    record_activity,
)


coach_usage_bp = Blueprint('coach_usage', __name__)

ACTIVE_WINDOW = timedelta(minutes=3)
RECENT_WINDOW = timedelta(minutes=15)


class CoachPresence(db.Model):
    """Lightweight presence snapshot for signed-in CoachBoard browser sessions."""

    __tablename__ = 'coach_presence'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False, index=True)
    browser_session_id = db.Column(db.String(96), nullable=False)
    started_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    last_seen_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)
    active_seconds = db.Column(db.Integer, nullable=False, default=0)
    current_area = db.Column(db.String(80), nullable=True)
    current_path = db.Column(db.String(180), nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)
    client_timezone = db.Column(db.String(80), nullable=True)
    client_utc_offset_minutes = db.Column(db.Integer, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'team_id', 'browser_session_id', name='uq_coach_presence_session'),
    )


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _owner_username():
    return str(os.environ.get('COACHBOARD_USAGE_OWNER_USERNAME') or 'mike1825').strip().lower()


def is_coach_usage_owner():
    return bool(
        session.get('logged_in')
        and str(session.get('username') or '').strip().lower() == _owner_username()
    )


@coach_usage_bp.app_context_processor
def inject_coach_usage_owner():
    return {'coach_usage_owner': is_coach_usage_owner()}


def _current_user_and_membership():
    if not session.get('logged_in') or not session.get('username') or not session.get('team_id'):
        return None, None
    user = db.session.query(User).filter(
        func.lower(User.username) == str(session['username']).lower()
    ).first()
    if not user:
        return None, None
    membership = db.session.query(TeamMembership).filter_by(
        user_id=user.id,
        team_id=session['team_id'],
    ).first()
    return user, membership


def _clean_text(value, limit, fallback=''):
    cleaned = ' '.join(str(value or '').split()).strip()
    return (cleaned[:limit] if cleaned else fallback)


def _request_ip():
    forwarded = str(request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    return (forwarded or request.remote_addr or '')[:64] or None


def _device_label(user_agent):
    ua = str(user_agent or '')
    if 'iPhone' in ua:
        device = 'iPhone'
    elif 'iPad' in ua:
        device = 'iPad'
    elif 'Android' in ua:
        device = 'Android'
    elif 'Windows' in ua:
        device = 'Windows PC'
    elif 'Macintosh' in ua or 'Mac OS X' in ua:
        device = 'Mac'
    elif 'Linux' in ua:
        device = 'Linux'
    else:
        device = 'Browser'

    if 'Edg/' in ua or 'EdgiOS/' in ua:
        browser = 'Edge'
    elif 'CriOS/' in ua or ('Chrome/' in ua and 'Edg/' not in ua):
        browser = 'Chrome'
    elif 'FxiOS/' in ua or 'Firefox/' in ua:
        browser = 'Firefox'
    elif 'Safari/' in ua:
        browser = 'Safari'
    else:
        browser = ''
    return f'{device} · {browser}' if browser else device


def _duration_label(seconds):
    total = max(0, int(seconds or 0))
    if total < 60:
        return '<1 min'
    minutes = total // 60
    if minutes < 60:
        return f'{minutes} min'
    hours, rem = divmod(minutes, 60)
    return f'{hours}h {rem}m' if rem else f'{hours}h'


@coach_usage_bp.route('/api/coach-usage/heartbeat', methods=['GET', 'POST'])
def heartbeat():
    user, membership = _current_user_and_membership()
    if not user or not membership:
        return jsonify({'status': 'error', 'message': 'Sign in required.'}), 401

    payload = (request.get_json(silent=True) or {}) if request.method == 'POST' else request.args
    browser_session_id = _clean_text(payload.get('browser_session_id'), 96)
    if not browser_session_id:
        browser_session_id = secrets.token_urlsafe(18)
    area = _clean_text(payload.get('area'), 80, 'CoachBoard')
    path = _clean_text(payload.get('path'), 180, '/')
    if not path.startswith('/'):
        path = '/'
    timezone_name = normalize_timezone_name(payload.get('timezone'))
    offset_minutes = normalize_utc_offset_minutes(payload.get('utc_offset_minutes'))
    now = _utcnow_naive()

    presence = db.session.query(CoachPresence).filter_by(
        user_id=user.id,
        team_id=membership.team_id,
        browser_session_id=browser_session_id,
    ).first()

    created = presence is None
    previous_area = presence.current_area if presence else None
    if presence is None:
        presence = CoachPresence(
            user_id=user.id,
            team_id=membership.team_id,
            browser_session_id=browser_session_id,
            started_at=now,
            last_seen_at=now,
            current_area=area,
            current_path=path,
            ip_address=_request_ip(),
            user_agent=str(request.headers.get('User-Agent') or '')[:300] or None,
            client_timezone=timezone_name,
            client_utc_offset_minutes=offset_minutes,
            active_seconds=0,
        )
        db.session.add(presence)
    else:
        gap = max(0, int((now - presence.last_seen_at).total_seconds())) if presence.last_seen_at else 0
        if 0 < gap <= 180:
            presence.active_seconds = int(presence.active_seconds or 0) + gap
        presence.last_seen_at = now
        presence.current_area = area
        presence.current_path = path
        presence.ip_address = _request_ip()
        presence.user_agent = str(request.headers.get('User-Agent') or '')[:300] or presence.user_agent
        if timezone_name:
            presence.client_timezone = timezone_name
        if offset_minutes is not None:
            presence.client_utc_offset_minutes = offset_minutes

    db.session.commit()

    if created:
        record_activity(
            'session_start',
            user=user,
            team_id=membership.team_id,
            role=membership.role,
            detail=f'Started using CoachBoard in {area}.',
            client_timezone=timezone_name,
            client_utc_offset_minutes=offset_minutes,
        )
    elif previous_area and previous_area != area:
        record_activity(
            'page_view',
            user=user,
            team_id=membership.team_id,
            role=membership.role,
            detail=f'Opened {area}.',
            client_timezone=timezone_name,
            client_utc_offset_minutes=offset_minutes,
        )

    return jsonify({'status': 'ok', 'area': area})


@coach_usage_bp.route('/admin/coach-usage')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    if not is_coach_usage_owner():
        abort(403)

    team_id = session.get('team_id')
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)

    memberships = db.session.query(TeamMembership).filter_by(team_id=team_id).all()
    users = {user.id: user for user in db.session.query(User).filter(
        User.id.in_([membership.user_id for membership in memberships] or [-1])
    ).all()}

    all_presence = db.session.query(CoachPresence).filter_by(team_id=team_id).order_by(
        CoachPresence.last_seen_at.desc()
    ).all()
    presence_by_user = {}
    for row in all_presence:
        presence_by_user.setdefault(row.user_id, []).append(row)

    login_rows = db.session.query(ActivityLog).filter_by(team_id=team_id, action='login').order_by(
        ActivityLog.created_at.desc(), ActivityLog.id.desc()
    ).all()
    latest_login = {}
    for row in login_rows:
        if row.user_id is not None and row.user_id not in latest_login:
            latest_login[row.user_id] = row

    now = _utcnow_naive()
    coaches = []
    active_count = 0
    recent_count = 0
    for membership in memberships:
        user = users.get(membership.user_id)
        if not user:
            continue
        rows = presence_by_user.get(user.id, [])
        latest = rows[0] if rows else None
        active_sessions = 0
        status = 'Offline'
        status_class = 'offline'
        if latest and latest.last_seen_at:
            age = now - latest.last_seen_at
            active_sessions = sum(
                1 for row in rows
                if row.last_seen_at and now - row.last_seen_at <= ACTIVE_WINDOW
            )
            if age <= ACTIVE_WINDOW:
                status = 'Active now'
                status_class = 'active'
                active_count += 1
                recent_count += 1
            elif age <= RECENT_WINDOW:
                status = 'Recently active'
                status_class = 'recent'
                recent_count += 1
        coaches.append({
            'user': user,
            'role': membership.role,
            'presence': latest,
            'status': status,
            'status_class': status_class,
            'active_sessions': active_sessions,
            'device': _device_label(latest.user_agent) if latest else '—',
            'active_time': _duration_label(latest.active_seconds) if latest else '—',
            'latest_login': latest_login.get(user.id),
        })

    coaches.sort(key=lambda item: (
        0 if item['status_class'] == 'active' else 1 if item['status_class'] == 'recent' else 2,
        (item['user'].full_name or item['user'].username).lower(),
    ))

    events = db.session.query(ActivityLog).filter(
        ActivityLog.team_id == team_id,
        ActivityLog.action.in_(['login', 'logout', 'session_start', 'page_view', 'team_switch']),
    ).order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).limit(150).all()

    used_24h_ids = {
        row.user_id for row in all_presence
        if row.user_id is not None and row.last_seen_at and now - row.last_seen_at <= timedelta(hours=24)
    }

    return render_template(
        'coach_usage.html',
        current_team=team,
        coaches=coaches,
        events=events,
        active_count=active_count,
        recent_count=recent_count,
        used_24h_count=len(used_24h_ids),
        timezone_name=team.timezone or 'UTC',
        refresh_seconds=30,
    )
