#!/usr/bin/env python3
"""Blocks until Postgres and Redis are accepting connections, or times out.

Used by ``scripts/bootstrap_dev.sh`` between ``docker compose up -d`` and
``alembic upgrade head`` — Compose's own ``depends_on: condition:
service_healthy`` already covers the multi-service topology (see
``docker-compose.yml``); this script covers the same wait for someone
running services individually outside Compose's own dependency graph.
"""

from __future__ import annotations

import socket
import sys
import time

SERVICES = [
    ("postgres", "localhost", 5432),
    ("redis", "localhost", 6379),
]
TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 2


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


def main() -> int:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    pending = list(SERVICES)

    while pending and time.monotonic() < deadline:
        still_pending = []
        for name, host, port in pending:
            if _port_open(host, port):
                print(f"[wait_for_services] {name} is up ({host}:{port})")
            else:
                still_pending.append((name, host, port))
        pending = still_pending
        if pending:
            time.sleep(POLL_INTERVAL_SECONDS)

    if pending:
        names = ", ".join(name for name, _, _ in pending)
        print(f"[wait_for_services] TIMED OUT waiting for: {names}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
