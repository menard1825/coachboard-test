def suggested_regulation_innings(age_group):
    """Return the normal regulation-game default for the configured age group.

    CoachBoard uses the common USSSA baseball structure as the automatic default:
    4U-12U = 6 innings, 13U+ = 7 innings. A team can explicitly override this
    in Team Settings for a league or event with different rules.
    """
    text = str(age_group or '').strip().upper()
    digits = ''.join(ch for ch in text if ch.isdigit())
    try:
        age = int(digits)
    except (TypeError, ValueError):
        return 6
    return 7 if age >= 13 else 6


def regulation_innings_for_team(team):
    """Resolve the team's effective regulation innings.

    regulation_innings=None means Auto and follows the age-group suggestion.
    Explicit overrides are constrained to a practical baseball range.
    """
    override = getattr(team, 'regulation_innings', None)
    if override not in (None, ''):
        try:
            value = int(override)
            if 3 <= value <= 12:
                return value
        except (TypeError, ValueError):
            pass
    return suggested_regulation_innings(getattr(team, 'age_group', None))
