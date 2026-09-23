"""/pitching says how many rostered players it leaves out, and collapses the
availability summary to one line when every pitcher is eligible.

The page lists designated pitchers only: players whose Pitcher Role is not
"Not a Pitcher", plus anyone who has ever recorded throwing. Before this, a
12-player roster could show 8 names with nothing to say the other 4 exist.
"""

import re
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash


def _build_app(monkeypatch, players, *, competition_rule='MLB Pitch Smart',
               outings=(), role='Head Coach'):
    """players: [(name, pitcher_role)]; outings: [(name, days_ago, pitches)]."""
    monkeypatch.setenv('SECRET_KEY', 'pitching-roster-count-test')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from blueprints.fair_play import TeamPitchingSettings
    from db import db
    from models import PitchingOuting, Player, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        db.session.add_all([
            Team(id=1, team_name='Roster Count', registration_code='roster-count',
                 age_group='12U', pitching_rule_set='MLB Pitch Smart',
                 outfielder_count=3, timezone='America/Indiana/Indianapolis'),
            User(id=1, username='coach', full_name='Test Coach',
                 password_hash=generate_password_hash('password123')),
        ])
        db.session.flush()
        db.session.add(TeamMembership(user_id=1, team_id=1, role=role, player_order=[]))
        if competition_rule:
            db.session.add(TeamPitchingSettings(
                team_id=1, competition_default_rule=competition_rule,
                arm_care_rule_set='MLB Pitch Smart'))
        ids = {}
        for index, (name, pitcher_role) in enumerate(players, start=1):
            db.session.add(Player(id=index, name=name, number=str(index),
                                  team_id=1, pitcher_role=pitcher_role))
            ids[name] = index
        db.session.flush()
        for name, days_ago, pitches in outings:
            db.session.add(PitchingOuting(
                date=datetime.now() - timedelta(days=days_ago), opponent='Prior',
                pitches=pitches, innings=3.0, pitcher_type='Starter',
                outing_type='Game', team_id=1, player_id=ids[name]))
        db.session.commit()
    return app


def _get(app, role='Head Coach'):
    client = app.test_client()
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['full_name'] = 'Test Coach'
        session['team_id'] = 1
        session['role'] = role
    response = client.get('/pitching')
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _note(body):
    match = re.search(r'<div class="cb-pitch-roster-note" id="pitchRosterNote">(.*?)</div>',
                      body, re.S)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', match.group(1))).strip() if match else None


EIGHT_PITCHERS_FOUR_NOT = (
    [(f'Pitcher {n}', 'Starter' if n % 2 else 'Reliever') for n in range(1, 9)]
    + [(f'Fielder {n}', 'Not a Pitcher') for n in range(1, 5)]
)


# --- the roster count line -------------------------------------------------

def test_count_line_names_the_players_left_out(monkeypatch):
    body = _get(_build_app(monkeypatch, EIGHT_PITCHERS_FOUR_NOT))
    note = _note(body)
    assert note is not None, 'the roster count line is missing'
    assert '8 of 12 players' in note
    assert '4 marked Not a Pitcher' in note


def test_count_line_links_to_the_roster_for_coaches_who_can_edit_it(monkeypatch):
    body = _get(_build_app(monkeypatch, EIGHT_PITCHERS_FOUR_NOT))
    assert re.search(r'id="pitchRosterNote".*?href="/#roster"[^>]*>Edit roster</a>', body, re.S)


def test_count_line_has_no_edit_link_for_read_only_roles(monkeypatch):
    app = _build_app(monkeypatch, EIGHT_PITCHERS_FOUR_NOT, role='Game Changer')
    body = _get(app, role='Game Changer')
    assert '8 of 12 players' in (_note(body) or '')
    assert 'Edit roster' not in body


def test_not_a_pitcher_who_has_thrown_is_shown_and_not_counted_hidden(monkeypatch):
    """Recorded throwing keeps a player on the page whatever their role says."""
    app = _build_app(monkeypatch, EIGHT_PITCHERS_FOUR_NOT,
                     outings=[('Fielder 1', 20, 20)])
    note = _note(_get(app))
    assert '9 of 12 players' in note
    assert '3 marked Not a Pitcher' in note


def test_blank_pitcher_role_counts_as_a_pitcher(monkeypatch):
    """Only an explicit Not a Pitcher hides a player; an unset role does not."""
    players = [('Set Starter', 'Starter'), ('Unset Role', None), ('Fielder', 'Not a Pitcher')]
    note = _note(_get(_build_app(monkeypatch, players)))
    assert '2 of 3 players' in note
    assert '1 marked Not a Pitcher' in note


def test_no_count_line_when_nobody_is_left_out(monkeypatch):
    players = [(f'Pitcher {n}', 'Starter') for n in range(1, 6)]
    body = _get(_build_app(monkeypatch, players))
    assert 'pitchRosterNote' not in body


# --- the all-eligible summary ----------------------------------------------

def test_all_eligible_collapses_the_three_tiles_to_one_line(monkeypatch):
    body = _get(_build_app(monkeypatch, EIGHT_PITCHERS_FOUR_NOT))
    assert 'id="pitchAllReady"' in body
    assert 'All 8 pitchers eligible today' in body
    assert 'cb-pitch-counts' not in body, 'the three tiles still rendered'


def test_single_eligible_pitcher_reads_naturally(monkeypatch):
    body = _get(_build_app(monkeypatch, [('Only Arm', 'Starter')]))
    assert '1 pitcher eligible today' in body
    assert 'All 1 pitchers' not in body


def test_tiles_return_when_any_pitcher_is_unavailable(monkeypatch):
    app = _build_app(monkeypatch, EIGHT_PITCHERS_FOUR_NOT,
                     outings=[('Pitcher 1', 0, 85)])
    body = _get(app)
    assert 'cb-pitch-counts' in body
    assert 'id="pitchAllReady"' not in body
    unavailable = re.search(r'<span>Unavailable</span><strong>(\d+)</strong>', body)
    assert unavailable and int(unavailable.group(1)) >= 1


def test_tiles_return_when_competition_rules_are_not_selected(monkeypatch):
    """No team default means every pitcher needs review, so nothing is 'all ready'."""
    app = _build_app(monkeypatch, EIGHT_PITCHERS_FOUR_NOT, competition_rule=None)
    body = _get(app)
    assert 'cb-pitch-counts' in body
    assert 'id="pitchAllReady"' not in body


def test_no_summary_line_when_there_are_no_pitchers(monkeypatch):
    body = _get(_build_app(monkeypatch, [('Fielder', 'Not a Pitcher')]))
    assert 'id="pitchAllReady"' not in body
    assert 'No pitchers found' in body
    assert '0 of 1 player' in (_note(body) or '')


# --- the compact layouts rely on the roll-up instead -------------------------

def test_compact_layouts_hide_the_all_ready_line():
    """Phones and touch tablets already show 'Ready to pitch · N available'."""
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1]
           / 'static' / 'css' / 'pitching_dashboard_v3.css').read_text()
    rule = re.search(
        r'body\.cb-pitch-dugout-mobile \.cb-pitch-all-ready,\s*'
        r'body\.cb-pitch-dugout-tablet \.cb-pitch-all-ready\s*\{\s*display:\s*none;',
        css)
    assert rule, 'the all-ready line is not hidden in the compact layouts'
