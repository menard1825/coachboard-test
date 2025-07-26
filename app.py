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
# MODIFIED: Import from the new utils.py file
from utils import (
    get_pitching_rules_for_team, calculate_cumulative_pitching_stats,
    calculate_cumulative_position_stats, calculate_pitch_count_summary, PITCHING_RULES
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
            pitching_outings = db.query(PitchingOuting).filter_by(team_id=user.team_id).all()
            
            pitcher_names = sorted([p.name for p in roster_players if p.pitcher_role != 'Not a Pitcher'])
            cumulative_pitching_data = {name: calculate_cumulative_pitching_stats(name, pitching_outings) for name in pitcher_names}

            cumulative_position_data = calculate_cumulative_position_stats(roster_players, lineups)
            
            all_tabs = {'roster': 'Roster', 'player_development': 'Player Development', 'lineups': 'Lineups', 'pitching': 'Pitching Log', 'scouting_list': 'Scouting List', 'rotations': 'Rotations', 'games': 'Games', 'collaboration': 'Coaches Log', 'practice_plan': 'Practice Plan', 'signs': 'Signs', 'stats': 'Stats'}

            return render_template('index.html',
                                   session=session,
                                   roster_players=roster_players,
                                   cumulative_position_data=cumulative_position_data,
                                   cumulative_pitching_data=cumulative_pitching_data,
                                   tab_order=json.loads(user.tab_order or "[]"),
                                   all_tabs=all_tabs
                                   )
        finally:
            db.close()

    @app.route('/get_app_data')
    @login_required
    def get_app_data():
        db = SessionLocal()
        try:
            team_id = session['team_id']
            user = db.query(User).filter_by(username=session['username']).first()
            team = db.query(Team).filter_by(id=team_id).first()

            # --- Data Queries ---
            roster_db = db.query(Player).filter_by(team_id=team_id).all()
            roster = [p.to_dict() for p in roster_db]
            lineups = [l.to_dict() for l in db.query(Lineup).filter_by(team_id=team_id).all()]
            pitching_outings_db = db.query(PitchingOuting).filter_by(team_id=team_id).all()
            pitching_outings = [po.to_dict() for po in pitching_outings_db]
            scouted_players = db.query(ScoutedPlayer).filter_by(team_id=team_id).all()
            rotations = [r.to_dict() for r in db.query(Rotation).filter_by(team_id=team_id).all()]
            games = [g.to_dict() for g in db.query(Game).filter_by(team_id=team_id).all()]
            collaboration_notes = db.query(CollaborationNote).filter_by(team_id=team_id).all()
            practice_plans_q = db.query(PracticePlan).filter_by(team_id=team_id).options(joinedload(PracticePlan.tasks)).all()
            player_dev_focuses = db.query(PlayerDevelopmentFocus).filter_by(team_id=team_id).all()
            signs = [s.to_dict() for s in db.query(Sign).filter_by(team_id=team_id).all()]
            
            # --- Data Processing ---
            player_dev_by_name = {}
            for p in roster:
                player_dev_by_name[p['name']] = []
            
            for focus in player_dev_focuses:
                player = db.query(Player).filter_by(id=focus.player_id).first()
                if player and player.name in player_dev_by_name:
                    player_dev_by_name[player.name].append({
                        'id': focus.id, 'type': 'Development', 'subtype': focus.skill_type.capitalize(),
                        'text': focus.focus, 'status': focus.status, 'notes': focus.notes,
                        'date': focus.created_date, 'completed_date': focus.completed_date, 'author': focus.author
                    })
            
            rules = get_pitching_rules_for_team(team)
            pitch_count_summary = calculate_pitch_count_summary(roster_db, pitching_outings_db, rules)

            full_data = {
                'roster': roster,
                'lineups': lineups,
                'pitching': pitching_outings,
                'scouting_list': {
                    'targets': [sp.to_dict() for sp in scouted_players if sp.list_type == 'targets'],
                    'committed': [sp.to_dict() for sp in scouted_players if sp.list_type == 'committed'],
                    'not_interested': [sp.to_dict() for sp in scouted_players if sp.list_type == 'not_interested']
                },
                'rotations': rotations,
                'games': games,
                'collaboration_notes': {
                    'team_notes': [cn.to_dict() for cn in collaboration_notes if cn.note_type == 'team_notes'],
                    'player_notes': [cn.to_dict() for cn in collaboration_notes if cn.note_type == 'player_notes']
                },
                'practice_plans': [
                    {**p.to_dict(), 'tasks': [t.to_dict() for t in p.tasks]} for p in practice_plans_q
                ],
                'player_development': player_dev_by_name,
                'signs': signs
            }

            return jsonify({
                'full_data': full_data,
                'player_order': json.loads(user.player_order or "[]"),
                'session': {'username': session.get('username'), 'role': session.get('role')},
                'pitch_count_summary': pitch_count_summary
            })
        finally:
            db.close()
        
    @app.route('/manifest.json')
    def serve_manifest():
        return send_from_directory('static', 'manifest.json')

    @app.route('/stats')
    @login_required
    def stats_page():
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