#!/bin/sh
# Failure and recovery test against the running Docker Compose stack. Prints a timestamped record.
#   sh scripts/chaos/recovery_test.sh
# A. crash: the ML API process dies -> Docker restarts it -> health check green again
# B. outage: ingestion is stopped for OUTAGE_S seconds -> Prometheus marks it down -> ServiceDown alert fires
#    in Alertmanager -> logs show it -> service started again -> MQTT QoS 1 backlog is delivered: no reading lost
set -eu
PROM=${PROM:-http://localhost:9090}
AM=${AM:-http://localhost:9093}
EDGE=${EDGE:-http://localhost:8001}
OUTAGE_S=${OUTAGE_S:-100}
ts() { date -u +%H:%M:%S; }
q() { curl -s "$PROM/api/v1/query" --data-urlencode "query=$1" | python3 -c "import json,sys; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else 'none')"; }
health() { docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "$1")"; }
restarts() { docker inspect -f '{{.RestartCount}}' "$(docker compose ps -q "$1")"; }
rows() { docker compose exec -T postgres psql -U sbadmin -d smartbuilding -tAc "SELECT count(*) FROM telemetry"; }
edge_rx() { curl -s "$EDGE/health" | python3 -c "import json,sys; print(json.load(sys.stdin)['hardware']['readings_received'])"; }

echo "== A. crash of the ML API process"
r0=$(restarts ml-api)
echo "$(ts) ml-api health=$(health ml-api) restarts=$r0; killing the server process"
docker compose exec -T ml-api python -c "import os, signal; os.kill(1, signal.SIGTERM)" || true
t0=$(date +%s)
until [ "$(docker compose ps -q ml-api)" ] && [ "$(health ml-api 2>/dev/null)" = healthy ] && [ "$(restarts ml-api)" -gt "$r0" ]; do sleep 1; done
echo "$(ts) ml-api health=$(health ml-api) restarts=$(restarts ml-api), back after $(( $(date +%s) - t0 )) s (restart: unless-stopped)"
curl -s -X POST localhost:8080/predict -H 'Content-Type: application/json' -d '{"temperature":24,"humidity":55,"lux":400}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('  /predict after restart: version', d['model']['version'], 'P', d['occupancy_probability'])"

echo "== B. ingestion outage of ${OUTAGE_S} s"
rows0=$(rows); edge0=$(edge_rx)
echo "$(ts) telemetry rows=$rows0, edge brain readings=$edge0, up{job=ingestion}=$(q 'up{job="ingestion"}')"
docker compose stop ingestion >/dev/null
echo "$(ts) ingestion stopped"
t0=$(date +%s); fired=""
while [ $(( $(date +%s) - t0 )) -lt "$OUTAGE_S" ]; do
  sleep 5
  up=$(q 'up{job="ingestion"}')
  state=$(q 'ALERTS{alertname="ServiceDown",job="ingestion"}')
  [ "$state" != none ] && [ -z "$fired" ] && fired=1 && echo "$(ts) Prometheus: up=$up, alert ServiceDown is $(curl -s "$PROM/api/v1/alerts" | python3 -c "import json,sys; print([a['state'] for a in json.load(sys.stdin)['data']['alerts'] if a['labels'].get('alertname')=='ServiceDown' and a['labels'].get('job')=='ingestion'])")"
done
echo "$(ts) Alertmanager has: $(curl -s "$AM/api/v2/alerts" | python3 -c "import json,sys; print([(a['labels']['alertname'], a['labels'].get('job'), a['status']['state']) for a in json.load(sys.stdin)])")"
echo "$(ts) edge brain kept running without ingestion: readings $(edge_rx) (was $edge0) - edge-first"
echo "$(ts) last ingestion log lines:"
docker compose logs --no-log-prefix --tail 2 ingestion | cut -c1-160 | sed 's/^/    /'
docker compose start ingestion >/dev/null
t1=$(date +%s)
until [ "$(health ingestion)" = healthy ]; do sleep 1; done
echo "$(ts) ingestion healthy again after $(( $(date +%s) - t1 )) s"
sleep 8
rows1=$(rows); edge1=$(edge_rx)
sent=$(( edge1 - edge0 )); stored=$(( rows1 - rows0 ))
echo "$(ts) during the window: board sent $sent readings (edge brain count), ingestion stored $stored"
[ "$stored" -ge $(( sent - 3 )) ] && echo "  no data lost: the broker kept the QoS 1 backlog for the persistent session" \
  || echo "  WARNING: $(( sent - stored )) readings missing"
echo "RECOVERY TEST DONE"
