from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from models import User, Team
from db import db
from sqlalchemy import func
from datetime import datetime
import json

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
            if user.username.lower() == 'mike1825':
                user.role = SUPER_ADMIN
            elif user.role == 'Admin':
                user.role = HEAD_COACH
            elif user.role == 'Coach':
                user.role = ASSISTANT_COACH

            user.last_login = datetime.now().strftime("%Y-%m-%d %H:%M")
            db.session.commit()

            session['logged_in'] = True
            session['username'] = user.username
            session['full_name'] = user.full_name or ''
            session['role'] = user.role
            session['team_id'] = user.team_id
            session['player_order'] = json.loads(user.player_order or "[]")
            session.permanent = True
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
        reg_code = request.form.get('registration_code')

        if not all([username, full_name, password, reg_code]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('auth.register'))
        if len(password) < 4:
            flash('Password must be at least 4 characters long.', 'danger')
            return redirect(url_for('auth.register'))
        if db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first():
            flash('That username is already taken. Please choose another.', 'danger')
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
            role=user_role,
            team_id=team.id,
            tab_order=json.dumps(default_tab_keys),
            player_order=json.dumps([])
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
        if len(new_password) < 4:
            flash('New password must be at least 4 characters long.', 'danger')
            return redirect(url_for('auth.change_password'))

        user.password_hash = generate_password_hash(new_password)
        db.session.commit()

        flash('Your password has been updated successfully!', 'success')
        return redirect(url_for('home'))
    return render_template('change_password.html')