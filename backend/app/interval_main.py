"""Composite FastAPI application including Research Lab and Interval Analyzer.

Run with:
    python -m uvicorn app.interval_main:app --reload --port 8000
"""

from .main import app
from .interval.router import router as interval_router

app.include_router(interval_router)
