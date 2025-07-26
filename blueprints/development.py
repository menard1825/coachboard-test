from flask import Blueprint, request, redirect, url_for, flash, session
from models import Player, PlayerDevelopmentFocus
from db import SessionLocal
from app import socketio
from datetime import date, datetime

development_bp = Blueprint('development', __name__, template_folder='templates')

def find_focus_by_id(db_session, focus_id):
    return db_session.query(PlayerDevelopmentFocus).filter_by(id=focus_id).first()

@development_bp.route('/add_focus/<player_name>', methods=['POST'])
def add_focus(player_name):
    db = SessionLocal()
    try:
        player = db.query(Player).filter_by(name=player_name, team_id=session['team_id']).first()
        skill = request.form.get('skill')
        focus_text = request.form.get('focus_text')

        if not all([player, skill, focus_text]):
            flash('Skill, focus text, and valid player are required.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))

        new_focus = PlayerDevelopmentFocus(
            player_id=player.id, 
            skill_type=skill, 
            focus=focus_text, 
            status="active",
            notes=request.form.get('notes', ''), 
            author=session['username'],
            created_date=date.today().strftime('%Y-%m-%d'), 
            team_id=session['team_id']
        )
        db.add(new_focus)
        db.commit()
        flash(f'New {skill} focus added for {player_name}.', 'success')
        socketio.emit('data_updated', {'message': f'New focus added for {player_name}.'})
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@development_bp.route('/update_focus/<int:focus_id>', methods=['POST'])
def update_focus(focus_id):
    db = SessionLocal()
    try:
        focus_item = find_focus_by_id(db, focus_id)
        if not focus_item or focus_item.team_id != session['team_id']:
            flash('Focus item not found or you do not have permission to edit.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))

        focus_item.focus = request.form.get('focus_text', focus_item.focus)
        focus_item.notes = request.form.get('notes', focus_item.notes)
        focus_item.last_edited_by = session['username']
        focus_item.last_edited_date = datetime.now().strftime('%Y-%m-%d %H:%M')
        db.commit()
        flash('Focus item updated successfully.', 'success')
        socketio.emit('data_updated', {'message': 'Focus item updated.'})
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@development_bp.route('/complete_focus/<int:focus_id>')
def complete_focus(focus_id):
    db = SessionLocal()
    try:
        focus_item = find_focus_by_id(db, focus_id)
        if not focus_item or focus_item.team_id != session['team_id']:
            flash('Focus item not found or you do not have permission.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))

        focus_item.status = 'completed'
        focus_item.completed_date = date.today().strftime('%Y-%m-%d')
        db.commit()
        flash('Focus marked as complete!', 'success')
        socketio.emit('data_updated', {'message': 'Focus marked complete.'})
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@development_bp.route('/delete_focus/<int:focus_id>')
def delete_focus(focus_id):
    db = SessionLocal()
    try:
        focus_item = find_focus_by_id(db, focus_id)
        if focus_item and focus_item.team_id == session['team_id']:
            db.delete(focus_item)
            db.commit()
            flash('Focus deleted successfully.', 'success')
            socketio.emit('data_updated', {'message': 'Focus deleted.'})
        else:
            flash('Could not find the focus item to delete or you do not have permission.', 'danger')
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@development_bp.route('/update_lesson_info/<int:player_id>', methods=['POST'])
def update_lesson_info(player_id):
    db = SessionLocal()
    try:
        player = db.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
        if not player:
            flash('Player not found.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))
            
        player.has_lessons = request.form.get('has_lessons')
        player.lesson_focus = request.form.get('lesson_focus')
        player.notes_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M")
        db.commit()
        flash(f'Lesson info for {player.name} updated.', 'success')
        socketio.emit('data_updated', {'message': f'Lesson info for {player.name} updated.'})
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()

@development_bp.route('/delete_lesson_info/<int:player_id>')
def delete_lesson_info(player_id):
    db = SessionLocal()
    try:
        player = db.query(Player).filter_by(id=player_id, team_id=session['team_id']).first()
        if not player:
            flash('Player not found.', 'danger')
            return redirect(url_for('home', _anchor='player_development'))
            
        player.has_lessons = 'No'
        player.lesson_focus = ''
        db.commit()
        flash(f'Lesson info for {player.name} has been deleted.', 'success')
        socketio.emit('data_updated', {'message': f'Lesson info for {player.name} deleted.'})
        return redirect(url_for('home', _anchor='player_development'))
    finally:
        db.close()