import sqlite3
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/pitching_log', methods=['GET'])
def get_pitching_log():
    conn = get_db_connection()
    pitching_log = conn.execute('SELECT * FROM pitching_log').fetchall()
    conn.close()
    return jsonify([dict(row) for row in pitching_log])

@app.route('/api/pitching_log', methods=['POST'])
def add_pitching_log():
    conn = get_db_connection()
    new_log = request.get_json()
    conn.execute('INSERT INTO pitching_log (pitcher_name, pitch_type, pitch_velocity) VALUES (?, ?, ?)',
                 (new_log['pitcher_name'], new_log['pitch_type'], new_log['pitch_velocity']))
    conn.commit()
    conn.close()
    return jsonify(new_log)