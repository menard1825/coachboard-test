from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
import uuid
import os
import random
import string
import json
from functools import wraps

from db import SessionLocal
from models import User, Team
from app import socketio # CORRECTED: Only import socketio, not app

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

# --- USER & TEAM MANAGEMENT ROUTES ---

@admin_bp.route('/users')
@admin_required
def user_management():
    db = SessionLocal()
    try:
        teams = []
        if session.get('role') == SUPER_ADMIN:
            users = db.query(User).options(joinedload(User.team)).all()
            teams = db.query(Team).options(joinedload(Team.users)).order_by(Team.team_name).all()
        else:
            users = db.query(User).filter_by(team_id=session['team_id']).options(joinedload(User.team)).all()

        return render_template('user_management.html', users=users, teams=teams, session=session)
    finally:
        db.close()


@admin_bp.route('/add_user', methods=['POST'])
@admin_required
def add_user():
    db = SessionLocal()
    try:
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
        if db.query(User).filter(func.lower(User.username) == func.lower(username)).first():
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
            last_login='Never',
            team_id=team_id_for_new_user
        )
        db.add(new_user)
        db.commit()
        
        team_name = db.query(Team).filter_by(id=team_id_for_new_user).first().team_name
        flash(f"User '{username}' created successfully for team '{team_name}'.", 'success')
        socketio.emit('data_updated', {'message': 'A new user was added.'})
        return redirect(url_for('.user_management'))
    finally:
        db.close()

@admin_bp.route('/delete_user/<username>')
@admin_required
def delete_user(username):
    db = SessionLocal()
    try:
        if username.lower() == 'mike1825':
            flash("The Super Admin cannot be deleted.", "danger")
            return redirect(url_for('.user_management'))
        user_to_delete = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if user_to_delete:
            if session.get('role') == HEAD_COACH and user_to_delete.team_id != session.get('team_id'):
                flash('You do not have permission to delete this user.', 'danger')
                return redirect(url_for('.user_management'))
            db.delete(user_to_delete)
            db.commit()
            flash(f"User '{username}' has been deleted.", "success")
            socketio.emit('data_updated', {'message': f"User {username} deleted."})
        else:
            flash("User not found.", "danger")
        return redirect(url_for('.user_management'))
    finally:
        db.close()


@admin_bp.route('/reset_password/<username>', methods=['POST'])
@admin_required
def reset_password(username):
    db = SessionLocal()
    try:
        if username.lower() == 'mike1825':
            flash("The Super Admin's password cannot be reset via this interface.", "danger")
            return redirect(url_for('.user_management'))
        user_to_reset = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if not user_to_reset:
            flash('User not found.', 'danger')
            return redirect(url_for('.user_management'))
        if session.get('role') == HEAD_COACH and user_to_reset.team_id != session.get('team_id'):
            flash('You do not have permission to reset this password.', 'danger')
            return redirect(url_for('.user_management'))
        temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        user_to_reset.password_hash = generate_password_hash(temp_password)
        db.commit()
        flash(f"Password for {username} has been reset. The temporary password is: {temp_password}", 'success')
        socketio.emit('data_updated', {'message': f"Password for {username} reset."})
        return redirect(url_for('.user_management'))
    finally:
        db.close()


@admin_bp.route('/change_role/<username>', methods=['POST'])
@admin_required
def change_user_role(username):
    db = SessionLocal()
    try:
        user_to_change = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if not user_to_change:
            flash('User not found.', 'danger')
            return redirect(url_for('.user_management'))
        if session.get('role') == HEAD_COACH and user_to_change.team_id != session.get('team_id'):
            flash('You do not have permission to edit this user.', 'danger')
            return redirect(url_for('.user_management'))
        if user_to_change.username.lower() == 'mike1825':
            flash('You cannot change the role of the Super Admin.', 'danger')
            return redirect(url_for('.user_management'))
        new_role = request.form.get('role')
        if new_role == SUPER_ADMIN and session.get('role') != SUPER_ADMIN:
            flash('Only a Super Admin can assign the Super Admin role.', 'danger')
            return redirect(url_for('.user_management'))
        if user_to_change.username == session['username'] and new_role != SUPER_ADMIN and db.query(User).filter_by(role=SUPER_ADMIN).count() == 1:
            flash('You cannot demote yourself as the sole Super Admin. Assign another Super Admin first.', 'danger')
            return redirect(url_for('.user_management'))
        if new_role in [HEAD_COACH, 'Assistant Coach', 'Game Changer', SUPER_ADMIN]:
            user_to_change.role = new_role
            db.commit()
            flash(f"Successfully changed {username}'s role to {new_role}.", 'success')
            socketio.emit('data_updated', {'message': f"User {username}'s role changed."})
        else:
            flash('Invalid role selected.', 'danger')
        return redirect(url_for('.user_management'))
    finally:
        db.close()


@admin_bp.route('/update_user_details/<username>', methods=['POST'])
@admin_required
def update_user_details(username):
    db = SessionLocal()
    try:
        user_to_update = db.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if not user_to_update:
            flash('User not found.', 'danger')
            return redirect(url_for('.user_management'))
        if session.get('role') == HEAD_COACH and user_to_update.team_id != session.get('team_id'):
            flash('You do not have permission to edit this user.', 'danger')
            return redirect(url_for('.user_management'))
        user_to_update.full_name = request.form.get('full_name')
        db.commit()
        if session.get('username') == user_to_update.username:
            session['full_name'] = user_to_update.full_name
        flash(f"Successfully updated details for {user_to_update.username}.", 'success')
        socketio.emit('data_updated', {'message': f"User {user_to_update.username}'s details updated."})
        return redirect(url_for('.user_management'))
    finally:
        db.close()


# --- TEAM SETTINGS ROUTES ---

@admin_bp.route('/settings', methods=['GET'])
@admin_required
def admin_settings():
    db = SessionLocal()
    try:
        team_settings = db.query(Team).filter_by(id=session['team_id']).first()
        from app import PITCHING_RULES # Local import to avoid circular dependency
        return render_template('admin_settings.html', session=session, settings=team_settings, all_rules=PITCHING_RULES)
    finally:
        db.close()


@admin_bp.route('/settings/update', methods=['POST'])
@admin_required
def update_admin_settings():
    db = SessionLocal()
    try:
        team_settings = db.query(Team).filter_by(id=session['team_id']).first()
        if not team_settings:
            flash('Team settings not found.', 'danger')
            return redirect(url_for('.admin_settings'))

        team_settings.team_name = request.form.get('team_name', team_settings.team_name)
        team_settings.display_coach_names = 'display_coach_names' in request.form
        team_settings.age_group = request.form.get('age_group', team_settings.age_group)
        team_settings.pitching_rule_set = request.form.get('pitching_rule_set', team_settings.pitching_rule_set)
        
        db.commit()
        flash('Team settings updated successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Team settings updated.'})
        return redirect(url_for('.admin_settings'))
    finally:
        db.close()


@admin_bp.route('/upload_logo', methods=['POST'])
@admin_required
def upload_logo():
    db = SessionLocal()
    try:
        team = db.query(Team).filter_by(id=session['team_id']).first()
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

        # Assuming `allowed_file` is defined in the main app file
        from app import allowed_file
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            unique_id = uuid.uuid4().hex
            file_ext = filename.rsplit('.', 1)[1].lower()
            new_filename = f"{team.id}_{unique_id}.{file_ext}"

            # Assuming app.config is accessible or path is defined elsewhere
            upload_folder = os.path.join('static', 'uploads', 'logos')
            os.makedirs(upload_folder, exist_ok=True)
            
            if team.logo_path:
                old_logo_path = os.path.join(upload_folder, team.logo_path)
                if os.path.exists(old_logo_path):
                    os.remove(old_logo_path)
            
            file_path = os.path.join(upload_folder, new_filename)
            file.save(file_path)
            team.logo_path = new_filename
            db.commit()

            flash('Team logo uploaded successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Team logo updated.'})
        else:
            flash('Invalid file type. Allowed types are: png, jpg, jpeg, gif, svg.', 'danger')

        return redirect(url_for('.admin_settings'))
    finally:
        db.close()

@admin_bp.route('/create_team', methods=['POST'])
@admin_required
def create_team():
    if session.get('role') != SUPER_ADMIN:
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('.user_management'))

    db = SessionLocal()
    try:
        team_name = request.form.get('team_name')
        if not team_name:
            flash('Team Name is required.', 'danger')
            return redirect(url_for('.user_management'))

        if db.query(Team).filter(func.lower(Team.team_name) == func.lower(team_name)).first():
            flash(f'A team with the name "{team_name}" already exists.', 'danger')
            return redirect(url_for('.user_management'))

        new_team = Team(team_name=team_name, registration_code=str(uuid.uuid4()).split('-')[-1])
        db.add(new_team)
        db.commit()

        flash(f'Team "{new_team.team_name}" created successfully!', 'success')
        return redirect(url_for('.user_management'))
    finally:
        db.close()

@admin_bp.route('/delete_team/<int:team_id>')
@admin_required
def delete_team(team_id):
    if session.get('role') != SUPER_ADMIN:
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('.user_management'))

    db = SessionLocal()
    try:
        team_to_delete = db.query(Team).filter_by(id=team_id).first()
        if not team_to_delete:
            flash('Team not found.', 'danger')
            return redirect(url_for('.user_management'))

        if team_to_delete.id == session.get('team_id'):
            flash('You cannot delete your own active team.', 'danger')
            return redirect(url_for('.user_management'))

        user_count = db.query(User).filter_by(team_id=team_id).count()
        if user_count > 0:
            flash(f'Cannot delete team "{team_to_delete.team_name}" because it has {user_count} user(s).', 'danger')
            return redirect(url_for('.user_management'))

        flash(f'Successfully deleted team "{team_to_delete.team_name}".', 'success')
        db.delete(team_to_delete)
        db.commit()
        socketio.emit('data_updated', {'message': f'Team {team_to_delete.team_name} deleted.'})
        return redirect(url_for('.user_management'))
    finally:
        db.close()