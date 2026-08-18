"""Disposable CoachBoard server used only by the Playwright test suite."""

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import eventlet

eventlet.monkey_patch()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from db import db
from extensions import socketio
from models import Game, Player, Rotation, Team, TeamMembership, User
from werkzeug.security import generate_password_hash


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'


def seed_database(app):
    with app.app_context():
        db.create_all()

        team = Team(
            id=1,
            team_name='Playwright Prospects',
            registration_code='playwright-team',
            primary_color='#102A66',
            secondary_color='#E5E7EB',
            age_group='12U',
            pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3,
            timezone='America/Indiana/Indianapolis',
        )
        other_team = Team(
            id=2,
            team_name='Other Team',
            registration_code='other-team',
            age_group='12U',
            pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3,
            timezone='America/Indiana/Indianapolis',
        )
        user = User(
            id=1,
            username=TEST_USERNAME,
            email='playwright@example.test',
            full_name='Playwright Coach',
            password_hash=generate_password_hash(TEST_PASSWORD),
        )
        membership = TeamMembership(
            user_id=1,
            team_id=1,
            role='Head Coach',
            player_order=[],
        )

        player_names = [
            'Pitcher Pat',
            'Catcher Cole',
            'First Frank',
            'Second Sam',
            'Third Theo',
            'Shortstop Shawn',
            'Left Lee',
            'Center Casey',
            'Right Riley',
        ]
        players = [
            Player(id=index, name=name, number=str(index), team_id=1)
            for index, name in enumerate(player_names, start=1)
        ]

        local_today = datetime.now(
            ZoneInfo('America/Indiana/Indianapolis')
        ).replace(tzinfo=None, hour=9, minute=0, second=0, microsecond=0)
        game = Game(
            id=1,
            date=local_today,
            start_time='09:00',
            opponent='Browser Bears',
            location='Playwright Field',
            game_notes='Disposable browser-test game',
            team_id=1,
        )
        inaccessible_game = Game(
            id=2,
            date=local_today,
            opponent='Private Opponent',
            team_id=2,
        )
        starting_defense = Rotation(
            id=1,
            title='DEFENSE PRESET — Everyday Defense',
            innings={
                '1': {
                    'C': 'Catcher Cole',
                    '1B': 'First Frank',
                    '2B': 'Second Sam',
                    '3B': 'Third Theo',
                    'SS': 'Shortstop Shawn',
                    'LF': 'Left Lee',
                    'CF': 'Center Casey',
                    'RF': 'Right Riley',
                }
            },
            associated_game_id=None,
            team_id=1,
        )

        db.session.add_all([
            team,
            other_team,
            user,
            membership,
            *players,
            game,
            inaccessible_game,
            starting_defense,
        ])
        db.session.commit()


app = create_app()
app.config.update(TESTING=False)
seed_database(app)


if __name__ == '__main__':
    socketio.run(
        app,
        host='127.0.0.1',
        port=int(os.environ['E2E_PORT']),
        debug=False,
        use_reloader=False,
    )
