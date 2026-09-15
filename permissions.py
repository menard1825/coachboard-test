"""Central role/capability definitions for CoachBoard.

Keep authorization decisions here instead of relying on scattered blueprint-name
exceptions.  Route guards may still add context-specific checks, but the role
model should remain easy to audit in one place.
"""

SUPER_ADMIN = 'Super Admin'
HEAD_COACH = 'Head Coach'
ASSISTANT_COACH = 'Assistant Coach'
GAME_CHANGER = 'Game Changer'

VIEW_TEAM = 'view_team'
VIEW_GAME_SETUP = 'view_game_setup'
VIEW_REPORTS = 'view_reports'
EDIT_ROSTER = 'edit_roster'
DELETE_PLAYER = 'delete_player'
EDIT_GAME_PLAN = 'edit_game_plan'
DELETE_GAME = 'delete_game'
RUN_LIVE_GAME = 'run_live_game'
EDIT_PITCHING = 'edit_pitching'
EDIT_DEVELOPMENT = 'edit_development'
EDIT_PRACTICE = 'edit_practice'
EDIT_SCOUTING = 'edit_scouting'
EDIT_COACH_NOTES = 'edit_coach_notes'
EDIT_TEAM_SETTINGS = 'edit_team_settings'
MANAGE_USERS = 'manage_users'
MANAGE_TEAMS = 'manage_teams'

ALL_CAPABILITIES = {
    VIEW_TEAM,
    VIEW_GAME_SETUP,
    VIEW_REPORTS,
    EDIT_ROSTER,
    DELETE_PLAYER,
    EDIT_GAME_PLAN,
    DELETE_GAME,
    RUN_LIVE_GAME,
    EDIT_PITCHING,
    EDIT_DEVELOPMENT,
    EDIT_PRACTICE,
    EDIT_SCOUTING,
    EDIT_COACH_NOTES,
    EDIT_TEAM_SETTINGS,
    MANAGE_USERS,
    MANAGE_TEAMS,
}

ROLE_CAPABILITIES = {
    SUPER_ADMIN: set(ALL_CAPABILITIES),
    HEAD_COACH: set(ALL_CAPABILITIES) - {MANAGE_TEAMS},
    ASSISTANT_COACH: {
        VIEW_TEAM,
        VIEW_GAME_SETUP,
        VIEW_REPORTS,
        EDIT_ROSTER,
        EDIT_GAME_PLAN,
        RUN_LIVE_GAME,
        EDIT_PITCHING,
        EDIT_DEVELOPMENT,
        EDIT_PRACTICE,
        EDIT_SCOUTING,
        EDIT_COACH_NOTES,
    },
    # Game Changer is intentionally a pregame scorekeeper/viewer role.  It can
    # read the information needed to enter the lineup/defense into GameChanger,
    # but it does not modify CoachBoard or operate CoachBoard's Live Game mode.
    GAME_CHANGER: {
        VIEW_TEAM,
        VIEW_GAME_SETUP,
        VIEW_REPORTS,
    },
}

ROLE_DESCRIPTIONS = {
    SUPER_ADMIN: 'System administrator with access to all teams and team-level coaching tools.',
    HEAD_COACH: 'Team owner: full coaching access plus team settings and coach management.',
    ASSISTANT_COACH: 'Full coaching workflow access without team administration or permanent player/game deletion.',
    GAME_CHANGER: 'Read-only pregame scorekeeper view for lineup, availability, and defensive rotation.',
}


def has_permission(role, capability):
    return capability in ROLE_CAPABILITIES.get(str(role or ''), set())
