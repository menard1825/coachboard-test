# menard1825/coachboard-test/coachboard-test-production-readiness-and-bug-fixes/migrate_data.py
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Team, User, Player, Lineup, PitchingOuting, ScoutedPlayer, \
                   Rotation, Game, CollaborationNote, PracticePlan, PracticeTask, \
                   PlayerDevelopmentFocus, Sign
from datetime import datetime
import os

def parse_date(date_str):
    """
    More robustly parses date strings from the old database, handling multiple formats,
    including those with microseconds.
    """
    if not date_str or date_str == 'Never':
        return None
    # Handles formats like '2025-07-23', '2025-07-24 23:55', and '2025-09-03 16:50:38.194614'
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    print(f"Warning: Could not parse date string '{date_str}' with known formats.")
    return None

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
# Construct the path to the data file
data_file_path = os.path.join(script_dir, 'data_backup.json')

try:
    with open(data_file_path, 'r') as f:
        data = json.load(f)
except FileNotFoundError:
    print(f"Error: {data_file_path} not found. Ensure you have run export_to_json.py first.")
    exit()

# Set up DB session
db_path = os.path.join(script_dir, 'app.db')
db_uri = f'sqlite:///{db_path}'
engine = create_engine(db_uri)
Session = sessionmaker(bind=engine)
session = Session()

try:
    team_map = {} # Maps old team IDs from JSON to new team IDs in the DB

    # Process teams from the JSON backup
    for team_data in data.get("teams", []):
        old_team_id = team_data.get('id')
        existing_team = session.query(Team).filter_by(team_name=team_data['team_name']).first()

        if existing_team:
            team_map[old_team_id] = existing_team.id
            print(f"Found existing team '{existing_team.team_name}'. Mapping old ID {old_team_id} to new ID {existing_team.id}.")
        else:
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

    existing_usernames = {u.username.lower() for u in session.query(User).all()}

    # Add users
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
                player_order=json.dumps(u_data.get('player_order', [])),
                team_id=new_team_id
            )
            session.add(user)
            existing_usernames.add(u_data['username'].lower())

    session.flush()

    player_name_to_id_map = {}
    # Add players (roster)
    for p_data in data.get("roster", []):
        old_team_id = p_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue

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
        player_name_to_id_map[(player.name, new_team_id)] = player.id

    # Add games
    game_id_map = {}
    for g_data in data.get("games", []):
        old_team_id = g_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue

        game = Game(
            date=parse_date(g_data['date']),
            time=g_data.get('time'),
            opponent=g_data['opponent'],
            location=g_data.get('location', ''),
            game_notes=g_data.get('game_notes', ''),
            team_id=new_team_id
        )
        session.add(game)
        session.flush()
        game_id_map[g_data['id']] = game.id

    # Add lineups (with transformation)
    for l_data in data.get("lineups", []):
        old_team_id = l_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue

        # This handles both the old list-of-dicts and new list-of-strings format
        lineup_data = l_data.get('lineup_positions', [])
        player_names = []
        if isinstance(lineup_data, str):
             try:
                 lineup_data = json.loads(lineup_data)
             except json.JSONDecodeError:
                 lineup_data = [] # Treat as empty if it's a non-JSON string

        if lineup_data and isinstance(lineup_data, list) and len(lineup_data) > 0 and isinstance(lineup_data[0], dict):
            player_names = [p['name'] for p in lineup_data if isinstance(p, dict) and 'name' in p]
        elif lineup_data and isinstance(lineup_data, list):
            player_names = lineup_data # It's already in the correct list-of-strings format

        new_game_id = game_id_map.get(l_data.get('associated_game_id'))

        lineup = Lineup(
            title=l_data['title'],
            lineup_positions=player_names,
            associated_game_id=new_game_id,
            team_id=new_team_id
        )
        session.add(lineup)

    # Add Rotations
    for r_data in data.get("rotations", []):
        old_team_id = r_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue

        new_game_id = game_id_map.get(r_data.get('associated_game_id'))

        innings_data = r_data.get('innings', {})
        if isinstance(innings_data, str):
            try:
                innings_data = json.loads(innings_data)
            except json.JSONDecodeError:
                innings_data = {}


        rotation = Rotation(
            title=r_data['title'],
            innings=innings_data,
            associated_game_id=new_game_id,
            team_id=new_team_id
        )
        session.add(rotation)

    # Add Pitching Outings
    for po_data in data.get("pitching", []):
        old_team_id = po_data.get('team_id')
        new_team_id = team_map.get(old_team_id)
        if not new_team_id: continue

        # The old data might have 'pitcher' as the player's name
        pitcher_name = po_data.get('pitcher') or po_data.get('player_name')
        if not pitcher_name:
            print(f"Warning: Pitching outing found without a pitcher name. Skipping. Data: {po_data}")
            continue

        player_id = player_name_to_id_map.get((pitcher_name, new_team_id))
        if not player_id:
            print(f"Warning: Could not find player '{pitcher_name}' for a pitching outing. Skipping.")
            continue

        outing = PitchingOuting(
            date=parse_date(po_data['date']),
            player_id=player_id,
            opponent=po_data.get('opponent', ''),
            pitches=po_data.get('pitches', 0),
            innings=po_data.get('innings', 0.0),
            pitcher_type=po_data.get('pitcher_type', 'Starter'),
            outing_type=po_data.get('outing_type', 'Game'),
            team_id=new_team_id,
            game_id=game_id_map.get(po_data.get('game_id'))
        )
        session.add(outing)


    session.commit()
    print("\nData migration complete.")

except Exception as e:
    session.rollback()
    print(f"Migration failed: {e}")
finally:
    session.close()
