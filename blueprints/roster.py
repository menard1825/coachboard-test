from flask import Blueprint, request, redirect, url_for, flash, session, jsonify
from models import Player, User
from db import db
from extensions import socketio
import json
from datetime import datetime

roster_bp = Blueprint('roster', __name__, template_folder='templates')

def get_player_order_as_list(player_order_data):
    """Safely returns player_order as a list, decoding from JSON if necessary."""
    if not player_order_data:
        return []
    if isinstance(player_order_data, list):
        return player_order_data
    if isinstance(player_order_data, str):
        try:
            return json.loads(player_order_data)
        except (json.JSONDecodeError, TypeError):
            return []
    return [] # default to empty list

@roster_bp.route('/add_player', methods=['POST'])
def add_player():
    name = request.form.get('name')
    if not name:
        flash('Player name is required.', 'danger')
        return redirect(url_for('home', _anchor='roster'))

    existing_player = db.session.query(Player).filter_by(name=name, team_id=session['team_id']).first()
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
        notes_timestamp=datetime.now(),
        team_id=session['team_id']
    )
    db.session.add(new_player)
    db.session.flush() # Flush to get the new player's ID

    for user_obj in db.session.query(User).filter_by(team_id=session['team_id']).all():
        current_order = get_player_order_as_list(user_obj.player_order)
        if new_player.id not in current_order:
            current_order.append(new_player.id)
            user_obj.player_order = current_order

    db.session.commit()
    flash(f'Player "{name}" added successfully!', 'success')
    socketio.emit('data_updated', {'message': f'Player {name} added.'})
    
    if 'X-Requested-With' in request.headers and request.headers['X-Requested-With'] == 'XMLHttpRequest':
         return jsonify({'status': 'success'})

    return redirect(url_for('home', _anchor='roster'))

@roster_bp.route('/update_player_inline/<int:player_id>', methods=['POST'])
def update_player_inline(player_id):
    player_to_edit = db.session.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
    if not player_to_edit:
        return jsonify({'status': 'error', 'message': 'Player not found.'}), 404
    
    original_name = player_to_edit.name
    new_name = request.form.get('name', original_name)
    if new_name != original_name and db.session.query(Player).filter_by(name=new_name, team_id=session['team_id']).first():
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
    player_to_edit.notes_timestamp = datetime.now()

    db.session.commit()
    socketio.emit('data_updated', {'message': f'Player {new_name} updated.'})
    return jsonify({'status': 'success', 'message': f'Player "{new_name}" updated successfully!'})

@roster_bp.route('/delete_player/<int:player_id>')
def delete_player(player_id):
    player_to_delete = db.session.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
    if player_to_delete:
        player_name = player_to_delete.name
        player_id_to_delete = player_to_delete.id
        db.session.delete(player_to_delete)

        for user_obj in db.session.query(User).filter_by(team_id=session['team_id']).all():
            current_order = get_player_order_as_list(user_obj.player_order)
            updated_order = [pid for pid in current_order if pid != player_id_to_delete]
            user_obj.player_order = updated_order
        
        if 'player_order' in session:
            session_order = get_player_order_as_list(session['player_order'])
            session['player_order'] = [pid for pid in session_order if pid != player_id_to_delete]
            session.modified = True

        db.session.commit()
        flash(f'Player "{player_name}" removed successfully!', 'success')
        socketio.emit('data_updated', {'message': f'Player {player_name} deleted.'})
    else:
        flash('Player not found.', 'danger')
    return redirect(url_for('home', _anchor=request.args.get('active_tab', 'roster').lstrip('#')))
        
@roster_bp.route('/save_player_order', methods=['POST'])
def save_player_order():
    user = db.session.query(User).filter_by(username=session['username']).first()
    if not user: return jsonify({'status': 'error', 'message': 'User not found'}), 404
    
    new_order = request.json.get('player_order')
    if not isinstance(new_order, list): 
        return jsonify({'status': 'error', 'message': 'Invalid order format'}), 400
    
    user.player_order = new_order
    session['player_order'] = new_order
    session.modified = True
    db.session.commit()
    
    socketio.emit('data_updated', {'message': 'Player order saved.'})
    return jsonify({'status': 'success', 'message': 'Player order saved.'})