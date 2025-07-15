from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Boolean, Float
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.inspection import inspect as sqlalchemy_inspect
from datetime import datetime
import json

Base = declarative_base()

# Helper function to convert model instances to dictionaries
def to_dict(instance):
    if instance is None:
        return None
    d = {}
    for column in sqlalchemy_inspect(instance).mapper.column_attrs:
        val = getattr(instance, column.key)
        # Special handling for JSON strings so they are parsed in the final dict
        if isinstance(val, str) and val.startswith(('[', '{')):
            try:
                d[column.key] = json.loads(val)
            except json.JSONDecodeError:
                d[column.key] = val # Keep as string if not valid JSON
        else:
            d[column.key] = val
    return d


class Team(Base):
    __tablename__ = 'teams'
    id = Column(Integer, primary_key=True)
    team_name = Column(String, nullable=False)
    registration_code = Column(String, nullable=False)
    logo_path = Column(String)
    display_coach_names = Column(Boolean, default=False, nullable=False)
    primary_color = Column(String, default="#1F2937")
    secondary_color = Column(String, default="#E5E7EB")

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

    def to_dict(self): return to_dict(self)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    full_name = Column(String(100), nullable=True) # <<< This line is crucial
    password_hash = Column(String, nullable=False)
    role = Column(String, default='Coach')
    last_login = Column(String) # Stored as string for now, consider DateTime
    tab_order = Column(Text) # Storing JSON string
    player_order = Column(Text) # Storing JSON string

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="users")
    
    def to_dict(self): return to_dict(self)

class Player(Base):
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
    notes_timestamp = Column(String) # Stored as string for now, consider DateTime

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="players")

    # A single relationship to handle all development focuses for a player.
    # The cascade option will automatically delete focuses when a player is deleted.
    development_focuses = relationship("PlayerDevelopmentFocus", back_populates="player", cascade="all, delete-orphan")
    
    def to_dict(self): return to_dict(self)

class Lineup(Base):
    __tablename__ = 'lineups'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    lineup_positions = Column(Text) # Storing JSON string of [{'name': 'Player Name', 'position': 'Pos'}]
    associated_game_id = Column(Integer) # Can be ForeignKey to games.id later if desired, nullable=True

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="lineups")
    
    def to_dict(self): return to_dict(self)

class PitchingOuting(Base):
    __tablename__ = 'pitching_outings'
    id = Column(Integer, primary_key=True)
    date = Column(String, nullable=False) # Stored as string, consider Date or DateTime
    pitcher = Column(String, nullable=False) # Consider ForeignKey to players.id later
    opponent = Column(String)
    pitches = Column(Integer)
    innings = Column(Float)
    pitcher_type = Column(String)
    outing_type = Column(String)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="pitching_outings")

    def to_dict(self): return to_dict(self)

class ScoutedPlayer(Base):
    __tablename__ = 'scouted_players'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    position1 = Column(String)
    position2 = Column(String)
    throws = Column(String)
    bats = Column(String)
    list_type = Column(String, nullable=False) # 'committed', 'targets', 'not_interested'

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="scouted_players")

    def to_dict(self): return to_dict(self)

class Rotation(Base):
    __tablename__ = 'rotations'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    innings = Column(Text) # Storing JSON string of {inning_num: {pos: player_name}}
    associated_game_id = Column(Integer, nullable=True) # ForeignKey to games.id later if desired

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="rotations")

    def to_dict(self): return to_dict(self)

class Game(Base):
    __tablename__ = 'games'
    id = Column(Integer, primary_key=True)
    date = Column(String, nullable=False) # Stored as string, consider Date or DateTime
    opponent = Column(String, nullable=False)
    location = Column(String)
    game_notes = Column(Text)
    associated_lineup_title = Column(String) # Can be linked to Lineup model later
    associated_rotation_date = Column(String) # Can be linked to Rotation model later

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="games")

    def to_dict(self): return to_dict(self)

class CollaborationNote(Base):
    __tablename__ = 'collaboration_notes'
    id = Column(Integer, primary_key=True)
    note_type = Column(String, nullable=False) # 'player_notes' or 'team_notes'
    text = Column(Text, nullable=False)
    author = Column(String) # Consider ForeignKey to users.id later
    timestamp = Column(String) # Stored as string, consider DateTime
    player_name = Column(String, nullable=True) # Only for player_notes, consider ForeignKey to players.id

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="collaboration_notes")

    def to_dict(self): return to_dict(self)

class PracticePlan(Base):
    __tablename__ = 'practice_plans'
    id = Column(Integer, primary_key=True)
    date = Column(String, nullable=False) # Stored as string, consider Date
    general_notes = Column(Text)
    # tasks will be a relationship to PracticeTask

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="practice_plans")
    tasks = relationship("PracticeTask", back_populates="practice_plan", order_by="PracticeTask.id") # Order by ID for consistency

    def to_dict(self): return to_dict(self)

class PracticeTask(Base):
    __tablename__ = 'practice_tasks'
    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False)
    status = Column(String, default="pending") # 'pending' or 'complete'
    author = Column(String) # Consider ForeignKey to users.id later
    timestamp = Column(String) # Stored as string, consider DateTime

    practice_plan_id = Column(Integer, ForeignKey('practice_plans.id'), nullable=False)
    practice_plan = relationship("PracticePlan", back_populates="tasks")

    def to_dict(self): return to_dict(self)

class PlayerDevelopmentFocus(Base):
    __tablename__ = 'player_development_focuses'
    id = Column(Integer, primary_key=True)
    focus = Column(Text, nullable=False)
    status = Column(String, default="active")
    notes = Column(Text)
    created_date = Column(String) # Stored as string, consider Date
    completed_date = Column(String, nullable=True) # Stored as string, consider Date
    author = Column(String) # Consider ForeignKey to users.id later
    last_edited_by = Column(String) # Consider ForeignKey to users.id later
    last_edited_date = Column(String) # Stored as string, consider DateTime

    # Link to player and skill type
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    player = relationship("Player", back_populates="development_focuses")
    skill_type = Column(String, nullable=False) # 'hitting', 'pitching', 'fielding', 'baserunning'

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team") # Simple relationship without back_populates if not directly accessed from Team

    def to_dict(self): return to_dict(self)

class Sign(Base):
    __tablename__ = 'signs'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    indicator = Column(String, nullable=False)

    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team = relationship("Team", back_populates="signs")
    
    def to_dict(self): return to_dict(self)