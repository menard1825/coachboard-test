# menard1825/coachboard-test/coachboard-test-structure-overhaul/models.py
# models.py
from sqlalchemy import Column, Integer, String, ForeignKey, Text, Boolean, Float, DateTime, JSON
from sqlalchemy.orm import relationship
from db import db
import json
from datetime import datetime

# All models now inherit from db.Model
class Team(db.Model):
    __tablename__ = 'teams'
    id = Column(Integer, primary_key=True)
    team_name = Column(String, nullable=False)
    registration_code = Column(String, nullable=False)
    logo_path = Column(String)
    display_coach_names = Column(Boolean, default=False, nullable=False)
    primary_color = Column(String, default="#1F2937")
    secondary_color = Column(String, default="#E5E7EB")
    age_group = Column(String, default='12U', nullable=False)
    pitching_rule_set = Column(String, default='USSSA', nullable=False)
    outfielder_count = Column(Integer, default=3, nullable=False)
    default_practice_location = Column(String, nullable=True)

    users = relationship("User", back_populates="team")
    players = relationship("Player", back_populates="team")
    lineups = relationship("Lineup", back_populates="team")
    pitching_outings = relationship("PitchingOuting", back_populates="team")
    scouted_players = relationship("ScoutedPlayer", back_populates="team")
    rotations = relationship("Rotation", back_populates="team")
    games = relationship("Game", back_populates="team")
    collaboration_notes = relationship("CollaborationNote", back_populates="team")
    practice_plans = relationship("PracticePlan", back_populates="team")
    signs = relationship("Sign", back_populates="team")
    player_development_focuses = relationship("PlayerDevelopmentFocus", back_populates="team")
    opponents = relationship("Opponent", back_populates="team", cascade="all, delete-orphan")

class User(db.Model):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    full_name = Column(String(100), nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default='Coach')
    last_login = Column(DateTime)
    tab_order = Column(Text) # Keeping as text for simplicity
    player_order = Column(JSON) # Changed to JSON

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="users")

class Player(db.Model):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    number = Column(String)
    position1 = Column(String)
    position2 = Column(String)
    position3 = Column(String)
    throws = Column(String)
    bats = Column(String)
    notes = Column(Text)
    pitcher_role = Column(String)
    has_lessons = Column(String)
    lesson_focus = Column(Text)
    notes_author = Column(String)
    notes_timestamp = Column(DateTime) # Changed to DateTime

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="players")

    development_focuses = relationship("PlayerDevelopmentFocus", back_populates="player", cascade="all, delete-orphan")
    game_absences = relationship("PlayerGameAbsence", back_populates="player", cascade="all, delete-orphan")
    practice_absences = relationship("PlayerPracticeAbsence", back_populates="player", cascade="all, delete-orphan")
    pitching_outings = relationship("PitchingOuting", back_populates="player", cascade="all, delete-orphan")
    
    @property
    def full_name(self):
        return self.name.strip() if self.name else None

    def to_dict(self):
        """Return a dictionary representation of the Player object."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Lineup(db.Model):
    __tablename__ = 'lineups'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    # Use a private attribute to map to the 'lineup_positions' column in the DB
    _lineup_positions_db = Column('lineup_positions', JSON)
    associated_game_id = Column(Integer, ForeignKey('games.id', ondelete='CASCADE'), nullable=True)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="lineups")

    @property
    def lineup_positions(self):
        """
        Getter for lineup_positions.
        Handles legacy data that might be stored as a JSON string.
        """
        db_val = self._lineup_positions_db
        if isinstance(db_val, str):
            try:
                return json.loads(db_val)
            except json.JSONDecodeError:
                # If it's a string but not valid JSON, return an empty list as a safe fallback.
                return []
        # Return the value if it's already a list/dict, or an empty list if it's None.
        return db_val if db_val is not None else []

    @lineup_positions.setter
    def lineup_positions(self, value):
        """
        Setter for lineup_positions.
        The SQLAlchemy JSON type handles serialization of the Python object (list/dict).
        """
        self._lineup_positions_db = value

class PitchingOuting(db.Model):
    __tablename__ = 'pitching_outings'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False)
    opponent = Column(String)
    pitches = Column(Integer)
    innings = Column(Float)
    pitcher_type = Column(String)
    outing_type = Column(String)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=True)
    practice_plan_id = Column(Integer, ForeignKey('practice_plans.id'), nullable=True) # ADD THIS LINE

    team = relationship("Team", back_populates="pitching_outings")
    player = relationship("Player", back_populates="pitching_outings")
    game = relationship("Game", back_populates="pitching_outings")
    practice_plan = relationship("PracticePlan", back_populates="pitching_outings") # ADD THIS LINE

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "opponent": self.opponent,
            "pitches": self.pitches,
            "innings": self.innings,
            "outing_type": self.outing_type,
            "pitcher_type": self.pitcher_type,
            "player_id": self.player_id,
            "player_name": self.player.full_name if self.player else None,
        }

class ScoutedPlayer(db.Model):
    __tablename__ = 'scouted_players'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    position1 = Column(String)
    position2 = Column(String)
    throws = Column(String)
    bats = Column(String)
    list_type = Column(String, nullable=False)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="scouted_players")
    
    def to_dict(self):
        """Return a dictionary representation of the ScoutedPlayer object."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class Rotation(db.Model):
    __tablename__ = 'rotations'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    innings = Column(JSON) # Changed to JSON
    associated_game_id = Column(Integer, ForeignKey('games.id', ondelete='CASCADE'), nullable=True)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="rotations")
    game = relationship("Game", back_populates="rotations")

class Game(db.Model):
    __tablename__ = 'games'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False) # Changed to DateTime
    opponent = Column(String, nullable=False)
    location = Column(String)
    game_notes = Column(Text)
    associated_lineup_title = Column(String)
    associated_rotation_date = Column(String)
    our_score = Column(Integer)
    opponent_score = Column(Integer)
    post_game_summary = Column(Text)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="games")
    absences = relationship("PlayerGameAbsence", back_populates="game", cascade="all, delete-orphan")
    pitching_outings = relationship("PitchingOuting", back_populates="game", cascade="all, delete-orphan")
    rotations = relationship("Rotation", back_populates="game", cascade="all, delete-orphan", passive_deletes=True)
    
    lineups = relationship("Lineup", backref="game", cascade="all, delete-orphan", passive_deletes=True)

    opponent_id = Column(Integer, ForeignKey('opponents.id'), nullable=True)
    opponent_relationship = relationship("Opponent", back_populates="games")
    quick_notes = relationship("GameQuickNote", back_populates="game", cascade="all, delete-orphan")

    def to_dict(self):
        """Return a dictionary representation of the Game object."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class Opponent(db.Model):
    __tablename__ = 'opponents'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    notes = Column(Text)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="opponents")
    games = relationship("Game", back_populates="opponent_relationship")

class GameQuickNote(db.Model):
    __tablename__ = 'game_quick_notes'
    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    author = Column(String)
    timestamp = Column(DateTime, nullable=True)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False)
    game = relationship("Game", back_populates="quick_notes")

class CollaborationNote(db.Model):
    __tablename__ = 'collaboration_notes'
    id = Column(Integer, primary_key=True)
    note_type = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    author = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow) # Changed to DateTime
    player_name = Column(String, nullable=True)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="collaboration_notes")

class PracticePlan(db.Model):
    __tablename__ = 'practice_plans'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False) # Changed to DateTime
    location = Column(String) # ADDED
    general_notes = Column(Text)
    emphasis = Column(Text)
    warm_up = Column(Text)
    infield_outfield = Column(Text)
    hitting = Column(Text)
    pitching_catching = Column(Text)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="practice_plans")
    tasks = relationship("PracticeTask", back_populates="practice_plan", order_by="PracticeTask.id")
    absences = relationship("PlayerPracticeAbsence", back_populates="practice_plan", cascade="all, delete-orphan")
    pitching_outings = relationship("PitchingOuting", back_populates="practice_plan", cascade="all, delete-orphan") # ADD THIS LINE

class PracticeTask(db.Model):
    __tablename__ = 'practice_tasks'
    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    status = Column(String, default="pending")
    author = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow) # Changed to DateTime

    practice_plan_id = Column(Integer, ForeignKey('practice_plans.id'), nullable=False)
    practice_plan = relationship("PracticePlan", back_populates="tasks")

class PlayerDevelopmentFocus(db.Model):
    __tablename__ = 'player_development_focuses'
    id = Column(Integer, primary_key=True)
    focus = Column(Text, nullable=False)
    status = Column(String, default="active")
    notes = Column(Text)
    progress_notes = Column(Text, nullable=True) # New field
    created_date = Column(DateTime, default=datetime.utcnow) # Changed to DateTime
    completed_date = Column(DateTime, nullable=True) # Changed to DateTime
    author = Column(String)
    last_edited_by = Column(String)
    last_edited_date = Column(DateTime) # Changed to DateTime

    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    player = relationship("Player", back_populates="development_focuses")
    skill_type = Column(String, nullable=False)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="player_development_focuses")

class Sign(db.Model):
    __tablename__ = 'signs'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    indicator = Column(String, nullable=False)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="signs")

class PlayerGameAbsence(db.Model):
    __tablename__ = 'player_game_absences'
    id = Column(Integer, primary_key=True)

    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False)

    player = relationship("Player", back_populates="game_absences")
    game = relationship("Game", back_populates="absences")

class PlayerPracticeAbsence(db.Model):
    __tablename__ = 'player_practice_absences'
    id = Column(Integer, primary_key=True)

    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    practice_plan_id = Column(Integer, ForeignKey('practice_plans.id'), nullable=False)

    player = relationship("Player", back_populates="practice_absences")
    practice_plan = relationship("PracticePlan", back_populates="absences")