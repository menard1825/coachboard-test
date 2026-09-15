"""Coverage for P3 team-logo upload hardening.

Background: the previous /admin/upload_logo implementation accepted any
file whose *extension* was png/jpg/jpeg/gif/svg, with no check that the
bytes actually decoded as that format. An uploaded .svg is served by
Flask's static route with Content-Type image/svg+xml; direct top-level
navigation to a same-origin SVG executes any embedded <script>, which
bypasses this app's same-origin CSRF check. This suite proves: SVG/GIF
are rejected outright, arbitrary bytes renamed as an image are rejected,
declared extension must agree with the Pillow-decoded format, oversized
uploads and oversized images are rejected, and the "validate everything
before touching existing state" replacement semantics hold even when a
later step (save/commit) fails.

Every test runs with the process's cwd chdir'd into a pytest tmp_path, so
the route's relative 'static/uploads/logos' path resolves into an
isolated throwaway directory -- these tests never write into, or read
from, the real repository-tracked static/uploads/logos directory.
"""
import io
import os

from PIL import Image
from werkzeug.security import generate_password_hash

from utils import MAX_LOGO_DIMENSION, MAX_LOGO_UPLOAD_BYTES


def _build_app(monkeypatch, tmp_path):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.chdir(tmp_path)

    from app import create_app
    from db import db
    from models import Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        home_team = Team(
            id=1, team_name='Home Team', registration_code='home-code',
            age_group='12U', pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3, timezone='America/Indiana/Indianapolis',
        )
        other_team = Team(
            id=2, team_name='Other Team', registration_code='other-code',
            age_group='12U', pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3, timezone='America/Indiana/Indianapolis',
        )
        head_coach = User(
            id=1, username='coach', full_name='Head Coach',
            password_hash=generate_password_hash('password123'),
        )
        assistant = User(
            id=2, username='assistant', full_name='Assistant Coach',
            password_hash=generate_password_hash('password123'),
        )
        game_changer = User(
            id=3, username='scorekeeper', full_name='Game Changer',
            password_hash=generate_password_hash('password123'),
        )
        db.session.add_all([home_team, other_team, head_coach, assistant, game_changer])
        db.session.flush()
        db.session.add_all([
            TeamMembership(user_id=head_coach.id, team_id=home_team.id, role='Head Coach', player_order=[]),
            TeamMembership(user_id=assistant.id, team_id=home_team.id, role='Assistant Coach', player_order=[]),
            TeamMembership(user_id=game_changer.id, team_id=home_team.id, role='Game Changer', player_order=[]),
        ])
        db.session.commit()

    return app


def _login(client, username, role, team_id=1):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = username
        sess['team_id'] = team_id
        sess['role'] = role


def _upload(client, filename, data, content_type='application/octet-stream'):
    return client.post(
        '/admin/upload_logo',
        data={'logo': (io.BytesIO(data), filename, content_type)},
        content_type='multipart/form-data',
    )


def _png_bytes(size=(10, 10)):
    buf = io.BytesIO()
    Image.new('RGB', size, color=(10, 20, 30)).save(buf, format='PNG')
    return buf.getvalue()


def _jpeg_bytes(size=(10, 10)):
    buf = io.BytesIO()
    Image.new('RGB', size, color=(10, 20, 30)).save(buf, format='JPEG')
    return buf.getvalue()


def _svg_bytes():
    return b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def _html_bytes():
    return b'<!doctype html><html><body><script>alert(document.cookie)</script></body></html>'


def _team_logo_path(app, team_id=1):
    from db import db
    from models import Team
    with app.app_context():
        return db.session.get(Team, team_id).logo_path


def _uploads_dir():
    return os.path.join('static', 'uploads', 'logos')


def _stored_files():
    directory = _uploads_dir()
    if not os.path.isdir(directory):
        return []
    return os.listdir(directory)


# ---------------------------------------------------------------------------
# Accept genuine images
# ---------------------------------------------------------------------------

def test_genuine_png_is_accepted(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    response = _upload(client, 'logo.png', _png_bytes())

    assert response.status_code == 302
    logo_path = _team_logo_path(app)
    assert logo_path is not None
    assert logo_path.endswith('.png')
    assert logo_path in _stored_files()


def test_genuine_jpeg_is_accepted(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    response = _upload(client, 'logo.jpg', _jpeg_bytes())

    assert response.status_code == 302
    logo_path = _team_logo_path(app)
    assert logo_path is not None
    assert logo_path.endswith('.jpg')
    assert logo_path in _stored_files()


# ---------------------------------------------------------------------------
# Reject non-images / disguised content
# ---------------------------------------------------------------------------

def test_svg_extension_is_rejected(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    response = _upload(client, 'logo.svg', _svg_bytes())

    assert response.status_code == 302
    assert _team_logo_path(app) is None
    assert _stored_files() == []


def test_svg_bytes_renamed_png_are_rejected(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    response = _upload(client, 'logo.png', _svg_bytes())

    assert response.status_code == 302
    assert _team_logo_path(app) is None
    assert _stored_files() == []


def test_html_renamed_jpg_is_rejected(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    response = _upload(client, 'logo.jpg', _html_bytes())

    assert response.status_code == 302
    assert _team_logo_path(app) is None
    assert _stored_files() == []


def test_unsupported_extension_is_rejected(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    response = _upload(client, 'logo.gif', _png_bytes())  # gif removed from allowlist

    assert response.status_code == 302
    assert _team_logo_path(app) is None
    assert _stored_files() == []


def test_corrupt_truncated_png_is_rejected_without_500(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    truncated = _png_bytes()[:20]
    response = _upload(client, 'logo.png', truncated)

    assert response.status_code == 302
    assert _team_logo_path(app) is None
    assert _stored_files() == []


def test_png_bytes_submitted_as_jpg_are_rejected(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    response = _upload(client, 'logo.jpg', _png_bytes())

    assert response.status_code == 302
    assert _team_logo_path(app) is None
    assert _stored_files() == []


def test_jpeg_bytes_submitted_as_png_are_rejected(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    response = _upload(client, 'logo.png', _jpeg_bytes())

    assert response.status_code == 302
    assert _team_logo_path(app) is None
    assert _stored_files() == []


# ---------------------------------------------------------------------------
# Size / decompression limits
# ---------------------------------------------------------------------------

def test_file_over_byte_limit_is_rejected(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    oversized = b'\x00' * (MAX_LOGO_UPLOAD_BYTES + 1)
    response = _upload(client, 'logo.png', oversized)

    assert response.status_code == 302
    assert _team_logo_path(app) is None
    assert _stored_files() == []


def test_excessive_dimensions_are_rejected(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    oversized_dimensions = _png_bytes(size=(MAX_LOGO_DIMENSION + 100, MAX_LOGO_DIMENSION + 100))
    response = _upload(client, 'logo.png', oversized_dimensions)

    assert response.status_code == 302
    assert _team_logo_path(app) is None
    assert _stored_files() == []


# ---------------------------------------------------------------------------
# Replacement semantics
# ---------------------------------------------------------------------------

def test_rejected_replacement_leaves_existing_logo_untouched(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    first = _upload(client, 'logo.png', _png_bytes())
    assert first.status_code == 302
    original_logo_path = _team_logo_path(app)
    assert original_logo_path is not None
    assert _stored_files() == [original_logo_path]

    rejected = _upload(client, 'logo.svg', _svg_bytes())
    assert rejected.status_code == 302

    assert _team_logo_path(app) == original_logo_path
    assert _stored_files() == [original_logo_path]


def test_successful_replacement_updates_db_and_removes_prior_logo(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    first = _upload(client, 'logo.png', _png_bytes())
    assert first.status_code == 302
    first_logo_path = _team_logo_path(app)
    assert first_logo_path in _stored_files()

    second = _upload(client, 'logo.jpg', _jpeg_bytes())
    assert second.status_code == 302
    second_logo_path = _team_logo_path(app)

    assert second_logo_path != first_logo_path
    assert second_logo_path in _stored_files()
    assert first_logo_path not in _stored_files()
    assert _stored_files() == [second_logo_path]


def test_shared_logo_across_teams_is_preserved_when_one_team_replaces_it(monkeypatch, tmp_path):
    """rollover_season() intentionally copies logo_path onto a newly
    created team, so two Team rows can legitimately reference one physical
    file. Replacing the logo for one of those teams must not delete the
    file out from under the other team that still references it."""
    app = _build_app(monkeypatch, tmp_path)

    from db import db
    from models import Team, TeamMembership, User

    shared_logo_filename = '1_shared0000000000000000000000.png'
    os.makedirs(_uploads_dir(), exist_ok=True)
    with open(os.path.join(_uploads_dir(), shared_logo_filename), 'wb') as f:
        f.write(_png_bytes())

    with app.app_context():
        team_a = db.session.get(Team, 1)
        team_b = db.session.get(Team, 2)
        team_a.logo_path = shared_logo_filename
        team_b.logo_path = shared_logo_filename
        # A genuine Head Coach of team B -- security_guard.py's session
        # membership check requires a real TeamMembership row matching the
        # session's (username, team_id) pair, so team-2 scoping can't just
        # be asserted via the session dict alone.
        team_b_coach = User(
            id=4, username='team-b-coach', full_name='Team B Head Coach',
            password_hash=generate_password_hash('password123'),
        )
        db.session.add(team_b_coach)
        db.session.flush()
        db.session.add(TeamMembership(user_id=team_b_coach.id, team_id=team_b.id, role='Head Coach', player_order=[]))
        db.session.commit()

    client = app.test_client()
    _login(client, 'team-b-coach', 'Head Coach', team_id=2)

    response = _upload(client, 'logo.jpg', _jpeg_bytes())
    assert response.status_code == 302

    team_a_logo_path = _team_logo_path(app, team_id=1)
    team_b_logo_path = _team_logo_path(app, team_id=2)

    assert team_a_logo_path == shared_logo_filename
    assert team_b_logo_path != shared_logo_filename
    assert team_b_logo_path.endswith('.jpg')

    stored = _stored_files()
    assert shared_logo_filename in stored, 'Team A still references it -- the file must survive'
    assert team_b_logo_path in stored


def test_new_logo_write_failure_cleans_up_partial_file_and_preserves_old_logo(monkeypatch, tmp_path):
    """Simulates the write to disk failing partway through (e.g. disk
    full): the target file gets created but the write itself raises. The
    route must remove that partial file and leave the prior logo and
    team.logo_path completely untouched."""
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    first = _upload(client, 'logo.png', _png_bytes())
    assert first.status_code == 302
    original_logo_path = _team_logo_path(app)
    assert original_logo_path in _stored_files()

    import blueprints.admin as admin_module
    real_open = open

    class _PartialWriteThenFail:
        def __init__(self, handle):
            self._handle = handle

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self._handle.close()
            return False

        def write(self, data):
            # Actually write something first, so a real partial file lands
            # on disk -- then fail, exactly like a mid-write I/O error.
            self._handle.write(data[:1])
            self._handle.flush()
            raise OSError('simulated disk full')

    def failing_open(path, mode='r', *args, **kwargs):
        if mode == 'wb':
            return _PartialWriteThenFail(real_open(path, mode, *args, **kwargs))
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(admin_module, 'open', failing_open, raising=False)

    second = _upload(client, 'logo.jpg', _jpeg_bytes())
    assert second.status_code == 302

    assert _team_logo_path(app) == original_logo_path
    assert original_logo_path in _stored_files()
    # The partially written new .jpg must have been cleaned up -- only the
    # original logo remains on disk.
    assert _stored_files() == [original_logo_path]


def test_db_commit_failure_after_write_rolls_back_and_removes_new_file(monkeypatch, tmp_path):
    """The new logo is written to disk successfully, but the DB commit
    that would record it fails. The route must roll back, remove the
    already-written new file, and leave the prior logo and team.logo_path
    completely untouched."""
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach')

    first = _upload(client, 'logo.png', _png_bytes())
    assert first.status_code == 302
    original_logo_path = _team_logo_path(app)
    assert original_logo_path in _stored_files()

    from db import db

    def failing_commit():
        raise RuntimeError('simulated database outage')

    monkeypatch.setattr(db.session, 'commit', failing_commit)

    second = _upload(client, 'logo.jpg', _jpeg_bytes())
    assert second.status_code == 302

    assert _team_logo_path(app) == original_logo_path
    assert original_logo_path in _stored_files()
    assert _stored_files() == [original_logo_path]


# ---------------------------------------------------------------------------
# Authorization / team scoping
# ---------------------------------------------------------------------------

def test_head_coach_can_only_replace_the_session_scoped_teams_logo(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'coach', 'Head Coach', team_id=1)

    response = _upload(client, 'logo.png', _png_bytes())
    assert response.status_code == 302

    assert _team_logo_path(app, team_id=1) is not None
    assert _team_logo_path(app, team_id=2) is None


def test_assistant_coach_cannot_upload_a_logo(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'assistant', 'Assistant Coach')

    response = _upload(client, 'logo.png', _png_bytes())

    assert response.status_code == 302
    assert response.headers['Location'] in ('/', 'http://localhost/')
    assert _team_logo_path(app) is None
    assert _stored_files() == []


def test_game_changer_cannot_upload_a_logo(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path)
    client = app.test_client()
    _login(client, 'scorekeeper', 'Game Changer')

    response = _upload(client, 'logo.png', _png_bytes())

    # Game Changer is blocked at the app-wide "read-only role" guard
    # (security_guard.py) before it ever reaches upload_logo's own
    # @admin_required check, so this is a 403, not upload_logo's 302.
    assert response.status_code == 403
    assert _team_logo_path(app) is None
    assert _stored_files() == []
