import os
import json
from flask import Flask, render_template, session, jsonify, send_from_directory, redirect, url_for, flash
from datetime import datetime, timedelta, date
from functools import wraps
from sqlalchemy.orm import joinedload, selectinload

# Local Imports
from db import SessionLocal
from models import (
    User, Team, Player, Lineup, PitchingOuting, ScoutedPlayer,
    Rotation, Game, CollaborationNote, PracticePlan, PlayerDevelopmentFocus, Sign
)
from extensions import socketio

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

    # Initialize extensions with the app
    socketio.init_app(app)

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(roster_bp)
    app.register_blueprint(development_bp)
    app.register_blueprint(gameday_bp)
    app.register_blueprint(pitching_bp)
    app.register_blueprint(scouting_bp)
    app.register_blueprint(team_management_bp)

    # --- PITCHING RULES (App-level config) ---
    PITCHING_RULES = {
        'USSSA': {
            'default': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
            '11U': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        }
    }

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
            db = SessionLocal()
            try:
                team = db.query(Team).filter_by(id=session['team_id']).first()
                return {'current_team': team}
            finally:
                db.close()
        return {}

    # --- DATA UTILITY FUNCTIONS ---
    with app.app_context():
        def get_pitching_rules_for_team(team):
            rule_set_name = getattr(team, 'pitching_rule_set', 'USSSA') or 'USSSA'
            age_group = getattr(team, 'age_group', 'default') or 'default'
            rule_set = PITCHING_RULES.get(rule_set_name, PITCHING_RULES['USSSA'])
            return rule_set.get(age_group, rule_set.get('default'))

        def calculate_cumulative_pitching_stats(pitcher_name, all_outings):
            stats = {'total_innings_pitched': 0.0, 'total_pitches_thrown': 0, 'appearances': 0}
            for outing in all_outings:
                if outing.pitcher == pitcher_name:
                    try:
                        stats['total_innings_pitched'] += float(outing.innings or 0.0)
                        stats['total_pitches_thrown'] += int(outing.pitches or 0)
                        stats['appearances'] += 1
                    except (ValueError, TypeError):
                        continue
            stats['total_innings_pitched'] = round(stats['total_innings_pitched'], 1)
            return stats

        def calculate_cumulative_position_stats(roster_players, lineups):
            stats = {player.name: {} for player in roster_players}
            for lineup in lineups:
                try:
                    positions = json.loads(lineup.lineup_positions or "[]")
                    for item in positions:
                        if item.get('name') in stats and item.get('position'):
                            pos = item['position']
                            stats[item['name']][pos] = stats[item['name']].get(pos, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    continue
            return stats
    
    # --- CORE APP ROUTES ---
    @app.route('/')
    @login_required
    def home():
        db = SessionLocal()
        try:
            user = db.query(User).options(joinedload(User.team)).filter_by(username=session['username']).first()
            if not user or not user.team:
                flash('User or team not found.', 'danger')
                return redirect(url_for('auth.login'))

            roster_players = db.query(Player).filter_by(team_id=user.team_id).all()
            lineups = db.query(Lineup).filter_by(team_id=user.team_id).all()
            # ADDED THIS LINE BACK
            pitching_outings = db.query(PitchingOuting).filter_by(team_id=user.team_id).all()
            
            # ADDED THESE LINES BACK
            pitcher_names = sorted([p.name for p in roster_players if p.pitcher_role != 'Not a Pitcher'])
            cumulative_pitching_data = {name: calculate_cumulative_pitching_stats(name, pitching_outings) for name in pitcher_names}

            cumulative_position_data = calculate_cumulative_position_stats(roster_players, lineups)
            
            all_tabs = {'roster': 'Roster', 'player_development': 'Player Development', 'lineups': 'Lineups', 'pitching': 'Pitching Log', 'scouting_list': 'Scouting List', 'rotations': 'Rotations', 'games': 'Games', 'collaboration': 'Coaches Log', 'practice_plan': 'Practice Plan', 'signs': 'Signs', 'stats': 'Stats'}

            return render_template('index.html',
                                   session=session,
                                   roster_players=roster_players,
                                   cumulative_position_data=cumulative_position_data,
                                   cumulative_pitching_data=cumulative_pitching_data, # ADDED THIS LINE BACK
                                   tab_order=json.loads(user.tab_order or "[]"),
                                   all_tabs=all_tabs
                                   )
        finally:
            db.close()

    # The rest of the routes and functions are unchanged...
    @app.route('/get_app_data')
    @login_required
    def get_app_data():
        # This will need a similar fix if it powers the stats tab dynamically,
        # but for now, the error is in the initial page load.
        pass
        
    @app.route('/manifest.json')
    def serve_manifest():
        return send_from_directory('static', 'manifest.json')

    @app.route('/stats')
    @login_required
    def stats_page():
        # This page also needs the data
        db = SessionLocal()
        try:
            team_id = session['team_id']
            roster_players = db.query(Player).filter_by(team_id=team_id).all()
            lineups = db.query(Lineup).filter_by(team_id=team_id).all()
            pitching_outings = db.query(PitchingOuting).filter_by(team_id=team_id).all()
            pitcher_names = sorted(list(set(po.pitcher for po in pitching_outings if po.pitcher)))
            
            cumulative_pitching_data = {name: calculate_cumulative_pitching_stats(name, pitching_outings) for name in pitcher_names}
            cumulative_position_data = calculate_cumulative_position_stats(roster_players, lineups)

            return render_template('stats.html',
                                   roster_players=roster_players,
                                   cumulative_pitching_data=cumulative_pitching_data,
                                   cumulative_position_data=cumulative_position_data,
                                   session=session)
        finally:
            db.close()

    return app

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'svg'}