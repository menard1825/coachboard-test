# menard1825/coachboard-test/coachboard-test-structure-overhaul/blueprints/gameday.py
from flask import Blueprint, request, redirect, url_for, flash, session, jsonify, render_template
from models import (
    Game, Player, Lineup, Rotation, PitchingOuting, Team, PlayerGameAbsence
)
from db import db
from extensions import socketio
import json
from utils import get_pitching_rules_for_team, calculate_pitch_count_summary

gameday_bp = Blueprint('gameday', __name__, template_folder='templates')

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
    
    roster_objects = db.session.query(Player).filter_by(team_id=team.id).all()
    
    lineup_obj = db.session.query(Lineup).filter_by(associated_game_id=game.id, team_id=team.id).first()
    rotation_obj = db.session.query(Rotation).filter_by(associated_game_id=game.id, team_id=team.id).first()
    
    all_pitching_outings = db.session.query(PitchingOuting).filter_by(team_id=team.id).all()
    game_pitching_log = [o for o in all_pitching_outings if o.opponent == game.opponent and o.date == game.date]
    
    absences = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team.id).all()
    absent_player_ids = [absence.player_id for absence in absences]

    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(roster_objects, all_pitching_outings, rules)

    return render_template('game_management.html', 
                           game=game.to_dict(), 
                           roster=[p.to_dict() for p in roster_objects], 
                           lineup=lineup_obj.to_dict() if lineup_obj else None, 
                           rotation=rotation_obj.to_dict() if rotation_obj else None, 
                           game_pitching_log=game_pitching_log, 
                           session=session, 
                           absent_player_ids=absent_player_ids,
                           pitch_count_summary=pitch_count_summary)

@gameday_bp.route('/add_game', methods=['POST'])
def add_game():
    new_game = Game(
        date=request.form['game_date'], 
        opponent=request.form['game_opponent'], 
        location=request.form.get('game_location', ''),
        game_notes=request.form.get('game_notes', ''),
        team_id=session['team_id']
    )
    db.session.add(new_game)
    db.session.commit()
    flash(f'Game vs "{new_game.opponent}" on {new_game.date} added successfully!', 'success')
    socketio.emit('data_updated', {'message': 'New game added.'})
    return redirect(url_for('gameday.game_management', game_id=new_game.id))

@gameday_bp.route('/edit_game/<int:game_id>', methods=['POST'])
def edit_game(game_id):
    game_to_edit = db.session.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
    if not game_to_edit:
        flash('Game not found.', 'danger')
        return redirect(url_for('home', _anchor='games'))
    game_to_edit.date = request.form.get('game_date', game_to_edit.date)
    game_to_edit.opponent = request.form.get('game_opponent', game_to_edit.opponent)
    game_to_edit.location = request.form.get('game_location', game_to_edit.location)
    game_to_edit.game_notes = request.form.get('game_notes', game_to_edit.game_notes)
    db.session.commit()
    flash('Game details updated successfully!', 'success')
    socketio.emit('data_updated', {'message': 'Game details updated.'})
    return redirect(url_for('.game_management', game_id=game_id))

@gameday_bp.route('/delete_game/<int:game_id>')
def delete_game(game_id):
    game_to_delete = db.session.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
    if game_to_delete:
        db.session.delete(game_to_delete)
        db.session.commit()
        flash(f'Game vs "{game_to_delete.opponent}" on {game_to_delete.date} removed successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Game deleted.'})
    else:
        flash('Game not found.', 'danger')
    return redirect(url_for('home', _anchor='games'))

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
        lineup_positions=json.dumps(payload['lineup_data']),
        associated_game_id=int(payload['associated_game_id']) if payload.get('associated_game_id') else None, 
        team_id=session['team_id']
    )
    db.session.add(new_lineup)
    db.session.commit()
    socketio.emit('data_updated', {'message': 'New lineup added.'})
    return jsonify({'status': 'success', 'message': f'Lineup "{new_lineup.title}" created successfully!', 'new_id': new_lineup.id})

@gameday_bp.route('/edit_lineup/<int:lineup_id>', methods=['POST'])
def edit_lineup(lineup_id):
    lineup_to_edit = db.session.query(Lineup).filter_by(id=lineup_id, team_id=session['team_id']).first()
    if not lineup_to_edit:
        return jsonify({'status': 'error', 'message': 'Lineup not found.'}), 404
    
    payload = request.get_json()
    if not payload or 'title' not in payload or 'lineup_data' not in payload:
        return jsonify({'status': 'error', 'message': 'Invalid lineup data.'}), 400
        
    lineup_to_edit.title = payload['title']
    lineup_to_edit.lineup_positions = json.dumps(payload['lineup_data'])
    lineup_to_edit.associated_game_id = int(payload.get('associated_game_id')) if payload.get('associated_game_id') else None
    db.session.commit()
    socketio.emit('data_updated', {'message': 'Lineup updated.'})
    return jsonify({'status': 'success', 'message': f'Lineup "{lineup_to_edit.title}" updated successfully!'})

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
            rotation_to_update.innings = json.dumps(innings_data)
            rotation_to_update.associated_game_id = associated_game_id
            message = 'Rotation updated successfully!'
            new_rotation_id = rotation_id
        else: 
            rotation_id = None
    
    if not rotation_id:
        new_rotation = Rotation(
            title=title, 
            innings=json.dumps(innings_data), 
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
    return jsonify({'status': 'success', 'message': message, 'new_id': new_rotation_id})

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
