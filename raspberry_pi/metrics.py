"""
Prometheus metrics for the edge brain: GET /metrics (text exposition format).

Two kinds of metrics:
  * request metrics recorded by Flask hooks (count and latency per route, status code);
  * state metrics read from the running brain at scrape time (board link, MQTT, BLE, room readings,
    models, AI switch). Reading at scrape time keeps the control loop untouched.

Every room metric has a `source` label: "physical" when Room 101's real board sent the reading,
"simulated_board" when the board simulator feeds Room 101 (container stack, tests) and "simulated" for the
digital twin's 25 rooms, so a dashboard can never present simulated values as measurements.
prometheus_client is optional on the Pi: without it /metrics answers 503 and nothing else changes.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Iterable, Optional

from flask import Flask, Response, g, request

logger = logging.getLogger("EdgeMetrics")

try:
    from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
    from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, InfoMetricFamily
    AVAILABLE = True
except ImportError:          # pragma: no cover - exercised only on a Pi without the package
    AVAILABLE = False

SKIP_LATENCY = {"/api/stream", "/metrics"}       # SSE stays open for minutes; /metrics measures itself


class BrainCollector:
    """Reads the brain's public state when Prometheus scrapes; never raises into the scrape."""

    def __init__(self, get_brain: Callable[[], object], api_version: int):
        self.get_brain = get_brain
        self.api_version = api_version

    def collect(self) -> Iterable:
        brain = self.get_brain()
        up = GaugeMetricFamily("sb_edge_up", "1 while the edge brain is running and its state is readable")
        if brain is None:
            up.add_metric([], 0)
            yield up
            return
        try:
            yield from self._collect(brain)
            up.add_metric([], 1)
        except Exception as e:          # a broken subsystem must not break the scrape
            logger.warning("metrics collection failed: %s", e)
            up.add_metric([], 0)
        yield up

    def _collect(self, brain) -> Iterable:
        info = InfoMetricFamily("sb_edge", "Edge brain build information")
        info.add_metric([], {"api_version": str(self.api_version)})
        yield info
        ai = GaugeMetricFamily("sb_edge_ai_enabled", "1 when the AI controls the rooms")
        ai.add_metric([], 1 if getattr(brain, "ai_enabled", False) else 0)
        yield ai

        # ---- board links (one per hardware room)
        real_board = {st["room_id"]: bool(st.get("real_board")) for st in brain.hardware_rooms()}
        conn = GaugeMetricFamily("sb_board_connected", "1 while the room's board is sending readings", labels=["room_id"])
        real = GaugeMetricFamily("sb_board_real", "1 when the sender is the real board (not a simulator)", labels=["room_id"])
        age = GaugeMetricFamily("sb_board_last_reading_age_seconds", "Seconds since the last board reading", labels=["room_id"])
        rx = CounterMetricFamily("sb_board_readings", "Board readings received since start", labels=["room_id"])
        for st in brain.hardware_rooms():
            rid = st["room_id"]
            conn.add_metric([rid], 1 if st.get("connected") else 0)
            real.add_metric([rid], 1 if st.get("real_board") else 0)
            if st.get("age_s") is not None:
                age.add_metric([rid], float(st["age_s"]))
            rx.add_metric([rid], float(st.get("readings_received") or 0))
        yield from (conn, real, age, rx)

        # ---- rooms (physical and simulated, labelled)
        state = brain.get_current_state()
        g_temp = GaugeMetricFamily("sb_room_temperature_celsius", "Room air temperature", labels=["room_id", "floor", "source"])
        g_rh = GaugeMetricFamily("sb_room_humidity_percent", "Room relative humidity", labels=["room_id", "floor", "source"])
        g_lux = GaugeMetricFamily("sb_room_light_lux", "Illuminance", labels=["room_id", "floor", "source"])
        g_occ = GaugeMetricFamily("sb_room_occupancy_probability", "AI's P(occupied)", labels=["room_id", "floor", "source"])
        g_pw = GaugeMetricFamily("sb_room_power_watts", "Electrical power: INA219 fan branch for the physical room, "
                                 "simulated 5R1C total for simulated rooms", labels=["room_id", "floor", "source"])
        g_fan = GaugeMetricFamily("sb_room_fan_on", "Fan relay state reported by the board", labels=["room_id", "source"])
        g_v = GaugeMetricFamily("sb_room_bus_voltage_volts", "INA219 bus voltage (fan branch)", labels=["room_id", "source"])
        g_i = GaugeMetricFamily("sb_room_current_amperes", "INA219 current (fan branch)", labels=["room_id", "source"])
        g_mq = GaugeMetricFamily("sb_room_mq135_millivolts", "MQ-135 output at the ADC (raw sensor response, not ppm)",
                                 labels=["room_id", "source"])
        g_motion = GaugeMetricFamily("sb_room_motion", "PIR presence reported by the board", labels=["room_id", "source"])
        n_rooms = {"physical": 0, "simulated_board": 0, "simulated": 0}
        for r in state.get("rooms", []):
            # physical = the real board is the sender; simulated_board = a hardware room fed by the board
            # simulator (container stack, tests); simulated = the digital twin's rooms
            if r.get("hardware"):
                source = "physical" if real_board.get(r["room_id"]) else "simulated_board"
            else:
                source = "simulated"
            n_rooms[source] += 1
            rid, floor = r["room_id"], str(r.get("floor_id", ""))
            lab = [rid, floor, source]
            s = r.get("sensors") or {}
            _add(g_temp, lab, s.get("Temperature"))
            _add(g_rh, lab, s.get("Humidity"))
            _add(g_lux, lab, s.get("Light"))
            _add(g_occ, lab, (r.get("ai") or {}).get("occupancy_probability"))
            if source != "simulated":
                pm = r.get("power_measurement") or {}
                if pm.get("power_mW") is not None:
                    g_pw.add_metric(lab, float(pm["power_mW"]) / 1000.0)
                hl = [rid, source]
                _add(g_v, hl, pm.get("voltage_v"))
                if pm.get("current_mA") is not None:
                    g_i.add_metric(hl, float(pm["current_mA"]) / 1000.0)
                ds = r.get("device_state") or {}
                if ds.get("fan_on") is not None:
                    g_fan.add_metric(hl, 1 if ds["fan_on"] else 0)
                _add(g_mq, hl, s.get("MQ135_adc_mV"))
                pir = (r.get("presence") or {}).get("pir_motion")
                if pir is not None:
                    g_motion.add_metric(hl, 1 if pir else 0)
            else:
                _add(g_pw, lab, ((r.get("energy") or {}).get("power_w")))
        yield from (g_temp, g_rh, g_lux, g_occ, g_pw, g_fan, g_v, g_i, g_mq, g_motion)
        rooms = GaugeMetricFamily("sb_twin_rooms", "Rooms in the digital twin by source", labels=["source"])
        for k, v in n_rooms.items():
            rooms.add_metric([k], v)
        yield rooms

        # ---- MQTT bridge
        mq = getattr(brain, "mqtt", None)
        en = GaugeMetricFamily("sb_mqtt_enabled", "1 when the MQTT bridge is running")
        en.add_metric([], 1 if mq is not None else 0)
        yield en
        if mq is not None:
            st = mq.status()
            c = GaugeMetricFamily("sb_mqtt_connected", "1 while connected to the broker")
            c.add_metric([], 1 if st.get("connected") else 0)
            msgs = CounterMetricFamily("sb_mqtt_messages", "MQTT bridge message counters", labels=["kind"])
            for k, v in (st.get("stats") or {}).items():
                msgs.add_metric([k], float(v))
            pend = GaugeMetricFamily("sb_mqtt_pending_acks", "Commands waiting for the board's ack")
            pend.add_metric([], float(st.get("pending_acks") or 0))
            yield from (c, msgs, pend)

        # ---- BLE gateway
        ble = getattr(brain, "ble", None)
        if ble is not None:
            st = ble.status()
            b = GaugeMetricFamily("sb_ble_connected", "1 while the BLE link to the board is up")
            b.add_metric([], 1 if st.get("connected") else 0)
            yield b

        # ---- models
        models = getattr(brain, "models", None)
        if models is not None:
            summ = models.summary()
            loaded = GaugeMetricFamily("sb_model_loaded", "1 when the model version is loaded",
                                       labels=["task", "version", "role"])
            for m in summ.get("models", []):
                if m.get("task"):
                    loaded.add_metric([m["task"], str(m.get("version")), str(m.get("role"))], 1 if m.get("loaded") else 0)
            yield loaded
            sh = summ.get("shadow") or {}
            acc = GaugeMetricFamily("sb_model_live_accuracy", "Live occupancy accuracy against the simulator's truth",
                                    labels=["model"])
            for name, key in (("learned_fusion", "candidate_vs_truth"), ("rule", "active_vs_truth")):
                _add(acc, [name], (sh.get(key) or {}).get("accuracy"))
            yield acc
            ol = summ.get("online_learning") or {}
            rows = GaugeMetricFamily("sb_model_online_buffer_rows", "Rows buffered for continual learning")
            rows.add_metric([], float(ol.get("buffer_rows") or 0))
            rounds = CounterMetricFamily("sb_model_online_rounds", "Continual-learning rounds completed")
            rounds.add_metric([], float(len(ol.get("rounds") or [])))
            yield from (rows, rounds)
            drift = ((summ.get("drift") or {}).get("real_room_inputs_vs_occupancy_rf_training") or {})
            psi = GaugeMetricFamily("sb_model_input_psi", "Population stability index of Room 101 inputs vs training",
                                    labels=["feature"])
            for f, item in (drift.get("features") or {}).items():
                _add(psi, [f], item.get("psi"))
            yield psi


def _add(fam, labels, value) -> None:
    if value is None:
        return
    try:
        fam.add_metric(labels, float(value))
    except (TypeError, ValueError):
        pass


def install(app: Flask, get_brain: Callable[[], object], api_version: int,
            registry: Optional["CollectorRegistry"] = None):
    """Add request hooks and GET /metrics to the Flask app. Returns the registry (None if unavailable)."""
    if not AVAILABLE:
        @app.route("/metrics", methods=["GET"])
        def metrics_unavailable():
            return Response("prometheus_client is not installed on this device\n", status=503, mimetype="text/plain")
        return None

    reg = registry or CollectorRegistry()
    requests_total = Counter("sb_edge_http_requests", "HTTP requests handled by the edge brain",
                             ["method", "endpoint", "status"], registry=reg)
    latency = Histogram("sb_edge_http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"],
                        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5), registry=reg)
    reg.register(BrainCollector(get_brain, api_version))

    @app.before_request
    def _start_timer():
        g._sb_t0 = time.perf_counter()

    @app.after_request
    def _record(response):
        rule = request.url_rule.rule if request.url_rule is not None else "unmatched"
        if rule == "/<path:path>":
            rule = "dashboard"              # static files: one label, not one per file
        requests_total.labels(request.method, rule, str(response.status_code)).inc()
        t0 = getattr(g, "_sb_t0", None)
        if t0 is not None and rule not in SKIP_LATENCY:
            latency.labels(request.method, rule).observe(time.perf_counter() - t0)
        return response

    @app.route("/metrics", methods=["GET"])
    def metrics():
        return Response(generate_latest(reg), mimetype=CONTENT_TYPE_LATEST)

    return reg
