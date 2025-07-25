from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
import json
import os
from datetime import datetime, timedelta, date
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import time
from sqlalchemy import func
import random
import string
import math
from db import SessionLocal
from models import (
    User, Team, Player, Lineup, PitchingOuting, ScoutedPlayer,
    Rotation, Game, CollaborationNote, PracticePlan, PracticeTask,
    PlayerDevelopmentFocus, Sign, PlayerGameAbsence
)
from sqlalchemy import create_engine
from sqlalchemy.inspection import inspect as sqlalchemy_inspect
from sqlalchemy.orm import joinedload, selectinload
from flask_socketio import SocketIO, emit
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'xXxG#fjs72d_!z921!kJjkjsd123kfj3FJ!*kfdjf8s!jf9jKJJJd'

# Set the permanent session lifetime to 30 days
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Configuration for file uploads
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'logos')
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

# --- Pitching Rules Engine ---
# Defines pitching limits and rest requirements based on a rule set and age group.
# rest_thresholds is a list of tuples: (max_pitches, days_of_rest).
# The list must be sorted by pitch count. The last entry is the maximum before needing the next tier of rest.
PITCHING_RULES = {
    'USSSA': {
        'default': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '10U': {'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '11U': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '12U': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '13U': {'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (75, 3)]},
        '14U': {'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (75, 3)]},
    }
    # Future rule sets like 'Little League' can be added here.
}

# --- ROLE CONSTANTS ---
SUPER_ADMIN = 'Super Admin'
HEAD_COACH = 'Head Coach'
ASSISTANT_COACH = 'Assistant Coach'
GAME_CHANGER = 'Game Changer'


# Helper function to check for allowed file extensions
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def check_database_initialized():
    """
    Checks if the database file exists and contains the necessary tables.
    If not, it prints a helpful error message and exits.
    """
    db_path = 'app.db'
    if not os.path.exists(db_path):
        print("="*70)
        print("!!! DATABASE NOT FOUND !!!")
        print(f"The database file '{db_path}' does not exist.")
        print("Please create and initialize it by running the setup script first:")
        print("\n    python init_db.py\n")
        print("="*70)
        exit()

    engine = create_engine(f'sqlite:///{db_path}')
    inspector = sqlalchemy_inspect(engine)
    if not inspector.has_table("users"):
        print("="*70)
        print("!!! DATABASE NOT INITIALIZED !!!")
        print("The database exists, but the 'users' table is missing.")
        print("Please ensure you have run the setup script successfully:")
        print("\n    python init_db.py\n")
        print("="*70)
        exit()

socketio = SocketIO(app)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        if session.get('role') not in [HEAD_COACH, SUPER_ADMIN]:
            flash('You must be a Head Coach or Super Admin to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# This function makes the current year available to all templates
@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}

# This makes the current team's info (like the logo) available on every page.
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

# --- Favicon Route ---
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'logo.png', mimetype='image/png')

# --- AUTHENTICATION ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        db = SessionLocal()
        try:
            username = request.form['username']
            password = request.form['password']

            user = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()

            if user and check_password_hash(user.password_hash, password):
                if user.username.lower() == 'mike1825':
                    user.role = SUPER_ADMIN
                elif user.role == 'Admin':
                    user.role = HEAD_COACH
                elif user.role == 'Coach':
                    user.role = ASSISTANT_COACH

                user.last_login = datetime.now().strftime("%Y-%m-%d %H:%M")
                db.commit()

                session['logged_in'] = True
                session['username'] = user.username
                session['full_name'] = user.full_name or ''
                session['role'] = user.role
                session['team_id'] = user.team_id
                session['player_order'] = json.loads(user.player_order or "[]")
                session.permanent = True
                flash('You were successfully logged in.', 'success')
                return redirect(url_for('home'))
            else:
                flash('Invalid username or password.', 'danger')
        finally:
            db.close()
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('You were successfully logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handles user registration. Users can only join an existing team."""
    if request.method == 'POST':
        db = SessionLocal()
        try:
            username = request.form.get('username')
            full_name = request.form.get('full_name')
            password = request.form.get('password')
            reg_code = request.form.get('registration_code')

            if not all([username, full_name, password, reg_code]):
                flash('All fields are required.', 'danger')
                return redirect(url_for('register'))
            if len(password) < 4:
                flash('Password must be at least 4 characters long.', 'danger')
                return redirect(url_for('register'))
            if db.query(User).filter(func.lower(User.username) == func.lower(username)).first():
                flash('That username is already taken. Please choose another.', 'danger')
                return redirect(url_for('register'))

            team = db.query(Team).filter_by(registration_code=reg_code).first()
            if not team:
                flash('Invalid Registration Code.', 'danger')
                return redirect(url_for('register'))

            is_first_user = db.query(User).filter_by(team_id=team.id).count() == 0
            user_role = HEAD_COACH if is_first_user else ASSISTANT_COACH

            hashed_password = generate_password_hash(password)
            default_tab_keys = ['roster', 'player_development', 'games', 'pitching', 'practice_plan', 'collaboration']

            new_user = User(
                username=username,
                full_name=full_name,
                password_hash=hashed_password,
                role=user_role,
                team_id=team.id,
                tab_order=json.dumps(default_tab_keys),
                player_order=json.dumps([])
            )
            db.add(new_user)
            db.commit()

            session['logged_in'] = True
            session['username'] = new_user.username
            session['full_name'] = new_user.full_name
            session['role'] = new_user.role
            session['team_id'] = new_user.team_id
            session['player_order'] = []
            session.permanent = True

            flash(f'Registration successful! You have joined team "{team.team_name}". Welcome.', 'success')
            return redirect(url_for('home'))

        except Exception as e:
            db.rollback()
            print(f"Registration Error: {e}")
            flash('An error occurred during registration. Please try again.', 'danger')
        finally:
            db.close()

    registration_code = request.args.get('code', '')
    return render_template('register.html', registration_code=registration_code)


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    db = SessionLocal()
    try:
        if request.method == 'POST':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_new_password = request.form.get('confirm_new_password')

            user = db.query(User).filter_by(username=session['username']).first()

            if not user or not check_password_hash(user.password_hash, current_password):
                flash('Your current password was incorrect.', 'danger')
                return redirect(url_for('change_password'))
            if new_password != confirm_new_password:
                flash('New passwords do not match.', 'danger')
                return redirect(url_for('change_password'))
            if len(new_password) < 4:
                flash('New password must be at least 4 characters long.', 'danger')
                return redirect(url_for('change_password'))

            user.password_hash = generate_password_hash(new_password)
            db.commit()

            flash('Your password has been updated successfully!', 'success')
            return redirect(url_for('home'))
        return render_template('change_password.html')
    finally:
        db.close()

@app.route('/rules')
@login_required
def pitching_rules():
    db = SessionLocal()
    try:
        team = db.query(Team).filter_by(id=session['team_id']).first()
        # MODIFIED: Get the specific rule set for the team instead of hardcoding
        rules_for_team = get_pitching_rules_for_team(team)
        return render_template('rules.html', 
                               team=team, 
                               rules=rules_for_team,
                               rule_set_name=team.pitching_rule_set,
                               age_group=team.age_group)
    finally:
        db.close()


def get_pitching_rules_for_team(team):
    """Gets the specific pitching rule set for a team."""
    # Fallback to defaults if settings are not present on the team object
    rule_set_name = getattr(team, 'pitching_rule_set', 'USSSA') or 'USSSA'
    age_group = getattr(team, 'age_group', 'default') or 'default'
    
    rule_set = PITCHING_RULES.get(rule_set_name, PITCHING_RULES['USSSA'])
    return rule_set.get(age_group, rule_set.get('default'))


def get_required_rest_days(pitches, team):
    """Calculates the required rest days based on team's rules."""
    rules = get_pitching_rules_for_team(team)
    rest_thresholds = rules['rest_thresholds']
    
    # Iterate through the sorted thresholds to find the required rest
    for max_pitches, rest_days in rest_thresholds:
        if pitches <= max_pitches:
            return rest_days
            
    # If pitches exceed all thresholds, return the max rest days + 1
    # (e.g., for USSSA 12U, throwing 66+ requires 4 days of rest)
    return rest_thresholds[-1][1] + 1


def calculate_pitcher_availability(pitcher_name, all_outings, team):
    """
    Calculates a pitcher's availability by summing all pitches on their most recent
    day of pitching to determine rest.
    """
    today = date.today()
    pitcher_outings = [o for o in all_outings if o.pitcher == pitcher_name]

    if not pitcher_outings:
        return {'status': 'Available', 'next_available': 'Today'}

    # Group outings by date
    outings_by_date = {}
    for outing in pitcher_outings:
        try:
            outing_date = datetime.strptime(outing.date, '%Y-%m-%d').date()
            if outing_date not in outings_by_date:
                outings_by_date[outing_date] = 0
            outings_by_date[outing_date] += int(outing.pitches)
        except (ValueError, TypeError):
            continue

    if not outings_by_date:
        return {'status': 'Available', 'next_available': 'Today'}
        
    # Find the most recent day the pitcher threw
    most_recent_pitching_date = max(outings_by_date.keys())
    total_pitches_on_last_day = outings_by_date[most_recent_pitching_date]

    # Calculate rest based on the total pitches for that day and team rules
    rest_days_needed = get_required_rest_days(total_pitches_on_last_day, team)
    
    # The first available day is the day after the rest period concludes
    next_available_date = most_recent_pitching_date + timedelta(days=rest_days_needed + 1)

    if today >= next_available_date:
        return {'status': 'Available', 'next_available': 'Today'}
    else:
        return {'status': 'Resting', 'next_available': next_available_date.strftime('%Y-%m-%d')}


def calculate_pitch_counts(pitcher_name, all_outings, team):
    """Calculates daily, weekly, and yearly pitch counts."""
    today = date.today()
    current_year = today.year
    start_of_week = today - timedelta(days=today.weekday()) # Monday
    
    counts = {'daily': 0, 'weekly': 0, 'cumulative_year': 0}
    
    for outing in all_outings:
        if outing.pitcher == pitcher_name:
            try:
                outing_date = datetime.strptime(outing.date, '%Y-%m-%d').date()
                pitches = int(outing.pitches)
                
                if outing_date.year == current_year:
                    counts['cumulative_year'] += pitches
                if outing_date >= start_of_week:
                    counts['weekly'] += pitches
                if outing_date == today:
                    counts['daily'] += pitches
            except (ValueError, TypeError):
                continue
                
    rules = get_pitching_rules_for_team(team)
    counts['max_daily'] = rules.get('max_daily', 85)
    counts['pitches_remaining_today'] = max(0, counts['max_daily'] - counts['daily'])
    
    return counts


def calculate_cumulative_pitching_stats(pitcher_name, all_outings):
    """
    Calculates cumulative pitching statistics for a given pitcher.
    """
    total_innings = 0.0
    total_pitches = 0
    appearances = 0

    for outing in all_outings:
        if outing.pitcher == pitcher_name:
            try:
                innings = float(outing.innings) if outing.innings is not None else 0.0
                pitches = int(outing.pitches) if outing.pitches is not None else 0

                total_innings += innings
                total_pitches += pitches
                appearances += 1
            except (ValueError, TypeError):
                continue
    return {
        'total_innings_pitched': round(total_innings, 1),
        'total_pitches_thrown': total_pitches,
        'appearances': appearances
    }

def calculate_cumulative_position_stats(roster_players, lineups):
    """
    Calculates cumulative games played at each position for all players.
    """
    player_position_stats = {}
    for player in roster_players:
        player_position_stats[player.name] = {}

    for lineup in lineups:
        try:
            # Handle both JSON strings from DB and already-parsed dicts
            if isinstance(lineup.lineup_positions, str):
                lineup_positions = json.loads(lineup.lineup_positions or "[]")
            else:
                lineup_positions = lineup.lineup_positions or []
                
            for item in lineup_positions:
                player_name = item.get('name')
                position = item.get('position')
                if player_name and position:
                    if player_name in player_position_stats:
                        player_position_stats[player_name][position] = player_position_stats[player_name].get(position, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue
    return player_position_stats

# --- Centralized data fetching function ---
def _get_full_team_data(db, team_id, current_user):
    """
    Fetches and structures all data for a given team.
    This function has been refactored for clarity and correctness.
    """
    # Eagerly load related data to prevent N+1 query problems
    team = db.query(Team).options(
        selectinload(Team.users),
        selectinload(Team.players).selectinload(Player.development_focuses),
        selectinload(Team.collaboration_notes),
        selectinload(Team.practice_plans).selectinload(PracticePlan.tasks)
    ).filter_by(id=team_id).first()

    if not team:
        return {}, [], [], []

    # Prepare user display names based on team settings
    user_name_map = {u.username: (u.full_name or u.username) for u in team.users}
    display_full_names = team.display_coach_names
    def get_display_name(username):
        if not username or username == 'N/A': return 'N/A'
        return user_name_map.get(username, username) if display_full_names else username

    # Fetch remaining data that isn't directly on the team object via common relationships
    lineups = db.query(Lineup).filter_by(team_id=team_id).all()
    pitching_outings = db.query(PitchingOuting).filter_by(team_id=team_id).all()
    scouted_players = db.query(ScoutedPlayer).filter_by(team_id=team_id).all()
    rotations = db.query(Rotation).filter_by(team_id=team_id).all()
    games = db.query(Game).filter_by(team_id=team_id).all()
    signs = db.query(Sign).filter_by(team_id=team_id).all()
    
    # Build the player activity log by combining different event types
    player_activity_log = {}
    collaboration_player_notes = [n for n in team.collaboration_notes if n.note_type == 'player_notes']
    
    for player in team.players:
        log_entries = []
        # 1. Development Focuses
        for focus in player.development_focuses:
            log_entries.append({
                'type': 'Development', 'subtype': focus.skill_type, 'id': focus.id,
                'timestamp': f"{focus.created_date} 00:00:00", # Pad for correct sorting
                'date': focus.created_date, 'text': focus.focus, 'notes': focus.notes,
                'author': get_display_name(focus.author), 'status': focus.status,
                'completed_date': focus.completed_date
            })
        # 2. Coach Notes
        for note in collaboration_player_notes:
            if note.player_name == player.name:
                log_entries.append({
                    'type': 'Coach Note', 'subtype': 'Player Log', 'id': note.id,
                    'timestamp': note.timestamp or '1970-01-01 00:00:00',
                    'date': note.timestamp.split(' ')[0] if note.timestamp else 'N/A',
                    'text': note.text, 'notes': None, 'author': get_display_name(note.author),
                    'status': 'active'
                })
        # 3. Lessons
        if player.has_lessons == 'Yes' and player.lesson_focus:
            log_entries.append({
                'type': 'Lessons', 'subtype': 'Private Instruction', 'id': player.id,
                'timestamp': player.notes_timestamp or '1970-01-01 00:00:00',
                'date': player.notes_timestamp.split(' ')[0] if player.notes_timestamp else 'N/A',
                'text': player.lesson_focus, 'notes': None, 'author': 'N/A',
                'status': 'active'
            })
            
        player_activity_log[player.name] = sorted(log_entries, key=lambda x: x.get('timestamp', ''), reverse=True)
    
    # Group scouted players by their list type
    scouting_list_grouped = {'committed': [], 'targets': [], 'not_interested': []}
    for sp in scouted_players:
        if sp.list_type in scouting_list_grouped:
            scouting_list_grouped[sp.list_type].append(sp.to_dict())

    # Final data structure to be sent to the frontend
    app_data = {
        "roster": [p.to_dict() for p in team.players],
        "lineups": [l.to_dict() for l in lineups],
        "pitching": [p.to_dict() for p in pitching_outings],
        "scouting_list": scouting_list_grouped,
        "rotations": [r.to_dict() for r in rotations],
        "games": [g.to_dict() for g in games],
        "settings": team.to_dict(),
        "collaboration_notes": {
            "player_notes": [n.to_dict() for n in collaboration_player_notes],
            "team_notes": [n.to_dict() for n in team.collaboration_notes if n.note_type == 'team_notes']
        },
        "practice_plans": [
            {**pp.to_dict(), "tasks": [t.to_dict() for t in pp.tasks]} for pp in team.practice_plans
        ],
        "player_development": player_activity_log,
        "signs": [s.to_dict() for s in signs]
    }
    return app_data, team.players, lineups, pitching_outings


# --- MAIN AND ADMIN ROUTES ---
@app.route('/')
@login_required
def home():
    db = SessionLocal()
    try:
        user = db.query(User).options(joinedload(User.team)).filter_by(username=session['username'], team_id=session['team_id']).first()
        if not user or not user.team:
            flash('User not found or not associated with a team.', 'danger')
            return redirect(url_for('login'))
        
        app_data, roster_players, lineups, pitching_outings = _get_full_team_data(db, user.team_id, user)
        team = user.team
        
        all_tabs = {'roster': 'Roster', 'player_development': 'Player Development', 'lineups': 'Lineups', 'pitching': 'Pitching Log', 'scouting_list': 'Scouting List', 'rotations': 'Rotations', 'games': 'Games', 'collaboration': 'Coaches Log', 'practice_plan': 'Practice Plan', 'signs': 'Signs', 'stats': 'Stats'}
        default_tab_keys = list(all_tabs.keys())
        user_tab_order = json.loads(user.tab_order or "[]") if user.tab_order else default_tab_keys
        for key in default_tab_keys:
            if key not in user_tab_order and key in all_tabs: user_tab_order.append(key)
        user_tab_order = [key for key in user_tab_order if key in all_tabs]

        pitcher_names = sorted([p.name for p in roster_players if p.pitcher_role != 'Not a Pitcher'])
        pitch_count_summary = {}
        for name in pitcher_names:
            counts = calculate_pitch_counts(name, pitching_outings, team)
            availability = calculate_pitcher_availability(name, pitching_outings, team)
            cumulative_stats = calculate_cumulative_pitching_stats(name, pitching_outings)
            pitch_count_summary[name] = {**counts, **availability, **cumulative_stats}
            
        cumulative_pitching_data = {}
        for name, summary in pitch_count_summary.items():
            cumulative_pitching_data[name] = {k: summary[k] for k in ('total_innings_pitched', 'total_pitches_thrown', 'appearances')}

        cumulative_position_data = calculate_cumulative_position_stats(roster_players, lineups)

        return render_template('index.html',
                               data=app_data,
                               session=session,
                               tab_order=user_tab_order,
                               all_tabs=all_tabs,
                               pitch_count_summary=pitch_count_summary,
                               roster_players=roster_players,
                               cumulative_pitching_data=cumulative_pitching_data,
                               cumulative_position_data=cumulative_position_data)
    finally:
        db.close()

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/service-worker.js')
def serve_sw():
    return send_from_directory('static', 'service-worker.js', mimetype='application/javascript')

@app.route('/get_app_data')
@login_required
def get_app_data():
    db = SessionLocal()
    try:
        user = db.query(User).options(joinedload(User.team)).filter_by(username=session['username'], team_id=session['team_id']).first()
        if not user or not user.team:
            return jsonify({'status': 'error', 'message': 'User not found or not associated with a team.'}), 404
        
        app_data, roster_players, _, pitching_outings = _get_full_team_data(db, user.team_id, user)
        team = user.team
        
        player_order = session.get('player_order', [p['name'] for p in app_data.get('roster', [])])

        pitcher_names = sorted([p['name'] for p in app_data['roster'] if p['pitcher_role'] != 'Not a Pitcher'])
        pitch_count_summary = {}
        for name in pitcher_names:
            counts = calculate_pitch_counts(name, pitching_outings, team)
            availability = calculate_pitcher_availability(name, pitching_outings, team)
            cumulative_stats = calculate_cumulative_pitching_stats(name, pitching_outings)
            pitch_count_summary[name] = {**counts, **availability, **cumulative_stats}

        app_data_response = {'full_data': app_data, 'player_order': player_order, 'session': {'username': session.get('username'), 'role': session.get('role'), 'full_name': session.get('full_name')}, 'pitch_count_summary': pitch_count_summary}
        return jsonify(app_data_response)
    finally:
        db.close()

# ... (The rest of your routes remain unchanged) ...
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
        cumulative_pitching_data = {}
        for name in pitcher_names:
            cumulative_pitching_data[name] = calculate_cumulative_pitching_stats(name, pitching_outings)
        cumulative_position_data = calculate_cumulative_position_stats(roster_players, lineups)

        return render_template('stats.html',
                               roster_players=roster_players,
                               cumulative_pitching_data=cumulative_pitching_data,
                               cumulative_position_data=cumulative_position_data,
                               session=session)
    finally:
        db.close()

@app.route('/save_tab_order', methods=['POST'])
@login_required
def save_tab_order():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username=session['username']).first()
        if not user: return jsonify({'status': 'error', 'message': 'User not found'}), 404
        new_order = request.json.get('order')
        if not isinstance(new_order, list): return jsonify({'status': 'error', 'message': 'Invalid order format'}), 400
        user.tab_order = json.dumps(new_order)
        db.commit()
        socketio.emit('data_updated', {'message': 'Tab order updated.'})
        return jsonify({'status': 'success', 'message': 'Tab order saved.'})
    finally:
        db.close()

@app.route('/admin/users')
@admin_required
def user_management():
    db = SessionLocal()
    try:
        teams = []
        if session.get('role') == SUPER_ADMIN:
            users = db.query(User).options(joinedload(User.team)).all()
            teams = db.query(Team).options(joinedload(Team.users)).order_by(Team.team_name).all()
        else:
            users = db.query(User).filter_by(team_id=session['team_id']).options(joinedload(User.team)).all()

        return render_template('user_management.html', users=users, teams=teams, session=session)
    finally:
        db.close()

@app.route('/admin/add_user', methods=['POST'])
@admin_required
def add_user():
    db = SessionLocal()
    try:
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        role = request.form.get('role', ASSISTANT_COACH)

        team_id_for_new_user = None
        if session.get('role') == SUPER_ADMIN:
            form_team_id = request.form.get('team_id')
            if not form_team_id:
                flash('Super Admins must select a team for the new user.', 'danger')
                return redirect(url_for('user_management'))
            team_id_for_new_user = int(form_team_id)
        else:
            team_id_for_new_user = session['team_id']

        if not username or not password:
            flash('Username and password are required.', 'danger')
            return redirect(url_for('user_management'))
        if db.query(User).filter(func.lower(User.username) == func.lower(username)).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('user_management'))

        if role == SUPER_ADMIN and session.get('role') != SUPER_ADMIN:
            flash('Only a Super Admin can create another Super Admin.', 'danger')
            return redirect(url_for('user_management'))

        hashed_password = generate_password_hash(password)
        default_tab_keys = ['roster', 'lineups', 'pitching', 'scouting_list', 'rotations', 'games', 'collaboration', 'practice_plan']

        new_user = User(
            username=username,
            full_name=full_name,
            password_hash=hashed_password,
            role=role,
            tab_order=json.dumps(default_tab_keys),
            last_login='Never',
            team_id=team_id_for_new_user
        )
        db.add(new_user)
        db.commit()

        team_name = db.query(Team).filter_by(id=team_id_for_new_user).first().team_name
        flash(f"User '{username}' created successfully for team '{team_name}'.", 'success')
        socketio.emit('data_updated', {'message': 'A new user was added.'})
        return redirect(url_for('user_management'))
    finally:
        db.close()

@app.route('/admin/create_team', methods=['POST'])
@login_required
def create_team():
    if session.get('role') != SUPER_ADMIN:
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('user_management'))

    db = SessionLocal()
    try:
        team_name = request.form.get('team_name')
        if not team_name:
            flash('Team Name is required.', 'danger')
            return redirect(url_for('user_management'))

        if db.query(Team).filter(func.lower(Team.team_name) == func.lower(team_name)).first():
            flash(f'A team with the name "{team_name}" already exists.', 'danger')
            return redirect(url_for('user_management'))

        new_team = Team(team_name=team_name, registration_code=str(uuid.uuid4()).split('-')[-1])
        db.add(new_team)
        db.commit()

        flash(f'Team "{new_team.team_name}" created successfully!', 'success')
        return redirect(url_for('user_management'))

    except Exception as e:
        db.rollback()
        print(f"Team Creation Error: {e}")
        flash('An error occurred while creating the team.', 'danger')
        return redirect(url_for('user_management'))
    finally:
        db.close()

@app.route('/admin/delete_team/<int:team_id>')
@login_required
def delete_team(team_id):
    if session.get('role') != SUPER_ADMIN:
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('user_management'))

    db = SessionLocal()
    try:
        team_to_delete = db.query(Team).filter_by(id=team_id).first()

        if not team_to_delete:
            flash('Team not found.', 'danger')
            return redirect(url_for('user_management'))

        if team_to_delete.id == session.get('team_id'):
            flash('You cannot delete your own active team.', 'danger')
            return redirect(url_for('user_management'))

        user_count = db.query(User).filter_by(team_id=team_id).count()
        if user_count > 0:
            flash(f'Cannot delete team "{team_to_delete.team_name}" because it still has {user_count} user(s) assigned to it.', 'danger')
            return redirect(url_for('user_management'))

        flash(f'Successfully deleted team "{team_to_delete.team_name}".', 'success')
        db.delete(team_to_delete)
        db.commit()
        socketio.emit('data_updated', {'message': f'Team {team_to_delete.team_name} deleted.'})
        return redirect(url_for('user_management'))

    finally:
        db.close()

@app.route('/admin/settings', methods=['GET'])
@admin_required
def admin_settings():
    db = SessionLocal()
    try:
        team_settings = db.query(Team).filter_by(id=session['team_id']).first()
        return render_template('admin_settings.html', session=session, settings=team_settings, all_rules=PITCHING_RULES)
    finally:
        db.close()

@app.route('/admin/settings/update', methods=['POST'])
@admin_required
def update_admin_settings():
    db = SessionLocal()
    try:
        team_settings = db.query(Team).filter_by(id=session['team_id']).first()
        if not team_settings:
            flash('Team settings not found.', 'danger')
            return redirect(url_for('admin_settings'))

        team_settings.team_name = request.form.get('team_name', team_settings.team_name)
        team_settings.display_coach_names = 'display_coach_names' in request.form
        
        # MODIFIED: Get the new form fields and update the database
        team_settings.age_group = request.form.get('age_group', team_settings.age_group)
        team_settings.pitching_rule_set = request.form.get('pitching_rule_set', team_settings.pitching_rule_set)
        
        db.commit()

        flash('Team settings updated successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Team settings updated.'})
        return redirect(url_for('admin_settings'))
    finally:
        db.close()


@app.route('/admin/upload_logo', methods=['POST'])
@admin_required
def upload_logo():
    db = SessionLocal()
    try:
        team = db.query(Team).filter_by(id=session['team_id']).first()
        if not team:
            flash('Your team could not be found.', 'danger')
            return redirect(url_for('admin_settings'))

        if 'logo' not in request.files:
            flash('No file part in the request.', 'danger')
            return redirect(url_for('admin_settings'))

        file = request.files['logo']
        if file.filename == '':
            flash('No selected file.', 'danger')
            return redirect(url_for('admin_settings'))

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            unique_id = uuid.uuid4().hex
            file_ext = filename.rsplit('.', 1)[1].lower()
            new_filename = f"{team.id}_{unique_id}.{file_ext}"

            if team.logo_path:
                old_logo_path = os.path.join(app.config['UPLOAD_FOLDER'], team.logo_path)
                if os.path.exists(old_logo_path):
                    os.remove(old_logo_path)

            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

            file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            file.save(file_path)
            team.logo_path = new_filename
            db.commit()

            flash('Team logo uploaded successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Team logo updated.'})
        else:
            flash('Invalid file type. Allowed types are: png, jpg, jpeg, gif, svg.', 'danger')

        return redirect(url_for('admin_settings'))
    finally:
        db.close()


@app.route('/admin/update_user_details/<username>', methods=['POST'])
@admin_required
def update_user_details(username):
    db = SessionLocal()
    try:
        user_to_update = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if not user_to_update:
            flash('User not found.', 'danger')
            return redirect(url_for('user_management'))
        if session.get('role') == HEAD_COACH and user_to_update.team_id != session.get('team_id'):
            flash('You do not have permission to edit this user.', 'danger')
            return redirect(url_for('user_management'))
        user_to_update.full_name = request.form.get('full_name')
        db.commit()
        if session.get('username') == user_to_update.username:
            session['full_name'] = user_to_update.full_name
        flash(f"Successfully updated details for {user_to_update.username}.", 'success')
        socketio.emit('data_updated', {'message': f"User {user_to_update.username}'s details updated."})
        return redirect(url_for('user_management'))
    finally:
        db.close()

@app.route('/admin/change_role/<username>', methods=['POST'])
@admin_required
def change_user_role(username):
    db = SessionLocal()
    try:
        user_to_change = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if not user_to_change:
            flash('User not found.', 'danger')
            return redirect(url_for('user_management'))
        if session.get('role') == HEAD_COACH and user_to_change.team_id != session.get('team_id'):
            flash('You do not have permission to edit this user.', 'danger')
            return redirect(url_for('user_management'))
        if user_to_change.username.lower() == 'mike1825':
            flash('You cannot change the role of the Super Admin.', 'danger')
            return redirect(url_for('user_management'))
        new_role = request.form.get('role')
        if new_role == SUPER_ADMIN and session.get('role') != SUPER_ADMIN:
            flash('Only a Super Admin can assign the Super Admin role.', 'danger')
            return redirect(url_for('user_management'))
        if user_to_change.username == session['username'] and new_role != SUPER_ADMIN and db.query(User).filter_by(role=SUPER_ADMIN).count() == 1:
            flash('You cannot demote yourself as the sole Super Admin. Assign another Super Admin first.', 'danger')
            return redirect(url_for('user_management'))
        if new_role in [HEAD_COACH, ASSISTANT_COACH, GAME_CHANGER, SUPER_ADMIN]:
            user_to_change.role = new_role
            db.commit()
            flash(f"Successfully changed {username}'s role to {new_role}.", 'success')
            socketio.emit('data_updated', {'message': f"User {username}'s role changed."})
        else:
            flash('Invalid role selected.', 'danger')
        return redirect(url_for('user_management'))
    finally:
        db.close()

@app.route('/admin/delete_user/<username>')
@admin_required
def delete_user(username):
    db = SessionLocal()
    try:
        if username.lower() == 'mike1825':
            flash("The Super Admin cannot be deleted.", "danger")
            return redirect(url_for('user_management'))
        user_to_delete = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if user_to_delete:
            if session.get('role') == HEAD_COACH and user_to_delete.team_id != session.get('team_id'):
                flash('You do not have permission to delete this user.', 'danger')
                return redirect(url_for('user_management'))
            db.delete(user_to_delete)
            db.commit()
            flash(f"User '{username}' has been deleted.", "success")
            socketio.emit('data_updated', {'message': f"User {username} deleted."})
        else:
            flash("User not found.", "danger")
        return redirect(url_for('user_management'))
    finally:
        db.close()

@app.route('/admin/reset_password/<username>', methods=['POST'])
@admin_required
def reset_password(username):
    db = SessionLocal()
    try:
        if username.lower() == 'mike1825':
            flash("The Super Admin's password cannot be reset via this interface.", "danger")
            return redirect(url_for('user_management'))
        user_to_reset = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if not user_to_reset:
            flash('User not found.', 'danger')
            return redirect(url_for('user_management'))
        if session.get('role') == HEAD_COACH and user_to_reset.team_id != session.get('team_id'):
            flash('You do not have permission to reset this password.', 'danger')
            return redirect(url_for('user_management'))
        temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        user_to_reset.password_hash = generate_password_hash(temp_password)
        db.commit()
        flash(f"Password for {username} has been reset. The temporary password is: {temp_password}", 'success')
        socketio.emit('data_updated', {'message': f"Password for {username} reset."})
        return redirect(url_for('user_management'))
    finally:
        db.close()

# --- Player Development Routes ---
def find_focus_by_id(db_session, focus_id):
    return db_session.query(PlayerDevelopmentFocus).filter_by(id=focus_id).first()

@app.route('/save_player_order', methods=['POST'])
@login_required
def save_player_order():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username=session['username']).first()
        if not user: return jsonify({'status': 'error', 'message': 'User not found'}), 404
        new_order = request.json.get('player_order')
        if not isinstance(new_order, list): return jsonify({'status': 'error', 'message': 'Invalid order format'}), 400
        user.player_order = json.dumps(new_order)
        session['player_order'] = new_order
        session.modified = True
        db.commit()
        socketio.emit('data_updated', {'message': 'Player order saved.'})
        return jsonify({'status': 'success', 'message': 'Player order saved.'})
    finally:
        db.close()

@app.route('/add_focus/<player_name>', methods=['POST'])
@login_required
def add_focus(player_name):
    db = SessionLocal()
    try:
        player = db.query(Player).filter_by(name=player_name, team_id=session['team_id']).first()
        skill = request.form.get('skill')
        focus_text = request.form.get('focus_text')

        if not all([player, skill, focus_text]):
            flash('Skill, focus text, and valid player are required.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))

        new_focus = PlayerDevelopmentFocus(
            player_id=player.id, skill_type=skill, focus=focus_text, status="active",
            notes=request.form.get('notes', ''), author=session['username'],
            created_date=date.today().strftime('%Y-%m-%d'), team_id=session['team_id']
        )
        db.add(new_focus)
        db.commit()
        flash(f'New {skill} focus added for {player_name}.', 'success')
        socketio.emit('data_updated', {'message': f'New focus added for {player_name}.'})
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@app.route('/update_focus/<int:focus_id>', methods=['POST'])
@login_required
def update_focus(focus_id):
    db = SessionLocal()
    try:
        focus_item = find_focus_by_id(db, focus_id)
        if not focus_item or focus_item.team_id != session['team_id']:
            flash('Focus item not found or you do not have permission to edit.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))

        focus_item.focus = request.form.get('focus_text', focus_item.focus)
        focus_item.notes = request.form.get('notes', focus_item.notes)
        focus_item.last_edited_by = session['username']
        focus_item.last_edited_date = datetime.now().strftime('%Y-%m-%d %H:%M')
        db.commit()
        flash('Focus item updated successfully.', 'success')
        socketio.emit('data_updated', {'message': 'Focus item updated.'})
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@app.route('/complete_focus/<int:focus_id>')
@login_required
def complete_focus(focus_id):
    db = SessionLocal()
    try:
        focus_item = find_focus_by_id(db, focus_id)
        if not focus_item or focus_item.team_id != session['team_id']:
            flash('Focus item not found or you do not have permission.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))

        focus_item.status = 'completed'
        focus_item.completed_date = date.today().strftime('%Y-%m-%d')
        db.commit()
        flash('Focus marked as complete!', 'success')
        socketio.emit('data_updated', {'message': 'Focus marked complete.'})
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@app.route('/delete_focus/<int:focus_id>')
@login_required
def delete_focus(focus_id):
    db = SessionLocal()
    try:
        focus_item = find_focus_by_id(db, focus_id)
        if focus_item and focus_item.team_id == session['team_id']:
            db.delete(focus_item)
            db.commit()
            flash('Focus deleted successfully.', 'success')
            socketio.emit('data_updated', {'message': 'Focus deleted.'})
        else:
            flash('Could not find the focus item to delete or you do not have permission.', 'danger')
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@app.route('/update_lesson_info/<int:player_id>', methods=['POST'])
@login_required
def update_lesson_info(player_id):
    db = SessionLocal()
    try:
        player = db.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
        if not player:
            flash('Player not found.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))
        player.has_lessons = request.form.get('has_lessons')
        player.lesson_focus = request.form.get('lesson_focus')
        player.notes_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M")
        db.commit()
        flash(f'Lesson info for {player.name} updated.', 'success')
        socketio.emit('data_updated', {'message': f'Lesson info for {player.name} updated.'})
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@app.route('/delete_lesson_info/<int:player_id>')
@login_required
def delete_lesson_info(player_id):
    db = SessionLocal()
    try:
        player = db.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
        if not player:
            flash('Player not found.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))
        player.has_lessons = 'No'
        player.lesson_focus = ''
        db.commit()
        flash(f'Lesson info for {player.name} has been deleted.', 'success')
        socketio.emit('data_updated', {'message': f'Lesson info for {player.name} deleted.'})
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

# --- Roster and Player Routes ---
@app.route('/add_player', methods=['POST'])
@login_required
def add_player():
    db = SessionLocal()
    try:
        name = request.form.get('name')
        if not name:
            flash('Player name is required.', 'danger')
            return redirect(url_for('home', _anchor='roster'))

        existing_player = db.query(Player).filter_by(name=name, team_id=session['team_id']).first()
        if existing_player:
            flash(f'A player with the name "{name}" already exists on this roster.', 'danger')
            return redirect(url_for('home', _anchor='roster'))

        new_player = Player(
            name=name,
            number=request.form.get('number'),
            position1=request.form.get('position1'),
            position2=request.form.get('position2'),
            position3=request.form.get('position3'),
            throws=request.form.get('throws'),
            bats=request.form.get('bats'),
            notes=request.form.get('notes'),
            pitcher_role=request.form.get('pitcher_role'),
            has_lessons="No",
            notes_author=session['username'],
            notes_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
            team_id=session['team_id']
        )
        db.add(new_player)

        for user_obj in db.query(User).filter_by(team_id=session['team_id']).all():
            current_order = json.loads(user_obj.player_order or "[]")
            if new_player.name not in current_order:
                current_order.append(new_player.name)
                user_obj.player_order = json.dumps(current_order)

        db.commit()
        flash(f'Player "{name}" added successfully!', 'success')
        socketio.emit('data_updated', {'message': f'Player {name} added.'})
        if 'X-Requested-With' in request.headers and request.headers['X-Requested-With'] == 'XMLHttpRequest':
             return jsonify({'status': 'success'})

        return redirect(url_for('home', _anchor='roster'))
    finally:
        db.close()

@app.route('/update_player_inline/<int:player_id>', methods=['POST'])
@login_required
def update_player_inline(player_id):
    db = SessionLocal()
    try:
        player_to_edit = db.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
        if not player_to_edit:
            return jsonify({'status': 'error', 'message': 'Player not found.'}), 404
        original_name = player_to_edit.name
        new_name = request.form.get('name', original_name)
        if new_name != original_name and db.query(Player).filter_by(name=new_name, team_id=session['team_id']).first():
            return jsonify({'status': 'error', 'message': f'Player name "{new_name}" already exists.'}), 400

        player_to_edit.name = new_name
        player_to_edit.number = request.form.get('number', player_to_edit.number)
        player_to_edit.position1 = request.form.get('position1', player_to_edit.position1)
        player_to_edit.position2 = request.form.get('position2', player_to_edit.position2)
        player_to_edit.position3 = request.form.get('position3', player_to_edit.position3)
        player_to_edit.throws = request.form.get('throws', player_to_edit.throws)
        player_to_edit.bats = request.form.get('bats', player_to_edit.bats)
        player_to_edit.notes = request.form.get('notes', player_to_edit.notes)
        player_to_edit.pitcher_role = request.form.get('pitcher_role', player_to_edit.pitcher_role)
        player_to_edit.notes_author = session['username']
        player_to_edit.notes_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        if original_name != new_name:
            for user_obj in db.query(User).filter_by(team_id=session['team_id']).all():
                current_order = json.loads(user_obj.player_order or "[]")
                updated_order = [new_name if name == original_name else name for name in current_order]
                user_obj.player_order = json.dumps(updated_order)
            session['player_order'] = [new_name if name == original_name else name for name in session.get('player_order', [])]
            session.modified = True
        db.commit()
        socketio.emit('data_updated', {'message': f'Player {new_name} updated.'})
        return jsonify({'status': 'success', 'message': f'Player "{new_name}" updated successfully!'})
    finally:
        db.close()

@app.route('/delete_player/<int:player_id>')
@login_required
def delete_player(player_id):
    db = SessionLocal()
    try:
        player_to_delete = db.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
        if player_to_delete:
            player_name = player_to_delete.name
            db.delete(player_to_delete)
            for user_obj in db.query(User).filter_by(team_id=session['team_id']).all():
                current_order = json.loads(user_obj.player_order or "[]")
                updated_order = [name for name in current_order if name != player_name]
                user_obj.player_order = json.dumps(updated_order)
            if 'player_order' in session:
                session['player_order'] = [name for name in session['player_order'] if name != player_name]
                session.modified = True
            db.commit()
            flash(f'Player "{player_name}" removed successfully!', 'success')
            socketio.emit('data_updated', {'message': f'Player {player_name} deleted.'})
        else:
            flash('Player not found.', 'danger')
        return redirect(url_for('home', _anchor=request.args.get('active_tab', 'roster').lstrip('#')))
    finally:
        db.close()

# --- Pitching Routes ---
@app.route('/add_pitching', methods=['POST'])
@login_required
def add_pitching():
    db = SessionLocal()
    try:
        try:
            pitch_count = int(request.form['pitches'])
            innings_pitched = float(request.form['innings'])
        except ValueError:
            flash('Pitch count and innings must be valid numbers.', 'danger')
            return redirect(url_for('home', _anchor='pitching'))

        new_outing = PitchingOuting(
            date=request.form['pitch_date'], pitcher=request.form['pitcher'], opponent=request.form['opponent'],
            pitches=pitch_count, innings=innings_pitched, pitcher_type=request.form.get('pitcher_type', 'Starter'),
            outing_type=request.form.get('outing_type', 'Game'), team_id=session['team_id']
        )
        db.add(new_outing)
        db.commit()
        flash(f'Pitching outing for "{new_outing.pitcher}" added successfully!', 'success')
        socketio.emit('data_updated', {'message': 'New pitching outing added.'})
        game_id = request.form.get('game_id')
        if game_id:
            return redirect(url_for('game_management', game_id=game_id, _anchor='pitching'))
        return redirect(url_for('home', _anchor='pitching'))
    finally:
        db.close()

@app.route('/delete_pitching/<int:outing_id>')
@login_required
def delete_pitching(outing_id):
    db = SessionLocal()
    try:
        outing_to_delete = db.query(PitchingOuting).filter_by(id=outing_id, team_id=session['team_id']).first()
        if outing_to_delete:
            db.delete(outing_to_delete)
            db.commit()
            flash(f'Pitching outing for "{outing_to_delete.pitcher}" removed successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Pitching outing deleted.'})
        else:
            flash('Pitching outing not found.', 'danger')
        redirect_url = request.referrer or url_for('home', _anchor='pitching')
        return redirect(redirect_url)
    finally:
        db.close()

# --- Signs Routes ---
@app.route('/add_sign', methods=['POST'])
@login_required
def add_sign():
    db = SessionLocal()
    try:
        sign_name = request.form.get('sign_name')
        sign_indicator = request.form.get('sign_indicator')
        if sign_name and sign_indicator:
            new_sign = Sign(name=sign_name, indicator=sign_indicator, team_id=session['team_id'])
            db.add(new_sign)
            db.commit()
            flash('Sign added successfully!', 'success')
            socketio.emit('data_updated', {'message': 'New sign added.'})
        else:
            flash('Sign Name and Indicator are required.', 'danger')
        return redirect(url_for('home', _anchor='signs'))
    finally:
        db.close()

@app.route('/update_sign/<int:sign_id>', methods=['POST'])
@login_required
def update_sign(sign_id):
    db = SessionLocal()
    try:
        sign_to_update = db.query(Sign).filter_by(id=sign_id, team_id=session['team_id']).first()
        if not sign_to_update:
            flash('Sign not found.', 'danger')
            return redirect(url_for('home', _anchor='signs'))
        sign_name = request.form.get('sign_name')
        sign_indicator = request.form.get('sign_indicator')
        if sign_name and sign_indicator:
            sign_to_update.name = sign_name
            sign_to_update.indicator = sign_indicator
            db.commit()
            flash('Sign updated successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Sign updated.'})
        else:
            flash('Sign Name and Indicator are required.', 'danger')
        return redirect(url_for('home', _anchor='signs'))
    finally:
        db.close()


@app.route('/delete_sign/<int:sign_id>')
@login_required
def delete_sign(sign_id):
    db = SessionLocal()
    try:
        sign_to_delete = db.query(Sign).filter_by(id=sign_id, team_id=session['team_id']).first()
        if sign_to_delete:
            db.delete(sign_to_delete)
            db.commit()
            flash('Sign deleted successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Sign deleted.'})
        else:
            flash('Sign not found.', 'danger')
        return redirect(url_for('home', _anchor='signs'))
    finally:
        db.close()

# --- Rotation Routes ---
@app.route('/save_rotation', methods=['POST'])
@login_required
def save_rotation():
    db = SessionLocal()
    try:
        rotation_data = request.get_json()
        rotation_id = rotation_data.get('id')
        title = rotation_data.get('title')
        innings_data = rotation_data.get('innings')
        associated_game_id = rotation_data.get('associated_game_id')
        if not title or not isinstance(innings_data, dict):
            return jsonify({'status': 'error', 'message': 'Invalid data provided. A title and inning data are required.'}), 400
        if rotation_id:
            rotation_to_update = db.query(Rotation).filter_by(id=rotation_id, team_id=session['team_id']).first()
            if rotation_to_update:
                rotation_to_update.title = title
                rotation_to_update.innings = json.dumps(innings_data)
                rotation_to_update.associated_game_id = associated_game_id
                message = 'Rotation updated successfully!'
                new_rotation_id = rotation_id
            else: rotation_id = None
        if not rotation_id:
            new_rotation = Rotation(title=title, innings=json.dumps(innings_data), associated_game_id=associated_game_id, team_id=session['team_id'])
            db.add(new_rotation)
            db.commit()
            new_rotation_id = new_rotation.id
            message = 'Rotation saved successfully!'
        db.commit()
        socketio.emit('data_updated', {'message': 'Rotation saved/updated.'})
        return jsonify({'status': 'success', 'message': message, 'new_id': new_rotation_id})
    finally:
        db.close()

@app.route('/delete_rotation/<int:rotation_id>')
@login_required
def delete_rotation(rotation_id):
    db = SessionLocal()
    try:
        rotation_to_delete = db.query(Rotation).filter_by(id=rotation_id, team_id=session['team_id']).first()
        if rotation_to_delete:
            db.delete(rotation_to_delete)
            db.commit()
            flash('Rotation deleted successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Rotation deleted.'})
        else:
            flash('Rotation not found.', 'danger')
        redirect_url = request.referrer or url_for('home', _anchor='rotations')
        return redirect(redirect_url)
    finally:
        db.close()

# --- Collaboration Notes Routes ---
@app.route('/add_note/<note_type>', methods=['POST'])
@login_required
def add_note(note_type):
    db = SessionLocal()
    try:
        if note_type not in ['player_notes', 'team_notes']:
            flash('Invalid note type.', 'danger')
            return redirect(url_for('home', _anchor='collaboration'))
        note_text = request.form.get('note_text')
        if not note_text:
            flash('Note cannot be empty.', 'warning')
            return redirect(url_for('home', _anchor='collaboration'))
        new_note = CollaborationNote(note_type=note_type, text=note_text, author=session['username'], timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"), team_id=session['team_id'])
        if note_type == 'player_notes':
            player_name = request.form.get('player_name')
            if not player_name:
                flash('You must select a player.', 'warning')
                return redirect(url_for('home', _anchor='collaboration'))
            new_note.player_name = player_name
        db.add(new_note)
        db.commit()
        flash('Note added successfully!', 'success')
        socketio.emit('data_updated', {'message': 'New note added.'})
        return redirect(url_for('home', _anchor='collaboration'))
    finally:
        db.close()

@app.route('/edit_note', methods=['POST'])
@login_required
def edit_note():
    db = SessionLocal()
    try:
        try:
            note_id = int(request.form.get('note_id'))
        except (ValueError, TypeError):
            flash('Invalid note ID.', 'danger')
            return redirect(url_for('home', _anchor='collaboration'))
        note_type = request.form.get('note_type')
        new_text = request.form.get('note_text')
        if not all([note_type, new_text]):
            flash('Invalid request data.', 'danger')
            return redirect(url_for('home', _anchor='collaboration'))
        note_to_edit = db.query(CollaborationNote).filter_by(id=note_id, team_id=session['team_id']).first()
        if not note_to_edit or note_to_edit.note_type != note_type:
            flash('Note not found or invalid note type.', 'danger')
            return redirect(url_for('home', _anchor='collaboration'))
        if session['username'] == note_to_edit.author or session.get('role') in [HEAD_COACH, SUPER_ADMIN]:
            note_to_edit.text = new_text
            db.commit()
            flash('Note updated successfully.', 'success')
            socketio.emit('data_updated', {'message': 'Note updated.'})
        else:
            flash('You do not have permission to edit this note.', 'danger')
        return redirect(url_for('home', _anchor='collaboration'))
    finally:
        db.close()

@app.route('/delete_note/<note_type>/<int:note_id>')
@login_required
def delete_note(note_type, note_id):
    db = SessionLocal()
    try:
        note_to_delete = db.query(CollaborationNote).filter_by(id=note_id, team_id=session['team_id']).first()
        if note_to_delete and note_to_delete.note_type == note_type:
            if session['username'] == note_to_delete.author or session.get('role') in [HEAD_COACH, SUPER_ADMIN]:
                db.delete(note_to_delete)
                db.commit()
                flash('Note deleted successfully.', 'success')
                socketio.emit('data_updated', {'message': 'Note deleted.'})
            else:
                flash('You do not have permission to delete this note.', 'danger')
        else:
            flash('Note not found or invalid note type.', 'danger')
        return redirect(url_for('home', _anchor='collaboration'))
    finally:
        db.close()

# --- Practice Plan Routes ---
@app.route('/add_practice_plan', methods=['POST'])
@login_required
def add_practice_plan():
    db = SessionLocal()
    try:
        plan_date = request.form.get('plan_date')
        if not plan_date:
            flash('Practice date is required.', 'danger')
            return redirect(url_for('home', _anchor='practice_plan'))
        new_plan = PracticePlan(date=plan_date, general_notes=request.form.get('general_notes', ''), team_id=session['team_id'])
        db.add(new_plan)
        db.commit()
        flash('New practice plan created!', 'success')
        socketio.emit('data_updated', {'message': 'New practice plan created.'})
        return redirect(url_for('home', _anchor='practice_plan'))
    finally:
        db.close()

@app.route('/add_task_to_plan/<int:plan_id>', methods=['POST'])
@login_required
def add_task_to_plan(plan_id):
    db = SessionLocal()
    try:
        if request.is_json:
            data = request.get_json()
            task_text = data.get('task_text')
        else:
            task_text = request.form.get('task_text')
        if not task_text:
            if request.is_json:
                return jsonify({'status': 'error', 'message': 'Task cannot be empty.'}), 400
            else:
                flash('Task cannot be empty.', 'warning')
                return redirect(url_for('home', _anchor='practice_plan'))
        plan = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
        if not plan:
            if request.is_json:
                return jsonify({'status': 'error', 'message': 'Plan not found.'}), 404
            else:
                flash('Practice plan not found.', 'danger')
                return redirect(url_for('home', _anchor='practice_plan'))
        new_task = PracticeTask(text=task_text, status="pending", author=session['username'], timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"), practice_plan_id=plan.id)
        db.add(new_task)
        db.commit()
        socketio.emit('data_updated', {'message': 'Task added to plan.'})
        if request.is_json:
            return jsonify({'status': 'success', 'message': 'Task added.'})
        flash('Task added to plan.', 'success')
        return redirect(url_for('home', _anchor='practice_plan'))
    finally:
        db.close()

@app.route('/delete_task/<int:plan_id>/<int:task_id>')
@login_required
def delete_task(plan_id, task_id):
    db = SessionLocal()
    try:
        plan = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
        if not plan:
            flash('Practice plan not found.', 'danger')
            return redirect(url_for('home', _anchor='practice_plan'))
        task_to_delete = db.query(PracticeTask).filter_by(id=task_id, practice_plan_id=plan.id).first()
        if task_to_delete:
            db.delete(task_to_delete)
            db.commit()
            flash('Task deleted.', 'success')
            socketio.emit('data_updated', {'message': 'Task deleted from plan.'})
        else: flash('Task not found.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
    finally:
        db.close()

@app.route('/update_task_status/<int:plan_id>/<int:task_id>', methods=['POST'])
@login_required
def update_task_status(plan_id, task_id):
    db = SessionLocal()
    try:
        plan = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
        if not plan:
            return jsonify({'status': 'error', 'message': 'Plan not found'}), 404
        task = db.query(PracticeTask).filter_by(id=task_id, practice_plan_id=plan.id).first()
        if not task:
            return jsonify({'status': 'error', 'message': 'Task not found'}), 404
        request_data = request.get_json()
        new_status = request_data.get('status')
        if new_status not in ['pending', 'complete']:
            return jsonify({'status': 'error', 'message': 'Invalid status'}), 400
        task.status = new_status
        db.commit()
        socketio.emit('data_updated', {'message': 'Task status updated.'})
        return jsonify({'status': 'success', 'message': 'Task status updated.'})
    finally:
        db.close()

@app.route('/move_note_to_practice_plan/<note_type>/<int:note_id>', methods=['GET', 'POST'])
@login_required
def move_note_to_practice_plan(note_type, note_id):
    db = SessionLocal()
    try:
        note_to_move = db.query(CollaborationNote).filter_by(id=note_id, team_id=session['team_id']).first()
        if not (note_to_move and note_to_move.note_type == note_type):
            flash('Note not found or invalid type.', 'danger')
            return redirect(url_for('home', _anchor='collaboration'))
        if request.method == 'POST':
            plan_id_str = request.form.get('plan_id')
            if not plan_id_str:
                flash('You must select a practice plan.', 'warning')
                return redirect(url_for('move_note_to_practice_plan', note_type=note_type, note_id=note_id))
            plan_id = int(plan_id_str)
            plan = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
            if not plan:
                flash('Practice plan not found.', 'danger')
                return redirect(url_for('home', _anchor='collaboration'))
            new_task = PracticeTask(
                text=note_to_move.text, status="pending", author=note_to_move.author,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"), practice_plan_id=plan.id
            )
            db.add(new_task)
            db.delete(note_to_move)
            db.commit()
            flash('Note successfully moved to practice plan and original deleted.', 'success')
            socketio.emit('data_updated', {'message': 'Note moved to practice plan.'})
            return redirect(url_for('home', _anchor='practice_plan'))
        practice_plans = db.query(PracticePlan).filter_by(team_id=session['team_id']).all()
        return render_template('move_note_to_plan.html', note=note_to_move, practice_plans=practice_plans, note_type=note_type, note_id=note_id)
    finally:
        db.close()

# --- Scouting and Recruiting Routes ---
@app.route('/add_scouted_player', methods=['POST'])
@login_required
def add_scouted_player():
    db = SessionLocal()
    try:
        data = request.get_json()
        player_name = data.get('scouted_player_name')
        scouted_player_type = data.get('scouted_player_type')
        if not player_name:
            return jsonify({'status': 'error', 'message': 'Player name is required.'}), 400
        if scouted_player_type not in ['committed', 'targets', 'not_interested']:
            return jsonify({'status': 'error', 'message': 'Invalid scouting list type.'}), 400
        new_player = ScoutedPlayer(
            name=player_name, position1=data.get('scouted_player_pos1', ''), position2=data.get('scouted_player_pos2', ''),
            throws=data.get('scouted_player_throws', ''), bats=data.get('scouted_player_bats', ''),
            list_type=scouted_player_type, team_id=session['team_id']
        )
        db.add(new_player)
        db.commit()
        socketio.emit('data_updated', {'message': 'New scouted player added.'})
        return jsonify({'status': 'success', 'message': f'Player "{new_player.name}" added to {scouted_player_type.replace("_", " ").title()} list.'})
    except Exception as e:
        app.logger.error(f"Error adding scouted player: {e}")
        return jsonify({'status': 'error', 'message': 'An internal server error occurred.'}), 500
    finally:
        db.close()

@app.route('/delete_scouted_player/<list_type>/<int:player_id>')
@login_required
def delete_scouted_player(list_type, player_id):
    db = SessionLocal()
    try:
        if list_type not in ['committed', 'targets', 'not_interested']:
            flash(f'Could not find the list type "{list_type}".', 'danger')
            return redirect(url_for('home', _anchor='scouting_list'))
        player_to_delete = db.query(ScoutedPlayer).filter_by(id=player_id, list_type=list_type, team_id=session['team_id']).first()
        if player_to_delete:
            player_name = player_to_delete.name
            db.delete(player_to_delete)
            db.commit()
            flash(f'Removed {player_name} from the scouting list.', 'success')
            socketio.emit('data_updated', {'message': f'Scouted player {player_name} removed.'})
        else:
            flash(f'Could not find the player to remove.', 'warning')
        return redirect(url_for('home', _anchor='scouting_list'))
    finally:
        db.close()

@app.route('/move_scouted_player/<from_type>/<to_type>/<int:player_id>', methods=['POST'])
@login_required
def move_scouted_player(from_type, to_type, player_id):
    db = SessionLocal()
    try:
        if from_type not in ['committed', 'targets', 'not_interested'] or to_type not in ['committed', 'targets', 'not_interested']:
            flash('Invalid list type.', 'danger')
            return redirect(url_for('home', _anchor='scouting_list'))
        player_to_move = db.query(ScoutedPlayer).filter_by(id=player_id, list_type=from_type, team_id=session['team_id']).first()
        if player_to_move:
            player_to_move.list_type = to_type
            db.commit()
            flash(f'Player "{player_to_move.name}" moved to {to_type.replace("_", " ").title()} list.', 'success')
            socketio.emit('data_updated', {'message': f'Scouted player {player_to_move.name} moved.'})
        else:
            flash('Could not move player.', 'danger')
        return redirect(url_for('home', _anchor='scouting_list'))
    finally:
        db.close()

@app.route('/move_scouted_player_to_roster/<int:player_id>', methods=['POST'])
@login_required
def move_scouted_player_to_roster(player_id):
    db = SessionLocal()
    try:
        scouted_player = db.query(ScoutedPlayer).filter_by(id=player_id, list_type='committed', team_id=session['team_id']).first()
        if not scouted_player:
            flash('Committed player not found.', 'danger')
            return redirect(url_for('home', _anchor='scouting_list'))
        if db.query(Player).filter_by(name=scouted_player.name, team_id=session['team_id']).first():
            flash(f'Cannot move "{scouted_player.name}" to roster because a player with that name already exists.', 'danger')
            return redirect(url_for('home', _anchor='scouting_list'))
        new_roster_player = Player(
            name=scouted_player.name, number="", position1=scouted_player.position1, position2=scouted_player.position2,
            throws=scouted_player.throws, bats=scouted_player.bats, notes="", pitcher_role="Not a Pitcher", has_lessons="No",
            lesson_focus="", notes_author=session['username'], notes_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"), team_id=session['team_id']
        )
        db.add(new_roster_player)
        db.delete(scouted_player)
        for user_obj in db.query(User).filter_by(team_id=session['team_id']).all():
            current_order = json.loads(user_obj.player_order or "[]")
            if new_roster_player.name not in current_order:
                current_order.append(new_roster_player.name)
                user_obj.player_order = json.dumps(current_order)
        if 'player_order' in session and new_roster_player.name not in session['player_order']:
            session['player_order'].append(new_roster_player.name)
            session.modified = True
        db.commit()
        flash(f'Player "{new_roster_player.name}" moved to Roster. Please assign a number.', 'success')
        socketio.emit('data_updated', {'message': f'Scouted player {new_roster_player.name} moved to roster.'})
        return redirect(url_for('home', _anchor='scouting_list'))
    finally:
        db.close()

# --- Game and Lineup Routes ---
@app.route('/add_game', methods=['POST'])
@login_required
def add_game():
    db = SessionLocal()
    try:
        new_game = Game(
            date=request.form['game_date'], opponent=request.form['game_opponent'], location=request.form.get('game_location', ''),
            game_notes=request.form.get('game_notes', ''), associated_lineup_title=request.form.get('associated_lineup_title', ''),
            associated_rotation_date=request.form.get('associated_rotation_date', ''), team_id=session['team_id']
        )
        db.add(new_game)
        db.commit()
        flash(f'Game vs "{new_game.opponent}" on {new_game.date} added successfully!', 'success')
        socketio.emit('data_updated', {'message': 'New game added.'})
        return redirect(url_for('game_management', game_id=new_game.id))
    finally:
        db.close()


@app.route('/delete_game/<int:game_id>')
@login_required
def delete_game(game_id):
    db = SessionLocal()
    try:
        game_to_delete = db.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
        if game_to_delete:
            db.delete(game_to_delete)
            db.commit()
            flash(f'Game vs "{game_to_delete.opponent}" on {game_to_delete.date} removed successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Game deleted.'})
        else:
            flash('Game not found.', 'danger')
        return redirect(url_for('home', _anchor='games'))
    finally:
        db.close()


def _sync_lineup_to_rotation(db, lineup):
    if not lineup.associated_game_id: return
    game = db.query(Game).filter_by(id=lineup.associated_game_id, team_id=lineup.team_id).first()
    if not game: return
    lineup_positions = json.loads(lineup.lineup_positions or "[]")
    inning_1_data = {item['position']: item['name'] for item in lineup_positions if item.get('position') and item.get('name')}
    if not inning_1_data: return
    rotation_for_game = db.query(Rotation).filter_by(associated_game_id=game.id, team_id=lineup.team_id).first()
    if rotation_for_game:
        current_innings = json.loads(rotation_for_game.innings or "{}")
        current_innings['1'] = inning_1_data
        rotation_for_game.innings = json.dumps(current_innings)
    else:
        new_rotation = Rotation(title=f"vs {game.opponent} ({game.date})", associated_game_id=game.id, innings=json.dumps({'1': inning_1_data}), team_id=lineup.team_id)
        db.add(new_rotation)

@app.route('/add_lineup', methods=['POST'])
@login_required
def add_lineup():
    db = SessionLocal()
    try:
        payload = request.get_json()
        if not payload or 'title' not in payload or 'lineup_data' not in payload:
            return jsonify({'status': 'error', 'message': 'Invalid lineup data.'}), 400
        new_lineup = Lineup(
            title=payload['title'], lineup_positions=json.dumps(payload['lineup_data']),
            associated_game_id=int(payload['associated_game_id']) if payload.get('associated_game_id') else None, team_id=session['team_id']
        )
        db.add(new_lineup)
        _sync_lineup_to_rotation(db, new_lineup)
        db.commit()
        socketio.emit('data_updated', {'message': 'New lineup added.'})
        return jsonify({'status': 'success', 'message': f'Lineup "{new_lineup.title}" created successfully!'})
    finally:
        db.close()

@app.route('/edit_lineup/<int:lineup_id>', methods=['POST'])
@login_required
def edit_lineup(lineup_id):
    db = SessionLocal()
    try:
        lineup_to_edit = db.query(Lineup).filter_by(id=lineup_id, team_id=session['team_id']).first()
        if not lineup_to_edit:
            return jsonify({'status': 'error', 'message': 'Lineup not found.'}), 404
        payload = request.get_json()
        if not payload or 'title' not in payload or 'lineup_data' not in payload:
            return jsonify({'status': 'error', 'message': 'Invalid lineup data.'}), 400
        lineup_to_edit.title = payload['title']
        lineup_to_edit.lineup_positions = json.dumps(payload['lineup_data'])
        lineup_to_edit.associated_game_id = int(payload.get('associated_game_id')) if payload.get('associated_game_id') else None
        _sync_lineup_to_rotation(db, lineup_to_edit)
        db.commit()
        socketio.emit('data_updated', {'message': 'Lineup updated.'})
        return jsonify({'status': 'success', 'message': f'Lineup "{lineup_to_edit.title}" updated successfully!'})
    finally:
        db.close()


@app.route('/delete_lineup/<int:lineup_id>')
@login_required
def delete_lineup(lineup_id):
    db = SessionLocal()
    try:
        lineup_to_delete = db.query(Lineup).filter_by(id=lineup_id, team_id=session['team_id']).first()
        if lineup_to_delete:
            db.delete(lineup_to_delete)
            db.commit()
            flash(f'Lineup "{lineup_to_delete.title}" deleted successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Lineup deleted.'})
        else:
            flash('Lineup not found.', 'danger')
        redirect_url = request.referrer or url_for('home', _anchor='lineups')
        return redirect(redirect_url)
    finally:
        db.close()


@app.route('/game/<int:game_id>')
@login_required
def game_management(game_id):
    db = SessionLocal()
    try:
        team = db.query(Team).filter_by(id=session['team_id']).first()
        if not team:
            flash('Team not found.', 'danger')
            return redirect(url_for('home'))

        game = db.query(Game).filter_by(id=game_id, team_id=team.id).first()
        if not game:
            flash('Game not found.', 'danger')
            return redirect(url_for('home', _anchor='games'))
        
        game_dict = {"id": game.id, "date": game.date, "opponent": game.opponent, "location": game.location, "game_notes": game.game_notes}
        roster_objects = db.query(Player).filter_by(team_id=team.id).all()
        roster_list = [{"id": p.id, "name": p.name, "number": p.number, "position1": p.position1, "position2": p.position2, "position3": p.position3, "throws": p.throws, "bats": p.bats, "pitcher_role": p.pitcher_role} for p in roster_objects]
        
        lineup_obj = db.query(Lineup).filter_by(associated_game_id=game.id, team_id=team.id).first()
        if lineup_obj:
            lineup_dict = {"id": lineup_obj.id, "title": lineup_obj.title, "lineup_positions": json.loads(lineup_obj.lineup_positions or "[]"), "associated_game_id": lineup_obj.associated_game_id}
        else:
            lineup_dict = {"id": None, "title": f"Lineup for vs {game.opponent}", "lineup_positions": [], "associated_game_id": game.id}
            
        rotation_obj = db.query(Rotation).filter_by(associated_game_id=game.id, team_id=team.id).first()
        if rotation_obj:
            rotation_dict = {"id": rotation_obj.id, "title": rotation_obj.title, "innings": json.loads(rotation_obj.innings or "{}"), "associated_game_id": rotation_obj.associated_game_id}
        else:
            rotation_dict = {"id": None, "title": f"Rotation for vs {game.opponent}", "innings": {}, "associated_game_id": game.id}

        pitching_outings = db.query(PitchingOuting).filter_by(team_id=team.id).all()
        pitcher_names = sorted([p["name"] for p in roster_list if p["pitcher_role"] != 'Not a Pitcher'])
        
        pitch_count_summary = {}
        for name in pitcher_names:
            counts = calculate_pitch_counts(name, pitching_outings, team)
            availability = calculate_pitcher_availability(name, pitching_outings, team)
            cumulative_stats = calculate_cumulative_pitching_stats(name, pitching_outings)
            pitch_count_summary[name] = {**counts, **availability, **cumulative_stats}
            
        game_pitching_log = [p for p in pitching_outings if p.opponent == game.opponent and p.date == game.date]
        
        absences = db.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team.id).all()
        absent_player_ids = [absence.player_id for absence in absences]

        return render_template('game_management.html', game=game_dict, roster=roster_list, lineup=lineup_dict, rotation=rotation_dict, pitch_count_summary=pitch_count_summary, game_pitching_log=game_pitching_log, session=session, absent_player_ids=absent_player_ids)
    finally:
        db.close()

@app.route('/game/<int:game_id>/update_absences', methods=['POST'])
@login_required
def update_absences(game_id):
    db = SessionLocal()
    try:
        team_id = session['team_id']
        game = db.query(Game).filter_by(id=game_id, team_id=team_id).first()
        if not game:
            flash('Game not found.', 'danger')
            return redirect(url_for('home', _anchor='games'))

        absent_player_ids = [int(pid) for pid in request.form.getlist('absent_players')]
        db.query(PlayerGameAbsence).filter_by(game_id=game_id, team_id=team_id).delete()

        for player_id in absent_player_ids:
            player = db.query(Player).filter_by(id=player_id, team_id=team_id).first()
            if player:
                new_absence = PlayerGameAbsence(player_id=player.id, game_id=game.id, team_id=team_id)
                db.add(new_absence)

        db.commit()
        flash('Player availability updated for this game.', 'success')
        socketio.emit('data_updated', {'message': f'Availability updated for game {game_id}.'})

    except Exception as e:
        db.rollback()
        flash('An error occurred while updating availability.', 'danger')
        print(f"Error updating absences: {e}")
    finally:
        db.close()

    return redirect(url_for('game_management', game_id=game_id, _anchor='availability'))


@app.route('/edit_game/<int:game_id>', methods=['POST'])
@login_required
def edit_game(game_id):
    db = SessionLocal()
    try:
        game_to_edit = db.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
        if not game_to_edit:
            flash('Game not found.', 'danger')
            return redirect(url_for('home', _anchor='games'))
        game_to_edit.date = request.form.get('game_date', game_to_edit.date)
        game_to_edit.opponent = request.form.get('game_opponent', game_to_edit.opponent)
        game_to_edit.location = request.form.get('game_location', game_to_edit.location)
        game_to_edit.game_notes = request.form.get('game_notes', game_to_edit.game_notes)
        db.commit()
        flash('Game details updated successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Game details updated.'})
        return redirect(url_for('game_management', game_id=game_id))
    finally:
        db.close()


@app.route('/delete_practice_plan/<int:plan_id>')
@login_required
def delete_practice_plan(plan_id):
    db = SessionLocal()
    try:
        plan_to_delete = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
        if plan_to_delete:
            db.query(PracticeTask).filter_by(practice_plan_id=plan_to_delete.id).delete()
            db.delete(plan_to_delete)
            db.commit()
            flash('Practice plan deleted successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Practice plan deleted.'})
        else:
            flash('Practice plan not found.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
    finally:
        db.close()


@app.route('/edit_practice_plan/<int:plan_id>', methods=['POST'])
@login_required
def edit_practice_plan(plan_id):
    db = SessionLocal()
    try:
        plan_to_edit = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
        if plan_to_edit:
            new_date = request.form.get('plan_date')
            new_notes = request.form.get('general_notes')
            if not new_date:
                flash('Plan date cannot be empty.', 'danger')
            else:
                plan_to_edit.date = new_date
                plan_to_edit.general_notes = new_notes
                db.commit()
                flash('Practice plan updated successfully!', 'success')
                socketio.emit('data_updated', {'message': 'Practice plan updated.'})
        else:
            flash('Practice plan not found.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
    finally:
        db.close()


if __name__ == '__main__':
    check_database_initialized()
    socketio.run(app, host='0.0.0.0', port=5002, debug=False)
