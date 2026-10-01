"""The HTTP interface of the lab, and everything the web UI needs from Python.

It is an optional part of the distribution: ``pip install -e ".[api]"`` brings
FastAPI and uvicorn in, ``paper-obs serve`` starts it, and the engine itself
never depends on them.
"""

from .app import FRONTEND_DIST, create_app

__all__ = ["FRONTEND_DIST", "create_app"]
