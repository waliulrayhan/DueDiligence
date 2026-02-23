# Re-export the router defined in src/api/answers.py so that app.py
# (which imports from src.routers.answers) continues to work unchanged.
from src.api.answers import router as router  # noqa: F401
