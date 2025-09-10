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

def export_db_to_json(db_path, json_path):
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

    # List of tables to export. The key is the JSON key, the value is the DB table name.
    tables_to_export = {
        "teams": "teams",
        "users": "users",
        "roster": "players",
        "lineups": "lineups",
        "pitching": "pitching_outings",
        "rotations": "rotations",
        "games": "games",
        "practice_plans": "practice_plans",
        "signs": "signs",
    }

    print("Exporting data...")

    for json_key, table_name in tables_to_export.items():
        try:
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            all_data[json_key] = [dict(row) for row in rows]
            print(f"  - Exported {len(all_data[json_key])} rows from '{table_name}'")
        except sqlite3.OperationalError:
            print(f"  - Warning: Table '{table_name}' not found in the old database. Skipping.")
            all_data[json_key] = []

    # Handle special structured data
    # Scouted Players
    try:
        cursor.execute("SELECT * FROM scouted_players")
        rows = cursor.fetchall()
        scouting_list = {}
        for row in rows:
            list_type = row['list_type']
            if list_type not in scouting_list:
                scouting_list[list_type] = []
            scouting_list[list_type].append(dict(row))
        all_data["scouting_list"] = scouting_list
        print(f"  - Exported {len(rows)} rows from 'scouted_players'")
    except sqlite3.OperationalError:
        print("  - Warning: Table 'scouted_players' not found. Skipping.")

    # Collaboration Notes
    try:
        cursor.execute("SELECT * FROM collaboration_notes")
        rows = cursor.fetchall()
        collab_notes = {}
        for row in rows:
            note_type = row['note_type']
            if note_type not in collab_notes:
                collab_notes[note_type] = []
            collab_notes[note_type].append(dict(row))
        all_data["collaboration_notes"] = collab_notes
        print(f"  - Exported {len(rows)} rows from 'collaboration_notes'")
    except sqlite3.OperationalError:
        print("  - Warning: Table 'collaboration_notes' not found. Skipping.")

    # Player Development Focuses (This one is complex, adjust if needed)
    # This part is simplified; migrate_data.py handles the complex structure.
    # We just need to dump the raw data.
    try:
        cursor.execute("SELECT * FROM player_development_focuses")
        rows = cursor.fetchall()
        all_data["player_development_focuses"] = [dict(row) for row in rows]
        print(f"  - Exported {len(rows)} rows from 'player_development_focuses'")
    except sqlite3.OperationalError:
        print("  - Warning: Table 'player_development_focuses' not found. Skipping.")

    with open(json_path, 'w') as f:
        json.dump(all_data, f, indent=4, default=str) # Use default=str for any types json doesn't know

    print(f"\nSuccessfully exported data to '{json_path}'")
    conn.close()

if __name__ == "__main__":
    old_db_file = 'app_old.db' # The name of your old database backup file
    json_backup_file = 'data_backup.json'
    export_db_to_json(old_db_file, json_backup_file)