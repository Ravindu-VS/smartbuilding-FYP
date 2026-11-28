# Monitoring, logging and alerting

Prometheus scrapes every service, Alertmanager routes alerts, Grafana shows five provisioned dashboards, and every
service writes one JSON object per log line. Config lives in `monitoring/`. Evidence:
[prometheus.txt](evidence/prometheus.txt), [dashboards-check.txt](evidence/dashboards-check.txt),
[logs.txt](evidence/logs.txt).

## "Is the system working?"

| Question | Where to look | Metric or endpoint |
|---|---|---|
| Is the ESP32 online? | Grafana *MQTT* → Room 101 board online | `sb_board_connected{room_id}`, `sb_board_last_reading_age_seconds`; alert `BoardOffline` |
| Is it the real board or the simulator? | *Rooms* → Data source | `sb_board_real` (1 = real ESP32-S3) |
| Is MQTT online? | *MQTT* → Edge brain ↔ broker / Ingestion ↔ broker | `sb_mqtt_connected`, `sb_ingest_mqtt_connected`; alert `MqttBridgeDisconnected` |
| Are telemetry messages arriving? | *MQTT* → messages per second | `rate(sb_ingest_messages_total[5m])`, `sb_ingest_last_message_timestamp_seconds`; alert `TelemetryStalled` |
| Is ingestion running? | *Application* → Ingestion UP | `up{job="ingestion"}`, `GET :8090/health`; alert `ServiceDown` |
| Is the database running? | *Application* → PostgreSQL reachable | `sb_ingest_db_up`, `sb_ingest_queue_depth`; alert `TelemetryDatabaseDown` |
| Is the API healthy? | *Application* → availability, 5xx | `up{job=~"edge-brain\|ml-api"}`, `sb_*_requests_total{status=~"5.."}` |
| Is the frontend running? | `GET :8001/` (the edge brain serves it) | `sb_edge_http_requests_total{endpoint="dashboard"}` |
| Is the ML service healthy? Is the model loaded? | *Machine learning* → Model loaded, Model being served | `sb_ml_model_loaded`, `sb_ml_model_info`; alert `ModelNotLoaded` |
| Are predictions being generated? | *Machine learning* → Predictions per second | `rate(sb_ml_predictions_total[5m])`, table `predictions` |
| Are containers healthy? | `docker compose ps`; *Infrastructure* → Containers | Docker health checks; cAdvisor `container_*` |
| Is the host healthy? | *Infrastructure* → Host | node-exporter; alerts `HostHighCpu`, `HostLowMemory`, `HostDiskFilling` |
| Is the Pi reachable from the cloud? | *Application* → Edge brain (Raspberry Pi) | `up{job="edge-brain-pi"}`; alert `EdgePiUnreachable` |

## Metrics

| Source | Endpoint | Main metrics |
|---|---|---|
| Edge brain | `:8001/metrics` | `sb_edge_up`, `sb_edge_http_requests_total`, `sb_edge_http_request_duration_seconds`, `sb_board_*`, `sb_mqtt_*`, `sb_ble_connected`, `sb_room_*{room_id,floor,source}`, `sb_twin_rooms{source}`, `sb_model_loaded`, `sb_model_live_accuracy`, `sb_model_input_psi` |
| ML API | `:8080/metrics` | `sb_ml_*` ([MLOPS.md](MLOPS.md#monitoring-and-drift)) |
| Ingestion | `:8090/metrics` | `sb_ingest_messages_total`, `sb_ingest_rejected_total`, `sb_ingest_rows_stored_total{table,provenance}`, `sb_ingest_duplicates_total`, `sb_ingest_db_up`, `sb_ingest_queue_depth`, `sb_ingest_db_write_seconds`, `sb_ingest_predictions_total` |
| MLflow | `:5000/metrics` | `mlflow_http_request_*` (`--expose-prometheus`) |
| Host, containers | node-exporter `:9100`, cAdvisor `:8080` | standard |

Units are SI: power in W, current in A, voltage in V. The MQ-135 is exported as its raw response in mV, never as ppm.
Every room metric carries `source`:

| `source` | Meaning |
|---|---|
| `physical` | the real board sent the reading |
| `simulated_board` | the board simulator feeds Room 101 |
| `simulated` | the digital twin's 25 rooms |

## Dashboards (Grafana, provisioned read-only)

| Dashboard | Panels |
|---|---|
| Infrastructure | Host CPU, memory, disk, network; container CPU, memory, network and age per Compose service |
| Application | Up/down per service; requests per second; p95 latency; 5xx; telemetry database: reachable, queue, rows per second, write time; alerts firing |
| MQTT and board link | Broker connections, board online, BLE; messages per second (edge brain, ingestion); rejected telemetry; last-reading age; pending acks |
| Machine learning | Model served (table), loaded, drift status; predictions per second; inference p50/p95; P(occupied) distribution; PIR agreement; PSI per feature; input means; edge live accuracy; continual learning |
| Rooms | Room 101 LIVE (data-source banner, temperature, humidity, lux, fan, PIR, power, V/I/P, MQ-135 raw); simulated rooms, kept separate (power and temperature by floor, AI-occupied rooms); latest rows from PostgreSQL |

* **Generated, not hand-edited.** The dashboards come from `monitoring/grafana/build_dashboards.py`; CI fails if
  the committed JSON differs from the generator's output.
* **Every query checked.** `python scripts/check_dashboards.py` runs all 78 queries against a live Prometheus.
  Recorded: 0 failures. The 9 that return nothing are legitimate (BLE exists only on the Pi; no 5xx errors
  happened; the simulator sends no V/I).

## Alerts

`monitoring/prometheus/alerts.yml` holds 15 rules, checked by promtool:

| Group | Rules |
|---|---|
| Availability | ServiceDown, EdgePiUnreachable |
| Edge | BoardOffline, MqttBridgeDisconnected, MqttRejectsHigh |
| Ingestion | TelemetryDatabaseDown, TelemetryStalled, IngestQueueBacklog |
| ML | ModelNotLoaded, InferenceSlow, MlApiErrors, InputDrift |
| Host | HostHighCpu, HostLowMemory, HostDiskFilling |

Alertmanager (`monitoring/alertmanager/alertmanager.yml`):
* groups alerts by name and job, and repeats critical alerts hourly;
* inhibits warnings when the same job's `ServiceDown` is firing;
* by default records alerts only. Add a webhook, Slack or e-mail receiver with `*_file` secrets for notifications.

Recorded during the recovery test: `ServiceDown{job="ingestion"}` went pending within 25 s of the outage and was
active in Alertmanager at 100 s.

## Logs

* **Format.** Every Python service uses `sbops.logs` (the edge brain with `LOG_FORMAT=json`): one JSON object per
  line with `ts` (UTC), `level`, `service`, `logger`, `msg` and, when relevant, `room_id`, `msg_id`, `model_version`,
  `request_id`, `topic`, `status`, `duration_ms`.
* **Secrets.** Keys that look like secrets are written as `***`; passwords and tokens are never logged (tested).
* **Where logs go.** Docker keeps them (json-file, 10 MB × 3): `docker compose logs -f <service>`. Kubernetes:
  `kubectl -n smartbuilding logs deploy/<service>`. On the Pi: `journalctl -u edge-brain`.
* **Searching.** The lines are JSON, so `docker compose logs --no-log-prefix ingestion | jq 'select(.level=="WARNING")'` works.

## Monitoring the Raspberry Pi

The Pi runs the edge brain natively, and `/metrics` is part of it (`pip install prometheus-client==0.26.0` on the Pi).
1. Put the Pi's address in `monitoring/prometheus/targets/edge-pi.yml`.
2. Prometheus picks it up within a minute (`file_sd`).
3. From the cloud, reach it over the VPN or SSH tunnel you use for the bridge; do not open :8001 to the Internet.

## Known limitation

cAdvisor cannot map containers on hosts where Docker uses the containerd image store (Docker 29 default):
"failed to identify the read-write layer ID". Container panels then stay empty. The fix is on the host: set
`"features": {"containerd-snapshotter": false}` in `/etc/docker/daemon.json` and restart Docker.
