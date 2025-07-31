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
from blueprints.gameday import gameday_bp
from blueprints.pitching import pitching_bp
from blueprints.scouting import scouting_bp
from blueprints.team_management import team_management_bp

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

    # --- Custom Jinja Filter for Date/Time Formatting ---
    @app.template_filter('format_datetime')
    def format_datetime_filter(s):
        if not s or s == 'Never':
            return s
        try:
            # Handle full datetime strings like '2025-07-24 23:55'
            dt = datetime.strptime(s, '%Y-%m-%d %H:%M')
            return dt.strftime('%A, %m/%d/%y, %I:%M %p')
        except ValueError:
            try:
                # Handle date-only strings like '2025-07-24'
                dt = datetime.strptime(s, '%Y-%m-%d')
                return dt.strftime('%A, %m/%d/%y')
            except ValueError:
                return s # Return original string if format is unexpected

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
            # NEW: Expire all objects in the session to force a fresh load from DB
            db.session.expire_all()
            team = db.session.get(Team, session['team_id'])
            return {'current_team': team}
        return {}

    # NEW: Context processor for CSS version
    @app.context_processor
    def inject_css_version():
        # Use a timestamp to force browser to reload CSS on server restart or significant change
        # In a production environment, you might use a build hash for better cache control
        return {'css_version': datetime.now().strftime('%Y%m%d%H%M%S')}

    # NEW: Context processor for timestamp for cache-busting links
    @app.context_processor
    def inject_current_year_and_timestamp():
        return {
            'current_year': datetime.now().year,
            'current_year_timestamp': datetime.now().timestamp() # New timestamp for cache-busting links
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

        # *** MODIFICATION START: More robust tab order handling ***
        final_tab_order = []
        try:
            user_tab_order = json.loads(user.tab_order or '[]')
            # If the saved order is not a list or is empty, reset to default
            if not isinstance(user_tab_order, list) or not user_tab_order:
                final_tab_order = default_tab_order
            else:
                # Use the user's order, but ensure all default tabs are present
                final_tab_order = user_tab_order
                for tab in default_tab_order:
                    if tab not in final_tab_order:
                        final_tab_order.append(tab)
        except (json.JSONDecodeError, TypeError):
            # If JSON is corrupted for any reason, reset to default
            final_tab_order = default_tab_order
        # *** MODIFICATION END ***

        roster_players = db.session.query(Player).filter_by(team_id=user.team_id).all()
        rotations = db.session.query(Rotation).filter_by(team_id=user.team_id).all()
        pitching_outings = db.session.query(PitchingOuting).filter_by(team_id=user.team_id).all()

        pitcher_names = sorted([p.name for p in roster_players if p.pitcher_role != 'Not a Pitcher'])
        cumulative_pitching_data = {name: calculate_cumulative_pitching_stats(name, pitching_outings) for name in pitcher_names}
        cumulative_position_data = calculate_cumulative_position_stats(roster_players, rotations)

        game_absences = db.session.query(PlayerGameAbsence.player_id, func.count(PlayerGameAbsence.id)).filter_by(team_id=user.team_id).group_by(PlayerGameAbsence.player_id).all()
        practice_absences = db.session.query(PlayerPracticeAbsence.player_id, func.count(PlayerPracticeAbsence.id)).filter_by(team_id=user.team_id).group_by(PlayerPracticeAbsence.player_id).all()

        attendance_stats = {p.id: {'name': p.name, 'games_missed': 0, 'practices_missed': 0} for p in roster_players}
        for player_id, count in game_absences:
            if player_id in attendance_stats:
                attendance_stats[player_id]['games_missed'] = count
        for player_id, count in practice_absences:
            if player_id in attendance_stats:
                attendance_stats[player_id]['practices_missed'] = count

        response = make_response(render_template('index.html',
                               session=session,
                               roster_players=roster_players,
                               cumulative_position_data=cumulative_position_data,
                               cumulative_pitching_data=cumulative_pitching_data,
                               attendance_stats=attendance_stats,
                               tab_order=final_tab_order,
                               all_tabs=all_tabs))

        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    @app.route('/manifest.json')
    def serve_manifest():
        return send_from_directory('static', 'manifest.json')

    @app.route('/get_app_data')
    @login_required
    def get_app_data():
        print("DEBUG: Attempting to load app data via /get_app_data")

        team_id = session['team_id']
        user = db.session.query(User).filter_by(username=session['username']).first()
        team = db.session.get(Team, team_id)

        # --- Data Queries ---
        roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
        lineups = db.session.query(Lineup).filter_by(team_id=team_id).all()
        pitching_outings_db = db.session.query(PitchingOuting).filter_by(team_id=team_id).all()
        scouted_players = db.session.query(ScoutedPlayer).filter_by(team_id=team_id).all()
        rotations = db.session.query(Rotation).filter_by(team_id=team_id).all()
        games = db.session.query(Game).filter_by(team_id=team_id).all()
        collaboration_notes = db.session.query(CollaborationNote).filter_by(team_id=team_id).all()
        practice_plans_q = db.session.query(PracticePlan).filter_by(team_id=team_id).options(joinedload(PracticePlan.tasks), joinedload(PracticePlan.absences)).all()
        player_dev_focuses = db.session.query(PlayerDevelopmentFocus).filter_by(team_id=team_id).all()
        signs = db.session.query(Sign).filter_by(team_id=team_id).all()
        
        # --- Data Processing ---
        player_dev_by_name = {p.name: [] for p in roster_db}
        player_id_to_name = {p.id: p.name for p in roster_db}
        
        for focus in player_dev_focuses:
            player_name = player_id_to_name.get(focus.player_id)
            if player_name:
                player_dev_by_name[player_name].append({
                    'id': focus.id, 'type': 'Development', 'subtype': focus.skill_type.capitalize(),
                    'text': focus.focus, 'status': focus.status, 'notes': focus.notes,
                    'date': focus.created_date, 'completed_date': focus.completed_date, 'author': focus.author
                })
        
        rules = get_pitching_rules_for_team(team)
        pitch_count_summary = calculate_pitch_count_summary(roster_db, pitching_outings_db, rules)

        practice_plans_list = []
        for p in practice_plans_q:
            plan_dict = {c.name: getattr(p, c.name) for c in p.__table__.columns}
            plan_dict['tasks'] = [{c.name: getattr(t, c.name) for c in t.__table__.columns} for t in p.tasks]
            plan_dict['absent_player_ids'] = [a.player_id for a in p.absences]
            practice_plans_list.append(plan_dict)

        full_data = {
            'roster': [{c.name: getattr(p, c.name) for c in p.__table__.columns} for p in roster_db],
            'lineups': [{c.name: getattr(l, c.name) for c in l.__table__.columns} for l in lineups],
            'pitching': [{c.name: getattr(po, c.name) for c in po.__table__.columns} for po in pitching_outings_db],
            'scouting_list': {
                'targets': [{c.name: getattr(sp, c.name) for c in sp.__table__.columns} for sp in scouted_players if sp.list_type == 'targets'],
                'committed': [{c.name: getattr(sp, c.name) for c in sp.__table__.columns} for sp in scouted_players if sp.list_type == 'committed'],
                'not_interested': [{c.name: getattr(sp, c.name) for c in sp.__table__.columns} for sp in scouted_players if sp.list_type == 'not_interested']
            },
            'rotations': [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rotations],
            'games': [{c.name: getattr(g, c.name) for c in g.__table__.columns} for g in games],
            'collaboration_notes': {
                'team_notes': [{c.name: getattr(cn, c.name) for c in cn.__table__.columns} for cn in collaboration_notes if cn.note_type == 'team_notes'],
                'player_notes': [{c.name: getattr(cn, c.name) for c in cn.__table__.columns} for cn in collaboration_notes if cn.note_type == 'player_notes']
            },
            'practice_plans': practice_plans_list,
            'player_development': player_dev_by_name,
            'signs': [{c.name: getattr(s, c.name) for c in s.__table__.columns} for s in signs]
        }

        return jsonify({
            'full_data': full_data,
            'player_order': json.loads(user.player_order or "[]"),
            'session': {'username': session.get('username'), 'role': session.get('role')},
            'pitch_count_summary': pitch_count_summary
        })

    return app

def allowed_file(filename):
    """Check if the filename has an allowed extension."""
    app = Flask(__name__)
    app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']
