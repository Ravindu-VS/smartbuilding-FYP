#!/bin/sh
# Backup of the container stack: PostgreSQL databases (custom format), roles, MLflow artifacts, edge output.
#   docker compose --profile backup run --rm backup          -> ./backups/<UTC time>/
# Environment: PGHOST, PGUSER, PGPASSWORD (superuser), DB_OWNERS ("database:role" pairs),
#              BACKUP_ROOT (/backups), BACKUP_KEEP (7 newest kept).
# Secrets (.env) are deliberately NOT backed up: keep them in your password manager.
set -eu
ROOT=${BACKUP_ROOT:-/backups}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DIR="$ROOT/$STAMP"
mkdir -p "$DIR"
echo "backup -> $DIR"
pg_dumpall --globals-only --no-role-passwords > "$DIR/roles.sql"
for pair in ${DB_OWNERS:-mlflow:mlflow smartbuilding:ingest}; do
  db=${pair%%:*}
  pg_dump --format=custom --no-owner --dbname="$db" --file="$DIR/$db.dump"
  echo "  $db: $(wc -c < "$DIR/$db.dump") bytes"
done
if [ -d /data/mlflow-artifacts ]; then tar -C /data -czf "$DIR/mlflow-artifacts.tgz" mlflow-artifacts; fi
# edge output: the SQLite store has its own consistent online backup (sqlite_backup.py); copy everything else
if [ -d /data/edge-output ]; then
  tar -C /data -czf "$DIR/edge-output.tgz" --exclude='*.sqlite3' --exclude='*.sqlite3-wal' --exclude='*.sqlite3-shm' edge-output
fi
( cd "$DIR" && sha256sum * > SHA256SUMS )
echo "  manifest: $(wc -l < "$DIR/SHA256SUMS") files"
# retention
ls -1d "$ROOT"/20*Z 2>/dev/null | sort | head -n -"${BACKUP_KEEP:-7}" | while read -r old; do rm -rf "$old"; echo "  pruned $old"; done
echo "backup complete: $STAMP"
