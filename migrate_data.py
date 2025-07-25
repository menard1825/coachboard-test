import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, Team, User, Player, Lineup, PitchingOuting, ScoutedPlayer, \
                   Rotation, Game, CollaborationNote, PracticePlan, PracticeTask, \
                   PlayerDevelopmentFocus, Sign
from datetime import datetime
import os

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
# Construct the path to the data file
data_file_path = os.path.join(script_dir, 'data_backup.json')

try:
    with open(data_file_path, 'r') as f:
        data = json.load(f)
except FileNotFoundError:
    print(f"Error: {data_file_path} not found. Make sure it's in the same directory as the script.")
    exit()

# Set up DB session
engine = create_engine('sqlite:///app.db')
Session = sessionmaker(bind=engine)
session = Session()

try:
    # --- MODIFIED LOGIC ---
    # The init_db.py script already creates the first team and a Super Admin.
    # We will find that existing team and use it as the primary team for migration.
    team_map = {} # Maps old team IDs from JSON to new team IDs in the DB

    # Process teams from the JSON backup
    for team_data in data.get("teams", []):
        old_team_id = team_data.get('id')
        
        # Check if a team with this name or registration code already exists.
        existing_team = session.query(Team).filter(
            (Team.team_name == team_data['team_name']) | 
            (Team.registration_code == team_data['registration_code'])
        ).first()

        if existing_team:
            # If it exists, we'll map the old ID to this existing one.
            team_map[old_team_id] = existing_team.id
            print(f"Found existing team '{existing_team.team_name}'. Mapping old ID {old_team_id} to new ID {existing_team.id}.")
            # Optionally update details of the existing team
            existing_team.logo_path = team_data.get('logo_path', existing_team.logo_path)
            existing_team.display_coach_names = team_data.get('display_coach_names', existing_team.display_coach_names)
        else:
            # If it doesn't exist, create it.
            new_team = Team(
                team_name=team_data.get("team_name", "Unnamed Team"),
                registration_code=team_data.get("registration_code"),
                logo_path=team_data.get("logo_path"),
                display_coach_names=team_data.get("display_coach_names", False)
            )
            session.add(new_team)
            session.flush() # Flush to get the new ID
            team_map[old_team_id] = new_team.id
            print(f"Created new team '{new_team.team_name}'. Mapping old ID {old_team_id} to new ID {new_team.id}.")

    # Fetch all existing usernames to prevent duplicates
    existing_usernames = {u.username.lower() for u in session.query(User).all()}

    # Add users, linking them to the correct new team ID
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
                last_login=u_data.get('last_login', 'Never'),
                tab_order=json.dumps(u_data.get('tab_order', [])),
                player_order=json.dumps(u_data.get('player_order', [])),
                team_id=new_team_id
            )
            session.add(user)
            existing_usernames.add(u_data['username'].lower())
            print(f"Added user: {u_data['username']}")
        else:
            print(f"User {u_data['username']} already exists, skipping.")

    # Helper to get player ID and map existing players
    existing_players = {(p.name.lower(), p.team_id) for p in session.query(Player).all()}
    player_name_to_id_map = {p.name: p.id for p in session.query(Player).all()}

    # Add players (roster)
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
                notes_timestamp=p_data.get('notes_timestamp', ''), team_id=new_team_id
            )
            session.add(player)
            session.flush()
            player_name_to_id_map[player.name] = player.id
            existing_players.add((player.name.lower(), new_team_id))
            print(f"Added player: {p_data['name']}")
        else:
            print(f"Player {p_data['name']} already exists for this team, skipping.")
            # Ensure the player_name_to_id_map is up to date even for existing players
            existing_player_obj = session.query(Player).filter_by(name=p_data['name'], team_id=new_team_id).first()
            if existing_player_obj:
                player_name_to_id_map[existing_player_obj.name] = existing_player_obj.id


    # --- FULL SCRIPT RESUMES HERE ---
    
    # Add lineups
    for l_data in data.get("lineups", []):
        old_team_id = l_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        lineup = Lineup(
            title=l_data['title'], lineup_positions=json.dumps(l_data.get('lineup_positions', [])),
            associated_game_id=l_data.get('associated_game_id'), team_id=new_team_id
        )
        session.add(lineup)
    
    # Add pitching outings
    for po_data in data.get("pitching", []):
        old_team_id = po_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        outing = PitchingOuting(
            date=po_data['date'], pitcher=po_data['pitcher'], opponent=po_data.get('opponent', ''),
            pitches=po_data.get('pitches', 0), innings=po_data.get('innings', 0.0),
            pitcher_type=po_data.get('pitcher_type', 'Starter'), outing_type=po_data.get('outing_type', 'Game'),
            team_id=new_team_id
        )
        session.add(outing)

    # Add scouted players
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

    # Add rotations
    for r_data in data.get("rotations", []):
        old_team_id = r_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        rotation = Rotation(
            title=r_data['title'], innings=json.dumps(r_data.get('innings', {})),
            associated_game_id=r_data.get('associated_game_id'), team_id=new_team_id
        )
        session.add(rotation)

    # Add games
    for g_data in data.get("games", []):
        old_team_id = g_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        game = Game(
            date=g_data['date'], opponent=g_data['opponent'], location=g_data.get('location', ''),
            game_notes=g_data.get('game_notes', ''), team_id=new_team_id
        )
        session.add(game)

    # Add collaboration notes
    for cn_type, cn_notes in data.get("collaboration_notes", {}).items():
        for cn_data in cn_notes:
            old_team_id = cn_data.get('team_id')
            new_team_id = team_map.get(old_team_id)
            if not new_team_id: continue
            note = CollaborationNote(
                text=cn_data['text'], author=cn_data['author'], timestamp=cn_data['timestamp'],
                note_type=cn_type, player_name=cn_data.get('player_name'), team_id=new_team_id
            )
            session.add(note)

    # Add practice plans and tasks
    for pp_data in data.get("practice_plans", []):
        old_team_id = pp_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue
        plan = PracticePlan(
            date=pp_data['date'], general_notes=pp_data.get('general_notes', ''), team_id=new_team_id
        )
        session.add(plan)
        session.flush()
        for task_data in pp_data.get('tasks', []):
            task = PracticeTask(
                text=task_data['text'], status=task_data.get('status', 'pending'),
                author=task_data.get('author', 'N/A'), timestamp=task_data.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M')),
                practice_plan_id=plan.id
            )
            session.add(task)

    # Add player development focuses
    for player_name, skills_data in data.get("player_development", {}).items():
        player_id = player_name_to_id_map.get(player_name)
        if not player_id:
            print(f"Warning: Player '{player_name}' not found in DB map. Skipping development focuses.")
            continue
        
        # Find the team_id for this player to correctly associate the focus
        player_obj = session.query(Player).filter_by(id=player_id).first()
        if not player_obj: continue
        new_team_id = player_obj.team_id

        for skill_type, focuses_list in skills_data.items():
            for f_data in focuses_list:
                focus = PlayerDevelopmentFocus(
                    player_id=player_id, skill_type=skill_type, focus=f_data['focus'],
                    status=f_data.get('status', 'active'), notes=f_data.get('notes', ''),
                    author=f_data.get('author', 'N/A'), created_date=f_data.get('created_date', datetime.now().strftime('%Y-%m-%d')),
                    completed_date=f_data.get('completed_date'), last_edited_by=f_data.get('last_edited_by'),
                    last_edited_date=f_data.get('last_edited_date'), team_id=new_team_id
                )
                session.add(focus)
    
    # Add signs
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
