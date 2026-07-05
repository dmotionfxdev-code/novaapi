#!/usr/bin/env bash
# Entrypoint for the Celery beat scheduler. Runs against an intentionally
# empty schedule (celery_app/app.py's `beat_schedule = {}`) — proves the
# service starts cleanly before Roadmap Sprint 9 adds the first real
# periodic job (weather/sensor polling).
set -euo pipefail

exec celery -A georisk.celery_app.app beat --loglevel=info
