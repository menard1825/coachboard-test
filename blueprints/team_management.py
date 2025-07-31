from flask import Blueprint, request, redirect, url_for, flash, session, jsonify
from models import (
    CollaborationNote, PracticePlan, PracticeTask, Sign, Player, PlayerPracticeAbsence
)
from db import db
from extensions import socketio
from datetime import datetime

team_management_bp = Blueprint('team_management', __name__, template_folder='templates')

# --- Collaboration Notes Routes ---
@team_management_bp.route('/add_note/<note_type>', methods=['POST'])
def add_note(note_type):
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
    db.session.add(new_note)
    db.session.commit()
    flash('Note added successfully!', 'success')
    socketio.emit('data_updated', {'message': 'New note added.'})
    return redirect(url_for('home', _anchor='collaboration'))

@team_management_bp.route('/edit_note', methods=['POST'])
def edit_note():
    note_id = int(request.form.get('note_id'))
    note_type = request.form.get('note_type')
    new_text = request.form.get('note_text')
    
    note_to_edit = db.session.query(CollaborationNote).filter_by(id=note_id, team_id=session['team_id']).first()
    if not note_to_edit or note_to_edit.note_type != note_type:
        flash('Note not found or invalid note type.', 'danger')
        return redirect(url_for('home', _anchor='collaboration'))
        
    author_name = session.get('full_name') or session.get('username')
    if author_name == note_to_edit.author or session.get('role') in ['Head Coach', 'Super Admin']:
        note_to_edit.text = new_text
        db.session.commit()
        flash('Note updated successfully.', 'success')
        socketio.emit('data_updated', {'message': 'Note updated.'})
    else:
        flash('You do not have permission to edit this note.', 'danger')
    return redirect(url_for('home', _anchor='collaboration'))

@team_management_bp.route('/delete_note/<note_type>/<int:note_id>')
def delete_note(note_type, note_id):
    note_to_delete = db.session.query(CollaborationNote).filter_by(id=note_id, team_id=session['team_id']).first()
    if note_to_delete and note_to_delete.note_type == note_type:
        author_name = session.get('full_name') or session.get('username')
        if author_name == note_to_delete.author or session.get('role') in ['Head Coach', 'Super Admin']:
            db.session.delete(note_to_delete)
            db.session.commit()
            flash('Note deleted successfully.', 'success')
            socketio.emit('data_updated', {'message': 'Note deleted.'})
        else:
            flash('You do not have permission to delete this note.', 'danger')
    else:
        flash('Note not found or invalid note type.', 'danger')
    return redirect(url_for('home', _anchor='collaboration'))

# --- Practice Plan Routes ---
@team_management_bp.route('/add_practice_plan', methods=['POST'])
def add_practice_plan():
    plan_date = request.form.get('plan_date')
    if not plan_date:
        flash('Practice date is required.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
    new_plan = PracticePlan(
        date=plan_date, 
        general_notes=request.form.get('general_notes', ''),
        emphasis=request.form.get('emphasis', ''),
        warm_up=request.form.get('warm_up', ''),
        infield_outfield=request.form.get('infield_outfield', ''),
        hitting=request.form.get('hitting', ''),
        pitching_catching=request.form.get('pitching_catching', ''),
        team_id=session['team_id']
    )
    db.session.add(new_plan)
    db.session.commit()
    flash('New practice plan created!', 'success')
    socketio.emit('data_updated', {'message': 'New practice plan created.'})
    return redirect(url_for('home', _anchor='practice_plan'))

@team_management_bp.route('/edit_practice_plan/<int:plan_id>', methods=['POST'])
def edit_practice_plan(plan_id):
    plan_to_edit = db.session.get(PracticePlan, plan_id)
    if plan_to_edit and plan_to_edit.team_id == session['team_id']:
        plan_to_edit.date = request.form.get('plan_date', plan_to_edit.date)
        plan_to_edit.general_notes = request.form.get('general_notes', plan_to_edit.general_notes)
        plan_to_edit.emphasis = request.form.get('emphasis', plan_to_edit.emphasis)
        plan_to_edit.warm_up = request.form.get('warm_up', plan_to_edit.warm_up)
        plan_to_edit.infield_outfield = request.form.get('infield_outfield', plan_to_edit.infield_outfield)
        plan_to_edit.hitting = request.form.get('hitting', plan_to_edit.hitting)
        plan_to_edit.pitching_catching = request.form.get('pitching_catching', plan_to_edit.pitching_catching)
        db.session.commit()
        flash('Practice plan updated successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Practice plan updated.'})
    else:
        flash('Practice plan not found.', 'danger')
    return redirect(url_for('home', _anchor=f'plan-{plan_id}'))

@team_management_bp.route('/delete_practice_plan/<int:plan_id>')
def delete_practice_plan(plan_id):
    plan_to_delete = db.session.get(PracticePlan, plan_id)
    if plan_to_delete and plan_to_delete.team_id == session['team_id']:
        db.session.query(PracticeTask).filter_by(practice_plan_id=plan_to_delete.id).delete()
        db.session.delete(plan_to_delete)
        db.session.commit()
        flash('Practice plan deleted successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Practice plan deleted.'})
    else:
        flash('Practice plan not found.', 'danger')
    return redirect(url_for('home', _anchor='practice_plan'))

@team_management_bp.route('/update_practice_attendance/<int:plan_id>', methods=['POST'])
def update_practice_attendance(plan_id):
    team_id = session['team_id']
    plan = db.session.query(PracticePlan).filter_by(id=plan_id, team_id=team_id).first()
    if not plan:
        return jsonify({'status': 'error', 'message': 'Practice plan not found'}), 404

    absent_player_ids = [int(pid) for pid in request.form.getlist('absent_players')]
    
    db.session.query(PlayerPracticeAbsence).filter_by(practice_plan_id=plan_id, team_id=team_id).delete()

    for player_id in absent_player_ids:
        player = db.session.query(Player).filter_by(id=player_id, team_id=team_id).first()
        if player:
            new_absence = PlayerPracticeAbsence(player_id=player.id, practice_plan_id=plan.id, team_id=team_id)
            db.session.add(new_absence)
    
    db.session.commit()
    flash('Practice attendance updated successfully!', 'success')
    socketio.emit('data_updated', {'message': f'Attendance updated for plan {plan_id}.'})
    return redirect(url_for('home', _anchor=f'plan-{plan_id}'))

# --- Practice Task Routes ---
@team_management_bp.route('/add_task_to_plan/<int:plan_id>', methods=['POST'])
def add_task_to_plan(plan_id):
    task_text = request.form.get('task_text')
    if not task_text:
        flash('Task cannot be empty.', 'warning')
        return redirect(url_for('home', _anchor=f'plan-{plan_id}'))

    plan = db.session.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
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
    db.session.add(new_task)
    db.session.commit()
    
    flash('Task added to plan.', 'success')
    socketio.emit('data_updated', {'message': 'Task added to plan.'})
    return redirect(url_for('home', _anchor=f'plan-{plan_id}'))

@team_management_bp.route('/delete_task/<int:plan_id>/<int:task_id>')
def delete_task(plan_id, task_id):
    plan = db.session.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
    if not plan:
        flash('Practice plan not found.', 'danger')
        return redirect(url_for('home', _anchor='practice_plan'))
    task_to_delete = db.session.query(PracticeTask).filter_by(id=task_id, practice_plan_id=plan.id).first()
    if task_to_delete:
        db.session.delete(task_to_delete)
        db.session.commit()
        flash('Task deleted.', 'success')
        socketio.emit('data_updated', {'message': 'Task deleted from plan.'})
    else: 
        flash('Task not found.', 'danger')
    return redirect(url_for('home', _anchor=f'plan-{plan_id}'))

@team_management_bp.route('/update_task_status/<int:plan_id>/<int:task_id>', methods=['POST'])
def update_task_status(plan_id, task_id):
    plan = db.session.query(PracticePlan).filter_by(id=plan_id, team_id=session['team_id']).first()
    if not plan:
        return jsonify({'status': 'error', 'message': 'Plan not found'}), 404
    task = db.session.query(PracticeTask).filter_by(id=task_id, practice_plan_id=plan.id).first()
    if not task:
        return jsonify({'status': 'error', 'message': 'Task not found'}), 404
    
    request_data = request.get_json()
    new_status = request_data.get('status')
    if new_status not in ['pending', 'complete']:
        return jsonify({'status': 'error', 'message': 'Invalid status'}), 400
    
    task.status = new_status
    db.session.commit()
    socketio.emit('data_updated', {'message': 'Task status updated.'})
    return jsonify({'status': 'success', 'message': 'Task status updated.'})

# --- Signs Routes ---
@team_management_bp.route('/add_sign', methods=['POST'])
def add_sign():
    sign_name = request.form.get('sign_name')
    sign_indicator = request.form.get('sign_indicator')
    if sign_name and sign_indicator:
        new_sign = Sign(name=sign_name, indicator=sign_indicator, team_id=session['team_id'])
        db.session.add(new_sign)
        db.session.commit()
        flash('Sign added successfully!', 'success')
        socketio.emit('data_updated', {'message': 'New sign added.'})
    else:
        flash('Sign Name and Indicator are required.', 'danger')
    return redirect(url_for('home', _anchor='signs'))

@team_management_bp.route('/update_sign/<int:sign_id>', methods=['POST'])
def update_sign(sign_id):
    sign_to_update = db.session.query(Sign).filter_by(id=sign_id, team_id=session['team_id']).first()
    if not sign_to_update:
        flash('Sign not found.', 'danger')
        return redirect(url_for('home', _anchor='signs'))
    sign_name = request.form.get('sign_name')
    sign_indicator = request.form.get('sign_indicator')
    if sign_name and sign_indicator:
        sign_to_update.name = sign_name
        sign_to_update.indicator = sign_indicator
        db.session.commit()
        flash('Sign updated successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Sign updated.'})
    else:
        flash('Sign Name and Indicator are required.', 'danger')
    return redirect(url_for('home', _anchor='signs'))

@team_management_bp.route('/delete_sign/<int:sign_id>')
def delete_sign(sign_id):
    sign_to_delete = db.session.query(Sign).filter_by(id=sign_id, team_id=session['team_id']).first()
    if sign_to_delete:
        db.session.delete(sign_to_delete)
        db.session.commit()
        flash('Sign deleted successfully!', 'success')
        socketio.emit('data_updated', {'message': 'Sign deleted.'})
    else:
        flash('Sign not found.', 'danger')
    return redirect(url_for('home', _anchor='signs'))
