"""Guided setup for brand-new teams and season rollovers.

Backward compatibility is intentional: a team with no TeamSetupState row is a
legacy/existing team and is treated as already set up. Only teams created after
this feature and teams created by the season-rollover workflow receive a row.
"""

from datetime import datetime

from flask import current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func

from db import db
from models import Game, Player, PracticePlan, Team, TeamMembership
from blueprints.team_management import team_management_bp


HEAD_COACH_ROLES = {'Head Coach', 'Super Admin'}
NEW_TEAM_SETUP = 'new_team'
SEASON_SETUP = 'season_rollover'


class TeamSetupState(db.Model):
    __tablename__ = 'team_setup_states'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False, unique=True)
    setup_type = db.Column(db.String(32), nullable=False)
    completed_steps = db.Column(db.JSON, nullable=False, default=list)
    dismissed = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


NEW_TEAM_STEPS = [
    {
        'key': 'team_settings',
        'title': 'Confirm Team Settings',
        'detail': 'Review team name, age group, timezone, lineup format, and field setup.',
        'href': '/admin/settings',
        'action': 'Review settings',
        'manual': True,
        'required': True,
    },
    {
        'key': 'pitching',
        'title': 'Review Pitching Preferences',
        'detail': 'Choose the competition-rule default and separate arm-care guidance.',
        'href': '/admin/settings#pitching-rules-settings',
        'action': 'Review pitching',
        'manual': True,
        'required': True,
    },
    {
        'key': 'playing_time',
        'title': 'Choose Playing-Time Assistance',
        'detail': 'Decide whether CoachBoard should keep this off, track usage, or show Fair Play guidance.',
        'href': '/admin/settings',
        'action': 'Review playing time',
        'manual': True,
        'required': True,
    },
    {
        'key': 'roster',
        'title': 'Build Your Roster',
        'detail': 'Add the players you will use for lineups, defense, pitching, and practice.',
        'href': '/#roster',
        'action': 'Open roster',
        'manual': False,
        'required': True,
    },
    {
        'key': 'coaches',
        'title': 'Confirm Coaches & Roles',
        'detail': 'Invite staff or confirm that you are coaching this team on your own.',
        'href': '/admin/users',
        'action': 'Review coaches',
        'manual': True,
        'required': True,
    },
    {
        'key': 'first_activity',
        'title': 'Create Your First Game or Practice',
        'detail': 'Add the first scheduled team activity so CoachBoard can start organizing the week.',
        'href': '/game-day',
        'action': 'Open Game Day',
        'manual': False,
        'required': True,
    },
]


SEASON_STEPS = [
    {
        'key': 'team_settings',
        'title': 'Confirm Season Details',
        'detail': 'Review the new team name, age group, timezone, and lineup format.',
        'href': '/admin/settings',
        'action': 'Review settings',
        'manual': True,
        'required': True,
    },
    {
        'key': 'roster_review',
        'title': 'Review Roster Carryover',
        'detail': 'Confirm returning players and update jersey numbers, positions, or new additions.',
        'href': '/#roster',
        'action': 'Review roster',
        'manual': True,
        'required': True,
    },
    {
        'key': 'coaches',
        'title': 'Confirm Coaches & Roles',
        'detail': 'Make sure the right coaches carried into the new season with the right access.',
        'href': '/admin/users',
        'action': 'Review coaches',
        'manual': True,
        'required': True,
    },
    {
        'key': 'pitching',
        'title': 'Review Pitching Preferences',
        'detail': 'Confirm competition rules and arm-care guidance for the new age level or season.',
        'href': '/admin/settings#pitching-rules-settings',
        'action': 'Review pitching',
        'manual': True,
        'required': True,
    },
    {
        'key': 'playing_time',
        'title': 'Review Playing-Time Assistance',
        'detail': 'Confirm whether playing-time tracking or Fair Play guidance still fits this team.',
        'href': '/admin/settings',
        'action': 'Review playing time',
        'manual': True,
        'required': True,
    },
    {
        'key': 'first_activity',
        'title': 'Create the First Game or Practice',
        'detail': 'Add the first activity for the new season.',
        'href': '/game-day',
        'action': 'Open Game Day',
        'manual': False,
        'required': True,
    },
    {
        'key': 'templates',
        'title': 'Review Lineup & Defense Templates',
        'detail': 'Optional: update reusable templates if personnel or roles changed.',
        'href': '/#lineups',
        'action': 'Review templates',
        'manual': True,
        'required': False,
    },
]


def _can_manage_setup():
    return session.get('logged_in') and session.get('role') in HEAD_COACH_ROLES and session.get('team_id')


def _setup_state(team_id=None):
    team_id = team_id or session.get('team_id')
    if not team_id:
        return None
    return db.session.query(TeamSetupState).filter_by(team_id=team_id).first()


def _steps_for(state):
    if not state:
        return []
    return SEASON_STEPS if state.setup_type == SEASON_SETUP else NEW_TEAM_STEPS


def _counts(team_id):
    return {
        'players': db.session.query(Player).filter_by(team_id=team_id).count(),
        'memberships': db.session.query(TeamMembership).filter_by(team_id=team_id).count(),
        'games': db.session.query(Game).filter_by(team_id=team_id).count(),
        'practices': db.session.query(PracticePlan).filter_by(team_id=team_id).count(),
    }


def _step_complete(step, state, counts):
    completed = set(state.completed_steps or [])
    key = step['key']
    if state.completed_at and step.get('required', True):
        return True
    if key == 'roster':
        return counts['players'] > 0
    if key == 'first_activity':
        return counts['games'] > 0 or counts['practices'] > 0
    if key == 'coaches' and counts['memberships'] > 1:
        return True
    return key in completed


def _payload(state=None):
    if not _can_manage_setup():
        return {
            'active': False,
            'legacy': False,
            'can_manage': False,
            'show_home': False,
            'steps': [],
        }

    team_id = session['team_id']
    state = state or _setup_state(team_id)
    if not state:
        # Critical backward-compatibility rule: missing row means the team
        # predates guided setup and therefore requires no onboarding.
        return {
            'active': False,
            'legacy': True,
            'can_manage': True,
            'show_home': False,
            'setup_type': 'existing',
            'title': 'Team Setup',
            'subtitle': 'This team was already set up before guided setup was added. Nothing is required.',
            'completed': 0,
            'total': 0,
            'percent': 100,
            'steps': [],
        }

    counts = _counts(team_id)
    steps = []
    for definition in _steps_for(state):
        item = dict(definition)
        item['complete'] = _step_complete(item, state, counts)
        steps.append(item)

    required = [step for step in steps if step.get('required', True)]
    completed_count = sum(1 for step in required if step['complete'])
    total = len(required)
    all_complete = total > 0 and completed_count == total

    if all_complete and state.completed_at is None:
        state.completed_at = datetime.utcnow()
        state.dismissed = False
        db.session.commit()
    elif state.completed_at is not None:
        all_complete = True
        completed_count = total
        for step in steps:
            if step.get('required', True):
                step['complete'] = True

    is_season = state.setup_type == SEASON_SETUP
    return {
        'active': True,
        'legacy': False,
        'can_manage': True,
        'setup_type': state.setup_type,
        'title': 'Season Setup' if is_season else 'Finish Team Setup',
        'subtitle': (
            'Review the items that can change from one season to the next.'
            if is_season else
            'Get the team ready for games, practices, pitching, and staff collaboration.'
        ),
        'completed': completed_count,
        'total': total,
        'percent': round((completed_count / total) * 100) if total else 100,
        'complete': all_complete,
        'dismissed': bool(state.dismissed),
        'show_home': not all_complete and not state.dismissed,
        'steps': steps,
        'counts': counts,
    }


def _ensure_state(team_id, setup_type):
    if not team_id:
        return None
    existing = _setup_state(team_id)
    if existing:
        return existing
    state = TeamSetupState(
        team_id=team_id,
        setup_type=setup_type,
        completed_steps=[],
        dismissed=False,
    )
    db.session.add(state)
    return state


@team_management_bp.before_app_request
def capture_team_creation_for_guided_setup():
    if request.method != 'POST':
        return None

    if request.endpoint == 'admin.create_team':
        team_name = str(request.form.get('team_name') or '').strip()
        if not team_name:
            return None
        exists = db.session.query(Team).filter(func.lower(Team.team_name) == team_name.lower()).first()
        if not exists:
            g.cb_setup_new_team_name = team_name

    elif request.endpoint == 'admin.rollover_season':
        g.cb_setup_previous_team_id = session.get('team_id')

    return None


@team_management_bp.after_app_request
def record_guided_setup_for_created_team(response):
    if response.status_code < 300 or response.status_code >= 400:
        return response

    try:
        changed = False
        if request.endpoint == 'admin.create_team':
            team_name = getattr(g, 'cb_setup_new_team_name', None)
            if team_name:
                team = db.session.query(Team).filter(func.lower(Team.team_name) == team_name.lower()).first()
                if team and not _setup_state(team.id):
                    _ensure_state(team.id, NEW_TEAM_SETUP)
                    changed = True

        elif request.endpoint == 'admin.rollover_season':
            previous_team_id = getattr(g, 'cb_setup_previous_team_id', None)
            new_team_id = session.get('team_id')
            if new_team_id and new_team_id != previous_team_id and db.session.get(Team, new_team_id):
                if not _setup_state(new_team_id):
                    _ensure_state(new_team_id, SEASON_SETUP)
                    changed = True

        if changed:
            db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Unable to initialize guided team setup state.')

    return response


@team_management_bp.route('/api/getting-started', methods=['GET'])
def getting_started_api():
    if not _can_manage_setup():
        return jsonify({'active': False, 'can_manage': False, 'show_home': False, 'steps': []})
    return jsonify(_payload())


@team_management_bp.route('/getting-started', methods=['GET'])
def getting_started_page():
    if not _can_manage_setup():
        flash('Getting Started is available to the Head Coach and Super Admin.', 'warning')
        return redirect(url_for('home'))
    return render_template('getting_started.html', setup=_payload())


@team_management_bp.route('/getting-started/step/<step_key>', methods=['POST'])
def update_getting_started_step(step_key):
    if not _can_manage_setup():
        return redirect(url_for('home'))

    state = _setup_state()
    if not state:
        return redirect(url_for('team_management.getting_started_page'))

    definitions = {step['key']: step for step in _steps_for(state)}
    step = definitions.get(step_key)
    if not step or not step.get('manual'):
        flash('That setup item updates automatically.', 'info')
        return redirect(url_for('team_management.getting_started_page'))

    completed = set(state.completed_steps or [])
    mark_complete = str(request.form.get('complete', '1')).lower() not in {'0', 'false', 'no'}
    if mark_complete:
        completed.add(step_key)
    else:
        completed.discard(step_key)
        state.completed_at = None
    state.completed_steps = sorted(completed)
    state.dismissed = False
    db.session.commit()

    # Recalculate auto + manual progress and complete the setup if this was the
    # final required item.
    _payload(state)
    return redirect(url_for('team_management.getting_started_page'))


@team_management_bp.route('/getting-started/dismiss', methods=['POST'])
def dismiss_getting_started():
    if not _can_manage_setup():
        return redirect(url_for('home'))
    state = _setup_state()
    if state and state.completed_at is None:
        state.dismissed = True
        db.session.commit()
    return redirect(url_for('home', _anchor='overview'))


@team_management_bp.route('/getting-started/show', methods=['POST'])
def show_getting_started_on_home():
    if not _can_manage_setup():
        return redirect(url_for('home'))
    state = _setup_state()
    if state and state.completed_at is None:
        state.dismissed = False
        db.session.commit()
    return redirect(url_for('team_management.getting_started_page'))
