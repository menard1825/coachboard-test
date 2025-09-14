import os
import json
import logging
from logging.handlers import RotatingFileHandler
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
from flask_wtf.csrf import CSRFProtect
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
from blueprints.gameday import gameday_bp
from blueprints.pitching import pitching_bp
from blueprints.scouting import scouting_bp
from blueprints.team_management import team_management_bp
from blueprints.api import api_bp

# --- ROLE CONSTANTS ---
SUPER_ADMIN = 'Super Admin'
HEAD_COACH = 'Head Coach'


def create_app():
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__)

    # Securely configure the secret key
    secret_key = os.environ.get('SECRET_KEY')
    is_production = os.environ.get('FLASK_ENV') == 'production'

    if is_production and not secret_key:
        raise ValueError("No SECRET_KEY set for production application")

    app.secret_key = secret_key or 'a-fallback-secret-key-for-development'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'logos')
    app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['WTF_CSRF_ENABLED'] = True

    # Initialize extensions with the app
    csrf = CSRFProtect(app)
    db.init_app(app)
    socketio.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(roster_bp)
    app.register_blueprint(development_bp)
    app.register_blueprint(gameday_bp)
    app.register_blueprint(pitching_bp)
    app.register_blueprint(scouting_bp)
    app.register_blueprint(team_management_bp)
    app.register_blueprint(api_bp)

    # --- Custom Jinja Filter for Date/Time Formatting ---
    @app.template_filter('format_datetime')
    def format_datetime_filter(s):
        if not s:
            return s

        dt = None
        if isinstance(s, (datetime, date)):
            dt = s
        elif isinstance(s, str):
            try:
                # Handle the ISO format string
                dt = datetime.fromisoformat(s)
            except ValueError:
                # If parsing fails, return the original string
                return s
        else:
            return s

        if not dt:
            return s

        # If the time is midnight, it was likely just a date entry, so only show the date.
        if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
            return dt.strftime('%A, %m/%d/%y')

        return dt.strftime('%A, %m/%d/%y, %I:%M %p')

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
        return {'current_year': datetime.utcnow().year}

    @app.context_processor
    def inject_team_info():
        if 'team_id' in session:
            db.session.expire_all()
            team = db.session.get(Team, session['team_id'])
            return {'current_team': team}
        return {}

    @app.context_processor
    def inject_css_version():
        return {'css_version': datetime.utcnow().strftime('%Y%m%d%H%M%S')}

    @app.context_processor
    def inject_current_year_and_timestamp():
        return {
            'current_year': datetime.utcnow().year,
            'current_year_timestamp': datetime.utcnow().timestamp()
        }

    # --- CORE APP ROUTES ---
    @app.route('/')
    @login_required
    def home():
        user = db.session.query(User).options(joinedload(User.team)).filter_by(username=session['username']).first()
        if not user or not user.team:
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

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(os.path.join(app.root_path, 'static'),
                               'logo.png', mimetype='image/png')

    @app.route('/manifest.json')
    def serve_manifest():
        return send_from_directory('static', 'manifest.json')


    @app.errorhandler(413)
    def request_entity_too_large(error):
        flash('The uploaded file is too large. Please upload a file smaller than 2MB.', 'danger')
        # Redirect to the admin settings page, as that's where the upload happens
        return redirect(url_for('admin.admin_settings'))

    # --- Production Logging ---
    if not app.debug:
        if not os.path.exists('logs'):
            os.mkdir('logs')
        file_handler = RotatingFileHandler('logs/app.log', maxBytes=10240, backupCount=10)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('CoachBoard startup')

    return app