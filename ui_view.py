"""A coach's own screen view: Classic or Updated.

One application, one database, one set of rules. The view only chooses how
the planning screens are presented; every save, check and permission is the
same in both. The choice belongs to one coach on one team (its
``TeamMembership.ui_view``), so it follows that coach to every device and
never changes what another coach sees.

* Updated is the default: ``ui_view`` NULL, or anything but ``'classic'``.
* A live game always shows the Updated screens. There is no Classic live
  screen; a coach who prefers Classic plans in Classic and runs the game in
  the same live screens, with the same protections, as everyone else.
* Until the Classic screens are ready, the choice is offered only where
  ``COACHBOARD_CLASSIC_VIEW`` allows it:

  ``off`` (the default)  nobody is offered it, and a stored choice is ignored;
  ``super-admin``        Super Admins only, to try it out;
  ``all``                every coach.
"""

from flask import Blueprint, current_app, g, jsonify, request, session
from sqlalchemy import func

from db import db
from models import Game, TeamMembership, User
from permissions import GAME_CHANGER, SUPER_ADMIN


CLASSIC = 'classic'
UPDATED = 'updated'
VIEWS = (UPDATED, CLASSIC)

CONFIG_KEY = 'COACHBOARD_CLASSIC_VIEW'
ACCESS_LEVELS = ('off', 'super-admin', 'all')


ui_view_bp = Blueprint('ui_view', __name__)


def access_level(value):
    """The configured access level; anything unrecognised is ``off``."""
    value = str(value or '').strip().lower()
    return value if value in ACCESS_LEVELS else 'off'


def classic_offered(role):
    """May a coach with this role choose the Classic view on this server?"""
    level = access_level(current_app.config.get(CONFIG_KEY))
    if role == GAME_CHANGER:
        return False
    if level == 'all':
        return True
    return level == 'super-admin' and role == SUPER_ADMIN


def chosen_view(stored, role):
    """What this coach has chosen, as far as this server offers it."""
    return CLASSIC if stored == CLASSIC and classic_offered(role) else UPDATED


def page_view(choice):
    """The view this page is shown in: the coach's choice, except that a live
    game is always Updated. Reads the game the view already loaded (identity
    map), so a coach on the default view costs no query at all."""
    if choice != CLASSIC:
        return UPDATED
    if request.endpoint == 'gameday.game_management':
        game_id = (request.view_args or {}).get('game_id')
        game = db.session.get(Game, game_id) if game_id else None
        if game is not None and game.is_live:
            return UPDATED
    return choice


def template_context(stored):
    role = session.get('role')
    choice = chosen_view(stored, role)
    return {
        'cb_view_offered': classic_offered(role),
        'cb_view_choice': choice,
        'cb_view': page_view(choice),
    }


def _own_membership():
    username = session.get('username')
    team_id = session.get('team_id')
    if not session.get('logged_in') or not username or not team_id:
        return None
    # The security guard has already found this request's own membership.
    cached = getattr(g, 'coachboard_membership', None)
    if cached is not None and cached.team_id == team_id and cached.user is not None \
            and cached.user.username.lower() == str(username).lower():
        return cached
    user = db.session.query(User).filter(func.lower(User.username) == func.lower(username)).first()
    if not user:
        return None
    return db.session.query(TeamMembership).filter_by(user_id=user.id, team_id=team_id).first()


@ui_view_bp.route('/api/account/view', methods=['POST'])
def set_view():
    """Set the signed-in coach's view for the team they are signed in to.

    Only ever their own membership row: no user or team id is accepted from
    the request. JSON only, so a cross-site form cannot send it (and the
    security guard already refuses cross-site writes)."""
    if not request.is_json:
        return jsonify({'status': 'error', 'message': 'Send the view as JSON.'}), 415
    membership = _own_membership()
    if membership is None:
        return jsonify({'status': 'error', 'message': 'Sign in to a team first.'}), 401
    view = str((request.get_json(silent=True) or {}).get('view') or '').strip().lower()
    if view not in VIEWS:
        return jsonify({'status': 'error', 'message': 'Choose Updated or Classic.'}), 400
    if view == CLASSIC and not classic_offered(session.get('role')):
        return jsonify({'status': 'error', 'message': 'The Classic view is not available yet.'}), 403
    membership.ui_view = CLASSIC if view == CLASSIC else None
    db.session.commit()
    return jsonify({'status': 'success', 'view': view})
