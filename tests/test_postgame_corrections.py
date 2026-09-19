from datetime import datetime

from werkzeug.security import generate_password_hash


def _build_app(monkeypatch, *, ended=True, role='Head Coach'):
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('COACHBOARD_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')

    from app import create_app
    from db import db
    from lineup_service import sync_lineup
    from models import Game, GameRotationEvent, Lineup, Player, Rotation, Team, TeamMembership, User

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        db.create_all()
        team = Team(
            id=1,
            team_name='Correction Test Team',
            registration_code='correction-test-code',
            age_group='12U',
            pitching_rule_set='MLB Pitch Smart',
            outfielder_count=3,
            regulation_innings=6,
            timezone='America/Indiana/Indianapolis',
        )
        user = User(
            id=1,
            username='coach',
            full_name='Test Coach',
            password_hash=generate_password_hash('password123'),
        )
        db.session.add_all([team, user])
        db.session.flush()
        db.session.add(TeamMembership(
            user_id=user.id,
            team_id=team.id,
            role=role,
            player_order=[],
        ))

        players = []
        for index, name in enumerate(['Ace', 'Cody', 'Finn', 'Gabe', 'Hank', 'Ivan', 'Jake', 'Kyle', 'Liam'], start=1):
            player = Player(name=name, number=str(index), team_id=team.id)
            db.session.add(player)
            players.append(player)
        db.session.flush()

        game = Game(
            id=1,
            date=datetime(2026, 8, 20),
            start_time='14:00',
            opponent='Correction Opponent',
            team_id=team.id,
            is_live=False,
            live_current_inning='1',
        )
        db.session.add(game)
        db.session.flush()

        alignment = {
            'P':'Ace', 'C':'Cody', '1B':'Finn', '2B':'Gabe', '3B':'Hank',
            'SS':'Ivan', 'LF':'Jake', 'CF':'Kyle', 'RF':'Liam',
        }
        db.session.add(Rotation(
            title='Game Defense',
            innings={'1': alignment},
            associated_game_id=game.id,
            team_id=team.id,
        ))

        lineup = Lineup(title='Game Lineup', team_id=team.id, associated_game_id=game.id)
        sync_lineup(
            lineup,
            players,
            title='Game Lineup',
            associated_game_id=game.id,
            is_default=False,
        )

        if ended:
            db.session.add(GameRotationEvent(
                inning='1',
                sequence=1,
                event_type='End Game',
                before_alignment=alignment,
                after_alignment=alignment,
                changed_by_user='coach',
                team_id=team.id,
                game_id=game.id,
            ))
        db.session.commit()

    return app


def _login(client, role='Head Coach'):
    with client.session_transaction() as session:
        session['logged_in'] = True
        session['username'] = 'coach'
        session['full_name'] = 'Test Coach'
        session['team_id'] = 1
        session['role'] = role


def test_ended_game_report_offers_safe_edit_mode(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    report = client.get('/game-day/1/report')
    assert report.status_code == 200
    html = report.get_data(as_text=True)
    assert 'Edit Game' in html
    assert '/game-day/1/correct' in html

    correction = client.get('/game-day/1/correct')
    assert correction.status_code == 200
    correction_html = correction.get_data(as_text=True)
    assert 'This does not reopen Live Game.' in correction_html
    assert 'Batting Order' in correction_html
    assert 'Defense by Inning' in correction_html


def test_postgame_defense_correction_updates_historical_report_without_reopening(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    corrected = {
        'P':'Ace', 'C':'Finn', '1B':'Cody', '2B':'Gabe', '3B':'Hank',
        'SS':'Ivan', 'LF':'Jake', 'CF':'Kyle', 'RF':'Liam',
    }
    response = client.post('/api/game-day/1/corrections/defense', json={
        'inning':'1',
        'alignment':corrected,
    })
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

    from db import db
    from models import Game, GameRotationEvent
    with app.app_context():
        game = db.session.get(Game, 1)
        assert game.is_live is False
        correction_event = db.session.query(GameRotationEvent).filter_by(
            game_id=1,
            event_type='Postgame Correction',
        ).one()
        assert correction_event.after_alignment['C'] == 'Finn'
        assert correction_event.after_alignment['1B'] == 'Cody'

    report = client.get('/game-day/1/report').get_data(as_text=True)
    assert '#3 Finn' in report
    assert '#2 Cody' in report



def test_incomplete_final_defense_is_explained_and_links_to_exact_inning(
    monkeypatch,
):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import GameRotationEvent

    with app.app_context():
        end_event = (
            db.session.query(GameRotationEvent)
            .filter_by(
                game_id=1,
                team_id=1,
                event_type='End Game',
                reverted=False,
            )
            .one()
        )

        incomplete = dict(end_event.after_alignment)
        incomplete.pop('2B')

        end_event.after_alignment = incomplete
        db.session.commit()

    report = client.get(
        '/game-day/1/report'
    )

    assert report.status_code == 200

    html = report.get_data(as_text=True)

    assert 'Incomplete defense' in html
    assert (
        '2B was left open at the end of the inning.'
        in html
    )
    assert 'This inning wasn&#39;t recorded' not in html
    assert 'Edit positions' in html
    assert '/game-day/1/correct?inning=1#defense' in html



def test_normal_roster_open_position_remains_incomplete_and_cannot_be_saved(
    monkeypatch,
):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    incomplete = {
        'P':'Ace', 'C':'Cody', '1B':'Finn',
        '3B':'Hank', 'SS':'Ivan',
        'LF':'Jake', 'CF':'Kyle', 'RF':'Liam',
    }

    response = client.post(
        '/api/game-day/1/corrections/defense',
        json={
            'inning':'1',
            'alignment':incomplete,
        },
    )

    assert response.status_code == 409
    assert (
        'Fill every defensive position before saving.'
        in response.get_json()['message']
    )


def test_short_handed_open_position_is_reliable_and_editable(
    monkeypatch,
):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from models import (
        GameRotationEvent,
        Player,
        PlayerGameAbsence,
    )

    with app.app_context():
        liam = (
            db.session.query(Player)
            .filter_by(
                team_id=1,
                name='Liam',
            )
            .one()
        )

        db.session.add(
            PlayerGameAbsence(
                player_id=liam.id,
                game_id=1,
                team_id=1,
            )
        )

        end_event = (
            db.session.query(GameRotationEvent)
            .filter_by(
                game_id=1,
                team_id=1,
                event_type='End Game',
                reverted=False,
            )
            .one()
        )

        short_handed = dict(
            end_event.after_alignment
        )
        short_handed.pop('RF')

        end_event.after_alignment = (
            short_handed
        )

        db.session.commit()

    report = client.get(
        '/game-day/1/report'
    )

    assert report.status_code == 200

    html = report.get_data(as_text=True)

    assert 'Short-handed' in html
    assert 'Open: RF (short-handed)' in html
    assert 'Incomplete defense' not in html

    corrected = dict(short_handed)
    corrected['C'], corrected['1B'] = (
        corrected['1B'],
        corrected['C'],
    )

    response = client.post(
        '/api/game-day/1/corrections/defense',
        json={
            'inning':'1',
            'alignment':corrected,
        },
    )

    assert response.status_code == 200
    assert (
        response.get_json()['status']
        == 'success'
    )

    with app.app_context():
        correction = (
            db.session.query(GameRotationEvent)
            .filter_by(
                game_id=1,
                team_id=1,
                event_type='Postgame Correction',
            )
            .one()
        )

        assert correction.after_alignment['RF'] == ''
        assert correction.after_alignment['C'] == 'Finn'
        assert correction.after_alignment['1B'] == 'Cody'


def test_postgame_correction_recalculates_bench_totals(
    monkeypatch,
):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    from db import db
    from game_day_helpers import build_actual_game_report
    from models import Game, Player, Team

    with app.app_context():
        db.session.add(
            Player(
                name='Milo',
                number='10',
                team_id=1,
            )
        )
        db.session.commit()

        team = db.session.get(Team, 1)
        game = db.session.get(Game, 1)

        before = build_actual_game_report(
            game,
            team,
        )

        before_rows = {
            row['name']: row
            for row in before['bench_rows']
        }

        assert before_rows['Milo']['innings'] == ['1']
        assert before_rows['Liam']['innings'] == []

    corrected = {
        'P':'Ace', 'C':'Cody', '1B':'Finn',
        '2B':'Gabe', '3B':'Hank', 'SS':'Ivan',
        'LF':'Jake', 'CF':'Kyle', 'RF':'Milo',
    }

    response = client.post(
        '/api/game-day/1/corrections/defense',
        json={
            'inning':'1',
            'alignment':corrected,
        },
    )

    assert response.status_code == 200

    with app.app_context():
        team = db.session.get(Team, 1)
        game = db.session.get(Game, 1)

        after = build_actual_game_report(
            game,
            team,
        )

        after_rows = {
            row['name']: row
            for row in after['bench_rows']
        }

        assert after_rows['Milo']['innings'] == []
        assert after_rows['Liam']['innings'] == ['1']


def test_resume_uses_postgame_corrected_final_inning_alignment(
    monkeypatch,
):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    corrected = {
        'P':'Ace', 'C':'Finn', '1B':'Cody',
        '2B':'Gabe', '3B':'Hank', 'SS':'Ivan',
        'LF':'Jake', 'CF':'Kyle', 'RF':'Liam',
    }

    correction = client.post(
        '/api/game-day/1/corrections/defense',
        json={
            'inning':'1',
            'alignment':corrected,
        },
    )

    assert correction.status_code == 200

    resumed = client.post(
        '/game-day/1/resume',
        follow_redirects=False,
    )

    assert resumed.status_code in {302, 303}

    from db import db
    from game_day_helpers import actual_game_rotation
    from models import Game, GameRotationEvent

    with app.app_context():
        game = db.session.get(Game, 1)

        assert game.is_live is True

        _, actual, _, _ = actual_game_rotation(
            game,
            1,
        )

        assert actual['1'] == corrected

        resume_event = (
            db.session.query(GameRotationEvent)
            .filter_by(
                game_id=1,
                team_id=1,
                event_type='Resume Game',
                reverted=False,
            )
            .one()
        )

        assert (
            resume_event.before_alignment
            == corrected
        )
        assert (
            resume_event.after_alignment
            == corrected
        )


def test_postgame_lineup_correction_changes_report_order(monkeypatch):
    app = _build_app(monkeypatch)
    client = app.test_client()
    _login(client)

    response = client.post('/api/game-day/1/corrections/lineup', json={
        'player_ids':[9, 8, 7, 6, 5, 4, 3, 2, 1],
    })
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'

    from db import db
    from lineup_service import lineup_to_dict
    from models import Lineup
    with app.app_context():
        lineup = db.session.query(Lineup).filter_by(associated_game_id=1, team_id=1).one()
        names = [entry['name'] for entry in lineup_to_dict(lineup)['lineup_entries']]
        assert names[0] == 'Liam'
        assert names[-1] == 'Ace'

    report = client.get('/game-day/1/report').get_data(as_text=True)
    batting_section = report.split('<strong>Batting Order</strong>', 1)[1].split('<strong>GameChanger Pitching</strong>', 1)[0]
    assert batting_section.index('#9 Liam') < batting_section.index('#1 Ace')


def test_postgame_corrections_reject_unended_games_and_gamechanger_role(monkeypatch):
    app = _build_app(monkeypatch, ended=False)
    client = app.test_client()
    _login(client)

    response = client.post('/api/game-day/1/corrections/lineup', json={'player_ids':[1]})
    assert response.status_code == 409

    ended_app = _build_app(monkeypatch, ended=True, role='Game Changer')
    gc_client = ended_app.test_client()
    _login(gc_client, role='Game Changer')
    response = gc_client.post('/api/game-day/1/corrections/lineup', json={'player_ids':[1]})
    assert response.status_code == 403
