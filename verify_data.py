# verify_data.py
from app import create_app
from models import (
    Team, User, Player, Lineup, PitchingOuting, ScoutedPlayer,
    Rotation, Game, CollaborationNote, PracticePlan, PlayerDevelopmentFocus, Sign
)

app = create_app()

with app.app_context():
    print("--- Verifying Data in New Database ---")

    # List of all models to check
    models_to_check = [
        Team, User, Player, Lineup, PitchingOuting, ScoutedPlayer,
        Rotation, Game, CollaborationNote, PracticePlan, PlayerDevelopmentFocus, Sign
    ]

    total_records = 0

    for model in models_to_check:
        try:
            count = model.query.count()
            print(f"- Found {count} records in the '{model.__tablename__}' table.")
            total_records += count
        except Exception as e:
            print(f"  - Error querying '{model.__tablename__}': {e}")

    print("--------------------------------------")
    print(f"Total records found across all tables: {total_records}")
    print("Verification complete.")
