import os
import json
from flask import Flask, render_template, session, jsonify, send_from_directory, redirect, url_for, flash, make_response
from datetime import datetime, timedelta, date
from functools import wraps
from sqlalchemy.orm import joinedload
from sqlalchemy import func

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
from blueprints.pitching import pitching_bp
from blueprints.scouting import scouting_bp
from blueprints.team_management import team_management_bp
from blueprints.api import api_bp
from blueprints.live_game_api import live_game_api_bp
from blueprints.live_game_bulk_api import live_game_bulk_bp
from blueprints.live_game_safety import live_game_safety_bp

# --- ROLE CONSTANTS ---
SUPER_ADMIN = 'Super Admin'
HEAD_COACH = 'Head Coach'


def create_app():
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY', 'a-fallback-secret-key-for-development')
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'logos')
    app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions with the app
    db.init_app(app)
    socketio.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)

    # Register Blueprints. The authoritative live-game API must be registered
    # before the legacy /api blueprint because both temporarily expose the
    # same GET /api/live-game/<game_id>/state URL during this transition.
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(roster_bp)
    app.register_blueprint(development_bp)
    app.register_blueprint(live_game_ui_bp)
    app.register_blueprint(live_game_safety_bp)
    app.register_blueprint(gameday_bp)
    app.register_blueprint(pitching_bp)
    app.register_blueprint(scouting_bp)
    app.register_blueprint(team_management_bp)
    app.register_blueprint(live_game_api_bp)
    app.register_blueprint(live_game_bulk_bp)
    app.register_blueprint(api_bp)

    # --- SocketIO Handlers ---
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

    # --- Custom Jinja Filter for Date/Time Formatting ---
    @app.template_filter('format_datetime')
    def format_datetime_filter(dt):
        if not dt or not isinstance(dt, (datetime, date)):
            return dt
        if isinstance(dt, datetime):
            return dt.strftime('%A, %m/%d/%y, %I:%M %p')
        if isinstance(dt, date):
            return dt.strftime('%A, %m/%d/%y')
        return dt

    # --- Decorators & Context Processors ---
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

            # Add list of available teams for the current user for switching
            if 'username' in session:
                from models import TeamMembership
                user_teams = db.session.query(Team).join(TeamMembership).join(User).filter(func.lower(User.username) == func.lower(session['username'])).all()
                info['available_teams'] = user_teams

        return info

    @app.context_processor
    def inject_css_version():
        return {'css_version': datetime.now().strftime('%Y%m%d%H%M%S')}

    @app.context_processor
    def inject_current_year_and_timestamp():
        return {
            'current_year': datetime.now().year,
            'current_year_timestamp': datetime.now().timestamp()
        }

    # --- CORE APP ROUTES ---
    @app.route('/')
    @login_required
    def home():
        user = db.session.query(User).filter_by(username=session['username']).first()
        team = db.session.get(Team, session.get('team_id')) if session.get('team_id') else None

        if not user or not team:
            flash('User or team not found.', 'danger')
            return redirect(url_for('auth.login'))

        all_tabs = {'overview': 'Overview', 'roster': 'Roster', 'player_development': 'Player Development', 'lineups': 'Lineup Templates', 'pitching': 'Pitching Log', 'scouting_list': 'Scouting List', 'rotations': 'Rotation Templates', 'games': 'Games', 'collaboration': 'Coaches Log', 'practice_plan': 'Practice Plan', 'signs': 'Signs', 'stats': 'Stats'}
        default_tab_order = list(all_tabs.keys())

        final_tab_order = []
        try:
            user_tab_order = json.loads(user.tab_order or '[]')
            if not isinstance(user_tab_order, list) or not user_tab_order:
                final_tab_order = default_tab_order
            else:
                final_tab_order = user_tab_order
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
