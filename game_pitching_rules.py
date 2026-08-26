from contextlib import contextmanager

from flask import g, has_request_context
from sqlalchemy.orm.attributes import set_committed_value

from blueprints.fair_play import pitching_preferences_for_team, pitching_rules_for_name
from db import db
from pitching_rule_presets import install_additional_pitching_rules
from utils import PITCHING_RULES, calculate_pitch_count_summary as _base_calculate_pitch_summary


install_additional_pitching_rules(PITCHING_RULES)
RULE_SET_OPTIONS = tuple(PITCHING_RULES.keys())
_CONTEXT_ATTR = 'coachboard_game_pitching_rule_context'


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
    return pitching_preferences_for_team(team)['competition_default_rule']


def rule_settings_payload(team, game=None):
    override = game_rule_override(game.id, team.id) if game is not None else None
    preferences = pitching_preferences_for_team(team)
    team_default = preferences['competition_default_rule']
    effective = effective_rule_set_name(team, game)
    if override:
        source = 'game'
    elif team_default:
        source = 'team'
    else:
        source = 'unselected'
    return {
        'team_default': team_default,
        'override': override.rule_set if override else None,
        'effective': effective,
        'source': source,
        'options': list(RULE_SET_OPTIONS),
        'arm_care_rule_set': preferences['arm_care_rule_set'],
    }


@contextmanager
def rule_name_context(team, rule_set_name):
    """Expose one game's competition rules to legacy calculators without persisting them."""
    original = getattr(team, 'pitching_rule_set', None)
    had_context = has_request_context() and hasattr(g, _CONTEXT_ATTR)
    previous_context = getattr(g, _CONTEXT_ATTR, None) if has_request_context() else None
    if has_request_context():
        setattr(g, _CONTEXT_ATTR, rule_set_name)
    set_committed_value(team, 'pitching_rule_set', rule_set_name)
    try:
        yield
    finally:
        set_committed_value(team, 'pitching_rule_set', original)
        if has_request_context():
            if had_context:
                setattr(g, _CONTEXT_ATTR, previous_context)
            else:
                try:
                    delattr(g, _CONTEXT_ATTR)
                except AttributeError:
                    pass


@contextmanager
def game_rule_context(team, game):
    with rule_name_context(team, effective_rule_set_name(team, game)):
        yield


def pitching_rules_for_game(team, game):
    return pitching_rules_for_name(team, effective_rule_set_name(team, game))


def _request_rule_name(team):
    if has_request_context() and hasattr(g, _CONTEXT_ATTR):
        return getattr(g, _CONTEXT_ATTR)
    override = getattr(g, 'coachboard_game_pitching_rule', None) if has_request_context() else None
    if override in RULE_SET_OPTIONS:
        return override
    return pitching_preferences_for_team(team)['competition_default_rule']


def request_aware_team_rules(team):
    """Return only the effective competition rules for eligibility displays."""
    return pitching_rules_for_name(team, _request_rule_name(team))


def request_aware_gameplay_rules(team):
    """Keep arm-care pitch guidance available even when competition rules are unset.

    Game Planning and Live Game still need useful pitch-count context such as the
    age-based Pitch Smart daily maximum. When a coach intentionally chooses no
    competition default, use the team's arm-care preset for that context while
    marking the rules as competition-unselected so it cannot masquerade as the
    tournament eligibility rule.
    """
    competition_rule = _request_rule_name(team)
    if competition_rule:
        return pitching_rules_for_name(team, competition_rule)

    preferences = pitching_preferences_for_team(team)
    arm_care_rule = preferences['arm_care_rule_set']
    if not arm_care_rule:
        return pitching_rules_for_name(team, None)

    rules = pitching_rules_for_name(team, arm_care_rule)
    rules['competition_unselected'] = True
    rules['competition_rule_set_name'] = None
    rules['arm_care_rule_set'] = arm_care_rule
    rules['rule_set_name'] = 'Rules Not Selected'
    rules['configured_rule_set_name'] = None
    rules['source_note'] = (
        'No competition pitching rules are selected for this game. Pitch-count '
        f'context below comes from the team arm-care setting ({arm_care_rule}) and '
        'does not establish tournament eligibility.'
    )
    return rules


def _missing_gameplay_summary(player, rules):
    """Return a fail-closed row when the base calculator cannot return one player."""
    max_daily = None
    if rules.get('rule_type') == 'pitch_count':
        try:
            max_daily = int(rules.get('max_daily', 85))
        except (TypeError, ValueError):
            max_daily = None
    return {
        'id': player.id,
        'name': player.name,
        'rule_type': rules.get('rule_type', 'unsupported'),
        'rule_set_name': rules.get('rule_set_name', 'Unknown'),
        'daily': None,
        'weekly': None,
        'daily_known_pitches': 0,
        'weekly_known_pitches': 0,
        'pitch_history_complete': False,
        'official_daily_pitches': None,
        'official_7_day_pitches': None,
        'workload_daily_pitches': None,
        'workload_7_day_pitches': None,
        'workload_history_complete': False,
        'status': 'Unavailable — Eligibility Error',
        'status_detail': (
            'CoachBoard could not calculate pitching eligibility for this player. '
            'Verify the pitching history before using this player to pitch.'
        ),
        'next_available': 'Verify pitching history',
        'max_daily': max_daily,
        'pitches_remaining_today': None,
        'last_outing_display': 'Unknown',
        'daily_outs': None,
        'daily_innings': None,
        'rolling_3_day_outs': None,
        'rolling_3_day_innings': None,
        'innings_remaining_today_outs': None,
        'innings_remaining_today': None,
        'coach_target': None,
        'coach_target_reason': None,
        'coach_target_reached': False,
        'coach_target_remaining': None,
    }


def _ensure_gameplay_summary_rows(roster, summary, rules):
    """Never let a calculator exception make a rostered player look available."""
    summary = summary if isinstance(summary, dict) else {}
    for player in roster:
        if not isinstance(summary.get(player.name), dict):
            summary[player.name] = _missing_gameplay_summary(player, rules)
    return summary


def _fail_closed_unknown_statuses(summary):
    """Make every non-Available eligibility state visibly non-selectable in Live Game."""
    for item in summary.values():
        status = str(item.get('status') or '').strip()
        lowered = status.lower()
        if status == 'Available':
            continue
        if lowered.startswith('unavailable') or 'rest' in lowered or 'ineligible' in lowered:
            continue
        item['status'] = f"Unavailable — {status or 'Eligibility Unknown'}"
        if not item.get('status_detail'):
            item['status_detail'] = 'Verify pitching eligibility before using this player to pitch.'
        if not item.get('next_available') or item.get('next_available') == 'Today':
            item['next_available'] = 'Verify pitching eligibility'
    return summary


def gameplay_pitch_summary(
    roster,
    all_outings,
    rules,
    target_date=None,
    all_targets=None,
    team_timezone=None,
    current_game_id=None,
):
    """Return gameplay pitching context without inventing eligibility.

    If no competition rules are selected, CoachBoard may still calculate arm-care
    pitch-count context, but official eligibility must fail closed. A coach must
    select or verify the event rules before Live Game can present a pitcher as
    available.
    """
    if not rules.get('competition_unselected'):
        summary = _base_calculate_pitch_summary(
            roster,
            all_outings,
            rules,
            target_date=target_date,
            all_targets=all_targets,
            team_timezone=team_timezone,
            current_game_id=current_game_id,
        )
        summary = _ensure_gameplay_summary_rows(roster, summary, rules)
        return _fail_closed_unknown_statuses(summary)

    if rules.get('rule_type') == 'pitch_count' and rules.get('max_daily'):
        proxy_rules = dict(rules)
        proxy_rules['rule_set_name'] = rules.get('arm_care_rule_set') or 'MLB Pitch Smart'
    else:
        age_group = rules.get('age_group') or 'default'
        pitch_smart = PITCHING_RULES['MLB Pitch Smart']
        effective_age = '7U' if age_group in {'4U', '5U', '6U'} else age_group
        proxy_rules = dict(pitch_smart.get(effective_age, pitch_smart['default']))
        proxy_rules.update({
            'rule_set_name': 'MLB Pitch Smart',
            'configured_rule_set_name': 'MLB Pitch Smart',
            'age_group': age_group,
            'source_note': rules.get('source_note'),
        })

    summary = _base_calculate_pitch_summary(
        roster,
        all_outings,
        proxy_rules,
        target_date=target_date,
        all_targets=all_targets,
        team_timezone=team_timezone,
        current_game_id=current_game_id,
    )
    summary = _ensure_gameplay_summary_rows(roster, summary, proxy_rules)
    for item in summary.values():
        # Preserve the advisory result separately so Game Planning can still show
        # useful arm-care context without presenting it as tournament eligibility.
        item['arm_care_status'] = item.get('status') or 'Unknown'
        item['arm_care_status_detail'] = item.get('status_detail') or ''
        item['arm_care_next_available'] = item.get('next_available')

        item['rule_type'] = 'none'
        item['rule_set_name'] = 'Rules Not Selected'
        item['status'] = 'Unavailable — Select Game Rules'
        item['status_detail'] = (
            'Competition pitching rules are not selected for this game. '
            'Select or verify the event rules before using this pitcher.'
        )
        item['next_available'] = 'Verify event rules'
        # Keep the arm-care daily max and remaining pitch context available to
        # the Game Planning UI. Those values remain guidance only.
    return summary


def install_request_rule_adapters():
    """Rebind legacy module imports to the new competition/arm-care preference layer."""
    gameplay_modules = (
        'blueprints.live_game_api',
        'blueprints.live_game_common',
        'blueprints.api',
        'blueprints.gameday',
        'game_day_helpers',
    )
    for module_name in gameplay_modules:
        try:
            module = __import__(module_name, fromlist=[module_name.rsplit('.', 1)[-1]])
            if hasattr(module, 'get_pitching_rules_for_team'):
                module.get_pitching_rules_for_team = request_aware_gameplay_rules
            if hasattr(module, 'calculate_pitch_count_summary'):
                module.calculate_pitch_count_summary = gameplay_pitch_summary
        except Exception:
            pass

    # The standalone Pitching dashboard explicitly treats competition eligibility
    # as unknown until event rules are selected. Its separate Arm Care column is
    # populated by the pitching-preferences API.
    try:
        pitching_module = __import__('blueprints.pitching', fromlist=['pitching'])
        if hasattr(pitching_module, 'get_pitching_rules_for_team'):
            pitching_module.get_pitching_rules_for_team = request_aware_team_rules
    except Exception:
        pass
