#!/bin/sh
# Restore PostgreSQL databases (and MLflow artifacts) from a backup made by backup.sh.
#   docker compose --profile backup run --rm --entrypoint /bin/sh backup /scripts/restore.sh /backups/<STAMP>
# Checksums are verified first. Each database is restored with --clean --if-exists as its owning service role
# (DB_OWNERS, "database:role" pairs), so the service can write its tables again afterwards.
set -eu
DIR=${1:?usage: restore.sh <backup directory>}
( cd "$DIR" && sha256sum -c SHA256SUMS >/dev/null ) || { echo "checksum mismatch in $DIR" >&2; exit 1; }
for pair in ${DB_OWNERS:-mlflow:mlflow smartbuilding:ingest}; do
  db=${pair%%:*}; owner=${pair##*:}
  [ -f "$DIR/$db.dump" ] || { echo "  $db: no dump in $DIR, skipped"; continue; }
  pg_restore --clean --if-exists --no-owner --role="$owner" --dbname="$db" "$DIR/$db.dump"
  echo "  $db restored (owner $owner)"
done
if [ -f "$DIR/mlflow-artifacts.tgz" ] && [ -w /data/mlflow-artifacts ]; then
  tar -C /data -xzf "$DIR/mlflow-artifacts.tgz" && echo "  mlflow artifacts restored"
fi
echo "restore complete from $DIR"
