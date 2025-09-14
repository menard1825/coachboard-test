from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import User, Team
from db import db
from sqlalchemy import func
from datetime import datetime
import json
import uuid

from utils import get_player_order_as_list

# Define role constants for clarity
HEAD_COACH = 'Head Coach'
ASSISTANT_COACH = 'Assistant Coach'
SUPER_ADMIN = 'Super Admin'

auth_bp = Blueprint('auth', __name__, template_folder='templates')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first()

        if user and check_password_hash(user.password_hash, password):
            user.last_login = datetime.utcnow()
            db.session.commit()

            session['logged_in'] = True
            session['username'] = user.username
            session['full_name'] = user.full_name or ''
            session['role'] = user.role
            session['team_id'] = user.team_id
            session['player_order'] = get_player_order_as_list(user.player_order)
            if request.form.get('remember'):
                session.permanent = True
            else:
                session.permanent = False
            flash('You were successfully logged in.', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You were successfully logged out.', 'success')
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        full_name = request.form.get('full_name')
        password = request.form.get('password')
        email = request.form.get('email')
        reg_code = request.form.get('registration_code')

        if not all([username, full_name, password, reg_code]):
            flash('A registration code is required to join a team.', 'danger')
            return redirect(url_for('auth.register'))
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return redirect(url_for('auth.register'))
        if db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first():
            flash('Registration failed. Please check your information and try again.', 'danger')
            return redirect(url_for('auth.register'))
        
        team = db.session.query(Team).filter_by(registration_code=reg_code).first()
        if not team:
            flash('Invalid Registration Code.', 'danger')
            return redirect(url_for('auth.register'))

        is_first_user = db.session.query(User).filter_by(team_id=team.id).count() == 0
        user_role = HEAD_COACH if is_first_user else ASSISTANT_COACH

        hashed_password = generate_password_hash(password)
        default_tab_keys = ['roster', 'player_development', 'games', 'pitching', 'practice_plan', 'collaboration']
        new_user = User(
            username=username,
            full_name=full_name,
            password_hash=hashed_password,
            email=email.lower() if email else None,
            role=user_role,
            team_id=team.id,
            tab_order=json.dumps(default_tab_keys),
            player_order=[]
        )
        db.session.add(new_user)
        db.session.commit()
        session['logged_in'] = True
        session['username'] = new_user.username
        session['full_name'] = new_user.full_name
        session['role'] = new_user.role
        session['team_id'] = new_user.team_id
        session['player_order'] = []
        session.permanent = True

        flash(f'Registration successful! You have joined team "{team.team_name}". Welcome.', 'success')
        return redirect(url_for('home'))

    registration_code = request.args.get('code', '')
    return render_template('register.html', registration_code=registration_code)

@auth_bp.route('/register-team', methods=['GET', 'POST'])
def register_team():
    if request.method == 'POST':
        # Form fields from register_team.html
        username = request.form.get('username')
        full_name = request.form.get('full_name')
        password = request.form.get('password')
        email = request.form.get('email')
        team_name = request.form.get('team_name')

        # --- Validation ---
        if not all([username, full_name, password, email, team_name]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('auth.register_team'))
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return redirect(url_for('auth.register_team'))
        if db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first():
            flash('Registration failed. Please check your information and try again.', 'danger')
            return redirect(url_for('auth.register_team'))
        if db.session.query(Team).filter(func.lower(Team.team_name) == func.lower(team_name)).first():
            flash('A team with that name already exists. Please choose another.', 'danger')
            return redirect(url_for('auth.register_team'))

        # --- Transactional Creation ---
        try:
            # 1. Create Team
            new_team = Team(
                team_name=team_name,
                registration_code=str(uuid.uuid4()).split('-')[-1] # Generate a unique code
            )
            db.session.add(new_team)
            db.session.flush()  # Flush to get the new_team.id

            # 2. Create User (as Head Coach of the new team)
            hashed_password = generate_password_hash(password)
            default_tab_keys = ['roster', 'player_development', 'games', 'pitching', 'practice_plan', 'collaboration']
            new_user = User(
                username=username,
                full_name=full_name,
                password_hash=hashed_password,
                email=email.lower() if email else None,
                role=HEAD_COACH, # First user of a new team is always the Head Coach
                team_id=new_team.id,
                tab_order=json.dumps(default_tab_keys),
                player_order=[]
            )
            db.session.add(new_user)
            db.session.commit()

            # 3. Log the new user in
            session['logged_in'] = True
            session['username'] = new_user.username
            session['full_name'] = new_user.full_name
            session['role'] = new_user.role
            session['team_id'] = new_user.team_id
            session['player_order'] = []
            session.permanent = True

            flash('Account and team created successfully! Welcome to CoachBoard.', 'success')
            return redirect(url_for('home'))

        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'danger')
            print(f"Error in /register-team: {e}") # for debugging
            return redirect(url_for('auth.register_team'))

    # GET request
    return render_template('register_team.html')


@auth_bp.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_new_password = request.form.get('confirm_new_password')

        user = db.session.query(User).filter_by(username=session['username']).first()

        if not user or not check_password_hash(user.password_hash, current_password):
            flash('Your current password was incorrect.', 'danger')
            return redirect(url_for('auth.change_password'))
        if new_password != confirm_new_password:
            flash('New passwords do not match.', 'danger')
            return redirect(url_for('auth.change_password'))
        if len(new_password) < 8:
            flash('New password must be at least 8 characters long.', 'danger')
            return redirect(url_for('auth.change_password'))

        user.last_password_change_at = datetime.utcnow()
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()

        flash('Your password has been updated successfully!', 'success')
        return redirect(url_for('home'))
    return render_template('change_password.html')
