from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, FloatField, SelectField, DateField
from wtforms.validators import DataRequired, Optional

class PitchingOutingForm(FlaskForm):
    player_id = SelectField('Pitcher', validators=[DataRequired()], coerce=int)
    game_id = SelectField('Associated Game (Optional)', coerce=int, validators=[Optional()])
    pitch_date = DateField('Date', format='%Y-%m-%d', validators=[Optional()])
    opponent = StringField('Opponent', validators=[Optional()])
    pitches = IntegerField('Pitches', validators=[DataRequired()])
    innings = FloatField('Innings', validators=[DataRequired()])
    pitcher_type = SelectField('Pitcher Type', choices=[('Starter', 'Starter'), ('Reliever', 'Reliever')], default='Starter')
    outing_type = SelectField('Outing Type', choices=[('Game', 'Game'), ('Bullpen', 'Bullpen'), ('Practice', 'Practice')], default='Game')
