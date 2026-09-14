import json

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_
from werkzeug.security import check_password_hash, generate_password_hash

from auth_rate_limit import RateLimitStorageError, clear_bucket, get_limit, release, reserve, resolve_client_ip
from blueprints.security_guard import normalize_timezone_name, normalize_utc_offset_minutes, record_activity
from db import db
from extensions import socketio
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

# Used to run a real (if pointless) PBKDF2 verification when the submitted
# identity doesn't resolve to a user, so login's response timing doesn't
# reveal whether an account exists. Computed once per process, not per
# request -- the value itself is never checked against anything.
_DUMMY_PASSWORD_HASH = generate_password_hash('coachboard-constant-time-dummy-password')

auth_bp = Blueprint('auth', __name__, template_folder='templates')

_TOO_MANY_ATTEMPTS_MESSAGE = 'Too many attempts. Please wait a bit and try again.'
_SERVICE_UNAVAILABLE_MESSAGE = 'CoachBoard is temporarily unavailable. Please try again in a moment.'


def _service_unavailable(template_name, **context):
    """A rate-limit storage failure (RateLimitStorageError) fails closed:
    no authentication, no account creation, no recovery email. This is
    deliberately a 503, never a 429 -- a 429 means the limiter is working
    and the caller is over a real limit; this means the limiter itself
    could not be consulted at all."""
    flash(_SERVICE_UNAVAILABLE_MESSAGE, 'danger')
    return render_template(template_name, **context), 503


def _best_effort_release(scope, subject, window_start):
    """Try to give back a reservation after a LATER step in the same
    request failed, so a caller that already decided to fail closed (503)
    doesn't also leave a stray provisional reservation behind. This is
    best-effort only: whether or not this succeeds, the caller still
    returns 503 -- a failure here must never be allowed to continue
    authentication/email work, and a success here must never turn a 503
    back into a 200."""
    try:
        release(scope, subject, window_start)
    except RateLimitStorageError:
        current_app.logger.exception(
            'auth rate limiter: compensating release failed for scope=%s (already failing closed)', scope,
        )


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


def _capture_submitted_client_context():
    """Persist browser-reported timezone in the signed-in session.

    When the first coach joins a brand-new team, that Head Coach's browser is
    also the best initial signal for the team's home timezone. It remains
    editable in Team Settings and later travel never changes it automatically.
    """
    timezone_name = normalize_timezone_name(request.form.get('client_timezone'))
    offset_minutes = normalize_utc_offset_minutes(request.form.get('client_utc_offset_minutes'))
    if timezone_name:
        session['client_timezone'] = timezone_name
    if offset_minutes is not None:
        session['client_utc_offset_minutes'] = offset_minutes

    if (
        timezone_name
        and request.endpoint == 'auth.register'
        and session.get('role') == HEAD_COACH
        and session.get('team_id')
    ):
        team_id = session['team_id']
        if db.session.query(TeamMembership).filter_by(team_id=team_id).count() == 1:
            team = db.session.get(Team, team_id)
            if team and team.timezone != timezone_name:
                team.timezone = timezone_name
                db.session.commit()


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
        # Step 1: gather submitted credentials.
        identity = request.form.get('identity') or request.form.get('username')
        password = request.form.get('password') or ''

        # Step 2: resolve the client IP and take a provisional reservation
        # against its bucket, atomically, before any account lookup or
        # password hashing. reserve() both increments and decides "is this
        # (also) over the limit" in one DB statement, so there is no gap
        # between checking and counting for a concurrent request to land
        # in -- unlike a separate check-then-increment pair.
        client_ip = resolve_client_ip()
        ip_max, ip_window = get_limit('login_ip')
        try:
            ip_reservation = reserve('login_ip', client_ip, ip_max, ip_window)
        except RateLimitStorageError:
            return _service_unavailable('login.html', identity=identity)

        if not ip_reservation.admitted:
            flash(_TOO_MANY_ATTEMPTS_MESSAGE, 'danger')
            return render_template('login.html', identity=identity), 429

        # Step 3: look up the account. Canonicalize the account-bucket
        # subject to the user's id when the identity resolves, so the same
        # account is always throttled under one key no matter which alias
        # (username or email) was submitted.
        user = _find_user_by_identity(identity)
        account_subject = user.id if user else f'unknown:{str(identity or "").strip().lower()}'
        account_max, account_window = get_limit('login_account')
        try:
            account_reservation = reserve('login_account', account_subject, account_max, account_window)
        except RateLimitStorageError:
            # The IP reservation above already succeeded -- give it back
            # (best-effort; either way this still fails closed) rather than
            # leaving a stray provisional reservation behind.
            _best_effort_release('login_ip', client_ip, ip_reservation.window_start)
            return _service_unavailable('login.html', identity=identity)

        # Step 4: if the account dimension is already over its limit, this
        # attempt never gets far enough to touch a password hash. Give back
        # the IP reservation this request just took -- for the EXACT window
        # it was taken in, per ip_reservation.window_start, never a freshly
        # recomputed "current" window, which could belong to a different
        # request if the clock has crossed a window boundary since. An
        # attacker hammering one already-blocked account shouldn't also
        # burn down the shared IP budget for everyone else on that network.
        if not account_reservation.admitted:
            try:
                release('login_ip', client_ip, ip_reservation.window_start)
            except RateLimitStorageError:
                return _service_unavailable('login.html', identity=identity)
            flash(_TOO_MANY_ATTEMPTS_MESSAGE, 'danger')
            return render_template('login.html', identity=identity), 429

        # Step 5: run exactly one password-hash verification every request,
        # whether or not the account exists, so response timing doesn't
        # leak account existence.
        if user:
            password_ok = check_password_hash(user.password_hash, password)
        else:
            check_password_hash(_DUMMY_PASSWORD_HASH, password)
            password_ok = False

        # Step 6: a failed attempt (missing account or wrong password)
        # keeps both reservations taken above -- that is the recorded
        # failure. Nothing further to do here.
        if not password_ok:
            flash('That username/email and password combination did not match.', 'danger')
            return render_template('login.html', identity=identity)

        # Step 7: successful login -- forgive prior failed attempts against
        # this specific account outright, and give back this request's own
        # IP reservation (a real, successful attempt shouldn't count as
        # abuse), by its exact window token, but deliberately leave the IP
        # bucket's existing history alone -- other bad actors sharing that
        # network should still be throttled.
        try:
            clear_bucket('login_account', account_subject)
            release('login_ip', client_ip, ip_reservation.window_start)
        except RateLimitStorageError:
            return _service_unavailable('login.html', identity=identity)

        primary_membership = _latest_membership(user)
        if not primary_membership:
            flash('Your CoachBoard account is not assigned to a team yet. Ask your Head Coach for access.', 'danger')
            return render_template('login.html', identity=identity)

        # Step 8: establish the session exactly as before.
        # Store login timestamps consistently in UTC. The audit/user UI
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
        _capture_submitted_client_context()

        team = db.session.get(Team, primary_membership.team_id)
        record_activity(
            'login',
            user=user,
            team_id=primary_membership.team_id,
            role=primary_membership.role,
            detail=f"Signed in to {team.team_name if team else 'team'}.",
        )
        # Step 9: redirect to the role-appropriate destination.
        return redirect(_signed_in_destination(primary_membership.role))

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

        # Step 1: IP volumetric limit, consumed before any lookup work --
        # including the registration-code lookup below -- so a flood of
        # otherwise-invalid submissions can't dodge throttling by failing
        # validation early.
        client_ip = resolve_client_ip()
        ip_max, ip_window = get_limit('register_ip')
        try:
            ip_reservation = reserve('register_ip', client_ip, ip_max, ip_window)
        except RateLimitStorageError:
            return _service_unavailable('register.html', registration_code=reg_code, form=request.form)

        if not ip_reservation.admitted:
            flash(_TOO_MANY_ATTEMPTS_MESSAGE, 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form), 429

        # Step 2: basic field validation. These messages aren't
        # enumeration-sensitive (they don't depend on whether any account
        # already exists), so their position relative to the checks below
        # doesn't affect privacy.
        if not all([username, email, full_name, password, reg_code]):
            flash('Name, username, email, password, and team registration code are required.', 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form)
        if not valid_email(email):
            flash('Enter a valid email address. CoachBoard uses it if you ever forget your password.', 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form)
        if len(password) < MIN_PASSWORD_LENGTH:
            flash(f'Password must be at least {MIN_PASSWORD_LENGTH} characters long.', 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form)

        # Step 3: the registration code must resolve to a real team BEFORE
        # any uniqueness check runs. Team codes are real secrets
        # (secrets.token_urlsafe(9)), so this closes the fully-anonymous
        # enumeration oracle -- without a valid code, nobody learns
        # anything about which usernames/emails already exist.
        team = db.session.query(Team).filter_by(registration_code=reg_code).first()
        if not team:
            flash('That team registration code was not recognized.', 'danger')
            return render_template('register.html', registration_code=reg_code, form=request.form)

        # Step 4: one combined uniqueness query, one generic message. A
        # caller who does hold a valid code can still learn *that* some
        # combination collides, but never which field or with what value.
        duplicate = db.session.query(User).filter(
            or_(func.lower(User.username) == username.lower(), func.lower(User.email) == email)
        ).first()
        if duplicate:
            flash(
                "That username or email is already registered. Try signing in, or use Forgot Password if you "
                "can't find your login.",
                'danger',
            )
            return render_template('register.html', registration_code=reg_code, form=request.form)

        # Step 5: create the account and establish the session.
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
        _capture_submitted_client_context()
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


def _deliver_password_reset_email(app, user_id, reset_url):
    """Background worker: does the real (slow) SMTP I/O off the request
    thread. Re-queries the user by primitive id inside a fresh app context
    rather than receiving a request-bound ORM object. A None user_id/
    reset_url (the nonexistent-account case) is a deliberate no-op, so this
    function always gets scheduled the same way regardless of whether the
    submitted identity resolved to a real account."""
    if not user_id or not reset_url:
        return
    with app.app_context():
        user = db.session.get(User, user_id)
        if not user or not user.email:
            return
        try:
            send_password_reset_email(user, reset_url)
        except Exception:
            app.logger.exception('Unable to send CoachBoard password reset email for user id %s', user_id)


@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    submitted = False
    email_available = email_delivery_configured()

    if request.method == 'POST':
        submitted = True
        identity = str(request.form.get('identity') or '').strip()

        client_ip = resolve_client_ip()
        ip_max, ip_window = get_limit('forgot_password_ip')
        try:
            ip_reservation = reserve('forgot_password_ip', client_ip, ip_max, ip_window)
        except RateLimitStorageError:
            return _service_unavailable('forgot_password.html', submitted=False, email_delivery_enabled=email_available)

        if not ip_reservation.admitted:
            flash(_TOO_MANY_ATTEMPTS_MESSAGE, 'danger')
            return render_template(
                'forgot_password.html', submitted=False, email_delivery_enabled=email_available,
            ), 429

        # Every submission consumes a reservation on both buckets, whether
        # or not the identity resolves -- this endpoint has no notion of a
        # "failed" attempt distinct from a "successful" one from the
        # caller's view, so both dimensions are simple volumetric limits.
        user = _find_user_by_identity(identity)
        account_subject = user.id if user else f'unknown:{identity.lower()}'
        account_max, account_window = get_limit('forgot_password_account')
        try:
            account_reservation = reserve('forgot_password_account', account_subject, account_max, account_window)
        except RateLimitStorageError:
            # The IP reservation above already succeeded -- give it back
            # (best-effort; either way this still fails closed) rather than
            # leaving a stray provisional reservation behind.
            _best_effort_release('forgot_password_ip', client_ip, ip_reservation.window_start)
            return _service_unavailable('forgot_password.html', submitted=False, email_delivery_enabled=email_available)

        if not account_reservation.admitted:
            # This is an ordinary over-limit on the account dimension, not
            # a storage failure -- the IP reservation stands. It was still
            # a real POST and must keep counting against the volumetric IP
            # bucket exactly as designed; only a RateLimitStorageError
            # above triggers a compensating release.
            flash(_TOO_MANY_ATTEMPTS_MESSAGE, 'danger')
            return render_template(
                'forgot_password.html', submitted=False, email_delivery_enabled=email_available,
            ), 429

        # password_reset_url() needs the active request context (it calls
        # url_for), so it must be resolved synchronously here -- but it's
        # cheap (an itsdangerous sign, no I/O), so doing it inline doesn't
        # reintroduce a timing signal. Only compute it when there's really
        # somewhere to send it.
        reset_user_id = None
        reset_url = None
        if user and user.email and email_available:
            reset_user_id = user.id
            reset_url = password_reset_url(user)

        # Always schedule exactly one background task, with the same shape
        # of arguments either way, so scheduling itself is never an
        # observable signal. The real SMTP I/O only ever happens off the
        # request thread, closing the synchronous-SMTP timing side channel.
        app_obj = current_app._get_current_object()
        socketio.start_background_task(_deliver_password_reset_email, app_obj, reset_user_id, reset_url)

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