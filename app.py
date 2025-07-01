from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import json
import os
from datetime import datetime, timedelta, date
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import time
import random
import string

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here' # IMPORTANT: Change this to a strong, random key in production

# Set the permanent session lifetime to 30 days
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

DATA_FILE = 'data.json'

def load_data():
    default_data = {
        "users": [], "roster": [], "lineups": [], "pitching": [],
        "scouting_list": {"committed": [], "targets": [], "not_interested": []},
        "rotations": [], "games": [], "feedback": [],
        "settings": {"registration_code": "DEFAULT_CODE"},
        "collaboration_notes": {"player_notes": [], "team_notes": []},
        "practice_plans": [],
        "player_development": {}, # NEW: For Hitting, Fielding, etc. focus
        "signs": [] # NEW: For team signs
    }
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump(default_data, f, indent=4)
        return default_data
        
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return default_data

    # Ensure all top-level keys from default_data exist
    for key, value in default_data.items():
        data.setdefault(key, value)

    # --- Data Migrations ---
    for user in data['users']:
        if 'role' not in user:
            user['role'] = 'Admin' if user['username'] == 'Mike1825' else 'Coach'
        if 'tab_order' not in user:
            default_tab_keys = list(default_data.keys())
            tabs_to_exclude = ['users', 'feedback', 'settings', 'player_development']
            user['tab_order'] = [key for key in default_tab_keys if key not in tabs_to_exclude]

    if 'rotations' in data:
        for rotation in data['rotations']:
            if 'positions' in rotation and 'innings' not in rotation:
                rotation['innings'] = {'1': rotation.pop('positions')}
            elif 'innings' not in rotation:
                rotation['innings'] = {}
    
    for player in data.get('roster', []):
        player.setdefault('position3', '')
        player.setdefault('has_lessons', 'No')
        player.setdefault('lesson_focus', '')

    if 'roster' in data and 'player_development' in data:
        roster_names = {p['name'] for p in data['roster']}
        for name in roster_names:
            if name not in data['player_development']:
                data['player_development'][name] = {
                    "hitting": "", "pitching": "", "fielding": "", "baserunning": ""
                }
    return data

def save_data(data):
    if 'practice_plans' in data:
        data['practice_plans'].sort(key=lambda x: x.get('date', ''), reverse=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

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
        if session.get('role') != 'Admin':
            flash('You must be an admin to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- AUTHENTICATION ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = load_data()
        username = request.form['username']
        password = request.form['password']
        user = next((u for u in data.get('users', []) if u['username'] == username), None)
        
        if user and 'password_hash' in user and check_password_hash(user['password_hash'], password):
            session['logged_in'] = True
            session['username'] = username
            session['role'] = user.get('role', 'Coach')
            session.permanent = True
            flash('You were successfully logged in.', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password.', 'danger')
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
    if request.method == 'POST':
        data = load_data()
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_new_password = request.form.get('confirm_new_password')
        user = next((u for u in data['users'] if u['username'] == session['username']), None)
        if not user or not check_password_hash(user['password_hash'], current_password):
            flash('Your current password was incorrect.', 'danger')
            return redirect(url_for('change_password'))
        if new_password != confirm_new_password:
            flash('New passwords do not match.', 'danger')
            return redirect(url_for('change_password'))
        if len(new_password) < 4:
            flash('New password must be at least 4 characters long.', 'danger')
            return redirect(url_for('change_password'))
        user['password_hash'] = generate_password_hash(new_password)
        save_data(data)
        flash('Your password has been updated successfully!', 'success')
        return redirect(url_for('home'))
    return render_template('change_password.html')

# --- PITCH COUNT CALCULATION HELPER ---
def calculate_pitch_counts(pitcher_name, all_outings):
    today = date.today()
    current_year = today.year
    start_of_week = today - timedelta(days=today.weekday())
    counts = {'daily': 0, 'weekly': 0, 'season': 0, 'annual': 0}
    for outing in [o for o in all_outings if o.get('pitcher') == pitcher_name]:
        try:
            outing_date = datetime.strptime(outing['date'], '%Y-%m-%d').date()
            pitches = int(outing.get('pitches', 0))
            if outing_date.year == current_year:
                counts['annual'] += pitches
                counts['season'] += pitches
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
    data = load_data()
    user = next((u for u in data.get('users', []) if u['username'] == session['username']), None)
    all_tabs = {
        'roster': 'Roster', 'lineups': 'Lineups', 'pitching': 'Pitching Log',
        'scouting_list': 'Scouting List', 'rotations': 'Rotations',
        'games': 'Games', 'collaboration': 'Collaboration', 'practice_plan': 'Practice Plan',
        'hitting_focus': 'Hitting Focus', 'pitching_focus': 'Pitching Focus',
        'fielding_focus': 'Fielding Focus', 'baserunning_focus': 'Baserunning Focus',
        'signs': 'Signs'
    }
    default_tab_keys = list(all_tabs.keys())
    user_tab_order = user.get('tab_order', default_tab_keys) if user else default_tab_keys
    for key in default_tab_keys:
        if key not in user_tab_order:
            user_tab_order.append(key)
    all_players_for_count = data['roster'] + data['scouting_list']['committed'] + data['scouting_list']['targets']
    position_counts = {}
    if all_players_for_count:
        for player in all_players_for_count:
            pos = player.get('position1')
            if pos and pos != "":
                position_counts[pos] = position_counts.get(pos, 0) + 1
    pitcher_names = sorted(list(set(o['pitcher'] for o in data.get('pitching', []) if o.get('pitcher'))))
    pitch_count_summary = {name: calculate_pitch_counts(name, data.get('pitching', [])) for name in pitcher_names}
    return render_template('index.html', 
                           data=data, 
                           session=session, 
                           tab_order=user_tab_order, 
                           all_tabs=all_tabs,
                           position_counts=position_counts,
                           pitch_count_summary=pitch_count_summary)

@app.route('/save_tab_order', methods=['POST'])
@login_required
def save_tab_order():
    data = load_data()
    user = next((u for u in data.get('users', []) if u['username'] == session['username']), None)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    new_order = request.json.get('order')
    if not isinstance(new_order, list):
        return jsonify({'status': 'error', 'message': 'Invalid order format'}), 400
    user['tab_order'] = new_order
    save_data(data)
    return jsonify({'status': 'success', 'message': 'Tab order saved.'})

@app.route('/admin/users')
@admin_required
def user_management():
    data = load_data()
    return render_template('user_management.html', users=data.get('users', []), session=session)

@app.route('/admin/add_user', methods=['POST'])
@admin_required
def add_user():
    data = load_data()
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'Coach')
    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('user_management'))
    if any(u['username'].lower() == username.lower() for u in data['users']):
        flash('Username already exists.', 'danger')
        return redirect(url_for('user_management'))
    hashed_password = generate_password_hash(password)
    default_tab_keys = ['roster', 'lineups', 'pitching', 'scouting_list', 'rotations', 'games', 'collaboration', 'practice_plan']
    data['users'].append({'username': username, 'password_hash': hashed_password, 'role': role, 'tab_order': default_tab_keys})
    save_data(data)
    flash(f"User '{username}' created successfully as a {role.replace('Admin', 'Head Coach')}.", 'success')
    return redirect(url_for('user_management'))
    
@app.route('/admin/settings', methods=['GET'])
@admin_required
def admin_settings():
    return render_template('admin_settings.html', session=session)

@app.route('/admin/change_role/<username>', methods=['POST'])
@admin_required
def change_user_role(username):
    data = load_data()
    user_to_change = next((u for u in data['users'] if u['username'] == username), None)
    if not user_to_change:
        flash('User not found.', 'danger')
        return redirect(url_for('user_management'))
    if user_to_change['username'] == 'Mike1825':
        flash('Cannot change the role of the super admin.', 'danger')
        return redirect(url_for('user_management'))
    new_role = request.form.get('role')
    if new_role in ['Admin', 'Coach']:
        user_to_change['role'] = new_role
        save_data(data)
        display_role = "Head Coach" if new_role == "Admin" else "Coach"
        flash(f"Successfully changed {username}'s role to {display_role}.", 'success')
    else:
        flash('Invalid role selected.', 'danger')
    return redirect(url_for('user_management'))

@app.route('/admin/delete_user/<username>')
@admin_required
def delete_user(username):
    data = load_data()
    if username == 'Mike1825':
        flash("The super admin cannot be deleted.", "danger")
        return redirect(url_for('user_management'))
    user_to_delete = next((u for u in data['users'] if u['username'] == username), None)
    if user_to_delete:
        data['users'].remove(user_to_delete)
        save_data(data)
        flash(f"User '{username}' has been deleted.", "success")
    else:
        flash("User not found.", "danger")
    return redirect(url_for('user_management'))

@app.route('/admin/reset_password/<username>', methods=['POST'])
@admin_required
def reset_password(username):
    data = load_data()
    user_to_reset = next((u for u in data['users'] if u['username'] == username), None)
    if not user_to_reset:
        flash('User not found.', 'danger')
        return redirect(url_for('user_management'))
    temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    user_to_reset['password_hash'] = generate_password_hash(temp_password)
    save_data(data)
    flash(f"Password for {username} has been reset. The temporary password is: {temp_password}", 'success')
    return redirect(url_for('user_management'))

# --- Roster and Player Routes ---
@app.route('/update_player_inline/<int:index>', methods=['POST'])
@login_required
def update_player_inline(index):
    data = load_data()
    if not (0 <= index < len(data['roster'])):
        return jsonify({'status': 'error', 'message': 'Player not found.'}), 404
    player_number_str = request.form.get('number', '')
    try:
        player_number = int(player_number_str) if player_number_str else ''
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Player number must be a valid integer.'}), 400
    player_to_edit = data['roster'][index]
    player_to_edit.update({
        "name": request.form.get('name'), "number": player_number,
        "position1": request.form.get('position1'), "position2": request.form.get('position2'),
        "position3": request.form.get('position3'),
        "throws": request.form.get('throws'), "bats": request.form.get('bats'),
        "notes": request.form.get('notes', ''), "pitcher_role": request.form.get('pitcher_role', 'Not a Pitcher'),
        "has_lessons": request.form.get('has_lessons'),
        "lesson_focus": request.form.get('lesson_focus')
    })
    save_data(data)
    return jsonify({'status': 'success', 'message': f'Player "{player_to_edit["name"]}" updated successfully!'})

@app.route('/add_player_inline', methods=['POST'])
@login_required
def add_player_inline():
    data = load_data()
    new_name = request.form.get('name')
    new_number_str = request.form.get('number', '')
    if any(p['name'].lower() == new_name.lower() for p in data['roster']):
        return jsonify({'status': 'error', 'message': f'A player named "{new_name}" already exists.'}), 400
    if new_number_str and any(str(p.get('number', '')) == new_number_str for p in data['roster']):
        return jsonify({'status': 'error', 'message': f'A player with number "{new_number_str}" already exists.'}), 400
    try:
        player_number = int(new_number_str) if new_number_str else ''
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Player number must be a valid integer.'}), 400
    player = { 
        "name": new_name, "number": player_number, 
        "position1": request.form.get('position1'), "position2": request.form.get('position2'),
        "position3": request.form.get('position3'),
        "throws": request.form.get('throws'), "bats": request.form.get('bats'), 
        "notes": request.form.get('notes', ''), 
        "pitcher_role": request.form.get('pitcher_role', 'Not a Pitcher'),
        "has_lessons": request.form.get('has_lessons'),
        "lesson_focus": request.form.get('lesson_focus')
    }
    data['roster'].append(player)
    data['player_development'][new_name] = {"hitting": "", "pitching": "", "fielding": "", "baserunning": ""}
    save_data(data)
    flash('Player added successfully!', 'success')
    return jsonify({'status': 'success', 'message': 'Player added successfully!'})

@app.route('/delete_player/<int:index>')
@login_required
def delete_player(index):
    data = load_data()
    if 0 <= index < len(data['roster']):
        player_name = data['roster'][index]['name']
        data['roster'].pop(index)
        if player_name in data['player_development']:
            del data['player_development'][player_name]
        save_data(data)
        flash(f'Player "{player_name}" removed successfully!', 'success')
    else:
        flash('Player not found.', 'danger')
    return redirect(url_for('home', _anchor=request.args.get('active_tab', 'roster').lstrip('#')))

@app.route('/edit_player/<int:index>', methods=['GET', 'POST'])
@login_required
def edit_player(index):
    data = load_data()
    if not (0 <= index < len(data['roster'])):
        flash('Player not found.', 'danger')
        return redirect(url_for('home'))
    player_to_edit = data['roster'][index]
    if request.method == 'POST':
        try:
            player_number = int(request.form['number'])
        except ValueError:
            flash('Player number must be a valid number.', 'danger')
            return render_template('edit_player.html', player=player_to_edit, index=index, session=session)
        player_to_edit.update({
            "name": request.form['name'], "number": player_number, 
            "position1": request.form['position1'], "position2": request.form['position2'],
            "position3": request.form.get('position3'),
            "throws": request.form['throws'], "bats": request.form['bats'], 
            "notes": request.form.get('notes', ''),
            "has_lessons": request.form.get('has_lessons'),
            "lesson_focus": request.form.get('lesson_focus')
        })
        save_data(data)
        flash('Player updated successfully!', 'success')
        return redirect(url_for('home', _anchor='roster'))
    else:
        return render_template('edit_player.html', player=player_to_edit, index=index, session=session)

# --- Player Development Route ---
@app.route('/save_development_focus', methods=['POST'])
@login_required
def save_development_focus():
    data = load_data()
    req_data = request.json
    player_name = req_data.get('playerName')
    skill = req_data.get('skill')
    focus_text = req_data.get('focusText')
    if player_name in data['player_development'] and skill in data['player_development'][player_name]:
        data['player_development'][player_name][skill] = focus_text
        save_data(data)
        return jsonify({'status': 'success', 'message': f'Focus for {player_name} saved.'})
    return jsonify({'status': 'error', 'message': 'Invalid player or skill.'}), 400

# --- Pitching Routes ---
@app.route('/add_pitching', methods=['POST'])
@login_required
def add_pitching():
    data = load_data()
    try:
        pitch_count = int(request.form['pitches'])
        innings_pitched = float(request.form['innings'])
    except ValueError:
        flash('Pitch count and innings must be valid numbers.', 'danger')
        return redirect(url_for('home', _anchor='pitching'))
    outing = {
        "date": request.form['pitch_date'], "pitcher": request.form['pitcher'],
        "opponent": request.form['opponent'], "pitches": pitch_count,
        "innings": innings_pitched, 
        "pitcher_type": request.form.get('pitcher_type', 'Starter'),
        "outing_type": request.form.get('outing_type', 'Game')
    }
    data['pitching'].append(outing)
    save_data(data)
    flash(f'Pitching outing for "{outing["pitcher"]}" added successfully!', 'success')
    return redirect(url_for('home', _anchor='pitching'))

@app.route('/delete_pitching/<int:index>')
@login_required
def delete_pitching(index):
    data = load_data()
    if 0 <= index < len(data['pitching']):
        outing = data['pitching'].pop(index)
        save_data(data)
        flash(f'Pitching outing for "{outing["pitcher"]}" removed successfully!', 'success')
    else:
        flash('Pitching outing not found.', 'danger')
    return redirect(url_for('home', _anchor='pitching'))

# --- Signs Routes ---
@app.route('/add_sign', methods=['POST'])
@login_required
def add_sign():
    data = load_data()
    sign_name = request.form.get('sign_name')
    sign_indicator = request.form.get('sign_indicator')
    if sign_name and sign_indicator:
        data['signs'].append({'name': sign_name, 'indicator': sign_indicator})
        save_data(data)
        flash('Sign added successfully!', 'success')
    else:
        flash('Sign Name and Indicator are required.', 'danger')
    return redirect(url_for('home', _anchor='signs'))

@app.route('/update_sign/<int:index>', methods=['POST'])
@login_required
def update_sign(index):
    data = load_data()
    if 0 <= index < len(data['signs']):
        sign_name = request.form.get('sign_name')
        sign_indicator = request.form.get('sign_indicator')
        if sign_name and sign_indicator:
            data['signs'][index] = {'name': sign_name, 'indicator': sign_indicator}
            save_data(data)
            flash('Sign updated successfully!', 'success')
        else:
            flash('Sign Name and Indicator are required.', 'danger')
    else:
        flash('Sign not found.', 'danger')
    return redirect(url_for('home', _anchor='signs'))

@app.route('/delete_sign/<int:index>')
@login_required
def delete_sign(index):
    data = load_data()
    if 0 <= index < len(data['signs']):
        data['signs'].pop(index)
        save_data(data)
        flash('Sign deleted successfully.', 'success')
    else:
        flash('Sign not found.', 'danger')
    return redirect(url_for('home', _anchor='signs'))

# --- ALL OTHER ORIGINAL ROUTES ---

@app.route('/save_rotation', methods=['POST'])
@login_required
def save_rotation():
    data = load_data()
    rotation_data = request.get_json()
    rotation_id = rotation_data.get('id')
    title = rotation_data.get('title')
    innings_data = rotation_data.get('innings')
    if not title or not isinstance(innings_data, dict):
        return jsonify({'status': 'error', 'message': 'Invalid data provided.'}), 400
    if rotation_id:
        rotation_to_update = next((r for r in data['rotations'] if r.get('id') == rotation_id), None)
        if rotation_to_update:
            rotation_to_update['title'] = title
            rotation_to_update['innings'] = innings_data
            message = 'Rotation updated successfully!'
        else: rotation_id = None
    if not rotation_id:
        new_rotation = {'id': int(time.time()), 'title': title, 'innings': innings_data}
        data['rotations'].append(new_rotation)
        message = 'Rotation saved successfully!'
    save_data(data)
    return jsonify({'status': 'success', 'message': message})

@app.route('/delete_rotation/<int:rotation_id>')
@login_required
def delete_rotation(rotation_id):
    data = load_data()
    rotation_to_delete = next((r for r in data['rotations'] if r.get('id') == rotation_id), None)
    if rotation_to_delete:
        data['rotations'].remove(rotation_to_delete)
        save_data(data)
        flash('Rotation deleted successfully!', 'success')
    else:
        flash('Rotation not found.', 'danger')
    return redirect(url_for('home', _anchor='rotations'))

@app.route('/add_note/<note_type>', methods=['POST'])
@login_required
def add_note(note_type):
    data = load_data()
    if note_type not in ['player_notes', 'team_notes']:
        flash('Invalid note type.', 'danger')
        return redirect(url_for('home', _anchor='collaboration'))
    note_text = request.form.get('note_text')
    if not note_text:
        flash('Note cannot be empty.', 'warning')
        return redirect(url_for('home', _anchor='collaboration'))
    new_note = {"text": note_text, "author": session['username'], "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if note_type == 'player_notes':
        player_name = request.form.get('player_name')
        if not player_name:
            flash('You must select a player.', 'warning')
            return redirect(url_for('home', _anchor='collaboration'))
        new_note['player_name'] = player_name
        data['collaboration_notes']['player_notes'].append(new_note)
    else:
        data['collaboration_notes']['team_notes'].append(new_note)
    save_data(data)
    flash('Note added successfully!', 'success')
    return redirect(url_for('home', _anchor='collaboration'))

@app.route('/delete_note/<note_type>/<int:index>')
@login_required
def delete_note(note_type, index):
    data = load_data()
    notes_list = data.get('collaboration_notes', {}).get(note_type)
    if notes_list is None or not (0 <= index < len(notes_list)):
        flash('Note not found.', 'danger')
        return redirect(url_for('home', _anchor='collaboration'))
    note_to_delete = notes_list[index]
    if session['username'] == note_to_delete.get('author') or session.get('role') == 'Admin':
        notes_list.pop(index)
        save_data(data)
        flash('Note deleted successfully.', 'success')
    else:
        flash('You do not have permission to delete this note.', 'danger')
    return redirect(url_for('home', _anchor='collaboration'))

@app.route('/add_practice_plan', methods=['POST'])
@login_required
def add_practice_plan():
    data = load_data()
    plan_date = request.form.get('plan_date')
    if not plan_date:
        flash('Practice date is required.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
    new_plan = {"id": int(time.time()), "date": plan_date, "general_notes": request.form.get('general_notes', ''), "tasks": []}
    data['practice_plans'].append(new_plan)
    save_data(data)
    flash('New practice plan created!', 'success')
    return redirect(url_for('home', _anchor='practice_plan'))

@app.route('/add_task_to_plan/<int:plan_id>', methods=['POST'])
@login_required
def add_task_to_plan(plan_id):
    data = load_data()
    plan = next((p for p in data['practice_plans'] if p['id'] == plan_id), None)
    if not plan:
        flash('Practice plan not found.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
    task_text = request.form.get('task_text')
    if not task_text:
        flash('Task cannot be empty.', 'warning')
        return redirect(url_for('home', _anchor='practice_plan'))
    new_task = {"id": int(time.time() * 1000), "text": task_text, "status": "pending", "author": session['username'], "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")}
    plan['tasks'].append(new_task)
    save_data(data)
    flash('Task added to plan.', 'success')
    return redirect(url_for('home', _anchor='practice_plan'))

@app.route('/delete_task/<int:plan_id>/<int:task_id>')
@login_required
def delete_task(plan_id, task_id):
    data = load_data()
    plan = next((p for p in data['practice_plans'] if p['id'] == plan_id), None)
    if plan:
        task_to_delete = next((t for t in plan['tasks'] if t['id'] == task_id), None)
        if task_to_delete:
            plan['tasks'].remove(task_to_delete)
            save_data(data)
            flash('Task deleted.', 'success')
        else: flash('Task not found.', 'danger')
    else: flash('Practice plan not found.', 'danger')
    return redirect(url_for('home', _anchor='practice_plan'))

@app.route('/update_task_status/<int:plan_id>/<int:task_id>', methods=['POST'])
@login_required
def update_task_status(plan_id, task_id):
    data = load_data()
    plan = next((p for p in data.get('practice_plans', []) if p.get('id') == plan_id), None)
    if not plan:
        return jsonify({'status': 'error', 'message': 'Plan not found'}), 404
    task = next((t for t in plan.get('tasks', []) if t.get('id') == task_id), None)
    if not task:
        return jsonify({'status': 'error', 'message': 'Task not found'}), 404
    request_data = request.get_json()
    new_status = request_data.get('status')
    if new_status not in ['pending', 'complete']:
        return jsonify({'status': 'error', 'message': 'Invalid status'}), 400
    task['status'] = new_status
    save_data(data)
    return jsonify({'status': 'success', 'message': 'Task status updated.'})

@app.route('/move_note_to_practice_plan/<note_type>/<int:note_index>', methods=['GET', 'POST'])
@login_required
def move_note_to_practice_plan(note_type, note_index):
    data = load_data()
    notes_list = data.get('collaboration_notes', {}).get(note_type)
    if not (notes_list and 0 <= note_index < len(notes_list)):
        flash('Note not found.', 'danger')
        return redirect(url_for('home', _anchor='collaboration'))
    if request.method == 'POST':
        plan_id_str = request.form.get('plan_id')
        if not plan_id_str:
            flash('You must select a practice plan.', 'warning')
            return redirect(url_for('move_note_to_practice_plan', note_type=note_type, note_index=note_index))
        plan_id = int(plan_id_str)
        plan = next((p for p in data['practice_plans'] if p['id'] == plan_id), None)
        if not plan:
            flash('Practice plan not found.', 'danger')
            return redirect(url_for('home', _anchor='collaboration'))
        note_to_move = notes_list.pop(note_index)
        new_task = {"id": int(time.time() * 1000), "text": note_to_move['text'], "status": "pending", "author": note_to_move['author'], "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")}
        plan['tasks'].append(new_task)
        save_data(data)
        flash('Note successfully moved to practice plan.', 'success')
        return redirect(url_for('home', _anchor='practice_plan'))
    note_to_move = notes_list[note_index]
    return render_template('move_note_to_plan.html', note=note_to_move, practice_plans=data['practice_plans'], note_type=note_type, note_index=note_index)

@app.route('/add_scouted_player', methods=['POST'])
@login_required
def add_scouted_player():
    data = load_data()
    scouted_player_type = request.form['scouted_player_type']
    new_player = {
        "name": request.form['scouted_player_name'],
        "position1": request.form.get('scouted_player_pos1', ''),
        "position2": request.form.get('scouted_player_pos2', ''),
        "throws": request.form.get('scouted_player_throws', ''),
        "bats": request.form.get('scouted_player_bats', '')
    }
    if scouted_player_type in data['scouting_list']:
        data['scouting_list'][scouted_player_type].append(new_player)
        save_data(data)
        flash(f'Player "{new_player["name"]}" added to {scouted_player_type.replace("_", " ").title()} list.', 'success')
    else:
        flash('Invalid scouting list type.', 'danger')
    return redirect(url_for('home', _anchor='scouting_list'))

@app.route('/remove_scouted_player/<scouted_player_type>/<int:index>')
@login_required
def remove_scouted_player(scouted_player_type, index):
    data = load_data()
    if scouted_player_type in data['scouting_list'] and 0 <= index < len(data['scouting_list'][scouted_player_type]):
        player_name = data['scouting_list'][scouted_player_type].pop(index)['name']
        save_data(data)
        flash(f'Player "{player_name}" removed from the {scouted_player_type.replace("_", " ").title()} list.', 'success')
    else:
        flash('Player not found or invalid list.', 'danger')
    return redirect(url_for('home', _anchor='scouting_list'))

@app.route('/move_scouted_player/<from_type>/<to_type>/<int:index>', methods=['POST'])
@login_required
def move_scouted_player(from_type, to_type, index):
    data = load_data()
    if from_type in data['scouting_list'] and to_type in data['scouting_list'] and 0 <= index < len(data['scouting_list'][from_type]):
        player = data['scouting_list'][from_type].pop(index)
        data['scouting_list'][to_type].append(player)
        save_data(data)
        flash(f'Player "{player["name"]}" moved to {to_type.replace("_", " ").title()} list.', 'success')
    else:
        flash('Could not move player.', 'danger')
    return redirect(url_for('home', _anchor='scouting_list'))

@app.route('/move_scouted_player_to_roster/<int:index>', methods=['POST'])
@login_required
def move_scouted_player_to_roster(index):
    data = load_data()
    if 0 <= index < len(data['scouting_list']['committed']):
        scouted_player = data['scouting_list']['committed'].pop(index)
        new_player = {
            "name": scouted_player['name'], "number": "", "position1": scouted_player.get('position1', ''), "position2": scouted_player.get('position2', ''),
            "throws": scouted_player.get('throws', ''), "bats": scouted_player.get('bats', ''), "notes": "", "pitcher_role": "Not a Pitcher"
        }
        data['roster'].append(new_player)
        save_data(data)
        flash(f'Player "{scouted_player["name"]}" moved to Roster. Please assign a number.', 'success')
    else:
        flash('Committed player not found.', 'danger')
    return redirect(url_for('home', _anchor='scouting_list'))
    
@app.route('/add_game', methods=['POST'])
@login_required
def add_game():
    data = load_data()
    game = {
        "date": request.form['game_date'], "opponent": request.form['game_opponent'],
        "location": request.form.get('game_location', ''), "game_notes": request.form.get('game_notes', ''),
        "associated_lineup_title": request.form.get('associated_lineup_title', ''), "associated_rotation_date": request.form.get('associated_rotation_date', '')
    }
    data['games'].append(game)
    save_data(data)
    flash(f'Game vs "{game["opponent"]}" on {game["date"]} added successfully!', 'success')
    return redirect(url_for('home', _anchor='games'))

@app.route('/delete_game/<int:index>')
@login_required
def delete_game(index):
    data = load_data()
    if 0 <= index < len(data['games']):
        game = data['games'].pop(index)
        save_data(data)
        flash(f'Game vs "{game["opponent"]}" on {game["date"]} removed successfully!', 'success')
    else:
        flash('Game not found.', 'danger')
    return redirect(url_for('home', _anchor='games'))

@app.route('/add_lineup', methods=['POST'])
@login_required
def add_lineup():
    data = load_data()
    selected_player_names = request.form.getlist('lineup_player')
    players_for_lineup = []
    for player_name in selected_player_names:
        found_player = next((p for p in data['roster'] if p['name'] == player_name), None)
        if found_player:
            players_for_lineup.append(found_player)
    lineup = {"title": request.form['lineup_title'], "players": players_for_lineup}
    data['lineups'].append(lineup)
    save_data(data)
    flash(f'Lineup "{lineup["title"]}" created successfully!', 'success')
    return redirect(url_for('home', _anchor='lineups'))

@app.route('/delete_lineup/<int:index>')
@login_required
def delete_lineup(index):
    data = load_data()
    if 0 <= index < len(data['lineups']):
        lineup = data['lineups'].pop(index)
        save_data(data)
        flash(f'Lineup "{lineup["title"]}" deleted successfully!', 'success')
    else:
        flash('Lineup not found.', 'danger')
    return redirect(url_for('home', _anchor='lineups'))

@app.route('/edit_lineup/<int:index>', methods=['POST'])
@login_required
def edit_lineup(index):
    data = load_data()
    if 0 <= index < len(data['lineups']):
        selected_player_names = request.form.getlist('lineup_player')
        player_map = {p['name']: p for p in data['roster']}
        ordered_players = [player_map[name] for name in selected_player_names if name in player_map]
        data['lineups'][index]['title'] = request.form['lineup_title']
        data['lineups'][index]['players'] = ordered_players
        save_data(data)
        flash(f'Lineup "{request.form["lineup_title"]}" updated successfully!', 'success')
    else:
        flash('Lineup not found.', 'danger')
    return redirect(url_for('home', _anchor=request.form.get('active_tab', '#lineups').lstrip('#')))

@app.route('/delete_practice_plan/<int:plan_id>')
@login_required
def delete_practice_plan(plan_id):
    data = load_data()
    plan_to_delete = next((p for p in data['practice_plans'] if p.get('id') == plan_id), None)
    if plan_to_delete:
        data['practice_plans'].remove(plan_to_delete)
        save_data(data)
        flash('Practice plan deleted successfully!', 'success')
    else:
        flash('Practice plan not found.', 'danger')
    return redirect(url_for('home', _anchor='practice_plan'))

@app.route('/edit_practice_plan/<int:plan_id>', methods=['POST'])
@login_required
def edit_practice_plan(plan_id):
    data = load_data()
    plan_to_edit = next((p for p in data['practice_plans'] if p.get('id') == plan_id), None)
    if plan_to_edit:
        new_date = request.form.get('plan_date')
        new_notes = request.form.get('general_notes')
        if not new_date:
            flash('Plan date cannot be empty.', 'danger')
        else:
            plan_to_edit['date'] = new_date
            plan_to_edit['general_notes'] = new_notes
            save_data(data)
            flash('Practice plan updated successfully!', 'success')
    else:
        flash('Practice plan not found.', 'danger')
    return redirect(url_for('home', _anchor='practice_plan'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
