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
from db import SessionLocal # Import SessionLocal
from models import ( # Import all necessary models
    User, Team, Player, Lineup, PitchingOuting, ScoutedPlayer,
    Rotation, Game, CollaborationNote, PracticePlan, PracticeTask,
    PlayerDevelopmentFocus, Sign
)
from sqlalchemy import create_engine
from sqlalchemy.inspection import inspect as sqlalchemy_inspect
from flask_socketio import SocketIO, emit # ADDED: Flask-SocketIO imports

app = Flask(__name__)
app.secret_key = 'xXxG#fjs72d_!z921!kJjkjsd123kfj3FJ!*kfdjf8s!jf9jKJJJd' # IMPORTANT: Change this to a strong, random key in production

# Set the permanent session lifetime to 30 days
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

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

# ADDED: Initialize Flask-SocketIO
socketio = SocketIO(app) # You can add cors_allowed_origins="*" here for local testing if needed: socketio = SocketIO(app, cors_allowed_origins="*")

# DATA_FILE and load_data/save_data functions are removed as data is now handled by the database.

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
        # UPDATED: Admin access now for 'Head Coach' and 'Super Admin'
        if session.get('role') not in ['Head Coach', 'Super Admin']:
            flash('You must be a Head Coach or Super Admin to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- AUTHENTICATION ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        db = SessionLocal() # Establish DB session
        try:
            username = request.form['username']
            password = request.form['password']

            user = db.query(User).filter(func.lower(User.username) == func.lower(username)).first() # Query user from DB case-insensitively
            
            if user and check_password_hash(user.password_hash, password):
                # UPDATED: Role migration logic
                if user.username.lower() == 'mike1825':
                    user.role = 'Super Admin'
                elif user.role == 'Admin': # Old Admin role becomes Head Coach
                    user.role = 'Head Coach'
                elif user.role == 'Coach': # Old Coach role becomes Assistant Coach
                    user.role = 'Assistant Coach'
                
                # This commit saves the role changes upon successful login
                user.last_login = datetime.now().strftime("%Y-%m-%d %H:%M")
                db.commit() # Commit changes to DB

                session['logged_in'] = True
                session['username'] = user.username # Use the username from DB to preserve casing
                session['full_name'] = user.full_name or '' # Handle potential None for full_name
                session['role'] = user.role
                session['team_id'] = user.team_id # Store team_id in session
                # Load player order for that team
                session['player_order'] = json.loads(user.player_order or "[]")
                session.permanent = True
                flash('You were successfully logged in.', 'success')
                return redirect(url_for('home'))
            else:
                flash('Invalid username or password.', 'danger')
        finally:
            db.close() # Close DB session
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('You were successfully logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    db = SessionLocal() # Establish DB session
    try:
        if request.method == 'POST':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_new_password = request.form.get('confirm_new_password')
            
            user = db.query(User).filter_by(username=session['username']).first() # Query user from DB
            
            if not user or not check_password_hash(user.password_hash, current_password):
                flash('Your current password was incorrect.', 'danger')
                return redirect(url_for('change_password'))
            if new_password != confirm_new_password:
                flash('New passwords do not match.', 'danger')
                return redirect(url_for('change_password'))
            if len(new_password) < 4:
                flash('New password must be at least 4 characters long.', 'danger')
                return redirect(url_for('change_password'))
            
            user.password_hash = generate_password_hash(new_password) # Update user object
            db.commit() # Commit changes to DB
            
            flash('Your password has been updated successfully!', 'success')
            return redirect(url_for('home'))
        return render_template('change_password.html')
    finally:
        db.close() # Close DB session

# --- NEW: Route for the pitching rules page ---
@app.route('/rules')
@login_required
def pitching_rules():
    return render_template('rules.html')

# --- PITCH COUNT AND REST CALCULATION HELPERS ---
def get_required_rest_days(pitches):
    """Calculates required rest days based on pitch count for 11-12u, following Pitch Smart guidelines."""
    if pitches >= 66:
        return 4
    elif pitches >= 51:
        return 3
    elif pitches >= 36:
        return 2
    elif pitches >= 21:
        return 1
    else: # 1-20 pitches
        return 0

def calculate_pitcher_availability(pitcher_name, all_outings):
    """Determines a pitcher's availability based on their most recent outing."""
    today = date.today()
    most_recent_outing = None

    # Find the most recent outing for the pitcher
    for outing in all_outings:
        if outing.pitcher == pitcher_name:
            try:
                outing_date = datetime.strptime(outing.date, '%Y-%m-%d').date()
                if most_recent_outing is None or outing_date > most_recent_outing['date']:
                    most_recent_outing = {'date': outing_date, 'pitches': int(outing.pitches)}
            except (ValueError, TypeError):
                continue

    if not most_recent_outing:
        return {'status': 'Available', 'next_available': 'Today'}

    rest_days_needed = get_required_rest_days(most_recent_outing['pitches'])
    next_available_date = most_recent_outing['date'] + timedelta(days=rest_days_needed + 1)

    if today >= next_available_date:
        return {'status': 'Available', 'next_available': 'Today'}
    else:
        return {'status': 'Resting', 'next_available': next_available_date.strftime('%Y-%m-%d')}

def calculate_pitch_counts(pitcher_name, all_outings):
    today = date.today()
    current_year = today.year
    start_of_week = today - timedelta(days=today.weekday())
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
    return counts

# --- MAIN AND ADMIN ROUTES ---
@app.route('/')
@login_required
def home():
    db = SessionLocal() # Establish DB session
    try:
        user = db.query(User).filter_by(username=session['username'], team_id=session['team_id']).first() # Query user from DB
        if not user:
            flash('User not found or not associated with a team.', 'danger')
            return redirect(url_for('login'))

        # Fetch data relevant to the user's team
        team_id = user.team_id
        
        # --- NEW: Name Display Logic ---
        all_users = db.query(User).filter_by(team_id=team_id).all()
        user_name_map = {u.username: (u.full_name or u.username) for u in all_users} # Default to username if full_name is None
        display_full_names = user.team.display_coach_names
        def get_display_name(username):
            if not username or username == 'N/A': return 'N/A'
            return user_name_map.get(username, username) if display_full_names else username
        # --- END NEW ---
        # Query all relevant data for the home page directly from the database
        roster_players = db.query(Player).filter_by(team_id=team_id).all()
        lineups = db.query(Lineup).filter_by(team_id=team_id).all()
        pitching_outings = db.query(PitchingOuting).filter_by(team_id=team_id).all()
        scouted_committed = db.query(ScoutedPlayer).filter_by(team_id=team_id, list_type='committed').all()
        scouted_targets = db.query(ScoutedPlayer).filter_by(team_id=team_id, list_type='targets').all()
        scouted_not_interested = db.query(ScoutedPlayer).filter_by(team_id=team_id, list_type='not_interested').all()
        rotations = db.query(Rotation).filter_by(team_id=team_id).all()
        games = db.query(Game).filter_by(team_id=team_id).all()
        collaboration_player_notes = db.query(CollaborationNote).filter_by(team_id=team_id, note_type='player_notes').all()
        collaboration_team_notes = db.query(CollaborationNote).filter_by(team_id=team_id, note_type='team_notes').all()
        practice_plans = db.query(PracticePlan).filter_by(team_id=team_id).order_by(PracticePlan.date.desc()).all() # Ordered by date
        signs = db.query(Sign).filter_by(team_id=team_id).all()
        player_development_focuses = db.query(PlayerDevelopmentFocus).filter_by(team_id=team_id).all()

        # <<< NEW: Unified Player Log Data Structure >>>
        player_activity_log = {}
        for player in roster_players:
            player_activity_log[player.name] = []

            # Add Development Focus activities
            for focus in player.development_focuses:
                player_activity_log[player.name].append({
                    'type': 'Development',
                    'subtype': focus.skill_type,
                    'date': focus.created_date,
                    'timestamp': datetime.strptime(focus.created_date, '%Y-%m-%d'),
                    'text': f"New Focus: {focus.focus}",
                    'notes': focus.notes,
                    'author': get_display_name(focus.author),
                    'status': focus.status,
                    'id': focus.id
                })
                if focus.status == 'completed' and focus.completed_date:
                     player_activity_log[player.name].append({
                        'type': 'Development',
                        'subtype': focus.skill_type,
                        'date': focus.completed_date,
                        'timestamp': datetime.strptime(focus.completed_date, '%Y-%m-%d'),
                        'text': f"Completed: {focus.focus}",
                        'notes': focus.notes,
                        'author': get_display_name(focus.last_edited_by or focus.author),
                        'status': focus.status,
                        'id': focus.id
                    })

            # Add Collaboration Note activities
            for note in collaboration_player_notes:
                if note.player_name == player.name:
                    ts_str = note.timestamp.split(' ')[0] # just date part for sorting
                    player_activity_log[player.name].append({
                        'type': 'Coach Note',
                        'subtype': 'Player Log',
                        'date': ts_str,
                        'timestamp': datetime.strptime(note.timestamp, '%Y-%m-%d %H:%M'),
                        'text': note.text,
                        'notes': None,
                        'author': get_display_name(note.author),
                        'status': 'active',
                        'id': note.id
                    })
            
            # Add Lesson Info activities
            if player.has_lessons == 'Yes' and player.lesson_focus:
                 player_activity_log[player.name].append({
                    'type': 'Lessons',
                    'subtype': 'Private Instruction',
                    'date': player.notes_timestamp.split(' ')[0] if player.notes_timestamp else 'N/A',
                    'timestamp': datetime.strptime(player.notes_timestamp, '%Y-%m-%d %H:%M') if player.notes_timestamp else datetime.min,
                    'text': f"Lesson Focus: {player.lesson_focus}",
                    'notes': None,
                    'author': 'N/A',
                    'status': 'active',
                    'id': player.id
                })

            # Sort the log for each player by timestamp descending
            player_activity_log[player.name].sort(key=lambda x: x['timestamp'], reverse=True)


        # Construct app_data dictionary mimicking the old data.json structure
        app_data = {
            "users": [], # Users info is not all needed in app_data normally, session has key info
            "roster": [{
                "name": p.name, "number": p.number, "position1": p.position1,
                "position2": p.position2, "position3": p.position3, "throws": p.throws,
                "bats": p.bats, "notes": p.notes, "pitcher_role": p.pitcher_role,
                "has_lessons": p.has_lessons, "lesson_focus": p.lesson_focus,                
                "notes_author": get_display_name(p.notes_author), "notes_timestamp": p.notes_timestamp,
                "id": p.id # Include ID for inline updates/deletes
            } for p in roster_players],
            "lineups": [{
                "id": l.id, # Include ID for updates/deletes
                "title": l.title,
                "lineup_positions": json.loads(l.lineup_positions or "[]"),
                "associated_game_id": l.associated_game_id
            } for l in lineups],
            "pitching": [{
                "id": po.id, # Include ID for updates/deletes
                "date": po.date, "pitcher": po.pitcher, "opponent": po.opponent,
                "pitches": po.pitches, "innings": po.innings,
                "pitcher_type": po.pitcher_type, "outing_type": po.outing_type
            } for po in pitching_outings],
            "scouting_list": {
                "committed": [{
                    "id": sp.id, # Include ID for updates/deletes
                    "name": sp.name, "position1": sp.position1,
                    "position2": sp.position2, "throws": sp.throws, "bats": sp.bats
                } for sp in scouted_committed],
                "targets": [{
                    "id": sp.id, # Include ID for updates/deletes
                    "name": sp.name, "position1": sp.position1,
                    "position2": sp.position2, "throws": sp.throws, "bats": sp.bats
                } for sp in scouted_targets],
                "not_interested": [{
                    "id": sp.id, # Include ID for updates/deletes
                    "name": sp.name, "position1": sp.position1,
                    "position2": sp.position2, "throws": sp.throws, "bats": sp.bats
                } for sp in scouted_not_interested]
            },
            "rotations": [{
                "id": r.id, # Include ID for updates/deletes
                "title": r.title,
                "innings": json.loads(r.innings or "{}"),
                "associated_game_id": r.associated_game_id
            } for r in rotations],
            "games": [{
                "id": g.id, # Include ID for updates/deletes
                "date": g.date, "opponent": g.opponent,
                "location": g.location, "game_notes": g.game_notes,
                "associated_lineup_title": g.associated_lineup_title,
                "associated_rotation_date": g.associated_rotation_date
            } for g in games],
            "feedback": [], # No Feedback model yet, or data in data.json
            "settings": {
                "registration_code": user.team.registration_code,
                "team_name": user.team.team_name
            },
            "collaboration_notes": {
                "player_notes": [{
                    "id": cn.id, "text": cn.text, "author": get_display_name(cn.author),
                    "timestamp": cn.timestamp, "player_name": cn.player_name
                } for cn in collaboration_player_notes],
                "team_notes": [{
                    "id": cn.id, "text": cn.text, "author": get_display_name(cn.author),
                    "timestamp": cn.timestamp
                } for cn in collaboration_team_notes]
            },
            "practice_plans": [{
                "id": pp.id, "date": pp.date, "general_notes": pp.general_notes,
                "tasks": [{ "id": pt.id, "text": pt.text, "status": pt.status, "author": get_display_name(pt.author), "timestamp": pt.timestamp } for pt in pp.tasks]
            } for pp in practice_plans],
            "player_development": player_activity_log, # <<< USE THE NEW UNIFIED LOG
            "signs": [{
                "id": s.id, "name": s.name, "indicator": s.indicator
            } for s in signs]
        }


        all_tabs = {
            'roster': 'Roster', 
            'player_development': 'Player Development',
            'lineups': 'Lineups', 
            'pitching': 'Pitching Log',
            'scouting_list': 'Scouting List', 
            'rotations': 'Rotations',
            'games': 'Games', 
            'collaboration': 'Coaches Log', 
            'practice_plan': 'Practice Plan',
            'signs': 'Signs'
        }
        default_tab_keys = list(all_tabs.keys())
        user_tab_order = json.loads(user.tab_order or "[]") if user.tab_order else default_tab_keys # Get from user object
        for key in default_tab_keys:
            if key not in user_tab_order and key in all_tabs:
                user_tab_order.append(key)
        user_tab_order = [key for key in user_tab_order if key in all_tabs]

        # Recalculate position_counts based on DB roster and scouted players
        all_players_for_count = roster_players + scouted_committed + scouted_targets
        position_counts = {}
        for player in all_players_for_count:
            pos = player.position1
            if pos:
                position_counts[pos] = position_counts.get(pos, 0) + 1

        # Pitch count summary using PitchingOuting model
        pitcher_names = sorted(list(set(po.pitcher for po in pitching_outings if po.pitcher)))
        pitch_count_summary = {}
        for name in pitcher_names:
            counts = calculate_pitch_counts(name, pitching_outings)
            availability = calculate_pitcher_availability(name, pitching_outings)
            # Combine counts and availability into one dictionary for the pitcher
            pitch_count_summary[name] = {**counts, **availability}
        
        return render_template('index.html', 
                               data=app_data, # Pass the constructed data
                               session=session, 
                               tab_order=user_tab_order, 
                               all_tabs=all_tabs,
                               position_counts=position_counts,
                               pitch_count_summary=pitch_count_summary)
    finally:
        db.close() # Close DB session

# --- PWA Service Routes ---
@app.route('/manifest.json')
def serve_manifest():
    """Serves the manifest.json file for PWA capabilities."""
    return send_from_directory('static', 'manifest.json')

@app.route('/service-worker.js')
def serve_sw():
    """Serves the service-worker.js file for PWA capabilities."""
    # It's good practice to set the mimetype for JS files.
    # The browser might be strict about this.
    return send_from_directory('static', 'service-worker.js', mimetype='application/javascript')


@app.route('/get_app_data')
@login_required
def get_app_data():
    """Provides the entire application data as a JSON object, now fetched from the database."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username=session['username'], team_id=session['team_id']).first()
        if not user:
            return jsonify({'status': 'error', 'message': 'User not found or not associated with a team.'}), 404

        team_id = user.team_id

        # --- NEW: Name Display Logic ---
        all_users = db.query(User).filter_by(team_id=team_id).all()
        user_name_map = {u.username: (u.full_name or u.username) for u in all_users} # Default to username if full_name is None
        display_full_names = user.team.display_coach_names
        def get_display_name(username):
            if not username or username == 'N/A': return 'N/A'
            return user_name_map.get(username, username) if display_full_names else username
        # --- END NEW ---
        
        # Fetch all data for the current team
        roster_players = db.query(Player).filter_by(team_id=team_id).all()
        lineups = db.query(Lineup).filter_by(team_id=team_id).all()
        pitching_outings = db.query(PitchingOuting).filter_by(team_id=team_id).all()
        scouted_committed = db.query(ScoutedPlayer).filter_by(team_id=team_id, list_type='committed').all()
        scouted_targets = db.query(ScoutedPlayer).filter_by(team_id=team_id, list_type='targets').all()
        scouted_not_interested = db.query(ScoutedPlayer).filter_by(team_id=team_id, list_type='not_interested').all()
        rotations = db.query(Rotation).filter_by(team_id=team_id).all()
        games = db.query(Game).filter_by(team_id=team_id).all()
        collaboration_player_notes = db.query(CollaborationNote).filter_by(team_id=team_id, note_type='player_notes').all()
        collaboration_team_notes = db.query(CollaborationNote).filter_by(team_id=team_id, note_type='team_notes').all()
        practice_plans = db.query(PracticePlan).filter_by(team_id=team_id).order_by(PracticePlan.date.desc()).all()
        signs = db.query(Sign).filter_by(team_id=team_id).all()


        # <<< NEW: Unified Player Log Data Structure (for get_app_data) >>>
        player_activity_log = {}
        for player in roster_players:
            player_activity_log[player.name] = []
            for focus in player.development_focuses:
                player_activity_log[player.name].append({'type': 'Development', 'subtype': focus.skill_type, 'date': focus.created_date, 'timestamp': datetime.strptime(focus.created_date, '%Y-%m-%d'), 'text': f"New Focus: {focus.focus}", 'notes': focus.notes, 'author': get_display_name(focus.author), 'status': focus.status, 'id': focus.id})
                if focus.status == 'completed' and focus.completed_date:
                     player_activity_log[player.name].append({'type': 'Development', 'subtype': focus.skill_type, 'date': focus.completed_date, 'timestamp': datetime.strptime(focus.completed_date, '%Y-%m-%d'), 'text': f"Completed: {focus.focus}", 'notes': focus.notes, 'author': get_display_name(focus.last_edited_by or focus.author), 'status': focus.status, 'id': focus.id})
            for note in collaboration_player_notes:
                if note.player_name == player.name:
                    ts_str = note.timestamp.split(' ')[0]
                    player_activity_log[player.name].append({'type': 'Coach Note', 'subtype': 'Player Log', 'date': ts_str, 'timestamp': datetime.strptime(note.timestamp, '%Y-%m-%d %H:%M'), 'text': note.text, 'notes': None, 'author': get_display_name(note.author), 'status': 'active', 'id': note.id})
            if player.has_lessons == 'Yes' and player.lesson_focus:
                 player_activity_log[player.name].append({'type': 'Lessons', 'subtype': 'Private Instruction', 'date': player.notes_timestamp.split(' ')[0] if player.notes_timestamp else 'N/A', 'timestamp': datetime.strptime(player.notes_timestamp, '%Y-%m-%d %H:%M') if player.notes_timestamp else datetime.min, 'text': f"Lesson Focus: {player.lesson_focus}", 'notes': None, 'author': 'N/A', 'status': 'active', 'id': player.id})
            player_activity_log[player.name].sort(key=lambda x: x['timestamp'], reverse=True)


        # Build app_data dictionary similar to data.json structure
        app_data = {
            'users': [], # Users info is not typically sent to frontend in full
            'roster': [{
                "name": p.name, "number": p.number, "position1": p.position1,
                "position2": p.position2, "position3": p.position3, "throws": p.throws,
                "bats": p.bats, "notes": p.notes, "pitcher_role": p.pitcher_role,
                "has_lessons": p.has_lessons, "lesson_focus": p.lesson_focus,                
                "notes_author": get_display_name(p.notes_author), "notes_timestamp": p.notes_timestamp,
                "id": p.id
            } for p in roster_players],
            'lineups': [{
                "id": l.id,
                "title": l.title,
                "lineup_positions": json.loads(l.lineup_positions or "[]"),
                "associated_game_id": l.associated_game_id
            } for l in lineups],
            'pitching': [{
                "id": po.id,
                "date": po.date, "pitcher": po.pitcher, "opponent": po.opponent,
                "pitches": po.pitches, "innings": po.innings,
                "pitcher_type": po.pitcher_type, "outing_type": po.outing_type
            } for po in pitching_outings],
            'scouting_list': {
                "committed": [{
                    "id": sp.id,
                    "name": sp.name, "position1": sp.position1,
                    "position2": sp.position2, "throws": sp.throws, "bats": sp.bats
                } for sp in scouted_committed],
                "targets": [{
                    "id": sp.id,
                    "name": sp.name, "position1": sp.position1,
                    "position2": sp.position2, "throws": sp.throws, "bats": sp.bats
                } for sp in scouted_targets],
                "not_interested": [{
                    "id": sp.id,
                    "name": sp.name, "position1": sp.position1,
                    "position2": sp.position2, "throws": sp.throws, "bats": sp.bats
                } for sp in scouted_not_interested]
            },
            'rotations': [{
                "id": r.id,
                "title": r.title,
                "innings": json.loads(r.innings or "{}"),
                "associated_game_id": r.associated_game_id
            } for r in rotations],
            'games': [{
                "id": g.id,
                "date": g.date, "opponent": g.opponent,
                "location": g.location, "game_notes": g.game_notes,
                "associated_lineup_title": g.associated_lineup_title,
                "associated_rotation_date": g.associated_rotation_date
            } for g in games],
            'feedback': [], # No Feedback model yet, or data in data.json
            'settings': {
                'registration_code': user.team.registration_code,
                'team_name': user.team.team_name
            },
            'collaboration_notes': {
                'player_notes': [{
                    "id": cn.id, "text": cn.text, "author": get_display_name(cn.author),
                    "timestamp": cn.timestamp, "player_name": cn.player_name
                } for cn in collaboration_player_notes],
                'team_notes': [{
                    "id": cn.id, "text": cn.text, "author": get_display_name(cn.author),
                    "timestamp": cn.timestamp
                } for cn in collaboration_team_notes]
            },
            'practice_plans': [{
                "id": pp.id, "date": pp.date, "general_notes": pp.general_notes,
                "tasks": [{ "id": pt.id, "text": pt.text, "status": pt.status, "author": get_display_name(pt.author), "timestamp": pt.timestamp } for pt in pp.tasks]
            } for pp in practice_plans],
            'player_development': player_activity_log, # <<< USE THE NEW UNIFIED LOG
            'signs': [{
                "id": s.id, "name": s.name, "indicator": s.indicator
            } for s in signs]
        }

        player_order = session.get('player_order', [p['name'] for p in app_data.get('roster', [])])
        
        pitcher_names = sorted(list(set(po.pitcher for po in pitching_outings if po.pitcher)))
        pitch_count_summary = {}
        for name in pitcher_names:
            counts = calculate_pitch_counts(name, pitching_outings)
            availability = calculate_pitcher_availability(name, pitching_outings)
            # Combine counts and availability into one dictionary for the pitcher
            pitch_count_summary[name] = {**counts, **availability}
        
        app_data_response = {
            'full_data': app_data,
            'player_order': player_order,
            'session': {
                'username': session.get('username'),
                'role': session.get('role'),
                'full_name': session.get('full_name')
            },
            'pitch_count_summary': pitch_count_summary
        }
        return jsonify(app_data_response)
    finally:
        db.close()

@app.route('/save_tab_order', methods=['POST'])
@login_required
def save_tab_order():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username=session['username']).first()
        if not user:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404
        new_order = request.json.get('order')
        if not isinstance(new_order, list):
            return jsonify({'status': 'error', 'message': 'Invalid order format'}), 400
        user.tab_order = json.dumps(new_order) # Store as JSON string
        db.commit()
        socketio.emit('data_updated', {'message': 'Tab order updated.'}) # ADDED: Emit Socket.IO event
        return jsonify({'status': 'success', 'message': 'Tab order saved.'})
    finally:
        db.close()

@app.route('/admin/users')
@admin_required
def user_management():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        return render_template('user_management.html', users=users, session=session)
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
        # UPDATED: Default role is now 'Assistant Coach'
        role = request.form.get('role', 'Assistant Coach')
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return redirect(url_for('user_management'))
        if db.query(User).filter(func.lower(User.username) == func.lower(username)).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('user_management'))
        
        # UPDATED: Security check for Super Admin role creation
        if role == 'Super Admin' and session.get('role') != 'Super Admin':
            flash('Only a Super Admin can create another Super Admin.', 'danger')
            return redirect(url_for('user_management'))
        hashed_password = generate_password_hash(password)
        default_tab_keys = ['roster', 'lineups', 'pitching', 'scouting_list', 'rotations', 'games', 'collaboration', 'practice_plan']
        
        # You'll need to decide how to assign a team_id for new users here.
        # For now, I'm assuming a default team_id (e.g., the first team created)
        # In a real app, you might have a team selection or invitation code.
        team = db.query(Team).first() # Assuming at least one team exists from migration
        if not team:
            flash('No team found. Please create a team first.', 'danger')
            return redirect(url_for('admin_settings'))

        new_user = User(
            username=username, 
            full_name=full_name,
            password_hash=hashed_password, 
            role=role, 
            tab_order=json.dumps(default_tab_keys), # Store as JSON string
            last_login='Never',
            team_id=team.id # Assign to the first team found
            # player_order will need to be handled based on your Player model relationships
        )
        db.add(new_user)
        db.commit()
        flash(f"User '{username}' created successfully as a {role}.", 'success')
        socketio.emit('data_updated', {'message': 'A new user was added.'}) # ADDED: Emit Socket.IO event
        return redirect(url_for('user_management'))
    finally:
        db.close()
    
@app.route('/admin/settings', methods=['GET'])
@admin_required
def admin_settings():
    db = SessionLocal()
    try:
        team_settings = db.query(Team).filter_by(id=session['team_id']).first()
        return render_template('admin_settings.html', session=session, settings=team_settings)
    finally:
        db.close()


@app.route('/admin/settings', methods=['POST'])
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
        # Add other settings here as they are implemented
        db.commit()
        flash('General settings updated successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Team settings updated.'})
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
        
        full_name = request.form.get('full_name')
        user_to_update.full_name = full_name
        db.commit()
        
        if session.get('username') == user_to_update.username:
            session['full_name'] = full_name
        
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
        # UPDATED: Prevent Super Admin from changing their own role (except if they are the only Super Admin)
        if user_to_change.username.lower() == 'mike1825':
            flash('You cannot change the role of the Super Admin.', 'danger')
            return redirect(url_for('user_management'))

        new_role = request.form.get('role')
        
        # UPDATED: Security check for Super Admin role assignment
        if new_role == 'Super Admin' and session.get('role') != 'Super Admin':
            flash('Only a Super Admin can assign the Super Admin role.', 'danger')
            return redirect(url_for('user_management'))
        # Prevent a Super Admin from changing their own role to something else if they are the only Super Admin
        if user_to_change.username == session['username'] and new_role != 'Super Admin' and \
           db.query(User).filter_by(role='Super Admin', team_id=session['team_id']).count() == 1:
            flash('You cannot demote yourself as the sole Super Admin. Assign another Super Admin first.', 'danger')
            return redirect(url_for('user_management'))


        # UPDATED: Define allowed roles
        if new_role in ['Head Coach', 'Assistant Coach', 'Game Changer', 'Super Admin']:
            user_to_change.role = new_role
            db.commit()
            flash(f"Successfully changed {username}'s role to {new_role}.", 'success')
            socketio.emit('data_updated', {'message': f"User {username}'s role changed."}) # ADDED: Emit Socket.IO event
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
        # UPDATED: Check for Mike1825 username specifically
        if username.lower() == 'mike1825':
            flash("The Super Admin cannot be deleted.", "danger")
            return redirect(url_for('user_management'))
        user_to_delete = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if user_to_delete:
            db.delete(user_to_delete)
            db.commit()
            flash(f"User '{username}' has been deleted.", "success")
            socketio.emit('data_updated', {'message': f"User {username} deleted."}) # ADDED: Emit Socket.IO event
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
        # UPDATED: Check for Mike1825 username specifically
        if username.lower() == 'mike1825':
            flash("The Super Admin's password cannot be reset via this interface.", "danger")
            return redirect(url_for('user_management'))
        user_to_reset = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if not user_to_reset:
            flash('User not found.', 'danger')
            return redirect(url_for('user_management'))
        temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        user_to_reset.password_hash = generate_password_hash(temp_password)
        db.commit()
        flash(f"Password for {username} has been reset. The temporary password is: {temp_password}", 'success')
        socketio.emit('data_updated', {'message': f"Password for {username} reset."}) # ADDED: Emit Socket.IO event
        return redirect(url_for('user_management'))
    finally:
        db.close()

# --- Player Development Routes ---
# This helper function will also need to be updated to query the database
# and will require a PlayerDevelopmentFocus model.
def find_focus_by_id(db_session, focus_id):
    return db_session.query(PlayerDevelopmentFocus).filter_by(id=focus_id).first()


@app.route('/save_player_order', methods=['POST'])
@login_required
def save_player_order():
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username=session['username']).first()
        if not user:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404
        
        new_order = request.json.get('player_order')
        if not isinstance(new_order, list):
            return jsonify({'status': 'error', 'message': 'Invalid order format'}), 400

        user.player_order = json.dumps(new_order)
        session['player_order'] = new_order
        session.modified = True
        db.commit()
        socketio.emit('data_updated', {'message': 'Player order saved.'}) # ADDED: Emit Socket.IO event
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
            player_id=player.id,
            skill_type=skill,
            focus=focus_text,
            status="active",
            notes=request.form.get('notes', ''),
            author=session['username'],
            created_date=date.today().strftime('%Y-%m-%d'),
            completed_date=None,
            last_edited_by="",
            last_edited_date="",
            team_id=session['team_id']
        )
        db.add(new_focus)
        db.commit()
        flash(f'New {skill} focus added for {player_name}.', 'success')
        socketio.emit('data_updated', {'message': f'New focus added for {player_name}.'}) # ADDED: Emit Socket.IO event
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
        socketio.emit('data_updated', {'message': 'Focus item updated.'}) # ADDED: Emit Socket.IO event
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
        socketio.emit('data_updated', {'message': 'Focus marked complete.'}) # ADDED: Emit Socket.IO event
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
            socketio.emit('data_updated', {'message': 'Focus deleted.'}) # ADDED: Emit Socket.IO event
        else:
            flash('Could not find the focus item to delete or you do not have permission.', 'danger')
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()


@app.route('/update_lesson_info/<int:player_id>', methods=['POST']) # CHANGED: from player_name to player_id
@login_required
def update_lesson_info(player_id):
    db = SessionLocal()
    try:
        player = db.query(Player).filter_by(id=player_id, team_id=session['team_id']).first() # CHANGED: filter_by id
        if not player:
            flash('Player not found.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))

        player.has_lessons = request.form.get('has_lessons')
        player.lesson_focus = request.form.get('lesson_focus')
        player.notes_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        db.commit()
        flash(f'Lesson info for {player.name} updated.', 'success')
        socketio.emit('data_updated', {'message': f'Lesson info for {player.name} updated.'}) # ADDED: Emit Socket.IO event
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@app.route('/delete_lesson_info/<int:player_id>') # CHANGED: from player_name to player_id
@login_required
def delete_lesson_info(player_id):
    db = SessionLocal()
    try:
        player = db.query(Player).filter_by(id=player_id, team_id=session['team_id']).first() # CHANGED: filter_by id
        if not player:
            flash('Player not found.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))

        player.has_lessons = 'No'
        player.lesson_focus = ''
        db.commit()
        flash(f'Lesson info for {player.name} has been deleted.', 'success')
        socketio.emit('data_updated', {'message': f'Lesson info for {player.name} deleted.'}) # ADDED: Emit Socket.IO event
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

# --- Roster and Player Routes ---
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

        # Prevent creating a duplicate player name on edit for the same team
        if new_name != original_name and db.query(Player).filter_by(name=new_name, team_id=session['team_id']).first():
            return jsonify({'status': 'error', 'message': f'Player name "{new_name}" already exists.'}), 400

        player_number_str = request.form.get('number', player_to_edit.number)
        try:
            player_number = player_number_str if player_number_str else ''
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Player number must be a valid integer.'}), 400

        player_to_edit.name = new_name
        player_to_edit.number = player_number
        player_to_edit.position1 = request.form.get('position1', player_to_edit.position1)
        player_to_edit.position2 = request.form.get('position2', player_to_edit.position2)
        player_to_edit.position3 = request.form.get('position3', player_to_edit.position3)
        player_to_edit.throws = request.form.get('throws', player_to_edit.throws)
        player_to_edit.bats = request.form.get('bats', player_to_edit.bats)
        player_to_edit.notes = request.form.get('notes', player_to_edit.notes)
        player_to_edit.pitcher_role = request.form.get('pitcher_role', player_to_edit.pitcher_role)
        player_to_edit.notes_author = session['username']
        player_to_edit.notes_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Update player_order in users if name changed
        if original_name != new_name:
            # Update player_development focuses for the renamed player
            # Note: PlayerDevelopmentFocus model does not directly store player_name, but player_id.
            # No direct update needed on player_development_focuses table, as it's linked by player_id.
            # The reconstruction in get_app_data will automatically use the new name.
            
            for user_obj in db.query(User).filter_by(team_id=session['team_id']).all():
                current_order = json.loads(user_obj.player_order or "[]")
                updated_order = [new_name if name == original_name else name for name in current_order]
                user_obj.player_order = json.dumps(updated_order)
            
            # Update current session player_order
            session['player_order'] = [new_name if name == original_name else name for name in session.get('player_order', [])]
            session.modified = True

        db.commit()
        socketio.emit('data_updated', {'message': f'Player {new_name} updated.'}) # ADDED: Emit Socket.IO event
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
            
            # Remove player from all user player_order lists for this team
            for user_obj in db.query(User).filter_by(team_id=session['team_id']).all():
                current_order = json.loads(user_obj.player_order or "[]")
                updated_order = [name for name in current_order if name != player_name]
                user_obj.player_order = json.dumps(updated_order)
            
            # Remove the player from the current session's player_order
            if 'player_order' in session:
                session['player_order'] = [name for name in session['player_order'] if name != player_name]
                session.modified = True 

            db.commit()
            flash(f'Player "{player_name}" removed successfully!', 'success')
            socketio.emit('data_updated', {'message': f'Player {player_name} deleted.'}) # ADDED: Emit Socket.IO event
        else:
            flash('Player not found.', 'danger')
        return redirect(url_for('home', _anchor=request.args.get('active_tab', 'roster').lstrip('#')))
    finally:
        db.close()


# <<< REMOVED: The redundant edit_player route is no longer needed. >>>


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
            # <<< MODIFIED: Redirect back to the correct anchor
            return redirect(url_for('home', _anchor='pitching'))
        
        new_outing = PitchingOuting(
            date=request.form['pitch_date'],
            pitcher=request.form['pitcher'], # Consider linking to player_id later
            opponent=request.form['opponent'],
            pitches=pitch_count,
            innings=innings_pitched,
            pitcher_type=request.form.get('pitcher_type', 'Starter'),
            outing_type=request.form.get('outing_type', 'Game'),
            team_id=session['team_id']
        )
        db.add(new_outing)
        db.commit()
        flash(f'Pitching outing for "{new_outing.pitcher}" added successfully!', 'success')
        socketio.emit('data_updated', {'message': 'New pitching outing added.'})
        
        # <<< MODIFIED: Redirect back to referring page or game page if applicable
        # This is a simple implementation. A more robust one might pass a `next` URL.
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
            socketio.emit('data_updated', {'message': 'Pitching outing deleted.'}) # ADDED: Emit Socket.IO event
        else:
            flash('Pitching outing not found.', 'danger')
        
        # <<< MODIFIED: Redirect back to referring page
        # This allows deleting from home or the new game management page
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
            new_sign = Sign(
                name=sign_name,
                indicator=sign_indicator,
                team_id=session['team_id']
            )
            db.add(new_sign)
            db.commit()
            flash('Sign added successfully!', 'success')
            socketio.emit('data_updated', {'message': 'New sign added.'}) # ADDED: Emit Socket.IO event
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
            socketio.emit('data_updated', {'message': 'Sign updated.'}) # ADDED: Emit Socket.IO event
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
            socketio.emit('data_updated', {'message': 'Sign deleted.'}) # ADDED: Emit Socket.IO event
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
                rotation_to_update.innings = json.dumps(innings_data) # Store as JSON string
                rotation_to_update.associated_game_id = associated_game_id
                message = 'Rotation updated successfully!'
                new_rotation_id = rotation_id
            else:
                rotation_id = None # Treat as new if ID not found for this team
        
        if not rotation_id:
            new_rotation = Rotation(
                title=title,
                innings=json.dumps(innings_data), # Store as JSON string
                associated_game_id=associated_game_id,
                team_id=session['team_id']
            )
            db.add(new_rotation)
            db.commit() # Commit to get the ID
            new_rotation_id = new_rotation.id
            message = 'Rotation saved successfully!'

        db.commit() # Commit again if updated, or initial commit already done for new
        socketio.emit('data_updated', {'message': 'Rotation saved/updated.'}) # ADDED: Emit Socket.IO event
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
            socketio.emit('data_updated', {'message': 'Rotation deleted.'}) # ADDED: Emit Socket.IO event
        else:
            flash('Rotation not found.', 'danger')
        
        # <<< MODIFIED: Redirect back to referring page
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
        
        new_note = CollaborationNote(
            note_type=note_type,
            text=note_text,
            author=session['username'],
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
            team_id=session['team_id']
        )

        if note_type == 'player_notes':
            player_name = request.form.get('player_name')
            if not player_name:
                flash('You must select a player.', 'warning')
                return redirect(url_for('home', _anchor='collaboration'))
            new_note.player_name = player_name # Assign player name
        
        db.add(new_note)
        db.commit()
        flash('Note added successfully!', 'success')
        socketio.emit('data_updated', {'message': 'New note added.'}) # ADDED: Emit Socket.IO event
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
            
        if session['username'] == note_to_edit.author or session.get('role') in ['Head Coach', 'Super Admin']: # UPDATED: Admin role check
            note_to_edit.text = new_text
            db.commit()
            flash('Note updated successfully.', 'success')
            socketio.emit('data_updated', {'message': 'Note updated.'}) # ADDED: Emit Socket.IO event
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
            if session['username'] == note_to_delete.author or session.get('role') in ['Head Coach', 'Super Admin']: # UPDATED: Admin role check
                db.delete(note_to_delete)
                db.commit()
                flash('Note deleted successfully.', 'success')
                socketio.emit('data_updated', {'message': 'Note deleted.'}) # ADDED: Emit Socket.IO event
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
        
        new_plan = PracticePlan(
            date=plan_date,
            general_notes=request.form.get('general_notes', ''),
            team_id=session['team_id']
        )
        db.add(new_plan)
        db.commit()
        flash('New practice plan created!', 'success')
        socketio.emit('data_updated', {'message': 'New practice plan created.'}) # ADDED: Emit Socket.IO event
        return redirect(url_for('home', _anchor='practice_plan'))
    finally:
        db.close()

# MODIFIED: This route now handles asynchronous JavaScript requests
@app.route('/add_task_to_plan/<int:plan_id>', methods=['POST'])
@login_required
def add_task_to_plan(plan_id):
    db = SessionLocal()
    try:
        # Check if the request is from our async JavaScript call
        if request.is_json:
            data = request.get_json()
            task_text = data.get('task_text')
        else: # This is now a fallback
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
        
        new_task = PracticeTask(
            text=task_text,
            status="pending",
            author=session['username'],
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
            practice_plan_id=plan.id
        )
        db.add(new_task)
        db.commit()

        # Emit socket event so all connected clients update automatically
        socketio.emit('data_updated', {'message': 'Task added to plan.'})
        
        # If the request was from our JavaScript, return a success message
        if request.is_json:
            return jsonify({'status': 'success', 'message': 'Task added.'})
        
        # Fallback for any non-JavaScript submissions
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
            socketio.emit('data_updated', {'message': 'Task deleted from plan.'}) # ADDED: Emit Socket.IO event
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
        socketio.emit('data_updated', {'message': 'Task status updated.'}) # ADDED: Emit Socket.IO event
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
            
            # Create a new PracticeTask from the CollaborationNote
            new_task = PracticeTask(
                text=note_to_move.text,
                status="pending",
                author=note_to_move.author,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
                practice_plan_id=plan.id
            )
            db.add(new_task)
            db.delete(note_to_move) # Delete the original note
            db.commit()
            flash('Note successfully moved to practice plan and original deleted.', 'success')
            socketio.emit('data_updated', {'message': 'Note moved to practice plan.'}) # ADDED: Emit Socket.IO event
            return redirect(url_for('home', _anchor='practice_plan'))
        
        # For GET request, display the note and available plans
        practice_plans = db.query(PracticePlan).filter_by(team_id=session['team_id']).all()
        return render_template('move_note_to_plan.html', note=note_to_move, practice_plans=practice_plans, note_type=note_type, note_id=note_id)
    finally:
        db.close()


# --- Scouting and Recruiting Routes ---
@app.route('/add_scouted_player', methods=['POST'])
@login_required
def add_scouted_player():
    """
    Handles adding a new scouted player via an API-style request.
    Accepts JSON data and returns a JSON response.
    """
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
            name=player_name,
            position1=data.get('scouted_player_pos1', ''),
            position2=data.get('scouted_player_pos2', ''),
            throws=data.get('scouted_player_throws', ''),
            bats=data.get('scouted_player_bats', ''),
            list_type=scouted_player_type,
            team_id=session['team_id']
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
            socketio.emit('data_updated', {'message': f'Scouted player {player_name} removed.'}) # ADDED: Emit Socket.IO event
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
        if from_type not in ['committed', 'targets', 'not_interested'] or \
           to_type not in ['committed', 'targets', 'not_interested']:
            flash('Invalid list type.', 'danger')
            return redirect(url_for('home', _anchor='scouting_list'))

        player_to_move = db.query(ScoutedPlayer).filter_by(id=player_id, list_type=from_type, team_id=session['team_id']).first()

        if player_to_move:
            player_to_move.list_type = to_type
            db.commit()
            flash(f'Player "{player_to_move.name}" moved to {to_type.replace("_", " ").title()} list.', 'success')
            socketio.emit('data_updated', {'message': f'Scouted player {player_to_move.name} moved.'}) # ADDED: Emit Socket.IO event
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

        # Prevent adding a player who already exists on the roster
        if db.query(Player).filter_by(name=scouted_player.name, team_id=session['team_id']).first():
            flash(f'Cannot move "{scouted_player.name}" to roster because a player with that name already exists.', 'danger')
            return redirect(url_for('home', _anchor='scouting_list'))

        new_roster_player = Player(
            name=scouted_player.name,
            number="", # Number is typically assigned later
            position1=scouted_player.position1,
            position2=scouted_player.position2,
            position3="",
            throws=scouted_player.throws,
            bats=scouted_player.bats,
            notes="",
            pitcher_role="Not a Pitcher",
            has_lessons="No",
            lesson_focus="",
            notes_author=session['username'], # User who moved to roster
            notes_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
            team_id=session['team_id']
        )
        db.add(new_roster_player)
        db.delete(scouted_player) # Remove from scouting_list

        # Add the new player name to all user player_order lists for this team
        for user_obj in db.query(User).filter_by(team_id=session['team_id']).all():
            current_order = json.loads(user_obj.player_order or "[]")
            if new_roster_player.name not in current_order:
                current_order.append(new_roster_player.name)
                user_obj.player_order = json.dumps(current_order)

        # Add the new player to the current session's player_order
        if 'player_order' in session and new_roster_player.name not in session['player_order']:
            session['player_order'].append(new_roster_player.name)
            session.modified = True 

        db.commit()
        flash(f'Player "{new_roster_player.name}" moved to Roster. Please assign a number.', 'success')
        socketio.emit('data_updated', {'message': f'Scouted player {new_roster_player.name} moved to roster.'}) # ADDED: Emit Socket.IO event
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
            date=request.form['game_date'],
            opponent=request.form['game_opponent'],
            location=request.form.get('game_location', ''),
            game_notes=request.form.get('game_notes', ''),
            associated_lineup_title=request.form.get('associated_lineup_title', ''),
            associated_rotation_date=request.form.get('associated_rotation_date', ''),
            team_id=session['team_id']
        )
        db.add(new_game)
        db.commit()
        flash(f'Game vs "{new_game.opponent}" on {new_game.date} added successfully!', 'success')
        socketio.emit('data_updated', {'message': 'New game added.'})
        # <<< MODIFIED: Redirect to the new game management page
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
            socketio.emit('data_updated', {'message': 'Game deleted.'}) # ADDED: Emit Socket.IO event
        else:
            flash('Game not found.', 'danger')
        return redirect(url_for('home', _anchor='games'))
    finally:
        db.close()


def _sync_lineup_to_rotation(db, lineup):
    """Helper to sync a lineup's positions to inning 1 of a game's rotation."""
    if not lineup.associated_game_id:
        return # Nothing to do if not linked to a game

    game = db.query(Game).filter_by(id=lineup.associated_game_id, team_id=lineup.team_id).first()
    if not game:
        return # Game not found

    lineup_positions = json.loads(lineup.lineup_positions or "[]")
    inning_1_data = {item['position']: item['name'] for item in lineup_positions if item.get('position') and item.get('name')}

    if not inning_1_data:
        return # Don't sync an empty lineup

    rotation_for_game = db.query(Rotation).filter_by(associated_game_id=game.id, team_id=lineup.team_id).first()

    if rotation_for_game:
        # Update existing rotation
        current_innings = json.loads(rotation_for_game.innings or "{}")
        current_innings['1'] = inning_1_data
        rotation_for_game.innings = json.dumps(current_innings)
    else:
        # Create new rotation
        new_rotation = Rotation(
            title=f"vs {game.opponent} ({game.date})",
            associated_game_id=game.id,
            innings=json.dumps({'1': inning_1_data}),
            team_id=lineup.team_id
        )
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
            title=payload['title'],
            lineup_positions=json.dumps(payload['lineup_data']), # Store as JSON string
            associated_game_id=int(payload['associated_game_id']) if payload.get('associated_game_id') else None,
            team_id=session['team_id']
        )
        db.add(new_lineup)

        # Sync to rotation if associated with a game
        _sync_lineup_to_rotation(db, new_lineup)
        db.commit()
        socketio.emit('data_updated', {'message': 'New lineup added.'}) # ADDED: Emit Socket.IO event
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
        
        # Sync to rotation if associated with a game
        _sync_lineup_to_rotation(db, lineup_to_edit)

        db.commit()
        socketio.emit('data_updated', {'message': 'Lineup updated.'}) # ADDED: Emit Socket.IO event
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
            socketio.emit('data_updated', {'message': 'Lineup deleted.'}) # ADDED: Emit Socket.IO event
        else:
            flash('Lineup not found.', 'danger')
        
        # <<< MODIFIED: Redirect back to referring page
        redirect_url = request.referrer or url_for('home', _anchor='lineups')
        return redirect(redirect_url)
    finally:
        db.close()


# <<< NEW: Game Management Route >>>
@app.route('/game/<int:game_id>')
@login_required
def game_management(game_id):
    db = SessionLocal()
    try:
        team_id = session['team_id']
        game = db.query(Game).filter_by(id=game_id, team_id=team_id).first()
        if not game:
            flash('Game not found.', 'danger')
            return redirect(url_for('home', _anchor='games'))

        # --- DATA PREPARATION FOR TEMPLATE ---
        
        # Prepare Game data
        game_dict = {
            "id": game.id, "date": game.date, "opponent": game.opponent, 
            "location": game.location, "game_notes": game.game_notes
        }

        # Prepare Roster data
        roster_objects = db.query(Player).filter_by(team_id=team_id).all()
        roster_list = [
            {"id": p.id, "name": p.name, "number": p.number, "position1": p.position1, 
             "position2": p.position2, "position3": p.position3, "throws": p.throws, "bats": p.bats}
            for p in roster_objects
        ]
        
        # Prepare Lineup data
        lineup_obj = db.query(Lineup).filter_by(associated_game_id=game.id, team_id=team_id).first()
        if lineup_obj:
            lineup_dict = {
                "id": lineup_obj.id, "title": lineup_obj.title,
                "lineup_positions": json.loads(lineup_obj.lineup_positions or "[]"),
                "associated_game_id": lineup_obj.associated_game_id
            }
        else:
            lineup_dict = {
                "id": None, "title": f"Lineup for vs {game.opponent}", 
                "lineup_positions": [], "associated_game_id": game.id
            }

        # Prepare Rotation data
        rotation_obj = db.query(Rotation).filter_by(associated_game_id=game.id, team_id=team_id).first()
        if rotation_obj:
            rotation_dict = {
                "id": rotation_obj.id, "title": rotation_obj.title,
                "innings": json.loads(rotation_obj.innings or "{}"),
                "associated_game_id": rotation_obj.associated_game_id
            }
        else:
            rotation_dict = {
                "id": None, "title": f"Rotation for vs {game.opponent}", 
                "innings": {}, "associated_game_id": game.id
            }
        
        # Fetch other data needed for the page
        pitching_outings = db.query(PitchingOuting).filter_by(team_id=team_id).all()
        pitcher_names = sorted(list(set(p["name"] for p in roster_list)))
        pitch_count_summary = {}
        for name in pitcher_names:
            counts = calculate_pitch_counts(name, pitching_outings)
            availability = calculate_pitcher_availability(name, pitching_outings)
            pitch_count_summary[name] = {**counts, **availability}
        
        game_pitching_log = [p for p in pitching_outings if p.opponent == game.opponent and p.date == game.date]

        return render_template('game_management.html',
                               game=game_dict,
                               roster=roster_list,
                               lineup=lineup_dict,
                               rotation=rotation_dict,
                               pitch_count_summary=pitch_count_summary,
                               game_pitching_log=game_pitching_log,
                               session=session)
    finally:
        db.close()


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
        # <<< MODIFIED: Redirect back to the game management page
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
            # Delete associated tasks first
            db.query(PracticeTask).filter_by(practice_plan_id=plan_to_delete.id).delete()
            db.delete(plan_to_delete)
            db.commit()
            flash('Practice plan deleted successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Practice plan deleted.'}) # ADDED: Emit Socket.IO event
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
                socketio.emit('data_updated', {'message': 'Practice plan updated.'}) # ADDED: Emit Socket.IO event
        else:
            flash('Practice plan not found.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
    finally:
        db.close()


if __name__ == '__main__':
    # Run a check to ensure the database is set up before starting the app.
    check_database_initialized()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False) # CHANGED: Use socketio.run()