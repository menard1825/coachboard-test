from flask import Flask, render_template, request, redirect, url_for, flash, session
import json
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import time

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here' # IMPORTANT: Change this to a strong, random key in production

DATA_FILE = 'data.json'
ADMIN_USERS = ["Mike1825"] # Add your admin username(s) here

# --- Add Headers to All Responses ---
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    # This will help with the 'set-cookie' warning in production
    if app.config.get("SESSION_COOKIE_SECURE"):
        response.headers['Set-Cookie'] = response.headers['Set-Cookie'].replace(';', '; Secure;')
    return response

def get_user_role(username):
    data = load_data()
    user = next((u for u in data['users'] if u['username'] == username), None)
    return user.get('role', 'Coach') if user else None

def load_data():
    data = {"users": [], "roster": [], "lineups": [], "pitching": [], "scouting_list": {"committed": [], "targets": []}, "rotations": [], "games": [], "feedback": [], "settings": {"registration_code": "DEFAULT_CODE"}, "collaboration_notes": {"player_notes": [], "team_notes": []}, "practice_plans": []}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)

    if 'settings' not in data:
        data['settings'] = {"registration_code": "DEFAULT_CODE"}
    if 'collaboration_notes' not in data:
        data['collaboration_notes'] = {"player_notes": [], "team_notes": []}
    if 'practice_plans' not in data:
        data['practice_plans'] = []
    if 'rotations' not in data:
        data['rotations'] = []

    # --- Data Migrations ---
    if 'users' in data:
        for user in data['users']:
            if 'role' not in user:
                user['role'] = 'Admin' if user['username'] == 'Mike1825' else 'Coach'
                
    if 'recruits' in data: # Check for the old key
        data['scouting_list'] = data.pop('recruits') # Rename it
        for category in ['committed', 'targets']:
            updated_list = []
            for item in data['scouting_list'][category]:
                if isinstance(item, str): # If it's just a name string
                    updated_list.append({
                        "name": item, "position1": "", "position2": "", "throws": "", "bats": ""
                    })
                else: # If it's already a dictionary
                    item.setdefault('position1', '')
                    item.setdefault('position2', '')
                    item.setdefault('throws', '')
                    item.setdefault('bats', '')
                    updated_list.append(item)
            data['scouting_list'][category] = updated_list
            
    for player in data['roster']:
        player.setdefault('notes', '')
        player.setdefault('position1', '')
        player.setdefault('position2', '')
        player.setdefault('throws', '')
        player.setdefault('bats', '')
        player.setdefault('pitcher_role', 'Not a Pitcher')

    if 'lineups' in data:
        updated_lineups = []
        for lineup in data['lineups']:
            if 'players' in lineup:
                new_players_list = []
                for player_entry in lineup['players']:
                    player_data = {}
                    if isinstance(player_entry, str):
                        player_data['name'] = player_entry
                        player_data['number'] = ""
                    elif isinstance(player_entry, dict) and 'name' in player_entry and 'number' in player_entry:
                        player_data = player_entry
                    else:
                        player_data = {"name": "", "number": ""}

                    full_player_info = next((p for p in data['roster'] if p['name'] == player_data['name']), None)
                    if full_player_info:
                        new_players_list.append({
                            "name": full_player_info['name'],
                            "number": full_player_info['number'],
                            "position1": full_player_info.get('position1', ''),
                            "position2": full_player_info.get('position2', ''),
                            "throws": full_player_info.get('throws', ''),
                            "bats": full_player_info.get('bats', '')
                        })
                    else:
                        player_data['position1'] = player_data.get('position1', '')
                        player_data['position2'] = player_data.get('position2', '')
                        player_data['throws'] = player_data.get('throws', '')
                        player_data['bats'] = player_data.get('bats', '')
                        new_players_list.append(player_data)
                lineup['players'] = new_players_list
            updated_lineups.append(lineup)
        data['lineups'] = updated_lineups

    return data

def save_data(data):
    # Sort practice plans by date before saving
    if 'practice_plans' in data:
        data['practice_plans'].sort(key=lambda x: x['date'], reverse=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- Login Required Decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Admin Required Decorator ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        if get_user_role(session.get('username')) != 'Admin':
            flash('You must be an admin to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = load_data()
        username = request.form['username']
        password = request.form['password']
        
        user = next((u for u in data['users'] if u['username'] == username), None)
        
        if user and check_password_hash(user['password_hash'], password):
            session['logged_in'] = True
            session['username'] = username
            session['role'] = user.get('role', 'Coach') # Store role in session
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

@app.route('/register', methods=['GET', 'POST'])
def register():
    data = load_data()
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        reg_code = request.form['registration_code']

        if reg_code != data['settings']['registration_code']:
            flash('Invalid Registration Code.', 'danger')
            return render_template('register.html')
            
        if any(u['username'] == username for u in data['users']):
            flash('Username already exists.', 'danger')
            return render_template('register.html')

        hashed_password = generate_password_hash(password)
        # New users default to the 'Coach' role
        data['users'].append({'username': username, 'password_hash': hashed_password, 'role': 'Coach'})
        save_data(data)

        flash('You have successfully registered! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/')
@login_required
def home():
    data = load_data()
    return render_template('index.html', data=data, username=session.get('username'), is_admin=session.get('role') == 'Admin')

@app.route('/admin/users')
@admin_required
def user_management():
    data = load_data()
    return render_template('user_management.html', users=data['users'])
    
@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    data = load_data()
    if request.method == 'POST':
        new_code = request.form['registration_code']
        data['settings']['registration_code'] = new_code
        save_data(data)
        flash('Registration code updated successfully!', 'success')
        return redirect(url_for('admin_settings'))
    
    return render_template('admin_settings.html', registration_code=data['settings']['registration_code'])
    
@app.route('/admin/change_role/<username>', methods=['POST'])
@admin_required
def change_user_role(username):
    data = load_data()
    user_to_change = next((u for u in data['users'] if u['username'] == username), None)
    
    if not user_to_change:
        flash('User not found.', 'danger')
        return redirect(url_for('user_management'))
    
    if username == 'Mike1825':
        flash('Cannot change the role of the super admin.', 'danger')
        return redirect(url_for('user_management'))
        
    new_role = request.form.get('role')
    if new_role in ['Admin', 'Coach']:
        user_to_change['role'] = new_role
        save_data(data)
        flash(f"Successfully changed {username}'s role to {new_role}.", 'success')
    else:
        flash('Invalid role selected.', 'danger')
        
    return redirect(url_for('user_management'))

@app.route('/admin/delete_user/<username>')
@admin_required
def delete_user(username):
    data = load_data()
    user_to_delete = next((u for u in data['users'] if u['username'] == username), None)
    if user_to_delete:
        if username == 'Mike1825':
            flash("The super admin cannot be deleted.", "danger")
            return redirect(url_for('user_management'))
            
        data['users'].remove(user_to_delete)
        save_data(data)
        flash(f"User '{username}' has been deleted.", "success")
    else:
        flash("User not found.", "danger")
    return redirect(url_for('user_management'))

@app.route('/update_player_inline/<int:index>', methods=['POST'])
@login_required
def update_player_inline(index):
    data = load_data()
    if not (0 <= index < len(data['roster'])):
        return json.dumps({'status': 'error', 'message': 'Player not found.'}), 404

    player_to_edit = data['roster'][index]
    player_number_str = request.form.get('number', '')
    player_number = "" 
    if player_number_str:
        try:
            player_number = int(player_number_str)
        except ValueError:
            return json.dumps({'status': 'error', 'message': 'Player number must be a valid integer or left blank.'}), 400
    
    player_to_edit.update({
        "name": request.form['name'],
        "number": player_number,
        "position1": request.form['position1'],
        "position2": request.form['position2'],
        "throws": request.form['throws'],
        "bats": request.form['bats'],
        "notes": request.form.get('notes', ''),
        "pitcher_role": request.form.get('pitcher_role', 'Not a Pitcher')
    })
    save_data(data)
    return json.dumps({'status': 'success', 'message': f'Player "{player_to_edit["name"]}" updated successfully!'})

@app.route('/add_player_inline', methods=['POST'])
@login_required
def add_player_inline():
    data = load_data()
    
    new_name = request.form['name']
    new_number_str = request.form.get('number', '')
    
    # --- Duplicate Player Check ---
    for player in data['roster']:
        if player['name'].lower() == new_name.lower():
            return json.dumps({'status': 'error', 'message': f'A player with the name "{new_name}" already exists.'}), 400
        if new_number_str and str(player.get('number', '')) == new_number_str:
            return json.dumps({'status': 'error', 'message': f'A player with the number "{new_number_str}" already exists.'}), 400

    player_number = ""
    if new_number_str:
        try:
            player_number = int(new_number_str)
        except ValueError:
            return json.dumps({'status': 'error', 'message': 'Player number must be a valid integer or left blank.'}), 400

    player = {
        "name": new_name,
        "number": player_number,
        "position1": request.form['position1'],
        "position2": request.form['position2'],
        "throws": request.form['throws'],
        "bats": request.form['bats'],
        "notes": request.form.get('notes', ''),
        "pitcher_role": request.form.get('pitcher_role', 'Not a Pitcher')
    }
    data['roster'].append(player)
    save_data(data)
    
    flash('Player added successfully!', 'success')
    return json.dumps({'status': 'success', 'message': 'Player added successfully!'})

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
            return render_template('edit_player.html', player=player_to_edit, index=index)

        player_to_edit.update({
            "name": request.form['name'],
            "number": player_number,
            "position1": request.form['position1'],
            "position2": request.form['position2'],
            "throws": request.form['throws'],
            "bats": request.form['bats'],
            "notes": request.form.get('notes', '')
        })
        save_data(data)
        flash('Player updated successfully!', 'success')
        return redirect(url_for('home') + '#roster')
    else:
        return render_template('edit_player.html', player=player_to_edit, index=index)

@app.route('/delete_player/<int:index>')
@login_required
def delete_player(index):
    data = load_data()
    if 0 <= index < len(data['roster']):
        player_name = data['roster'][index]['name']
        data['roster'].pop(index)
        save_data(data)
        flash(f'Player "{player_name}" removed successfully!', 'success')
    else:
        flash('Player not found.', 'danger')
    active_tab = request.args.get('active_tab', '')
    return redirect(url_for('home') + active_tab)

@app.route('/add_lineup', methods=['POST'])
@login_required
def add_lineup():
    data = load_data()
    selected_player_names = request.form.getlist('lineup_player')
    
    players_for_lineup = []
    for player_name in selected_player_names:
        found_player = next((p for p in data['roster'] if p['name'] == player_name), None)
        if found_player:
            players_for_lineup.append({
                "name": found_player['name'],
                "number": found_player['number'],
                "position1": found_player.get('position1', ''),
                "position2": found_player.get('position2', ''),
                "throws": found_player.get('throws', ''),
                "bats": found_player.get('bats', '')
            })
        else:
            players_for_lineup.append({
                "name": player_name,
                "number": "",
                "position1": "",
                "position2": "",
                "throws": "",
                "bats": ""
            })

    lineup = {
        "title": request.form['lineup_title'],
        "players": players_for_lineup
    }
    data['lineups'].append(lineup)
    save_data(data)
    flash(f'Lineup "{lineup["title"]}" created successfully!', 'success')
    active_tab = request.form.get('active_tab', '')
    return redirect(url_for('home') + active_tab)

@app.route('/update_lineup/<int:index>', methods=['POST'])
@login_required
def update_lineup(index):
    data = load_data()
    if 0 <= index < len(data['lineups']):
        new_lineup_title = request.form['lineup_title']
        updated_players = json.loads(request.form['lineup_player_ordered'])
        data['lineups'][index]['title'] = new_lineup_title
        data['lineups'][index]['players'] = updated_players
        save_data(data)
        flash(f'Lineup "{data["lineups"][index]["title"]}" updated successfully!', 'success')
        return json.dumps({'status': 'success', 'message': f'Lineup "{new_lineup_title}" updated successfully!'})
    else:
        return json.dumps({'status': 'error', 'message': 'Lineup not found.'}), 404

@app.route('/delete_lineup/<int:index>')
@login_required
def delete_lineup(index):
    data = load_data()
    if 0 <= index < len(data['lineups']):
        lineup_title = data['lineups'][index]['title']
        data['lineups'].pop(index)
        save_data(data)
        flash(f'Lineup "{lineup_title}" deleted successfully!', 'success')
    else:
        flash('Lineup not found.', 'danger')
    active_tab = request.args.get('active_tab', '')
    return redirect(url_for('home') + active_tab)

@app.route('/add_pitching', methods=['POST'])
@login_required
def add_pitching():
    data = load_data()
    try:
        pitch_count = int(request.form['pitches'])
        innings_pitched = float(request.form['innings'])
    except ValueError:
        flash('Pitch count and innings must be valid numbers.', 'danger')
        active_tab = request.form.get('active_tab', '')
        return redirect(url_for('home') + active_tab)

    outing = {
        "date": request.form['pitch_date'],
        "pitcher": request.form['pitcher'],
        "opponent": request.form['opponent'],
        "pitches": pitch_count,
        "innings": innings_pitched,
        "pitcher_type": request.form.get('pitcher_type', 'Starter')
    }
    data['pitching'].append(outing)
    save_data(data)
    flash(f'Pitching outing for "{outing["pitcher"]}" added successfully!', 'success')
    active_tab = request.form.get('active_tab', '')
    return redirect(url_for('home') + active_tab)

@app.route('/delete_pitching/<int:index>')
@login_required
def delete_pitching(index):
    data = load_data()
    if 0 <= index < len(data['pitching']):
        pitcher_name = data['pitching'][index]['pitcher']
        data['pitching'].pop(index)
        save_data(data)
        flash(f'Pitching outing for "{pitcher_name}" removed successfully!', 'success')
    else:
        flash('Pitching outing not found.', 'danger')
    active_tab = request.args.get('active_tab', '')
    return redirect(url_for('home') + active_tab)

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
        flash(f'Player "{new_player["name"]}" added to {scouted_player_type.replace("committed", "Committed Players").replace("targets", "Target Players")} successfully!', 'success')
    else:
        flash('Invalid player type.', 'danger')
    active_tab = request.form.get('active_tab', '')
    return redirect(url_for('home') + active_tab)

@app.route('/remove_scouted_player/<scouted_player_type>/<int:index>')
@login_required
def remove_scouted_player(scouted_player_type, index):
    data = load_data()
    if scouted_player_type in data['scouting_list'] and 0 <= index < len(data['scouting_list'][scouted_player_type]):
        player_name = data['scouting_list'][scouted_player_type][index]['name']
        data['scouting_list'][scouted_player_type].pop(index)
        save_data(data)
        flash(f'Player "{player_name}" removed from {scouted_player_type.replace("committed", "Committed Players").replace("targets", "Target Players")} successfully!', 'success')
    else:
        flash('Player not found or invalid type.', 'danger')
    active_tab = request.args.get('active_tab', '')
    return redirect(url_for('home') + active_tab)


@app.route('/move_scouted_player/<from_type>/<to_type>/<int:index>', methods=['POST'])
@login_required
def move_scouted_player(from_type, to_type, index):
    data = load_data()
    if from_type in data['scouting_list'] and to_type in data['scouting_list'] and 0 <= index < len(data['scouting_list'][from_type]):
        player = data['scouting_list'][from_type].pop(index)
        data['scouting_list'][to_type].append(player)
        save_data(data)
        flash(f'Player "{player["name"]}" moved to {to_type.replace("committed", "Committed Players").replace("targets", "Target Players")} successfully!', 'success')
    else:
        flash('Player not found or invalid type.', 'danger')
    active_tab = request.form.get('active_tab', '')
    return redirect(url_for('home') + active_tab)

@app.route('/move_scouted_player_to_roster/<int:index>', methods=['POST'])
@login_required
def move_scouted_player_to_roster(index):
    data = load_data()
    if 0 <= index < len(data['scouting_list']['committed']):
        scouted_player = data['scouting_list']['committed'].pop(index)

        new_player = {
            "name": scouted_player['name'],
            "number": "",
            "position1": scouted_player.get('position1', ''),
            "position2": scouted_player.get('position2', ''),
            "throws": scouted_player.get('throws', ''),
            "bats": scouted_player.get('bats', ''),
            "notes": ""
        }
        data['roster'].append(new_player)
        save_data(data)
        flash(f'Player "{scouted_player["name"]}" moved to roster successfully! You can add more details on the Roster tab.', 'success')
    else:
        flash('Committed player not found.', 'danger')
    active_tab = request.form.get('active_tab', '')
    return redirect(url_for('home') + active_tab)

@app.route('/save_rotation', methods=['POST'])
@login_required
def save_rotation():
    data = load_data()
    rotation_data = request.get_json()
    
    new_rotation = {
        'id': int(time.time()),
        'title': rotation_data['title'],
        'positions': rotation_data['positions']
    }
    
    data['rotations'].append(new_rotation)
    save_data(data)
    return json.dumps({'status': 'success', 'message': 'Rotation saved successfully!'})

@app.route('/delete_rotation/<int:rotation_id>')
@login_required
def delete_rotation(rotation_id):
    data = load_data()
    rotation_to_delete = next((r for r in data['rotations'] if r['id'] == rotation_id), None)
    if rotation_to_delete:
        data['rotations'].remove(rotation_to_delete)
        save_data(data)
        flash('Rotation deleted successfully!', 'success')
    else:
        flash('Rotation not found.', 'danger')
    return redirect(url_for('home') + '#rotations')


@app.route('/add_game', methods=['POST'])
@login_required
def add_game():
    data = load_data()
    
    game = {
        "date": request.form['game_date'],
        "opponent": request.form['game_opponent'],
        "location": request.form.get('game_location', ''),
        "game_notes": request.form.get('game_notes', ''),
        "associated_lineup_title": request.form.get('associated_lineup_title', ''),
        "associated_rotation_date": request.form.get('associated_rotation_date', '')
    }
    data['games'].append(game)
    save_data(data)
    flash(f'Game vs "{game["opponent"]}" on {game["date"]} added successfully!', 'success')
    active_tab = request.form.get('active_tab', '')
    return redirect(url_for('home') + active_tab)

@app.route('/delete_game/<int:index>')
@login_required
def delete_game(index):
    data = load_data()
    if 0 <= index < len(data['games']):
        game_opponent = data['games'][index]['opponent']
        game_date = data['games'][index]['date']
        data['games'].pop(index)
        save_data(data)
        flash(f'Game vs "{game_opponent}" on {game_date} removed successfully!', 'success')
    else:
        flash('Game not found.', 'danger')
    active_tab = request.args.get('active_tab', '')
    return redirect(url_for('home') + active_tab)

@app.route('/add_note/<note_type>', methods=['POST'])
@login_required
def add_note(note_type):
    data = load_data()
    if note_type not in ['player_notes', 'team_notes']:
        flash('Invalid note type.', 'danger')
        return redirect(url_for('home'))

    note_text = request.form.get('note_text')
    if not note_text:
        flash('Note cannot be empty.', 'warning')
        return redirect(url_for('home') + '#collaboration')

    new_note = {
        "text": note_text,
        "author": session['username'],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    if note_type == 'player_notes':
        player_name = request.form.get('player_name')
        if not player_name:
            flash('You must select a player.', 'warning')
            return redirect(url_for('home') + '#collaboration')
        new_note['player_name'] = player_name
        data['collaboration_notes']['player_notes'].append(new_note)
    else: # team_notes
        data['collaboration_notes']['team_notes'].append(new_note)
    
    save_data(data)
    flash('Note added successfully!', 'success')
    return redirect(url_for('home') + '#collaboration')


@app.route('/delete_note/<note_type>/<int:index>')
@login_required
def delete_note(note_type, index):
    data = load_data()
    notes_list = data.get('collaboration_notes', {}).get(note_type)

    if notes_list is None or not (0 <= index < len(notes_list)):
        flash('Note not found.', 'danger')
        return redirect(url_for('home') + '#collaboration')

    note_to_delete = notes_list[index]
    
    # Allow deletion if user is the author OR is an admin
    if session['username'] == note_to_delete['author'] or session.get('role') == 'Admin':
        notes_list.pop(index)
        save_data(data)
        flash('Note deleted successfully.', 'success')
    else:
        flash('You do not have permission to delete this note.', 'danger')
        
    return redirect(url_for('home') + '#collaboration')


@app.route('/add_practice_plan', methods=['POST'])
@login_required
def add_practice_plan():
    data = load_data()
    plan_date = request.form.get('plan_date')
    general_notes = request.form.get('general_notes', '')

    if not plan_date:
        flash('Practice date is required.', 'danger')
        return redirect(url_for('home') + '#practice_plan')

    new_plan = {
        "id": int(time.time()), # Simple unique ID
        "date": plan_date,
        "general_notes": general_notes,
        "tasks": []
    }
    data['practice_plans'].append(new_plan)
    save_data(data)
    flash('New practice plan created!', 'success')
    return redirect(url_for('home') + '#practice_plan')


@app.route('/add_task_to_plan/<int:plan_id>', methods=['POST'])
@login_required
def add_task_to_plan(plan_id):
    data = load_data()
    plan = next((p for p in data['practice_plans'] if p['id'] == plan_id), None)
    
    if not plan:
        flash('Practice plan not found.', 'danger')
        return redirect(url_for('home') + '#practice_plan')

    task_text = request.form.get('task_text')
    if not task_text:
        flash('Task cannot be empty.', 'warning')
        return redirect(url_for('home') + '#practice_plan')

    new_task = {
        "id": int(time.time() * 1000), # More granular ID
        "text": task_text,
        "status": "pending",
        "author": session['username'],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    plan['tasks'].append(new_task)
    save_data(data)
    flash('Task added to plan.', 'success')
    return redirect(url_for('home') + '#practice_plan')


@app.route('/update_task_status/<int:plan_id>/<int:task_id>', methods=['POST'])
@login_required
def update_task_status(plan_id, task_id):
    data = load_data()
    plan = next((p for p in data['practice_plans'] if p['id'] == plan_id), None)
    if plan:
        task = next((t for t in plan['tasks'] if t['id'] == task_id), None)
        if task:
            task['status'] = 'complete' if task['status'] == 'pending' else 'pending'
            save_data(data)
            return json.dumps({'status': 'success', 'new_status': task['status']})
    return json.dumps({'status': 'error', 'message': 'Task not found.'}), 404

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
        else:
            flash('Task not found.', 'danger')
    else:
        flash('Practice plan not found.', 'danger')
    return redirect(url_for('home') + '#practice_plan')


@app.route('/move_note_to_practice_plan/<note_type>/<int:note_index>', methods=['GET', 'POST'])
@login_required
def move_note_to_practice_plan(note_type, note_index):
    data = load_data()
    notes_list = data.get('collaboration_notes', {}).get(note_type)

    if notes_list is None or not (0 <= note_index < len(notes_list)):
        flash('Note not found.', 'danger')
        return redirect(url_for('home') + '#collaboration')

    note_to_move = notes_list[note_index]
    
    if request.method == 'POST':
        plan_id = int(request.form.get('plan_id'))
        plan = next((p for p in data['practice_plans'] if p['id'] == plan_id), None)

        if not plan:
            flash('Selected practice plan not found.', 'danger')
            return redirect(url_for('home') + '#collaboration')

        new_task = {
            "id": int(time.time() * 1000),
            "text": note_to_move['text'],
            "status": "pending",
            "author": note_to_move['author'], # Keep original author
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        plan['tasks'].append(new_task)
        notes_list.pop(note_index) # Remove the original note
        save_data(data)
        flash('Note successfully moved to practice plan.', 'success')
        return redirect(url_for('home') + '#practice_plan')

    return render_template('move_note_to_plan.html', note=note_to_move, practice_plans=data['practice_plans'], note_type=note_type, note_index=note_index)


if __name__ == '__main__':
    # For production, use a proper WSGI server instead of app.run()
    # For development, run as is.
    app.run(host='0.0.0.0', port=5000, debug=True)