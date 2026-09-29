"""Small production workflow for creating a new team without erasing history."""
import secrets
import uuid
from flask import Blueprint, request, session, g, render_template, redirect, url_for, flash, abort
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from db import db
from extensions import socketio
from models import Team, Player, TeamMembership, Sign
from team_access import activate_team, membership_for, team_members, error
from utils import PITCHING_RULES

seasons_bp = Blueprint('seasons', __name__, url_prefix='/teams')


def require_manager():
    if session.get('role') not in ('Head Coach', 'Super Admin'):
        abort(403)


@seasons_bp.route('/')
def index():
    memberships = TeamMembership.query.filter_by(user_id=g.current_user.id).all()
    session.setdefault('rollover_nonce', secrets.token_hex(32))
    return render_template('seasons.html', memberships=memberships,
        players=Player.query.filter_by(team_id=g.current_team.id, is_active=True).order_by(Player.name).all(),
        archived_players=Player.query.filter_by(team_id=g.current_team.id, is_active=False).order_by(Player.name).all(),
        coaches=team_members(g.current_team.id),
        age_groups=[a for a in PITCHING_RULES['MLB Pitch Smart'] if a != 'default'],
        rollover_nonce=session['rollover_nonce'])


@seasons_bp.route('/switch', methods=['POST'])
def switch_team():
    target_id = request.form.get('team_id', type=int)
    membership = membership_for(g.current_user.id, target_id)
    if not membership:
        abort(403)
    activate_team(g.current_user, membership)
    return redirect(url_for('home'))


@seasons_bp.route('/rollover', methods=['POST'])
def rollover():
    require_manager()
    key = request.form.get('rollover_nonce', '')
    if not key or key != session.get('rollover_nonce'):
        return error('This rollover form has already been used or expired. Open Teams & Seasons again.', 409)
    # Unique key also protects against simultaneous submissions from two tabs.
    if Team.query.filter_by(rollover_key=key).first():
        return error('This rollover has already been created. Open Teams & Seasons.', 409)
    name = request.form.get('team_name', '').strip()
    season = request.form.get('season_label', '').strip()
    age = request.form.get('age_group', '')
    if not name or len(name) > 120 or not season or len(season) > 80 or age not in PITCHING_RULES['MLB Pitch Smart'] or age == 'default':
        return error('Enter a team name, season, and valid age group.', 400)
    if Team.query.filter(func.lower(Team.team_name) == name.lower()).first():
        return error('That team name already exists. Include the season in the name.', 400)
    try:
        player_ids = {int(v) for v in request.form.getlist('players')}
        coach_ids = {int(v) for v in request.form.getlist('coaches')}
    except ValueError:
        return error('Invalid roster or coach selection.', 400)
    players = Player.query.filter_by(team_id=g.current_team.id, is_active=True).all()
    coaches = team_members(g.current_team.id)
    if not player_ids.issubset({p.id for p in players}) or not coach_ids.issubset({m.user_id for m in coaches}):
        return error('Only players and coaches on the current team can carry over.', 400)
    source = g.current_team
    target = Team(team_name=name, season_label=season, age_group=age,
        registration_code=secrets.token_urlsafe(12), rollover_key=key,
        primary_color=source.primary_color, secondary_color=source.secondary_color,
        display_coach_names=source.display_coach_names,
        pitching_rule_set=source.pitching_rule_set, outfielder_count=source.outfielder_count)
    # Logos are not shared: the legacy logo uploader deletes the previous file.
    fields = ('name', 'number', 'position1', 'position2', 'position3', 'throws', 'bats',
              'notes', 'pitcher_role', 'has_lessons', 'lesson_focus', 'notes_author', 'notes_timestamp')
    try:
        db.session.add(target)
        db.session.flush()
        new_names = []
        for player in players:
            if player.id not in player_ids:
                continue
            db.session.refresh(player)
            player.pitching_identity = player.pitching_identity or str(uuid.uuid4())
            copied = Player(team_id=target.id, pitching_identity=player.pitching_identity,
                            **{f: getattr(player, f) for f in fields})
            db.session.add(copied)
            new_names.append(player.name)
        coach_ids.add(g.current_user.id)
        for member in coaches:
            if member.user_id in coach_ids:
                role = 'Head Coach' if member.user_id == g.current_user.id else member.role
                if role == 'Super Admin':
                    role = 'Head Coach'
                db.session.add(TeamMembership(user_id=member.user_id, team_id=target.id,
                                              role=role, player_order=new_names))
        if request.form.get('copy_signs') == 'yes':
            for sign in Sign.query.filter_by(team_id=source.id).all():
                db.session.add(Sign(team_id=target.id, name=sign.name, indicator=sign.indicator))
        if request.form.get('archive_source') == 'yes':
            source.is_archived = True
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error('This rollover was already submitted. Open Teams & Seasons to check the new team.', 409)
    activate_team(g.current_user, membership_for(g.current_user.id, target.id))
    flash('New team created. Your previous team history is preserved. Recent pitching workload follows returning players.', 'success')
    return redirect(url_for('seasons.index'))


@seasons_bp.route('/archive', methods=['POST'])
def archive_team():
    require_manager()
    if request.form.get('confirmation') != g.current_team.team_name:
        return error('Type the current team name to confirm.', 400)
    g.current_team.is_archived = not g.current_team.is_archived
    db.session.commit()
    flash('Team restored.' if not g.current_team.is_archived else 'Team archived. Its history is available read-only.', 'success')
    return redirect(url_for('seasons.index'))


@seasons_bp.route('/players/<int:player_id>/restore', methods=['POST'])
def restore_player(player_id):
    require_manager()
    player = Player.query.filter_by(id=player_id, team_id=g.current_team.id).first_or_404()
    player.is_active = True
    db.session.commit()
    socketio.emit('data_updated', {'message': 'Player restored.'})
    flash(f'{player.name} restored to the active roster.', 'success')
    return redirect(url_for('seasons.index'))
