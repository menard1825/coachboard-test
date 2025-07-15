import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, Team, User, Player, Lineup, PitchingOuting, ScoutedPlayer, \
                   Rotation, Game, CollaborationNote, PracticePlan, PracticeTask, \
                   PlayerDevelopmentFocus, Sign # Import all new models
from datetime import datetime
import os # Import os module

# --- UPDATED: More robust path handling ---
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

# Create all tables defined in models.py
# This is the crucial step that was missing.
Base.metadata.create_all(engine)

try:
    # 1. Create a team entry (if not already created by previous run)
    # Check if a team with the default registration code already exists
    settings = data.get("settings") or {}
    registration_code = settings.get("registration_code", "DEFAULT_CODE")
    team = session.query(Team).filter_by(registration_code=registration_code).first()
    if not team:
        team = Team(
            team_name=settings.get("team_name", "Unnamed Team"),
            registration_code=registration_code
        )
        session.add(team)
        session.flush() # Use flush to get the team.id before committing
        print(f"Created new team: {team.team_name} (ID: {team.id})")
    else:
        print(f"Using existing team: {team.team_name} (ID: {team.id})")

    # Fetch existing data for the current team to avoid duplicates on re-run
    existing_usernames = {u.username for u in session.query(User).filter_by(team_id=team.id).all()}
    existing_player_names = {p.name for p in session.query(Player).filter_by(team_id=team.id).all()}
    existing_lineup_titles = {l.title for l in session.query(Lineup).filter_by(team_id=team.id).all()}
    existing_scouted_players_keys = {(sp.name, sp.list_type) for sp in session.query(ScoutedPlayer).filter_by(team_id=team.id).all()}
    existing_rotation_titles = {r.title for r in session.query(Rotation).filter_by(team_id=team.id).all()}
    existing_games_keys = {(g.date, g.opponent) for g in session.query(Game).filter_by(team_id=team.id).all()}
    existing_collab_notes_keys = {
        (cn.timestamp, cn.author, cn.text, cn.note_type, cn.player_name)
        for cn in session.query(CollaborationNote).filter_by(team_id=team.id).all()
    }
    existing_practice_plan_dates = {pp.date for pp in session.query(PracticePlan).filter_by(team_id=team.id).all()}
    existing_sign_keys = {(s.name, s.indicator) for s in session.query(Sign).filter_by(team_id=team.id).all()}
    existing_pitching_outings_keys = { # More robust check for pitching outings
        (po.date, po.pitcher, po.opponent, po.pitches)
        for po in session.query(PitchingOuting).filter_by(team_id=team.id).all()
    }
    # NEW: Check for existing player development focuses
    player_id_to_name_map_for_check = {p.id: p.name for p in session.query(Player).filter_by(team_id=team.id).all()}
    existing_dev_focuses_keys = {
        (player_id_to_name_map_for_check.get(f.player_id), f.skill_type, f.focus)
        for f in session.query(PlayerDevelopmentFocus).filter_by(team_id=team.id).all()
        if player_id_to_name_map_for_check.get(f.player_id)
    }

    # Helper to get player ID
    player_name_to_id_map = {p.name: p.id for p in session.query(Player).filter_by(team_id=team.id).all()}

    # 2. Add users
    for u_data in data.get("users", []):
        if u_data['username'] not in existing_usernames:
            user = User(
                username=u_data['username'],
                full_name=u_data.get('full_name'), # Add full_name, will be None if not in JSON
                password_hash=u_data['password_hash'],
                role=u_data.get('role', 'Coach'),
                last_login=u_data.get('last_login', 'Never'),
                tab_order=json.dumps(u_data.get('tab_order', [])),
                player_order=json.dumps(u_data.get('player_order', [])),
                team_id=team.id
            )
            session.add(user)
            existing_usernames.add(u_data['username'])
            print(f"Added user: {u_data['username']}")
        else:
            print(f"User {u_data['username']} already exists, skipping.")

    # 3. Add players (roster)
    for p_data in data.get("roster", []):
        if p_data['name'] not in existing_player_names:
            player = Player(
                name=p_data['name'],
                number=p_data.get('number', ''),
                position1=p_data.get('position1', ''),
                position2=p_data.get('position2', ''),
                position3=p_data.get('position3', ''),
                throws=p_data.get('throws', ''),
                bats=p_data.get('bats', ''),
                notes=p_data.get('notes', ''),
                pitcher_role=p_data.get('pitcher_role', 'Not a Pitcher'),
                has_lessons=p_data.get('has_lessons', 'No'),
                lesson_focus=p_data.get('lesson_focus', ''),
                notes_author=p_data.get('notes_author', 'N/A'),
                notes_timestamp=p_data.get('notes_timestamp', ''),
                team_id=team.id
            )
            session.add(player)
            session.flush() # Flush to get player ID for later use
            player_name_to_id_map[player.name] = player.id # Update map for player_dev_focuses
            existing_player_names.add(p_data['name'])
            print(f"Added player: {p_data['name']}")
        else:
            print(f"Player {p_data['name']} already exists, skipping.")

    # 4. Add lineups
    for l_data in data.get("lineups", []):
        if l_data['title'] not in existing_lineup_titles:
            lineup = Lineup(
                title=l_data['title'],
                lineup_positions=json.dumps(l_data.get('lineup_positions', [])),
                associated_game_id=l_data.get('associated_game_id'),
                team_id=team.id
            )
            session.add(lineup)
            existing_lineup_titles.add(l_data['title'])
            print(f"Added lineup: {l_data['title']}")
        else:
            print(f"Lineup {l_data['title']} already exists, skipping.")

    # 5. Add pitching outings
    for po_data in data.get("pitching", []):
        outing_key = (po_data['date'], po_data['pitcher'], po_data.get('opponent', ''), po_data.get('pitches', 0))
        if outing_key not in existing_pitching_outings_keys:
            outing = PitchingOuting(
                date=po_data['date'],
                pitcher=po_data['pitcher'], # Corrected from pitcher_name
                opponent=po_data.get('opponent', ''),
                pitches=po_data.get('pitches', 0),
                innings=po_data.get('innings', 0.0),
                pitcher_type=po_data.get('pitcher_type', 'Starter'),
                outing_type=po_data.get('outing_type', 'Game'),
                team_id=team.id
            )
            session.add(outing)
            existing_pitching_outings_keys.add(outing_key)
            print(f"Added pitching outing for {po_data['pitcher']} on {po_data['date']}")
        else:
            print(f"Pitching outing for {po_data['pitcher']} on {po_data['date']} already exists, skipping.")

    # 6. Add scouted players
    for sp_list_type, sp_players in data.get("scouting_list", {}).items():
        for sp_data in sp_players:
            key = (sp_data['name'], sp_list_type)
            if key not in existing_scouted_players_keys:
                scouted_player = ScoutedPlayer(
                    name=sp_data['name'],
                    position1=sp_data.get('position1', ''),
                    position2=sp_data.get('position2', ''),
                    throws=sp_data.get('throws', ''),
                    bats=sp_data.get('bats', ''),
                    list_type=sp_list_type,
                    team_id=team.id
                )
                session.add(scouted_player)
                existing_scouted_players_keys.add(key)
                print(f"Added scouted player: {sp_data['name']} to {sp_list_type}")
            else:
                print(f"Scouted player {sp_data['name']} already exists in {sp_list_type}, skipping.")

    # 7. Add rotations
    for r_data in data.get("rotations", []):
        if r_data['title'] not in existing_rotation_titles:
            rotation = Rotation(
                title=r_data['title'],
                innings=json.dumps(r_data.get('innings', {})), # Corrected from innings_data
                associated_game_id=r_data.get('associated_game_id'),
                team_id=team.id
            )
            session.add(rotation)
            existing_rotation_titles.add(r_data['title'])
            print(f"Added rotation: {r_data['title']}")
        else:
            print(f"Rotation {r_data['title']} already exists, skipping.")

    # 8. Add games
    for g_data in data.get("games", []):
        key = (g_data['date'], g_data['opponent'])
        if key not in existing_games_keys:
            game = Game(
                date=g_data['date'],
                opponent=g_data['opponent'],
                location=g_data.get('location', ''),
                game_notes=g_data.get('game_notes', ''),
                team_id=team.id
            )
            session.add(game)
            existing_games_keys.add(key)
            print(f"Added game: {g_data['opponent']} on {g_data['date']}")
        else:
            print(f"Game {g_data['opponent']} on {g_data['date']} already exists, skipping.")

    # 9. Add collaboration notes
    for cn_type, cn_notes in data.get("collaboration_notes", {}).items():
        for cn_data in cn_notes:
            note_key = (
                cn_data['timestamp'],
                cn_data['author'],
                cn_data['text'],
                cn_type,
                cn_data.get('player_name')
            )
            if note_key not in existing_collab_notes_keys:
                note = CollaborationNote(
                    text=cn_data['text'],
                    author=cn_data['author'],
                    timestamp=cn_data['timestamp'],
                    note_type=cn_type,
                    player_name=cn_data.get('player_name'),
                    team_id=team.id
                )
                session.add(note)
                existing_collab_notes_keys.add(note_key)
                print(f"Added collaboration note for {cn_type}")
            else:
                print(f"Collaboration note for {cn_type} already exists, skipping.")

    # 10. Add practice plans and their tasks
    for pp_data in data.get("practice_plans", []):
        if pp_data['date'] not in existing_practice_plan_dates:
            plan = PracticePlan(
                date=pp_data['date'],
                general_notes=pp_data.get('general_notes', ''),
                team_id=team.id
            )
            session.add(plan)
            session.flush() # Flush to get plan ID for tasks
            existing_practice_plan_dates.add(pp_data['date'])
            print(f"Added practice plan for {pp_data['date']}")

            # Add tasks for the newly created plan
            for task_data in pp_data.get('tasks', []):
                task = PracticeTask(
                    text=task_data['text'],
                    status=task_data.get('status', 'pending'),
                    author=task_data.get('author', 'N/A'),
                    timestamp=task_data.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M')),
                    practice_plan_id=plan.id
                )
                session.add(task)
                print(f"  Added task: {task_data['text']}")
        else:
            print(f"Practice plan for {pp_data['date']} already exists, skipping.")


    # 11. Add player development focuses
    for player_name, skills_data in data.get("player_development", {}).items():
        player_id = player_name_to_id_map.get(player_name)
        if not player_id:
            print(f"Warning: Player '{player_name}' not found in database. Skipping development focuses for this player.")
            continue

        for skill_type_from_json, focuses_list in skills_data.items(): # Renamed skill to skill_type_from_json for clarity
            if isinstance(focuses_list, list):
                for f_data in focuses_list:
                    # Using skill_type_from_json to match the dict key from JSON
                    focus_key = (player_name, skill_type_from_json, f_data['focus'])
                    if focus_key not in existing_dev_focuses_keys:
                        focus = PlayerDevelopmentFocus(
                            player_id=player_id, # Link by ID
                            skill_type=skill_type_from_json, # Corrected to skill_type
                            focus=f_data['focus'],
                            status=f_data.get('status', 'active'),
                            notes=f_data.get('notes', ''),
                            author=f_data.get('author', 'N/A'),
                            created_date=f_data.get('created_date', datetime.now().strftime('%Y-%m-%d')),
                            completed_date=f_data.get('completed_date'),
                            last_edited_by=f_data.get('last_edited_by'),
                            last_edited_date=f_data.get('last_edited_date'),
                            team_id=team.id
                        )
                        session.add(focus)
                        existing_dev_focuses_keys.add(focus_key)
                        print(f"Added development focus for {player_name} ({skill_type_from_json}): {f_data['focus']}")
            elif isinstance(focuses_list, str): # Handle old string format if still present after migration script
                if focuses_list:
                    focus_key = (player_name, skill_type_from_json, focuses_list)
                    if focus_key not in existing_dev_focuses_keys:
                        focus = PlayerDevelopmentFocus(
                            player_id=player_id, # Link by ID
                            skill_type=skill_type_from_json, # Corrected to skill_type
                            focus=focuses_list,
                            status='active',
                            notes='',
                            author='N/A',
                            created_date=datetime.now().strftime('%Y-%m-%d'),
                            completed_date=None,
                            last_edited_by='',
                            last_edited_date='',
                            team_id=team.id
                        )
                        session.add(focus)
                        existing_dev_focuses_keys.add(focus_key)
                        print(f"Added development focus (string) for {player_name} ({skill_type_from_json}): {focuses_list}")
            else:
                print(f"Warning: Unexpected format for player development data for {player_name} under {skill_type_from_json}. Expected list or string, got {type(focuses_list)}.")

    # 12. Add signs
    for s_data in data.get("signs", []):
        key = (s_data['name'], s_data['indicator'])
        if key not in existing_sign_keys:
            sign = Sign(
                name=s_data['name'],
                indicator=s_data['indicator'],
                team_id=team.id
            )
            session.add(sign)
            existing_sign_keys.add(key)
            print(f"Added sign: {s_data['name']}")
        else:
            print(f"Sign {s_data['name']} already exists, skipping.")

    session.commit()
    print("? Data migration complete.")

except Exception as e:
    session.rollback()
    print(f"Migration failed: {e}")
finally:
    session.close()