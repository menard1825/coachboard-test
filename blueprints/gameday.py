from flask import Blueprint, request, redirect, url_for, flash, session, jsonify, render_template
from flask_socketio import join_room, leave_room
from sqlalchemy.orm.attributes import flag_modified
from models import (
    Game, Player, Lineup, Rotation, PitchingOuting, Team, PlayerGameAbsence
)
from db import db
from extensions import socketio
from datetime import datetime
from utils import get_pitching_rules_for_team, calculate_pitch_count_summary, model_to_dict, parse_date
from sqlalchemy.orm import joinedload
from sqlalchemy import func

gameday_bp = Blueprint('gameday', __name__, template_folder='templates')

def pitching_outing_to_dict(outing):
    if not outing:
        return None
    d = model_to_dict(outing)
    d['player_name'] = outing.player.name if outing.player else "Unknown"
    return d

# --- Game Management ---
@gameday_bp.route('/game/<int:game_id>')
def game_management(game_id):
    team = db.session.get(Team, session['team_id'])
    if not team:
        flash('Team not found.', 'danger')
        return redirect(url_for('home'))

    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        flash('Game not found.', 'danger')
        return redirect(url_for('home', _anchor='games'))

    roster_objects = db.session.query(Player).filter_by(team_id=team.id).order_by(Player.name).all()
    
    lineup_obj = db.session.query(Lineup).filter_by(associated_game_id=game.id, team_id=team.id).first()
    rotation_obj = db.session.query(Rotation).filter_by(associated_game_id=game.id, team_id=team.id).first()
    
    # Fetch all pitching outings for the team once to be used for both summary stats and the game log.
    all_pitching_outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team.id).all()

    game_pitching_log = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter(
        PitchingOuting.team_id == team.id,
        PitchingOuting.opponent == game.opponent,
        func.date(PitchingOuting.date) == game.date.date()
    ).all()

    absences = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team.id).all()
    absent_player_ids = [absence.player_id for absence in absences]

    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(roster_objects, all_pitching_outings, rules)

    lineup_templates = db.session.query(Lineup).filter_by(team_id=team.id, associated_game_id=None).all()

    # NEW: Query for unassigned rotations to use as templates
    rotation_templates = db.session.query(Rotation).filter_by(team_id=team.id, associated_game_id=None).all()

    game_date_for_input = game.date.strftime('%Y-%m-%d')

    return render_template('game_management.html',
                           current_team=team,
                           game=model_to_dict(game),
                           game_date_for_input=game_date_for_input,
                           roster=[model_to_dict(p) for p in roster_objects],
                           lineup=model_to_dict(lineup_obj),
                           rotation=model_to_dict(rotation_obj),
                           game_pitching_log=[pitching_outing_to_dict(o) for o in game_pitching_log],
                           session=session, 
                           absent_player_ids=absent_player_ids,
                           pitch_count_summary=pitch_count_summary,
                           lineup_templates=[model_to_dict(lt) for lt in lineup_templates],
                           # NEW: Pass rotation templates to the render_template call
                           rotation_templates=[model_to_dict(rt) for rt in rotation_templates])

@gameday_bp.route('/add_game', methods=['POST'])
def add_game():
    game_date_str = request.form.get('game_date')
    opponent = request.form.get('game_opponent', '').strip()
    location = request.form.get('game_location', '').strip()
    game_notes = request.form.get('game_notes', '').strip()

    # --- VALIDATION START ---
    game_date = parse_date(game_date_str)
    if not game_date:
        flash('Invalid date format. Please use YYYY-MM-DD.', 'danger')
        return redirect(url_for('home', _anchor='games'))

    if not opponent:
        flash('Opponent name is required.', 'danger')
        return redirect(url_for('home', _anchor='games'))

    if len(opponent) > 100:
        flash('Opponent name cannot exceed 100 characters.', 'danger')
        return redirect(url_for('home', _anchor='games'))

    if len(location) > 100:
        flash('Location cannot exceed 100 characters.', 'danger')
        return redirect(url_for('home', _anchor='games'))
    # --- VALIDATION END ---

    # Ensure the time is set to midnight, not the current time
    game_date = game_date.replace(hour=0, minute=0, second=0, microsecond=0)

    new_game = Game(
        date=game_date,
        opponent=opponent,
        location=location,
        game_notes=game_notes,
        team_id=session['team_id']
    )
    db.session.add(new_game)
    db.session.commit()
    flash(f'Game vs "{new_game.opponent}" on {new_game.date.strftime("%m/%d/%Y")} added successfully!', 'success')
    socketio.emit('game_add', {'game': new_game.to_dict()})
    return redirect(url_for('gameday.game_management', game_id=new_game.id))

@gameday_bp.route('/edit_game/<int:game_id>', methods=['POST'])
def edit_game(game_id):
    game_to_edit = db.session.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
    if not game_to_edit:
        flash('Game not found.', 'danger')
        return redirect(url_for('home', _anchor='games'))

    game_date_str = request.form.get('game_date')
    if game_date_str:
        parsed_date = parse_date(game_date_str)
        if parsed_date:
            # Ensure the time is set to midnight, not the current time
            game_to_edit.date = parsed_date.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            flash('Invalid date format. Please use YYYY-MM-DD.', 'danger')
            return redirect(url_for('.game_management', game_id=game_id))

    opponent = request.form.get('game_opponent', '').strip()
    location = request.form.get('game_location', '').strip()

    if not opponent:
        flash('Opponent name is required.', 'danger')
        return redirect(url_for('.game_management', game_id=game_id))
    if len(opponent) > 100:
        flash('Opponent name cannot exceed 100 characters.', 'danger')
        return redirect(url_for('.game_management', game_id=game_id))
    if len(location) > 100:
        flash('Location cannot exceed 100 characters.', 'danger')
        return redirect(url_for('.game_management', game_id=game_id))

    game_to_edit.opponent = opponent
    game_to_edit.location = location
    game_to_edit.game_notes = request.form.get('game_notes', '').strip()
    db.session.commit()
    flash('Game details updated successfully!', 'success')
    socketio.emit('game_update', {'game': game_to_edit.to_dict()})
    return redirect(url_for('.game_management', game_id=game_id))

@gameday_bp.route('/delete_game/<int:game_id>')
def delete_game(game_id):
    game_to_delete = db.session.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
    if game_to_delete:
        game_date_str = game_to_delete.date.strftime('%m/%d/%Y')
        db.session.delete(game_to_delete)
        db.session.commit()
        flash(f'Game vs "{game_to_delete.opponent}" on {game_date_str} removed successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Game deleted.'})
    else:
        flash('Game not found.', 'danger')
    return redirect(url_for('home', _anchor='games'))


@gameday_bp.route('/game/<int:game_id>/status')
def update_game_status(game_id):
    status = request.args.get('status')
    game = db.session.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found.'}), 404

    if status in ['pre-game', 'live', 'final']:
        game.game_status = status
        db.session.commit()
        socketio.emit('status_changed', {'game_id': game_id, 'status': status}, room=str(game_id))
        return jsonify({'status': 'success', 'message': f'Game status updated to {status}.'})
    else:
        return jsonify({'status': 'error', 'message': 'Invalid game status.'}), 400


@gameday_bp.route('/game/<int:game_id>/update_absences', methods=['POST'])
def update_absences(game_id):
    team_id = session['team_id']
    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if not game:
        flash('Game not found.', 'danger')
        return redirect(url_for('home', _anchor='games'))

    absent_player_ids = [int(pid) for pid in request.form.getlist('absent_players')]
    db.session.query(PlayerGameAbsence).filter_by(game_id=game_id, team_id=team_id).delete()

    for player_id in absent_player_ids:
        player = db.session.query(Player).filter_by(id=player_id, team_id=team_id).first()
        if player:
            new_absence = PlayerGameAbsence(player_id=player.id, game_id=game.id, team_id=team_id)
            db.session.add(new_absence)

    db.session.commit()
    flash('Player availability updated for this game.', 'success')
    socketio.emit('data_updated', {'message': f'Availability updated for game {game_id}.'})
    return redirect(url_for('.game_management', game_id=game_id, _anchor='availability'))

# --- Lineup & Rotation API-like routes ---
@gameday_bp.route('/add_lineup', methods=['POST'])
def add_lineup():
    payload = request.get_json()
    if not payload or 'title' not in payload or 'lineup_data' not in payload:
        return jsonify({'status': 'error', 'message': 'Invalid lineup data.'}), 400
    
    new_lineup = Lineup(
        title=payload['title'], 
        lineup_positions=payload['lineup_data'],
        associated_game_id=int(payload['associated_game_id']) if payload.get('associated_game_id') else None, 
        team_id=session['team_id']
    )
    db.session.add(new_lineup)
    db.session.commit()

    lineup_dict = model_to_dict(new_lineup)
    socketio.emit('lineup_add', {'lineup': lineup_dict})

    return jsonify({
        'status': 'success',
        'message': f'Lineup "{new_lineup.title}" created successfully!',
        'new_id': new_lineup.id,
        'lineup': lineup_dict,
        'last_updated': datetime.now().strftime('%-I:%M:%S %p')
    })

@gameday_bp.route('/edit_lineup/<int:lineup_id>', methods=['POST'])
def edit_lineup(lineup_id):
    lineup_to_edit = db.session.query(Lineup).filter_by(id=lineup_id, team_id=session['team_id']).first()
    if not lineup_to_edit:
        return jsonify({'status': 'error', 'message': 'Lineup not found.'}), 404
    
    payload = request.get_json()
    if not payload or 'title' not in payload or 'lineup_data' not in payload:
        return jsonify({'status': 'error', 'message': 'Invalid lineup data.'}), 400
        
    lineup_to_edit.title = payload['title']
    lineup_to_edit.lineup_positions = payload['lineup_data']
    lineup_to_edit.associated_game_id = int(payload.get('associated_game_id')) if payload.get('associated_game_id') else None
    db.session.commit()

    lineup_dict = model_to_dict(lineup_to_edit)
    socketio.emit('lineup_update', {'lineup': lineup_dict})

    return jsonify({
        'status': 'success',
        'message': f'Lineup "{lineup_to_edit.title}" updated successfully!',
        'lineup': lineup_dict,
        'last_updated': datetime.now().strftime('%-I:%M:%S %p')
    })

@gameday_bp.route('/delete_lineup/<int:lineup_id>')
def delete_lineup(lineup_id):
    lineup_to_delete = db.session.query(Lineup).filter_by(id=lineup_id, team_id=session['team_id']).first()
    if lineup_to_delete:
        db.session.delete(lineup_to_delete)
        db.session.commit()
        flash(f'Lineup "{lineup_to_delete.title}" deleted successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Lineup deleted.'})
    else:
        flash('Lineup not found.', 'danger')
    redirect_url = request.referrer or url_for('home', _anchor='lineups')
    return redirect(redirect_url)

@gameday_bp.route('/save_rotation', methods=['POST'])
def save_rotation():
    rotation_data = request.get_json()
    rotation_id = rotation_data.get('id')
    title = rotation_data.get('title')
    innings_data = rotation_data.get('innings')
    associated_game_id = rotation_data.get('associated_game_id')

    if not title or not isinstance(innings_data, dict):
        return jsonify({'status': 'error', 'message': 'Invalid data provided.'}), 400

    if rotation_id:
        rotation_to_update = db.session.query(Rotation).filter_by(id=rotation_id, team_id=session['team_id']).first()
        if rotation_to_update:
            rotation_to_update.title = title
            rotation_to_update.innings = innings_data
            rotation_to_update.associated_game_id = associated_game_id
            message = 'Rotation updated successfully!'
            new_rotation_id = rotation_id
        else: 
            rotation_id = None
    
    if not rotation_id:
        new_rotation = Rotation(
            title=title, 
            innings=innings_data,
            associated_game_id=associated_game_id, 
            team_id=session['team_id']
        )
        db.session.add(new_rotation)
        db.session.commit()
        new_rotation_id = new_rotation.id
        message = 'Rotation saved successfully!'
    else:
         db.session.commit()

    socketio.emit('data_updated', {'message': 'Rotation saved/updated.'})
    return jsonify({
        'status': 'success',
        'message': message,
        'new_id': new_rotation_id,
        'last_updated': datetime.now().strftime('%-I:%M:%S %p')
    })

@gameday_bp.route('/delete_rotation/<int:rotation_id>')
def delete_rotation(rotation_id):
    rotation_to_delete = db.session.query(Rotation).filter_by(id=rotation_id, team_id=session['team_id']).first()
    if rotation_to_delete:
        db.session.delete(rotation_to_delete)
        db.session.commit()
        flash('Rotation deleted successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Rotation deleted.'})
    else:
        flash('Rotation not found.', 'danger')
    redirect_url = request.referrer or url_for('home', _anchor='rotations')
    return redirect(redirect_url)

@gameday_bp.route('/save_rotation_as_template', methods=['POST'])
def save_rotation_as_template():
    payload = request.get_json()
    title = payload.get('title')
    innings_data = payload.get('innings')

    if not title or not isinstance(innings_data, dict):
        return jsonify({'status': 'error', 'message': 'Invalid data provided.'}), 400

    # Check for existing template with the same name to avoid duplicates
    existing_template = db.session.query(Rotation).filter_by(
        title=title,
        team_id=session['team_id'],
        associated_game_id=None
    ).first()

    if existing_template:
        return jsonify({'status': 'error', 'message': f'A template with the name "{title}" already exists.'}), 400

    new_template = Rotation(
        title=title,
        innings=innings_data,
        associated_game_id=None, # This makes it a template
        team_id=session['team_id']
    )
    db.session.add(new_template)
    db.session.commit()

    # Emit an update so other open tabs/users see the new template
    socketio.emit('data_updated', {'message': 'New rotation template created.'})

    return jsonify({
        'status': 'success',
        'message': 'Template saved successfully!',
        'new_template': model_to_dict(new_template)
    })

# --- Socket.IO Event Handlers for Real-Time Gameday ---

@socketio.on('join_game')
def on_join(data):
    """Client joins a room for a specific game."""
    game_id = data.get('game_id')
    if game_id:
        room = str(game_id)
        join_room(room)
        print(f"Client joined room: {room}")

@socketio.on('leave_game')
def on_leave(data):
    """Client leaves a room for a specific game."""
    game_id = data.get('game_id')
    if game_id:
        room = str(game_id)
        leave_room(room)
        print(f"Client left room: {room}")

@socketio.on('game_update')
def handle_game_update(data):
    """Handles live updates to the game state (score, inning, outs)."""
    game_id = data.get('game_id')
    game = db.session.get(Game, game_id)
    if not game:
        return

    # Update score, inning, and outs from the received data
    score_data = data.get('score', {})
    game.our_score = score_data.get('our_score', game.our_score)
    game.opponent_score = score_data.get('opponent_score', game.opponent_score)
    game.inning = data.get('inning', game.inning)
    game.outs = data.get('outs', game.outs)

    db.session.commit()

    # Broadcast the updated state to all clients in the same game room
    emit_data = {
        'game_id': game_id,
        'score': {'our_score': game.our_score, 'opponent_score': game.opponent_score},
        'inning': game.inning,
        'outs': game.outs
    }
    socketio.emit('game_state_updated', emit_data, room=str(game_id))

@socketio.on('substitution')
def handle_substitution(data):
    """Handles a player substitution and updates the rotation."""
    game_id = data.get('game_id')
    inning = str(data.get('inning'))
    position = data.get('position')
    new_player_name = data.get('player_name')

    rotation = db.session.query(Rotation).filter_by(associated_game_id=game_id).first()
    if not rotation or not rotation.innings:
        return

    # Update the specific position for the specific inning
    if inning in rotation.innings and position:
        rotation.innings[inning][position] = new_player_name
        flag_modified(rotation, "innings") # Mark the JSONB field as modified
        db.session.commit()

        # Broadcast the entire updated rotation to all clients
        socketio.emit('defensive_rotation_updated', {
            'game_id': game_id,
            'rotation': model_to_dict(rotation)
        }, room=str(game_id))

@socketio.on('swap_positions')
def handle_position_swap(data):
    """Handles a two-player position swap on the field."""
    game_id = data.get('game_id')
    inning = str(data.get('inning'))
    pos1 = data.get('pos1')
    player1_name = data.get('player1_name')
    pos2 = data.get('pos2')
    player2_name = data.get('player2_name')

    rotation = db.session.query(Rotation).filter_by(associated_game_id=game_id).first()
    if not rotation or not rotation.innings:
        return

    if inning in rotation.innings and pos1 and pos2:
        # Perform the swap
        rotation.innings[inning][pos1] = player2_name
        rotation.innings[inning][pos2] = player1_name

        flag_modified(rotation, "innings") # Mark the JSONB field as modified
        db.session.commit()

        # Broadcast the updated rotation
        socketio.emit('defensive_rotation_updated', {
            'game_id': game_id,
            'rotation': model_to_dict(rotation)
        }, room=str(game_id))