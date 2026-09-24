"""CoachBoard installs to a home screen with its own icon and name.

Android reads the web app manifest; iOS mostly ignores it and reads
apple-touch-icon and the apple-mobile-web-app-* tags instead. Both come from
one partial, so the login pages (auth_base.html) and the signed-in pages
(base.html) carry the same metadata. There is no service worker and nothing
is cached offline.
"""

import io
import json
import math
from html.parser import HTMLParser

import pytest
from PIL import Image
from werkzeug.security import generate_password_hash


NAVY = (0x17, 0x20, 0x33)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from models import Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(id=1, team_name='Install Team', registration_code='install-code', age_group='9U',
                 pitching_rule_set='MLB Pitch Smart', outfielder_count=3,
                 timezone='America/Indiana/Indianapolis'),
            User(id=1, username='coach', full_name='Test Coach',
                 password_hash=generate_password_hash('password123')),
        ])
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=1, role='Head Coach', player_order=[]))
        db.session.commit()
    return app


def _signed_in(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(logged_in=True, username='coach', full_name='Test Coach', team_id=1, role='Head Coach')
    return client


class _Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.metas, self._in_head = [], {}, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'head':
            self._in_head = True
        elif self._in_head and tag == 'link':
            self.links.append(attrs)
        elif self._in_head and tag == 'meta' and attrs.get('name'):
            self.metas[attrs['name']] = attrs.get('content')

    def handle_endtag(self, tag):
        if tag == 'head':
            self._in_head = False


def _head(response):
    assert response.status_code == 200, response.status_code
    parser = _Head()
    parser.feed(response.get_data(as_text=True))
    return parser


def _manifest(client):
    response = client.get('/manifest.json')
    assert response.status_code == 200
    assert response.mimetype in ('application/manifest+json', 'application/json')
    return json.loads(response.get_data(as_text=True))


def _png(client, src):
    response = client.get(src)
    assert response.status_code == 200, src
    image = Image.open(io.BytesIO(response.data))
    assert image.format == 'PNG', src
    return image.convert('RGBA')


# --- manifest ---------------------------------------------------------------------

def test_manifest_is_public_and_names_the_installed_app(app):
    manifest = _manifest(app.test_client())          # not signed in
    assert manifest['name'] == 'CoachBoard'
    assert manifest['short_name'] == 'CoachBoard'
    assert manifest['id'] == '/'
    assert manifest['start_url'] == '/'
    assert manifest['scope'] == '/'
    assert manifest['display'] == 'standalone'
    assert manifest['theme_color'].lower() == '#172033'
    assert manifest['background_color'].lower() == '#f3f5f8'   # the page background (--cb-bg)
    assert 'serviceworker' not in manifest


def test_manifest_icons_exist_at_their_declared_sizes(app):
    client = app.test_client()
    icons = _manifest(client)['icons']
    by_purpose = {}
    for icon in icons:
        assert icon['type'] == 'image/png'
        width, height = (int(n) for n in icon['sizes'].split('x'))
        image = _png(client, icon['src'])
        assert image.size == (width, height), icon
        for purpose in icon.get('purpose', 'any').split():
            by_purpose.setdefault(purpose, set()).add(width)
    # Android needs 192 and 512 for the launcher and splash screen, and a
    # maskable icon so adaptive (round, squircle) launchers do not shrink it
    # onto a white plate.
    assert {192, 512} <= by_purpose['any'], by_purpose
    assert max(by_purpose['maskable']) >= 512, by_purpose


def test_maskable_icon_is_full_bleed_with_the_mark_inside_the_safe_zone(app):
    client = app.test_client()
    icon = next(i for i in _manifest(client)['icons'] if 'maskable' in i.get('purpose', ''))
    image = _png(client, icon['src'])
    size = image.width
    pixels = image.load()
    # Full bleed: every corner is opaque navy, so any launcher mask shape is filled.
    for x, y in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
        assert pixels[x, y][3] == 255 and pixels[x, y][:3] == NAVY, (x, y, pixels[x, y])
    # The white mark stays inside the 80% safe-zone circle every mask keeps.
    centre, safe = (size - 1) / 2, 0.4 * size
    for y in range(0, size, 2):
        for x in range(0, size, 2):
            r, g, b, _ = pixels[x, y]
            if min(r, g, b) > 200:
                assert math.hypot(x - centre, y - centre) <= safe, (x, y)


def test_apple_touch_icon_is_opaque_180_square(app):
    client = app.test_client()
    link = next(l for l in _head(client.get('/login')).links if l.get('rel') == 'apple-touch-icon')
    image = _png(client, link['href'].split('?')[0])
    assert image.size == (180, 180)
    # iOS draws its own rounded corners and fills transparency with black.
    assert image.getextrema()[3] == (255, 255)
    assert image.getpixel((0, 0))[:3] == NAVY


# --- head metadata ----------------------------------------------------------------

@pytest.mark.parametrize('path', ['/login', '/register', '/forgot_password', '/'])
def test_install_metadata_is_on_login_and_signed_in_pages(app, path):
    client = _signed_in(app) if path == '/' else app.test_client()
    head = _head(client.get(path))

    rels = {link.get('rel'): link for link in head.links}
    assert rels['manifest']['href'] == '/manifest.json'
    assert rels['apple-touch-icon']['href'].split('?')[0] == '/static/icons/apple-touch-icon.png'
    assert rels['apple-touch-icon'].get('sizes') == '180x180'

    assert head.metas.get('apple-mobile-web-app-title') == 'CoachBoard'
    assert head.metas.get('application-name') == 'CoachBoard'
    assert head.metas.get('apple-mobile-web-app-capable') == 'yes'
    assert head.metas.get('mobile-web-app-capable') == 'yes'
    # The default status bar keeps the page below it; no top inset handling needed.
    assert head.metas.get('apple-mobile-web-app-status-bar-style') == 'default'
    assert head.metas.get('theme-color', '').lower() == '#172033'


def test_no_service_worker_is_registered_or_served(app):
    client = _signed_in(app)
    html = client.get('/').get_data(as_text=True) + app.test_client().get('/login').get_data(as_text=True)
    assert 'serviceWorker.register' not in html
    assert client.get('/service-worker.js').status_code == 404
