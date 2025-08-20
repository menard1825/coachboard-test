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
    calculate_cumulative_position_stats, calculate_pitch_count_summary,
    model_to_dict, pitching_outing_to_dict
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
    app.secret_key = 'xXxG#fjs72d_!z921!kJjkjsd123kfj3FJ!*kfdjf8s!jf9jKJJJd'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'logos')
    app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize extensions with the app
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
        if 'team_id' in session:
            db.session.expire_all()
            team = db.session.get(Team, session['team_id'])
            return {'current_team': team}
        return {}

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
        user = db.session.query(User).options(joinedload(User.team)).filter_by(username=session['username']).first()
        if not user or not user.team:
            flash('User or team not found.', 'danger')
            return redirect(url_for('auth.login'))

        all_tabs = {'roster': 'Roster', 'player_development': 'Player Development', 'lineups': 'Lineups', 'pitching': 'Pitching Log', 'scouting_list': 'Scouting List', 'rotations': 'Rotations', 'games': 'Games', 'collaboration': 'Coaches Log', 'practice_plan': 'Practice Plan', 'signs': 'Signs', 'stats': 'Stats'}
        default_tab_order = list(all_tabs.keys())

        final_tab_order = []
        try:
            user_tab_order = json.loads(user.tab_order or '[]')
            if not isinstance(user_tab_order, list) or not user_tab_order:
                final_tab_order = default_tab_order
            else:
                # FIX: Check for and flatten corrupted nested list structure
                if any(isinstance(i, list) for i in user_tab_order):
                    flat_list = [item for sublist in user_tab_order for item in sublist if isinstance(item, str)]
                    # Deduplicate while preserving order
                    seen = set()
                    final_tab_order = [x for x in flat_list if not (x in seen or seen.add(x))]
                    user.tab_order = json.dumps(final_tab_order)
                    db.session.commit()
                else:
                    final_tab_order = user_tab_order

                # Ensure all default tabs are present
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