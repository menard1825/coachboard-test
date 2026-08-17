import hashlib
import os
import smtplib
from email.message import EmailMessage

from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from db import db
from models import User

RESET_SALT = 'coachboard-password-reset-v1'
DEFAULT_RESET_SECONDS = 3600


def normalize_email(value):
    return str(value or '').strip().lower()


def valid_email(value):
    email = normalize_email(value)
    if not email or len(email) > 255 or '@' not in email:
        return False
    local, domain = email.rsplit('@', 1)
    return bool(local and '.' in domain and not domain.startswith('.') and not domain.endswith('.'))


def _password_fingerprint(user):
    return hashlib.sha256((user.password_hash or '').encode('utf-8')).hexdigest()[:24]


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt=RESET_SALT)


def _setting(name, default=None):
    value = current_app.config.get(name)
    if value not in (None, ''):
        return value
    return os.environ.get(name, default)


def _bool_setting(name, default=False):
    value = _setting(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def create_password_reset_token(user):
    return _serializer().dumps({
        'uid': int(user.id),
        'pwd': _password_fingerprint(user),
    })


def password_reset_max_age():
    try:
        return int(_setting('PASSWORD_RESET_MAX_AGE', DEFAULT_RESET_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_RESET_SECONDS


def resolve_password_reset_token(token):
    try:
        payload = _serializer().loads(token, max_age=password_reset_max_age())
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None

    try:
        user_id = int(payload.get('uid'))
    except (TypeError, ValueError, AttributeError):
        return None

    user = db.session.get(User, user_id)
    if not user:
        return None
    if payload.get('pwd') != _password_fingerprint(user):
        return None
    return user


def password_reset_url(user):
    token = create_password_reset_token(user)
    path = url_for('auth.reset_password_token', token=token, _external=False)
    public_base = str(_setting('PUBLIC_BASE_URL', '') or '').strip().rstrip('/')
    if public_base:
        return f'{public_base}{path}'
    return url_for('auth.reset_password_token', token=token, _external=True)


def email_delivery_configured():
    return bool(_setting('SMTP_HOST') and _setting('SMTP_FROM'))


def send_password_reset_email(user, reset_url):
    if not user.email:
        raise ValueError('This user does not have an email address on file.')
    if not email_delivery_configured():
        raise RuntimeError('Email delivery is not configured on this CoachBoard server.')

    host = _setting('SMTP_HOST')
    port = int(_setting('SMTP_PORT', 587))
    username = _setting('SMTP_USERNAME')
    password = _setting('SMTP_PASSWORD')
    use_tls = _bool_setting('SMTP_USE_TLS', True)
    use_ssl = _bool_setting('SMTP_USE_SSL', False)
    sender = _setting('SMTP_FROM')

    minutes = max(1, password_reset_max_age() // 60)
    message = EmailMessage()
    message['Subject'] = 'Reset your CoachBoard password'
    message['From'] = sender
    message['To'] = user.email
    message.set_content(
        f"Hi {user.full_name or user.username},\n\n"
        f"Use the link below to choose a new CoachBoard password.\n\n"
        f"{reset_url}\n\n"
        f"This link expires in {minutes} minutes and stops working after your password is changed.\n\n"
        "If you did not request this, you can ignore this message."
    )

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(host, port, timeout=20) as smtp:
        if not use_ssl and use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password or '')
        smtp.send_message(message)
