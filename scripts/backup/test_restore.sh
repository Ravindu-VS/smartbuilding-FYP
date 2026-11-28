#!/bin/sh
# Backup -> data loss -> restore test against the running Docker Compose stack (records evidence on stdout).
#   sh scripts/backup/test_restore.sh
set -eu
dc() { docker compose "$@"; }
psql_sb() { dc exec -T postgres psql -U sbadmin -d smartbuilding -tAc "$1"; }
marker="restore-test-$(date +%s)"
echo "1. write a marker row"
psql_sb "INSERT INTO telemetry (room_id, msg_id, provenance, payload) VALUES ('restore_test', '$marker', 'simulated', '{}')" >/dev/null
rows_before=$(psql_sb "SELECT count(*) FROM telemetry")
models_before=$(dc exec -T postgres psql -U sbadmin -d mlflow -tAc "SELECT count(*) FROM model_versions")
echo "   telemetry rows: $rows_before, MLflow model versions: $models_before"
echo "2. backup"
dc --profile backup run --rm -T backup | tail -3
latest=$(ls -1d ${BACKUP_DIR:-./backups}/20*Z | sort | tail -1)
echo "3. simulate data loss: drop the telemetry table and the MLflow registry rows"
dc stop ingestion >/dev/null
psql_sb "DROP TABLE telemetry CASCADE" >/dev/null
dc exec -T postgres psql -U sbadmin -d mlflow -tAc "DELETE FROM model_version_tags; DELETE FROM registered_model_aliases; DELETE FROM model_versions" >/dev/null
echo "   telemetry table exists: $(psql_sb "SELECT to_regclass('telemetry') IS NOT NULL")"
echo "4. restore from $latest"
dc --profile backup run --rm -T --entrypoint /bin/sh backup /scripts/restore.sh "/backups/$(basename "$latest")" | tail -3
rows_after=$(psql_sb "SELECT count(*) FROM telemetry")
found=$(psql_sb "SELECT count(*) FROM telemetry WHERE msg_id='$marker'")
models_after=$(dc exec -T postgres psql -U sbadmin -d mlflow -tAc "SELECT count(*) FROM model_versions")
dc start ingestion >/dev/null
echo "5. verify: telemetry rows $rows_after (marker found: $found), MLflow model versions $models_after"
[ "$found" = 1 ] && [ "$rows_after" -ge "$rows_before" ] && [ "$models_after" = "$models_before" ] \
  && echo "RESTORE TEST PASSED" || { echo "RESTORE TEST FAILED"; exit 1; }
