import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from werkzeug.security import generate_password_hash

# Import your models
from models import Base, Team, User

# --- Configuration ---
DATABASE_URL = 'sqlite:///app.db'
DEFAULT_TEAM_NAME = "Marucci Prospects Midwest 11u"
DEFAULT_REG_CODE = "Westfield"
SUPER_ADMIN_USERNAME = "Mike1825"
SUPER_ADMIN_PASSWORD = "password" # You can change this immediately after first login

# --- Script ---
def initialize_database():
    """
    Creates the database tables and populates it with essential initial data.
    """
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    print("Creating database tables...")
    # This creates all the tables defined in your models.py file
    Base.metadata.create_all(engine)
    print("Tables created.")

    try:
        # Check if the default team exists
        team = session.query(Team).filter_by(registration_code=DEFAULT_REG_CODE).first()
        if not team:
            print(f"Creating default team: {DEFAULT_TEAM_NAME}")
            team = Team(
                team_name=DEFAULT_TEAM_NAME,
                registration_code=DEFAULT_REG_CODE
            )
            session.add(team)
            session.flush()  # Flush to get the team.id for the user

        # Check if the super admin user exists
        admin_user = session.query(User).filter(User.username.ilike(SUPER_ADMIN_USERNAME)).first()
        if not admin_user:
            print(f"Creating Super Admin user: {SUPER_ADMIN_USERNAME}")
            hashed_password = generate_password_hash(SUPER_ADMIN_PASSWORD)
            default_tab_keys = ['roster', 'player_development', 'lineups', 'pitching', 'scouting_list', 'rotations', 'games', 'collaboration', 'practice_plan', 'signs']
            
            new_user = User(
                username=SUPER_ADMIN_USERNAME,
                full_name="Mike", # Adding a default full_name for the super admin
                password_hash=hashed_password,
                role='Super Admin',
                team_id=team.id,
                tab_order=json.dumps(default_tab_keys),
                player_order=json.dumps([])
            )
            session.add(new_user)

        session.commit()
        print("\nDatabase initialized successfully!")
        print(f"You can now log in with username '{SUPER_ADMIN_USERNAME}' and password '{SUPER_ADMIN_PASSWORD}'.")

    except Exception as e:
        session.rollback()
        print(f"An error occurred: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    initialize_database()