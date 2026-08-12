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
    pitching_rule_set = Column(String, default='MLB Pitch Smart', nullable=False)
    outfielder_count = Column(Integer, default=3, nullable=False)
    timezone = Column(String, default='America/Indiana/Indianapolis', nullable=False)

    memberships = relationship("TeamMembership", back_populates="team", cascade="all, delete-orphan")
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
    player_game_absences = relationship("PlayerGameAbsence", back_populates="team")
    player_practice_absences = relationship("PlayerPracticeAbsence", back_populates="team")

class User(db.Model):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    full_name = Column(String(100), nullable=True)
    password_hash = Column(String, nullable=False)
    last_login = Column(DateTime)
    tab_order = Column(Text) # Keeping as text for simplicity

    # We no longer have team_id, role, or player_order directly on the user.
    # Those are now on the TeamMembership model.
    memberships = relationship("TeamMembership", back_populates="user", cascade="all, delete-orphan")

class TeamMembership(db.Model):
    """Maps a user to a team, storing their role and preferences specific to that team."""
    __tablename__ = 'team_memberships'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    role = Column(String, default='Coach', nullable=False)
    player_order = Column(JSON, default=list)

    user = relationship("User", back_populates="memberships")
    team = relationship("Team", back_populates="memberships")

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
    lineup_positions = Column(JSON) # Changed to JSON
    associated_game_id = Column(Integer)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="lineups")

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

    team = relationship("Team", back_populates="pitching_outings")
    player = relationship("Player", back_populates="pitching_outings")
    game = relationship("Game", back_populates="pitching_outings")

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
    associated_game_id = Column(Integer, nullable=True)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="rotations")

from sqlalchemy import Index

class Game(db.Model):
    __tablename__ = 'games'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False) # Changed to DateTime
    start_time = Column(String, nullable=True) # Optional e.g. "09:00 AM"
    opponent = Column(String, nullable=False)
    location = Column(String)
    game_notes = Column(Text)
    associated_lineup_title = Column(String)
    associated_rotation_date = Column(String)
    is_live = Column(Boolean, default=False, nullable=False)
    live_current_inning = Column(String, default="1", nullable=False)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="games")
    absences = relationship("PlayerGameAbsence", back_populates="game", cascade="all, delete-orphan")
    pitching_outings = relationship("PitchingOuting", back_populates="game", cascade="all, delete-orphan")
    rotation_events = relationship("GameRotationEvent", back_populates="game", cascade="all, delete-orphan")
    
    def to_dict(self):
        """Return a dictionary representation of the Game object."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class GameRotationEvent(db.Model):
    __tablename__ = 'game_rotation_events'
    id = Column(Integer, primary_key=True)
    inning = Column(String, nullable=False)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)  # 'Pitcher Change', 'Defensive Change', 'End Inning'
    timestamp = Column(DateTime, default=datetime.utcnow)
    changed_by_user = Column(String)

    before_alignment = Column(JSON)
    after_alignment = Column(JSON)

    old_pitcher_id = Column(Integer, ForeignKey('players.id'), nullable=True)
    new_pitcher_id = Column(Integer, ForeignKey('players.id'), nullable=True)
    reverted = Column(Boolean, default=False, nullable=False)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False)

    game = relationship("Game", back_populates="rotation_events")
    old_pitcher = relationship("Player", foreign_keys=[old_pitcher_id])
    new_pitcher = relationship("Player", foreign_keys=[new_pitcher_id])

class PlayerPitchTarget(db.Model):
    __tablename__ = 'player_pitch_targets'
    id = Column(Integer, primary_key=True)
    target_pitches = Column(Integer, nullable=False)
    local_date = Column(String, nullable=False)  # Stored as YYYY-MM-DD
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=True) # Nullable for daily targets

    player = relationship("Player")

    # Partial indexes to ensure unique targets per day vs unique targets per game
    __table_args__ = (
        Index('idx_unique_daily_target', 'team_id', 'player_id', 'local_date', unique=True, sqlite_where=Column('game_id').is_(None)),
        Index('idx_unique_game_target', 'team_id', 'player_id', 'local_date', 'game_id', unique=True, sqlite_where=Column('game_id').is_not(None)),
    )

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
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)

    player = relationship("Player", back_populates="game_absences")
    game = relationship("Game", back_populates="absences")
    team = relationship("Team", back_populates="player_game_absences")

class PlayerPracticeAbsence(db.Model):
    __tablename__ = 'player_practice_absences'
    id = Column(Integer, primary_key=True)

    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    practice_plan_id = Column(Integer, ForeignKey('practice_plans.id'), nullable=False)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)

    player = relationship("Player", back_populates="practice_absences")
    practice_plan = relationship("PracticePlan", back_populates="absences")
    team = relationship("Team", back_populates="player_practice_absences")