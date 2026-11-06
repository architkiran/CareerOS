#!/bin/zsh
set -euo pipefail
career_repo="${0:A:h}"
cd "$career_repo"
export PYTHONPATH="$career_repo/src${PYTHONPATH:+:$PYTHONPATH}"
export APP_HOST=127.0.0.1
export APP_PORT="${APP_PORT:-8766}"
print "CareerOS: http://127.0.0.1:${APP_PORT}/mission-control"
print 'If a server starts, keep this terminal running. Press Ctrl+C to stop it.'
exec "$career_repo/.venv/bin/python" -m careeros.local_launcher
