"""Storage-backed abuse controls for the authentication endpoints.

Login, forgot-password and registration are all public, unauthenticated
POST endpoints, so they need volumetric (per-IP) and, where an account
concept applies, per-account throttling. This module is the single storage
layer for that: one SQLite-backed table (`auth_rate_limits`) holding fixed
windows, keyed by an HMAC-SHA256 digest so raw usernames/emails/IPs are
never persisted in the clear.

Admission control goes through a single atomic primitive, `reserve()`: one
`INSERT ... ON CONFLICT DO UPDATE ... RETURNING` statement that both rolls
the window over/increments the counter AND reports whether the resulting
count is within the limit, in one serialized database operation. A
check-then-increment pair (read the count, decide, write the increment
later) cannot do this safely: many concurrent requests can all read the
same pre-increment count and all be admitted before any of their
increments commit. `reserve()` closes that race because there is no gap
between "increment" and "decide" for another request to land in.

Fail-closed: if the database itself is unreachable or errors, every
mutating primitive here (`reserve`, `release`, `clear_bucket`) rolls back
and raises `RateLimitStorageError` rather than silently letting the caller
proceed. A route that cannot determine whether a request is within its
abuse-control budget must not authenticate, create an account, or schedule
a recovery email -- it must fail the request (a generic 503) instead. This
is a different failure mode from an ordinary 429: a 429 means the limiter
is working and the caller is over a real limit; a `RateLimitStorageError`
means the limiter itself could not be consulted at all, and callers must
never collapse the two.
"""
import hashlib
import hmac
import ipaddress
import os
import random
import time
from typing import NamedTuple

from flask import current_app, request
from sqlalchemy import BigInteger, Column, Integer, String, case, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db import db

# Fixed-window thresholds. Overridable per-app (tests need short windows and
# low ceilings) via app.config, without weakening these production defaults.
_LIMIT_DEFAULTS = {
    'login_ip': (20, 900),                  # 20 failed attempts / 15 min
    'login_account': (5, 900),              # 5 failed attempts / 15 min
    'forgot_password_ip': (10, 3600),       # 10 requests / 60 min
    'forgot_password_account': (3, 3600),   # 3 requests / 60 min
    'register_ip': (10, 3600),              # 10 requests / 60 min
}

_CLEANUP_PROBABILITY = 0.01
_CLEANUP_RETENTION_MARGIN = 2  # keep a full extra window's worth of slack


class RateLimitStorageError(Exception):
    """A rate-limit storage operation (reserve/release/clear) could not be
    completed. Callers MUST fail closed: return a generic 503 and perform
    no protected side effect (authentication, account creation, recovery
    email). Never treat this the same as a normal over-limit result -- that
    is a plain False/429, not an exception."""


class Reservation(NamedTuple):
    """The result of one reserve() call. `window_start` is the exact fixed
    window this particular reservation landed in -- callers that may later
    need to release() it MUST pass this value back, not recompute a fresh
    window_start from the current time. If the clock has since crossed a
    window boundary, recomputing would target the WRONG (newer) window and
    release() could decrement a completely different request's count."""

    admitted: bool
    window_start: int


class AuthRateLimit(db.Model):
    """One fixed-window counter bucket, keyed by an HMAC digest."""

    __tablename__ = 'auth_rate_limits'

    key = Column(String(64), primary_key=True)
    window_start = Column(BigInteger, nullable=False, index=True)
    count = Column(Integer, nullable=False, default=0)


def get_limit(name):
    """Return (max_attempts, window_seconds) for a named limit, honoring
    AUTH_RATE_LIMIT_<NAME>_MAX / _WINDOW overrides in app.config or the
    environment (used by tests; production keeps the hardcoded defaults).
    Raises ValueError if either value is not a positive integer -- a zero
    window would divide-by-zero in the window-bucketing math below, and a
    negative value would make "over the limit" meaningless."""
    max_default, window_default = _LIMIT_DEFAULTS[name]
    max_attempts = _int_setting(f'AUTH_RATE_LIMIT_{name.upper()}_MAX', max_default)
    window_seconds = _int_setting(f'AUTH_RATE_LIMIT_{name.upper()}_WINDOW', window_default)
    _validate_limit(max_attempts, window_seconds)
    return max_attempts, window_seconds


def reserve(scope, subject, max_attempts, window_seconds):
    """Atomically increment this bucket's counter for the current window
    (rolling the window over first if it has expired) and, in that same
    serialized statement, report whether the resulting count is within the
    limit. This is the sole admission-control primitive -- there is no
    separate read step for a concurrent caller to race against.

    Returns a Reservation(admitted, window_start). `admitted` is True if
    this attempt is within the limit (resulting count <= max), False if it
    is over. A denied attempt is still counted: the counter always
    reflects every reservation made against it, admitted or not.
    `window_start` identifies exactly which fixed window this reservation
    landed in -- a caller that may later call release() for this specific
    reservation MUST pass this value back rather than letting release()
    recompute "the current window", since the clock may have moved on to a
    new window by the time release() runs.

    Raises RateLimitStorageError (after rolling back) if the database
    cannot complete the operation. Callers MUST fail closed on that
    exception.
    """
    _validate_limit(max_attempts, window_seconds)
    key = _derive_key(scope, subject)
    window_start = _window_start(window_seconds)
    stmt = sqlite_insert(AuthRateLimit).values(key=key, window_start=window_start, count=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AuthRateLimit.key],
        set_={
            'count': case(
                (AuthRateLimit.window_start == window_start, AuthRateLimit.count + 1),
                else_=1,
            ),
            'window_start': window_start,
        },
    ).returning(AuthRateLimit.count)
    try:
        new_count = db.session.execute(stmt).scalar_one()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('auth rate limiter: failed to reserve scope=%s', scope)
        raise RateLimitStorageError(f'reserve failed for scope={scope}') from exc
    _maybe_cleanup()
    return Reservation(admitted=new_count <= max_attempts, window_start=window_start)


def release(scope, subject, expected_window_start):
    """Atomically give back exactly one reservation (decrement by 1,
    floored at 0) for the EXACT window it was taken in -- `expected_window_
    start` must be the `window_start` a prior reserve() call returned
    alongside the reservation being undone. The UPDATE only matches a row
    whose key AND window_start both match, so if the bucket has since
    rolled over into a new window (a new request already reserved against
    it under a fresh window_start), this becomes a safe no-op: it will
    never decrement a different, unrelated reservation's count. Without
    this check, a reservation released late (e.g. after a slow request)
    could silently erase a completely different, still-live window's
    count.

    Never use this to forgive a bucket's whole history; that is
    clear_bucket's job. This only ever undoes a single reservation.

    Raises RateLimitStorageError (after rolling back) if the database
    cannot complete the operation. Callers MUST fail closed on that
    exception.
    """
    key = _derive_key(scope, subject)
    stmt = (
        update(AuthRateLimit)
        .where(
            AuthRateLimit.key == key,
            AuthRateLimit.window_start == expected_window_start,
            AuthRateLimit.count > 0,
        )
        .values(count=AuthRateLimit.count - 1)
    )
    try:
        db.session.execute(stmt)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('auth rate limiter: failed to release scope=%s', scope)
        raise RateLimitStorageError(f'release failed for scope={scope}') from exc


def clear_bucket(scope, subject):
    """Delete a bucket outright (used to forgive an account's prior failed
    login attempts once it authenticates successfully).

    Raises RateLimitStorageError (after rolling back) if the database
    cannot complete the operation. Callers MUST fail closed on that
    exception.
    """
    key = _derive_key(scope, subject)
    try:
        db.session.query(AuthRateLimit).filter(AuthRateLimit.key == key).delete()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('auth rate limiter: failed to clear bucket for scope=%s', scope)
        raise RateLimitStorageError(f'clear failed for scope={scope}') from exc


def cleanup_stale_rows(now=None):
    """Delete rows whose window expired long enough ago that they can no
    longer affect any live check. Safe to call anytime -- a deleted row is
    just recreated fresh by the next reserve() for that key. Retention is
    derived from the longest currently-configured window (with a margin),
    not a fixed constant, so a window configured longer than the old
    hardcoded 2-hour retention can never have its still-valid row deleted
    out from under it. Called probabilistically from reserve(), and
    exposed here so callers (tests, an ops task) can force it
    deterministically."""
    now = int(time.time()) if now is None else now
    cutoff = now - _cleanup_retention_seconds()
    try:
        db.session.query(AuthRateLimit).filter(AuthRateLimit.window_start < cutoff).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('auth rate limiter: cleanup failed')


def resolve_client_ip():
    """Return the client IP to key rate-limit buckets on.

    Defaults to `request.remote_addr` -- the raw TCP peer. In production
    that peer is cloudflared for coachboard.io, or the parallel nginx
    ingress on port 80 for the same host (both loopback from Gunicorn's
    point of view); test.coachboard.io currently also tunnels through
    cloudflared, straight to Test App 2 on localhost:5005, per
    /etc/cloudflared/config.yml. None of these peers are the real client,
    but the peer address is never spoofable, which matters more for an
    abuse-throttling signal than getting the "real" address.

    Do NOT trust X-Forwarded-For here: the existing nginx config sets it to
    `$proxy_add_x_forwarded_for`, which appends onto whatever the client
    already sent rather than replacing it, so it's trivially spoofable by
    anyone hitting nginx directly.

    Opt-in Cloudflare mode (AUTH_RATE_LIMIT_TRUST_CLOUDFLARE=1, disabled by
    default) additionally trusts CF-Connecting-IP, but only when the
    immediate TCP peer is loopback AND the header value is a syntactically
    valid IP address; otherwise it silently falls back to remote_addr.

    IMPORTANT: this mode is not yet safe to enable in production. The
    parallel nginx ingress on port 80 also appears to Gunicorn as a
    loopback peer and does not currently strip an inbound CF-Connecting-IP
    header, so a request sent straight to nginx (bypassing Cloudflare
    entirely) could forge one. Enabling this requires nginx to be
    reconfigured to strip client-supplied CF-Connecting-IP/X-Forwarded-For
    before proxying -- a separate, out-of-scope infrastructure change, not
    made here; nginx/cloudflared configuration is not touched by this
    module. Cloudflare-header trust stays disabled by default until that
    prerequisite is met.
    """
    remote_addr = request.remote_addr or ''
    if not _trust_cloudflare_header():
        return remote_addr
    if not _is_loopback(remote_addr):
        return remote_addr
    candidate = (request.headers.get('CF-Connecting-IP') or '').strip()
    if not candidate:
        return remote_addr
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return remote_addr
    return candidate


def _derive_key(scope, subject):
    secret = (current_app.secret_key or '').encode('utf-8')
    message = f'{scope}:{subject}'.encode('utf-8')
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _window_start(window_seconds):
    now = int(time.time())
    return now - (now % window_seconds)


def _cleanup_retention_seconds():
    longest_window = max(get_limit(name)[1] for name in _LIMIT_DEFAULTS)
    return longest_window * _CLEANUP_RETENTION_MARGIN


def _maybe_cleanup():
    if random.random() < _CLEANUP_PROBABILITY:
        cleanup_stale_rows()


def _validate_limit(max_attempts, window_seconds):
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts <= 0:
        raise ValueError(f'max_attempts must be a positive integer, got {max_attempts!r}')
    if not isinstance(window_seconds, int) or isinstance(window_seconds, bool) or window_seconds <= 0:
        raise ValueError(f'window_seconds must be a positive integer, got {window_seconds!r}')


def _int_setting(name, default):
    value = current_app.config.get(name)
    if value in (None, ''):
        value = os.environ.get(name)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_setting(name, default=False):
    value = current_app.config.get(name)
    if value in (None, ''):
        value = os.environ.get(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _trust_cloudflare_header():
    return _bool_setting('AUTH_RATE_LIMIT_TRUST_CLOUDFLARE', False)


def _is_loopback(remote_addr):
    try:
        return ipaddress.ip_address(remote_addr).is_loopback
    except ValueError:
        return False
