"""CoachBoard blueprint package initialization.

Guided setup extends the existing team_management blueprint before Flask
registers it with the application. Keeping this import here avoids changing the
application factory just to add the onboarding routes.
"""

from . import getting_started as _getting_started  # noqa: F401,E402
