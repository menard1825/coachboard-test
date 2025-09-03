from flask import Blueprint, request, redirect, url_for, flash, session, render_template
from models import PitchingOuting, Team, Game, Player
from db import db
from sqlalchemy import func, case, cast, Date
from sqlalchemy.orm import joinedload
from extensions import socketio
from utils import get_pitching_rules_for_team, calculate_pitch_count_summary
from datetime import datetime, date, timedelta
from functools import wraps
from .forms import PitchingOutingForm

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

# This route is now handled by pitching_page

@pitching_bp.route('/edit_pitching/<int:outing_id>', methods=['POST'])
def edit_pitching(outing_id):
    outing_to_edit = db.session.get(PitchingOuting, outing_id)
    if not outing_to_edit or outing_to_edit.team_id != session['team_id']:
        flash('Pitching outing not found or you do not have permission to edit it.', 'danger')
        return redirect(url_for('pitching.pitching_page'))
    
    try:
        pitch_date_str = request.form.get('pitch_date')
        if pitch_date_str:
            parsed_date = parse_date(pitch_date_str)
            if parsed_date:
                outing_to_edit.date = parsed_date
            else:
                flash('Invalid date format.', 'danger')
                return redirect(request.referrer or url_for('pitching.pitching_page'))

        player_id = request.form.get('player_id')
        if player_id:
            outing_to_edit.player_id = int(player_id)
        else:
            pitcher_name = request.form.get('pitcher')
            if pitcher_name:
                player = db.session.query(Player).filter(func.lower(Player.name) == func.lower(pitcher_name), Player.team_id == session['team_id']).first()
                if player:
                    outing_to_edit.player_id = player.id

        outing_to_edit.opponent = request.form.get('opponent', outing_to_edit.opponent)
        outing_to_edit.pitches = int(request.form.get('pitches', outing_to_edit.pitches))
        outing_to_edit.innings = float(request.form.get('innings', outing_to_edit.innings))
        outing_to_edit.pitcher_type = request.form.get('pitcher_type', outing_to_edit.pitcher_type)
        outing_to_edit.outing_type = request.form.get('outing_type', outing_to_edit.outing_type)
        
        db.session.commit()
        flash(f'Successfully updated outing for {outing_to_edit.player.full_name}.', 'success')
        socketio.emit('pitching_update', {'message': 'Pitching outing updated.'})
    except ValueError:
        flash('Invalid number format for pitches or innings.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred: {e}', 'danger')
        
    return redirect(url_for('pitching.pitching_page'))


@pitching_bp.route('/delete_pitching/<int:outing_id>')
def delete_pitching(outing_id):
    outing_to_delete = db.session.query(PitchingOuting).filter_by(id=outing_id, team_id=session['team_id']).first()
    if outing_to_delete:
        player_name = outing_to_delete.player.full_name if outing_to_delete.player else "An unknown player"
        db.session.delete(outing_to_delete)
        db.session.commit()
        flash(f'Pitching outing for "{player_name}" removed successfully!', 'success')
        socketio.emit('pitching_update', {'message': 'Pitching outing deleted.'})
    else:
        flash('Pitching outing not found.', 'danger')
    
    redirect_url = request.referrer or url_for('pitching.pitching_page')
    return redirect(redirect_url)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('auth.login'))
        if 'team_id' not in session:
            flash('Please select a team first.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@pitching_bp.route("/pitching", methods=["GET", "POST"])
@login_required
def pitching_page():
    team_id = session['team_id']
    team = db.session.get(Team, team_id)
    form = PitchingOutingForm()

    # Use a separate query for populating the form choices to keep it sorted
    form.player_id.choices = [(p.id, p.full_name) for p in Player.query.filter_by(team_id=team_id).order_by(Player.name).all()]

    if form.validate_on_submit():
        # Handle form submission
        new_outing = PitchingOuting(
            date=form.pitch_date.data,
            player_id=form.player_id.data,
            opponent=form.opponent.data,
            pitches=form.pitches.data,
            innings=form.innings.data,
            pitcher_type=form.pitcher_type.data,
            outing_type=form.outing_type.data,
            team_id=team_id
        )
        db.session.add(new_outing)
        db.session.commit()
        flash('Pitching outing added successfully!', 'success')
        socketio.emit('pitching_update', {'message': 'New pitching outing added.'})
        return redirect(url_for('pitching.pitching_page'))

    # This part is for the GET request or if validation fails
    all_players = Player.query.filter_by(team_id=team_id).options(joinedload(Player.pitching_outings)).all()
    all_outings = [outing for player in all_players for outing in player.pitching_outings]

    recent_outings = sorted(all_outings, key=lambda o: o.date, reverse=True)[:10]

    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(all_players, all_outings, rules)

    designated_pitchers = {p.id: p for p in all_players if p.pitcher_role != 'Not a Pitcher'}
    players_with_outings = {o.player_id: o.player for o in all_outings if o.player is not None}
    combined_pitchers_dict = {**designated_pitchers, **players_with_outings}
    pitchers = list(combined_pitchers_dict.values())

    return render_template(
        "pitching.html",
        recent_outings=recent_outings,
        pitch_count_summary=pitch_count_summary,
        current_team=team,
        pitchers=pitchers,
        form=form
    )


@pitching_bp.route('/rules')
def pitching_rules():
    team = db.session.get(Team, session['team_id'])
    rules_for_team = get_pitching_rules_for_team(team)
    return render_template('rules.html', 
                           team=team, 
                           rules=rules_for_team,
                           rule_set_name=team.pitching_rule_set,
                           age_group=team.age_group)
