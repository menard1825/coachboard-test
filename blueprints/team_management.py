from flask import Blueprint, request, redirect, url_for, flash, session, jsonify, render_template
from models import (
    CollaborationNote, PracticePlan, PracticeTask, Sign
)
from db import SessionLocal
from extensions import socketio
from datetime import datetime

team_management_bp = Blueprint('team_management', __name__, template_folder='templates')

# --- Collaboration Notes Routes ---
@team_management_bp.route('/add_note/<note_type>', methods=['POST'])
def add_note(note_type):
    db = SessionLocal()
    try:
        if note_type not in ['player_notes', 'team_notes']:
            flash('Invalid note type.', 'danger')
            return redirect(url_for('home', _anchor='collaboration'))
        note_text = request.form.get('note_text')
        if not note_text:
            flash('Note cannot be empty.', 'warning')
            return redirect(url_for('home', _anchor='collaboration'))
        
        author_name = session.get('full_name') or session.get('username')
        
        new_note = CollaborationNote(
            note_type=note_type, 
            text=note_text, 
            author=author_name, 
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"), 
            team_id=session['team_id']
        )

        if note_type == 'player_notes':
            player_name = request.form.get('player_name')
            if not player_name:
                flash('You must select a player.', 'warning')
                return redirect(url_for('home', _anchor='collaboration'))
            new_note.player_name = player_name
        db.add(new_note)
        db.commit()
        flash('Note added successfully!', 'success')
        socketio.emit('data_updated', {'message': 'New note added.'})
        return redirect(url_for('home', _anchor='collaboration'))
    finally:
        db.close()

@team_management_bp.route('/edit_note', methods=['POST'])
def edit_note():
    db = SessionLocal()
    try:
        note_id = int(request.form.get('note_id'))
        note_type = request.form.get('note_type')
        new_text = request.form.get('note_text')
        
        note_to_edit = db.query(CollaborationNote).filter_by(id=note_id, team_id=session['team_id']).first()
        if not note_to_edit or note_to_edit.note_type != note_type:
            flash('Note not found or invalid note type.', 'danger')
            return redirect(url_for('home', _anchor='collaboration'))
            
        author_name = session.get('full_name') or session.get('username')
        if author_name == note_to_edit.author or session.get('role') in ['Head Coach', 'Super Admin']:
            note_to_edit.text = new_text
            db.commit()
            flash('Note updated successfully.', 'success')
            socketio.emit('data_updated', {'message': 'Note updated.'})
        else:
            flash('You do not have permission to edit this note.', 'danger')
        return redirect(url_for('home', _anchor='collaboration'))
    finally:
        db.close()

@team_management_bp.route('/delete_note/<note_type>/<int:note_id>')
def delete_note(note_type, note_id):
    db = SessionLocal()
    try:
        note_to_delete = db.query(CollaborationNote).filter_by(id=note_id, team_id=session['team_id']).first()
        if note_to_delete and note_to_delete.note_type == note_type:
            author_name = session.get('full_name') or session.get('username')
            if author_name == note_to_delete.author or session.get('role') in ['Head Coach', 'Super Admin']:
                db.delete(note_to_delete)
                db.commit()
                flash('Note deleted successfully.', 'success')
                socketio.emit('data_updated', {'message': 'Note deleted.'})
            else:
                flash('You do not have permission to delete this note.', 'danger')
        else:
            flash('Note not found or invalid note type.', 'danger')
        return redirect(url_for('home', _anchor='collaboration'))
    finally:
        db.close()

# ADDED: New function to handle moving a note
@team_management_bp.route('/move_note_to_practice_plan/<note_type>/<int:note_id>', methods=['GET', 'POST'])
def move_note_to_practice_plan(note_type, note_id):
    db = SessionLocal()
    try:
        note = db.query(CollaborationNote).filter_by(id=note_id, team_id=session['team_id']).first()
        if not note:
            flash('Note not found.', 'danger')
            return redirect(url_for('home', _anchor='collaboration'))

        if request.method == 'POST':
            plan_id = request.form.get('plan_id')
            plan = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
            if not plan:
                flash('Practice plan not found.', 'danger')
                return redirect(url_for('.move_note_to_practice_plan', note_type=note_type, note_id=note_id))

            # Create a new task from the note
            author_name = session.get('full_name') or session.get('username')
            task_text = f"From {note.author}'s note"
            if note.player_name:
                task_text += f" for {note.player_name}"
            task_text += f": \"{note.text}\""

            new_task = PracticeTask(
                text=task_text,
                status="pending",
                author=author_name,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
                practice_plan_id=plan.id
            )
            db.add(new_task)
            db.delete(note) # Delete the original note
            db.commit()

            flash('Note successfully moved to practice plan as a task!', 'success')
            socketio.emit('data_updated', {'message': 'Note moved to plan.'})
            return redirect(url_for('home', _anchor='collaboration'))

        # For a GET request, show the selection form
        practice_plans = db.query(PracticePlan).filter_by(team_id=session['team_id']).order_by(PracticePlan.date.desc()).all()
        return render_template('move_note_to_plan.html', note=note, practice_plans=practice_plans, note_type=note_type, note_id=note_id)

    finally:
        db.close()

# --- Practice Plan Routes ---
@team_management_bp.route('/add_practice_plan', methods=['POST'])
def add_practice_plan():
    db = SessionLocal()
    try:
        plan_date = request.form.get('plan_date')
        if not plan_date:
            flash('Practice date is required.', 'danger')
            return redirect(url_for('home', _anchor='practice_plan'))
        new_plan = PracticePlan(
            date=plan_date, 
            general_notes=request.form.get('general_notes', ''), 
            team_id=session['team_id']
        )
        db.add(new_plan)
        db.commit()
        flash('New practice plan created!', 'success')
        socketio.emit('data_updated', {'message': 'New practice plan created.'})
        return redirect(url_for('home', _anchor='practice_plan'))
    finally:
        db.close()

@team_management_bp.route('/edit_practice_plan/<int:plan_id>', methods=['POST'])
def edit_practice_plan(plan_id):
     db = SessionLocal()
     try:
        plan_to_edit = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
        if plan_to_edit:
            new_date = request.form.get('plan_date')
            new_notes = request.form.get('general_notes')
            if not new_date:
                flash('Plan date cannot be empty.', 'danger')
            else:
                plan_to_edit.date = new_date
                plan_to_edit.general_notes = new_notes
                db.commit()
                flash('Practice plan updated successfully!', 'success')
                socketio.emit('data_updated', {'message': 'Practice plan updated.'})
        else:
            flash('Practice plan not found.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
     finally:
        db.close()

@team_management_bp.route('/delete_practice_plan/<int:plan_id>')
def delete_practice_plan(plan_id):
     db = SessionLocal()
     try:
        plan_to_delete = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
        if plan_to_delete:
            db.query(PracticeTask).filter_by(practice_plan_id=plan_to_delete.id).delete()
            db.delete(plan_to_delete)
            db.commit()
            flash('Practice plan deleted successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Practice plan deleted.'})
        else:
            flash('Practice plan not found.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
     finally:
        db.close()

# --- Practice Task Routes ---
@team_management_bp.route('/add_task_to_plan/<int:plan_id>', methods=['POST'])
def add_task_to_plan(plan_id):
    db = SessionLocal()
    try:
        task_text = request.form.get('task_text')
        if not task_text:
            flash('Task cannot be empty.', 'warning')
            return redirect(url_for('home', _anchor='practice_plan'))

        plan = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
        if not plan:
            flash('Practice plan not found.', 'danger')
            return redirect(url_for('home', _anchor='practice_plan'))
        
        author_name = session.get('full_name') or session.get('username')
        
        new_task = PracticeTask(
            text=task_text, 
            status="pending", 
            author=author_name, 
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"), 
            practice_plan_id=plan.id
        )
        db.add(new_task)
        db.commit()
        
        flash('Task added to plan.', 'success')
        socketio.emit('data_updated', {'message': 'Task added to plan.'})
        return redirect(url_for('home', _anchor='practice_plan'))
    finally:
        db.close()

@team_management_bp.route('/delete_task/<int:plan_id>/<int:task_id>')
def delete_task(plan_id, task_id):
    db = SessionLocal()
    try:
        plan = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
        if not plan:
            flash('Practice plan not found.', 'danger')
            return redirect(url_for('home', _anchor='practice_plan'))
        task_to_delete = db.query(PracticeTask).filter_by(id=task_id, practice_plan_id=plan.id).first()
        if task_to_delete:
            db.delete(task_to_delete)
            db.commit()
            flash('Task deleted.', 'success')
            socketio.emit('data_updated', {'message': 'Task deleted from plan.'})
        else: 
            flash('Task not found.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
    finally:
        db.close()

@team_management_bp.route('/update_task_status/<int:plan_id>/<int:task_id>', methods=['POST'])
def update_task_status(plan_id, task_id):
    db = SessionLocal()
    try:
        plan = db.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
        if not plan:
            return jsonify({'status': 'error', 'message': 'Plan not found'}), 404
        task = db.query(PracticeTask).filter_by(id=task_id, practice_plan_id=plan.id).first()
        if not task:
            return jsonify({'status': 'error', 'message': 'Task not found'}), 404
        
        request_data = request.get_json()
        new_status = request_data.get('status')
        if new_status not in ['pending', 'complete']:
            return jsonify({'status': 'error', 'message': 'Invalid status'}), 400
        
        task.status = new_status
        db.commit()
        socketio.emit('data_updated', {'message': 'Task status updated.'})
        return jsonify({'status': 'success', 'message': 'Task status updated.'})
    finally:
        db.close()

# --- Signs Routes ---
@team_management_bp.route('/add_sign', methods=['POST'])
def add_sign():
    db = SessionLocal()
    try:
        sign_name = request.form.get('sign_name')
        sign_indicator = request.form.get('sign_indicator')
        if sign_name and sign_indicator:
            new_sign = Sign(name=sign_name, indicator=sign_indicator, team_id=session['team_id'])
            db.add(new_sign)
            db.commit()
            flash('Sign added successfully!', 'success')
            socketio.emit('data_updated', {'message': 'New sign added.'})
        else:
            flash('Sign Name and Indicator are required.', 'danger')
        return redirect(url_for('home', _anchor='signs'))
    finally:
        db.close()

@team_management_bp.route('/update_sign/<int:sign_id>', methods=['POST'])
def update_sign(sign_id):
    db = SessionLocal()
    try:
        sign_to_update = db.query(Sign).filter_by(id=sign_id, team_id=session['team_id']).first()
        if not sign_to_update:
            flash('Sign not found.', 'danger')
            return redirect(url_for('home', _anchor='signs'))
        sign_name = request.form.get('sign_name')
        sign_indicator = request.form.get('sign_indicator')
        if sign_name and sign_indicator:
            sign_to_update.name = sign_name
            sign_to_update.indicator = sign_indicator
            db.commit()
            flash('Sign updated successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Sign updated.'})
        else:
            flash('Sign Name and Indicator are required.', 'danger')
        return redirect(url_for('home', _anchor='signs'))
    finally:
        db.close()

@team_management_bp.route('/delete_sign/<int:sign_id>')
def delete_sign(sign_id):
    db = SessionLocal()
    try:
        sign_to_delete = db.query(Sign).filter_by(id=sign_id, team_id=session['team_id']).first()
        if sign_to_delete:
            db.delete(sign_to_delete)
            db.commit()
            flash('Sign deleted successfully!', 'success')
            socketio.emit('data_updated', {'message': 'Sign deleted.'})
        else:
            flash('Sign not found.', 'danger')
        return redirect(url_for('home', _anchor='signs'))
    finally:
        db.close()