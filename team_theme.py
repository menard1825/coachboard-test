"""Team color theming: the one place team colors are validated and read.

A team's primary color paints the header, the main buttons and badges. What
sits on it -- text and icons -- has to stay readable whatever color a coach
picks, so the foreground is chosen here from the WCAG contrast ratio:

* white while white reaches 4.5:1 against the team color (most team colors,
  and what every dark theme looked like before);
* otherwise whichever of white and dark ink contrasts more -- dark ink on
  gold, yellow or white.

The team color is also drawn *as* text -- links, outlined buttons, the active
tab -- on white cards and the light page background. That is a different
contrast problem, so it gets its own color (--cb-primary-text): the team
color itself when it already reads there, otherwise the same hue darkened
just until it does. White and grey teams, which have no hue to keep, use
dark ink.

The danger color never comes from the team. A team color close to it is only
flagged, so the page can keep destructive buttons visibly different.

Colors are stored as the coach entered them and printed into a <style> block
in base.html, so anything that is not a plain hex color is replaced here with
a default before it gets there.
"""

import colorsys
import re

DEFAULT_PRIMARY = '#343a40'
DEFAULT_SECONDARY = '#e5e7eb'
LIGHT_FOREGROUND = '#ffffff'
DARK_FOREGROUND = '#172033'   # --cb-ink
DANGER = '#b42318'            # --cb-danger
# --cb-bg: the darkest of the light surfaces team-colored text is drawn on
# (cards are white, #ffffff).
LIGHT_SURFACE = '#f3f5f8'
AA_NORMAL_TEXT = 4.5
# CIE76 color difference below which a team color reads as the danger red.
NEAR_DANGER_DELTA_E = 25
# HSL saturation below which a color is treated as white/grey: no hue to keep.
NEUTRAL_SATURATION = 0.12

_HEX = re.compile(r'#([0-9a-f]{3}|[0-9a-f]{6})')


def normalize_hex(value):
    """'#ABC' / '#AABBCC' in any case -> '#aabbcc'; anything else -> None."""
    if not isinstance(value, str):
        return None
    match = _HEX.fullmatch(value.strip().lower())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = ''.join(ch * 2 for ch in digits)
    return f'#{digits}'


def _rgb(color):
    color = normalize_hex(color)
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _linear(channel):
    channel /= 255
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(color):
    r, g, b = (_linear(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first, second):
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def on_primary_color(primary):
    """The text/icon color for content sitting on the team color."""
    primary = normalize_hex(primary) or DEFAULT_PRIMARY
    if contrast_ratio(LIGHT_FOREGROUND, primary) >= AA_NORMAL_TEXT:
        return LIGHT_FOREGROUND
    if contrast_ratio(DARK_FOREGROUND, primary) > contrast_ratio(LIGHT_FOREGROUND, primary):
        return DARK_FOREGROUND
    return LIGHT_FOREGROUND


def _hex(r, g, b):
    return '#' + ''.join(f'{round(channel * 255):02x}' for channel in (r, g, b))


def primary_text_color(primary):
    """The team color to use for text, icons and outlines on light surfaces."""
    primary = normalize_hex(primary) or DEFAULT_PRIMARY
    if contrast_ratio(primary, LIGHT_SURFACE) >= AA_NORMAL_TEXT:
        return primary
    hue, lightness, saturation = colorsys.rgb_to_hls(*(c / 255 for c in _rgb(primary)))
    if saturation < NEUTRAL_SATURATION:
        return DARK_FOREGROUND

    def shade(level):
        return _hex(*colorsys.hls_to_rgb(hue, level, saturation))

    # Keep hue and saturation; find the lightest shade that still reads.
    readable, unreadable = 0.0, lightness
    for _ in range(24):
        middle = (readable + unreadable) / 2
        if contrast_ratio(shade(middle), LIGHT_SURFACE) >= AA_NORMAL_TEXT:
            readable = middle
        else:
            unreadable = middle
    return shade(readable)


def _lab(color):
    r, g, b = (_linear(c) for c in _rgb(color))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def is_near_danger(primary):
    primary = normalize_hex(primary) or DEFAULT_PRIMARY
    a, b = _lab(primary), _lab(DANGER)
    return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5 < NEAR_DANGER_DELTA_E


def readability_warnings(primary):
    """Plain-language notes for Team Settings. Informational only."""
    primary = normalize_hex(primary) or DEFAULT_PRIMARY
    foreground = on_primary_color(primary)
    warnings = []
    if contrast_ratio(foreground, primary) < AA_NORMAL_TEXT:
        warnings.append('Header and button text will be hard to read on this color, '
                        'whether it is shown light or dark.')
    text = primary_text_color(primary)
    if text != primary:
        warnings.append(f'On white backgrounds, links and outlined buttons will use a darker '
                        f'shade ({text}) so they stay readable. Your team color is not changed.')
    if is_near_danger(primary):
        warnings.append('This color is close to the red CoachBoard uses for Delete. Delete '
                        'buttons will be shown outlined so they stay distinct from your '
                        'main buttons.')
    return warnings


def theme_for(team):
    """Everything base.html needs to theme the page for this team."""
    primary = normalize_hex(getattr(team, 'primary_color', None)) or DEFAULT_PRIMARY
    secondary = normalize_hex(getattr(team, 'secondary_color', None)) or DEFAULT_SECONDARY
    foreground = on_primary_color(primary)
    return {
        'primary': primary,
        'secondary': secondary,
        'on_primary': foreground,
        'on_primary_is_dark': foreground != LIGHT_FOREGROUND,
        'primary_text': primary_text_color(primary),
        'danger': DANGER,
        'near_danger': is_near_danger(primary),
        'warnings': readability_warnings(primary),
    }
