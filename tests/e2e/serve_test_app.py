"""Disposable CoachBoard server used only by the Playwright test suite."""

import os
import sys
from datetime import datetime, timedelta
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
from models import (
    CollaborationNote,
    Game,
    GamePitchingPlan,
    Lineup,
    PitchingOuting,
    Player,
    PlayerDevelopmentFocus,
    PlayerPitchTarget,
    PlayerPitchingProfile,
    PracticePlan,
    PracticeTask,
    Rotation,
    ScoutedPlayer,
    Sign,
    Team,
    TeamMembership,
    User,
)
from werkzeug.security import generate_password_hash


TEST_USERNAME = 'playwright-coach'
TEST_PASSWORD = 'playwright-password'
ASSISTANT_USERNAME = 'playwright-assistant'
ASSISTANT_PASSWORD = 'playwright-assistant-password'


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
        assistant = User(
            id=2,
            username=ASSISTANT_USERNAME,
            email='playwright-assistant@example.test',
            full_name='Playwright Assistant',
            password_hash=generate_password_hash(ASSISTANT_PASSWORD),
        )
        membership = TeamMembership(
            id=2,
            user_id=1,
            team_id=1,
            role='Super Admin',
            player_order=[],
        )
        assistant_membership = TeamMembership(
            id=3,
            user_id=2,
            team_id=1,
            role='Assistant Coach',
            player_order=[],
        )
        second_team_membership = TeamMembership(
            id=1,
            user_id=1,
            team_id=2,
            role='Super Admin',
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
            Player(
                id=index,
                name=name,
                number=str(index),
                position1=(
                    'P' if index == 1 else
                    'C' if index == 2 else
                    '1B' if index == 3 else
                    '2B' if index == 4 else
                    '3B' if index == 5 else
                    'SS' if index == 6 else
                    'LF' if index == 7 else
                    'CF' if index == 8 else
                    'RF'
                ),
                throws='Left' if index in {1, 7} else 'Right',
                bats='Left' if index in {1, 7, 8} else 'Right',
                pitcher_role='Starter' if index == 1 else 'Not a Pitcher',
                has_lessons='No',
                team_id=1,
            )
            for index, name in enumerate(player_names, start=1)
        ]
        private_player = Player(
            id=100,
            name='Private Player',
            number='99',
            team_id=2,
        )

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
        full_rotation = Rotation(
            id=2,
            title='Six Inning Rotation',
            innings={
                '1': {
                    'P': 'Pitcher Pat',
                    'C': 'Catcher Cole',
                    '1B': 'First Frank',
                    '2B': 'Second Sam',
                    '3B': 'Third Theo',
                    'SS': 'Shortstop Shawn',
                    'LF': 'Left Lee',
                    'CF': 'Center Casey',
                    'RF': 'Right Riley',
                },
                '2': {
                    'P': 'Pitcher Pat',
                    'C': 'Catcher Cole',
                    '1B': 'First Frank',
                    '2B': 'Second Sam',
                    '3B': 'Third Theo',
                    'SS': 'Shortstop Shawn',
                    'LF': 'Left Lee',
                    'CF': 'Center Casey',
                    'RF': 'Right Riley',
                },
            },
            associated_game_id=None,
            team_id=1,
        )
        lineup = Lineup(
            id=1,
            title='Everyday Batting Order',
            lineup_positions=list(player_names),
            associated_game_id=None,
            team_id=1,
        )
        outing = PitchingOuting(
            id=1,
            date=local_today - timedelta(days=2),
            opponent='Seed Tigers',
            pitches=35,
            innings=2.0,
            pitcher_type='Starter',
            outing_type='Game',
            team_id=1,
            player_id=1,
        )
        target = PlayerPitchTarget(
            id=1,
            target_pitches=50,
            local_date=local_today.strftime('%Y-%m-%d'),
            reason='Browser-test target',
            player_id=1,
            team_id=1,
        )
        profile = PlayerPitchingProfile(
            id=1,
            player_id=1,
            team_id=1,
            traits=['Command / Strike Thrower', 'Holds Runners Well'],
        )
        pitching_plan = GamePitchingPlan(
            id=1,
            role='Starter',
            expected_innings='2',
            coach_note='Start efficient',
            situational_note='First time through order',
            player_id=1,
            game_id=1,
            team_id=1,
        )
        target_scout = ScoutedPlayer(
            id=1,
            name='Target Taylor',
            position1='SS',
            position2='2B',
            throws='Right',
            bats='Right',
            list_type='targets',
            team_id=1,
        )
        committed_scout = ScoutedPlayer(
            id=2,
            name='Committed Cameron',
            position1='OF',
            throws='Left',
            bats='Left',
            list_type='committed',
            team_id=1,
        )
        team_note = CollaborationNote(
            id=1,
            note_type='team_notes',
            text='Seeded team note',
            author='Playwright Coach',
            timestamp=local_today,
            team_id=1,
        )
        player_note = CollaborationNote(
            id=2,
            note_type='player_notes',
            text='Seeded player note',
            author='Playwright Coach',
            timestamp=local_today,
            player_name='Pitcher Pat',
            team_id=1,
        )
        practice_plan = PracticePlan(
            id=1,
            date=local_today + timedelta(days=1),
            general_notes='Seeded practice',
            emphasis='Communication',
            warm_up='Dynamic warm-up',
            infield_outfield='Team defense',
            hitting='Situational hitting',
            pitching_catching='Bullpens',
            team_id=1,
        )
        practice_task = PracticeTask(
            id=1,
            text='Review bunt defense',
            status='pending',
            author='Playwright Coach',
            timestamp=local_today,
            practice_plan_id=1,
        )
        development_focus = PlayerDevelopmentFocus(
            id=1,
            focus='Throw first-pitch strikes',
            status='active',
            notes='Track bullpen quality',
            created_date=local_today,
            author='Playwright Coach',
            player_id=1,
            skill_type='pitching',
            team_id=1,
        )
        sign = Sign(
            id=1,
            name='Steal',
            indicator='Touch belt',
            team_id=1,
        )

        db.session.add_all([
            team,
            other_team,
            user,
            assistant,
            membership,
            assistant_membership,
            second_team_membership,
            *players,
            private_player,
            game,
            inaccessible_game,
            starting_defense,
            full_rotation,
            lineup,
            outing,
            target,
            profile,
            pitching_plan,
            target_scout,
            committed_scout,
            team_note,
            player_note,
            practice_plan,
            practice_task,
            development_focus,
            sign,
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
