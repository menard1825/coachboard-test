from flask import Blueprint, request, redirect, url_for, flash, session, jsonify
from models import ScoutedPlayer, Player, User
from db import db
from extensions import socketio
from datetime import datetime

scouting_bp = Blueprint('scouting', __name__, template_folder='templates')

@scouting_bp.route('/add_scouted_player', methods=['POST'])
def add_scouted_player():
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
        db.session.add(new_player)
        db.session.commit()
        socketio.emit('data_updated', {'message': 'New scouted player added.'})
        return jsonify({'status': 'success', 'message': f'Player "{new_player.name}" added to {scouted_player_type.replace("_", " ").title()} list.'})
    except Exception as e:
        print(f"Error adding scouted player: {e}")
        return jsonify({'status': 'error', 'message': 'An internal server error occurred.'}), 500

@scouting_bp.route('/delete_scouted_player/<list_type>/<int:player_id>')
def delete_scouted_player(list_type, player_id):
    player_to_delete = db.session.query(ScoutedPlayer).filter_by(id=player_id, list_type=list_type, team_id=session['team_id']).first()
    if player_to_delete:
        player_name = player_to_delete.name
        db.session.delete(player_to_delete)
        db.session.commit()
        flash(f'Removed {player_name} from the scouting list.', 'success')
        socketio.emit('data_updated', {'message': f'Scouted player {player_name} removed.'})
    else:
        flash(f'Could not find the player to remove.', 'warning')
    return redirect(url_for('home', _anchor='scouting_list'))

@scouting_bp.route('/move_scouted_player/<from_type>/<to_type>/<int:player_id>', methods=['POST'])
def move_scouted_player(from_type, to_type, player_id):
    player_to_move = db.session.query(ScoutedPlayer).filter_by(id=player_id, list_type=from_type, team_id=session['team_id']).first()
    if player_to_move:
        player_to_move.list_type = to_type
        db.session.commit()
        flash(f'Player "{player_to_move.name}" moved to {to_type.replace("_", " ").title()} list.', 'success')
        socketio.emit('data_updated', {'message': f'Scouted player {player_to_move.name} moved.'})
    else:
        flash('Could not move player.', 'danger')
    return redirect(url_for('home', _anchor='scouting_list'))

@scouting_bp.route('/move_scouted_player_to_roster/<int:player_id>', methods=['POST'])
def move_scouted_player_to_roster(player_id):
    scouted_player = db.session.query(ScoutedPlayer).filter_by(id=player_id, list_type='committed', team_id=session['team_id']).first()
    if not scouted_player:
        flash('Committed player not found.', 'danger')
        return redirect(url_for('home', _anchor='scouting_list'))
    if db.session.query(Player).filter_by(name=scouted_player.name, team_id=session['team_id']).first():
        flash(f'Cannot move "{scouted_player.name}" to roster because a player with that name already exists.', 'danger')
        return redirect(url_for('home', _anchor='scouting_list'))
        
    new_roster_player = Player(
        name=scouted_player.name, number="", position1=scouted_player.position1, position2=scouted_player.position2,
        throws=scouted_player.throws, bats=scouted_player.bats, notes="", pitcher_role="Not a Pitcher", has_lessons="No",
        lesson_focus="", notes_author=session['username'], notes_timestamp=datetime.now(), team_id=session['team_id']
    )
    db.session.add(new_roster_player)
    db.session.flush() # to get the new player's ID
    db.session.delete(scouted_player)
    
    for user_obj in db.session.query(User).filter_by(team_id=session['team_id']).all():
        current_order = user_obj.player_order or []
        if new_roster_player.id not in current_order:
            current_order.append(new_roster_player.id)
            user_obj.player_order = current_order

    if 'player_order' in session and new_roster_player.id not in session['player_order']:
        session['player_order'].append(new_roster_player.id)
        session.modified = True
        
    db.session.commit()
    flash(f'Player "{new_roster_player.name}" moved to Roster. Please assign a number.', 'success')
    socketio.emit('data_updated', {'message': f'Scouted player {new_roster_player.name} moved to roster.'})
    return redirect(url_for('home', _anchor='scouting_list'))