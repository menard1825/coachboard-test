from flask import Blueprint, request, redirect, url_for, flash, session, render_template
from models import PitchingOuting, Team
from db import db
from extensions import socketio
from utils import get_pitching_rules_for_team

pitching_bp = Blueprint('pitching', __name__, template_folder='templates')

@pitching_bp.route('/add_pitching', methods=['POST'])
def add_pitching():
    try:
        pitch_count = int(request.form['pitches'])
        innings_pitched = float(request.form['innings'])
    except ValueError:
        flash('Pitch count and innings must be valid numbers.', 'danger')
        return redirect(url_for('home', _anchor='pitching'))

    new_outing = PitchingOuting(
        date=request.form['pitch_date'], 
        pitcher=request.form['pitcher'], 
        opponent=request.form['opponent'],
        pitches=pitch_count, 
        innings=innings_pitched, 
        pitcher_type=request.form.get('pitcher_type', 'Starter'),
        outing_type=request.form.get('outing_type', 'Game'), 
        team_id=session['team_id']
    )
    db.session.add(new_outing)
    db.session.commit()
    flash(f'Pitching outing for "{new_outing.pitcher}" added successfully!', 'success')
    socketio.emit('data_updated', {'message': 'New pitching outing added.'})
    
    game_id = request.form.get('game_id')
    if game_id:
        return redirect(url_for('gameday.game_management', game_id=game_id, _anchor='pitching'))
    return redirect(url_for('home', _anchor='pitching'))

@pitching_bp.route('/edit_pitching/<int:outing_id>', methods=['POST'])
def edit_pitching(outing_id):
    outing_to_edit = db.session.get(PitchingOuting, outing_id)
    if not outing_to_edit or outing_to_edit.team_id != session['team_id']:
        flash('Pitching outing not found or you do not have permission to edit it.', 'danger')
        return redirect(url_for('home', _anchor='pitching'))
    
    try:
        outing_to_edit.date = request.form.get('pitch_date', outing_to_edit.date)
        outing_to_edit.pitcher = request.form.get('pitcher', outing_to_edit.pitcher)
        outing_to_edit.opponent = request.form.get('opponent', outing_to_edit.opponent)
        outing_to_edit.pitches = int(request.form.get('pitches', outing_to_edit.pitches))
        outing_to_edit.innings = float(request.form.get('innings', outing_to_edit.innings))
        outing_to_edit.pitcher_type = request.form.get('pitcher_type', outing_to_edit.pitcher_type)
        outing_to_edit.outing_type = request.form.get('outing_type', outing_to_edit.outing_type)
        
        db.session.commit()
        flash(f'Successfully updated outing for {outing_to_edit.pitcher}.', 'success')
        socketio.emit('data_updated', {'message': 'Pitching outing updated.'})
    except ValueError:
        flash('Invalid number format for pitches or innings.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred: {e}', 'danger')
        
    return redirect(url_for('home', _anchor='pitching'))


@pitching_bp.route('/delete_pitching/<int:outing_id>')
def delete_pitching(outing_id):
    outing_to_delete = db.session.query(PitchingOuting).filter_by(id=outing_id, team_id=session['team_id']).first()
    if outing_to_delete:
        db.session.delete(outing_to_delete)
        db.session.commit()
        flash(f'Pitching outing for "{outing_to_delete.pitcher}" removed successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Pitching outing deleted.'})
    else:
        flash('Pitching outing not found.', 'danger')
    
    redirect_url = request.referrer or url_for('home', _anchor='pitching')
    return redirect(redirect_url)

@pitching_bp.route('/rules')
def pitching_rules():
    team = db.session.get(Team, session['team_id'])
    rules_for_team = get_pitching_rules_for_team(team)
    return render_template('rules.html', 
                           team=team, 
                           rules=rules_for_team,
                           rule_set_name=team.pitching_rule_set,
                           age_group=team.age_group)
