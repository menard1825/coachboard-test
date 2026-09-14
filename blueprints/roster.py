from flask import Blueprint, request, redirect, url_for, flash, session, jsonify
from models import (
    Game,
    LineupEntry,
    Player,
    PlayerGameAbsence,
    PlayerPitchingProfile,
    User,
    TeamMembership,
)
from db import db
from extensions import socketio
import json
from datetime import datetime

roster_bp = Blueprint('roster', __name__, template_folder='templates')

PITCHER_TRAITS = [
    'Power / Velocity',
    'Change of Pace',
    'Changes Speeds',
    'Command / Strike Thrower',
    'Breaking Ball',
    'Ground Ball',
    'Swing & Miss',
    'Deception',
    'Composed Under Pressure',
    'Holds Runners Well',
    'Gets Out of Trouble',
]


def get_player_order_as_list(player_order_data):
    """Safely returns player_order as a list, decoding from JSON if necessary."""
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


def _active_live_game_for_team(team_id):
    if not team_id:
        return None

    return db.session.query(Game).filter_by(
        team_id=team_id,
        is_live=True,
    ).order_by(Game.id.desc()).first()


def _live_roster_lock_message(game):
    opponent = str(getattr(game, 'opponent', '') or '').strip()

    if opponent:
        return (
            f'Roster changes are locked while the game vs {opponent} is live. '
            'End the live game before changing players or Guest status.'
        )

    return (
        'Roster changes are locked while a game is live. '
        'End the live game before changing players or Guest status.'
    )


def _mark_guest_out_for_future_games(player):
    """Guest players opt in per game; future games default them to Out."""
    if not player or not player.is_guest:
        return

    start_today = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    game_ids = [
        game_id
        for (game_id,) in db.session.query(Game.id).filter(
            Game.team_id == player.team_id,
            Game.date >= start_today,
            Game.is_live.is_(False),
        ).all()
    ]

    if not game_ids:
        return

    existing_game_ids = {
        game_id
        for (game_id,) in db.session.query(PlayerGameAbsence.game_id).filter(
            PlayerGameAbsence.team_id == player.team_id,
            PlayerGameAbsence.player_id == player.id,
            PlayerGameAbsence.game_id.in_(game_ids),
        ).all()
    }

    db.session.add_all([
        PlayerGameAbsence(
            player_id=player.id,
            game_id=game_id,
            team_id=player.team_id,
        )
        for game_id in game_ids
        if game_id not in existing_game_ids
    ])


@roster_bp.route('/add_player', methods=['POST'])
def add_player():
    live_game = _active_live_game_for_team(session.get('team_id'))
    if live_game:
        flash(_live_roster_lock_message(live_game), 'warning')
        return redirect(url_for('home', _anchor='roster'))

    name = request.form.get('name')
    if not name:
        flash('Player name is required.', 'danger')
        return redirect(url_for('home', _anchor='roster'))

    existing_player = db.session.query(Player).filter_by(name=name, team_id=session['team_id']).first()
    if existing_player:
        flash(f'A player with the name "{name}" already exists on this roster.', 'danger')
        return redirect(url_for('home', _anchor='roster'))

    new_player = Player(
        name=name,
        number=request.form.get('number'),
        position1=request.form.get('position1'),
        position2=request.form.get('position2'),
        position3=request.form.get('position3'),
        throws=request.form.get('throws'),
        bats=request.form.get('bats'),
        notes=request.form.get('notes'),
        pitcher_role=request.form.get('pitcher_role'),
        has_lessons="No",
        notes_author=session['username'],
        notes_timestamp=datetime.now(),
        is_guest=request.form.get('roster_status', 'regular') == 'guest',
        team_id=session['team_id']
    )
    db.session.add(new_player)
    db.session.flush()

    if new_player.is_guest:
        _mark_guest_out_for_future_games(new_player)

    for membership in db.session.query(TeamMembership).filter_by(team_id=session['team_id']).all():
        current_order = get_player_order_as_list(membership.player_order)
        if new_player.id not in current_order:
            current_order.append(new_player.id)
            membership.player_order = current_order

    db.session.commit()
    flash(f'Player "{name}" added successfully!', 'success')
    socketio.emit('data_updated', {'message': f'Player {name} added.'})

    if 'X-Requested-With' in request.headers and request.headers['X-Requested-With'] == 'XMLHttpRequest':
        return jsonify({'status': 'success'})

    return redirect(url_for('home', _anchor='roster'))


@roster_bp.route('/update_player_inline/<int:player_id>', methods=['POST'])
def update_player_inline(player_id):
    live_game = _active_live_game_for_team(session.get('team_id'))
    if live_game:
        return jsonify({
            'status': 'error',
            'code': 'live_roster_locked',
            'message': _live_roster_lock_message(live_game),
        }), 409

    player_to_edit = db.session.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
    if not player_to_edit:
        return jsonify({'status': 'error', 'message': 'Player not found.'}), 404

    original_name = player_to_edit.name
    new_name = request.form.get('name', original_name)
    if new_name != original_name and db.session.query(Player).filter_by(name=new_name, team_id=session['team_id']).first():
        return jsonify({'status': 'error', 'message': f'Player name "{new_name}" already exists.'}), 400

    was_guest = bool(player_to_edit.is_guest)
    if 'roster_status' in request.form:
        player_to_edit.is_guest = request.form.get('roster_status') == 'guest'
        if player_to_edit.is_guest and not was_guest:
            _mark_guest_out_for_future_games(player_to_edit)

    if new_name != original_name:
        linked_entries = db.session.query(LineupEntry).filter_by(player_id=player_to_edit.id).all()
        for entry in linked_entries:
            entry.player_name_snapshot = new_name
            legacy_names = list(entry.lineup.lineup_positions or [])
            entry.lineup.lineup_positions = [
                new_name if name == original_name else name
                for name in legacy_names
            ]

    player_to_edit.name = new_name
    player_to_edit.number = request.form.get('number', player_to_edit.number)
    player_to_edit.position1 = request.form.get('position1', player_to_edit.position1)
    player_to_edit.position2 = request.form.get('position2', player_to_edit.position2)
    player_to_edit.position3 = request.form.get('position3', player_to_edit.position3)
    player_to_edit.throws = request.form.get('throws', player_to_edit.throws)
    player_to_edit.bats = request.form.get('bats', player_to_edit.bats)
    player_to_edit.notes = request.form.get('notes', player_to_edit.notes)
    player_to_edit.pitcher_role = request.form.get('pitcher_role', player_to_edit.pitcher_role)
    player_to_edit.notes_author = session['username']
    player_to_edit.notes_timestamp = datetime.now()

    db.session.commit()
    socketio.emit('data_updated', {'message': f'Player {new_name} updated.'})
    return jsonify({'status': 'success', 'message': f'Player "{new_name}" updated successfully!'})


@roster_bp.route('/api/roster-pitching-profiles')
def roster_pitching_profiles():
    if 'logged_in' not in session or not session.get('team_id'):
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    profiles = db.session.query(PlayerPitchingProfile).filter_by(team_id=session['team_id']).all()
    return jsonify({
        'status': 'success',
        'team_id': session['team_id'],
        'traits': list(PITCHER_TRAITS),
        'profiles': {
            str(profile.player_id): list(profile.traits or [])
            for profile in profiles
        },
    })


@roster_bp.route('/update_pitching_profile/<int:player_id>', methods=['POST'])
def update_pitching_profile(player_id):
    if 'logged_in' not in session or not session.get('team_id'):
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    player = db.session.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
    if not player:
        return jsonify({'status': 'error', 'message': 'Player not found.'}), 404

    data = request.get_json(silent=True) or {}
    requested_traits = data.get('traits') or []
    if not isinstance(requested_traits, list):
        return jsonify({'status': 'error', 'message': 'Traits must be a list.'}), 400

    allowed = set(PITCHER_TRAITS)
    traits = []
    for raw_trait in requested_traits:
        trait = str(raw_trait or '').strip()
        if trait in allowed and trait not in traits:
            traits.append(trait)

    profile = db.session.query(PlayerPitchingProfile).filter_by(
        player_id=player_id,
        team_id=session['team_id'],
    ).first()
    if not profile:
        profile = PlayerPitchingProfile(player_id=player_id, team_id=session['team_id'])
        db.session.add(profile)

    profile.traits = traits
    db.session.commit()

    # A profile edit should synchronize only the affected profile. The old
    # generic data_updated broadcast makes every connected dashboard re-fetch
    # and redraw all application data.
    socketio.emit('pitching_profile_update', {
        'team_id': session['team_id'],
        'player_id': player.id,
        'traits': traits,
    })

    return jsonify({
        'status': 'success',
        'team_id': session['team_id'],
        'player_id': player.id,
        'traits': traits,
    })


@roster_bp.route('/delete_player/<int:player_id>')
def delete_player(player_id):
    live_game = _active_live_game_for_team(session.get('team_id'))
    if live_game:
        flash(_live_roster_lock_message(live_game), 'warning')
        return redirect(
            url_for(
                'home',
                _anchor=request.args.get(
                    'active_tab',
                    'roster',
                ).lstrip('#'),
            )
        )

    player_to_delete = db.session.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
    if player_to_delete:
        player_name = player_to_delete.name
        player_id_to_delete = player_to_delete.id
        db.session.delete(player_to_delete)

        for membership in db.session.query(TeamMembership).filter_by(team_id=session['team_id']).all():
            current_order = get_player_order_as_list(membership.player_order)
            updated_order = [pid for pid in current_order if pid != player_id_to_delete]
            membership.player_order = updated_order

        if 'player_order' in session:
            session_order = get_player_order_as_list(session['player_order'])
            session['player_order'] = [pid for pid in session_order if pid != player_id_to_delete]
            session.modified = True

        db.session.commit()
        flash(f'Player "{player_name}" removed successfully!', 'success')
        socketio.emit('data_updated', {'message': f'Player {player_name} deleted.'})
    else:
        flash('Player not found.', 'danger')
    return redirect(url_for('home', _anchor=request.args.get('active_tab', 'roster').lstrip('#')))


@roster_bp.route('/save_player_order', methods=['POST'])
def save_player_order():
    live_game = _active_live_game_for_team(session.get('team_id'))
    if live_game:
        return jsonify({
            'status': 'error',
            'code': 'live_roster_locked',
            'message': _live_roster_lock_message(live_game),
        }), 409

    user = db.session.query(User).filter_by(username=session['username']).first()
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    membership = db.session.query(TeamMembership).filter_by(user_id=user.id, team_id=session['team_id']).first()
    if not membership:
        return jsonify({'status': 'error', 'message': 'Membership not found'}), 404

    new_order = request.json.get('player_order')
    if not isinstance(new_order, list):
        return jsonify({'status': 'error', 'message': 'Invalid order format'}), 400

    membership.player_order = new_order
    session['player_order'] = new_order
    session.modified = True
    db.session.commit()

    socketio.emit('data_updated', {'message': 'Player order saved.'})
    return jsonify({'status': 'success', 'message': 'Player order saved.'})
