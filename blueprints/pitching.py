from flask import Blueprint, request, redirect, url_for, flash, session, render_template
from models import PitchingOuting, Team, Game, Player
from db import db
from sqlalchemy.orm import joinedload
from extensions import socketio
from utils import get_pitching_rules_for_team
from datetime import datetime

pitching_bp = Blueprint('pitching', __name__, template_folder='templates')

def parse_date(date_str):
    """Tries to parse a date string with multiple formats."""
    if not date_str:
        return None
    for fmt in ('%Y-%m-%d', '%A, %m/%d/%y, %I:%M %p', '%A, %m/%d/%y'):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    return None

@pitching_bp.route('/add_pitching', methods=['POST'])
def add_pitching():
    game_id = request.form.get('game_id')
    game = None
    if game_id:
        game = db.session.get(Game, game_id)

    try:
        pitch_count = int(request.form['pitches'])
        innings_pitched = float(request.form['innings'])
        player_id = int(request.form.get('player_id'))
    except (ValueError, KeyError, TypeError):
        flash('Pitch count, innings, and player must be valid.', 'danger')
        return redirect(request.referrer or url_for('home', _anchor='pitching'))

    pitch_date_str = request.form.get('pitch_date')
    pitch_date = parse_date(pitch_date_str) or (game.date if game else None)
    if not pitch_date:
        flash('A valid date is required.', 'danger')
        return redirect(request.referrer or url_for('home', _anchor='pitching'))

    opponent = request.form.get('opponent') or (game.opponent if game else None)
    if not opponent:
        flash('Opponent is required.', 'danger')
        return redirect(request.referrer or url_for('home', _anchor='pitching'))

    player = db.session.get(Player, player_id)
    if not player:
        flash('Selected pitcher not found.', 'danger')
        return redirect(request.referrer or url_for('home', _anchor='pitching'))

    new_outing = PitchingOuting(
        date=pitch_date, player_id=player_id, opponent=opponent, pitches=pitch_count,
        innings=innings_pitched, pitcher_type=request.form.get('pitcher_type', 'Starter'),
        outing_type=request.form.get('outing_type', 'Game'), team_id=session['team_id']
    )
    db.session.add(new_outing)
    db.session.commit()
    flash(f'Pitching outing for "{player.full_name}" added successfully!', 'success')
    socketio.emit('pitching_update')
    
    if game_id:
        return redirect(url_for('gameday.game_management', game_id=game_id, _anchor='pitching'))
    return redirect(url_for('home', _anchor='pitching'))

@pitching_bp.route('/edit_pitching/<int:outing_id>', methods=['POST'])
def edit_pitching(outing_id):
    outing_to_edit = db.session.get(PitchingOuting, outing_id)
    if not outing_to_edit or outing_to_edit.team_id != session['team_id']:
        flash('Pitching outing not found.', 'danger')
        return redirect(request.referrer or url_for('home', _anchor='pitching'))
    
    try:
        pitch_date_str = request.form.get('pitch_date')
        if pitch_date_str:
            outing_to_edit.date = parse_date(pitch_date_str) or outing_to_edit.date

        outing_to_edit.player_id = int(request.form.get('player_id', outing_to_edit.player_id))
        outing_to_edit.opponent = request.form.get('opponent', outing_to_edit.opponent)
        outing_to_edit.pitches = int(request.form.get('pitches', outing_to_edit.pitches))
        outing_to_edit.innings = float(request.form.get('innings', outing_to_edit.innings))
        outing_to_edit.pitcher_type = request.form.get('pitcher_type', outing_to_edit.pitcher_type)
        outing_to_edit.outing_type = request.form.get('outing_type', outing_to_edit.outing_type)
        
        db.session.commit()
        flash(f'Successfully updated outing for {outing_to_edit.player.full_name}.', 'success')
        socketio.emit('pitching_update')
    except (ValueError, TypeError):
        flash('Invalid number format for pitches or innings.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred: {e}', 'danger')
        
    return redirect(request.referrer or url_for('home', _anchor='pitching'))

@pitching_bp.route('/delete_pitching/<int:outing_id>')
def delete_pitching(outing_id):
    outing_to_delete = db.session.query(PitchingOuting).filter_by(id=outing_id, team_id=session['team_id']).first()
    if outing_to_delete:
        player_name = outing_to_delete.player.full_name if outing_to_delete.player else "An unknown player"
        db.session.delete(outing_to_delete)
        db.session.commit()
        flash(f'Pitching outing for "{player_name}" removed successfully!', 'success')
        socketio.emit('pitching_update')
    else:
        flash('Pitching outing not found.', 'danger')
    
    return redirect(request.referrer or url_for('home', _anchor='pitching'))

@pitching_bp.route('/rules')
def pitching_rules():
    team = db.session.get(Team, session['team_id'])
    if not team:
        flash("Team not found.", 'danger')
        return redirect(url_for('home'))
    rules_for_team = get_pitching_rules_for_team(team)
    return render_template('rules.html', 
                           team=team, 
                           rules=rules_for_team,
                           rule_set_name=team.pitching_rule_set,
                           age_group=team.age_group)
