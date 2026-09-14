"""Coverage for P2 authentication abuse controls: rate limiting on login,
forgot-password and registration, the dummy-hash login timing fix, the
background-task email dispatch that removes forgot-password's synchronous
SMTP timing signal, and the fail-closed/atomic-admission storage layer in
auth_rate_limit.py.

All fixed-window behavior is tested deterministically, either by keeping
thresholds low enough to trip within a handful of requests, or by writing a
stale `window_start` directly into the database -- never by sleeping past a
real window. The one genuinely concurrent test uses real OS threads against
a temporary file-backed SQLite database (not sqlite:///:memory:), because a
sequential loop cannot exercise -- and therefore cannot prove closed -- an
admission race between concurrent requests.
"""
import threading

from werkzeug.security import generate_password_hash


def _build_app(monkeypatch, **rate_limit_overrides):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)
    app.config.update(rate_limit_overrides)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1, team_name='Home Team', registration_code='home-code',
            age_group='12U', pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3, timezone='America/Indiana/Indianapolis',
        )
        coach = User(
            id=1, username='coach', email='coach@example.com', full_name='Head Coach',
            password_hash=generate_password_hash('correct-horse'),
        )
        other_coach = User(
            id=2, username='assistant', email='assistant@example.com', full_name='Assistant Coach',
            password_hash=generate_password_hash('another-password'),
        )
        db.session.add_all([team, coach, other_coach])
        db.session.flush()
        db.session.add_all([
            TeamMembership(user_id=coach.id, team_id=team.id, role='Head Coach', player_order=[]),
            TeamMembership(user_id=other_coach.id, team_id=team.id, role='Assistant Coach', player_order=[]),
        ])
        db.session.commit()

    return app


# ---------------------------------------------------------------------------
# auth_rate_limit.py storage-layer unit tests
# ---------------------------------------------------------------------------

def test_reserve_admits_first_attempt_when_bucket_has_no_row(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import reserve

    with app.app_context():
        assert reserve('probe', 'nobody', max_attempts=3, window_seconds=900).admitted is True


def test_reserve_admits_up_to_max_then_denies(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import reserve

    with app.app_context():
        assert reserve('probe', 'target', max_attempts=2, window_seconds=900).admitted is True
        assert reserve('probe', 'target', max_attempts=2, window_seconds=900).admitted is True
        # Denied, but still counted -- reserve() always consumes a slot.
        assert reserve('probe', 'target', max_attempts=2, window_seconds=900).admitted is False
        assert reserve('probe', 'target', max_attempts=2, window_seconds=900).admitted is False


def test_reserve_counts_a_denied_attempt(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import AuthRateLimit, _derive_key, reserve
    from db import db

    with app.app_context():
        reserve('probe', 'target', max_attempts=1, window_seconds=900)
        reserve('probe', 'target', max_attempts=1, window_seconds=900)  # denied
        row = db.session.get(AuthRateLimit, _derive_key('probe', 'target'))
        assert row.count == 2


def test_stale_window_gives_reserve_a_fresh_count(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import AuthRateLimit, _derive_key, reserve
    from db import db

    with app.app_context():
        for _ in range(3):
            reserve('probe', 'target', max_attempts=3, window_seconds=900)
        assert reserve('probe', 'target', max_attempts=3, window_seconds=900).admitted is False

        key = _derive_key('probe', 'target')
        row = db.session.get(AuthRateLimit, key)
        row.window_start = 0  # force it into a long-expired window
        db.session.commit()

        assert reserve('probe', 'target', max_attempts=3, window_seconds=900).admitted is True
        row = db.session.get(AuthRateLimit, key)
        assert row.count == 1


def test_release_decrements_by_one_and_floors_at_zero(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import AuthRateLimit, _derive_key, release, reserve
    from db import db

    with app.app_context():
        first = reserve('probe', 'target', max_attempts=5, window_seconds=900)
        reserve('probe', 'target', max_attempts=5, window_seconds=900)
        key = _derive_key('probe', 'target')

        release('probe', 'target', first.window_start)
        assert db.session.get(AuthRateLimit, key).count == 1

        release('probe', 'target', first.window_start)
        assert db.session.get(AuthRateLimit, key).count == 0

        # Releasing an already-zero bucket must not go negative or raise.
        release('probe', 'target', first.window_start)
        assert db.session.get(AuthRateLimit, key).count == 0

        # Releasing a bucket with no row at all must not raise.
        release('probe', 'never-reserved', first.window_start)


def test_clear_bucket_removes_row_and_is_idempotent(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import AuthRateLimit, _derive_key, clear_bucket, reserve
    from db import db

    with app.app_context():
        reserve('probe', 'target', max_attempts=2, window_seconds=900)
        key = _derive_key('probe', 'target')
        assert db.session.get(AuthRateLimit, key) is not None

        clear_bucket('probe', 'target')
        assert db.session.get(AuthRateLimit, key) is None

        # Clearing an already-empty bucket must not raise.
        clear_bucket('probe', 'target')


def test_keys_are_hmac_derived_not_raw_subject(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import AuthRateLimit, reserve
    from db import db

    with app.app_context():
        reserve('login_ip', '203.0.113.42', max_attempts=5, window_seconds=900)
        reserve('login_account', 'coach@example.com', max_attempts=5, window_seconds=900)

        stored_keys = [row.key for row in db.session.query(AuthRateLimit).all()]
        assert stored_keys, 'expected rows to have been written'
        for key in stored_keys:
            assert '203.0.113.42' not in key
            assert 'coach@example.com' not in key
            assert len(key) == 64  # sha256 hex digest


def test_different_scopes_do_not_share_a_bucket(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import reserve

    with app.app_context():
        for _ in range(3):
            reserve('login_ip', '203.0.113.42', max_attempts=3, window_seconds=900)
        assert reserve('login_ip', '203.0.113.42', max_attempts=3, window_seconds=900).admitted is False
        assert reserve('forgot_password_ip', '203.0.113.42', max_attempts=3, window_seconds=900).admitted is True


def test_reserve_fails_closed_on_storage_error(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import RateLimitStorageError, reserve
    from db import db

    with app.app_context():
        def boom(*args, **kwargs):
            raise RuntimeError('database is unavailable')

        monkeypatch.setattr(db.session, 'execute', boom)
        try:
            reserve('probe', 'target', max_attempts=3, window_seconds=900)
            assert False, 'expected RateLimitStorageError'
        except RateLimitStorageError:
            pass


def test_release_fails_closed_on_storage_error(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import RateLimitStorageError, release, reserve
    from db import db

    with app.app_context():
        reservation = reserve('probe', 'target', max_attempts=5, window_seconds=900)

        def boom(*args, **kwargs):
            raise RuntimeError('database is unavailable')

        monkeypatch.setattr(db.session, 'execute', boom)
        try:
            release('probe', 'target', reservation.window_start)
            assert False, 'expected RateLimitStorageError'
        except RateLimitStorageError:
            pass


def test_clear_bucket_fails_closed_on_storage_error(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import RateLimitStorageError, clear_bucket, reserve
    from db import db

    with app.app_context():
        reserve('probe', 'target', max_attempts=5, window_seconds=900)

        def boom(*args, **kwargs):
            raise RuntimeError('database is unavailable')

        monkeypatch.setattr(db.session, 'commit', boom)
        try:
            clear_bucket('probe', 'target')
            assert False, 'expected RateLimitStorageError'
        except RateLimitStorageError:
            pass


def test_cleanup_stale_rows_deletes_only_old_rows(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import AuthRateLimit, _derive_key, cleanup_stale_rows, reserve
    from db import db

    with app.app_context():
        reserve('probe', 'fresh', max_attempts=5, window_seconds=900)
        reserve('probe', 'stale', max_attempts=5, window_seconds=900)

        stale_row = db.session.get(AuthRateLimit, _derive_key('probe', 'stale'))
        stale_row.window_start = 0
        db.session.commit()

        cleanup_stale_rows(now=10_000_000)

        remaining_keys = {row.key for row in db.session.query(AuthRateLimit).all()}
        assert _derive_key('probe', 'fresh') in remaining_keys
        assert _derive_key('probe', 'stale') not in remaining_keys


def test_cleanup_retention_scales_with_longest_configured_window(monkeypatch):
    # A window configured longer than the old hardcoded 7200s retention must
    # not have its still-valid row swept away.
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_LOGIN_IP_WINDOW=20000)
    from auth_rate_limit import AuthRateLimit, _derive_key, cleanup_stale_rows, reserve
    from db import db

    with app.app_context():
        reserve('login_ip', 'still-valid', max_attempts=5, window_seconds=20000)
        row = db.session.get(AuthRateLimit, _derive_key('login_ip', 'still-valid'))
        # Set window_start to "old enough that the OLD fixed 7200s retention
        # would have deleted it" but still within this row's real 20000s
        # window from a plausible "now".
        now = 100_000
        row.window_start = now - 8000  # older than 7200s ago, younger than 20000s
        db.session.commit()

        cleanup_stale_rows(now=now)

        assert db.session.get(AuthRateLimit, _derive_key('login_ip', 'still-valid')) is not None


def test_get_limit_defaults(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import get_limit

    with app.app_context():
        assert get_limit('login_ip') == (20, 900)
        assert get_limit('login_account') == (5, 900)
        assert get_limit('forgot_password_ip') == (10, 3600)
        assert get_limit('forgot_password_account') == (3, 3600)
        assert get_limit('register_ip') == (10, 3600)


def test_get_limit_overridable_via_config(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_LOGIN_ACCOUNT_MAX=2, AUTH_RATE_LIMIT_LOGIN_ACCOUNT_WINDOW=30)
    from auth_rate_limit import get_limit

    with app.app_context():
        assert get_limit('login_account') == (2, 30)
        # Overriding one limit must not weaken the untouched ones.
        assert get_limit('login_ip') == (20, 900)


def test_get_limit_rejects_zero_or_negative_overrides(monkeypatch):
    from auth_rate_limit import get_limit

    for bad_max, bad_window in [(0, 900), (-1, 900), (5, 0), (5, -30)]:
        app = _build_app(
            monkeypatch,
            AUTH_RATE_LIMIT_LOGIN_ACCOUNT_MAX=bad_max,
            AUTH_RATE_LIMIT_LOGIN_ACCOUNT_WINDOW=bad_window,
        )
        with app.app_context():
            try:
                get_limit('login_account')
                assert False, f'expected ValueError for max={bad_max}, window={bad_window}'
            except ValueError:
                pass


def test_reserve_rejects_zero_window_instead_of_dividing_by_zero(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import reserve

    with app.app_context():
        try:
            reserve('probe', 'target', max_attempts=5, window_seconds=0)
            assert False, 'expected ValueError'
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# resolve_client_ip()
# ---------------------------------------------------------------------------

def test_resolve_client_ip_defaults_to_remote_addr(monkeypatch):
    app = _build_app(monkeypatch)
    from auth_rate_limit import resolve_client_ip

    with app.test_request_context('/', environ_overrides={'REMOTE_ADDR': '198.51.100.7'},
                                    headers={'CF-Connecting-IP': '9.9.9.9'}):
        assert resolve_client_ip() == '198.51.100.7'


def test_resolve_client_ip_ignores_spoofed_x_forwarded_for_header(monkeypatch):
    # X-Forwarded-For is never consulted by this module at all -- not by
    # default, and not even in opt-in Cloudflare mode (which only reads
    # CF-Connecting-IP) -- so a spoofed value must never change the
    # resolved identity used for rate-limit buckets.
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_TRUST_CLOUDFLARE=True)
    from auth_rate_limit import resolve_client_ip

    with app.test_request_context(
        '/',
        environ_overrides={'REMOTE_ADDR': '198.51.100.7'},
        headers={'X-Forwarded-For': '1.2.3.4, 5.6.7.8'},
    ):
        assert resolve_client_ip() == '198.51.100.7'


def test_resolve_client_ip_ignores_cf_header_when_disabled(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_TRUST_CLOUDFLARE=False)
    from auth_rate_limit import resolve_client_ip

    with app.test_request_context('/', environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                                    headers={'CF-Connecting-IP': '9.9.9.9'}):
        assert resolve_client_ip() == '127.0.0.1'


def test_resolve_client_ip_trusts_cf_header_when_enabled_and_peer_loopback(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_TRUST_CLOUDFLARE=True)
    from auth_rate_limit import resolve_client_ip

    with app.test_request_context('/', environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                                    headers={'CF-Connecting-IP': '9.9.9.9'}):
        assert resolve_client_ip() == '9.9.9.9'


def test_resolve_client_ip_ignores_cf_header_when_peer_not_loopback(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_TRUST_CLOUDFLARE=True)
    from auth_rate_limit import resolve_client_ip

    with app.test_request_context('/', environ_overrides={'REMOTE_ADDR': '203.0.113.9'},
                                    headers={'CF-Connecting-IP': '9.9.9.9'}):
        assert resolve_client_ip() == '203.0.113.9'


def test_resolve_client_ip_falls_back_on_malformed_cf_header(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_TRUST_CLOUDFLARE=True)
    from auth_rate_limit import resolve_client_ip

    with app.test_request_context('/', environ_overrides={'REMOTE_ADDR': '127.0.0.1'},
                                    headers={'CF-Connecting-IP': 'not-an-ip; DROP TABLE users'}):
        assert resolve_client_ip() == '127.0.0.1'


def test_release_with_stale_window_token_is_a_safe_no_op(monkeypatch):
    """Reserve in window A, force the clock/bucket into window B, reserve
    the same bucket again (now in B), then release the OLD window-A token.
    Without the window_start check in release()'s WHERE clause, this would
    decrement window B's count -- a completely different reservation's
    accounting -- rather than doing nothing. This is exactly the race
    described in the review: request A reserves, the window rolls over,
    request B reserves in the new window, and request A's late release()
    must not be able to touch B's count."""
    app = _build_app(monkeypatch)
    import auth_rate_limit
    from auth_rate_limit import AuthRateLimit, _derive_key, release, reserve
    from db import db

    with app.app_context():
        fake_now = [1_700_000_000]  # arbitrary fixed epoch second
        monkeypatch.setattr(auth_rate_limit.time, 'time', lambda: fake_now[0])

        reservation_a = reserve('probe', 'target', max_attempts=10, window_seconds=900)
        assert reservation_a.admitted is True

        # Advance the (mocked) clock past this window's boundary -- request
        # B's reserve() now genuinely lands in a brand new fixed window.
        fake_now[0] += 900

        reservation_b = reserve('probe', 'target', max_attempts=10, window_seconds=900)
        assert reservation_b.admitted is True
        assert reservation_b.window_start != reservation_a.window_start

        key = _derive_key('probe', 'target')
        assert db.session.get(AuthRateLimit, key).count == 1  # window B's own fresh count

        # Release request A's now-stale token (from the OLD window). Its
        # window_start no longer matches the row's current window_start,
        # so this must be a safe no-op -- window B's count must be
        # untouched.
        release('probe', 'target', reservation_a.window_start)

        row_after_release = db.session.get(AuthRateLimit, key)
        assert row_after_release.count == 1
        assert row_after_release.window_start == reservation_b.window_start


# ---------------------------------------------------------------------------
# Real concurrency regression for the atomic reserve() primitive
# ---------------------------------------------------------------------------

def test_reserve_admits_no_more_than_configured_max_under_real_concurrency(monkeypatch, tmp_path):
    """Proves the admission race is actually closed. A sequential loop
    cannot exercise this: it never gives two callers a chance to observe
    the same pre-increment state. This spins up real OS threads (this
    process is never eventlet-monkeypatched under pytest -- only
    run.py's production entrypoint calls eventlet.monkey_patch()) against
    a temporary file-backed SQLite database, synchronized with a Barrier so
    they all call reserve() on the same bucket as close to simultaneously
    as possible."""
    db_path = tmp_path / 'concurrency.db'
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{db_path}')

    from app import create_app
    from db import db
    from auth_rate_limit import reserve

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()

    max_attempts = 5
    window_seconds = 900
    worker_count = 25
    results = [None] * worker_count
    barrier = threading.Barrier(worker_count)

    def worker(index):
        try:
            barrier.wait()
            with app.app_context():
                results[index] = reserve('concurrency-probe', 'shared-bucket', max_attempts, window_seconds)
        except Exception as exc:  # noqa: BLE001 -- captured for the assertion below
            results[index] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(worker_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, f'worker threads raised: {errors}'

    admitted = sum(1 for r in results if r.admitted is True)
    denied = sum(1 for r in results if r.admitted is False)
    assert admitted == max_attempts, f'expected exactly {max_attempts} admitted, got {admitted}'
    assert denied == worker_count - max_attempts


# ---------------------------------------------------------------------------
# /login
# ---------------------------------------------------------------------------

def test_login_wrong_password_reserves_both_buckets(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()

    client.post('/login', data={'identity': 'coach', 'password': 'wrong'})

    from auth_rate_limit import AuthRateLimit, _derive_key
    from db import db
    with app.app_context():
        ip_row = db.session.get(AuthRateLimit, _derive_key('login_ip', '127.0.0.1'))
        account_row = db.session.get(AuthRateLimit, _derive_key('login_account', 1))
        assert ip_row.count == 1
        assert account_row.count == 1


def test_login_dummy_hash_runs_exactly_once_for_unknown_identity(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()

    import blueprints.auth as auth_module
    calls = []
    original = auth_module.check_password_hash

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(auth_module, 'check_password_hash', counting)

    response = client.post('/login', data={'identity': 'no-such-user', 'password': 'whatever'})

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == auth_module._DUMMY_PASSWORD_HASH


def test_login_real_hash_runs_exactly_once_for_wrong_password(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()

    import blueprints.auth as auth_module
    calls = []
    original = auth_module.check_password_hash

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(auth_module, 'check_password_hash', counting)

    response = client.post('/login', data={'identity': 'coach', 'password': 'wrong'})

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] != auth_module._DUMMY_PASSWORD_HASH


def test_login_account_limit_blocks_one_account_without_affecting_another(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_LOGIN_ACCOUNT_MAX=2)
    client = app.test_client()

    for _ in range(2):
        response = client.post('/login', data={'identity': 'coach', 'password': 'wrong'})
        assert response.status_code == 200

    blocked = client.post('/login', data={'identity': 'coach', 'password': 'wrong'})
    assert blocked.status_code == 429

    still_allowed = client.post('/login', data={'identity': 'assistant', 'password': 'wrong'})
    assert still_allowed.status_code == 200
    assert 'Too many attempts' not in still_allowed.get_data(as_text=True)


def test_login_ip_limit_blocks_across_different_identities(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_LOGIN_IP_MAX=2)
    client = app.test_client()

    client.post('/login', data={'identity': 'coach', 'password': 'wrong'})
    client.post('/login', data={'identity': 'assistant', 'password': 'wrong'})

    blocked = client.post('/login', data={'identity': 'nobody-at-all', 'password': 'wrong'})
    assert blocked.status_code == 429
    assert 'Too many attempts' in blocked.get_data(as_text=True)


def test_login_account_denial_releases_this_requests_ip_reservation(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_LOGIN_ACCOUNT_MAX=1, AUTH_RATE_LIMIT_LOGIN_IP_MAX=100)
    client = app.test_client()

    first = client.post('/login', data={'identity': 'coach', 'password': 'wrong'})
    assert first.status_code == 200  # admitted: account count -> 1, ip count -> 1

    second = client.post('/login', data={'identity': 'coach', 'password': 'wrong'})
    assert second.status_code == 429  # account count -> 2, over max=1: denied

    from auth_rate_limit import AuthRateLimit, _derive_key
    from db import db
    with app.app_context():
        ip_row = db.session.get(AuthRateLimit, _derive_key('login_ip', '127.0.0.1'))
        account_row = db.session.get(AuthRateLimit, _derive_key('login_account', 1))

    # The account bucket keeps counting every reservation, admitted or not.
    assert account_row.count == 2
    # But the second request's IP reservation was given back, since the
    # account dimension already blocked it -- the shared IP budget isn't
    # spent on an attempt that never even reached password verification.
    assert ip_row.count == 1


def test_successful_login_clears_account_bucket_and_releases_only_its_own_ip_reservation(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_LOGIN_ACCOUNT_MAX=3, AUTH_RATE_LIMIT_LOGIN_IP_MAX=10)
    client = app.test_client()

    client.post('/login', data={'identity': 'coach', 'password': 'wrong'})
    client.post('/login', data={'identity': 'coach', 'password': 'wrong'})

    success = client.post('/login', data={'identity': 'coach', 'password': 'correct-horse'})
    assert success.status_code == 302

    from auth_rate_limit import AuthRateLimit, _derive_key
    from db import db
    with app.app_context():
        account_row = db.session.get(AuthRateLimit, _derive_key('login_account', 1))
        ip_row = db.session.get(AuthRateLimit, _derive_key('login_ip', '127.0.0.1'))

    assert account_row is None  # fully forgiven
    # The IP bucket keeps the 2 prior failures but not a 3rd for the
    # successful attempt itself -- that reservation was released, not left
    # in place and not wiped along with the account bucket's history.
    assert ip_row.count == 2


def test_login_username_and_email_alias_share_one_account_bucket(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_LOGIN_ACCOUNT_MAX=3)
    client = app.test_client()

    responses = [
        client.post('/login', data={'identity': 'coach', 'password': 'wrong'}),
        client.post('/login', data={'identity': 'coach@example.com', 'password': 'wrong'}),
        client.post('/login', data={'identity': 'COACH', 'password': 'wrong'}),
    ]
    assert [r.status_code for r in responses] == [200, 200, 200]

    # A 4th attempt via yet another alias for the same real user must be
    # blocked -- proving all three aliases shared one canonicalized bucket.
    blocked = client.post('/login', data={'identity': 'Coach@Example.com', 'password': 'wrong'})
    assert blocked.status_code == 429


def test_login_503_on_storage_error_does_not_authenticate(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()

    import blueprints.auth as auth_module
    from auth_rate_limit import RateLimitStorageError

    def boom(*args, **kwargs):
        raise RateLimitStorageError('simulated storage outage')

    monkeypatch.setattr(auth_module, 'reserve', boom)

    response = client.post('/login', data={'identity': 'coach', 'password': 'correct-horse'})

    assert response.status_code == 503
    assert 'temporarily unavailable' in response.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert not sess.get('logged_in')


def test_login_503_with_compensating_release_when_account_reserve_raises(monkeypatch):
    """The IP reservation succeeds, then the account reservation blows up.
    The route must fail closed (503, no authentication) AND, since storage
    is available again for the compensating call, must actually give back
    the provisional IP reservation rather than leaving it stuck."""
    app = _build_app(monkeypatch)
    client = app.test_client()

    import blueprints.auth as auth_module
    from auth_rate_limit import AuthRateLimit, RateLimitStorageError, _derive_key
    from auth_rate_limit import reserve as real_reserve
    from db import db

    def flaky_reserve(scope, subject, max_attempts, window_seconds):
        if scope == 'login_account':
            raise RateLimitStorageError('simulated storage outage on account bucket')
        return real_reserve(scope, subject, max_attempts, window_seconds)

    monkeypatch.setattr(auth_module, 'reserve', flaky_reserve)

    response = client.post('/login', data={'identity': 'coach', 'password': 'correct-horse'})

    assert response.status_code == 503
    with client.session_transaction() as sess:
        assert not sess.get('logged_in')

    with app.app_context():
        ip_row = db.session.get(AuthRateLimit, _derive_key('login_ip', '127.0.0.1'))
    # The provisional IP reservation (count 1 after the successful reserve)
    # was released once the account reservation raised -- it must not be
    # left stuck at 1.
    assert ip_row is not None and ip_row.count == 0


# ---------------------------------------------------------------------------
# /forgot_password
# ---------------------------------------------------------------------------

def test_forgot_password_response_and_scheduling_identical_for_real_and_fake_identity(monkeypatch):
    app = _build_app(monkeypatch)
    app.config['SMTP_HOST'] = 'smtp.example.com'
    app.config['SMTP_FROM'] = 'noreply@example.com'

    import blueprints.auth as auth_module
    scheduled = []

    def fake_start_background_task(func, *args, **kwargs):
        scheduled.append((func, args))
        return None  # do not actually run it in this test

    monkeypatch.setattr(auth_module.socketio, 'start_background_task', fake_start_background_task)

    client = app.test_client()
    real_response = client.post('/forgot_password', data={'identity': 'coach'})
    fake_response = client.post('/forgot_password', data={'identity': 'no-such-person'})

    assert real_response.status_code == fake_response.status_code == 200
    assert real_response.get_data(as_text=True) == fake_response.get_data(as_text=True)

    assert len(scheduled) == 2
    for func, args in scheduled:
        assert func is auth_module._deliver_password_reset_email
        assert len(args) == 3  # (app, user_id_or_None, reset_url_or_None)

    real_user_id, real_reset_url = scheduled[0][1][1], scheduled[0][1][2]
    fake_user_id, fake_reset_url = scheduled[1][1][1], scheduled[1][1][2]
    assert real_user_id == 1 and real_reset_url
    assert fake_user_id is None and fake_reset_url is None


def test_forgot_password_worker_sends_email_for_real_account_only(monkeypatch):
    app = _build_app(monkeypatch)

    import blueprints.auth as auth_module
    sent = []
    monkeypatch.setattr(auth_module, 'send_password_reset_email', lambda user, url: sent.append((user.id, url)))

    with app.app_context():
        auth_module._deliver_password_reset_email(app, 1, 'https://example.test/reset/abc')
        auth_module._deliver_password_reset_email(app, None, None)

    assert sent == [(1, 'https://example.test/reset/abc')]


def test_forgot_password_ip_and_account_limits_block_after_threshold(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_FORGOT_PASSWORD_ACCOUNT_MAX=1)
    client = app.test_client()

    first = client.post('/forgot_password', data={'identity': 'coach'})
    assert first.status_code == 200

    blocked = client.post('/forgot_password', data={'identity': 'coach'})
    assert blocked.status_code == 429

    # A different account from the same client is unaffected.
    still_allowed = client.post('/forgot_password', data={'identity': 'assistant'})
    assert still_allowed.status_code == 200


def test_forgot_password_503_on_storage_error_does_not_schedule_email(monkeypatch):
    app = _build_app(monkeypatch)

    import blueprints.auth as auth_module
    from auth_rate_limit import RateLimitStorageError

    scheduled = []
    monkeypatch.setattr(
        auth_module.socketio, 'start_background_task',
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )

    def boom(*args, **kwargs):
        raise RateLimitStorageError('simulated storage outage')

    monkeypatch.setattr(auth_module, 'reserve', boom)

    client = app.test_client()
    response = client.post('/forgot_password', data={'identity': 'coach'})

    assert response.status_code == 503
    assert scheduled == []


def test_forgot_password_503_with_compensating_release_when_account_reserve_raises(monkeypatch):
    """Same partial-failure shape as login: the IP reservation succeeds,
    then the account reservation raises. Must fail closed (503, no email
    scheduled) and give back the provisional IP reservation."""
    app = _build_app(monkeypatch)
    client = app.test_client()

    import blueprints.auth as auth_module
    from auth_rate_limit import AuthRateLimit, RateLimitStorageError, _derive_key
    from auth_rate_limit import reserve as real_reserve
    from db import db

    scheduled = []
    monkeypatch.setattr(
        auth_module.socketio, 'start_background_task',
        lambda *args, **kwargs: scheduled.append((args, kwargs)),
    )

    def flaky_reserve(scope, subject, max_attempts, window_seconds):
        if scope == 'forgot_password_account':
            raise RateLimitStorageError('simulated storage outage on account bucket')
        return real_reserve(scope, subject, max_attempts, window_seconds)

    monkeypatch.setattr(auth_module, 'reserve', flaky_reserve)

    response = client.post('/forgot_password', data={'identity': 'coach'})

    assert response.status_code == 503
    assert scheduled == []

    with app.app_context():
        ip_row = db.session.get(AuthRateLimit, _derive_key('forgot_password_ip', '127.0.0.1'))
    assert ip_row is not None and ip_row.count == 0


# ---------------------------------------------------------------------------
# /register
# ---------------------------------------------------------------------------

def test_registration_ip_limit_blocks_after_threshold(monkeypatch):
    app = _build_app(monkeypatch, AUTH_RATE_LIMIT_REGISTER_IP_MAX=1)
    client = app.test_client()

    client.post('/register', data={
        'username': 'first-new-coach', 'email': 'first@example.com', 'full_name': 'First',
        'password': 'a-strong-password', 'registration_code': 'bogus-code',
    })

    blocked = client.post('/register', data={
        'username': 'second-new-coach', 'email': 'second@example.com', 'full_name': 'Second',
        'password': 'a-strong-password', 'registration_code': 'bogus-code',
    })
    assert blocked.status_code == 429


def test_registration_code_checked_before_uniqueness_and_duplicate_message_is_generic(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()

    # An invalid code with a colliding username must reveal nothing about
    # the collision -- only that the code was not recognized.
    invalid_code_response = client.post('/register', data={
        'username': 'coach', 'email': 'new-email@example.com', 'full_name': 'Someone',
        'password': 'a-strong-password', 'registration_code': 'not-a-real-code',
    })
    body = invalid_code_response.get_data(as_text=True)
    assert 'registration code was not recognized' in body
    assert 'already taken' not in body
    assert 'already registered' not in body

    # With a valid code, a colliding username/email gets one generic message.
    duplicate_response = client.post('/register', data={
        'username': 'coach', 'email': 'new-email@example.com', 'full_name': 'Someone',
        'password': 'a-strong-password', 'registration_code': 'home-code',
    })
    assert 'already registered' in duplicate_response.get_data(as_text=True)


def test_registration_success_still_works_under_the_limit(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()

    response = client.post('/register', data={
        'username': 'brand-new-coach', 'email': 'brand-new@example.com', 'full_name': 'Brand New',
        'password': 'a-strong-password', 'registration_code': 'home-code',
    })
    assert response.status_code == 302

    from db import db
    from models import User
    with app.app_context():
        assert db.session.query(User).filter_by(username='brand-new-coach').first() is not None


def test_registration_503_on_storage_error_does_not_create_account(monkeypatch):
    app = _build_app(monkeypatch)

    import blueprints.auth as auth_module
    from auth_rate_limit import RateLimitStorageError

    def boom(*args, **kwargs):
        raise RateLimitStorageError('simulated storage outage')

    monkeypatch.setattr(auth_module, 'reserve', boom)

    client = app.test_client()
    response = client.post('/register', data={
        'username': 'shouldnotexist', 'email': 'shouldnotexist@example.com', 'full_name': 'Nope',
        'password': 'a-strong-password', 'registration_code': 'home-code',
    })

    assert response.status_code == 503

    from db import db
    from models import User
    with app.app_context():
        assert db.session.query(User).filter_by(username='shouldnotexist').first() is None
