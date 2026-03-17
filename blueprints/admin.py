from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
import uuid
import os
import random
import string
import json
import csv
import io
import zipfile
from functools import wraps

from db import db
from models import User, Team, Player, Lineup, PitchingOuting, ScoutedPlayer, Rotation, Game, CollaborationNote, PracticePlan, PracticeTask, PlayerDevelopmentFocus, Sign, PlayerGameAbsence, PlayerPracticeAbsence
from extensions import socketio
from utils import PITCHING_RULES, allowed_file

# Define role constants
SUPER_ADMIN = 'Super Admin'
HEAD_COACH = 'Head Coach'

# Create the Blueprint
admin_bp = Blueprint('admin', __name__, template_folder='templates', url_prefix='/admin')

# Decorators
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('auth.login'))
        if session.get('role') not in [HEAD_COACH, SUPER_ADMIN]:
            flash('You must be a Head Coach or Super Admin to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('auth.login'))
        if session.get('role') != SUPER_ADMIN:
            flash('You must be a Super Admin to access this page.', 'danger')
            return redirect(url_for('admin.user_management'))
        return f(*args, **kwargs)
    return decorated_function


# --- USER & TEAM MANAGEMENT ROUTES ---
@admin_bp.route('/users')
@admin_required
def user_management():
    teams = []
    if session.get('role') == SUPER_ADMIN:
        users = db.session.query(User).options(joinedload(User.team)).all()
        teams = db.session.query(Team).order_by(Team.team_name).all()
    else:
        users = db.session.query(User).filter_by(team_id=session['team_id']).options(joinedload(User.team)).all()

    return render_template('user_management.html', users=users, teams=teams, session=session)


@admin_bp.route('/teams')
@super_admin_required
def team_management():
    teams = db.session.query(Team).options(joinedload(Team.users)).order_by(Team.team_name).all()
    return render_template('team_management.html', teams=teams, session=session)


@admin_bp.route('/add_user', methods=['POST'])
@admin_required
def add_user():
    username = request.form.get('username')
    password = request.form.get('password')
    full_name = request.form.get('full_name')
    role = request.form.get('role', 'Assistant Coach')
    
    team_id_for_new_user = None
    if session.get('role') == SUPER_ADMIN:
        form_team_id = request.form.get('team_id')
        if not form_team_id:
            flash('Super Admins must select a team for the new user.', 'danger')
            return redirect(url_for('.user_management'))
        team_id_for_new_user = int(form_team_id)
    else:
        team_id_for_new_user = session['team_id']

    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('.user_management'))
    if db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first():
        flash('Username already exists.', 'danger')
        return redirect(url_for('.user_management'))

    if role == SUPER_ADMIN and session.get('role') != SUPER_ADMIN:
        flash('Only a Super Admin can create another Super Admin.', 'danger')
        return redirect(url_for('.user_management'))
        
    hashed_password = generate_password_hash(password)
    default_tab_keys = ['roster', 'lineups', 'pitching', 'scouting_list', 'rotations', 'games', 'collaboration', 'practice_plan']
    
    new_user = User(
        username=username,
        full_name=full_name,
        password_hash=hashed_password,
        role=role,
        tab_order=json.dumps(default_tab_keys),
        last_login=None,
        player_order=[],
        team_id=team_id_for_new_user
    )
    db.session.add(new_user)
    db.session.commit()
    
    team_name = db.session.get(Team, team_id_for_new_user).team_name
    flash(f"User '{username}' created successfully for team '{team_name}'.", 'success')
    socketio.emit('data_updated', {'message': 'A new user was added.'})
    return redirect(url_for('.user_management'))

@admin_bp.route('/delete_user/<username>', methods=['POST'])
@admin_required
def delete_user(username):
    user_to_delete = db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first()
    if user_to_delete:
        # MODIFIED: Check against the user's role instead of hardcoded username
        if user_to_delete.role == SUPER_ADMIN:
            flash("A Super Admin cannot be deleted.", "danger")
            return redirect(url_for('.user_management'))
            
        if session.get('role') == HEAD_COACH and user_to_delete.team_id != session.get('team_id'):
            flash('You do not have permission to delete this user.', 'danger')
            return redirect(url_for('.user_management'))
            
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f"User '{username}' has been deleted.", "success")
        socketio.emit('data_updated', {'message': f"User {username} deleted."})
    else:
        flash("User not found.", "danger")
    return redirect(url_for('.user_management'))


@admin_bp.route('/reset_password/<username>', methods=['POST'])
@admin_required
def reset_password(username):
    user_to_reset = db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first()
    if not user_to_reset:
        flash('User not found.', 'danger')
        return redirect(url_for('.user_management'))
    
    # MODIFIED: Check against the user's role instead of hardcoded username
    if user_to_reset.role == SUPER_ADMIN:
        flash("A Super Admin's password cannot be reset via this interface.", "danger")
        return redirect(url_for('.user_management'))

    if session.get('role') == HEAD_COACH and user_to_reset.team_id != session.get('team_id'):
        flash('You do not have permission to reset this password.', 'danger')
        return redirect(url_for('.user_management'))
        
    temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    user_to_reset.password_hash = generate_password_hash(temp_password)
    db.session.commit()
    flash(f"Password for {username} has been reset. The temporary password is: {temp_password}", 'success')
    socketio.emit('data_updated', {'message': f"Password for {username} reset."})
    return redirect(url_for('.user_management'))


@admin_bp.route('/edit_user/<username>', methods=['POST'])
@admin_required
def edit_user(username):
    user_to_edit = db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first()
    if not user_to_edit:
        flash('User not found.', 'danger')
        return redirect(url_for('.user_management'))

    # Permission check: Head Coach can only edit users on their team
    if session.get('role') == HEAD_COACH and user_to_edit.team_id != session.get('team_id'):
        flash('You do not have permission to edit this user.', 'danger')
        return redirect(url_for('.user_management'))

    new_full_name = request.form.get('full_name')
    new_role = request.form.get('role')

    # Update Full Name
    user_to_edit.full_name = new_full_name
    if session.get('username') == user_to_edit.username:
        session['full_name'] = user_to_edit.full_name

    # Update Role
    if new_role and new_role != user_to_edit.role:
        # Prevent self-demotion if the user is the sole Super Admin
        if user_to_edit.role == SUPER_ADMIN and user_to_edit.username == session['username']:
            if db.session.query(User).filter_by(role=SUPER_ADMIN).count() == 1:
                flash('You cannot demote yourself as the sole Super Admin. Assign another Super Admin first.', 'danger')
                db.session.rollback() # Rollback name change
                return redirect(url_for('.user_management'))

        # Prevent non-Super Admins from assigning Super Admin role
        if new_role == SUPER_ADMIN and session.get('role') != SUPER_ADMIN:
            flash('Only a Super Admin can assign the Super Admin role.', 'danger')
            db.session.rollback() # Rollback name change
            return redirect(url_for('.user_management'))

        if new_role in [HEAD_COACH, 'Assistant Coach', 'Game Changer', SUPER_ADMIN]:
            user_to_edit.role = new_role
        else:
            flash('Invalid role selected.', 'danger')
            db.session.rollback() # Rollback name change
            return redirect(url_for('.user_management'))

    db.session.commit()
    flash(f"Successfully updated user {username}.", 'success')
    socketio.emit('data_updated', {'message': f"User {username}'s details updated."})
    return redirect(url_for('.user_management'))


# --- TEAM SETTINGS ROUTES ---
@admin_bp.route('/settings', methods=['GET'])
@admin_required
def admin_settings():
    team_settings = db.session.get(Team, session['team_id'])
    return render_template('admin_settings.html', session=session, settings=team_settings, all_rules=PITCHING_RULES)


@admin_bp.route('/settings/backup_season_data', methods=['GET'])
@admin_required
def backup_season_data():
    team_id = session.get('team_id')
    team = db.session.get(Team, team_id)
    if not team:
        return "Team not found", 404

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Helper to convert model to dict and write to CSV
        def add_model_to_zip(model_class, filename):
            # Special case for PracticeTask since it doesn't have a team_id column
            if model_class == PracticeTask:
                practice_plan_ids = [p.id for p in db.session.query(PracticePlan.id).filter_by(team_id=team_id).all()]
                if not practice_plan_ids:
                    return
                records = db.session.query(PracticeTask).filter(PracticeTask.practice_plan_id.in_(practice_plan_ids)).all()
            else:
                records = db.session.query(model_class).filter_by(team_id=team_id).all()

            if not records:
                return

            # Use the first record to get column names, fallback to model columns
            if hasattr(records[0], 'to_dict'):
                fieldnames = records[0].to_dict().keys()
                rows = [r.to_dict() for r in records]
            else:
                fieldnames = [c.name for c in model_class.__table__.columns if c.name != 'team_id']
                rows = [{c.name: getattr(r, c.name) for c in model_class.__table__.columns if c.name != 'team_id'} for r in records]

            # Convert dicts with nested structures (like JSON) to strings for CSV
            for row in rows:
                for k, v in row.items():
                    if isinstance(v, (dict, list)):
                        row[k] = json.dumps(v)

            string_io = io.StringIO()
            writer = csv.DictWriter(string_io, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            zf.writestr(filename, string_io.getvalue())

        # Add all relevant data to the ZIP
        add_model_to_zip(Player, 'Roster.csv')
        add_model_to_zip(Game, 'Games.csv')
        add_model_to_zip(Lineup, 'Lineups.csv')
        add_model_to_zip(Rotation, 'Rotations.csv')
        add_model_to_zip(PitchingOuting, 'PitchingOutings.csv')
        add_model_to_zip(PracticePlan, 'PracticePlans.csv')
        add_model_to_zip(PracticeTask, 'PracticeTasks.csv')
        add_model_to_zip(ScoutedPlayer, 'ScoutedPlayers.csv')
        add_model_to_zip(CollaborationNote, 'CollaborationNotes.csv')
        add_model_to_zip(PlayerDevelopmentFocus, 'PlayerDevelopment.csv')
        add_model_to_zip(Sign, 'Signs.csv')

    memory_file.seek(0)

    # Format filename safely
    safe_team_name = "".join([c for c in team.team_name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
    zip_filename = f"{safe_team_name.replace(' ', '_')}_Season_Backup.zip"

    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_filename
    )

@admin_bp.route('/settings/start_new_season', methods=['POST'])
@admin_required
def start_new_season():
    team_id = session.get('team_id')
    team = db.session.get(Team, team_id)
    if not team:
        flash('Team not found.', 'danger')
        return redirect(url_for('admin.admin_settings'))

    # Update Team Settings
    new_team_name = request.form.get('new_team_name')
    new_age_group = request.form.get('new_age_group')
    if new_team_name:
        team.team_name = new_team_name
    if new_age_group:
        team.age_group = new_age_group

    # Get checkboxes
    keep_players = request.form.get('keep_players') == 'on'
    keep_dev_notes = request.form.get('keep_dev_notes') == 'on'
    keep_scouted_players = request.form.get('keep_scouted_players') == 'on'
    keep_collab_notes = request.form.get('keep_collab_notes') == 'on'
    keep_signs = request.form.get('keep_signs') == 'on'

    try:
        # 1. DELETE CHILD RECORDS FIRST (to satisfy Foreign Key constraints)

        # PitchingOuting, Lineup, Rotation, Absences
        db.session.query(PitchingOuting).filter_by(team_id=team_id).delete()
        db.session.query(Lineup).filter_by(team_id=team_id).delete()
        db.session.query(Rotation).filter_by(team_id=team_id).delete()
        db.session.query(PlayerGameAbsence).filter_by(team_id=team_id).delete()
        db.session.query(PlayerPracticeAbsence).filter_by(team_id=team_id).delete()

        # Manually clear tasks linked to the plans we are deleting (no team_id on PracticeTask)
        practice_plan_ids = [p.id for p in db.session.query(PracticePlan.id).filter_by(team_id=team_id).all()]
        if practice_plan_ids:
            db.session.query(PracticeTask).filter(PracticeTask.practice_plan_id.in_(practice_plan_ids)).delete(synchronize_session=False)

        # 2. DELETE PARENT RECORDS
        db.session.query(Game).filter_by(team_id=team_id).delete()
        db.session.query(PracticePlan).filter_by(team_id=team_id).delete()

        # 3. CONDITIONALLY DELETE (based on user choice)
        if not keep_players:
            # Delete players. This should cascade to dev notes, absences, pitching outings.
            db.session.query(Player).filter_by(team_id=team_id).delete()
        elif not keep_dev_notes:
            # Kept players, but want to wipe dev notes
            db.session.query(PlayerDevelopmentFocus).filter_by(team_id=team_id).delete()

        if not keep_scouted_players:
            db.session.query(ScoutedPlayer).filter_by(team_id=team_id).delete()

        if not keep_collab_notes:
            db.session.query(CollaborationNote).filter_by(team_id=team_id).delete()

        if not keep_signs:
            db.session.query(Sign).filter_by(team_id=team_id).delete()

        db.session.commit()

        # Broadcast team settings update to clients
        socketio.emit('team_settings_updated', {'team_id': team_id}, namespace='/')

        flash(f'Successfully started new season for {team.team_name}!', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred while resetting the season: {str(e)}', 'danger')

    return redirect(url_for('admin.admin_settings'))


@admin_bp.route('/settings/update', methods=['POST'])
@admin_required
def update_admin_settings():
    team_settings = db.session.get(Team, session['team_id'])
    if not team_settings:
        flash('Team settings not found.', 'danger')
        return redirect(url_for('.admin_settings'))

    team_settings.team_name = request.form.get('team_name', team_settings.team_name)
    team_settings.display_coach_names = 'display_coach_names' in request.form
    team_settings.age_group = request.form.get('age_group', team_settings.age_group)
    team_settings.pitching_rule_set = request.form.get('pitching_rule_set', team_settings.pitching_rule_set)
    team_settings.outfielder_count = int(request.form.get('outfielder_count', 3))
    
    # ADDED: Handle the new color inputs
    team_settings.primary_color = request.form.get('primary_color', team_settings.primary_color)
    team_settings.secondary_color = request.form.get('secondary_color', team_settings.secondary_color)
    
    db.session.commit()
    flash('Team settings updated successfully!', 'success')
    socketio.emit('data_updated', {'message': 'Team settings updated.'})
    return redirect(url_for('.admin_settings'))


@admin_bp.route('/upload_logo', methods=['POST'])
@admin_required
def upload_logo():
    team = db.session.get(Team, session['team_id'])
    if not team:
        flash('Your team could not be found.', 'danger')
        return redirect(url_for('.admin_settings'))
    
    if 'logo' not in request.files:
        flash('No file part in the request.', 'danger')
        return redirect(url_for('.admin_settings'))

    file = request.files['logo']
    if file.filename == '':
        flash('No selected file.', 'danger')
        return redirect(url_for('.admin_settings'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_id = uuid.uuid4().hex
        file_ext = filename.rsplit('.', 1)[1].lower()
        new_filename = f"{team.id}_{unique_id}.{file_ext}"

        upload_folder = os.path.join('static', 'uploads', 'logos')
        os.makedirs(upload_folder, exist_ok=True)
        
        if team.logo_path:
            old_logo_path = os.path.join(upload_folder, team.logo_path)
            if os.path.exists(old_logo_path):
                os.remove(old_logo_path)
        
        file_path = os.path.join(upload_folder, new_filename)
        file.save(file_path)
        team.logo_path = new_filename
        db.session.commit()

        flash('Team logo uploaded successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Team logo updated.'})
    else:
        flash('Invalid file type. Allowed types are: png, jpg, jpeg, gif, svg.', 'danger')

    return redirect(url_for('.admin_settings'))

@admin_bp.route('/create_team', methods=['POST'])
@super_admin_required
def create_team():
    team_name = request.form.get('team_name')
    if not team_name:
        flash('Team Name is required.', 'danger')
        return redirect(url_for('.team_management'))

    if db.session.query(Team).filter(func.lower(Team.team_name) == func.lower(team_name)).first():
        flash(f'A team with the name "{team_name}" already exists.', 'danger')
        return redirect(url_for('.team_management'))

    new_team = Team(team_name=team_name, registration_code=str(uuid.uuid4()).split('-')[-1])
    db.session.add(new_team)
    db.session.commit()

    flash(f'Team "{new_team.team_name}" created successfully!', 'success')
    return redirect(url_for('.team_management'))

@admin_bp.route('/delete_team/<int:team_id>')
@super_admin_required
def delete_team(team_id):
    team_to_delete = db.session.get(Team, team_id)
    if not team_to_delete:
        flash('Team not found.', 'danger')
        return redirect(url_for('.team_management'))

    if team_to_delete.id == session.get('team_id'):
        flash('You cannot delete your own active team.', 'danger')
        return redirect(url_for('.team_management'))

    user_count = db.session.query(User).filter_by(team_id=team_id).count()
    if user_count > 0:
        flash(f'Cannot delete team "{team_to_delete.team_name}" because it has {user_count} user(s).', 'danger')
        return redirect(url_for('.team_management'))

    flash(f'Successfully deleted team "{team_to_delete.team_name}".', 'success')
    db.session.delete(team_to_delete)
    db.session.commit()
    socketio.emit('data_updated', {'message': f'Team {team_to_delete.team_name} deleted.'})
    return redirect(url_for('.team_management'))
