"""Team color theming: readable foregrounds and a danger color of its own.

A team's primary color paints the header, the main buttons and badges, and
whatever sits on them has to stay readable. The foreground is chosen from the
real WCAG contrast ratio: white while white reaches 4.5:1, otherwise whichever
of white or dark ink contrasts more. Danger stays a fixed red; a team color
close to it is only reported, so destructive controls can be styled apart.
"""

import pytest

import colorsys

from team_theme import (
    DANGER, DARK_FOREGROUND, DEFAULT_PRIMARY, LIGHT_FOREGROUND, LIGHT_SURFACE,
    contrast_ratio, normalize_hex, on_primary_color, primary_text_color,
    readability_warnings, theme_for,
)


class _Team:
    def __init__(self, primary, secondary='#E5E7EB'):
        self.primary_color = primary
        self.secondary_color = secondary


# --- the foreground choice, by its actual contrast -------------------------

@pytest.mark.parametrize('color', ['#102A66', '#991B1B', '#B91C1C', '#166534', '#15803D', '#000000'])
def test_dark_team_colors_keep_light_foreground(color):
    foreground = on_primary_color(color)
    assert foreground == LIGHT_FOREGROUND
    assert contrast_ratio(foreground, color) >= 4.5


@pytest.mark.parametrize('color', ['#C9A227', '#FFD600', '#FACC15', '#FFFFFF', '#F5F5F4'])
def test_light_team_colors_switch_to_dark_foreground(color):
    foreground = on_primary_color(color)
    assert foreground == DARK_FOREGROUND
    assert contrast_ratio(foreground, color) >= 4.5
    # ...because white would not have been readable there.
    assert contrast_ratio(LIGHT_FOREGROUND, color) < 4.5


def test_mid_tone_picks_whichever_foreground_reads_better():
    # Tailwind blue-500: white is 3.7:1, dark ink is higher.
    color = '#3B82F6'
    foreground = on_primary_color(color)
    other = LIGHT_FOREGROUND if foreground == DARK_FOREGROUND else DARK_FOREGROUND
    assert contrast_ratio(foreground, color) > contrast_ratio(other, color)


def test_contrast_ratio_matches_known_values():
    assert contrast_ratio('#000000', '#FFFFFF') == pytest.approx(21.0)
    assert contrast_ratio('#FFFFFF', '#FFFFFF') == pytest.approx(1.0)
    assert contrast_ratio('#FFFFFF', '#C9A227') == pytest.approx(2.42, abs=0.01)
    assert contrast_ratio('#FFFFFF', '#102A66') == pytest.approx(13.59, abs=0.01)


# --- input handling ---------------------------------------------------------

def test_shorthand_and_case_normalize():
    assert normalize_hex('#fff') == '#ffffff'
    assert normalize_hex('#C9A227') == normalize_hex('#c9a227') == '#c9a227'
    assert normalize_hex('  #102a66 ') == '#102a66'
    assert on_primary_color('#FFF') == on_primary_color('#ffffff') == DARK_FOREGROUND


@pytest.mark.parametrize('value', [None, '', 'red', '#12345', '#ggg', '102a66',
                                   'url(javascript:x)', '#fff;}body{display:none}',
                                   'rgb(0,0,0)'])
def test_malformed_colors_fall_back_safely(value):
    assert normalize_hex(value) is None
    theme = theme_for(_Team(value, value))
    assert theme['primary'] == DEFAULT_PRIMARY
    assert theme['on_primary'] == on_primary_color(DEFAULT_PRIMARY)
    assert ';' not in theme['primary'] and ';' not in theme['secondary']


def test_missing_team_uses_defaults():
    theme = theme_for(None)
    assert theme['primary'] == DEFAULT_PRIMARY
    assert theme['on_primary'] == LIGHT_FOREGROUND
    assert theme['on_primary_is_dark'] is False


# --- the team color as text on a light surface ------------------------------
# --cb-primary-text: links, outlined buttons and active nav drawn in the team
# color on white cards and the light page background.

def _hls(color):
    return colorsys.rgb_to_hls(*(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)))


def _reads_on_light_surfaces(color):
    return min(contrast_ratio(color, '#ffffff'), contrast_ratio(color, LIGHT_SURFACE)) >= 4.5


@pytest.mark.parametrize('color', ['#102A66', '#B91C1C', '#15803D', '#991B1B', '#000000'])
def test_team_colors_that_read_on_white_are_used_unchanged(color):
    assert _reads_on_light_surfaces(color)
    assert primary_text_color(color) == normalize_hex(color)


@pytest.mark.parametrize('color', ['#C9A227', '#FFD600', '#FACC15', '#3B82F6', '#EA580C'])
def test_light_team_colors_are_darkened_in_their_own_hue(color):
    text = primary_text_color(color)
    assert not _reads_on_light_surfaces(color)
    assert text != normalize_hex(color)
    assert _reads_on_light_surfaces(text)
    hue, lightness, saturation = _hls(text)
    orig_hue, orig_lightness, orig_saturation = _hls(normalize_hex(color))
    # Same color family, only darker: not swapped for navy or ink.
    assert abs(hue - orig_hue) * 360 < 4
    assert abs(saturation - orig_saturation) < 0.05
    assert lightness < orig_lightness
    assert text not in (DARK_FOREGROUND, '#102a66')


@pytest.mark.parametrize('color', ['#C9A227', '#FFD600'])
def test_darkening_stops_once_readable(color):
    # Darker than it needs to be would lose the brand color for nothing.
    assert contrast_ratio(primary_text_color(color), LIGHT_SURFACE) < 5


@pytest.mark.parametrize('color', ['#FFFFFF', '#fff', '#F5F5F4', '#C0C0C0'])
def test_white_and_grey_teams_get_the_dark_ink(color):
    # No hue to keep, and a just-readable grey looks like a disabled control.
    text = primary_text_color(color)
    assert text == DARK_FOREGROUND
    assert contrast_ratio(text, '#ffffff') >= 7


def test_primary_text_is_in_the_theme_and_the_team_color_is_untouched():
    theme = theme_for(_Team('#FFD600'))
    assert theme['primary'] == '#ffd600'
    assert theme['primary_text'] == primary_text_color('#FFD600')
    assert theme_for(_Team('#102A66'))['primary_text'] == '#102a66'
    assert theme_for(_Team('not a color'))['primary_text'] == primary_text_color(DEFAULT_PRIMARY)


# --- danger stays its own color ----------------------------------------------

def test_danger_is_fixed_whatever_the_team_color():
    for color in ('#102A66', '#B91C1C', '#FFD600'):
        assert theme_for(_Team(color))['danger'] == DANGER


@pytest.mark.parametrize('color,near', [
    ('#B91C1C', True), ('#B42318', True), ('#DC2626', True), ('#991B1B', True),
    ('#102A66', False), ('#15803D', False), ('#C9A227', False), ('#FFFFFF', False),
    ('#EA580C', False),
])
def test_team_colors_close_to_danger_are_flagged(color, near):
    assert theme_for(_Team(color))['near_danger'] is near


# --- what Team Settings tells the coach ---------------------------------------

def test_readable_colors_have_no_warning():
    assert readability_warnings('#102A66') == []
    assert readability_warnings('#15803D') == []


def test_light_colors_explain_the_darker_text_shade():
    for color in ('#C9A227', '#FFD600', '#FFFFFF'):
        warnings = readability_warnings(color)
        note = [w for w in warnings if 'darker' in w.lower()]
        assert note and 'white' in note[0].lower(), (color, warnings)
        assert primary_text_color(color) in note[0]


def test_colors_neither_foreground_can_read_on_warn_about_the_header():
    # Pick a color where both foregrounds miss 4.5:1.
    color = '#7A7A7A'
    assert max(contrast_ratio(LIGHT_FOREGROUND, color),
               contrast_ratio(DARK_FOREGROUND, color)) < 4.5
    assert any('header' in w.lower() for w in readability_warnings(color))


def test_red_team_is_told_delete_buttons_stay_distinct():
    assert any('delete' in w.lower() for w in readability_warnings('#B91C1C'))
