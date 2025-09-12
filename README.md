CoachBoard - Team Management Application
Setup and Installation
This guide will walk you through setting up the CoachBoard application on your local machine for development.

1. Prerequisites
Python 3.8+

pip for installing Python packages

2. Installation
Clone the Repository (or use your existing code):
Make sure you have all the project files in a single directory.

Create a Virtual Environment:
It's highly recommended to use a virtual environment to manage project dependencies.

# For macOS/Linux
python3 -m venv venv
source venv/bin/activate

# For Windows
python -m venv venv
.\venv\Scripts\activate

Install Dependencies:
Install all the required packages using the requirements.txt file.

pip install -r requirements.txt

Set Up Environment Variables:
Create a file named .env in the root directory of the project. Copy the contents of .env.staging into it and update the values as needed.

FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=a-very-secret-key-for-development
DATABASE_URL=sqlite:///app.db
GOOGLE_MAPS_API_KEY=YOUR_GOOGLE_MAPS_API_KEY_HERE

Note: The SECRET_KEY should be a long, random string. You can generate one easily with Python: python -c 'import secrets; print(secrets.token_hex(24))'

3. Initialize the Database
With the fresh codebase, you need to create and initialize your database.

Initialize Flask-Migrate:
This command sets up the database migration tracking.

flask db init

Create the Initial Migration:
This command inspects your models and generates the first migration script to create all tables.

flask db migrate -m "Initial migration."

Apply the Migration:
This command applies the migration to your database, creating the app.db file and all the necessary tables.

flask db upgrade

Create the Default Super Admin User:
Run the init_db.py script to create the first team and the super admin user.

python init_db.py

You can now log in with the credentials specified in the script (default: Mike1825 / password).

4. Running the Application
You can now run the application using the provided run.py script, which uses Flask-SocketIO's server.

python run.py

The application will be available at http://127.0.0.1:5005.
