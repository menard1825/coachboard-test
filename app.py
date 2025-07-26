from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
import json
import os
from datetime import datetime, timedelta, date
from functools import wraps

# Database and Model Imports
from db import SessionLocal
from models import (
    User, Team, Player, Lineup, PitchingOuting, ScoutedPlayer,
    Rotation, Game, CollaborationNote, PracticePlan, PracticeTask,
    PlayerDevelopmentFocus, Sign, PlayerGameAbsence
)
from sqlalchemy import create_engine
from sqlalchemy.orm import joinedload, selectinload
from flask_socketio import SocketIO

# --- Blueprint Imports ---
from blueprints.auth import auth_bp
from blueprints.admin import admin_bp
from blueprints.roster import roster_bp
from blueprints.development import development_bp
from blueprints.gameday import gameday_bp
from blueprints.pitching import pitching_bp
from blueprints.scouting import scouting_bp
from blueprints.team_management import team_management_bp

app = Flask(__name__)
app.secret_key = 'xXxG#fjs72d_!z921!kJjkjsd123kfj3FJ!*kfdjf8s!jf9jKJJJd'
socketio = SocketIO(app)

# --- App Configuration ---
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'logos')
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

# --- Register Blueprints ---
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(roster_bp)
app.register_blueprint(development_bp)
app.register_blueprint(gameday_bp)
app.register_blueprint(pitching_bp)
app.register_blueprint(scouting_bp)
app.register_blueprint(team_management_bp)


# --- PITCHING RULES ENGINE (Core Business Logic) ---
PITCHING_RULES = {
    'USSSA': {
        'default': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '10U': {'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '11U': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '12U': {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3)]},
        '13U': {'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (75, 3)]},
        '14U': {'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (75, 3)]},
    }
}

# --- ROLE CONSTANTS ---
SUPER_ADMIN = 'Super Admin'
HEAD_COACH = 'Head Coach'
ASSISTANT_COACH = 'Assistant Coach'
GAME_CHANGER = 'Game Changer'


# --- Helper functions ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']
           

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
def get_pitching_rules_for_team(team):
    rule_set_name = getattr(team, 'pitching_rule_set', 'USSSA') or 'USSSA'
    age_group = getattr(team, 'age_group', 'default') or 'default'
    rule_set = PITCHING_RULES.get(rule_set_name, PITCHING_RULES['USSSA'])
    return rule_set.get(age_group, rule_set.get('default'))

def get_required_rest_days(pitches, team):
    rules = get_pitching_rules_for_team(team)
    for max_pitches, rest_days in rules['rest_thresholds']:
        if pitches <= max_pitches:
            return rest_days
    return rules['rest_thresholds'][-1][1] + 1

def calculate_pitcher_availability(pitcher_name, all_outings, team):
    today = date.today()
    pitcher_outings = [o for o in all_outings if o.pitcher == pitcher_name]
    if not pitcher_outings:
        return {'status': 'Available', 'next_available': 'Today'}
    outings_by_date = {}
    for outing in pitcher_outings:
        try:
            outing_date = datetime.strptime(outing.date, '%Y-%m-%d').date()
            outings_by_date.setdefault(outing_date, 0)
            outings_by_date[outing_date] += int(outing.pitches)
        except (ValueError, TypeError):
            continue
    if not outings_by_date:
        return {'status': 'Available', 'next_available': 'Today'}
    most_recent_pitching_date = max(outings_by_date.keys())
    total_pitches_on_last_day = outings_by_date[most_recent_pitching_date]
    rest_days_needed = get_required_rest_days(total_pitches_on_last_day, team)
    next_available_date = most_recent_pitching_date + timedelta(days=rest_days_needed + 1)
    return {'status': 'Available', 'next_available': 'Today'} if today >= next_available_date else {'status': 'Resting', 'next_available': next_available_date.strftime('%Y-%m-%d')}

def calculate_pitch_counts(pitcher_name, all_outings, team):
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

def _get_full_team_data(db, team_id, current_user):
    team = db.query(Team).options(
        selectinload(Team.users),
        selectinload(Team.players).selectinload(Player.development_focuses),
        selectinload(Team.collaboration_notes),
        selectinload(Team.practice_plans).selectinload(PracticePlan.tasks)
    ).filter_by(id=team_id).first()

    if not team:
        return {}, [], [], []

    user_name_map = {u.username: (u.full_name or u.username) for u in team.users}
    display_full_names = team.display_coach_names
    def get_display_name(username):
        if not username or username == 'N/A': return 'N/A'
        return user_name_map.get(username, username) if display_full_names else username

    lineups = db.query(Lineup).filter_by(team_id=team_id).all()
    pitching_outings = db.query(PitchingOuting).filter_by(team_id=team_id).all()
    scouted_players = db.query(ScoutedPlayer).filter_by(team_id=team_id).all()
    rotations = db.query(Rotation).filter_by(team_id=team_id).all()
    games = db.query(Game).filter_by(team_id=team_id).all()
    signs = db.query(Sign).filter_by(team_id=team_id).all()
    
    player_activity_log = {}
    collaboration_player_notes = [n for n in team.collaboration_notes if n.note_type == 'player_notes']
    
    for player in team.players:
        log_entries = []
        for focus in player.development_focuses:
            log_entries.append({
                'type': 'Development', 'subtype': focus.skill_type, 'id': focus.id,
                'timestamp': f"{focus.created_date} 00:00:00",
                'date': focus.created_date, 'text': focus.focus, 'notes': focus.notes,
                'author': get_display_name(focus.author), 'status': focus.status,
                'completed_date': focus.completed_date
            })
        for note in collaboration_player_notes:
            if note.player_name == player.name:
                log_entries.append({
                    'type': 'Coach Note', 'subtype': 'Player Log', 'id': note.id,
                    'timestamp': note.timestamp or '1970-01-01 00:00:00',
                    'date': note.timestamp.split(' ')[0] if note.timestamp else 'N/A',
                    'text': note.text, 'notes': None, 'author': get_display_name(note.author),
                    'status': 'active'
                })
        if player.has_lessons == 'Yes' and player.lesson_focus:
            log_entries.append({
                'type': 'Lessons', 'subtype': 'Private Instruction', 'id': player.id,
                'timestamp': player.notes_timestamp or '1970-01-01 00:00:00',
                'date': player.notes_timestamp.split(' ')[0] if player.notes_timestamp else 'N/A',
                'text': player.lesson_focus, 'notes': None, 'author': 'N/A',
                'status': 'active'
            })
            
        player_activity_log[player.name] = sorted(log_entries, key=lambda x: x.get('timestamp', ''), reverse=True)
    
    scouting_list_grouped = {'committed': [], 'targets': [], 'not_interested': []}
    for sp in scouted_players:
        if sp.list_type in scouting_list_grouped:
            scouting_list_grouped[sp.list_type].append(sp.to_dict())

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


# --- CORE APP ROUTES ---

@app.route('/')
@login_required
def home():
    db = SessionLocal()
    try:
        user = db.query(User).options(joinedload(User.team)).filter_by(username=session['username'], team_id=session['team_id']).first()
        if not user or not user.team:
            flash('User not found or not associated with a team.', 'danger')
            return redirect(url_for('auth.login'))
        
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

        app_data_response = {
            'full_data': app_data, 
            'player_order': player_order, 
            'session': {'username': session.get('username'), 'role': session.get('role'), 'full_name': session.get('full_name')}, 
            'pitch_count_summary': pitch_count_summary
        }
        return jsonify(app_data_response)
    finally:
        db.close()

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'logo.png', mimetype='image/png')
                               
@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/service-worker.js')
def serve_sw():
    return send_from_directory('static', 'service-worker.js', mimetype='application/javascript')

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


# --- Main execution block ---
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5002, debug=True)