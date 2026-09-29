"""Small production reliability fixes that must preserve existing team data."""
from io import BytesIO

from db import db
from models import Team
from test_production_rollover import env, headers, login


PNG = b'\x89PNG\r\n\x1a\n' + b'logo-image-data'


def upload(client, filename, content):
    return client.post('/admin/upload_logo',
                       data={'logo': (BytesIO(content), filename)},
                       headers=headers(client), follow_redirects=False)


def test_logo_failure_preserves_previous_file_and_database(env, tmp_path, monkeypatch):
    app, ids = env
    logo_dir = tmp_path / 'logos'
    logo_dir.mkdir()
    app.config['UPLOAD_FOLDER'] = str(logo_dir)
    old = logo_dir / 'old.png'
    old.write_bytes(PNG)
    with app.app_context():
        Team.query.filter_by(id=ids['old']).one().logo_path = old.name
        db.session.commit()

    client = login(app)
    assert upload(client, 'logo.svg', b'<svg><script>alert(1)</script></svg>').status_code == 302
    assert upload(client, 'new.png', b'<script>not an image</script>').status_code == 302
    assert upload(client, 'huge.png', PNG + b'x' * (5 * 1024 * 1024)).status_code == 302
    assert old.read_bytes() == PNG
    with app.app_context():
        assert Team.query.filter_by(id=ids['old']).one().logo_path == old.name
    assert list(logo_dir.iterdir()) == [old]

    original_commit = db.session.commit
    def fail_commit():
        raise RuntimeError('simulated database failure')
    monkeypatch.setattr(db.session, 'commit', fail_commit)
    assert upload(client, 'new.png', PNG).status_code == 302
    monkeypatch.setattr(db.session, 'commit', original_commit)
    assert old.read_bytes() == PNG
    assert list(logo_dir.iterdir()) == [old]
    with app.app_context():
        assert Team.query.filter_by(id=ids['old']).one().logo_path == old.name


def test_logo_replacement_keeps_file_shared_by_another_team(env, tmp_path):
    app, ids = env
    logo_dir = tmp_path / 'logos'
    logo_dir.mkdir()
    app.config['UPLOAD_FOLDER'] = str(logo_dir)
    old = logo_dir / 'shared.png'
    old.write_bytes(PNG)
    with app.app_context():
        Team.query.filter_by(id=ids['old']).one().logo_path = old.name
        Team.query.filter_by(id=ids['other']).one().logo_path = old.name
        db.session.commit()

    client = login(app)
    assert upload(client, 'new.png', PNG).status_code == 302
    with app.app_context():
        replacement = Team.query.filter_by(id=ids['old']).one().logo_path
        assert replacement != old.name
        assert Team.query.filter_by(id=ids['other']).one().logo_path == old.name
    assert old.read_bytes() == PNG
    assert (logo_dir / replacement).read_bytes() == PNG
