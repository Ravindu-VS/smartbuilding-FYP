#!/usr/bin/env python3
"""
Generates the Grafana dashboards in monitoring/grafana/dashboards/ (provisioned read-only into Grafana).

    python monitoring/grafana/build_dashboards.py

One function per dashboard; panels are built from small helpers so every query, unit and threshold is visible
in one place. Physical and simulated rooms are always separate panels with the source in the title.
"""
import json
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards")
PROM = {"type": "prometheus", "uid": "prometheus"}
PG = {"type": "grafana-postgresql-datasource", "uid": "telemetry-db"}


class Board:
    def __init__(self, uid, title, tags, description):
        self.d = {"uid": uid, "title": title, "tags": ["smart-building"] + tags, "description": description,
                  "timezone": "browser", "schemaVersion": 39, "version": 1, "editable": False,
                  "time": {"from": "now-1h", "to": "now"}, "refresh": "15s", "panels": [],
                  "templating": {"list": []}, "annotations": {"list": []}}
        self.y = 0
        self.x = 0
        self.row_h = 0
        self.next_id = 1

    def row(self, title):
        self._newline()
        self.d["panels"].append({"type": "row", "title": title, "id": self._id(), "collapsed": False,
                                 "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}, "panels": []})
        self.y += 1

    def _id(self):
        self.next_id += 1
        return self.next_id - 1

    def _newline(self):
        if self.x:
            self.y += self.row_h
            self.x, self.row_h = 0, 0

    def add(self, panel, w=8, h=8):
        if self.x + w > 24:
            self._newline()
        panel["id"] = self._id()
        panel["gridPos"] = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.d["panels"].append(panel)
        self.x += w
        self.row_h = max(self.row_h, h)

    def save(self):
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, f"{self.d['uid']}.json")
        with open(path, "w") as f:
            json.dump(self.d, f, indent=2)
            f.write("\n")
        return path


def t(expr, legend=""):
    return {"datasource": PROM, "expr": expr, "legendFormat": legend, "refId": "A"}


def targets(*pairs):
    out = []
    for i, (expr, legend) in enumerate(pairs):
        q = t(expr, legend)
        q["refId"] = chr(65 + i)
        out.append(q)
    return out


def ts(title, qs, unit="short", desc="", minv=None, maxv=None, stack=False):
    p = {"type": "timeseries", "title": title, "description": desc, "datasource": PROM, "targets": qs,
         "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 10,
                                                               "stacking": {"mode": "normal" if stack else "none"}}},
                         "overrides": []},
         "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}}
    if minv is not None:
        p["fieldConfig"]["defaults"]["min"] = minv
    if maxv is not None:
        p["fieldConfig"]["defaults"]["max"] = maxv
    return p


def stat(title, qs, unit="short", desc="", steps=None, mappings=None, decimals=None):
    p = {"type": "stat", "title": title, "description": desc, "datasource": PROM, "targets": qs,
         "fieldConfig": {"defaults": {"unit": unit, "mappings": mappings or [],
                                      "thresholds": {"mode": "absolute", "steps": steps or [
                                          {"color": "green", "value": None}]}}, "overrides": []},
         "options": {"colorMode": "background", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}}}
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    return p


UPDOWN = [{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}]
ONOFF = [{"type": "value", "options": {"0": {"text": "OFF", "color": "text"}, "1": {"text": "ON", "color": "green"}}}]
RED0 = [{"color": "red", "value": None}, {"color": "green", "value": 1}]


# ----------------------------------------------------------------------------- dashboards
def infrastructure():
    b = Board("sb-infrastructure", "Smart Building · Infrastructure", ["infrastructure"],
              "Host (node-exporter) and containers (cAdvisor).")
    b.row("Host")
    b.add(stat("CPU busy", [t('100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[$__rate_interval])))')],
               "percent", steps=[{"color": "green", "value": None}, {"color": "orange", "value": 70},
                                 {"color": "red", "value": 90}]), 6, 4)
    b.add(stat("Memory used", [t("100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)")],
               "percent", steps=[{"color": "green", "value": None}, {"color": "orange", "value": 80},
                                 {"color": "red", "value": 90}]), 6, 4)
    b.add(stat("Root disk free", [t('100 * node_filesystem_avail_bytes{mountpoint="/"} / '
                                    'node_filesystem_size_bytes{mountpoint="/"}')], "percent",
               steps=[{"color": "red", "value": None}, {"color": "orange", "value": 10},
                      {"color": "green", "value": 20}]), 6, 4)
    b.add(stat("Uptime", [t("time() - node_boot_time_seconds")], "s"), 6, 4)
    b.add(ts("CPU by mode", [t('sum by (mode) (rate(node_cpu_seconds_total{mode!="idle"}[$__rate_interval]))',
                               "{{mode}}")], "percentunit", stack=True), 8)
    b.add(ts("Memory", targets(("node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes", "used"),
                               ("node_memory_MemTotal_bytes", "total")), "bytes"), 8)
    b.add(ts("Network", targets(('sum(rate(node_network_receive_bytes_total{device!~"lo|veth.*|docker.*|br-.*"}'
                                 '[$__rate_interval]))', "receive"),
                                ('sum(rate(node_network_transmit_bytes_total{device!~"lo|veth.*|docker.*|br-.*"}'
                                 '[$__rate_interval]))', "transmit")), "Bps"), 8)
    b.row("Containers")
    b.add(ts("CPU per service", [t('sum by (container_label_com_docker_compose_service) '
                                   '(rate(container_cpu_usage_seconds_total{container_label_com_docker_compose_service!=""}'
                                   '[$__rate_interval]))', "{{container_label_com_docker_compose_service}}")],
             "percentunit"), 12)
    b.add(ts("Memory per service", [t('sum by (container_label_com_docker_compose_service) '
                                      '(container_memory_working_set_bytes{container_label_com_docker_compose_service!=""})',
                                      "{{container_label_com_docker_compose_service}}")], "bytes"), 12)
    b.add(ts("Network per service", [t('sum by (container_label_com_docker_compose_service) '
                                       '(rate(container_network_receive_bytes_total{container_label_com_docker_compose_service!=""}'
                                       '[$__rate_interval]))', "{{container_label_com_docker_compose_service}} rx")],
             "Bps"), 12)
    b.add(ts("Container age (restarts reset it)", [t('time() - max by (container_label_com_docker_compose_service) '
                                                     '(container_start_time_seconds{container_label_com_docker_compose_service!=""})',
                                                     "{{container_label_com_docker_compose_service}}")], "s"), 12)
    return b


def application():
    b = Board("sb-application", "Smart Building · Application", ["application"],
              "Availability, traffic, latency and errors of the edge brain, ML API, ingestion and MLflow.")
    b.row("Availability")
    for job, title in (("edge-brain", "Edge brain (container)"), ("edge-brain-pi", "Edge brain (Raspberry Pi)"),
                       ("ml-api", "ML API"), ("ingestion", "Ingestion"), ("mlflow", "MLflow")):
        b.add(stat(title, [t(f'max(up{{job="{job}"}})')], mappings=UPDOWN, steps=RED0), 24 // 5 if job != "mlflow" else 4, 4)
    b.row("Traffic and latency")
    b.add(ts("Requests per second", targets(
        ('sum by (endpoint) (rate(sb_edge_http_requests_total[$__rate_interval]))', "edge {{endpoint}}"),
        ('sum by (endpoint) (rate(sb_ml_requests_total{endpoint!="/metrics"}[$__rate_interval]))', "ml {{endpoint}}")),
        "reqps"), 12)
    b.add(ts("p95 latency", targets(
        ('histogram_quantile(0.95, sum by (le, endpoint) (rate(sb_edge_http_request_duration_seconds_bucket'
         '[$__rate_interval])))', "edge {{endpoint}}"),
        ('histogram_quantile(0.95, sum by (le, endpoint) (rate(sb_ml_request_duration_seconds_bucket'
         '[$__rate_interval])))', "ml {{endpoint}}")), "s"), 12)
    b.add(ts("Errors (HTTP 5xx) per second", targets(
        ('sum(rate(sb_edge_http_requests_total{status=~"5.."}[$__rate_interval])) or vector(0)', "edge brain"),
        ('sum(rate(sb_ml_requests_total{status=~"5.."}[$__rate_interval])) or vector(0)', "ML API"),
        ('sum(rate(sb_ml_errors_total[$__rate_interval])) or vector(0)', "ML errors (all types)")), "reqps"), 12)
    b.row("Telemetry database")
    b.add(stat("PostgreSQL reachable", [t("max(sb_ingest_db_up)")], mappings=UPDOWN, steps=RED0), 6, 4)
    b.add(stat("Queue depth", [t("max(sb_ingest_queue_depth)")], steps=[
        {"color": "green", "value": None}, {"color": "orange", "value": 100}, {"color": "red", "value": 1000}]), 6, 4)
    b.add(ts("Rows written per second", [t('sum by (table, provenance) (rate(sb_ingest_rows_stored_total'
                                           '[$__rate_interval]))', "{{table}} {{provenance}}")], "rowsps"), 12)
    b.add(ts("DB write time p95", [t("histogram_quantile(0.95, sum by (le) (rate(sb_ingest_db_write_seconds_bucket"
                                     "[$__rate_interval])))", "p95")], "s"), 12)
    b.add(ts("Alerts firing", [t('sum by (alertname) (ALERTS{alertstate="firing"})', "{{alertname}}")]), 12)
    return b


def mqtt():
    b = Board("sb-mqtt", "Smart Building · MQTT and board link", ["mqtt"],
              "Broker connections, telemetry flow and the Room 101 board link (MQTT + Bluetooth LE).")
    b.row("Connections")
    b.add(stat("Edge brain ↔ broker", [t("max(sb_mqtt_connected)")], mappings=UPDOWN, steps=RED0), 6, 4)
    b.add(stat("Ingestion ↔ broker", [t("max(sb_ingest_mqtt_connected)")], mappings=UPDOWN, steps=RED0), 6, 4)
    b.add(stat("Room 101 board online", [t("max(sb_board_connected)")], mappings=UPDOWN, steps=RED0), 6, 4)
    b.add(stat("Bluetooth LE link", [t("max(sb_ble_connected)")], mappings=UPDOWN, steps=RED0,
               desc="Only on the Raspberry Pi (BLE gateway)."), 6, 4)
    b.row("Telemetry flow")
    b.add(ts("Edge brain: messages per second", [t('sum by (kind) (rate(sb_mqtt_messages_total[$__rate_interval]))',
                                                   "{{kind}}")], "short"), 12)
    b.add(ts("Ingestion: messages per second", [t('sum by (kind) (rate(sb_ingest_messages_total[$__rate_interval]))',
                                                  "{{kind}}")], "short"), 12)
    b.add(ts("Rejected telemetry", targets(
        ('sum by (reason) (rate(sb_ingest_rejected_total[$__rate_interval]))', "ingestion {{reason}}"),
        ('sum(rate(sb_ingest_rejected_total[$__rate_interval])) or vector(0)', "ingestion (all)"),
        ('sum(rate(sb_mqtt_messages_total{kind="rejected"}[$__rate_interval])) or vector(0)', "edge brain")), "short"), 8)
    b.add(ts("Seconds since the last board reading", [t("max by (room_id) (sb_board_last_reading_age_seconds)",
                                                        "{{room_id}}")], "s"), 8)
    b.add(ts("Commands waiting for an ack", [t("max(sb_mqtt_pending_acks)", "pending")]), 8)
    return b


def ml():
    b = Board("sb-ml", "Smart Building · Machine learning", ["ml"],
              "ML API (MLflow production model) and the edge brain's live models.")
    b.row("Model")
    b.add({"type": "table", "title": "Model being served", "datasource": PROM,
           "targets": [dict(t("max by (name, version, alias, run_id) (sb_ml_model_info)"), format="table",
                            instant=True)],
           "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True, "Value": True}}}],
           "fieldConfig": {"defaults": {}, "overrides": []}, "options": {"showHeader": True}}, 12, 4)
    b.add(stat("Model loaded", [t("max(sb_ml_model_loaded)")], mappings=UPDOWN, steps=RED0), 6, 4)
    b.add(stat("Input drift", [t("max(sb_ml_drift_status)")], mappings=[{"type": "value", "options": {
        "-1": {"text": "not enough data", "color": "text"}, "0": {"text": "stable", "color": "green"},
        "1": {"text": "moderate", "color": "orange"}, "2": {"text": "significant", "color": "red"}}}]), 6, 4)
    b.row("Predictions")
    b.add(ts("Predictions per second", [t('sum by (outcome) (rate(sb_ml_predictions_total[$__rate_interval]))',
                                          "{{outcome}}")], "short", stack=True), 8)
    b.add(ts("Inference time", targets(
        ("histogram_quantile(0.5, sum by (le) (rate(sb_ml_inference_duration_seconds_bucket[$__rate_interval])))", "p50"),
        ("histogram_quantile(0.95, sum by (le) (rate(sb_ml_inference_duration_seconds_bucket[$__rate_interval])))", "p95")),
        "s"), 8)
    b.add({"type": "bargauge", "title": "P(occupied) distribution (last hour)", "datasource": PROM,
           "targets": [dict(t("sum by (le) (increase(sb_ml_prediction_probability_bucket[1h]))", "{{le}}"),
                            format="heatmap", instant=True)],
           "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
           "options": {"orientation": "vertical", "displayMode": "basic"}}, 8)
    b.add(ts("PIR agrees with the model", [t('sum(rate(sb_ml_pir_agreement_total{agree="yes"}[$__rate_interval])) / '
                                             'sum(rate(sb_ml_pir_agreement_total[$__rate_interval]))', "agreement")],
             "percentunit", desc="Room 101 has no occupancy ground truth; PIR agreement is the live proxy.",
             minv=0, maxv=1), 8)
    b.add(ts("Input drift (PSI per feature)", [t("sb_ml_drift_psi", "{{feature}}")], "short",
             desc="< 0.10 stable, 0.10–0.25 moderate, > 0.25 significant"), 8)
    b.add(ts("Rolling input means", [t("sb_ml_input_mean", "{{feature}}")]), 8)
    b.row("Edge brain models (Raspberry Pi / twin)")
    b.add(ts("Live occupancy accuracy (simulated rooms vs simulator truth)", [t("sb_model_live_accuracy", "{{model}}")],
             "percentunit", minv=0.5, maxv=1), 12)
    b.add(ts("Continual learning", targets(("sb_model_online_buffer_rows", "buffer rows"),
                                           ("sb_model_online_rounds_total", "rounds"))), 12)
    return b


def building():
    b = Board("sb-building", "Smart Building · Rooms", ["building"],
              "Room 101 (physical, measured by the board) and the 25 simulated rooms of the digital twin, "
              "never mixed in one panel.")
    phys = 'source=~"physical|simulated_board"'
    b.row("Room 101 · LIVE board (physical when the real board sends; simulator otherwise)")
    b.add(stat("Data source", [t("max(sb_board_real)")], mappings=[{"type": "value", "options": {
        "1": {"text": "REAL BOARD (physical)", "color": "green"},
        "0": {"text": "SIMULATOR (not a measurement)", "color": "orange"}}}],
        desc="sb_board_real: 1 when the sender is the real ESP32-S3 board"), 24, 3)
    b.add(stat("Temperature", [t(f"max(sb_room_temperature_celsius{{{phys}}})")], "celsius", decimals=1), 4, 4)
    b.add(stat("Humidity", [t(f"max(sb_room_humidity_percent{{{phys}}})")], "percent", decimals=0), 4, 4)
    b.add(stat("Light", [t(f"max(sb_room_light_lux{{{phys}}})")], "lux", decimals=0), 4, 4)
    b.add(stat("Fan", [t(f"max(sb_room_fan_on{{{phys}}})")], mappings=ONOFF), 4, 4)
    b.add(stat("Motion (PIR)", [t(f"max(sb_room_motion{{{phys}}})")], mappings=ONOFF), 4, 4)
    b.add(stat("Fan power (INA219)", [t(f"max(sb_room_power_watts{{{phys}}})")], "watt", decimals=2), 4, 4)
    b.add(ts("Temperature and humidity", targets((f"sb_room_temperature_celsius{{{phys}}}", "°C ({{source}})"),
                                                 (f"sb_room_humidity_percent{{{phys}}}", "% RH ({{source}})"))), 8)
    b.add(ts("Light and occupancy", targets((f"sb_room_light_lux{{{phys}}}", "lux ({{source}})"),
                                            (f"sb_room_occupancy_probability{{{phys}}} * 1000",
                                             "P(occupied) × 1000"))), 8)
    b.add(ts("Fan branch: power, current, voltage", targets((f"sb_room_power_watts{{{phys}}}", "W ({{source}})"),
                                                            (f"sb_room_current_amperes{{{phys}}}", "A {{source}}"),
                                                            (f"sb_room_bus_voltage_volts{{{phys}}}", "V {{source}}"))), 8)
    b.add(ts("Fan relay and PIR", targets((f"sb_room_fan_on{{{phys}}}", "fan on ({{source}})"), (f"sb_room_motion{{{phys}}}", "motion ({{source}})")),
             minv=0, maxv=1), 12)
    b.add(ts("MQ-135 raw response", [t(f"sb_room_mq135_millivolts{{{phys}}}", "mV at ADC ({{source}})")], "mvolt",
             desc="Raw sensor response. The MQ-135 is not a calibrated ppm sensor."), 12)
    b.row("Simulated rooms · digital twin (not measurements)")
    sim = 'source="simulated"'
    b.add(stat("Simulated rooms", [t('sum(sb_twin_rooms{source="simulated"})')]), 4, 4)
    b.add(stat("Simulated building power", [t(f"sum(sb_room_power_watts{{{sim}}})")], "watt", decimals=0), 5, 4)
    b.add(stat("Mean simulated temperature", [t(f"avg(sb_room_temperature_celsius{{{sim}}})")], "celsius",
               decimals=1), 5, 4)
    b.add(stat("Rooms the AI thinks are occupied", [t(f"count(sb_room_occupancy_probability{{{sim}}} > 0.5)")]), 5, 4)
    b.add(stat("AI control", [t("max(sb_edge_ai_enabled)")], mappings=ONOFF), 5, 4)
    b.add(ts("Simulated power by floor", [t(f"sum by (floor) (sb_room_power_watts{{{sim}}})", "floor {{floor}}")],
             "watt", stack=True), 12)
    b.add(ts("Simulated temperature by floor", [t(f"avg by (floor) (sb_room_temperature_celsius{{{sim}}})",
                                                  "floor {{floor}}")], "celsius"), 12)
    b.row("Telemetry database (PostgreSQL)")
    b.add({"type": "table", "title": "Latest stored readings", "datasource": PG,
           "targets": [{"datasource": PG, "refId": "A", "format": "table", "rawQuery": True, "editorMode": "code",
                        "rawSql": "SELECT received_at, room_id, provenance, temperature, humidity, lux, motion, "
                                  "power_mw, fan_on FROM telemetry ORDER BY received_at DESC LIMIT 20"}],
           "fieldConfig": {"defaults": {}, "overrides": []}, "options": {"showHeader": True}}, 24, 9)
    return b


def main():
    for fn in (infrastructure, application, mqtt, ml, building):
        print(fn().save())


if __name__ == "__main__":
    main()
