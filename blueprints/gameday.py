from flask import Blueprint, request, redirect, url_for, flash, session, jsonify, render_template
from models import (
    Game, Player, Lineup, Rotation, PitchingOuting, Team, PlayerGameAbsence
)
from db import SessionLocal
from app import socketio, get_pitching_rules_for_team, calculate_pitch_counts, calculate_pitcher_availability, calculate_cumulative_pitching_stats
import json
from datetime import datetime

gameday_bp = Blueprint('gameday', __name__, template_folder='templates')

# --- Game Management ---
@gameday_bp.route('/game/<int:game_id>')
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
        lineup_dict = json.loads(lineup_obj.lineup_positions or "[]") if lineup_obj else {"id": None, "title": f"Lineup for vs {game.opponent}", "lineup_positions": [], "associated_game_id": game.id}

        rotation_obj = db.query(Rotation).filter_by(associated_game_id=game.id, team_id=team.id).first()
        rotation_dict = json.loads(rotation_obj.innings or "{}") if rotation_obj else {"id": None, "title": f"Rotation for vs {game.opponent}", "innings": {}, "associated_game_id": game.id}

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

@gameday_bp.route('/add_game', methods=['POST'])
def add_game():
    db = SessionLocal()
    try:
        new_game = Game(
            date=request.form['game_date'], 
            opponent=request.form['game_opponent'], 
            location=request.form.get('game_location', ''),
            game_notes=request.form.get('game_notes', ''),
            team_id=session['team_id']
        )
        db.add(new_game)
        db.commit()
        flash(f'Game vs "{new_game.opponent}" on {new_game.date} added successfully!', 'success')
        socketio.emit('data_updated', {'message': 'New game added.'})
        return redirect(url_for('gameday.game_management', game_id=new_game.id))
    finally:
        db.close()

@gameday_bp.route('/edit_game/<int:game_id>', methods=['POST'])
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
        return redirect(url_for('.game_management', game_id=game_id))
    finally:
        db.close()

@gameday_bp.route('/delete_game/<int:game_id>')
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

@gameday_bp.route('/game/<int:game_id>/update_absences', methods=['POST'])
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
    finally:
        db.close()
    return redirect(url_for('.game_management', game_id=game_id, _anchor='availability'))


# --- Lineup & Rotation ---

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

@gameday_bp.route('/add_lineup', methods=['POST'])
def add_lineup():
    db = SessionLocal()
    try:
        payload = request.get_json()
        if not payload or 'title' not in payload or 'lineup_data' not in payload:
            return jsonify({'status': 'error', 'message': 'Invalid lineup data.'}), 400
        
        new_lineup = Lineup(
            title=payload['title'], 
            lineup_positions=json.dumps(payload['lineup_data']),
            associated_game_id=int(payload['associated_game_id']) if payload.get('associated_game_id') else None, 
            team_id=session['team_id']
        )
        db.add(new_lineup)
        _sync_lineup_to_rotation(db, new_lineup)
        db.commit()
        socketio.emit('data_updated', {'message': 'New lineup added.'})
        return jsonify({'status': 'success', 'message': f'Lineup "{new_lineup.title}" created successfully!', 'new_id': new_lineup.id})
    finally:
        db.close()

@gameday_bp.route('/edit_lineup/<int:lineup_id>', methods=['POST'])
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

@gameday_bp.route('/delete_lineup/<int:lineup_id>')
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

@gameday_bp.route('/save_rotation', methods=['POST'])
def save_rotation():
    db = SessionLocal()
    try:
        rotation_data = request.get_json()
        rotation_id = rotation_data.get('id')
        title = rotation_data.get('title')
        innings_data = rotation_data.get('innings')
        associated_game_id = rotation_data.get('associated_game_id')

        if not title or not isinstance(innings_data, dict):
            return jsonify({'status': 'error', 'message': 'Invalid data provided.'}), 400

        if rotation_id:
            rotation_to_update = db.query(Rotation).filter_by(id=rotation_id, team_id=session['team_id']).first()
            if rotation_to_update:
                rotation_to_update.title = title
                rotation_to_update.innings = json.dumps(innings_data)
                rotation_to_update.associated_game_id = associated_game_id
                message = 'Rotation updated successfully!'
                new_rotation_id = rotation_id
            else: 
                rotation_id = None # Force creation if ID not found
        
        if not rotation_id:
            new_rotation = Rotation(
                title=title, 
                innings=json.dumps(innings_data), 
                associated_game_id=associated_game_id, 
                team_id=session['team_id']
            )
            db.add(new_rotation)
            db.commit() # Commit to get the new ID
            new_rotation_id = new_rotation.id
            message = 'Rotation saved successfully!'
        else:
             db.commit()

        socketio.emit('data_updated', {'message': 'Rotation saved/updated.'})
        return jsonify({'status': 'success', 'message': message, 'new_id': new_rotation_id})
    finally:
        db.close()

@gameday_bp.route('/delete_rotation/<int:rotation_id>')
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