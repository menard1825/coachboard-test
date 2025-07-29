from app import create_app
from db import db
from models import Team, User
from werkzeug.security import generate_password_hash
import json

# Create an application instance to work with
app = create_app()

# --- Configuration ---
DEFAULT_TEAM_NAME = "Marucci Prospects Midwest 11u"
DEFAULT_REG_CODE = "Westfield"
SUPER_ADMIN_USERNAME = "Mike1825"
SUPER_ADMIN_PASSWORD = "password" # You can change this immediately after first login

# --- Script ---
def initialize_database():
    """
    Creates the database tables and populates it with essential initial data.
    """
    # Use the application context to interact with the database
    with app.app_context():
        # Flask-Migrate now handles table creation, but this is a good safeguard.
        db.create_all()

        try:
            # Check if the default team exists
            team = db.session.query(Team).filter_by(registration_code=DEFAULT_REG_CODE).first()
            if not team:
                print(f"Creating default team: {DEFAULT_TEAM_NAME}")
                team = Team(
                    team_name=DEFAULT_TEAM_NAME,
                    registration_code=DEFAULT_REG_CODE
                )
                db.session.add(team)
                db.session.flush()

            # Check if the super admin user exists
            admin_user = db.session.query(User).filter(User.username.ilike(SUPER_ADMIN_USERNAME)).first()
            if not admin_user:
                print(f"Creating Super Admin user: {SUPER_ADMIN_USERNAME}")
                hashed_password = generate_password_hash(SUPER_ADMIN_PASSWORD)
                default_tab_keys = ['roster', 'player_development', 'lineups', 'pitching', 'scouting_list', 'rotations', 'games', 'collaboration', 'practice_plan', 'signs']
                
                new_user = User(
                    username=SUPER_ADMIN_USERNAME,
                    full_name="Mike",
                    password_hash=hashed_password,
                    role='Super Admin',
                    team_id=team.id,
                    tab_order=json.dumps(default_tab_keys),
                    player_order=json.dumps([])
                )
                db.session.add(new_user)

            db.session.commit()
            print("\nDatabase initialized successfully!")
            print(f"You can now log in with username '{SUPER_ADMIN_USERNAME}' and password '{SUPER_ADMIN_PASSWORD}'.")

        except Exception as e:
            db.session.rollback()
            print(f"An error occurred: {e}")

if __name__ == "__main__":
    initialize_database()