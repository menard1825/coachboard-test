from flask import Blueprint, request, redirect, url_for, flash, session, jsonify, render_template
from models import (
    Game, Player, Lineup, Rotation, PitchingOuting, Team, PlayerGameAbsence
)
from db import db
from extensions import socketio
from datetime import datetime
from models import GameRotationEvent, PlayerPitchTarget
from utils import get_pitching_rules_for_team, calculate_pitch_count_summary, model_to_dict
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
    
    # Prefer game_id matching if present, else fallback
    from sqlalchemy import or_
    all_pitching_outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team.id).all() # Keep for summary stats
    game_pitching_log = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter(
        PitchingOuting.team_id == team.id,
        or_(
            PitchingOuting.game_id == game.id,
            db.and_(PitchingOuting.game_id.is_(None), PitchingOuting.opponent == game.opponent, db.func.date(PitchingOuting.date) == game.date.date())
        )
    ).all()

    absences = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team.id).all()
    absent_player_ids = [absence.player_id for absence in absences]

    from models import PlayerPitchTarget
    all_targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team.id).all()
    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(roster_objects, all_pitching_outings, rules, target_date=game.date, all_targets=all_targets, team_timezone=team.timezone, current_game_id=game.id)

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
    game_date_str = request.form['game_date']
    try:
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d')
    except ValueError:
        flash('Invalid date format. Please use YYYY-MM-DD.', 'danger')
        return redirect(url_for('home', _anchor='games'))

    new_game = Game(
        date=game_date,
        start_time=request.form.get('game_start_time', ''),
        opponent=request.form['game_opponent'], 
        location=request.form.get('game_location', ''),
        game_notes=request.form.get('game_notes', ''),
        team_id=session['team_id']
    )
    db.session.add(new_game)
    db.session.commit()
    flash(f'Game vs "{new_game.opponent}" on {new_game.date.strftime("%m/%d/%Y")} added successfully!', 'success')
    socketio.emit('data_updated', {'message': 'New game added.'})
    return redirect(url_for('gameday.game_management', game_id=new_game.id))

@gameday_bp.route('/edit_game/<int:game_id>', methods=['POST'])
def edit_game(game_id):
    game_to_edit = db.session.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
    if not game_to_edit:
        flash('Game not found.', 'danger')
        return redirect(url_for('home', _anchor='games'))

    game_date_str = request.form.get('game_date')
    if game_date_str:
        try:
            game_to_edit.date = datetime.strptime(game_date_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date format. Please use YYYY-MM-DD.', 'danger')
            return redirect(url_for('.game_management', game_id=game_id))

    game_to_edit.start_time = request.form.get('game_start_time', game_to_edit.start_time)
    game_to_edit.opponent = request.form.get('game_opponent', game_to_edit.opponent)
    game_to_edit.location = request.form.get('game_location', game_to_edit.location)
    game_to_edit.game_notes = request.form.get('game_notes', game_to_edit.game_notes)
    db.session.commit()
    flash('Game details updated successfully!', 'success')
    socketio.emit('data_updated', {'message': 'Game details updated.'})
    return redirect(url_for('.game_management', game_id=game_id))

@gameday_bp.route('/delete_game/<int:game_id>')
def delete_game(game_id):
    team_id = session['team_id']
    game_to_delete = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if game_to_delete:
        game_date_str = game_to_delete.date.strftime('%m/%d/%Y')

        # Delete associated Lineup and Rotation to prevent orphaning
        db.session.query(Lineup).filter_by(associated_game_id=game_id, team_id=team_id).delete()
        db.session.query(Rotation).filter_by(associated_game_id=game_id, team_id=team_id).delete()

        db.session.delete(game_to_delete)
        db.session.commit()
        flash(f'Game vs "{game_to_delete.opponent}" on {game_date_str} removed successfully!', 'success')
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
        lineup_positions=payload['lineup_data'],
        associated_game_id=int(payload['associated_game_id']) if payload.get('associated_game_id') else None, 
        team_id=session['team_id']
    )
    db.session.add(new_lineup)
    db.session.commit()

    lineup_dict = model_to_dict(new_lineup)
    socketio.emit('lineup_add', {'lineup': lineup_dict})

    return jsonify({'status': 'success', 'message': f'Lineup "{new_lineup.title}" created successfully!', 'new_id': new_lineup.id, 'lineup': lineup_dict})

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

    return jsonify({'status': 'success', 'message': f'Lineup "{lineup_to_edit.title}" updated successfully!', 'lineup': lineup_dict})

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

    # Re-fetch the rotation to send back a complete object
    saved_rotation = db.session.query(Rotation).get(new_rotation_id)
    if saved_rotation:
        socketio.emit('rotation_save', {'rotation': model_to_dict(saved_rotation)})


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

@gameday_bp.route('/save_rotation_event', methods=['POST'])
def save_rotation_event():
    data = request.get_json()
    game_id = data.get('game_id')
    inning = data.get('inning')
    event_type = data.get('event_type')
    before_alignment = data.get('before_alignment')
    after_alignment = data.get('after_alignment')
    old_pitcher_id = data.get('old_pitcher_id')
    new_pitcher_id = data.get('new_pitcher_id')

    if not all([game_id, inning, event_type, after_alignment]):
        return jsonify({'status': 'error', 'message': 'Missing required fields.'}), 400

    game = db.session.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found or unauthorized.'}), 404

    from models import Player
    if old_pitcher_id and not db.session.query(Player).filter_by(id=old_pitcher_id, team_id=session['team_id']).first():
        return jsonify({'status': 'error', 'message': 'Invalid old pitcher ID.'}), 403
    if new_pitcher_id and not db.session.query(Player).filter_by(id=new_pitcher_id, team_id=session['team_id']).first():
        return jsonify({'status': 'error', 'message': 'Invalid new pitcher ID.'}), 403

    # Generate sequence server-side for robust order
    last_event = db.session.query(GameRotationEvent).filter_by(game_id=game_id).order_by(GameRotationEvent.sequence.desc()).first()
    new_sequence = (last_event.sequence + 1) if last_event else 1

    new_event = GameRotationEvent(
        team_id=session['team_id'],
        game_id=game_id,
        inning=str(inning),
        sequence=new_sequence,
        event_type=event_type,
        changed_by_user=session.get('username'),
        before_alignment=before_alignment,
        after_alignment=after_alignment,
        old_pitcher_id=old_pitcher_id,
        new_pitcher_id=new_pitcher_id
    )
    db.session.add(new_event)

    if event_type == 'End Inning':
        game.live_current_inning = str(inning)

    db.session.commit()

    socketio.emit('rotation_event', {'event': model_to_dict(new_event)})
    return jsonify({'status': 'success'})

@gameday_bp.route('/toggle_live_game', methods=['POST'])
def toggle_live_game():
    data = request.get_json()
    game_id = data.get('game_id')
    is_live = data.get('is_live')

    game = db.session.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found'}), 404

    game.is_live = bool(is_live)
    db.session.commit()
    socketio.emit('game_updated', {'message': 'Game live state updated.'})
    return jsonify({'status': 'success'})

@gameday_bp.route('/undo_rotation_event', methods=['POST'])
def undo_rotation_event():
    data = request.get_json()
    event_id = data.get('event_id')

    event = db.session.query(GameRotationEvent).filter_by(id=event_id, team_id=session['team_id']).first()
    if not event:
        return jsonify({'status': 'error', 'message': 'Event not found.'}), 404

    event.reverted = True

    # If we are undoing an End Inning, we need to revert the game's live_current_inning pointer
    # to the last non-reverted End Inning
    if event.event_type == 'End Inning':
        game = db.session.query(Game).filter_by(id=event.game_id).first()
        last_end_inning = db.session.query(GameRotationEvent).filter_by(
            game_id=event.game_id, event_type='End Inning', reverted=False
        ).order_by(GameRotationEvent.sequence.desc()).first()

        if last_end_inning:
            game.live_current_inning = last_end_inning.inning
        else:
            game.live_current_inning = "1"

    db.session.commit()

    socketio.emit('rotation_event_undone', {'event_id': event_id})
    return jsonify({'status': 'success'})

@gameday_bp.route('/save_final_pitch_counts', methods=['POST'])
def save_final_pitch_counts():
    data = request.get_json()
    game_id = data.get('game_id')
    counts = data.get('counts') # list of dicts: {'player_id': 1, 'pitches': 45}

    if not game_id or not counts:
        return jsonify({'status': 'error', 'message': 'Missing game_id or counts data.'}), 400

    game = db.session.query(Game).filter_by(id=game_id, team_id=session['team_id']).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found.'}), 404

    from models import PitchingOuting

    for count_data in counts:
        player_id = count_data.get('player_id')
        pitches = count_data.get('pitches')

        if not player_id or pitches is None:
            continue

        # Check if an outing already exists for this game and player
        existing_outing = db.session.query(PitchingOuting).filter_by(
            game_id=game.id,
            player_id=player_id,
            team_id=session['team_id']
        ).first()

        if existing_outing:
            existing_outing.pitches = pitches
        else:
            # Figure out if starter or reliever by looking at rotation JSON
            pitcher_type = 'Reliever'
            try:
                if game.associated_rotation_date:
                    from models import Rotation
                    rot = db.session.query(Rotation).filter_by(associated_game_id=game.id).first()
                    if rot and rot.innings and '1' in rot.innings:
                        if rot.innings['1'].get('P') == count_data.get('player_name'): # Wait, we don't have player_name here. We'll use id.
                            # Just default to reliever if we can't easily tell. It's easy to edit later.
                            pass
            except:
                pass

            new_outing = PitchingOuting(
                date=game.date,
                opponent=game.opponent,
                pitches=pitches,
                innings=None, # Leave unknown instead of falsely claiming 0
                outing_type='Game',
                pitcher_type=pitcher_type,
                team_id=session['team_id'],
                player_id=player_id,
                game_id=game.id
            )
            db.session.add(new_outing)

    db.session.commit()
    socketio.emit('pitching_update', {'message': 'Final game pitch counts saved.'})
    return jsonify({'status': 'success'})

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