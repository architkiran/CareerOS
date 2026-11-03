#!/bin/sh
# CareerOS container entrypoint.
# Migrations are applied here explicitly (ADR 0005), and only after a verified backup
# of the existing database, so an upgrade can always be rolled back.
set -eu

cd /app
mkdir -p "$DATA_DIR" "$EXPORT_DIR" "$BACKUP_DIR"

if [ "${1:-serve}" = "serve" ]; then
  state=$(python - <<'PY'
from careeros.config import get_settings
from careeros.db.migrations import current_revision, head_revision
from careeros.db.session import create_sqlite_engine
from careeros.modules.backup.service import db_path
s = get_settings()
if not db_path(s.database_url).exists():
    print("new")
else:
    e = create_sqlite_engine(s.database_url)
    try:
        cur = current_revision(e)
    finally:
        e.dispose()
    print("current" if cur == head_revision(s.database_url) else "pending")
PY
)
  case "$state" in
    pending)
      echo "CareerOS: database migrations pending; backing up first."
      careeros backup
      careeros migrate ;;
    new)
      echo "CareerOS: creating a new database."
      careeros migrate ;;
    *)
      echo "CareerOS: database is up to date." ;;
  esac
  if [ -r /app/config/sources.toml ]; then
    careeros sources sync --file /app/config/sources.toml || echo "CareerOS: watchlist sync failed; check config/sources.toml"
  elif [ -d /app/config ] && ! ls /app/config >/dev/null 2>&1; then
    echo "CareerOS: can't read the config folder; make config/ readable to sync sources.toml"
  else
    echo "CareerOS: no config/sources.toml; skipping watchlist sync"
  fi
  exec careeros serve
fi

exec careeros "$@"
