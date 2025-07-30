import sys
from app import create_app  # Import the app factory
from models import db, User, Team

# Create an app instance to work with the database context
app = create_app()

def list_users():
    """Prints a list of all users and their associated team."""
    print("--- User & Team Assignments ---")
    users = User.query.all()
    if not users:
        print("No users found in the database.")
        return

    for user in users:
        if user.team_id:
            team = Team.query.get(user.team_id)
            team_name = team.name if team else "Invalid Team ID"
            print(f"Username: {user.username:<20} Team ID: {user.team_id:<5} Team Name: {team_name}")
        else:
            print(f"Username: {user.username:<20} Team ID: {'None':<5} Team Name: Not Assigned")
    print("-----------------------------")


def list_teams():
    """Prints a list of all teams and their IDs."""
    print("--- Available Teams ---")
    teams = Team.query.all()
    if not teams:
        print("No teams found in the database.")
        return
        
    for team in teams:
        print(f"Team ID: {team.id:<5} Team Name: {team.name}")
    print("-----------------------")


def set_user_team(username, team_id):
    """Assigns a user to a team."""
    user = User.query.filter_by(username=username).first()
    if not user:
        print(f"Error: User '{username}' not found.")
        return

    try:
        team_id = int(team_id)
        team = Team.query.get(team_id)
        if not team:
            print(f"Error: Team with ID '{team_id}' not found.")
            return
            
        user.team_id = team_id
        db.session.commit()
        print(f"Success! User '{username}' has been assigned to Team '{team.name}' (ID: {team_id}).")

    except ValueError:
        print("Error: Team ID must be a number.")
    except Exception as e:
        db.session.rollback()
        print(f"An error occurred: {e}")


def print_usage():
    """Prints the help message."""
    print("\n--- User Management Script ---")
    print("Usage: python manage_users.py [command]")
    print("\nCommands:")
    print("  list-users          List all users and their assigned team.")
    print("  list-teams          List all available teams and their IDs.")
    print("  set-team [user] [id]  Assign a user to a team. e.g., 'python manage_users.py set-team coachbob 1'")
    print("----------------------------\n")


if __name__ == '__main__':
    # We need to be within the Flask application context to access the database
    with app.app_context():
        # Check command-line arguments passed to the script
        if len(sys.argv) < 2:
            print_usage()
        else:
            command = sys.argv[1]
            if command == 'list-users':
                list_users()
            elif command == 'list-teams':
                list_teams()
            elif command == 'set-team':
                if len(sys.argv) == 4:
                    username_arg = sys.argv[2]
                    team_id_arg = sys.argv[3]
                    set_user_team(username_arg, team_id_arg)
                else:
                    print("Error: 'set-team' command requires a username and a team ID.")
                    print_usage()
            else:
                print(f"Error: Unknown command '{command}'")
                print_usage()
