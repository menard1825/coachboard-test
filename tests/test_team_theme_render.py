"""The page chrome renders the team theme the server computed.

base.html prints the team colors into a <style> block, so a malformed stored
value must never reach it, and the header must say which foreground it uses.
Team Settings warns, without blocking, when a color will read badly.
"""

import re

import pytest
from werkzeug.security import generate_password_hash


def _app(monkeypatch, primary):
    monkeypatch.setenv('SECRET_KEY', 'team-theme-render-test')
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
            Team(id=1, team_name='Theme Team', registration_code='theme-team',
                 age_group='12U', pitching_rule_set='MLB Pitch Smart', outfielder_count=3,
                 timezone='America/Indiana/Indianapolis', primary_color=primary,
                 secondary_color='#E5E7EB'),
            User(id=1, username='coach', full_name='Test Coach',
                 password_hash=generate_password_hash('password123')),
        ])
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=1, role='Head Coach', player_order=[]))
        db.session.commit()
    return app


def _client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(logged_in=True, username='coach', full_name='Test Coach',
                       team_id=1, role='Head Coach')
    return client


def _page(app, path='/pitching'):
    response = _client(app).get(path)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _root_vars(body):
    style = re.search(r'<style>\s*:root \{(.*?)\}', body, re.S).group(1)
    return dict(re.findall(r'(--[\w-]+):\s*([^;]+);', style))


def _navbar_classes(body):
    return re.search(r'<nav class="(navbar [^"]*)"', body).group(1).split()


@pytest.mark.parametrize('color,foreground,navbar', [
    ('#102A66', '#ffffff', 'navbar-dark'),
    ('#B91C1C', '#ffffff', 'navbar-dark'),
    ('#15803D', '#ffffff', 'navbar-dark'),
    ('#C9A227', '#172033', 'navbar-light'),
    ('#FFD600', '#172033', 'navbar-light'),
    ('#FFFFFF', '#172033', 'navbar-light'),
])
def test_header_uses_the_computed_foreground(monkeypatch, color, foreground, navbar):
    from team_theme import primary_text_color
    body = _page(_app(monkeypatch, color))
    root = _root_vars(body)
    assert root['--primary-color'] == color.lower()
    assert root['--on-primary-color'] == foreground
    assert root['--primary-text-color'] == primary_text_color(color)
    assert navbar in _navbar_classes(body)
    dark = foreground != '#ffffff'
    assert ('cb-on-primary-dark' in re.search(r'<html[^>]*>', body).group(0)) is dark


def test_red_team_marks_the_page_so_delete_buttons_stay_distinct(monkeypatch):
    red = _page(_app(monkeypatch, '#B91C1C'))
    assert 'cb-primary-near-danger' in re.search(r'<html[^>]*>', red).group(0)


def test_navy_team_does_not(monkeypatch):
    navy = _page(_app(monkeypatch, '#102A66'))
    assert 'cb-primary-near-danger' not in re.search(r'<html[^>]*>', navy).group(0)


def test_a_malformed_stored_color_never_reaches_the_style_block(monkeypatch):
    body = _page(_app(monkeypatch, 'red;} body{display:none} :root{--x:1'))
    assert 'display:none' not in body
    root = _root_vars(body)
    assert re.fullmatch(r'#[0-9a-f]{6}', root['--primary-color'])


def test_saving_an_invalid_color_keeps_the_previous_one(monkeypatch):
    app = _app(monkeypatch, '#102A66')
    client = _client(app)
    response = client.post('/admin/settings/update',
                           data={'primary_color': 'red;}body{display:none}',
                                 'secondary_color': '#fff'})
    assert response.status_code == 302
    from db import db
    from models import Team
    with app.app_context():
        team = db.session.get(Team, 1)
        assert team.primary_color.lower() == '#102a66'
        assert team.secondary_color == '#ffffff'


def test_team_settings_warns_about_hard_to_read_colors(monkeypatch):
    body = _page(_app(monkeypatch, '#FFD600'), '/admin/settings')
    warning = re.search(r'id="teamColorWarning"[^>]*>(.*?)</div>', body, re.S)
    assert warning and 'd-none' not in warning.group(0).split('>')[0]
    assert 'white' in warning.group(1).lower()


def test_team_settings_is_quiet_for_readable_colors(monkeypatch):
    body = _page(_app(monkeypatch, '#102A66'), '/admin/settings')
    warning = re.search(r'<div[^>]*id="teamColorWarning"[^>]*>', body)
    assert warning and 'd-none' in warning.group(0)


def test_team_settings_previews_the_color_as_text_on_white(monkeypatch):
    from team_theme import primary_text_color
    body = _page(_app(monkeypatch, '#FFD600'), '/admin/settings')
    sample = re.search(r'<[^>]*id="teamColorTextPreview"[^>]*>', body)
    assert sample and 'var(--primary-text-color)' in sample.group(0)
    assert primary_text_color('#FFD600') in body
