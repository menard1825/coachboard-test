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

from db import db
from models import User, Team, TeamMembership, Player, Game, PitchingOuting, Lineup, Rotation, PracticePlan, CollaborationNote, Sign, ScoutedPlayer, PlayerDevelopmentFocus, PlayerGameAbsence, PlayerPracticeAbsence
from flask import g
from types import SimpleNamespace
from team_access import membership_for, team_members, error
from extensions import socketio, disconnect_team_member
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
    members = team_members(session['team_id'])
    users = [SimpleNamespace(username=m.user.username, full_name=m.user.full_name,
        role='Super Admin' if m.user.role == SUPER_ADMIN else m.role,
        team=m.team, last_login=m.user.last_login) for m in members]
    return render_template('user_management.html', users=users, teams=[g.current_team], session=session)


@admin_bp.route('/teams')
@super_admin_required
def team_management():
    teams = db.session.query(Team).order_by(Team.team_name).all()
    member_counts = {team.id: TeamMembership.query.filter_by(team_id=team.id).count() for team in teams}
    return render_template('team_management.html', teams=teams, member_counts=member_counts, session=session)


@admin_bp.route('/add_user', methods=['POST'])
@admin_required
def add_user():
    username = request.form.get('username')
    password = request.form.get('password')
    full_name = request.form.get('full_name')
    role = request.form.get('role', 'Assistant Coach')
    
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
        
    if role not in [SUPER_ADMIN, HEAD_COACH, 'Assistant Coach', 'Game Changer']:
        return error('Invalid role.', 400)
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
    db.session.flush()
    db.session.add(TeamMembership(user_id=new_user.id, team_id=team_id_for_new_user,
                                  role=HEAD_COACH if role == SUPER_ADMIN else role, player_order=[]))
    db.session.commit()
    
    team_name = db.session.get(Team, team_id_for_new_user).team_name
    flash(f"User '{username}' created successfully for team '{team_name}'.", 'success')
    socketio.emit('data_updated', {'message': 'A new user was added.'})
    return redirect(url_for('.user_management'))

@admin_bp.route('/delete_user/<username>', methods=['POST'])
@admin_required
def delete_user(username):
    user = User.query.filter(func.lower(User.username) == func.lower(username)).first()
    member = membership_for(user.id, session['team_id']) if user else None
    if not member or user.role == SUPER_ADMIN or user.id == g.current_user.id:
        return error('You cannot remove this account from the current team.', 403)
    if member.role == HEAD_COACH and TeamMembership.query.filter_by(team_id=member.team_id, role=HEAD_COACH).count() <= 1:
        return error('Assign another head coach before removing the last one.', 400)
    removed_user_id = user.id
    db.session.delete(member)
    db.session.flush()
    remaining = TeamMembership.query.filter_by(user_id=user.id).first()
    if remaining:
        if user.team_id == session['team_id']:
            user.team_id = remaining.team_id
            user.role = remaining.role
    else:
        db.session.delete(user)
    db.session.commit()
    disconnect_team_member(removed_user_id, session['team_id'])
    flash(f'{username} removed from this team. Access to other teams is preserved.', 'success')
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

    if not membership_for(user_to_reset.id, session['team_id']):
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
    user = User.query.filter(func.lower(User.username) == func.lower(username)).first()
    member = membership_for(user.id, session['team_id']) if user else None
    if not member or (user.role == SUPER_ADMIN and session['role'] != SUPER_ADMIN):
        return error('You cannot edit this account.', 403)
    role = request.form.get('role')
    if role not in [HEAD_COACH, 'Assistant Coach', 'Game Changer', SUPER_ADMIN]:
        return error('Invalid role.', 400)
    if role == SUPER_ADMIN and session['role'] != SUPER_ADMIN:
        return error('Only a Super Admin can assign that role.', 403)
    if user.role == SUPER_ADMIN and role != SUPER_ADMIN and User.query.filter_by(role=SUPER_ADMIN).count() <= 1:
        return error('You cannot demote the last Super Admin.', 400)
    if member.role == HEAD_COACH and role not in [HEAD_COACH, SUPER_ADMIN] and TeamMembership.query.filter_by(team_id=member.team_id, role=HEAD_COACH).count() <= 1:
        return error('Assign another head coach first.', 400)
    user.full_name = request.form.get('full_name', user.full_name)
    member.role = HEAD_COACH if role == SUPER_ADMIN else role
    if user.role == SUPER_ADMIN and role != SUPER_ADMIN:
        # Older membership rows may contain the legacy global role.
        for other in TeamMembership.query.filter_by(user_id=user.id, role=SUPER_ADMIN):
            other.role = HEAD_COACH
        user.role = role
    elif role == SUPER_ADMIN or user.team_id == member.team_id:
        user.role = role
    db.session.commit()
    if user.id == g.current_user.id:
        session['full_name'] = user.full_name
    flash('Coach details updated for this team.', 'success')
    return redirect(url_for('.user_management'))


# --- TEAM SETTINGS ROUTES ---
@admin_bp.route('/settings', methods=['GET'])
@admin_required
def admin_settings():
    team_settings = db.session.get(Team, session['team_id'])
    return render_template('admin_settings.html', session=session, settings=team_settings, all_rules=PITCHING_RULES)


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
    db.session.flush()
    db.session.add(TeamMembership(user_id=g.current_user.id, team_id=new_team.id, role=HEAD_COACH, player_order=[]))
    db.session.commit()

    flash(f'Team "{new_team.team_name}" created successfully!', 'success')
    return redirect(url_for('.team_management'))

@admin_bp.route('/delete_team/<int:team_id>', methods=['POST'])
@super_admin_required
def delete_team(team_id):
    team_to_delete = db.session.get(Team, team_id)
    if not team_to_delete:
        flash('Team not found.', 'danger')
        return redirect(url_for('.team_management'))

    if team_to_delete.id == session.get('team_id'):
        flash('You cannot delete your own active team.', 'danger')
        return redirect(url_for('.team_management'))

    user_count = TeamMembership.query.filter_by(team_id=team_id).count()
    if user_count > 0:
        flash(f'Cannot delete team "{team_to_delete.team_name}" because it has {user_count} user(s).', 'danger')
        return redirect(url_for('.team_management'))

    if any(model.query.filter_by(team_id=team_id).first() is not None for model in
           (Player, Game, PitchingOuting, Lineup, Rotation, PracticePlan, CollaborationNote, Sign, ScoutedPlayer, PlayerDevelopmentFocus, PlayerGameAbsence, PlayerPracticeAbsence)):
        return error('This team has historical records. Archive it instead of deleting it.', 400)

    flash(f'Successfully deleted team "{team_to_delete.team_name}".', 'success')
    db.session.delete(team_to_delete)
    db.session.commit()
    socketio.emit('data_updated', {'message': f'Team {team_to_delete.team_name} deleted.'})
    return redirect(url_for('.team_management'))
