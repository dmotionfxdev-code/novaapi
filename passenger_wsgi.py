"""Phusion Passenger entry point for cPanel's "Setup Python App" (Python
Application Manager).

NOVA GeoRisk Platform is an ASGI application (FastAPI/Starlette) — it does
NOT speak plain WSGI. Passenger has supported ASGI applications directly
since 6.0.9: it inspects the object exposed here as `application` and, if
it is an async-callable (3-argument `async def app(scope, receive, send)`,
which is exactly what a FastAPI instance is), dispatches to it as ASGI
rather than WSGI. No adapter/shim is required or used here.

IMPORTANT — verify before relying on this file:
    Many cPanel/WHM hosts still ship a Passenger version older than 6.0.9,
    in which case this file will NOT work (Passenger will try to call the
    app the WSGI way — 2 args — and fail immediately on request). Check
    the installed Passenger version with `passenger -v` via SSH, or ask
    the hosting provider. If Passenger is too old, do NOT force this path
    — use the uvicorn-as-a-service + reverse-proxy approach documented in
    CPANEL_DEPLOYMENT_GUIDE.md §"Alternative: reverse-proxied uvicorn"
    instead, which works on every cPanel host regardless of Passenger
    version.

cPanel's Python Application Manager sets up its own virtualenv and, when
you enable the app, runs something equivalent to:
    <virtualenv>/bin/python passenger_wsgi.py
via Passenger — it does not run `uvicorn` directly. This file's only job
is to import and expose the real application object; all app construction
logic stays in `georisk.api.app.create_app()`, unchanged.
"""

from __future__ import annotations

import os
import sys

# cPanel's Python Application Manager sets the app's "Application root" as
# the working directory but does not always add `src/` to `sys.path` the
# way an editable `pip install -e .` would in development — add it
# explicitly and defensively so this works whether or not the app was
# `pip install`-ed into the cPanel virtualenv.
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC_PATH = os.path.join(_PROJECT_ROOT, "src")
if _SRC_PATH not in sys.path:
    sys.path.insert(0, _SRC_PATH)

from georisk.api.app import create_app  # noqa: E402 — must follow sys.path setup above
from georisk.settings import get_settings  # noqa: E402

# `get_settings()` reads `.env` from the current working directory via
# pydantic-settings' `env_file=".env"` — cPanel's Python App sets the
# working directory to the application root, so this resolves the same
# `.env` file described in CPANEL_DEPLOYMENT_GUIDE.md.
application = create_app(settings=get_settings())
