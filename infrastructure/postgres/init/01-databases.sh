#!/bin/sh
# First start of the PostgreSQL volume only: one database and one owner per service, plus a read-only role for
# Grafana. Passwords come from the environment and are passed as psql variables (quoted by psql, never spliced).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
     -v mlflow_pw="$MLFLOW_DB_PASSWORD" -v ingest_pw="$INGEST_DB_PASSWORD" -v grafana_pw="$GRAFANA_DB_PASSWORD" <<'EOSQL'
CREATE ROLE mlflow LOGIN PASSWORD :'mlflow_pw';
CREATE DATABASE mlflow OWNER mlflow;
CREATE ROLE ingest LOGIN PASSWORD :'ingest_pw';
CREATE DATABASE smartbuilding OWNER ingest;
CREATE ROLE grafana_ro LOGIN PASSWORD :'grafana_pw';
REVOKE ALL ON DATABASE mlflow FROM PUBLIC;
REVOKE ALL ON DATABASE smartbuilding FROM PUBLIC;
GRANT CONNECT ON DATABASE smartbuilding TO grafana_ro;
EOSQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname smartbuilding <<'EOSQL'
GRANT USAGE ON SCHEMA public TO grafana_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE ingest IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro;
GRANT CREATE ON SCHEMA public TO ingest;
EOSQL
echo "01-databases.sh: databases mlflow and smartbuilding created"
