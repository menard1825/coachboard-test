from datetime import datetime, timedelta

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for

from db import db
from extensions import socketio
from game_day_helpers import (
    build_actual_game_report,
    build_game_followup_status,
    build_game_readiness,
    team_now,
)
from game_pitching_rules import (
    GamePitchingRule,
    RULE_SET_OPTIONS,
    game_rule_context,
    rule_name_context,
    game_rule_override,
    install_request_rule_adapters,
    rule_settings_payload,
)
from game_start_readiness import can_start_game
from models import (
    Game,
    Lineup,
    Player,
    PlayerGameAbsence,
    PlayerPitchTarget,
    Rotation,
    Team,
)


game_day_bp = Blueprint('game_day', __name__)


def _team_context():
    team_id = session.get('team_id')
    if not team_id:
        return None
    return db.session.get(Team, team_id)


# Distinct from None, which is a legitimate effective rule name: a team with no
# competition rule selected resolves to None, so None cannot mean "not supplied".
_RULE_PAYLOAD_UNSET = object()


def _readiness_for_game(game, team, *, rule_payload=_RULE_PAYLOAD_UNSET, **preloads):
    # build_game_readiness still uses the established team-based rules engine.
    # Temporarily expose this game's effective rules without changing Team data.
    #
    # **preloads forwards the optional roster/absences/rotation arguments so
    # readiness_api() can share one load with can_start_game(). Callers that
    # pass nothing get the original behaviour unchanged.
    #
    # rule_payload is the same optional sharing for the rule lookup.
    # game_rule_context() resolves the effective rule name by querying
    # game_pitching_rules and team_pitching_settings again, which readiness_api()
    # has already read for can_start_game(). When it hands that payload over,
    # enter the name-based context directly instead. Every other caller -- the
    # game-day home cards, the next-game card, the follow-up history cards and
    # the game report -- omits it and keeps game_rule_context() untouched.
    if rule_payload is _RULE_PAYLOAD_UNSET:
        with game_rule_context(team, game):
            return build_game_readiness(game, team, **preloads)

    with rule_name_context(team, rule_payload.get('effective')):
        return build_game_readiness(game, team, **preloads)


@game_day_bp.before_app_request
def apply_game_pitching_rule_context():
    """Make per-game pitching rules visible to existing game-state calculators."""
    install_request_rule_adapters()

    if 'logged_in' not in session or not session.get('team_id'):
        return None

    # Game Day's own endpoints need the real team default so they can display and
    # edit the override correctly. Their calculations use _readiness_for_game().
    if str(request.endpoint or '').startswith('game_day.'):
        return None

    game_id = (request.view_args or {}).get('game_id')
    try:
        game_id = int(game_id)
    except (TypeError, ValueError):
        return None

    override = game_rule_override(game_id, session['team_id'])
    if override and override.rule_set in RULE_SET_OPTIONS:
        g.coachboard_game_pitching_rule = override.rule_set
    return None


@game_day_bp.route('/game-day')
def game_day_home():
    team = _team_context()
    if not team or 'logged_in' not in session:
        return redirect(url_for('auth.login'))

    now = team_now(team)
    today = now.date()
    day_start = datetime.combine(today, datetime.min.time())
    next_day = day_start + timedelta(days=1)

    todays_games = db.session.query(Game).filter(
        Game.team_id == team.id,
        Game.date >= day_start,
        Game.date < next_day,
    ).order_by(Game.date.asc(), Game.start_time.asc(), Game.id.asc()).all()

    # Calculate today's readiness once so the same-day history section can tell
    # the difference between an upcoming/current game and one that has actually
    # been played. Previously a completed game stayed only under "Today's Games"
    # until midnight, which made Past Games appear to disappear on game day.
    todays_cards = [
        {'game': game, 'readiness': _readiness_for_game(game, team)}
        for game in todays_games
    ]

    game_cards = todays_cards
    focus_label = "Today's Games"
    if not game_cards:
        next_game = db.session.query(Game).filter(
            Game.team_id == team.id,
            Game.date >= next_day,
        ).order_by(Game.date.asc(), Game.start_time.asc(), Game.id.asc()).first()
        game_cards = [
            {'game': next_game, 'readiness': _readiness_for_game(next_game, team)}
        ] if next_game else []
        focus_label = 'Next Game'

    focus_ids = {item['game'].id for item in game_cards}

    # Keep postgame work visible after game day. This is especially important for
    # GameChanger, whose final pitching numbers may not be available immediately.
    followup_candidates = db.session.query(Game).filter(
        Game.team_id == team.id,
        Game.date < next_day,
    ).order_by(Game.date.desc(), Game.id.desc()).limit(20).all()
    # This loop classifies up to 20 candidates to keep at most six, so it uses
    # build_game_followup_status() rather than _readiness_for_game(): three
    # queries per candidate instead of twelve. The Postgame Follow-Up section
    # of game_day.html renders only item.game.*, readiness.status and
    # readiness.pitching_missing, which is exactly what the classifier returns.
    #
    # Today's games and the next-game card still get the full payload below --
    # they render readiness detail, and there is at most a handful of them.
    followup_cards = []
    for game in followup_candidates:
        if game.id in focus_ids:
            continue
        followup = build_game_followup_status(game, team.id)
        if followup is not None:
            followup_cards.append({'game': game, 'readiness': followup})
        if len(followup_cards) >= 6:
            break
    followup_ids = {item['game'].id for item in followup_cards}

    # Game Day doubles as the schedule manager. Keep a useful upcoming window
    # here instead of forcing coaches back to the legacy home-page Games tab.
    upcoming_query = db.session.query(Game).filter(
        Game.team_id == team.id,
        Game.date >= next_day,
    )
    if focus_ids:
        upcoming_query = upcoming_query.filter(~Game.id.in_(focus_ids))
    upcoming = upcoming_query.order_by(Game.date.asc(), Game.start_time.asc(), Game.id.asc()).limit(12).all()

    # Preserve schedule history. Include games from earlier dates plus games from
    # today that have actually reached postgame/completion. A game that still has
    # postgame work stays only in Postgame Follow-Up until that work is complete,
    # so the same game is never rendered twice on Game Day.
    historical_games = db.session.query(Game).filter(
        Game.team_id == team.id,
        Game.date < day_start,
    ).order_by(Game.date.desc(), Game.start_time.desc(), Game.id.desc()).all()

    same_day_history = []
    for item in todays_cards:
        readiness = item['readiness']
        if readiness.get('has_end_game') or readiness.get('status') in {
            'COMPLETE', 'GC STATS PENDING', 'NEEDS POSTGAME'
        }:
            same_day_history.append(item['game'])

    past_games = [
        game for game in [*same_day_history, *historical_games]
        if game.id not in focus_ids and game.id not in followup_ids
    ]

    return render_template(
        'game_day.html',
        current_team=team,
        game_cards=game_cards,
        followup_cards=followup_cards,
        focus_label=focus_label,
        local_now=now,
        upcoming=upcoming,
        past_games=past_games,
    )


@game_day_bp.route('/api/game-day/pitching-rule-options')
def pitching_rule_options():
    team = _team_context()
    if not team or 'logged_in' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401
    return jsonify({
        'status': 'success',
        'team_default': team.pitching_rule_set or 'MLB Pitch Smart',
        'options': list(RULE_SET_OPTIONS),
    })


@game_day_bp.route('/api/game-day/<int:game_id>/pitching-rules', methods=['GET', 'POST'])
def game_pitching_rules(game_id):
    team = _team_context()
    if not team or 'logged_in' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found.'}), 404

    if request.method == 'POST':
        if game.is_live:
            return jsonify({
                'status': 'error',
                'message': 'Pitching rules cannot be changed while the game is live. End Live Game first.',
            }), 409

        data = request.get_json(silent=True) or request.form
        requested = str(data.get('rule_set') or '').strip()
        override = game_rule_override(game.id, team.id)

        if requested.lower() in {'', 'default', 'team default', 'team_default'}:
            if override:
                db.session.delete(override)
        elif requested not in RULE_SET_OPTIONS:
            return jsonify({'status': 'error', 'message': 'Unsupported pitching rule set.'}), 400
        else:
            if not override:
                override = GamePitchingRule(game_id=game.id, team_id=team.id, rule_set=requested)
                db.session.add(override)
            else:
                override.rule_set = requested

        db.session.commit()
        socketio.emit('data_updated', {'message': f'Pitching rules updated for game vs {game.opponent}.'})

    return jsonify({'status': 'success', **rule_settings_payload(team, game)})


@game_day_bp.route('/game-day/add', methods=['POST'])
def add_game():
    """Create a game directly from the Game Day / Schedule experience."""
    team = _team_context()
    if not team or 'logged_in' not in session:
        return redirect(url_for('auth.login'))

    game_date_raw = str(request.form.get('game_date') or '').strip()
    opponent = str(request.form.get('game_opponent') or '').strip()
    requested_rule = str(request.form.get('pitching_rule_set') or '').strip()
    if not game_date_raw or not opponent:
        flash('Game date and opponent are required.', 'danger')
        return redirect(url_for('game_day.game_day_home'))
    if requested_rule and requested_rule not in RULE_SET_OPTIONS:
        flash('Invalid pitching rule set.', 'danger')
        return redirect(url_for('game_day.game_day_home'))

    try:
        game_date = datetime.strptime(game_date_raw, '%Y-%m-%d')
    except ValueError:
        flash('Invalid game date.', 'danger')
        return redirect(url_for('game_day.game_day_home'))

    game = Game(
        date=game_date,
        start_time=str(request.form.get('game_start_time') or '').strip(),
        opponent=opponent,
        location=str(request.form.get('game_location') or '').strip(),
        game_notes=str(request.form.get('game_notes') or '').strip(),
        team_id=team.id,
    )
    db.session.add(game)
    db.session.flush()

    # Guest players are opt-in for every game. Keep Game Day game creation
    # consistent with the legacy /add_game route by defaulting every guest Out.
    guest_player_ids = [
        player_id
        for (player_id,) in db.session.query(Player.id).filter_by(
            team_id=team.id,
            is_guest=True,
        ).all()
    ]
    db.session.add_all([
        PlayerGameAbsence(
            player_id=player_id,
            game_id=game.id,
            team_id=team.id,
        )
        for player_id in guest_player_ids
    ])

    if requested_rule:
        db.session.add(GamePitchingRule(
            game_id=game.id,
            team_id=team.id,
            rule_set=requested_rule,
        ))

    db.session.commit()
    socketio.emit('data_updated', {'message': f'Game vs {game.opponent} added.'})
    flash(f'Game vs {game.opponent} added.', 'success')
    return redirect(url_for('gameday.game_management', game_id=game.id))


def delete_game_and_related(game, team):
    """Authoritative cleanup for a permanently deleted game.

    This is CoachBoard's one canonical game-deletion implementation. Every
    caller (dashboard, Game Day) must route through this function so the
    cleanup list cannot drift between two independent implementations again.

    Refuses to delete a live game and mutates nothing in that case. This is
    the one place that rule is enforced, so any future caller inherits it
    automatically instead of depending on the calling route remembering to
    check game.is_live itself.

    Lineup/Rotation/PlayerPitchTarget/GamePitchingRule/GameNextInningPrep use
    integer game ids rather than an ORM relationship with cascade, so they are
    removed explicitly here. PlayerGameAbsence, PitchingOuting,
    GameRotationEvent, and GamePitchingPlan already cascade via the Game
    model's own relationships; GameClockState cascades at the database level.
    Deleting a game's PitchingOuting history along with it is existing,
    intentional behavior and is not changed here.

    Returns True if the game was deleted, False if it was live and nothing
    was mutated. Callers are responsible for the team-scoped lookup and for
    committing afterward so the whole operation stays one transaction.
    """
    if game.is_live:
        return False

    db.session.query(Lineup).filter_by(
        associated_game_id=game.id,
        team_id=team.id,
    ).delete(synchronize_session=False)
    db.session.query(Rotation).filter_by(
        associated_game_id=game.id,
        team_id=team.id,
    ).delete(synchronize_session=False)
    db.session.query(PlayerPitchTarget).filter_by(
        game_id=game.id,
        team_id=team.id,
    ).delete(synchronize_session=False)
    db.session.query(GamePitchingRule).filter_by(
        game_id=game.id,
        team_id=team.id,
    ).delete(synchronize_session=False)

    # Next-inning prep is defined in the compatibility live-game module. Import
    # locally to avoid coupling Game Day module initialization to that model.
    from blueprints.live_game_ui import GameNextInningPrep
    db.session.query(GameNextInningPrep).filter_by(
        game_id=game.id,
        team_id=team.id,
    ).delete(synchronize_session=False)

    db.session.delete(game)
    return True


@game_day_bp.route('/game-day/<int:game_id>/delete', methods=['POST'])
def delete_game(game_id):
    """Delete a scheduled/test game from Game Day without allowing live-game loss."""
    team = _team_context()
    if not team or 'logged_in' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401

    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found.'}), 404

    opponent = game.opponent
    if not delete_game_and_related(game, team):
        return jsonify({
            'status': 'error',
            'message': 'A live game cannot be deleted. End the game first.',
        }), 409

    db.session.commit()
    socketio.emit('data_updated', {'message': f'Game vs {opponent} deleted.'})
    return jsonify({
        'status': 'success',
        'message': f'Game vs {opponent} deleted.',
    })


@game_day_bp.route('/api/game-day/<int:game_id>/readiness')
def readiness_api(game_id):
    team = _team_context()
    if not team or 'logged_in' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'}), 401
    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        return jsonify({'status': 'error', 'message': 'Game not found.'}), 404

    # can_start_game() and build_game_readiness() each used to load the roster,
    # this game's absences and its rotation for themselves, so one request read
    # all three twice. Load them once here and hand the same objects to both.
    # The roster is name-ordered because build_game_readiness() needs that
    # ordering; can_start_game() uses the roster for membership only, so the
    # ordered list is safe for it too.
    #
    # These objects are request-local by construction. Nothing here is cached
    # between requests.
    roster = db.session.query(Player).filter_by(team_id=team.id).order_by(Player.name).all()
    absences = db.session.query(PlayerGameAbsence).filter_by(
        game_id=game.id,
        team_id=team.id,
    ).all()
    rotation = db.session.query(Rotation).filter_by(
        associated_game_id=game.id,
        team_id=team.id,
    ).first()

    # Both consumers need this game's effective pitching rules, and each used to
    # resolve them for itself: can_start_game() through rule_settings_payload()
    # and build_game_readiness() through game_rule_context(). Resolve once here
    # and hand the same dict to both.
    #
    # Request-local and game-specific by construction: a plain local, resolved
    # from the `game` loaded above and passed straight into the two calls below.
    # Nothing is memoized on g, the Team, the Game, a module global, or any
    # cross-request structure.
    rule_payload = rule_settings_payload(team, game)

    start_readiness = can_start_game(
        game,
        team,
        roster=roster,
        absences=absences,
        rotation=rotation,
        rule_payload=rule_payload,
    )
    return jsonify({
        'status': 'success',
        **start_readiness,
        'readiness': _readiness_for_game(
            game,
            team,
            roster=roster,
            absences=absences,
            rotation=rotation,
            rule_payload=rule_payload,
        ),
    })


@game_day_bp.route('/game-day/<int:game_id>/report')
def game_report(game_id):
    team = _team_context()
    if not team or 'logged_in' not in session:
        return redirect(url_for('auth.login'))
    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        return redirect(url_for('game_day.game_day_home'))

    readiness = _readiness_for_game(game, team)
    report = build_actual_game_report(game, team)
    return render_template(
        'game_report.html',
        current_team=team,
        game=game,
        readiness=readiness,
        report=report,
    )


@game_day_bp.route('/game-day/<int:game_id>/notes', methods=['POST'])
def save_game_notes(game_id):
    team = _team_context()
    if not team or 'logged_in' not in session:
        return redirect(url_for('auth.login'))
    game = db.session.query(Game).filter_by(id=game_id, team_id=team.id).first()
    if not game:
        flash('Game not found.', 'danger')
        return redirect(url_for('game_day.game_day_home'))

    game.game_notes = str(request.form.get('game_notes') or '').strip()
    db.session.commit()
    flash('Game notes saved.', 'success')
    return redirect(url_for('game_day.game_report', game_id=game.id))