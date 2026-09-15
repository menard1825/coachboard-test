from datetime import date, timedelta, datetime
import io
import logging
import warnings
import zoneinfo

from PIL import Image
from werkzeug.utils import secure_filename


logger = logging.getLogger(__name__)

# --- Team logo upload validation -------------------------------------------
#
# This is the single authoritative source for which logo file types
# CoachBoard accepts. app.py's ALLOWED_EXTENSIONS config is derived from
# this set rather than hardcoding its own copy, so the two can never
# disagree. SVG is intentionally excluded: a same-origin uploaded SVG is
# served with Content-Type image/svg+xml, and a browser that navigates to
# it directly (not just via <img>) will execute any embedded <script> --
# a stored-XSS path that also bypasses this app's same-origin CSRF check.
ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Extension -> the Pillow format name the decoded bytes must match. Both
# .jpg and .jpeg map to Pillow's 'JPEG'; there is deliberately no format
# that maps from an extension we don't accept (svg, gif, ...).
_LOGO_EXTENSION_TO_PILLOW_FORMAT = {'png': 'PNG', 'jpg': 'JPEG', 'jpeg': 'JPEG'}

# Passed as Image.open(..., formats=...) on every open below, so Pillow
# never even attempts to sniff/dispatch to any other registered plugin
# (PSD, FITS, TIFF, EPS, GIF, WebP, ...) before CoachBoard's own format
# check runs -- the decoder itself is restricted to what this app accepts,
# not just the result checked afterward.
_ALLOWED_PILLOW_FORMATS = ('PNG', 'JPEG')

# Pillow format -> the canonical extension CoachBoard stores it under. The
# original filename's extension is never used for the stored basename.
_LOGO_PILLOW_FORMAT_TO_STORED_EXTENSION = {'PNG': 'png', 'JPEG': 'jpg'}

MAX_LOGO_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MiB
MAX_LOGO_DIMENSION = 4096
MAX_LOGO_DECODED_PIXELS = 16_777_216  # 4096 * 4096

# A lightweight early check on the *whole request's* Content-Length, used
# by the route before it even touches request.files, so an obviously
# oversized multipart request can be rejected without parsing the form at
# all. This is not the authoritative limit -- it allows headroom for
# multipart boundary/header overhead on top of the actual file, and it
# does nothing when Content-Length is absent (e.g. chunked requests). The
# real limit is the bounded stream read inside
# read_and_validate_logo_upload(), which enforces MAX_LOGO_UPLOAD_BYTES
# against the file's own bytes regardless of how the request got there.
MAX_LOGO_REQUEST_BYTES = MAX_LOGO_UPLOAD_BYTES + 64 * 1024  # + multipart overhead headroom


class LogoUploadRejected(Exception):
    """Raised when an uploaded team logo fails validation. The message is
    written to be shown to the end user as-is: never a filesystem path or
    a library exception's internal text."""


def model_to_dict(obj):
    """Convert a SQLAlchemy model instance into a JSON-friendly dictionary."""
    if obj is None:
        return None
    result = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if isinstance(value, datetime):
            result[column.name] = value.isoformat()
        elif isinstance(value, date):
            result[column.name] = value.strftime('%Y-%m-%d')
        else:
            result[column.name] = value
    return result


def pitching_outing_to_dict(outing):
    if not outing:
        return None
    result = model_to_dict(outing)
    result['player_name'] = outing.player.name if outing.player else 'Unknown'
    return result


# Pitch Smart is game-pitch-count based. USSSA youth pitching limits are
# innings/outs based. Practice and lesson throws remain workload context only.
PITCHING_RULES = {
    'MLB Pitch Smart': {
        '7U': {'rule_type': 'pitch_count', 'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '8U': {'rule_type': 'pitch_count', 'max_daily': 50, 'rest_thresholds': [(20, 0), (35, 1), (50, 2)]},
        '9U': {'rule_type': 'pitch_count', 'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (75, 4)]},
        '10U': {'rule_type': 'pitch_count', 'max_daily': 75, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (75, 4)]},
        '11U': {'rule_type': 'pitch_count', 'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]},
        '12U': {'rule_type': 'pitch_count', 'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]},
        '13U': {'rule_type': 'pitch_count', 'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (95, 4)]},
        '14U': {'rule_type': 'pitch_count', 'max_daily': 95, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (95, 4)]},
        '15U': {'rule_type': 'pitch_count', 'max_daily': 95, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (75, 3), (95, 4)]},
        '16U': {'rule_type': 'pitch_count', 'max_daily': 95, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (75, 3), (95, 4)]},
        '17U': {'rule_type': 'pitch_count', 'max_daily': 105, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4)]},
        '18U': {'rule_type': 'pitch_count', 'max_daily': 105, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4)]},
        '19U': {'rule_type': 'pitch_count', 'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        '20U': {'rule_type': 'pitch_count', 'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        '21U': {'rule_type': 'pitch_count', 'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        '22U': {'rule_type': 'pitch_count', 'max_daily': 120, 'rest_thresholds': [(30, 0), (45, 1), (60, 2), (80, 3), (105, 4), (120, 5)]},
        'default': {'rule_type': 'pitch_count', 'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]},
    },
    'USSSA': {
        **{
            age: {
                'rule_type': 'innings',
                'next_day_max_outs': 9,
                'max_daily_outs': 18,
                'rolling_3_day_max_outs': 24,
                'max_consecutive_days': 3,
            }
            for age in ('7U', '8U', '9U', '10U', '11U', '12U')
        },
        **{
            age: {
                'rule_type': 'innings',
                'next_day_max_outs': 9,
                'max_daily_outs': 21,
                'rolling_3_day_max_outs': 24,
                'max_consecutive_days': 3,
            }
            for age in ('13U', '14U')
        },
        'default': {
            'rule_type': 'innings',
            'next_day_max_outs': 9,
            'max_daily_outs': 18,
            'rolling_3_day_max_outs': 24,
            'max_consecutive_days': 3,
        },
    },
}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS


def read_and_validate_logo_upload(file_storage):
    """Validate an uploaded team logo end-to-end and return (data, stored_extension).

    The submitted filename and the browser-supplied MIME type are never
    trusted as the security decision -- the extension is only checked for
    agreement with what the bytes actually decode as via Pillow. Reads at
    most MAX_LOGO_UPLOAD_BYTES + 1 bytes so an oversized upload is rejected
    without ever buffering it in full.

    Raises LogoUploadRejected (safe to show directly to the user) on any
    failure. The caller must not touch the existing logo file or
    team.logo_path until this has returned successfully.
    """
    filename = file_storage.filename or ''
    safe_name = secure_filename(filename)
    if not safe_name or not allowed_file(safe_name):
        raise LogoUploadRejected('Invalid file type. Allowed types are: png, jpg, jpeg.')

    submitted_ext = safe_name.rsplit('.', 1)[1].lower()
    expected_format = _LOGO_EXTENSION_TO_PILLOW_FORMAT[submitted_ext]

    data = file_storage.stream.read(MAX_LOGO_UPLOAD_BYTES + 1)
    if not data:
        raise LogoUploadRejected('No file was uploaded.')
    if len(data) > MAX_LOGO_UPLOAD_BYTES:
        raise LogoUploadRejected('That logo file is too large. The maximum size is 5 MB.')

    # Cheap header-only parse first: get the claimed format and dimensions
    # without decoding any pixel data, so an oversized image is rejected
    # before any expensive/memory-risky full decode is ever attempted.
    try:
        with Image.open(io.BytesIO(data), formats=_ALLOWED_PILLOW_FORMATS) as probe:
            decoded_format = probe.format
            width, height = probe.size
    except Exception:
        raise LogoUploadRejected('That file is not a valid PNG or JPEG image.')

    if decoded_format not in _LOGO_PILLOW_FORMAT_TO_STORED_EXTENSION:
        raise LogoUploadRejected('Only PNG and JPEG logos are supported.')
    if decoded_format != expected_format:
        raise LogoUploadRejected('The file contents do not match its file extension.')
    if width > MAX_LOGO_DIMENSION or height > MAX_LOGO_DIMENSION or width * height > MAX_LOGO_DECODED_PIXELS:
        raise LogoUploadRejected(
            f'That image is too large. Maximum size is {MAX_LOGO_DIMENSION}x{MAX_LOGO_DIMENSION} pixels.'
        )

    # Only now -- once the claimed dimensions are already known to be
    # within limits -- force a full decode to catch truncation/corruption
    # that a header-only parse can miss. Pillow's own decompression-bomb
    # protection is a Python warning by default; escalate it to an
    # exception so it fails closed here too, even though our explicit
    # dimension/pixel checks above are what actually keep this call safe.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=_ALLOWED_PILLOW_FORMATS) as verify_image:
                verify_image.verify()
            with Image.open(io.BytesIO(data), formats=_ALLOWED_PILLOW_FORMATS) as load_image:
                load_image.load()
    except Exception:
        raise LogoUploadRejected('That file is not a valid PNG or JPEG image.')

    return data, _LOGO_PILLOW_FORMAT_TO_STORED_EXTENSION[decoded_format]


def get_pitching_rules_for_team(team):
    """Return a copy of the configured pitching rules for the team's age."""
    configured_name = getattr(team, 'pitching_rule_set', 'MLB Pitch Smart') or 'MLB Pitch Smart'
    age_group = getattr(team, 'age_group', 'default') or 'default'

    rule_set = PITCHING_RULES.get(configured_name)
    effective_name = configured_name
    source_note = None
    if rule_set is None:
        rule_set = PITCHING_RULES['MLB Pitch Smart']
        effective_name = 'MLB Pitch Smart'
        source_note = f'Unknown configured ruleset "{configured_name}"; using MLB Pitch Smart until the team setting is corrected.'

    effective_age = age_group
    if effective_name == 'MLB Pitch Smart' and age_group in {'4U', '5U', '6U'}:
        effective_age = '7U'
        source_note = 'MLB Pitch Smart publishes its first pitch-count table at ages 7–8; using that guidance for this younger team setting.'

    if effective_name == 'USSSA' and age_group not in rule_set:
        source_note = f'USSSA youth limits for {age_group} are not explicitly configured; verify the event rules before relying on eligibility.'

    rules = dict(rule_set.get(effective_age, rule_set.get('default', {})))
    rules['rule_set_name'] = effective_name
    rules['configured_rule_set_name'] = configured_name
    rules['age_group'] = age_group
    rules['source_note'] = source_note
    return rules


def baseball_innings_to_outs(value):
    """Convert baseball notation (2.1 = 7 outs) to outs; reject .3, .4, etc."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if '.' in text:
            whole_text, frac_text = text.split('.', 1)
            whole = int(whole_text or '0')
            frac_text = (frac_text or '0').rstrip('0') or '0'
            if frac_text not in {'0', '1', '2'}:
                return None
            partial_outs = int(frac_text)
        else:
            whole = int(text)
            partial_outs = 0
    except (TypeError, ValueError):
        return None
    if whole < 0:
        return None
    return whole * 3 + partial_outs


def outs_to_baseball_innings(outs):
    if outs is None:
        return None
    try:
        outs = int(outs)
    except (TypeError, ValueError):
        return None
    if outs < 0:
        return None
    return f'{outs // 3}.{outs % 3}'


def normalize_baseball_innings(value):
    outs = baseball_innings_to_outs(value)
    if outs is None:
        return None
    return float(outs_to_baseball_innings(outs))


def _is_game_outing(outing):
    return str(getattr(outing, 'outing_type', None) or 'Game').strip().lower() == 'game'


def calculate_cumulative_pitching_stats(player_id, all_outings):
    """Calculate game pitching totals by outs, never decimal-float addition."""
    total_outs = 0
    total_pitches = 0
    appearances = 0
    incomplete_innings = False

    for outing in all_outings:
        if outing.player_id != player_id or not _is_game_outing(outing):
            continue
        appearances += 1
        if outing.pitches is not None:
            try:
                total_pitches += int(outing.pitches)
            except (TypeError, ValueError):
                pass
        outs = baseball_innings_to_outs(outing.innings)
        if outs is None:
            incomplete_innings = True
        else:
            total_outs += outs

    return {
        'total_innings_pitched': outs_to_baseball_innings(total_outs),
        'total_outs_pitched': total_outs,
        'total_pitches_thrown': total_pitches,
        'appearances': appearances,
        'innings_history_complete': not incomplete_innings,
    }


def calculate_cumulative_position_stats(roster_players, rotations):
    stats = {player.name: {} for player in roster_players}
    game_rotations_counted = set()
    for rotation in rotations:
        rotation_key = rotation.associated_game_id or rotation.id
        if rotation_key in game_rotations_counted:
            continue
        try:
            innings_data = rotation.innings or {}
            if not isinstance(innings_data, dict):
                continue
            positions_seen = set()
            for positions in innings_data.values():
                for position, player_name in positions.items():
                    key = (player_name, position)
                    if player_name in stats and key not in positions_seen:
                        stats[player_name][position] = stats[player_name].get(position, 0) + 1
                        positions_seen.add(key)
            game_rotations_counted.add(rotation_key)
        except Exception:
            continue
    return stats


def _required_rest_days(pitches, thresholds):
    if pitches is None:
        return None
    if pitches <= 0:
        return 0
    for threshold, rest_days in thresholds or []:
        if pitches <= threshold:
            return rest_days
    return (thresholds[-1][1] + 1) if thresholds else 0


def calculate_pitch_count_summary(roster, all_outings, rules, target_date=None, all_targets=None, team_timezone=None, current_game_id=None):
    """Calculate official eligibility, separate throwing workload, and targets.

    * Official Pitch Smart eligibility uses GAME pitches only.
    * Official USSSA eligibility uses GAME innings/outs only.
    * Practice/lesson pitches are workload context, not official competition usage.
    * Missing official values remain unknown; they are never silently zero-filled.
    """
    summary = {}
    tz = zoneinfo.ZoneInfo(team_timezone) if team_timezone else zoneinfo.ZoneInfo('America/Indiana/Indianapolis')

    if target_date is None:
        today = datetime.now(tz).date()
    elif isinstance(target_date, datetime):
        today = target_date.date() if target_date.tzinfo is None else target_date.astimezone(tz).date()
    elif isinstance(target_date, str):
        today = datetime.strptime(target_date, '%Y-%m-%d').date()
    else:
        today = target_date

    all_targets = all_targets or []
    rule_type = rules.get('rule_type', 'pitch_count')
    rule_set_name = rules.get('rule_set_name', 'MLB Pitch Smart')

    def local_date(value):
        if isinstance(value, datetime):
            return value.date() if value.tzinfo is None else value.astimezone(tz).date()
        return value

    for player in roster:
        try:
            player_outings = sorted(
                [o for o in all_outings if o.player_id == player.id and isinstance(o.date, (datetime, date))],
                key=lambda o: o.date,
                reverse=True,
            )
            game_outings = [o for o in player_outings if _is_game_outing(o)]

            today_workload = [o for o in player_outings if local_date(o.date) == today]
            week_workload = [o for o in player_outings if 0 <= (today - local_date(o.date)).days < 7]
            today_games = [o for o in game_outings if local_date(o.date) == today]
            week_games = [o for o in game_outings if 0 <= (today - local_date(o.date)).days < 7]

            workload_daily_complete = all(o.pitches is not None for o in today_workload)
            workload_weekly_complete = all(o.pitches is not None for o in week_workload)
            workload_daily_known = sum(int(o.pitches) for o in today_workload if o.pitches is not None)
            workload_weekly_known = sum(int(o.pitches) for o in week_workload if o.pitches is not None)
            workload_daily_pitches = workload_daily_known if workload_daily_complete else None
            workload_weekly_pitches = workload_weekly_known if workload_weekly_complete else None

            official_daily_complete = all(o.pitches is not None for o in today_games)
            official_weekly_complete = all(o.pitches is not None for o in week_games)
            official_daily_known = sum(int(o.pitches) for o in today_games if o.pitches is not None)
            official_weekly_known = sum(int(o.pitches) for o in week_games if o.pitches is not None)
            official_daily_pitches = official_daily_known if official_daily_complete else None
            official_weekly_pitches = official_weekly_known if official_weekly_complete else None

            games_by_date = {}
            for outing in game_outings:
                games_by_date.setdefault(local_date(outing.date), []).append(outing)

            status = 'Available'
            status_detail = ''
            next_available = 'Today'
            official_history_complete = True
            last_game_outing = 'N/A'
            if game_outings:
                last_game_outing = local_date(game_outings[0].date).strftime('%a, %b %d')

            max_daily = None
            pitches_remaining_today = None
            daily_outs = None
            rolling_3_day_outs = None
            innings_remaining_today_outs = None

            if rule_type == 'pitch_count':
                max_daily = int(rules.get('max_daily', 85))
                thresholds = rules.get('rest_thresholds', [])

                relevant_dates = [d for d in games_by_date if 0 <= (today - d).days <= 7]
                missing_game_counts = any(
                    o.pitches is None for d in relevant_dates for o in games_by_date[d]
                )

                if missing_game_counts:
                    status = 'Pitch Count Incomplete'
                    status_detail = 'Verify missing game pitch counts before using this pitcher.'
                    next_available = 'Verify game pitch counts'
                    official_history_complete = False
                else:
                    for outing_date in sorted((d for d in games_by_date if d < today), reverse=True):
                        day_pitches = sum(int(o.pitches) for o in games_by_date[outing_date])
                        rest_days = _required_rest_days(day_pitches, thresholds)
                        eligible_date = outing_date + timedelta(days=rest_days + 1)
                        if today < eligible_date:
                            status = 'Resting'
                            status_detail = f'{day_pitches} game pitches on {outing_date.strftime("%a, %b %d")} require {rest_days} day(s) rest.'
                            next_available = eligible_date.strftime('%a, %b %d')
                            break

                    if status == 'Available' and (today - timedelta(days=1)) in games_by_date and (today - timedelta(days=2)) in games_by_date:
                        status = 'Resting'
                        status_detail = 'Pitch Smart: do not pitch on a third consecutive day.'
                        next_available = (today + timedelta(days=1)).strftime('%a, %b %d')

                    if status == 'Available' and today_games:
                        if not official_daily_complete:
                            status = 'Pitch Count Incomplete'
                            status_detail = 'Verify today\'s game pitch count.'
                            next_available = 'Verify game pitch counts'
                            official_history_complete = False
                        else:
                            today_rest_days = _required_rest_days(official_daily_pitches, thresholds)
                            after_today_date = today + timedelta(days=today_rest_days + 1)

                            same_current_game_only = (
                                current_game_id is not None
                                and all(o.game_id is not None and int(o.game_id) == int(current_game_id) for o in today_games)
                            )
                            other_game_today = not same_current_game_only

                            if official_daily_pitches >= max_daily:
                                status = 'Resting'
                                status_detail = f'Daily game-pitch maximum reached ({max_daily}).'
                                next_available = after_today_date.strftime('%a, %b %d')
                            elif other_game_today:
                                status = 'Same-Day Game Restriction'
                                status_detail = 'Pitch Smart guidance: do not pitch in multiple games on the same day.'
                                next_available = after_today_date.strftime('%a, %b %d')

                if official_daily_pitches is not None and status == 'Available':
                    pitches_remaining_today = max(0, max_daily - official_daily_pitches)

            elif rule_type == 'innings':
                next_day_max_outs = int(rules.get('next_day_max_outs', 9))
                max_daily_outs = int(rules.get('max_daily_outs', 18))
                rolling_max_outs = int(rules.get('rolling_3_day_max_outs', 24))

                relevant_dates = [d for d in games_by_date if 0 <= (today - d).days <= 3]
                missing_game_innings = any(
                    baseball_innings_to_outs(o.innings) is None
                    for d in relevant_dates for o in games_by_date[d]
                )

                if missing_game_innings:
                    status = 'Innings Incomplete'
                    status_detail = 'Verify missing game innings/outs before using this pitcher.'
                    next_available = 'Verify game innings'
                    official_history_complete = False
                else:
                    outs_by_date = {
                        d: sum(baseball_innings_to_outs(o.innings) or 0 for o in outings)
                        for d, outings in games_by_date.items()
                    }
                    daily_outs = outs_by_date.get(today, 0)
                    prior_two_outs = sum(outs_by_date.get(today - timedelta(days=n), 0) for n in (1, 2))
                    rolling_3_day_outs = prior_two_outs + daily_outs
                    innings_remaining_today_outs = max(
                        0,
                        min(max_daily_outs - daily_outs, rolling_max_outs - rolling_3_day_outs),
                    )

                    yesterday_outs = outs_by_date.get(today - timedelta(days=1), 0)
                    if yesterday_outs > next_day_max_outs:
                        status = 'Resting'
                        status_detail = f'Pitched {outs_to_baseball_innings(yesterday_outs)} IP yesterday; more than 3.0 IP requires today off.'
                        next_available = (today + timedelta(days=1)).strftime('%a, %b %d')
                    elif all(outs_by_date.get(today - timedelta(days=n), 0) > 0 for n in (1, 2, 3)):
                        status = 'Resting'
                        status_detail = 'USSSA: pitcher must rest after pitching on three consecutive days.'
                        next_available = (today + timedelta(days=1)).strftime('%a, %b %d')
                    elif innings_remaining_today_outs <= 0:
                        status = 'Ineligible'
                        status_detail = 'One-day or rolling three-day innings limit reached.'
                        next_available = (today + timedelta(days=1)).strftime('%a, %b %d')

            else:
                status = 'Verify Rules'
                status_detail = 'The configured pitching rule set is not supported for automatic eligibility.'
                next_available = 'Verify event rules'
                official_history_complete = False

            today_string = today.strftime('%Y-%m-%d')
            player_targets = [t for t in all_targets if t.player_id == player.id and t.local_date == today_string]
            game_target = next((t for t in player_targets if current_game_id is not None and t.game_id == current_game_id), None)
            daily_target = next((t for t in player_targets if t.game_id is None), None)
            target_obj = game_target or daily_target
            coach_target = target_obj.target_pitches if target_obj else None
            coach_target_reason = target_obj.reason if target_obj else None
            coach_target_remaining = None
            coach_target_reached = False

            if coach_target is not None:
                target_basis = None
                if game_target and current_game_id is not None:
                    exact_game = [o for o in today_games if o.game_id is not None and int(o.game_id) == int(current_game_id)]
                    if exact_game and all(o.pitches is not None for o in exact_game):
                        target_basis = sum(int(o.pitches) for o in exact_game)
                elif daily_target:
                    target_basis = official_daily_pitches

                if target_basis is not None:
                    coach_target_remaining = max(0, coach_target - target_basis)
                    coach_target_reached = target_basis >= coach_target

            eligibility_complete = official_history_complete
            if rule_type == 'pitch_count':
                eligibility_complete = eligibility_complete and official_weekly_complete

            summary[player.name] = {
                'id': player.id,
                'name': player.name,
                'rule_type': rule_type,
                'rule_set_name': rule_set_name,
                'daily': official_daily_pitches,
                'weekly': official_weekly_pitches,
                'daily_known_pitches': official_daily_known,
                'weekly_known_pitches': official_weekly_known,
                'pitch_history_complete': eligibility_complete,
                'official_daily_pitches': official_daily_pitches,
                'official_7_day_pitches': official_weekly_pitches,
                'workload_daily_pitches': workload_daily_pitches,
                'workload_7_day_pitches': workload_weekly_pitches,
                'workload_history_complete': workload_daily_complete and workload_weekly_complete,
                'status': status,
                'status_detail': status_detail,
                'next_available': next_available,
                'max_daily': max_daily,
                'pitches_remaining_today': pitches_remaining_today,
                'last_outing_display': last_game_outing,
                'daily_outs': daily_outs,
                'daily_innings': outs_to_baseball_innings(daily_outs) if daily_outs is not None else None,
                'rolling_3_day_outs': rolling_3_day_outs,
                'rolling_3_day_innings': outs_to_baseball_innings(rolling_3_day_outs) if rolling_3_day_outs is not None else None,
                'innings_remaining_today_outs': innings_remaining_today_outs,
                'innings_remaining_today': outs_to_baseball_innings(innings_remaining_today_outs) if innings_remaining_today_outs is not None else None,
                'coach_target': coach_target,
                'coach_target_reason': coach_target_reason,
                'coach_target_reached': coach_target_reached,
                'coach_target_remaining': coach_target_remaining,
            }
        except Exception:
            logger.exception('Error calculating pitching summary for %s (ID %s)', player.name, player.id)
            summary[player.name] = {
                'id': player.id,
                'name': player.name,
                'rule_type': rule_type,
                'rule_set_name': rule_set_name,
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
                'status': 'Eligibility Error',
                'status_detail': 'CoachBoard could not calculate pitching eligibility. Verify this player\'s pitching history before using them to pitch.',
                'next_available': 'Verify pitching history',
                'max_daily': None,
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

    return summary
