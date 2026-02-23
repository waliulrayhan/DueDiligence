# Re-export the router defined in src/api/projects.py so that app.py
# (which imports from src.routers.projects) continues to work unchanged.
from src.api.projects import router as router  # noqa: F401
