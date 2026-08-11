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
from models import User, Team
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
    from models import TeamMembership
    if session.get('role') == SUPER_ADMIN:
        users = db.session.query(User).join(TeamMembership).options(joinedload(User.memberships)).all()
        teams = db.session.query(Team).order_by(Team.team_name).all()
    else:
        users = db.session.query(User).join(TeamMembership).filter(TeamMembership.team_id==session['team_id']).options(joinedload(User.memberships)).all()

    return render_template('user_management.html', users=users, teams=teams, session=session)


@admin_bp.route('/teams')
@super_admin_required
def team_management():
    teams = db.session.query(Team).options(joinedload(Team.memberships)).order_by(Team.team_name).all()

    # Get current team's players for the rollover modal
    current_team_players = []
    if session.get('team_id'):
        from models import Player
        current_team_players = db.session.query(Player).filter_by(team_id=session['team_id']).order_by(Player.name).all()

    return render_template('team_management.html', teams=teams, current_team_players=current_team_players, session=session)


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

    from models import TeamMembership
    existing_user = db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first()

    if existing_user:
        # Check if they already have a membership to this team
        existing_membership = db.session.query(TeamMembership).filter_by(user_id=existing_user.id, team_id=team_id_for_new_user).first()
        if existing_membership:
            flash('User is already assigned to this team.', 'danger')
            return redirect(url_for('.user_management'))

        # Create a new membership for the existing user
        new_membership = TeamMembership(
            user_id=existing_user.id,
            team_id=team_id_for_new_user,
            role=role,
            player_order=[]
        )
        db.session.add(new_membership)
        db.session.commit()
        team_name = db.session.get(Team, team_id_for_new_user).team_name
        flash(f'Existing user {username} successfully granted access to team {team_name}.', 'success')
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
        tab_order=json.dumps(default_tab_keys),
        last_login=None
    )
    db.session.add(new_user)
    db.session.flush() # Flush to get new user ID

    new_membership = TeamMembership(
        user_id=new_user.id,
        team_id=team_id_for_new_user,
        role=role,
        player_order=[]
    )
    db.session.add(new_membership)
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
        from models import TeamMembership
        membership = db.session.query(TeamMembership).filter_by(user_id=user_to_delete.id, team_id=session.get('team_id')).first()

        # Super admins can see all memberships if they switch teams, but let's restrict deletion to current team context
        if not membership and session.get('role') != SUPER_ADMIN:
            flash('You do not have permission to delete this user.', 'danger')
            return redirect(url_for('.user_management'))
            
        if membership and membership.role == SUPER_ADMIN:
             flash("A Super Admin's access cannot be removed.", "danger")
             return redirect(url_for('.user_management'))

        if membership:
            db.session.delete(membership)
            db.session.commit()

            # If they have no more memberships, delete the user entirely
            remaining_memberships = db.session.query(TeamMembership).filter_by(user_id=user_to_delete.id).count()
            if remaining_memberships == 0:
                db.session.delete(user_to_delete)
                db.session.commit()
                flash(f"User '{username}' has been completely removed from the system.", "success")
            else:
                flash(f"User '{username}' access to this team has been removed.", "success")

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

    from models import TeamMembership
    membership = db.session.query(TeamMembership).filter_by(user_id=user_to_reset.id, team_id=session.get('team_id')).first()
    
    if membership and membership.role == SUPER_ADMIN:
        flash("A Super Admin's password cannot be reset via this interface.", "danger")
        return redirect(url_for('.user_management'))

    if session.get('role') == HEAD_COACH and not membership:
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

    from models import TeamMembership
    membership = db.session.query(TeamMembership).filter_by(user_id=user_to_edit.id, team_id=session.get('team_id')).first()

    # Permission check: Head Coach can only edit users on their team
    if session.get('role') == HEAD_COACH and not membership:
        flash('You do not have permission to edit this user.', 'danger')
        return redirect(url_for('.user_management'))

    new_full_name = request.form.get('full_name')
    new_role = request.form.get('role')

    # Update Full Name
    user_to_edit.full_name = new_full_name
    if session.get('username') == user_to_edit.username:
        session['full_name'] = user_to_edit.full_name

    # Update Role
    if membership and new_role and new_role != membership.role:
        # Prevent self-demotion if the user is the sole Super Admin
        if membership.role == SUPER_ADMIN and user_to_edit.username == session['username']:
            if db.session.query(TeamMembership).filter_by(role=SUPER_ADMIN).count() == 1:
                flash('You cannot demote yourself as the sole Super Admin. Assign another Super Admin first.', 'danger')
                db.session.rollback() # Rollback name change
                return redirect(url_for('.user_management'))

        # Prevent non-Super Admins from assigning Super Admin role
        if new_role == SUPER_ADMIN and session.get('role') != SUPER_ADMIN:
            flash('Only a Super Admin can assign the Super Admin role.', 'danger')
            db.session.rollback() # Rollback name change
            return redirect(url_for('.user_management'))

        if new_role in [HEAD_COACH, 'Assistant Coach', 'Game Changer', SUPER_ADMIN]:
            membership.role = new_role
            # Update session role if they are editing themselves
            if session.get('username') == user_to_edit.username:
                session['role'] = new_role
        else:
            flash('Invalid role selected.', 'danger')
            db.session.rollback() # Rollback name change
            return redirect(url_for('.user_management'))

    db.session.commit()
    flash(f"User '{username}' has been updated.", "success")
    socketio.emit('data_updated', {'message': f"User {username} updated."})
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


@admin_bp.route('/rollover_season', methods=['POST'])
@admin_required
def rollover_season():
    from models import TeamMembership, Player, PlayerDevelopmentFocus, ScoutedPlayer, CollaborationNote, Sign

    current_team = db.session.get(Team, session['team_id'])
    if not current_team:
        flash('Current team not found.', 'danger')
        return redirect(url_for('.admin_settings'))

    new_team_name = request.form.get('new_team_name')
    new_age_group = request.form.get('new_age_group')

    if not new_team_name:
        flash('New Team Name is required.', 'danger')
        return redirect(url_for('.admin_settings'))

    if db.session.query(Team).filter(func.lower(Team.team_name) == func.lower(new_team_name)).first():
        flash(f'A team with the name "{new_team_name}" already exists.', 'danger')
        return redirect(url_for('.admin_settings'))

    try:
        # Create new team
        new_team = Team(
            team_name=new_team_name,
            registration_code=str(uuid.uuid4()).split('-')[-1],
            logo_path=current_team.logo_path, # Optional: carry over logo
            display_coach_names=current_team.display_coach_names,
            primary_color=current_team.primary_color,
            secondary_color=current_team.secondary_color,
            age_group=new_age_group or current_team.age_group,
            pitching_rule_set=current_team.pitching_rule_set,
            outfielder_count=current_team.outfielder_count
        )
        db.session.add(new_team)
        db.session.flush() # flush to get the new team id

        # 1. Give ALL current coaches access to the new team
        current_memberships = db.session.query(TeamMembership).filter_by(team_id=current_team.id).all()
        for membership in current_memberships:
            new_membership = TeamMembership(
                user_id=membership.user_id,
                team_id=new_team.id,
                role=membership.role,
                player_order=[] # Reset player order since IDs will change
            )
            db.session.add(new_membership)

        # 2. Copy Roster and Player Dev if requested
        player_id_map = {} # Maps old player ID to new player ID
        if request.form.get('copy_roster'):
            current_players = db.session.query(Player).filter_by(team_id=current_team.id).all()
            for p in current_players:
                new_player = Player(
                    name=p.name,
                    number=p.number,
                    position1=p.position1,
                    position2=p.position2,
                    position3=p.position3,
                    throws=p.throws,
                    bats=p.bats,
                    notes=p.notes,
                    pitcher_role=p.pitcher_role,
                    has_lessons=p.has_lessons,
                    lesson_focus=p.lesson_focus,
                    notes_author=p.notes_author,
                    notes_timestamp=p.notes_timestamp,
                    team_id=new_team.id
                )
                db.session.add(new_player)
                db.session.flush()
                player_id_map[p.id] = new_player.id

            # Copy player dev notes, mapped to the new player IDs
            if request.form.get('copy_dev_notes'):
                dev_notes = db.session.query(PlayerDevelopmentFocus).filter_by(team_id=current_team.id).all()
                for note in dev_notes:
                    if note.player_id in player_id_map: # Should always be true, but safe
                        new_note = PlayerDevelopmentFocus(
                            focus=note.focus,
                            status=note.status,
                            notes=note.notes,
                            progress_notes=note.progress_notes,
                            created_date=note.created_date,
                            completed_date=note.completed_date,
                            author=note.author,
                            last_edited_by=note.last_edited_by,
                            last_edited_date=note.last_edited_date,
                            player_id=player_id_map[note.player_id],
                            skill_type=note.skill_type,
                            team_id=new_team.id
                        )
                        db.session.add(new_note)

        # 3. Copy Scouted Players
        if request.form.get('copy_scouted'):
            scouted = db.session.query(ScoutedPlayer).filter_by(team_id=current_team.id).all()
            for s in scouted:
                new_s = ScoutedPlayer(
                    name=s.name, position1=s.position1, position2=s.position2,
                    throws=s.throws, bats=s.bats, list_type=s.list_type,
                    team_id=new_team.id
                )
                db.session.add(new_s)

        # 4. Copy Collaboration Notes
        if request.form.get('copy_collab'):
            notes = db.session.query(CollaborationNote).filter_by(team_id=current_team.id).all()
            for n in notes:
                new_n = CollaborationNote(
                    note_type=n.note_type, text=n.text, author=n.author,
                    timestamp=n.timestamp, player_name=n.player_name,
                    team_id=new_team.id
                )
                db.session.add(new_n)

        # 5. Copy Signs
        if request.form.get('copy_signs'):
            signs = db.session.query(Sign).filter_by(team_id=current_team.id).all()
            for s in signs:
                new_s = Sign(name=s.name, indicator=s.indicator, team_id=new_team.id)
                db.session.add(new_s)

        # Commit everything as a single transaction
        db.session.commit()

        # Switch the active coach into the new season
        session['team_id'] = new_team.id
        session['player_order'] = [] # Clear out session player order for new season

        flash(f'Successfully started new season! You are now managing "{new_team.team_name}". Your previous season was preserved.', 'success')
        socketio.emit('data_updated', {'message': f'New season {new_team.team_name} created.'})
        return redirect(url_for('home'))

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        flash(f'An error occurred while rolling over the season: {str(e)}', 'danger')
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

    from models import TeamMembership
    user_count = db.session.query(TeamMembership).filter_by(team_id=team_id).count()
    if user_count > 0:
        flash(f'Cannot delete team "{team_to_delete.team_name}" because it has {user_count} user(s) assigned.', 'danger')
        return redirect(url_for('.team_management'))

    flash(f'Successfully deleted team "{team_to_delete.team_name}".', 'success')
    db.session.delete(team_to_delete)
    db.session.commit()
    socketio.emit('data_updated', {'message': f'Team {team_to_delete.team_name} deleted.'})
    return redirect(url_for('.team_management'))
