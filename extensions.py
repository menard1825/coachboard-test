from flask import has_request_context, session
from flask_socketio import SocketIO, join_room
from flask_migrate import Migrate
from db import db


class TeamSocketIO(SocketIO):
    def emit(self, event, *args, **kwargs):
        # Existing route emit calls are restricted to the active team's room.
        if has_request_context() and session.get('team_id') and not any(k in kwargs for k in ('to', 'room')):
            kwargs['to'] = f"team:{session['team_id']}"
        return super().emit(event, *args, **kwargs)


socketio = TeamSocketIO()
migrate = Migrate()


@socketio.on('connect')
def connect(auth=None):
    from models import User, TeamMembership
    if not session.get('logged_in') or not isinstance(auth, dict):
        return False
    if str(auth.get('team_id')) != str(session.get('team_id')):
        return False
    user = User.query.filter_by(username=session.get('username')).first()
    if not user or not db.session.get(TeamMembership, (user.id, session['team_id'])):
        return False
    join_room(f"team:{session['team_id']}")
    join_room(f"userteam:{user.id}:{session['team_id']}")


def disconnect_team_member(user_id, team_id):
    room = f'userteam:{user_id}:{team_id}'
    for sid, _ in list(socketio.server.manager.get_participants('/', room)):
        socketio.server.disconnect(sid, namespace='/')
