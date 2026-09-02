import os
import json
import sqlite3
import zoneinfo
from flask import Flask, render_template, session, jsonify, send_from_directory, redirect, url_for, flash, make_response
from datetime import datetime, timedelta, date, timezone
from functools import wraps
from sqlalchemy.orm import joinedload
from sqlalchemy import event, func
from sqlalchemy.engine import Engine

# Local Imports
from db import db
from models import (
    User, Team, Player, Lineup, PitchingOuting, ScoutedPlayer,
    Rotation, Game, CollaborationNote, PracticePlan, PlayerDevelopmentFocus, Sign,
    PlayerGameAbsence, PlayerPracticeAbsence
)
from extensions import socketio, migrate

from utils import (
    get_pitching_rules_for_team, calculate_cumulative_pitching_stats,
    calculate_cumulative_position_stats, calculate_pitch_count_summary
)

# --- Blueprint Imports ---
from blueprints.auth import auth_bp
from blueprints.admin import admin_bp
from blueprints.roster import roster_bp
from blueprints.development import development_bp
from blueprints.live_game_ui import live_game_ui_bp
from blueprints.gameday import gameday_bp
from blueprints.game_day import game_day_bp
from blueprints.rotation_templates import rotation_templates_bp
from blueprints.pitching import pitching_bp
from blueprints.scouting import scouting_bp
from blueprints.team_management import team_management_bp
from blueprints.api import api_bp
from blueprints.stats_dashboard import stats_dashboard_bp
from blueprints.live_game_api import live_game_api_bp
from blueprints.live_game_bulk_api import live_game_bulk_bp
from blueprints.live_game_safety import live_game_safety_bp
from blueprints.live_game_pitching_api import live_game_pitching_bp
from blueprints.security_guard import security_guard_bp
from blueprints.coach_usage import coach_usage_bp
from blueprints.live_game_write_lock import live_game_write_lock_bp
from blueprints.live_game_clock import live_game_clock_bp
from blueprints.postgame_navigation import postgame_navigation_bp
from blueprints.fair_play import fair_play_bp

# --- ROLE CONSTANTS ---
SUPER_ADMIN = 'Super Admin'
HEAD_COACH = 'Head Coach'


@event.listens_for(Engine, 'connect')
def _configure_sqlite_connection(dbapi_connection, connection_record):
    """Make SQLite safer for concurrent coaches and enforce foreign keys."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=15000')
        cursor.execute('PRAGMA journal_mode=WAL')
    finally:
        cursor.close()


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def create_app():
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__)

    runtime = str(os.environ.get('COACHBOARD_ENV') or os.environ.get('FLASK_ENV') or 'development').lower()
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if runtime in {'production', 'prod'}:
            raise RuntimeError('SECRET_KEY must be set when COACHBOARD_ENV=production.')
        secret_key = 'coachboard-development-only-secret-change-me'
        app.logger.warning('SECRET_KEY is not set. Using a development-only fallback.')
    app.secret_key = secret_key

    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    # Do not rewrite the signed session cookie on every background API request.
    # Concurrent responses from a page opened before a team switch can otherwise
    # overwrite the newer team selection with stale session data.
    app.config['SESSION_REFRESH_EACH_REQUEST'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = _env_bool('SESSION_COOKIE_SECURE', runtime in {'production', 'prod'})
    app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'logos')
    app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or (
        'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app.db')
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'connect_args': {'timeout': 15} if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:') else {},
    }

    asset_version = os.environ.get('ASSET_VERSION') or str(int(datetime.now().timestamp()))

    db.init_app(app)
    socketio.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)

    # Register guards before application routes so their before_request handlers
    # protect all later blueprints.
    app.register_blueprint(security_guard_bp)
    app.register_blueprint(coach_usage_bp)
    app.register_blueprint(live_game_write_lock_bp)
    app.register_blueprint(live_game_clock_bp)
    app.register_blueprint(postgame_navigation_bp)

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(roster_bp)
    app.register_blueprint(development_bp)
    app.register_blueprint(live_game_ui_bp)
    app.register_blueprint(live_game_safety_bp)
    app.register_blueprint(gameday_bp)
    app.register_blueprint(game_day_bp)
    app.register_blueprint(rotation_templates_bp)
    app.register_blueprint(pitching_bp)
    app.register_blueprint(scouting_bp)
    app.register_blueprint(team_management_bp)
    app.register_blueprint(live_game_api_bp)
    app.register_blueprint(live_game_bulk_bp)
    app.register_blueprint(live_game_pitching_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(stats_dashboard_bp)
    app.register_blueprint(fair_play_bp)

    from flask_socketio import join_room, leave_room
    from models import TeamMembership

    def _authorized_game_room(game_id):
        if 'logged_in' not in session:
            return None
        username = session.get('username')
        team_id = session.get('team_id')
        if not username or not team_id:
            return None
        user = db.session.query(User).filter(func.lower(User.username) == username.lower()).first()
        if not user:
            return None
        membership = db.session.query(TeamMembership).filter_by(user_id=user.id, team_id=team_id).first()
        if not membership:
            return None
        game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
        if not game:
            return None
        return f"team_{team_id}_game_{game_id}"

    @socketio.on('join_game_room')
    def handle_join_game_room(data):
        try:
            game_id = int((data or {}).get('game_id'))
        except (TypeError, ValueError):
            return {'status': 'error', 'message': 'Invalid game.'}
        room_name = _authorized_game_room(game_id)
        if not room_name:
            return {'status': 'error', 'message': 'Unauthorized.'}
        join_room(room_name)
        return {'status': 'success', 'room': room_name}

    @socketio.on('leave_game_room')
    def handle_leave_game_room(data):
        try:
            game_id = int((data or {}).get('game_id'))
        except (TypeError, ValueError):
            return {'status': 'error', 'message': 'Invalid game.'}
        room_name = _authorized_game_room(game_id)
        if not room_name:
            return {'status': 'error', 'message': 'Unauthorized.'}
        leave_room(room_name)
        return {'status': 'success'}

    @app.template_filter('format_datetime')
    def format_datetime_filter(dt):
        if not dt or not isinstance(dt, (datetime, date)):
            return dt
        if isinstance(dt, datetime):
            # Timestamp columns in CoachBoard are stored as naive UTC. Convert
            # them to the active team's timezone so Last Login/activity-style
            # timestamps do not appear several hours off on a UTC server.
            aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
            tz_name = 'UTC'
            team_id = session.get('team_id')
            if team_id:
                team = db.session.get(Team, team_id)
                if team and team.timezone:
                    tz_name = team.timezone
            try:
                aware = aware.astimezone(zoneinfo.ZoneInfo(tz_name))
            except (zoneinfo.ZoneInfoNotFoundError, ValueError):
                pass
            return aware.strftime('%A, %m/%d/%y, %I:%M %p')
        if isinstance(dt, date):
            return dt.strftime('%A, %m/%d/%y')
        return dt

    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'logged_in' not in session:
                return redirect(url_for('auth.login'))
            return f(*args, **kwargs)
        return decorated_function

    @app.context_processor
    def inject_current_year():
        return {'current_year': datetime.now().year}

    @app.context_processor
    def inject_team_info():
        info = {}
        if 'team_id' in session:
            db.session.expire_all()
            team = db.session.get(Team, session['team_id'])
            info['current_team'] = team

            if 'username' in session:
                from models import TeamMembership
                user_teams = db.session.query(Team).join(TeamMembership).join(User).filter(func.lower(User.username) == func.lower(session['username'])).all()
                info['available_teams'] = user_teams

        return info

    @app.context_processor
    def inject_css_version():
        return {'css_version': asset_version}

    @app.context_processor
    def inject_current_year_and_timestamp():
        return {
            'current_year': datetime.now().year,
            'current_year_timestamp': asset_version
        }

    @app.route('/')
    @login_required
    def home():
        user = db.session.query(User).filter_by(username=session['username']).first()
        team = db.session.get(Team, session.get('team_id')) if session.get('team_id') else None

        if not user or not team:
            flash('User or team not found.', 'danger')
            return redirect(url_for('auth.login'))

        all_tabs = {'overview': 'Overview', 'roster': 'Roster', 'player_development': 'Player Development', 'lineups': 'Lineup Templates', 'pitching': 'Pitching', 'scouting_list': 'Scouting List', 'rotations': 'Rotation Templates', 'games': 'Schedule', 'collaboration': 'Coaches Log', 'practice_plan': 'Practice Plan', 'signs': 'Signs', 'stats': 'Stats'}
        default_tab_order = list(all_tabs.keys())

        final_tab_order = []
        try:
            user_tab_order = json.loads(user.tab_order or '[]')
            if not isinstance(user_tab_order, list) or not user_tab_order:
                final_tab_order = default_tab_order
            else:
                final_tab_order = [tab for tab in user_tab_order if tab in all_tabs]
                for tab in default_tab_order:
                    if tab not in final_tab_order:
                        final_tab_order.append(tab)
        except (json.JSONDecodeError, TypeError):
            final_tab_order = default_tab_order

        response = make_response(render_template('index.html',
                               session=session,
                               tab_order=final_tab_order,
                               all_tabs=all_tabs))

        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    @app.route('/manifest.json')
    def serve_manifest():
        return send_from_directory('static', 'manifest.json')

    return app
