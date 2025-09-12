# menard1825/coachboard-test/coachboard-test-production-readiness-and-bug-fixes/export_to_json.py
import sqlite3
import json
import os
from datetime import datetime

def adapt_datetime(dt):
    """Adapter to store datetime objects as ISO 8601 strings."""
    return dt.isoformat()

def convert_datetime(s):
    """Converter to parse ISO 8601 strings back to datetime objects."""
    return datetime.fromisoformat(s.decode('utf-8'))

# Register the adapter and converter
sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("DATETIME", convert_datetime)

def export_db_to_json(db_path='app_old.db', json_path='data_backup.json'):
    """
    Reads data from a SQLite database and exports it to a JSON file
    in the format expected by migrate_data.py.
    """
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at '{db_path}'")
        return

    # Use detect_types to handle datetime conversion
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row  # This allows accessing columns by name
    cursor = conn.cursor()

    all_data = {}

    # Dynamically get all table names from the database
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = cursor.fetchall()
    table_names = [table['name'] for table in tables]

    print("Exporting data...")

    # Map DB table names to the keys expected in the JSON file
    table_to_json_key_map = {
        "players": "roster",
        "pitching_outings": "pitching",
        "player_development_focuses": "player_development_focuses_raw", # Temp key
    }

    for table_name in table_names:
        json_key = table_to_json_key_map.get(table_name, table_name)

        try:
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            all_data[json_key] = [dict(row) for row in rows]
            print(f"  - Exported {len(all_data[json_key])} rows from '{table_name}'")
        except sqlite3.OperationalError:
            print(f"  - Warning: Table '{table_name}' not found in the old database. Skipping.")
            all_data[json_key] = []

    # --- Restructure data to match migrate_data.py's expected format ---

    # Handle special structured data
    # Scouted Players
    scouting_list = {"committed": [], "targets": [], "not_interested": []}
    for player_data in all_data.get("scouted_players", []):
        list_type = player_data.get('list_type')
        if list_type in scouting_list:
            scouting_list[list_type].append(player_data)
    all_data["scouting_list"] = scouting_list

    # Collaboration Notes
    collab_notes = {"player_notes": [], "team_notes": []}
    for note_data in all_data.get("collaboration_notes", []):
        note_type = note_data.get('note_type')
        if note_type in collab_notes:
            collab_notes[note_type].append(note_data)
    all_data["collaboration_notes"] = collab_notes

    # Practice Plans and Tasks
    tasks_by_plan_id = {}
    for task in all_data.get("practice_tasks", []):
        plan_id = task.get('practice_plan_id')
        if plan_id:
            if plan_id not in tasks_by_plan_id:
                tasks_by_plan_id[plan_id] = []
            tasks_by_plan_id[plan_id].append(task)

    for plan in all_data.get("practice_plans", []):
        plan['tasks'] = tasks_by_plan_id.get(plan['id'], [])

    # Player Development Focuses
    player_dev_data = {}
    player_id_to_name = {p['id']: p['name'] for p in all_data.get('roster', [])}
    for focus in all_data.get('player_development_focuses_raw', []):
        player_name = player_id_to_name.get(focus.get('player_id'))
        skill_type = focus.get('skill_type')
        if player_name and skill_type:
            if player_name not in player_dev_data:
                player_dev_data[player_name] = {"hitting": [], "pitching": [], "fielding": [], "baserunning": []}
            if skill_type in player_dev_data[player_name]:
                 player_dev_data[player_name][skill_type].append(focus)
    all_data["player_development"] = player_dev_data

    # Clean up raw data to keep the final JSON clean
    for key in ['scouted_players', 'collaboration_notes', 'practice_tasks', 'player_development_focuses_raw']:
        if key in all_data:
            del all_data[key]


    with open(json_path, 'w') as f:
        json.dump(all_data, f, indent=4, default=str) # Use default=str for any types json doesn't know

    print(f"\nSuccessfully exported data to '{json_path}'")
    conn.close()

if __name__ == "__main__":
    export_db_to_json()