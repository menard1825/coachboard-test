import json

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_
from werkzeug.security import check_password_hash, generate_password_hash

from blueprints.security_guard import record_activity
from db import db
from models import Team, TeamMembership, User, utcnow_naive
from password_recovery import (
    email_delivery_configured,
    normalize_email,
    password_reset_max_age,
    password_reset_url,
    resolve_password_reset_token,
    send_password_reset_email,
    valid_email,
)
from permissions import ASSISTANT_COACH, GAME_CHANGER, HEAD_COACH, SUPER_ADMIN

MIN_PASSWORD_LENGTH = 8

auth_bp = Blueprint('auth', __name__, template_folder='templates')


def get_player_order_as_list(player_order_data):
    if not player_order_data:
        return []
    if isinstance(player_order_data, list):
        return player_order_data
    if isinstance(player_order_data, str):
        try:
            return json.loads(player_order_data)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _find_user_by_identity(identity):
    identity = str(identity or '').strip()
    if not identity:
        return None
    lowered = identity.lower()
    return db.session.query(User).filter(or_(
        func.lower(User.username) == lowered,
        func.lower(User.email) == lowered,
    )).first()


def _email_available(email, exclude_user_id=None):
    query = db.session.query(User).filter(func.lower(User.email) == email.lower())
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.first() is None


def _admin_can_help_user(user):
    if not user or not session.get('logged_in'):
        return False
    if session.get('role') == SUPER_ADMIN:
        return True
    if session.get('role') != HEAD_COACH or not session.get('team_id'):
        return False
    return db.session.query(TeamMembership).filter_by(
        user_id=user.id,
        team_id=session['team_id'],
    ).first() is not None


def _password_help_page(user):
    return render_template(
        'password_help.html',
        user=user,
        reset_url=password_reset_url(user),
        expires_minutes=max(1, password_reset_max_age() // 60),
        email_delivery_enabled=email_delivery_configured(),
    )


def _latest_membership(user):
    if not user:
        return None
    return db.session.query(TeamMembership).filter_by(user_id=user.id).order_by(TeamMembership.id.desc()).first()


def _signed_in_destination(role):
    return url_for('game_day.game_day_home') if role == GAME_CHANGER else url_for('home')


@auth_bp.before_app_request
def replace_legacy_admin_password_reset():
    """Turn the old random-password admin action into secure password help."""
    if request.method != 'POST' or request.endpoint != 'admin.reset_password':
        return None
    username = (request.view_args or {}).get('username')
    user = _find_user_by_identity(username)
    if not _admin_can_help_user(user):
        flash('You do not have permission to help with that account.', 'danger')
        return redirect(url_for('admin.user_management'))
    return _password_help_page(user)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(_signed_in_destination(session.get('role')))

    if request.method == 'POST':
        identity = request.form.get('identity') or request.form.get('username')
        password = request.form.get('password') or ''
        user = _find_user_by_identity(identity)

        if user and check_password_hash(user.password_hash, password):
            primary_membership = _latest_membership(user)
            if not primary_membership:
                flash('Your CoachBoard account is not assigned to a team yet. Ask your Head Coach for access.', 'danger')
                return render_template('login.html', identity=identity)

            # Store login timestamps consistently in UTC.  The audit/user UI
            # converts them to the active team's timezone for display.
            user.last_login = utcnow_naive()
            db.session.commit()

            session['logged_in'] = True
            session['username'] = user.username
            session['full_name'] = user.full_name or ''
            session['role'] = primary_membership.role
            session['team_id'] = primary_membership.team_id
            session['player_order'] = get_player_order_as_list(primary_membership.player_order)
            session.permanent = True

            team = db.session.get(Team, primary_membership.team_id)
            record_activity(
                'login',
                user=user,
                team_id=primary_membership.team_id,
                role=primary_membership.role,
                detail=f"Signed in to {team.team_name if team else 'team'}.",
            )
            return redirect(_signed_in_destination(primary_membership.role))

        flash('That username/email and password combination did not match.', 'danger')
        return render_template('login.html', identity=identity)

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    if session.get('logged_in'):
        user = _find_user_by_identity(session.get('username'))
        team = db.session.get(Team, session.get('team_id')) if session.get('team_id') else None
        record_activity(
            'logout',
            user=user,
            team_id=session.get('team_id'),
            role=session.get('role'),
            detail=f"Signed out of {team.team_name if team else 'CoachBoard'}.",
        )
    session.clear()
    flash('You were successfully logged out.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/switch_team/<int:team_id>')
def switch_team(team_id):
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    username = session.get('username')
    user = db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first()
    if not user:
        return redirect(url_for('auth.logout'))

    membership = db.session.query(TeamMembership).filter_by(user_id=user.id, team_id=team_id).first()
    if not membership:
        flash('You do not have access to that team.', 'danger')
        return redirect(url_for('home'))

    previous_team = db.session.get(Team, session.get('team_id')) if session.get('team_id') else None
    new_team = db.session.get(Team, membership.team_id)
    session['team_id'] = membership.team_id
    session['role'] = membership.role
    session['player_order'] = get_player_order_as_list(membership.player_order)
    record_activity(
        'team_switch',
        user=user,
        team_id=membership.team_id,
        role=membership.role,
        detail=f"Switched from {previous_team.team_name if previous_team else 'another team'} to {new_team.team_name if new_team else 'this team'}.",
    )
    flash('Switched team successfully.', 'success')
    return redirect(_signed_in_destination(membership.role))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = str(request.form.get('username') or '').strip()
        email = normalize_email(request.form.get('email'))
        full_name = str(request.form.get('full_name') or '').strip()
        password = request.form.get('password') or ''
        reg_code = str(request.form.get('registration_code') or '').strip()

        if not all([username, email, full_name, password, reg_code]):
            flash('Name, username, email, password, and team registration code are required.', 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form)
        if not valid_email(email):
            flash('Enter a valid email address. CoachBoard uses it if you ever forget your password.', 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form)
        if len(password) < MIN_PASSWORD_LENGTH:
            flash(f'Password must be at least {MIN_PASSWORD_LENGTH} characters long.', 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form)
        if db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first():
            flash('That username is already taken. Please choose another.', 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form)
        if not _email_available(email):
            flash('That email is already connected to a CoachBoard account. Try signing in or use Forgot Password.', 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form)

        team = db.session.query(Team).filter_by(registration_code=reg_code).first()
        if not team:
            flash('That team registration code was not recognized.', 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form)

        is_first_user = db.session.query(TeamMembership).filter_by(team_id=team.id).count() == 0
        user_role = HEAD_COACH if is_first_user else ASSISTANT_COACH
        default_tab_keys = ['roster', 'player_development', 'games', 'pitching', 'practice_plan', 'collaboration']

        new_user = User(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=generate_password_hash(password),
            tab_order=json.dumps(default_tab_keys),
            last_login=utcnow_naive(),
        )
        db.session.add(new_user)
        db.session.flush()
        new_membership = TeamMembership(
            user_id=new_user.id,
            team_id=team.id,
            role=user_role,
            player_order=[]
        )
        db.session.add(new_membership)
        db.session.commit()

        session['logged_in'] = True
        session['username'] = new_user.username
        session['full_name'] = new_user.full_name
        session['role'] = new_membership.role
        session['team_id'] = new_membership.team_id
        session['player_order'] = []
        session.permanent = True
        record_activity(
            'account_created',
            user=new_user,
            team_id=team.id,
            role=user_role,
            detail=f'Joined {team.team_name}.',
        )
        record_activity(
            'login',
            user=new_user,
            team_id=team.id,
            role=user_role,
            detail=f'Signed in to {team.team_name} after registration.',
        )
        flash(f'Welcome to CoachBoard. You joined {team.team_name}.', 'success')
        return redirect(_signed_in_destination(user_role))

    registration_code = request.args.get('code', '')
    return render_template('register.html', registration_code=registration_code, form={})


@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    submitted = False
    email_available = email_delivery_configured()

    if request.method == 'POST':
        submitted = True
        identity = str(request.form.get('identity') or '').strip()
        user = _find_user_by_identity(identity)
        if user and user.email and email_available:
            try:
                reset_url = password_reset_url(user)
                send_password_reset_email(user, reset_url)
            except Exception:
                current_app.logger.exception('Unable to send CoachBoard password reset email for user id %s', user.id)

    return render_template(
        'forgot_password.html',
        submitted=submitted,
        email_delivery_enabled=email_available,
    )


@auth_bp.route('/password_help/<username>', methods=['GET'])
def password_help(username):
    user = _find_user_by_identity(username)
    if not _admin_can_help_user(user):
        flash('You do not have permission to help with that account.', 'danger')
        return redirect(url_for('home'))
    return _password_help_page(user)


@auth_bp.route('/password_help/<username>/email', methods=['POST'])
def email_password_help(username):
    user = _find_user_by_identity(username)
    if not _admin_can_help_user(user):
        flash('You do not have permission to help with that account.', 'danger')
        return redirect(url_for('home'))
    if not user.email:
        flash('That coach does not have a recovery email on file. Copy the reset link instead.', 'warning')
        return _password_help_page(user)
    if not email_delivery_configured():
        flash('Email delivery is not configured yet. Copy the reset link and text it to the coach.', 'warning')
        return _password_help_page(user)
    try:
        send_password_reset_email(user, password_reset_url(user))
        flash(f'Password reset email sent to {user.email}.', 'success')
        return redirect(url_for('admin.user_management'))
    except Exception:
        current_app.logger.exception('Unable to send admin password reset email for user id %s', user.id)
        flash('CoachBoard could not send the email. Copy the reset link instead.', 'danger')
        return _password_help_page(user)


@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_token(token):
    user = resolve_password_reset_token(token)
    if not user:
        flash('That password reset link is invalid or has expired. Request a new link or ask your Head Coach for help.', 'warning')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        if len(new_password) < MIN_PASSWORD_LENGTH:
            flash(f'Choose a password with at least {MIN_PASSWORD_LENGTH} characters.', 'danger')
            return render_template('reset_password.html', token=token, user=user)
        if new_password != confirm_password:
            flash('The two passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token, user=user)

        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        membership = _latest_membership(user)
        record_activity(
            'password_reset',
            user=user,
            team_id=membership.team_id if membership else None,
            role=membership.role if membership else None,
            detail='Password changed with a recovery link.',
        )
        session.clear()
        flash('Your password has been changed. Sign in with your new password.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token, user=user)


@auth_bp.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    user = db.session.query(User).filter(func.lower(User.username) == func.lower(session.get('username'))).first()
    if not user:
        return redirect(url_for('auth.logout'))

    if request.method == 'POST':
        action = request.form.get('action') or 'password'
        if action == 'email':
            email = normalize_email(request.form.get('email'))
            if not valid_email(email):
                flash('Enter a valid recovery email address.', 'danger')
                return redirect(url_for('auth.change_password'))
            if not _email_available(email, exclude_user_id=user.id):
                flash('That email is already connected to another CoachBoard account.', 'danger')
                return redirect(url_for('auth.change_password'))
            user.email = email
            db.session.commit()
            record_activity('recovery_email_changed', user=user, detail='Recovery email updated.')
            flash('Your recovery email has been saved.', 'success')
            return redirect(url_for('auth.change_password'))

        current_password = request.form.get('current_password') or ''
        new_password = request.form.get('new_password') or ''
        confirm_new_password = request.form.get('confirm_new_password') or ''
        if not check_password_hash(user.password_hash, current_password):
            flash('Your current password was incorrect.', 'danger')
            return redirect(url_for('auth.change_password'))
        if new_password != confirm_new_password:
            flash('New passwords do not match.', 'danger')
            return redirect(url_for('auth.change_password'))
        if len(new_password) < MIN_PASSWORD_LENGTH:
            flash(f'New password must be at least {MIN_PASSWORD_LENGTH} characters long.', 'danger')
            return redirect(url_for('auth.change_password'))

        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        record_activity('password_changed', user=user, detail='Password changed while signed in.')
        flash('Your password has been updated successfully.', 'success')
        return redirect(_signed_in_destination(session.get('role')))

    return render_template('change_password.html', user=user)
