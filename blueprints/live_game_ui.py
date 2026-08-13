from flask import Blueprint, flash, redirect, render_template, session, url_for
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from db import db
from models import (
    Game,
    Lineup,
    PitchingOuting,
    Player,
    PlayerGameAbsence,
    PlayerPitchTarget,
    Rotation,
    Team,
)
from utils import calculate_pitch_count_summary, get_pitching_rules_for_team, model_to_dict

live_game_ui_bp = Blueprint('live_game_ui', __name__)


@live_game_ui_bp.route('/game/<int:game_id>')
def game_management_v2(game_id):
    team_id = session.get('team_id')
    if not team_id:
        return redirect(url_for('auth.login'))

    team = db.session.get(Team, team_id)
    game = db.session.query(Game).filter_by(id=game_id, team_id=team_id).first()
    if not team or not game:
        flash('Game not found.', 'danger')
        return redirect(url_for('home', _anchor='games'))

    roster_objects = db.session.query(Player).filter_by(team_id=team_id).order_by(Player.name).all()
    lineup_obj = db.session.query(Lineup).filter_by(associated_game_id=game.id, team_id=team_id).first()
    rotation_obj = db.session.query(Rotation).filter_by(associated_game_id=game.id, team_id=team_id).first()

    all_outings = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter_by(team_id=team_id).all()
    game_pitching_log = db.session.query(PitchingOuting).options(joinedload(PitchingOuting.player)).filter(
        PitchingOuting.team_id == team_id,
        or_(
            PitchingOuting.game_id == game.id,
            and_(
                PitchingOuting.game_id.is_(None),
                PitchingOuting.opponent == game.opponent,
                db.func.date(PitchingOuting.date) == game.date.date(),
            ),
        ),
    ).all()

    absences = db.session.query(PlayerGameAbsence).filter_by(game_id=game.id, team_id=team_id).all()
    absent_player_ids = [a.player_id for a in absences]
    all_targets = db.session.query(PlayerPitchTarget).filter_by(team_id=team_id).all()
    rules = get_pitching_rules_for_team(team)
    pitch_count_summary = calculate_pitch_count_summary(
        roster_objects,
        all_outings,
        rules,
        target_date=game.date,
        all_targets=all_targets,
        team_timezone=team.timezone,
        current_game_id=game.id,
    )

    lineup_templates = db.session.query(Lineup).filter_by(team_id=team_id, associated_game_id=None).all()
    rotation_templates = db.session.query(Rotation).filter_by(team_id=team_id, associated_game_id=None).all()

    def outing_dict(outing):
        data = model_to_dict(outing)
        data['player_name'] = outing.player.name if outing.player else None
        return data

    return render_template(
        'game_management_v2.html',
        current_team=team,
        game=model_to_dict(game),
        game_date_for_input=game.date.strftime('%Y-%m-%d'),
        roster=[model_to_dict(p) for p in roster_objects],
        lineup=model_to_dict(lineup_obj) if lineup_obj else None,
        rotation=model_to_dict(rotation_obj) if rotation_obj else None,
        game_pitching_log=[outing_dict(o) for o in game_pitching_log],
        session=session,
        absent_player_ids=absent_player_ids,
        pitch_count_summary=pitch_count_summary,
        lineup_templates=[model_to_dict(x) for x in lineup_templates],
        rotation_templates=[model_to_dict(x) for x in rotation_templates],
    )
