"""Composite FastAPI application including Research Lab and Interval Analyzer.

Run with:
    python -m uvicorn app.interval_main:app --app-dir backend --reload --port 8000

The research application mounts the repository's static files at ``/``. Starlette
matches routes in declaration order, so that catch-all mount must remain last;
otherwise it intercepts ``/api/interval/*`` before the interval router can run.
"""

from starlette.routing import Mount

from .main import app
from .interval.router import router as interval_router


# ``app.main`` has already attached the root static mount. Temporarily remove it,
# register the interval API, then restore static serving as the final catch-all.
_static_mounts = [
    route
    for route in app.router.routes
    if isinstance(route, Mount) and route.name == "static"
]
for _route in _static_mounts:
    app.router.routes.remove(_route)

app.include_router(interval_router)
app.router.routes.extend(_static_mounts)
