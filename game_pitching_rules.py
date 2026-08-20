from contextlib import contextmanager

from flask import g, has_request_context
from sqlalchemy.orm.attributes import set_committed_value

from db import db
from pitching_rule_presets import install_additional_pitching_rules
from utils import PITCHING_RULES, get_pitching_rules_for_team as _base_team_rules


install_additional_pitching_rules(PITCHING_RULES)
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
def rule_name_context(team, rule_set_name):
    """Expose a ruleset to the existing team-based calculator without persisting it."""
    original = getattr(team, 'pitching_rule_set', None)
    set_committed_value(team, 'pitching_rule_set', rule_set_name)
    try:
        yield
    finally:
        set_committed_value(team, 'pitching_rule_set', original)


@contextmanager
def game_rule_context(team, game):
    with rule_name_context(team, effective_rule_set_name(team, game)):
        yield


def pitching_rules_for_game(team, game):
    with game_rule_context(team, game):
        return _base_team_rules(team)


def request_aware_team_rules(team):
    """Use the current game's override when an HTTP game route is being handled.

    The override name is kept on Flask's request context instead of the Team row,
    so a db.session.commit() during Live Game cannot accidentally erase or persist
    the temporary ruleset.
    """
    override = getattr(g, 'coachboard_game_pitching_rule', None) if has_request_context() else None
    if override in RULE_SET_OPTIONS:
        with rule_name_context(team, override):
            return _base_team_rules(team)
    return _base_team_rules(team)


def install_request_rule_adapters():
    """Point existing game-specific modules at the request-aware rules function."""
    # These modules imported get_pitching_rules_for_team directly before game
    # overrides existed. Rebind only their module-local reference so standalone
    # team pitching screens continue to use the team's default rules normally.
    for module_name in ('live_game_api', 'live_game_common', 'api', 'gameday'):
        try:
            module = __import__(f'blueprints.{module_name}', fromlist=[module_name])
            if hasattr(module, 'get_pitching_rules_for_team'):
                module.get_pitching_rules_for_team = request_aware_team_rules
        except Exception:
            pass
