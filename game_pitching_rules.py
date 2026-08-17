from contextlib import contextmanager

from sqlalchemy.orm.attributes import set_committed_value

from db import db
from utils import PITCHING_RULES, get_pitching_rules_for_team


RULE_SET_OPTIONS = tuple(PITCHING_RULES.keys())


class GamePitchingRule(db.Model):
    __tablename__ = 'game_pitching_rules'

    id = db.Column(db.Integer, primary_key=True)
    rule_set = db.Column(db.String, nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id', ondelete='CASCADE'), nullable=False, unique=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False)


def game_rule_override(game_id, team_id):
    if not game_id or not team_id:
        return None
    return db.session.query(GamePitchingRule).filter_by(
        game_id=game_id,
        team_id=team_id,
    ).first()


def effective_rule_set_name(team, game=None):
    if game is not None:
        override = game_rule_override(game.id, team.id)
        if override and override.rule_set in RULE_SET_OPTIONS:
            return override.rule_set
    configured = getattr(team, 'pitching_rule_set', None) or 'MLB Pitch Smart'
    return configured if configured in RULE_SET_OPTIONS else 'MLB Pitch Smart'


def rule_settings_payload(team, game=None):
    override = game_rule_override(game.id, team.id) if game is not None else None
    team_default = getattr(team, 'pitching_rule_set', None) or 'MLB Pitch Smart'
    return {
        'team_default': team_default,
        'override': override.rule_set if override else None,
        'effective': effective_rule_set_name(team, game),
        'source': 'game' if override else 'team',
        'options': list(RULE_SET_OPTIONS),
    }


@contextmanager
def game_rule_context(team, game):
    """Temporarily expose a game's rule override to the existing rules engine.

    set_committed_value changes the in-memory mapped value without marking Team
    dirty, so a game override can never be persisted back over the team default
    when another game route commits.
    """
    original = getattr(team, 'pitching_rule_set', None)
    effective = effective_rule_set_name(team, game)
    set_committed_value(team, 'pitching_rule_set', effective)
    try:
        yield
    finally:
        set_committed_value(team, 'pitching_rule_set', original)


def pitching_rules_for_game(team, game):
    with game_rule_context(team, game):
        return get_pitching_rules_for_team(team)
