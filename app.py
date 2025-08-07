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

def model_to_dict(obj):
    """Converts a SQLAlchemy model instance into a dictionary."""
    if obj is None:
        return None

    d = {}
    for column in obj.__table__.columns:
        val = getattr(obj, column.name)
        if isinstance(val, (datetime, date)):
            # Format dates and datetimes as 'YYYY-MM-DD'
            d[column.name] = val.strftime('%Y-%m-%d')
        else:
            d[column.name] = val
    return d

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
                final_tab_order = user_tab_order
                for tab in default_tab_order:
                    if tab not in final_tab_order:
                        final_tab_order.append(tab)
        except (json.JSONDecodeError, TypeError):
            final_tab_order = default_tab_order

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
        team_id = session['team_id']
        user = db.session.query(User).filter_by(username=session['username']).first()
        team = db.session.get(Team, team_id)

        roster_db = db.session.query(Player).filter_by(team_id=team_id).all()
        lineups_db = db.session.query(Lineup).filter_by(team_id=team_id).all()
        pitching_outings_db = db.session.query(PitchingOuting).filter_by(team_id=team_id).all()
        scouted_players = db.session.query(ScoutedPlayer).filter_by(team_id=team_id).all()
        rotations_db = db.session.query(Rotation).filter_by(team_id=team_id).all()
        games = db.session.query(Game).filter_by(team_id=team_id).all()
        collaboration_notes = db.session.query(CollaborationNote).filter_by(team_id=team_id).all()
        practice_plans_q = db.session.query(PracticePlan).filter_by(team_id=team_id).options(joinedload(PracticePlan.tasks), joinedload(PracticePlan.absences)).all()
        player_dev_focuses = db.session.query(PlayerDevelopmentFocus).filter_by(team_id=team_id).all()
        signs = db.session.query(Sign).filter_by(team_id=team_id).all()
        
        player_dev_by_name = {p.name: [] for p in roster_db}
        player_id_to_name = {p.id: p.name for p in roster_db}
        
        for focus in player_dev_focuses:
            player_name = player_id_to_name.get(focus.player_id)
            if player_name:
                focus_dict = model_to_dict(focus)
                focus_dict.update({
                    'type': 'Development',
                    'subtype': focus.skill_type.capitalize(),
                    'text': focus.focus,
                    'date': focus.created_date.strftime('%Y-%m-%d')
                })
                player_dev_by_name[player_name].append(focus_dict)

        rules = get_pitching_rules_for_team(team)
        pitch_count_summary = calculate_pitch_count_summary(roster_db, pitching_outings_db, rules)

        practice_plans_list = []
        for p in practice_plans_q:
            plan_dict = model_to_dict(p)
            plan_dict['tasks'] = [model_to_dict(t) for t in p.tasks]
            plan_dict['absent_player_ids'] = [a.player_id for a in p.absences]
            practice_plans_list.append(plan_dict)

        full_data = {
            'roster': [model_to_dict(p) for p in roster_db],
            'lineups': [model_to_dict(l) for l in lineups_db],
            'pitching': [model_to_dict(po) for po in pitching_outings_db],
            'scouting_list': {
                'targets': [model_to_dict(sp) for sp in scouted_players if sp.list_type == 'targets'],
                'committed': [model_to_dict(sp) for sp in scouted_players if sp.list_type == 'committed'],
                'not_interested': [model_to_dict(sp) for sp in scouted_players if sp.list_type == 'not_interested']
            },
            'rotations': [model_to_dict(r) for r in rotations_db],
            'games': [model_to_dict(g) for g in games],
            'collaboration_notes': {
                'team_notes': [model_to_dict(cn) for cn in collaboration_notes if cn.note_type == 'team_notes'],
                'player_notes': [model_to_dict(cn) for cn in collaboration_notes if cn.note_type == 'player_notes']
            },
            'practice_plans': practice_plans_list,
            'player_development': player_dev_by_name,
            'signs': [model_to_dict(s) for s in signs]
        }

        return jsonify({
            'full_data': full_data,
            'player_order': user.player_order or [],
            'session': {'username': session.get('username'), 'role': session.get('role')},
            'pitch_count_summary': pitch_count_summary
        })

    return app
