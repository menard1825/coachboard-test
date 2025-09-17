import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Team, User, Player, Lineup, PitchingOuting, ScoutedPlayer, \
                   Rotation, Game, CollaborationNote, PracticePlan, PracticeTask, \
                   PlayerDevelopmentFocus, Sign
from datetime import datetime
import os
from utils import parse_date

script_dir = os.path.dirname(os.path.abspath(__file__))
data_file_path = os.path.join(script_dir, 'data_backup.json')

try:
    with open(data_file_path, 'r') as f:
        data = json.load(f)
except FileNotFoundError:
    print(f"Error: {data_file_path} not found. Make sure it's in the same directory as the script.")
    exit()

db_path = os.path.join(script_dir, 'app.db')
db_uri = f'sqlite:///{db_path}'
engine = create_engine(db_uri)
Session = sessionmaker(bind=engine)
session = Session()

try:
    team_map = {}

    for team_data in data.get("teams", []):
        old_team_id = team_data.get('id')
        
        existing_team = session.query(Team).filter(
            (Team.team_name == team_data['team_name']) | 
            (Team.registration_code == team_data['registration_code'])
        ).first()

        if existing_team:
            team_map[old_team_id] = existing_team.id
            print(f"Found existing team '{existing_team.team_name}'. Mapping old ID {old_team_id} to new ID {existing_team.id}.")
            existing_team.logo_path = team_data.get('logo_path', existing_team.logo_path)
            existing_team.display_coach_names = team_data.get('display_coach_names', existing_team.display_coach_names)
        else:
            new_team = Team(
                team_name=team_data.get("team_name", "Unnamed Team"),
                registration_code=team_data.get("registration_code"),
                logo_path=team_data.get("logo_path"),
                display_coach_names=team_data.get("display_coach_names", False)
            )
            session.add(new_team)
            session.flush()
            team_map[old_team_id] = new_team.id
            print(f"Created new team '{new_team.team_name}'. Mapping old ID {old_team_id} to new ID {new_team.id}.")

    existing_usernames = {u.username.lower() for u in session.query(User).all()}

    for u_data in data.get("users", []):
        if u_data['username'].lower() not in existing_usernames:
            old_team_id = u_data.get('team_id')
            new_team_id = team_map.get(old_team_id)

            if not new_team_id:
                print(f"Warning: Could not find a team for user '{u_data['username']}'. Skipping user.")
                continue

            user = User(
                username=u_data['username'],
                full_name=u_data.get('full_name'),
                password_hash=u_data['password_hash'],
                role=u_data.get('role', 'Coach'),
                last_login=parse_date(u_data.get('last_login')),
                tab_order=json.dumps(u_data.get('tab_order', [])),
                player_order=u_data.get('player_order', []),
                team_id=new_team_id
            )
            session.add(user)
            existing_usernames.add(u_data['username'].lower())
            print(f"Added user: {u_data['username']}")
        else:
            print(f"User {u_data['username']} already exists, skipping.")

    existing_players = {(p.name.lower(), p.team_id) for p in session.query(Player).all()}
    player_name_to_id_map = {}
    for p in session.query(Player).all():
        player_name_to_id_map[p.name] = p.id

    for p_data in data.get("roster", []):
        old_team_id = p_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue

        if (p_data['name'].lower(), new_team_id) not in existing_players:
            player = Player(
                name=p_data['name'], number=p_data.get('number', ''), position1=p_data.get('position1', ''),
                position2=p_data.get('position2', ''), position3=p_data.get('position3', ''),
                throws=p_data.get('throws', ''), bats=p_data.get('bats', ''), notes=p_data.get('notes', ''),
                pitcher_role=p_data.get('pitcher_role', 'Not a Pitcher'), has_lessons=p_data.get('has_lessons', 'No'),
                lesson_focus=p_data.get('lesson_focus', ''), notes_author=p_data.get('notes_author', 'N/A'),
                notes_timestamp=parse_date(p_data.get('notes_timestamp')), team_id=new_team_id
            )
            session.add(player)
            session.flush()
            player_name_to_id_map[player.name] = player.id
            existing_players.add((player.name.lower(), new_team_id))
            print(f"Added player: {p_data['name']}")
        else:
            print(f"Player {p_data['name']} already exists for this team, skipping.")
            existing_player_obj = session.query(Player).filter_by(name=p_data['name'], team_id=new_team_id).first()
            if existing_player_obj:
                player_name_to_id_map[existing_player_obj.name] = existing_player_obj.id

    for l_data in data.get("lineups", []):
        old_team_id = l_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        lineup_data = l_data.get('lineup_positions', [])
        player_names = [p['name'] for p in lineup_data if isinstance(p, dict) and 'name' in p]

        lineup = Lineup(
            title=l_data['title'], lineup_positions=player_names,
            associated_game_id=l_data.get('associated_game_id'), team_id=new_team_id
        )
        session.add(lineup)
    
    for po_data in data.get("pitching", []):
        old_team_id = po_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        outing = PitchingOuting(
            date=parse_date(po_data['date']), opponent=po_data.get('opponent', ''),
            pitches=po_data.get('pitches', 0), innings=po_data.get('innings', 0.0),
            pitcher_type=po_data.get('pitcher_type', 'Starter'), outing_type=po_data.get('outing_type', 'Game'),
            team_id=new_team_id
        )
        player_id = player_name_to_id_map.get(po_data['pitcher'])
        if player_id:
            outing.player_id = player_id
        else:
            print(f"Warning: Could not find player ID for pitcher '{po_data['pitcher']}'. Skipping outing.")
            continue
        session.add(outing)

    for sp_list_type, sp_players in data.get("scouting_list", {}).items():
        for sp_data in sp_players:
            old_team_id = sp_data.get('team_id')
            new_team_id = team_map.get(old_team_id)
            if not new_team_id: continue
            scouted_player = ScoutedPlayer(
                name=sp_data['name'], position1=sp_data.get('position1', ''), position2=sp_data.get('position2', ''),
                throws=sp_data.get('throws', ''), bats=sp_data.get('bats', ''), list_type=sp_list_type,
                team_id=new_team_id
            )
            session.add(scouted_player)

    for r_data in data.get("rotations", []):
        old_team_id = r_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        rotation = Rotation(
            title=r_data['title'], innings=r_data.get('innings', {}),
            associated_game_id=r_data.get('associated_game_id'), team_id=new_team_id
        )
        session.add(rotation)

    for g_data in data.get("games", []):
        old_team_id = g_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        game = Game(
            date=parse_date(g_data['date']), opponent=g_data['opponent'], location=g_data.get('location', ''),
            game_notes=g_data.get('game_notes', ''), team_id=new_team_id
        )
        session.add(game)

    for cn_type, cn_notes in data.get("collaboration_notes", {}).items():
        for cn_data in cn_notes:
            old_team_id = cn_data.get('team_id')
            new_team_id = team_map.get(old_team_id)
            if not new_team_id: continue
            note = CollaborationNote(
                text=cn_data['text'], author=cn_data['author'], timestamp=parse_date(cn_data['timestamp']),
                note_type=cn_type, player_name=cn_data.get('player_name'), team_id=new_team_id
            )
            session.add(note)

    for pp_data in data.get("practice_plans", []):
        old_team_id = pp_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        plan = PracticePlan(
            date=parse_date(pp_data['date']), general_notes=pp_data.get('general_notes', ''), team_id=new_team_id
        )
        session.add(plan)
        session.flush()
        for task_data in pp_data.get('tasks', []):
            task = PracticeTask(
                text=task_data['text'], status=task_data.get('status', 'pending'),
                author=task_data.get('author', 'N/A'), timestamp=parse_date(task_data.get('timestamp')),
                practice_plan_id=plan.id
            )
            session.add(task)

    for player_name, skills_data in data.get("player_development", {}).items():
        player_id = player_name_to_id_map.get(player_name)
        if not player_id:
            print(f"Warning: Player '{player_name}' not found in DB map. Skipping development focuses.")
            continue
        
        player_obj = session.query(Player).filter_by(id=player_id).first()
        if not player_obj: continue
        new_team_id = player_obj.team_id

        for skill_type, focuses_list in skills_data.items():
            for f_data in focuses_list:
                focus = PlayerDevelopmentFocus(
                    player_id=player_id, skill_type=skill_type, focus=f_data['focus'],
                    status=f_data.get('status', 'active'), notes=f_data.get('notes', ''),
                    author=f_data.get('author', 'N/A'), created_date=parse_date(f_data.get('created_date')),
                    completed_date=parse_date(f_data.get('completed_date')), last_edited_by=f_data.get('last_edited_by'),
                    last_edited_date=parse_date(f_data.get('last_edited_date')), team_id=new_team_id
                )
                session.add(focus)
    
    for s_data in data.get("signs", []):
        old_team_id = s_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        sign = Sign(
            name=s_data['name'], indicator=s_data['indicator'], team_id=new_team_id
        )
        session.add(sign)

    session.commit()
    print("\nData migration complete.")

except Exception as e:
    session.rollback()
    print(f"Migration failed: {e}")
finally:
    session.close()
