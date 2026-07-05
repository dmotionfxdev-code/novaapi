"""Alternative entry point for hosts where Passenger's ASGI support is
unavailable or too old (see `passenger_wsgi.py`'s docstring). Runs the
real application via `uvicorn` directly, meant to be launched as a
long-running background process (systemd unit, `supervisord` program, or
cPanel's "Application Manager" pointed at this script instead of
`passenger_wsgi.py`) sitting behind an Apache/Nginx reverse proxy that
forwards `novaapi.novarex.co.tz` to `127.0.0.1:$PORT`.

See CPANEL_DEPLOYMENT_GUIDE.md §"Alternative: reverse-proxied uvicorn"
for the exact reverse-proxy configuration this pairs with.

Usage:
    python3 startup.py
    PORT=8001 WORKERS=2 python3 startup.py
"""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC_PATH = os.path.join(_PROJECT_ROOT, "src")
if _SRC_PATH not in sys.path:
    sys.path.insert(0, _SRC_PATH)

import uvicorn  # noqa: E402 — must follow sys.path setup above

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8001"))
    workers = int(os.environ.get("WORKERS", "1"))
    uvicorn.run(
        "georisk.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        workers=workers,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
