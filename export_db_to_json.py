import sqlite3
import json
import os

# Database URL
DATABASE_FILE = 'app.db'
OUTPUT_JSON_FILE = 'data_backup_from_db.json'

def export_data_to_json_direct_sqlite():
    if not os.path.exists(DATABASE_FILE):
        print(f"Error: Database file '{DATABASE_FILE}' not found. Please ensure your backup is named 'app.db' and is in the same directory.")
        return

    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # Get all table names (excluding sqlite_sequence and internal tables)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = cursor.fetchall()
        table_names = [table[0] for table in tables]

        data = {}

        for table_name in table_names:
            # Skip the new table if it somehow exists but is empty/problematic in the old DB
            # This is a safeguard, as the old DB shouldn't have it anyway.
            if table_name == 'player_game_absences':
                continue

            print(f"Exporting data from table: {table_name}")
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns_info = cursor.fetchall()
            column_names = [col[1] for col in columns_info]

            cursor.execute(f"SELECT * FROM {table_name};")
            rows = cursor.fetchall()

            table_data = []
            for row in rows:
                row_dict = {}
                for i, col_name in enumerate(column_names):
                    value = row[i]
                    # Attempt to parse JSON strings that might be stored as TEXT
                    if isinstance(value, str) and (value.startswith('[') or value.startswith('{')):
                        try:
                            row_dict[col_name] = json.loads(value)
                        except json.JSONDecodeError:
                            row_dict[col_name] = value # Keep as string if not valid JSON
                    else:
                        row_dict[col_name] = value
                table_data.append(row_dict)
            data[table_name] = table_data

        # Special handling for nested structures if needed (like player_development)
        # This part assumes your migrate_data.py can handle the flat structure or
        # you'll manually re-nest it if needed. For now, it exports flat tables.
        # If player_development was originally stored as separate rows per focus, this is fine.
        # If it was a single JSON blob per player, this direct export might need adjustment.
        # Based on your models.py, player_development_focuses is a separate table, so this should work.

        # Reformat into the structure expected by migrate_data.py
        # This assumes a specific structure for migrate_data.py
        # You might need to manually adjust this section based on your migrate_data.py's exact expectations.
        # For example, if 'roster' is expected, it should be 'players' table data.
        # If 'scouting_list' is expected as an object with 'committed', 'targets', etc., it needs re-grouping.

        # Let's try to map the flat table names to your expected JSON structure
        final_export_data = {
            "teams": data.get("teams", []),
            "users": data.get("users", []),
            "roster": data.get("players", []), # 'players' table maps to 'roster' in your JSON
            "lineups": data.get("lineups", []),
            "pitching": data.get("pitching_outings", []), # 'pitching_outings' table maps to 'pitching'
            "scouting_list": {"committed": [], "targets": [], "not_interested": []}, # Re-group scouted players
            "rotations": data.get("rotations", []),
            "games": data.get("games", []),
            "collaboration_notes": {"player_notes": [], "team_notes": []}, # Re-group notes
            "practice_plans": [], # Re-group plans and tasks
            "player_development": {}, # Re-group player development focuses
            "signs": data.get("signs", [])
        }

        # Re-group scouted_players
        for sp_data in data.get("scouted_players", []):
            list_type = sp_data.get('list_type')
            if list_type and list_type in final_export_data["scouting_list"]:
                final_export_data["scouting_list"][list_type].append(sp_data)

        # Re-group collaboration_notes
        for cn_data in data.get("collaboration_notes", []):
            note_type = cn_data.get('note_type')
            if note_type and note_type in final_export_data["collaboration_notes"]:
                final_export_data["collaboration_notes"][note_type].append(cn_data)

        # Re-group practice_plans and tasks
        # This assumes tasks are linked by practice_plan_id in the flat export
        practice_tasks_by_plan_id = {}
        for task in data.get("practice_tasks", []):
            plan_id = task.get('practice_plan_id')
            if plan_id not in practice_tasks_by_plan_id:
                practice_tasks_by_plan_id[plan_id] = []
            practice_tasks_by_plan_id[plan_id].append(task)

        for pp_data in data.get("practice_plans", []):
            plan_id = pp_data.get('id')
            pp_data['tasks'] = practice_tasks_by_plan_id.get(plan_id, [])
            final_export_data["practice_plans"].append(pp_data)

        # Re-group player_development_focuses
        player_names_map = {p['id']: p['name'] for p in data.get('players', [])}
        for pdf_data in data.get("player_development_focuses", []):
            player_id = pdf_data.get('player_id')
            player_name = player_names_map.get(player_id)
            if player_name:
                if player_name not in final_export_data["player_development"]:
                    final_export_data["player_development"][player_name] = {"hitting": [], "pitching": [], "fielding": [], "baserunning": []}
                skill_type = pdf_data.get('skill_type')
                if skill_type and skill_type in final_export_data["player_development"][player_name]:
                    final_export_data["player_development"][player_name][skill_type].append(pdf_data)
                else: # For new skill types or if not pre-defined
                    if skill_type:
                        final_export_data["player_development"][player_name][skill_type] = final_export_data["player_development"][player_name].get(skill_type, [])
                        final_export_data["player_development"][player_name][skill_type].append(pdf_data)


        with open(OUTPUT_JSON_FILE, 'w') as f:
            json.dump(final_export_data, f, indent=4)
        print(f"Data successfully exported to {OUTPUT_JSON_FILE}")

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during export: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    export_data_to_json_direct_sqlite()
